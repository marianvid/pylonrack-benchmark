"""model_scanner.py — Scan HF Cache for GGUF models (shared with llama slot)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GGUFModel:
    display_name: str
    full_path:    str
    size_gb:      float

    def __str__(self) -> str:
        return self.display_name


def _display_name(repo_dir: Path, gguf_file: Path) -> str:
    repo = re.sub(r"^models--", "", repo_dir.name).replace("--", "/")
    stem = gguf_file.stem
    short_repo = repo.split("/")[-1].lower()
    if stem.lower().startswith(short_repo):
        stem = stem[len(short_repo):].lstrip("-_")
    return f"{repo} / {stem}" if stem else repo


def scan(hf_cache_path: Path) -> list[GGUFModel]:
    if not hf_cache_path.exists():
        return []
    models: list[GGUFModel] = []
    for gguf_file in sorted(hf_cache_path.rglob("*.gguf")):
        # Skip projection models
        if gguf_file.name.startswith("mmproj"):
            continue
        repo_dir = gguf_file.parent
        for ancestor in gguf_file.parents:
            if ancestor.name.startswith("models--"):
                repo_dir = ancestor
                break
        models.append(GGUFModel(
            display_name = _display_name(repo_dir, gguf_file),
            full_path    = str(gguf_file),
            size_gb      = round(gguf_file.stat().st_size / (1024 ** 3), 1),
        ))
    return models
