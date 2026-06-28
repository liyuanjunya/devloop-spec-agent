"""Tests for devloop.tools.cost_summary."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from devloop.tools.cost_summary import (
    PRICING,
    RunCostSummary,
    StageCost,
    parse_trace_file,
    render_summary_json,
    render_summary_markdown,
)

# ----------------------------------------------------------------------
# Fixture helpers


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    """Write a list of events as one JSON object per line."""
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + ("\n" if events else ""),
        encoding="utf-8",
    )


def _llm_event(
    *,
    run_id: str = "r1",
    stage: str = "writer.initial",
    current_stage: str = "writer",
    model: str = "claude-opus-4.7",
    input_tokens: int = 100,
    output_tokens: int = 50,
    latency_ms: float = 1000.0,
    agent: str = "writer",
    provider: str = "anthropic",
    error: str | None = None,
) -> dict[str, Any]:
    """Build a minimal but realistic llm_call trace event."""
    return {
        "type": "llm_call",
        "run_id": run_id,
        "trace_id": "trace-x",
        "stage": stage,
        "current_stage": current_stage,
        "agent": agent,
        "provider": provider,
        "model": model,
        "messages_count": 1,
        "tools_count": 0,
        "latency_ms": latency_ms,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "stop_reason": "end_turn",
        "tool_calls_count": 0,
        "error": error,
    }


# ----------------------------------------------------------------------
# 1. Empty trace


def test_parse_empty_trace_file(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    p.write_text("", encoding="utf-8")

    summary = parse_trace_file(p)

    assert isinstance(summary, RunCostSummary)
    assert summary.run_id == ""
    assert summary.total_llm_calls == 0
    assert summary.total_input_tokens == 0
    assert summary.total_output_tokens == 0
    assert summary.total_estimated_cost_usd == 0.0
    assert summary.total_latency_ms == 0
    assert summary.per_stage == []
    assert summary.per_model == {}


# ----------------------------------------------------------------------
# 2. Single call


def test_parse_single_call_trace(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_jsonl(
        p,
        [
            _llm_event(
                input_tokens=1000,
                output_tokens=500,
                latency_ms=1200.0,
                current_stage="writer",
                model="claude-opus-4.7",
            )
        ],
    )

    summary = parse_trace_file(p)

    assert summary.run_id == "r1"
    assert summary.total_llm_calls == 1
    assert summary.total_input_tokens == 1000
    assert summary.total_output_tokens == 500
    expected_cost = (
        1000 * PRICING["claude-opus-4.7"]["input"] / 1_000_000
        + 500 * PRICING["claude-opus-4.7"]["output"] / 1_000_000
    )
    assert summary.total_estimated_cost_usd == pytest.approx(expected_cost, rel=1e-6)
    assert summary.total_latency_ms == 1200
    assert len(summary.per_stage) == 1
    only = summary.per_stage[0]
    assert isinstance(only, StageCost)
    assert only.stage == "writer"
    assert only.llm_calls == 1
    assert only.estimated_cost_usd == pytest.approx(expected_cost, rel=1e-6)
    assert "claude-opus-4.7" in summary.per_model


# ----------------------------------------------------------------------
# 3. Multi-stage


def test_parse_multi_stage_trace(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    events = [
        _llm_event(
            stage="intent.analyzer", current_stage="intent",
            input_tokens=200, output_tokens=80, latency_ms=300.0,
        ),
        _llm_event(
            stage="intent.skeptic", current_stage="intent",
            input_tokens=300, output_tokens=120, latency_ms=400.0,
        ),
        _llm_event(
            stage="writer.initial", current_stage="writer",
            input_tokens=2000, output_tokens=800, latency_ms=2000.0,
        ),
        _llm_event(
            stage="review.security", current_stage="review_iter_1",
            input_tokens=600, output_tokens=200, latency_ms=600.0,
        ),
        _llm_event(
            stage="review.architecture", current_stage="review_iter_1",
            input_tokens=700, output_tokens=210, latency_ms=700.0,
        ),
    ]
    _write_jsonl(p, events)

    summary = parse_trace_file(p)

    assert summary.total_llm_calls == 5
    assert summary.total_input_tokens == 200 + 300 + 2000 + 600 + 700
    assert summary.total_output_tokens == 80 + 120 + 800 + 200 + 210
    assert summary.total_latency_ms == 4000

    stages = {s.stage: s for s in summary.per_stage}
    assert set(stages.keys()) == {"intent", "writer", "review_iter_1"}
    assert stages["intent"].llm_calls == 2
    assert stages["intent"].input_tokens == 500
    assert stages["intent"].output_tokens == 200
    assert stages["writer"].llm_calls == 1
    assert stages["writer"].input_tokens == 2000
    assert stages["review_iter_1"].llm_calls == 2

    # Per-stage list is sorted by cost descending; writer (2000 input + 800 output
    # on opus-4.7) is the most expensive.
    assert summary.per_stage[0].stage == "writer"


# ----------------------------------------------------------------------
# 4. p50/p95 latency


def test_p50_p95_latency_computation(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    # 11 latencies all in the same stage so percentile is over a known set.
    latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100]
    _write_jsonl(
        p,
        [
            _llm_event(
                current_stage="writer",
                latency_ms=float(lat),
                input_tokens=10,
                output_tokens=5,
            )
            for lat in latencies
        ],
    )

    summary = parse_trace_file(p)

    assert len(summary.per_stage) == 1
    writer = summary.per_stage[0]
    assert writer.llm_calls == 11
    assert writer.latency_ms_total == sum(latencies)
    # Median of 11 sorted values is the 6th (index 5) = 600.
    assert writer.latency_ms_p50 == pytest.approx(600.0, abs=1.0)
    # p95 linear-interp: k = (11-1)*0.95 = 9.5 → between s[9]=1000 and s[10]=1100
    # → 1000 * 0.5 + 1100 * 0.5 = 1050.
    assert writer.latency_ms_p95 == pytest.approx(1050.0, abs=1.0)


# ----------------------------------------------------------------------
# 5. Unknown model


def test_unknown_model_does_not_crash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    p = tmp_path / "trace.jsonl"
    _write_jsonl(
        p,
        [
            _llm_event(
                model="some-unreleased-model-9000",
                input_tokens=10_000,
                output_tokens=5_000,
            )
        ],
    )

    with caplog.at_level(logging.WARNING, logger="devloop.tools.cost_summary"):
        summary = parse_trace_file(p)

    # Cost should be zero (no pricing entry) but the call must still be counted.
    assert summary.total_llm_calls == 1
    assert summary.total_input_tokens == 10_000
    assert summary.total_output_tokens == 5_000
    assert summary.total_estimated_cost_usd == 0.0
    assert "some-unreleased-model-9000" in summary.per_model
    assert summary.per_model["some-unreleased-model-9000"].estimated_cost_usd == 0.0
    # A warning was emitted naming the offending model.
    assert any(
        "some-unreleased-model-9000" in record.getMessage()
        for record in caplog.records
    ), f"expected warning about unknown model in caplog; got: {[r.getMessage() for r in caplog.records]}"


# ----------------------------------------------------------------------
# 6. Markdown rendering


def test_render_summary_markdown_format(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_jsonl(
        p,
        [
            _llm_event(
                current_stage="writer",
                model="claude-opus-4.7",
                input_tokens=1000,
                output_tokens=500,
                latency_ms=1500.0,
            ),
            _llm_event(
                current_stage="review_iter_1",
                model="gpt-5.5",
                input_tokens=200,
                output_tokens=100,
                latency_ms=500.0,
            ),
        ],
    )
    summary = parse_trace_file(p)

    md = render_summary_markdown(summary)

    # Headings present
    assert md.startswith("# Cost summary")
    assert "## Per stage" in md
    assert "## Per model" in md
    # All buckets show up
    assert "writer" in md
    assert "review_iter_1" in md
    assert "claude-opus-4.7" in md
    assert "gpt-5.5" in md
    # Table header
    assert "| Stage |" in md
    assert "| Model |" in md
    # Totals line uses dollar formatting
    assert "Total estimated cost" in md
    assert "$" in md


# ----------------------------------------------------------------------
# 7. JSON rendering


def test_render_summary_json_format(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_jsonl(
        p,
        [
            _llm_event(
                current_stage="writer",
                model="claude-opus-4.7",
                input_tokens=1000,
                output_tokens=500,
            ),
            _llm_event(
                current_stage="review_iter_1",
                model="gpt-5.5",
                input_tokens=200,
                output_tokens=100,
            ),
        ],
    )
    summary = parse_trace_file(p)

    js = render_summary_json(summary)
    parsed = json.loads(js)

    assert parsed["run_id"] == "r1"
    assert parsed["total_llm_calls"] == 2
    assert parsed["total_input_tokens"] == 1200
    assert parsed["total_output_tokens"] == 600
    assert isinstance(parsed["per_stage"], list)
    assert isinstance(parsed["per_model"], dict)
    # Each stage entry has the full StageCost shape.
    stage = parsed["per_stage"][0]
    for field in (
        "stage",
        "llm_calls",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "latency_ms_total",
        "latency_ms_p50",
        "latency_ms_p95",
    ):
        assert field in stage, f"missing field {field!r} in per_stage entry"
    # per_model preserves the same shape.
    assert set(parsed["per_model"].keys()) == {"claude-opus-4.7", "gpt-5.5"}
    assert "estimated_cost_usd" in parsed["per_model"]["claude-opus-4.7"]


# ----------------------------------------------------------------------
# 8. Per-model grouping


def test_per_model_grouping(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_jsonl(
        p,
        [
            _llm_event(
                current_stage="writer",
                model="claude-opus-4.7",
                input_tokens=1000,
                output_tokens=500,
                latency_ms=1000.0,
            ),
            _llm_event(
                current_stage="writer",
                model="claude-opus-4.7",
                input_tokens=2000,
                output_tokens=1000,
                latency_ms=2000.0,
            ),
            _llm_event(
                current_stage="review_iter_1",
                model="gpt-5.5",
                input_tokens=500,
                output_tokens=200,
                latency_ms=400.0,
            ),
            _llm_event(
                current_stage="review_iter_1",
                model="gpt-5.4",
                input_tokens=300,
                output_tokens=100,
                latency_ms=300.0,
            ),
        ],
    )

    summary = parse_trace_file(p)

    assert set(summary.per_model.keys()) == {"claude-opus-4.7", "gpt-5.5", "gpt-5.4"}
    opus = summary.per_model["claude-opus-4.7"]
    assert opus.llm_calls == 2
    assert opus.input_tokens == 3000
    assert opus.output_tokens == 1500
    expected_opus_cost = (
        3000 * PRICING["claude-opus-4.7"]["input"] / 1_000_000
        + 1500 * PRICING["claude-opus-4.7"]["output"] / 1_000_000
    )
    assert opus.estimated_cost_usd == pytest.approx(expected_opus_cost, rel=1e-6)
    # latency_ms_total aggregates across both calls.
    assert opus.latency_ms_total == 3000

    # The two single-call models are bucketed independently.
    assert summary.per_model["gpt-5.5"].llm_calls == 1
    assert summary.per_model["gpt-5.4"].llm_calls == 1


# ----------------------------------------------------------------------
# Extra: backward-compat fallback (no current_stage field)


def test_stage_falls_back_to_legacy_field_when_current_stage_absent(
    tmp_path: Path,
) -> None:
    """Older traces predating Sprint D have no current_stage field; the parser
    should fall back to the fine-grained per-call `stage` field instead of
    bucketing everything as 'unknown'."""
    p = tmp_path / "trace.jsonl"
    events = [
        {
            "type": "llm_call",
            "run_id": "old-run",
            "stage": "writer.initial",
            "model": "claude-opus-4.7",
            "latency_ms": 100.0,
            "usage": {"input_tokens": 50, "output_tokens": 25},
        },
        {
            "type": "llm_call",
            "run_id": "old-run",
            "stage": "review.security",
            "model": "claude-opus-4.7",
            "latency_ms": 80.0,
            "usage": {"input_tokens": 30, "output_tokens": 10},
        },
    ]
    _write_jsonl(p, events)

    summary = parse_trace_file(p)

    stages = {s.stage for s in summary.per_stage}
    assert stages == {"writer.initial", "review.security"}


# ----------------------------------------------------------------------
# Extra: missing trace file raises


def test_missing_trace_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_trace_file(tmp_path / "no_such_trace.jsonl")
