"""results_store.py — Persist benchmark results per model."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from benchmark_runner import BenchmarkResult

MAX_RUNS_PER_MODEL = 10


class ResultsStore:
    """JSON-backed store: { models: { "<path>": { params, runs: [...] } } }"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load_model(self, model_path: str) -> dict:
        data  = self._read()
        entry = data["models"].get(model_path)
        return entry if entry else {"params": {}, "runs": []}

    def save_result(self, model_path: str, params: dict,
                    result: BenchmarkResult) -> None:
        data  = self._read()
        entry = data["models"].setdefault(model_path, {"params": {}, "runs": []})
        entry["params"] = params
        entry["runs"].append({
            "date":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tok_s":    round(result.tok_s, 2),
            "tokens":   result.tokens,
            "elapsed":  result.elapsed,
            "parallel": result.parallel,
            "params":   dict(params),
        })
        if len(entry["runs"]) > MAX_RUNS_PER_MODEL:
            entry["runs"] = entry["runs"][-MAX_RUNS_PER_MODEL:]
        self._write(data)

    def _read(self) -> dict:
        try:
            if self._path.exists():
                return json.loads(self._path.read_text())
        except Exception:
            pass
        return {"models": {}}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))
