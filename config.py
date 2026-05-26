"""config.py — Load and validate settings.json with defaults."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"

DEFAULT_PARAMS = {
    "ctx_size":          32768,
    "parallel":          16,
    "batch_size":        2048,
    "ubatch_size":       256,
    "threads":           8,
    "n_gpu_layers":      99,
    "cache_reuse":       200,
    "flash_attn":        True,
    "cont_batching":     True,
    "spec_type":         None,
    "spec_ngram_size_n": None,
    "draft":             None,
    "reasoning_budget":  None,
    "enable_thinking":   None,
}

DEFAULT_PROMPT = (
    "Explain the importance of 400GB/s memory bandwidth for LLM "
    "inference on Apple Silicon in 150 words."
)


@dataclass
class AppConfig:
    llama_bin:    str = "/usr/local/bin/llama-server"
    hf_cache:     str = ""
    bench_port:   int = 1235
    params:       dict = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    prompt:       str = DEFAULT_PROMPT
    results_file: str = "~/.pylonrack/benchmark_results.json"

    @property
    def bin_path(self) -> Path:
        return Path(os.path.expanduser(self.llama_bin))

    @property
    def hf_cache_path(self) -> Path:
        return Path(os.path.expanduser(self.hf_cache))

    @property
    def results_path(self) -> Path:
        return Path(os.path.expanduser(self.results_file))


def load() -> AppConfig:
    if not SETTINGS_FILE.exists():
        return AppConfig()

    raw = json.loads(SETTINGS_FILE.read_text())

    params = dict(DEFAULT_PARAMS)
    params.update(raw.get("params", {}))

    return AppConfig(
        llama_bin    = os.path.expanduser(raw.get("llama_bin",    AppConfig.llama_bin)),
        hf_cache     = os.path.expanduser(raw.get("hf_cache",     AppConfig.hf_cache)),
        bench_port   = raw.get("bench_port",   AppConfig.bench_port),
        params       = params,
        prompt       = raw.get("prompt",       AppConfig.prompt),
        results_file = raw.get("results_file", AppConfig.results_file),
    )
