"""Tests for trace analyzer."""

import json

from devloop.llm.trace_analyzer import parse_trace, render_summary_markdown


def test_parse_empty_trace(tmp_path):
    p = tmp_path / "trace.jsonl"
    p.write_text("", encoding="utf-8")
    s = parse_trace(p)
    assert s.total_llm_calls == 0
    assert s.total_tool_calls == 0


def test_parse_full_trace(tmp_path):
    p = tmp_path / "trace.jsonl"
    events = [
        {
            "type": "llm_call",
            "run_id": "r1",
            "stage": "intent.analyzer",
            "agent": "intent_analyzer",
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "latency_ms": 1200.0,
            "usage": {"input_tokens": 1500, "output_tokens": 400},
        },
        {
            "type": "tool_call",
            "run_id": "r1",
            "agent": "explorer_data",
            "tool_name": "file_read",
            "latency_ms": 50.0,
            "cached": False,
        },
        {
            "type": "tool_call",
            "run_id": "r1",
            "agent": "explorer_data",
            "tool_name": "file_read",
            "latency_ms": 5.0,
            "cached": True,
        },
        {
            "type": "llm_call",
            "run_id": "r1",
            "stage": "writer.initial",
            "agent": "writer",
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "latency_ms": 3000.0,
            "usage": {"input_tokens": 10000, "output_tokens": 2000},
            "error": "TimeoutError: x",
        },
    ]
    p.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    s = parse_trace(p)
    assert s.run_id == "r1"
    assert s.total_llm_calls == 2
    assert s.total_tool_calls == 2
    assert s.total_input_tokens == 11500
    assert s.total_output_tokens == 2400
    assert s.total_errors == 1
    assert s.tool_cache_hit_rate == 0.5
    assert "intent.analyzer" in s.per_stage
    assert s.per_tool["file_read"] == 2
    assert s.per_model["claude-opus-4-7"] == 2

    md = render_summary_markdown(s)
    assert "Trace summary" in md
    assert "file_read" in md
    assert "claude-opus-4-7" in md
