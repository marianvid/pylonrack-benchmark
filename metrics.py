"""metrics.py — Extract & aggregate timing metrics from llama-server responses.

The `timings` object returned by llama-server is the authoritative source of
truth — measured server-side, no network jitter, no client overhead. Format
(confirmed against llama.cpp b9415 master):

    {
        "prompt_n":              <int>,     tokens in prompt (after cache)
        "prompt_ms":             <float>,   ms spent on prefill
        "prompt_per_token_ms":   <float>,
        "prompt_per_second":     <float>,   prefill throughput
        "predicted_n":           <int>,     tokens generated
        "predicted_ms":          <float>,   ms spent generating
        "predicted_per_token_ms":<float>,
        "predicted_per_second":  <float>,   decode throughput
        "cache_n":               <int>,     tokens reused from cache
        # speculative decoding only:
        "draft_n":               <int>,
        "draft_n_accepted":      <int>,
    }

TTFT (time-to-first-token) is approximated as `prompt_ms` plus the time to
generate one token: prompt_ms + predicted_per_token_ms. This matches what a
user perceives when streaming.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Sample:
    """One measurement from one HTTP request to llama-server."""
    prompt_n:               int
    prompt_ms:              float
    prompt_per_second:      float
    predicted_n:            int
    predicted_ms:           float
    predicted_per_second:   float
    cache_n:                int = 0
    draft_n:                Optional[int] = None
    draft_n_accepted:       Optional[int] = None

    @property
    def ttft_ms(self) -> float:
        """Time-to-first-token estimate: prefill + 1 decode step."""
        per_tok = self.predicted_ms / max(self.predicted_n, 1)
        return self.prompt_ms + per_tok

    @property
    def acceptance_rate(self) -> Optional[float]:
        if self.draft_n is None or self.draft_n == 0:
            return None
        return self.draft_n_accepted / self.draft_n

    @classmethod
    def from_response(cls, response_json: dict) -> Optional["Sample"]:
        """Parse a chat/completions response. Returns None if no timings."""
        timings = response_json.get("timings")
        if not timings:
            return None
        try:
            return cls(
                prompt_n             = int(timings["prompt_n"]),
                prompt_ms            = float(timings["prompt_ms"]),
                prompt_per_second    = float(timings.get("prompt_per_second", 0.0)),
                predicted_n          = int(timings["predicted_n"]),
                predicted_ms         = float(timings["predicted_ms"]),
                predicted_per_second = float(timings.get("predicted_per_second", 0.0)),
                cache_n              = int(timings.get("cache_n", 0)),
                draft_n              = (int(timings["draft_n"]) if "draft_n" in timings else None),
                draft_n_accepted     = (int(timings["draft_n_accepted"]) if "draft_n_accepted" in timings else None),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def as_dict(self) -> dict:
        d = {
            "prompt_n":              self.prompt_n,
            "prompt_ms":             round(self.prompt_ms, 2),
            "prompt_per_second":     round(self.prompt_per_second, 2),
            "predicted_n":           self.predicted_n,
            "predicted_ms":          round(self.predicted_ms, 2),
            "predicted_per_second":  round(self.predicted_per_second, 2),
            "cache_n":               self.cache_n,
            "ttft_ms":               round(self.ttft_ms, 2),
        }
        if self.draft_n is not None:
            d["draft_n"]          = self.draft_n
            d["draft_n_accepted"] = self.draft_n_accepted
            d["acceptance_rate"]  = round(self.acceptance_rate or 0.0, 3)
        return d


@dataclass
class Aggregate:
    """Median values over multiple Samples for one parameter combination."""
    prefill_tok_s:         float
    decode_tok_s:          float
    ttft_ms:               float
    samples_count:         int
    acceptance_rate:       Optional[float] = None  # speculative decoding only

    def as_dict(self) -> dict:
        d = {
            "prefill_tok_s": round(self.prefill_tok_s, 1),
            "decode_tok_s":  round(self.decode_tok_s, 1),
            "ttft_ms":       round(self.ttft_ms, 1),
            "samples":       self.samples_count,
        }
        if self.acceptance_rate is not None:
            d["acceptance_rate"] = round(self.acceptance_rate, 3)
        return d


def median_of(samples: list[Sample]) -> Optional[Aggregate]:
    """Aggregate multiple samples via median. Returns None if no valid samples."""
    if not samples:
        return None

    prefills = [s.prompt_per_second for s in samples if s.prompt_per_second > 0]
    decodes  = [s.predicted_per_second for s in samples if s.predicted_per_second > 0]
    ttfts    = [s.ttft_ms for s in samples]

    if not prefills or not decodes:
        return None

    acc_rates = [s.acceptance_rate for s in samples if s.acceptance_rate is not None]
    acc = statistics.median(acc_rates) if acc_rates else None

    return Aggregate(
        prefill_tok_s   = statistics.median(prefills),
        decode_tok_s    = statistics.median(decodes),
        ttft_ms         = statistics.median(ttfts),
        samples_count   = len(samples),
        acceptance_rate = acc,
    )


def aggregate_parallel(samples: list[Sample], wall_seconds: float) -> dict:
    """Aggregate metrics for parallel-request runs.

    For throughput profile, we care about total tokens/sec across all parallel
    requests against wall-clock time. Individual per-request decode tok/s is
    less meaningful — it's the aggregate that matters.
    """
    if not samples or wall_seconds <= 0:
        return {}
    total_generated = sum(s.predicted_n for s in samples)
    aggregate_tok_s = total_generated / wall_seconds
    avg_ttft        = statistics.median([s.ttft_ms for s in samples])
    # per-request decode tok/s, median
    decode_median   = statistics.median(
        [s.predicted_per_second for s in samples if s.predicted_per_second > 0]
    )
    return {
        "aggregate_tok_s":      round(aggregate_tok_s, 1),
        "per_request_decode":   round(decode_median, 1),
        "total_tokens":         total_generated,
        "wall_seconds":         round(wall_seconds, 2),
        "median_ttft_ms":       round(avg_ttft, 1),
        "samples":              len(samples),
    }
