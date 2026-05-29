"""prompts.py — Fixed prompt set for reproducible calibration measurements.

Three prompts of different lengths to characterize prefill behaviour at the
three scales that matter for parallaxvox-like workloads:
  - SHORT  (~50 tokens):  chat / triage scale
  - MEDIUM (~500 tokens): single-article extraction scale
  - LONG   (~4000 tokens): consolidation / long-context scale

Content is intentionally generic — calibration measures the engine, not the
quality of the response. What matters is the token count, not the meaning.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SHORT — ~50 tokens
# ---------------------------------------------------------------------------
SHORT = (
    "Summarize in two sentences why local LLM inference on Apple Silicon "
    "differs from datacenter GPU inference. Be concise and factual."
)

# ---------------------------------------------------------------------------
# MEDIUM — ~500 tokens of context
# ---------------------------------------------------------------------------
MEDIUM = (
    "You are an editor reviewing a draft article for a technical publication. "
    "The draft below discusses memory bandwidth in modern computer architectures, "
    "with a focus on the implications for large language model inference workloads. "
    "Read the draft carefully and produce a structured assessment.\n\n"
    "--- DRAFT BEGINS ---\n"
    "Memory bandwidth has emerged as the dominant constraint in modern inference "
    "workloads. Where compute throughput was the bottleneck of the early deep "
    "learning era, the picture has inverted: large language models spend the "
    "majority of their decode time waiting on weights to traverse the memory "
    "hierarchy rather than performing arithmetic. The reason is structural. "
    "During the decode phase, each generated token requires reading the entire "
    "model's weights from memory once, since the matrix-vector multiplications "
    "involved have minimal arithmetic intensity. A 7-billion-parameter model "
    "quantized to four bits occupies roughly 4 GB; generating each token thus "
    "demands moving 4 GB through the memory subsystem. At a memory bandwidth "
    "of 400 GB per second, the theoretical ceiling for such a model is 100 "
    "tokens per second per stream — and observed performance approaches this "
    "limit closely on well-tuned implementations. The implication for hardware "
    "selection is clear: bandwidth, not flops, is the figure of merit for "
    "inference. Apple Silicon's unified memory architecture, which places CPU "
    "and GPU on a single bandwidth-shared pool, performs surprisingly well in "
    "this regime despite lacking the raw compute density of discrete GPUs.\n"
    "--- DRAFT ENDS ---\n\n"
    "Provide your editorial assessment covering: factual accuracy, clarity of "
    "exposition, what is missing or could be elaborated, and any technical "
    "claims that should be verified before publication."
)

# ---------------------------------------------------------------------------
# LONG — ~4000 tokens of context
# Built by concatenating a long technical passage to stress prefill at scale.
# ---------------------------------------------------------------------------
def _build_long() -> str:
    intro = (
        "You are a senior technical analyst preparing a comprehensive briefing "
        "for an executive audience. Below are excerpts from multiple sources "
        "covering the current state of local LLM inference on consumer hardware. "
        "Synthesize the material into a coherent briefing that highlights the "
        "key trade-offs, the most important architectural decisions, and the "
        "open questions that remain unresolved in the field.\n\n"
    )
    section_template = (
        "--- SOURCE {n}: {title} ---\n"
        "The technical landscape for running large language models locally has "
        "shifted significantly over the past eighteen months. What was once an "
        "experimental capability requiring substantial hardware investment is "
        "now routinely deployed on consumer-grade laptops and desktops. The "
        "convergence of several factors made this possible: quantization "
        "techniques matured, with four-bit and even two-bit schemes producing "
        "models that retain most of the quality of the full-precision originals; "
        "memory architectures on the consumer side caught up, particularly with "
        "Apple's transition to unified memory at scale; and the inference "
        "engines themselves — llama.cpp, MLX, and others — have been the focus "
        "of intense optimization work, with kernel-level improvements arriving "
        "weekly. The result is a regime where a developer with a modern laptop "
        "and 64 to 128 gigabytes of unified memory can run models that would "
        "have required a small datacenter only a few years ago. The implications "
        "extend beyond the obvious cost savings. Local inference unlocks "
        "privacy-sensitive workflows, removes dependence on cloud availability, "
        "and dramatically reduces latency for interactive applications. It also "
        "shifts the optimization problem: instead of paying per token to a "
        "provider, the cost is measured in time and electricity, with the "
        "important caveat that the constraints are no longer elastic. A cloud "
        "endpoint can be scaled up at the cost of money; a local machine has "
        "fixed resources, and the question becomes how to allocate them well.\n\n"
    )
    sections = "".join(
        section_template.format(n=i + 1, title=t)
        for i, t in enumerate([
            "The Quantization Landscape",
            "Apple Silicon Architectural Notes",
            "Inference Engine Trade-offs",
            "Benchmarking Methodology Concerns",
            "Memory Bandwidth as the Dominant Constraint",
            "The Role of KV Cache Size",
            "Speculative Decoding in Practice",
            "Continuous Batching Under Load",
            "The Future of On-Device Inference",
        ])
    )
    outro = (
        "\nProduce the executive briefing now. Structure it with clear headings, "
        "highlight the three most consequential trade-offs, and identify the "
        "open questions that warrant further investigation."
    )
    return intro + sections + outro


LONG = _build_long()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROMPTS: dict[str, str] = {
    "short":  SHORT,
    "medium": MEDIUM,
    "long":   LONG,
}


def get(name: str) -> str:
    """Get a prompt by name. Raises KeyError if unknown."""
    return PROMPTS[name]


def names() -> list[str]:
    """All available prompt names, in order of increasing length."""
    return ["short", "medium", "long"]
