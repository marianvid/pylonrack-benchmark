"""benchmark_runner.py — Run a single llama-server benchmark.

Lifecycle:
  1. Kill any stale process on bench_port
  2. Start llama-server with benchmark params
  3. Wait for readiness
  4. Fire N parallel chat/completions requests
  5. Parse throughput
  6. Stop llama-server
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import aiohttp
import psutil

from config import AppConfig

log = logging.getLogger(__name__)

READY_TIMEOUT  = 90   # seconds
RESULT_RE = re.compile(
    r"\[PARALLEL\s+\d+\]\s+Total Tokens:\s*(\d+)\s*\|"
    r"\s*Time:\s*([\d.]+)s?\s*\|"
    r"\s*Throughput:\s*([\d.]+)\s*tok/s",
    re.IGNORECASE,
)

TEST_PROMPT = (
    "Explain the importance of 400GB/s memory bandwidth for LLM "
    "inference on Apple Silicon in 150 words."
)


@dataclass
class BenchmarkResult:
    tok_s:    float
    tokens:   int
    elapsed:  float
    parallel: int


class BenchmarkRunner:
    """Manages one benchmark run: start server → measure → stop server."""

    def __init__(self, cfg: AppConfig, log_cb: Callable[[str], None] | None = None) -> None:
        self._cfg    = cfg
        self._log_cb = log_cb or (lambda line: log.info("[bench] %s", line))

    def run(self, model_path: str, parallel: int, params: dict,
            prompt: str) -> BenchmarkResult | None:
        """Synchronous blocking run. Returns result or None on failure."""
        self._emit(f"Starting llama-server on port {self._cfg.bench_port}…")
        self._kill_stale()

        proc = self._start_server(model_path, params)
        if not proc:
            return None

        try:
            if not self._wait_ready(proc):
                self._emit("ERROR: server did not become ready")
                return None

            self._emit(f"Server ready — running {parallel} parallel requests…")
            result = asyncio.run(self._fire_requests(parallel, prompt))
            if result:
                self._emit(
                    f"Result: {result.tok_s:.1f} tok/s  "
                    f"{result.tokens} tokens  {result.elapsed:.2f}s"
                )
            return result

        finally:
            self._emit("Stopping llama-server…")
            self._stop(proc)
            self._emit("Done.")

    # ------------------------------------------------------------------

    def _build_cmd(self, model_path: str, params: dict) -> list[str]:
        cmd = [
            str(self._cfg.bin_path),
            "--host",         "127.0.0.1",
            "--port",         str(self._cfg.bench_port),
            "-m",             model_path,
            "--ctx-size",     str(params.get("ctx_size",    32768)),
            "--n-gpu-layers", str(params.get("n_gpu_layers", 99)),
            "--parallel",     str(params.get("parallel",    1)),
            "--threads",      str(params.get("threads",     8)),
            "--batch-size",   str(params.get("batch_size",  512)),
            "--ubatch-size",  str(params.get("ubatch_size", 256)),
            "--metrics",
        ]
        if params.get("cache_reuse"):
            cmd += ["--cache-reuse", str(params["cache_reuse"])]
        if params.get("flash_attn"):
            cmd += ["--flash-attn", "on"]
        if params.get("cont_batching"):
            cmd += ["--cont-batching"]
        if params.get("reasoning_budget") is not None:
            cmd += ["--reasoning-budget", str(params["reasoning_budget"])]
        if params.get("enable_thinking") is not None:
            val = "true" if params["enable_thinking"] else "false"
            cmd += ["--chat-template-kwargs", f'{{"enable_thinking":{val}}}']
        return cmd

    def _start_server(self, model_path: str, params: dict) -> subprocess.Popen | None:
        cmd = self._build_cmd(model_path, params)
        self._emit(" ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(self._cfg.bin_path.parent),
            )
            threading.Thread(
                target=self._drain, args=(proc.stdout,), daemon=True
            ).start()
            return proc
        except Exception as exc:
            self._emit(f"ERROR: {exc}")
            return None

    def _wait_ready(self, proc: subprocess.Popen) -> bool:
        url      = f"http://127.0.0.1:{self._cfg.bench_port}/health"
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                import requests
                if requests.get(url, timeout=2).status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False

    async def _fire_requests(self, parallel: int, prompt: str) -> BenchmarkResult | None:
        url     = f"http://127.0.0.1:{self._cfg.bench_port}/v1/chat/completions"
        payload = {
            "model":       "test-model",
            "messages":    [{"role": "user", "content": prompt}],
            "max_tokens":  150,
            "temperature": 0.1,
        }

        async def one(session: aiohttp.ClientSession):
            t0 = time.perf_counter()
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return {
                        "gen_tokens": data.get("usage", {}).get("completion_tokens", 0),
                        "duration":   time.perf_counter() - t0,
                    }
            except Exception:
                return None

        t_wall_start = time.perf_counter()
        async with aiohttp.ClientSession() as session:
            results = [r for r in await asyncio.gather(*[one(session) for _ in range(parallel)]) if r]
        elapsed = time.perf_counter() - t_wall_start

        if not results:
            return None

        total_tokens = sum(r["gen_tokens"] for r in results)
        tok_s        = total_tokens / elapsed if elapsed > 0 else 0.0
        return BenchmarkResult(tok_s=tok_s, tokens=total_tokens,
                               elapsed=round(elapsed, 2), parallel=parallel)

    def _kill_stale(self) -> None:
        port = self._cfg.bench_port
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr.port == port and conn.status == "LISTEN" and conn.pid:
                    try:
                        psutil.Process(conn.pid).terminate()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(0.3)

    @staticmethod
    def _stop(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _drain(self, pipe) -> None:
        for raw in pipe:
            line = raw.decode(errors="replace").rstrip()
            if line:
                self._emit(line)

    def _emit(self, line: str) -> None:
        self._log_cb(line)
