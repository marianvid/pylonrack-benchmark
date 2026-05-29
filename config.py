"""config.py — Load and validate settings.json with defaults."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"


@dataclass
class AppConfig:
    llama_bin:       str = "/usr/local/bin/llama-server"
    hf_cache:        str = ""
    bench_port:      int = 1235
    results_file:    str = "~/.pylonrack/calibrate_results.json"
    log_file:        str = "~/.pylonrack/calibrate.log"
    n_predict:       int = 256
    runs_per_combo:  int = 3
    min_memory_gb:   float = 6.0

    @property
    def bin_path(self) -> Path:
        return Path(os.path.expanduser(self.llama_bin))

    @property
    def hf_cache_path(self) -> Path:
        return Path(os.path.expanduser(self.hf_cache))

    @property
    def results_path(self) -> Path:
        return Path(os.path.expanduser(self.results_file))

    @property
    def log_path(self) -> Path:
        return Path(os.path.expanduser(self.log_file))


def load() -> AppConfig:
    if not SETTINGS_FILE.exists():
        return AppConfig()

    raw = json.loads(SETTINGS_FILE.read_text())

    return AppConfig(
        llama_bin      = os.path.expanduser(raw.get("llama_bin",     AppConfig.llama_bin)),
        hf_cache       = os.path.expanduser(raw.get("hf_cache",      AppConfig.hf_cache)),
        bench_port     = raw.get("bench_port",     AppConfig.bench_port),
        results_file   = raw.get("results_file",   AppConfig.results_file),
        log_file       = raw.get("log_file",       AppConfig.log_file),
        n_predict      = raw.get("n_predict",      AppConfig.n_predict),
        runs_per_combo = raw.get("runs_per_combo", AppConfig.runs_per_combo),
        min_memory_gb  = raw.get("min_memory_gb",  AppConfig.min_memory_gb),
    )
