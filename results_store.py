"""results_store.py — Persist calibration suite results.

Schema:

  {
    "version": 2,
    "suites": [
      {
        "id":             "suite_20260529_142200",
        "started_at":     ISO timestamp,
        "ended_at":       ISO timestamp,
        "duration_sec":   int,
        "budget":         "quick" | "standard" | "thorough",
        "mode":           "auto" | "manual",
        "profiles":       ["single", "throughput"],
        "models_tested":  [path, path, ...],
        "runs": [
          {
            "model":       path,
            "profile":     "single" | "throughput",
            "label":       "ub=2048, ctx=8192",
            "params":      {...},
            "prompt_name": "medium",
            "samples":     [Sample.as_dict(), ...],
            "aggregate":   Aggregate.as_dict() or aggregate_parallel(),
            "status":      "ok" | "failed" | "skipped",
            "error":       null | str,
          }
        ],
        "winners": {
          "<model_path>": {
            "single":     {"run_index": int, "label": str, "params": {...}, "metrics": {...}},
            "throughput": {"run_index": int, ...},
          }
        }
      }
    ]
  }

We keep all suites by default. Pruning happens via UI delete action.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = 2


class ResultsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: Optional[dict] = None

    # -------------------------------------------------------------------
    # Read / write
    # -------------------------------------------------------------------

    def _read(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text())
                if data.get("version") == SCHEMA_VERSION:
                    self._cache = data
                    return self._cache
        except Exception:
            pass
        self._cache = {"version": SCHEMA_VERSION, "suites": []}
        return self._cache

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))
        self._cache = data

    # -------------------------------------------------------------------
    # Suite operations
    # -------------------------------------------------------------------

    @staticmethod
    def new_suite_id() -> str:
        return "suite_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    def start_suite(self,
                    suite_id: str,
                    models: list[str],
                    profiles: list[str],
                    budget: str,
                    mode: str = "auto") -> dict:
        """Create a new suite entry and persist."""
        data = self._read()
        suite = {
            "id":            suite_id,
            "started_at":    datetime.now().isoformat(),
            "ended_at":      None,
            "duration_sec":  0,
            "budget":        budget,
            "mode":          mode,
            "profiles":      list(profiles),
            "models_tested": list(models),
            "runs":          [],
            "winners":       {},
            "status":        "running",
        }
        data["suites"].append(suite)
        self._write(data)
        return suite

    def append_run(self, suite_id: str, run_data: dict) -> None:
        """Add one run to an existing suite."""
        data = self._read()
        suite = self._find_suite(data, suite_id)
        if suite is None:
            return
        suite["runs"].append(run_data)
        self._write(data)

    def finish_suite(self,
                     suite_id: str,
                     winners: dict,
                     status: str = "complete") -> None:
        data = self._read()
        suite = self._find_suite(data, suite_id)
        if suite is None:
            return
        suite["ended_at"]     = datetime.now().isoformat()
        suite["status"]       = status
        suite["winners"]      = winners
        try:
            t0 = datetime.fromisoformat(suite["started_at"])
            t1 = datetime.fromisoformat(suite["ended_at"])
            suite["duration_sec"] = int((t1 - t0).total_seconds())
        except Exception:
            pass
        self._write(data)

    # -------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------

    def list_suites_summary(self) -> list[dict]:
        """Lightweight list — for the history panel."""
        data = self._read()
        return [{
            "id":            s["id"],
            "started_at":    s.get("started_at"),
            "ended_at":      s.get("ended_at"),
            "duration_sec":  s.get("duration_sec", 0),
            "budget":        s.get("budget"),
            "mode":          s.get("mode"),
            "profiles":      s.get("profiles", []),
            "models_count":  len(s.get("models_tested", [])),
            "runs_count":    len(s.get("runs", [])),
            "status":        s.get("status", "unknown"),
        } for s in data.get("suites", [])]

    def get_suite(self, suite_id: str) -> Optional[dict]:
        data = self._read()
        return self._find_suite(data, suite_id)

    def delete_suite(self, suite_id: str) -> bool:
        data = self._read()
        before = len(data["suites"])
        data["suites"] = [s for s in data["suites"] if s["id"] != suite_id]
        if len(data["suites"]) != before:
            self._write(data)
            return True
        return False

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _find_suite(data: dict, suite_id: str) -> Optional[dict]:
        for s in data.get("suites", []):
            if s["id"] == suite_id:
                return s
        return None

    def invalidate_cache(self) -> None:
        self._cache = None
