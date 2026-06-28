"""Trace analyzer — inspect trace.jsonl from a spec run."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StageStats:
    stage: str
    llm_calls: int = 0
    tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0
    errors: int = 0


@dataclass
class TraceSummary:
    run_id: str
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0
    total_errors: int = 0
    per_stage: dict[str, StageStats] = field(default_factory=dict)
    per_tool: Counter = field(default_factory=Counter)
    per_model: Counter = field(default_factory=Counter)
    tool_cache_hit_rate: float = 0.0


def parse_trace(trace_path: Path) -> TraceSummary:
    """Parse a trace.jsonl into a structured summary."""
    if not trace_path.exists():
        raise FileNotFoundError(f"trace file not found: {trace_path}")

    run_id = ""
    stages: dict[str, StageStats] = {}
    per_tool: Counter = Counter()
    per_model: Counter = Counter()
    total_tool_calls = 0
    cached_tool_calls = 0
    total_errors = 0
    total_latency = 0.0
    total_llm_calls = 0
    total_input = 0
    total_output = 0

    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not run_id and ev.get("run_id"):
                run_id = ev["run_id"]

            etype = ev.get("type")
            stage = ev.get("stage", "unknown")
            if stage not in stages:
                stages[stage] = StageStats(stage=stage)
            s = stages[stage]

            if etype == "llm_call":
                s.llm_calls += 1
                total_llm_calls += 1
                usage = ev.get("usage") or {}
                inp = int(usage.get("input_tokens", 0) or 0)
                outp = int(usage.get("output_tokens", 0) or 0)
                s.total_input_tokens += inp
                s.total_output_tokens += outp
                total_input += inp
                total_output += outp
                lat = float(ev.get("latency_ms", 0) or 0)
                s.total_latency_ms += lat
                total_latency += lat
                per_model[ev.get("model", "?")] += 1
                if ev.get("error"):
                    s.errors += 1
                    total_errors += 1

            elif etype == "tool_call":
                s.tool_calls += 1
                total_tool_calls += 1
                per_tool[ev.get("tool_name", "?")] += 1
                if ev.get("cached"):
                    cached_tool_calls += 1
                if ev.get("error"):
                    s.errors += 1
                    total_errors += 1

    summary = TraceSummary(
        run_id=run_id,
        total_llm_calls=total_llm_calls,
        total_tool_calls=total_tool_calls,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_latency_ms=total_latency,
        total_errors=total_errors,
        per_stage=stages,
        per_tool=per_tool,
        per_model=per_model,
        tool_cache_hit_rate=(cached_tool_calls / total_tool_calls) if total_tool_calls else 0.0,
    )
    return summary


def render_summary_markdown(summary: TraceSummary) -> str:
    out: list[str] = []
    out.append(f"# Trace summary — run {summary.run_id}")
    out.append("")
    out.append(f"- Total LLM calls: **{summary.total_llm_calls}**")
    out.append(f"- Total tool calls: **{summary.total_tool_calls}** ({summary.tool_cache_hit_rate:.0%} cache hit)")
    out.append(f"- Total input tokens: {summary.total_input_tokens:,}")
    out.append(f"- Total output tokens: {summary.total_output_tokens:,}")
    out.append(f"- Total latency: {summary.total_latency_ms / 1000:.1f}s")
    out.append(f"- Errors: {summary.total_errors}")
    out.append("")
    out.append("## Per stage")
    out.append("| Stage | LLM calls | Tool calls | Input tokens | Output tokens | Latency (s) | Errors |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    for name in sorted(summary.per_stage):
        s = summary.per_stage[name]
        out.append(
            f"| {name} | {s.llm_calls} | {s.tool_calls} | {s.total_input_tokens:,} | "
            f"{s.total_output_tokens:,} | {s.total_latency_ms/1000:.2f} | {s.errors} |"
        )
    out.append("")
    out.append("## Tool usage")
    for tool, n in summary.per_tool.most_common():
        out.append(f"- {tool}: {n}")
    out.append("")
    out.append("## Model usage")
    for m, n in summary.per_model.most_common():
        out.append(f"- {m}: {n}")
    return "\n".join(out)
