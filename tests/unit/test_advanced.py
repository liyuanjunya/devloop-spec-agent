"""Tests targeting specific advanced behaviors: review-rewrite loop, no-progress
termination, max-iter hard cap, ReAct loop, trace concurrency, explorer partial
failure, strict-json repair, tool budget.

These tests focus on individual components (or narrow orchestrator slices) so
they can exercise paths that the broad-strokes pipeline integration test in
`tests/integration/test_orchestrator_mock.py` skips for brevity.
"""

from __future__ import annotations

import json
import threading

import pytest
from pydantic import BaseModel

from devloop.cache import NullCache
from devloop.llm.gateway import LLMGateway
from devloop.llm.json_helpers import call_react_with_tools, call_strict_json
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import TraceWriter
from devloop.llm.types import LLMResponse, Message, ToolCall, ToolResult, ToolSpec, Usage
from devloop.tools import AgentRole, AgentScratchpad, ToolContext, build_default_registry
from tests.fixtures.mock_provider import (
    MockProvider,
    make_json_response,
    make_text_response,
    make_tool_call_response,
)

# ============================================================================
# call_react_with_tools
# ============================================================================


async def test_react_loop_terminates_on_no_tool_calls():
    """If the LLM stops calling tools, the ReAct loop must terminate immediately."""
    handler_state = {"calls": 0}

    def handler(*_a, **_kw):
        handler_state["calls"] += 1
        return make_text_response("Done — no more tools needed.")

    provider = MockProvider("anthropic", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": provider, "openai": MockProvider("openai", handler)},
        router=router,
    )

    async def executor(_tc):
        raise AssertionError("executor should not be called when LLM doesn't call tools")

    final_text, calls = await call_react_with_tools(
        gateway,
        role="role",
        messages=[Message(role="user", content="go")],
        system="sys",
        tools=[],
        tool_executor=executor,
        max_iterations=5,
    )
    assert "Done" in final_text
    assert calls == 0
    assert handler_state["calls"] == 1


async def test_react_loop_executes_and_terminates():
    """LLM calls one tool then provides final text."""
    state = {"step": 0}

    def handler(model, system, messages, tools, response_format):
        state["step"] += 1
        if state["step"] == 1:
            return make_tool_call_response(
                name="file_read", arguments={"path": "x.py"}
            )
        return make_text_response("All good. EXPLORATION COMPLETE.")

    provider = MockProvider("anthropic", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": provider, "openai": MockProvider("openai", handler)},
        router=router,
    )

    exec_calls: list[ToolCall] = []

    async def executor(tc: ToolCall) -> ToolResult:
        exec_calls.append(tc)
        return ToolResult(tool_call_id=tc.id, name=tc.name, content="file contents")

    final_text, calls = await call_react_with_tools(
        gateway,
        role="role",
        messages=[Message(role="user", content="go")],
        system="sys",
        tools=[ToolSpec(name="file_read", description="r", input_schema={"type": "object"})],
        tool_executor=executor,
        max_iterations=10,
    )
    assert "All good" in final_text
    assert calls == 1
    assert len(exec_calls) == 1
    assert exec_calls[0].name == "file_read"


async def test_react_loop_max_iterations_cap():
    """If LLM never stops calling tools, loop terminates at max_iterations."""

    def handler(*_a, **_kw):
        return make_tool_call_response(name="x", arguments={})

    provider = MockProvider("anthropic", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": provider, "openai": MockProvider("openai", handler)},
        router=router,
    )

    async def executor(tc):
        return ToolResult(tool_call_id=tc.id, name=tc.name, content="ok")

    _, calls = await call_react_with_tools(
        gateway,
        role="role",
        messages=[Message(role="user", content="go")],
        system="sys",
        tools=[ToolSpec(name="x", description="x", input_schema={"type": "object"})],
        tool_executor=executor,
        max_iterations=4,
    )
    assert calls == 4  # one tool per iteration


# ============================================================================
# call_strict_json repair
# ============================================================================


class TinyOut(BaseModel):
    name: str
    count: int


async def test_strict_json_first_response_invalid_then_fixed():
    state = {"attempt": 0}

    def handler(model, system, messages, tools, response_format):
        state["attempt"] += 1
        if state["attempt"] == 1:
            return make_text_response("not json at all")
        return make_json_response({"name": "ok", "count": 7})

    provider = MockProvider("anthropic", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": provider, "openai": MockProvider("openai", handler)},
        router=router,
    )
    result = await call_strict_json(
        gateway,
        role="role",
        schema=TinyOut,
        messages=[Message(role="user", content="go")],
        max_repair_attempts=3,
    )
    assert result.name == "ok"
    assert result.count == 7
    assert state["attempt"] == 2


async def test_strict_json_gives_up_after_attempts():
    def handler(*_a, **_kw):
        return make_text_response("never json")

    provider = MockProvider("anthropic", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": provider, "openai": MockProvider("openai", handler)},
        router=router,
    )
    with pytest.raises(ValueError, match="failed after"):
        await call_strict_json(
            gateway,
            role="role",
            schema=TinyOut,
            messages=[Message(role="user", content="go")],
            max_repair_attempts=1,
        )


# ============================================================================
# TraceWriter concurrency
# ============================================================================


def test_trace_writer_concurrent_writes(tmp_path):
    path = tmp_path / "trace.jsonl"
    tw = TraceWriter(path)
    n_threads = 10
    n_per_thread = 50

    def writer(tid: int):
        for j in range(n_per_thread):
            tw.record({"thread": tid, "i": j, "type": "test"})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_threads * n_per_thread
    parsed = [json.loads(line) for line in lines]
    assert {p["thread"] for p in parsed} == set(range(n_threads))


# ============================================================================
# Tool budget hard limit
# ============================================================================


async def test_tool_registry_hard_limit_rejects_excess_calls(fixture_repo):
    reg = build_default_registry()
    ctx = ToolContext(
        repo_path=fixture_repo,
        commit_hash="abc",
        scratchpad=AgentScratchpad(),
        cache=NullCache(),
        run_id="t",
        agent_name="test",
        enable_cache=False,
    )
    executor, _ = reg.make_executor(
        ctx,
        role=AgentRole.EXPLORER,
        soft_limit=1,
        hard_limit=2,
    )

    async def call(i):
        tc = ToolCall(id=f"tc{i}", name="list_directory", arguments={"path": "."})
        return await executor(tc)

    r1 = await call(1)
    r2 = await call(2)
    r3 = await call(3)
    assert not r1.is_error
    assert not r2.is_error
    assert r3.is_error
    assert "budget" in r3.content.lower() or "exceeded" in r3.content.lower()


async def test_tool_registry_denies_unauthorized_tool(fixture_repo):
    reg = build_default_registry()
    ctx = ToolContext(
        repo_path=fixture_repo,
        commit_hash="abc",
        scratchpad=AgentScratchpad(),
        cache=NullCache(),
        run_id="t",
        agent_name="test",
        enable_cache=False,
    )
    executor, _ = reg.make_executor(ctx, role=AgentRole.REVIEWER)
    # Reviewer should NOT have mark_as_relevant
    tc = ToolCall(
        id="x",
        name="mark_as_relevant",
        arguments={"path": "x", "importance": "critical", "reason": "r"},
    )
    res = await executor(tc)
    assert res.is_error
    assert "denied" in res.content.lower() or "not available" in res.content.lower()


# ============================================================================
# Counter aggregation through gateway + tools
# ============================================================================


async def test_gateway_run_counter_aggregates_llm_calls():
    def handler(*_a, **_kw):
        return LLMResponse(
            content="hello",
            tool_calls=[],
            stop_reason="end_turn",
            model="m",
            usage=Usage(input_tokens=100, output_tokens=50),
        )

    provider = MockProvider("anthropic", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": provider, "openai": MockProvider("openai", handler)},
        router=router,
    )
    counter = gateway.register_run("run-x")
    await gateway.call(
        role="role",
        messages=[Message(role="user", content="hi")],
        run_id="run-x",
    )
    await gateway.call(
        role="role",
        messages=[Message(role="user", content="hi again")],
        run_id="run-x",
    )
    assert counter["llm_calls"] == 2
    assert counter["input_tokens"] == 200
    assert counter["output_tokens"] == 100
    gateway.unregister_run("run-x")
    assert gateway.get_run_counter("run-x") is None
