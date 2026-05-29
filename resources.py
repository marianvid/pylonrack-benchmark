"""resources.py — Memory check + detection of running pylonrack-llama slot.

The slot itself starts with no resource check (it consumes <100MB). The check
happens at `start_suite` time — we look at currently available memory and
decide which selected models can actually run.

Memory accounting on macOS:
  Available  =  free_pages   + inactive_pages   + purgeable_pages
  We exclude `wired` (locked, not recoverable) and `active` (in use).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

_PAGE_SIZE_RE = re.compile(r"page size of (\d+) bytes")
_PAGES_RE     = re.compile(r"^(.+?):\s+(\d+)\.?$")


def _parse_vm_stat(output: str) -> dict:
    """Parse `vm_stat` output into a dict of metric → page count."""
    page_size = 16384  # M-series default
    m = _PAGE_SIZE_RE.search(output)
    if m:
        page_size = int(m.group(1))

    pages = {"_page_size": page_size}
    for line in output.splitlines():
        line = line.strip()
        m = _PAGES_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower().replace(" ", "_")
        pages[key] = int(m.group(2))
    return pages


def get_memory_status() -> dict:
    """Return memory accounting in GB. Uses macOS vm_stat."""
    try:
        out = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=5,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"total_gb": 0.0, "available_gb": 0.0, "error": "vm_stat unavailable"}

    pages = _parse_vm_stat(out)
    page_size = pages.get("_page_size", 16384)

    def gb(pkey: str) -> float:
        return pages.get(pkey, 0) * page_size / (1024 ** 3)

    free       = gb("pages_free")
    inactive   = gb("pages_inactive")
    purgeable  = gb("pages_purgeable")
    active     = gb("pages_active")
    wired      = gb("pages_wired_down")
    compressed = gb("pages_occupied_by_compressor")
    speculative = gb("pages_speculative")

    # Available = free + inactive + purgeable + speculative.
    # macOS will recover these immediately when a new process asks for memory.
    available = free + inactive + purgeable + speculative
    total     = active + wired + free + inactive + compressed + speculative

    return {
        "total_gb":     round(total, 1),
        "available_gb": round(available, 1),
        "free_gb":      round(free, 1),
        "inactive_gb":  round(inactive, 1),
        "purgeable_gb": round(purgeable, 1),
        "active_gb":    round(active, 1),
        "wired_gb":     round(wired, 1),
        "compressed_gb": round(compressed, 1),
    }


# ---------------------------------------------------------------------------
# Model size estimation
# ---------------------------------------------------------------------------

@dataclass
class ModelFit:
    path:         str
    size_gb:      float
    kv_estimate_gb: float
    total_gb:     float       # weights + KV cache estimate
    fits:         bool
    margin_gb:    float       # available - total (negative if doesn't fit)


def estimate_kv_cache_gb(model_size_gb: float, ctx_size: int = 32768,
                          parallel: int = 1) -> float:
    """Rough KV cache size estimate.

    Heuristic: KV cache scales linearly with ctx × parallel, and is roughly
    proportional to model size (number of layers × hidden dim). For Q4_K_M:
      - 8B model:  ~0.5 GB / 32k ctx / slot
      - 26B MoE:   ~1.0 GB / 32k ctx / slot
      - 35B MoE:   ~1.2 GB / 32k ctx / slot

    This is an approximation good enough for "fits / does not fit" decisions.
    """
    # Per-slot per-32k-ctx KV cost in GB, scaled by model size
    per_slot_32k = 0.06 * model_size_gb   # 0.06 × 8 = 0.48 GB → matches 8B
    return per_slot_32k * (ctx_size / 32768) * parallel


def check_model_fit(model_path: str, model_size_gb: float, available_gb: float,
                    ctx_size: int = 32768, parallel: int = 1,
                    safety_margin_gb: float = 2.0) -> ModelFit:
    kv = estimate_kv_cache_gb(model_size_gb, ctx_size, parallel)
    total = model_size_gb + kv + safety_margin_gb
    margin = available_gb - total
    return ModelFit(
        path           = model_path,
        size_gb        = model_size_gb,
        kv_estimate_gb = round(kv, 1),
        total_gb       = round(total, 1),
        fits           = margin > 0,
        margin_gb      = round(margin, 1),
    )


# ---------------------------------------------------------------------------
# pylonrack-llama detection
# ---------------------------------------------------------------------------

PYLONRACK_DIR = Path.home() / "Library" / "Application Support" / "PylonRack"
SLOTS_JSON    = PYLONRACK_DIR / "slots.json"


def detect_active_llama_servers() -> list[dict]:
    """Look at PylonRack's slots.json + active ports to find live llama servers.

    Returns a list of dicts: [{name, host, port, pid}]
    """
    found = []
    if not SLOTS_JSON.exists():
        return found

    try:
        slots = json.loads(SLOTS_JSON.read_text())
    except Exception:
        return found

    # Schema may vary; try to be liberal
    slot_list = slots if isinstance(slots, list) else slots.get("slots", [])

    for s in slot_list:
        if not isinstance(s, dict):
            continue
        port = s.get("port")
        if not port:
            continue
        # Only report slots that are actually listening
        pid = _pid_listening_on(port)
        if pid:
            found.append({
                "name": s.get("name", "?"),
                "host": s.get("host", "localhost"),
                "port": port,
                "pid":  pid,
                "is_active": s.get("isActive", s.get("is_active", False)),
            })
    return found


def _pid_listening_on(port: int) -> Optional[int]:
    """Return the PID of the process listening on `port`, or None."""
    try:
        out = subprocess.run(
            ["lsof", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if not out:
            return None
        return int(out.splitlines()[0])
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None


def is_port_in_use(port: int) -> bool:
    return _pid_listening_on(port) is not None


# ---------------------------------------------------------------------------
# Combined check
# ---------------------------------------------------------------------------

def check_suite_feasibility(selected_models: list[tuple[str, float]],
                             ctx_size: int = 32768, parallel: int = 1,
                             min_required_gb: float = 6.0) -> dict:
    """Pre-suite feasibility check.

    Args:
      selected_models: list of (path, size_gb) for each model to test.
      ctx_size, parallel: largest sweep params to consider.
      min_required_gb: absolute floor — refuse below this.

    Returns:
      {
        "ok":           bool,
        "available_gb": float,
        "memory":       dict,
        "models":       [{path, fits, status, ...}, ...],
        "warnings":     [str, ...],
        "blockers":     [str, ...],
        "llama_slots":  [...],
      }
    """
    mem        = get_memory_status()
    available  = mem.get("available_gb", 0.0)
    llama_slots = detect_active_llama_servers()

    warnings:  list[str] = []
    blockers:  list[str] = []
    model_fits = []

    if available < min_required_gb:
        blockers.append(
            f"Insufficient memory: {available:.1f} GB available, need at least "
            f"{min_required_gb:.1f} GB to run any model."
        )

    for path, size_gb in selected_models:
        fit = check_model_fit(path, size_gb, available, ctx_size, parallel)
        if not fit.fits:
            blockers.append(
                f"Model {Path(path).name} ({size_gb:.1f} GB) does not fit: "
                f"needs ~{fit.total_gb:.1f} GB total but only {available:.1f} GB available."
            )
        elif fit.margin_gb < 4.0:
            warnings.append(
                f"Model {Path(path).name} fits tightly (margin {fit.margin_gb:.1f} GB)."
            )
        model_fits.append({
            "path":     path,
            "size_gb":  size_gb,
            "fits":     fit.fits,
            "total_gb": fit.total_gb,
            "kv_gb":    fit.kv_estimate_gb,
            "margin_gb": fit.margin_gb,
        })

    if llama_slots:
        names = ", ".join(s["name"] for s in llama_slots)
        warnings.append(
            f"pylonrack-llama is currently active ({names}). "
            "Consider stopping it before running a heavy calibration suite."
        )

    return {
        "ok":           not blockers,
        "available_gb": available,
        "memory":       mem,
        "models":       model_fits,
        "warnings":     warnings,
        "blockers":     blockers,
        "llama_slots":  llama_slots,
    }
