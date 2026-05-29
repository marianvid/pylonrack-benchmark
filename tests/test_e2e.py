"""test_e2e.py — End-to-end backend smoke test.

Runs a minimal calibration suite against a small model (Llama 3.2-1B) with
the "quick" budget. Bypasses the WebSocket layer — calls SuiteRunner directly.

Run:
    python3 tests/test_e2e.py

Output:
    Live progress + final winners + path to results file.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Make parent dir importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg_module
from model_scanner import scan
from results_store import ResultsStore
from suite_runner import SuiteRunner


SMALL_MODELS_HINTS = [
    "Llama-3.2-1B-Instruct-Q4_K_M",
    "Qwen3.5-4B-Q3_K_S",
]


async def main() -> None:
    cfg = cfg_module.load()
    print(f"llama_bin: {cfg.bin_path}")
    print(f"hf_cache:  {cfg.hf_cache_path}")
    print(f"results:   {cfg.results_path}")
    print()

    all_models = scan(cfg.hf_cache_path)
    selected = []
    for hint in SMALL_MODELS_HINTS:
        m = next((mm for mm in all_models if hint in mm.full_path), None)
        if m:
            selected.append((m.full_path, m.size_gb))
            print(f"Selected: {m.display_name} ({m.size_gb} GB)")

    if not selected:
        print("ERROR: No small model found for testing.")
        print("Available models:")
        for m in all_models[:10]:
            print(f"  {m.full_path}")
        sys.exit(1)

    print()
    store = ResultsStore(cfg.results_path)

    async def notify(event: dict) -> None:
        t = event.get("type", "")
        d = event.get("data", {})
        if t == "log":
            line = d.get("line", "")
            if line:
                short = line[:200] if len(line) > 200 else line
                print(f"  [log] {short}")
        elif t == "suite_started":
            print(f"=== SUITE STARTED ===")
            print(f"  suite_id: {d.get('suite_id')}")
            print(f"  total_runs: {d.get('total_runs')}")
            print(f"  eta: {d.get('eta_seconds')}s")
            print()
        elif t == "suite_progress":
            idx = d.get("run_index", 0)
            tot = d.get("total_runs", 0)
            cur = d.get("current", {})
            print(f"--- Run {idx + 1}/{tot}: {cur.get('label', '?')} "
                  f"profile={cur.get('profile')} prompt={cur.get('prompt_name')} ---")
        elif t == "run_complete":
            run = d.get("run", {})
            status = run.get("status")
            if status == "ok":
                agg = run.get("aggregate", {})
                if run.get("profile") == "single":
                    print(f"  OK decode={agg.get('decode_tok_s', 0):.1f} t/s · "
                          f"prefill={agg.get('prefill_tok_s', 0):.0f} t/s · "
                          f"TTFT={agg.get('ttft_ms', 0):.0f}ms")
                else:
                    print(f"  OK aggregate={agg.get('aggregate_tok_s', 0):.1f} t/s · "
                          f"per_req={agg.get('per_request_decode', 0):.1f} t/s · "
                          f"TTFT={agg.get('median_ttft_ms', 0):.0f}ms")
            else:
                print(f"  FAIL {status} - {run.get('error', '?')}")
            print()
        elif t == "suite_complete":
            print()
            print("=== SUITE COMPLETE ===")
            print(f"  duration: {d.get('duration_sec')}s")
            print(f"  winners:")
            print(json.dumps(d.get("winners", {}), indent=4))
        elif t == "suite_aborted":
            print(f"!! SUITE ABORTED: {d.get('error', 'unknown')}")

    runner = SuiteRunner(
        llama_bin      = cfg.bin_path,
        bench_port     = cfg.bench_port,
        store          = store,
        notify         = notify,
        n_predict      = 64,
        runs_per_combo = 2,
    )

    result = await runner.start(
        selected_models = selected,
        profiles        = ["single", "throughput"],
        budget          = "quick",
        mode            = "auto",
    )

    if not result.get("ok"):
        print(f"Failed to start suite: {result}")
        sys.exit(1)

    print(f"Suite started: {result['suite_id']}, total_runs={result['total_runs']}")

    while runner.is_running:
        await asyncio.sleep(0.5)

    print()
    print(f"Results file: {cfg.results_path}")
    if cfg.results_path.exists():
        print(f"File size: {cfg.results_path.stat().st_size} bytes")


if __name__ == "__main__":
    asyncio.run(main())
