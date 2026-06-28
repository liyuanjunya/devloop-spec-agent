"""Per-stage and per-model cost & latency summary for spec phase trace files.

Parses a TraceWriter JSONL file (`trace.jsonl`) into a structured
:class:`RunCostSummary`, with markdown and JSON renderers.

Used by:

* the ``devloop cost-summary <trace.jsonl>`` CLI subcommand, and
* the automatic "top 3 stages by cost" summary printed at the end of every
  ``devloop spec`` invocation.

Stages are read from each event's ``current_stage`` field — the orchestrator-
level stage set by ``TraceWriter.stage()`` (e.g. ``writer``, ``review_iter_1``).
If an event lacks ``current_stage`` (older traces predating Sprint D), the
fine-grained ``stage`` field is used as a fallback so the summary still groups
something useful instead of dumping everything into ``unknown``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Pricing table (USD per 1M tokens). Update as model pricing changes.
# Keys mirror both the dotted (`claude-opus-4.7`) and hyphenated
# (`claude-opus-4-7`) variants seen in configs/models.yaml.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4.7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4.6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "gpt-5.5": {"input": 5.0, "output": 20.0},
    "gpt-5.4": {"input": 4.0, "output": 16.0},
}

UNKNOWN_STAGE = "unknown"
UNKNOWN_MODEL = "<unknown-model>"


@dataclass(frozen=True)
class StageCost:
    """Aggregate cost & latency stats for a single stage (or model bucket)."""

    stage: str
    llm_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms_total: int
    latency_ms_p50: float
    latency_ms_p95: float


@dataclass(frozen=True)
class RunCostSummary:
    """Full per-stage + per-model cost report for one spec run."""

    run_id: str
    total_llm_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    total_latency_ms: int
    per_stage: list[StageCost]
    # Model name → bucket. We reuse StageCost so callers get the same fields.
    per_model: dict[str, StageCost]


# ----------------------------------------------------------------------
# Internals


def _model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a single call. Unknown models log a warning and return 0."""
    pricing = PRICING.get(model)
    if pricing is None:
        logger.warning(
            "cost_summary: model %r not in PRICING table; treating as $0",
            model,
        )
        return 0.0
    return (
        input_tokens * pricing["input"] / 1_000_000.0
        + output_tokens * pricing["output"] / 1_000_000.0
    )


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (0 ≤ pct ≤ 100). Returns 0.0 on empty input."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


@dataclass
class _Bucket:
    """Mutable accumulator used during a single parse pass."""

    key: str
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latencies: list[float] = field(default_factory=list)

    def add(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        latency_ms: float,
    ) -> None:
        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.estimated_cost_usd += cost
        self.latencies.append(latency_ms)

    def freeze(self) -> StageCost:
        return StageCost(
            stage=self.key,
            llm_calls=self.llm_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            estimated_cost_usd=round(self.estimated_cost_usd, 6),
            latency_ms_total=int(sum(self.latencies)),
            latency_ms_p50=round(_percentile(self.latencies, 50.0), 2),
            latency_ms_p95=round(_percentile(self.latencies, 95.0), 2),
        )


# ----------------------------------------------------------------------
# Public API


def parse_trace_file(trace_path: Path) -> RunCostSummary:
    """Parse a TraceWriter JSONL file and compute the cost summary.

    Only events of type ``llm_call`` contribute to cost. ``tool_call`` and
    ``stage_event`` rows are ignored (tool calls have no token cost in this
    pricing model).
    """
    if not trace_path.exists():
        raise FileNotFoundError(f"trace file not found: {trace_path}")

    run_id = ""
    stage_buckets: dict[str, _Bucket] = {}
    model_buckets: dict[str, _Bucket] = {}
    total_calls = 0
    total_input = 0
    total_output = 0
    total_cost = 0.0
    total_latency = 0.0

    with trace_path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(
                    "cost_summary: skipping malformed line in %s", trace_path
                )
                continue

            if not run_id and ev.get("run_id"):
                run_id = ev["run_id"]

            if ev.get("type") != "llm_call":
                continue

            usage = ev.get("usage") or {}
            inp = int(usage.get("input_tokens", 0) or 0)
            outp = int(usage.get("output_tokens", 0) or 0)
            latency = float(ev.get("latency_ms", 0) or 0)
            model = ev.get("model") or UNKNOWN_MODEL
            # Prefer the orchestrator-level grouping; fall back to the
            # fine-grained per-call stage for backward compat with older
            # traces, finally fall back to "unknown".
            stage = ev.get("current_stage") or ev.get("stage") or UNKNOWN_STAGE

            cost = _model_cost(model, inp, outp)

            stage_buckets.setdefault(stage, _Bucket(stage)).add(
                input_tokens=inp,
                output_tokens=outp,
                cost=cost,
                latency_ms=latency,
            )
            model_buckets.setdefault(model, _Bucket(model)).add(
                input_tokens=inp,
                output_tokens=outp,
                cost=cost,
                latency_ms=latency,
            )
            total_calls += 1
            total_input += inp
            total_output += outp
            total_cost += cost
            total_latency += latency

    per_stage = [b.freeze() for b in stage_buckets.values()]
    per_stage.sort(key=lambda s: s.estimated_cost_usd, reverse=True)
    per_model = {k: b.freeze() for k, b in model_buckets.items()}

    return RunCostSummary(
        run_id=run_id,
        total_llm_calls=total_calls,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_estimated_cost_usd=round(total_cost, 6),
        total_latency_ms=int(total_latency),
        per_stage=per_stage,
        per_model=per_model,
    )


def render_summary_markdown(summary: RunCostSummary) -> str:
    """Render a markdown table report of the summary."""
    lines: list[str] = []
    lines.append(f"# Cost summary — run {summary.run_id or '<unknown>'}")
    lines.append("")
    lines.append(f"- Total LLM calls: **{summary.total_llm_calls}**")
    lines.append(f"- Total input tokens: {summary.total_input_tokens:,}")
    lines.append(f"- Total output tokens: {summary.total_output_tokens:,}")
    lines.append(
        f"- Total estimated cost: **${summary.total_estimated_cost_usd:.4f}**"
    )
    lines.append(f"- Total latency: {summary.total_latency_ms / 1000:.2f}s")
    lines.append("")
    lines.append("## Per stage (sorted by cost)")
    lines.append(
        "| Stage | Calls | Input tokens | Output tokens | Cost (USD) | "
        "Latency total (s) | p50 (ms) | p95 (ms) |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in summary.per_stage:
        lines.append(
            f"| {s.stage} | {s.llm_calls} | {s.input_tokens:,} | "
            f"{s.output_tokens:,} | ${s.estimated_cost_usd:.4f} | "
            f"{s.latency_ms_total / 1000:.2f} | "
            f"{s.latency_ms_p50:.0f} | {s.latency_ms_p95:.0f} |"
        )
    lines.append("")
    lines.append("## Per model")
    lines.append(
        "| Model | Calls | Input tokens | Output tokens | Cost (USD) | "
        "Latency total (s) |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for name, s in sorted(
        summary.per_model.items(),
        key=lambda kv: kv[1].estimated_cost_usd,
        reverse=True,
    ):
        lines.append(
            f"| {name} | {s.llm_calls} | {s.input_tokens:,} | "
            f"{s.output_tokens:,} | ${s.estimated_cost_usd:.4f} | "
            f"{s.latency_ms_total / 1000:.2f} |"
        )
    return "\n".join(lines)


def render_summary_json(summary: RunCostSummary) -> str:
    """JSON of the summary for programmatic consumption."""
    payload = {
        "run_id": summary.run_id,
        "total_llm_calls": summary.total_llm_calls,
        "total_input_tokens": summary.total_input_tokens,
        "total_output_tokens": summary.total_output_tokens,
        "total_estimated_cost_usd": summary.total_estimated_cost_usd,
        "total_latency_ms": summary.total_latency_ms,
        "per_stage": [asdict(s) for s in summary.per_stage],
        "per_model": {k: asdict(v) for k, v in summary.per_model.items()},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
