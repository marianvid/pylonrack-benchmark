"""server.py — PylonRack slot application for llama.cpp benchmarking.

Controls:
  - model_select  (dropdown) — select GGUF model
  - parallel      (dropdown) — number of parallel requests [1, 2, 4, 8, 16, 24]
  - run           (button)   — run benchmark
  - status_label  (label)    — current state / last result

The body panel is empty (no ui_url) — all interaction via rack controls.
Results and run history are shown in the rack log panel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import websockets
from websockets import ServerConnection

import config as cfg_module
from model_scanner import GGUFModel, scan
from benchmark_runner import BenchmarkRunner
from results_store import ResultsStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

PARALLEL_OPTIONS = ["1", "2", "4", "8", "16", "24"]


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.cfg              = cfg_module.load()
        self.store            = ResultsStore(self.cfg.results_path)
        self.models:    list[GGUFModel] = []
        self.selected_model:  GGUFModel | None = None
        self.selected_parallel: int = 16
        self.running:         bool = False
        self.log_lines:       list[str] = []

    def refresh_models(self) -> None:
        self.models = scan(self.cfg.hf_cache_path)
        if self.models and self.selected_model is None:
            self.selected_model = self.models[0]

    def add_log(self, line: str) -> None:
        self.log_lines.append(line)
        if len(self.log_lines) > 500:
            self.log_lines = self.log_lines[-500:]


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _manifest() -> dict:
    return {
        "type":    "manifest",
        "name":    "Benchmark",
        "version": "1.0",
        "heartbeat_interval": 5,
        "controls": [
            {"id": "model_select", "type": "dropdown", "label": "Model"},
            {"id": "parallel",     "type": "dropdown", "label": "Parallel"},
            {"id": "run",          "type": "button",   "label": "Run",  "style": "primary"},
            {"id": "status_label", "type": "label",    "value": "Idle", "style": "default"},
        ],
    }


def _controls_update(state: AppState) -> dict:
    return {
        "type": "controls_update",
        "controls": [
            {
                "id":    "run",
                "label": "Running…" if state.running else "Run",
                "style": "secondary" if state.running else "primary",
            },
            {
                "id":    "status_label",
                "value": "Running…" if state.running else "Idle",
                "style": "warning" if state.running else "default",
            },
        ],
    }


def _pong(state: AppState) -> dict:
    return {
        "type":    "pong",
        "status":  "warning" if state.running else "running",
        "message": "Benchmark running…" if state.running else "Ready",
    }


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

class SlotHandler:
    def __init__(self, state: AppState) -> None:
        self._state = state

    async def handle(self, ws: ServerConnection) -> None:
        log.info("Rack connected from %s", ws.remote_address)
        try:
            async for raw in ws:
                await self._dispatch(ws, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        log.info("Rack disconnected")

    async def _dispatch(self, ws: ServerConnection, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        t = msg.get("type", "")

        if t == "manifest":
            await self._send(ws, _manifest())
            await self._send(ws, _controls_update(self._state))

        elif t == "ping":
            await self._send(ws, _pong(self._state))

        elif t == "control_data":
            await self._handle_control_data(ws, msg)

        elif t == "action":
            await self._handle_action(ws, msg)

        elif t == "log_request":
            n = msg.get("lines", 50)
            lines = self._state.log_lines[-n:]
            await self._send(ws, {"type": "log_response", "lines": lines, "total": len(self._state.log_lines)})

        elif t == "shutdown":
            pass  # benchmark has no persistent process to stop

    async def _handle_control_data(self, ws: ServerConnection, msg: dict) -> None:
        cid = msg.get("control_id", "")
        if cid == "model_select":
            self._state.refresh_models()
            await self._send(ws, {
                "type":       "control_data",
                "control_id": "model_select",
                "items":      [m.display_name for m in self._state.models],
            })
        elif cid == "parallel":
            await self._send(ws, {
                "type":       "control_data",
                "control_id": "parallel",
                "items":      PARALLEL_OPTIONS,
            })

    async def _handle_action(self, ws: ServerConnection, msg: dict) -> None:
        cid   = msg.get("control_id", "")
        value = msg.get("value")

        if cid == "model_select" and value:
            match = next((m for m in self._state.models if m.display_name == value), None)
            if match:
                self._state.selected_model = match
                self._state.add_log(f"Model selected: {match.display_name}")

        elif cid == "parallel" and value:
            try:
                self._state.selected_parallel = int(value)
            except ValueError:
                pass

        elif cid == "run":
            await self._handle_run(ws)

    async def _handle_run(self, ws: ServerConnection) -> None:
        if self._state.running:
            return

        model = self._state.selected_model
        if not model:
            self._state.refresh_models()
            model = self._state.selected_model
        if not model:
            await self._send(ws, {
                "type": "controls_update",
                "controls": [{"id": "status_label", "value": "No model selected", "style": "error"}],
            })
            return

        self._state.running = True
        await self._send(ws, _controls_update(self._state))

        parallel = self._state.selected_parallel
        params   = dict(self._state.cfg.params)
        params["parallel"] = parallel
        prompt   = self._state.cfg.prompt

        self._state.add_log(f"--- Benchmark: {model.display_name} / parallel={parallel} ---")

        def log_cb(line: str) -> None:
            self._state.add_log(line)

        loop   = asyncio.get_event_loop()
        runner = BenchmarkRunner(self._state.cfg, log_cb)
        result = await loop.run_in_executor(
            None, runner.run, model.full_path, parallel, params, prompt
        )

        self._state.running = False

        if result:
            summary = f"Result: {result.tok_s:.1f} tok/s · {result.tokens} tokens · {result.elapsed:.2f}s"
            self._state.add_log(summary)
            self._state.store.save_result(model.full_path, params, result)

            await self._send(ws, {
                "type": "controls_update",
                "controls": [
                    {"id": "run",          "label": "Run",    "style": "primary"},
                    {"id": "status_label", "value": f"{result.tok_s:.1f} tok/s", "style": "success"},
                ],
            })
        else:
            await self._send(ws, {
                "type": "controls_update",
                "controls": [
                    {"id": "run",          "label": "Run",   "style": "primary"},
                    {"id": "status_label", "value": "Failed", "style": "error"},
                ],
            })

        # Push full log to rack
        await self._send(ws, {
            "type":  "log_response",
            "lines": self._state.log_lines[-100:],
            "total": len(self._state.log_lines),
        })

    @staticmethod
    async def _send(ws: ServerConnection, data: dict) -> None:
        try:
            await ws.send(json.dumps(data))
        except websockets.exceptions.ConnectionClosed:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    rack_json = Path(__file__).parent / "rack.json"
    manifest  = json.loads(rack_json.read_text())
    port      = manifest.get("port", 8766)

    state = AppState()
    state.refresh_models()

    handler = SlotHandler(state)
    log.info("PylonRack Benchmark slot starting on ws://localhost:%d", port)

    async with websockets.serve(handler.handle, "localhost", port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
