"""ToolRegistry — manages all tool implementations and per-agent visibility."""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum

from devloop.llm.trace import TraceWriter
from devloop.llm.types import ToolCall, ToolResult, ToolSpec
from devloop.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


class AgentRole(StrEnum):
    EXPLORER = "explorer"
    WRITER = "writer"
    REVIEWER = "reviewer"
    INTENT_VERIFIER = "intent_verifier"


# Which output tools each role gets
ROLE_OUTPUT_TOOLS = {
    AgentRole.EXPLORER: {"mark_as_relevant", "take_note"},
    AgentRole.WRITER: set(),
    AgentRole.REVIEWER: {"flag_issue"},
    AgentRole.INTENT_VERIFIER: set(),
}


class ToolRegistry:
    """Holds all tools and exposes them by agent role."""

    # 11 code tools shared by Explorer and Reviewer
    CODE_TOOL_NAMES = {
        "code_search",
        "file_read",
        "find_references",
        "find_callees",
        "find_similar_files",
        "list_directory",
        "read_tests",
        "read_docs_and_readme",
        "read_configs",
        "find_data_migrations",
        "git_log",
        "git_blame",
    }

    OUTPUT_TOOL_NAMES = {"mark_as_relevant", "take_note", "flag_issue"}

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def register_many(self, tools: list[BaseTool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered")
        return self._tools[name]

    def specs_for(self, role: AgentRole) -> list[ToolSpec]:
        out = []
        for name, tool in self._tools.items():
            if name in self.CODE_TOOL_NAMES:
                out.append(tool.spec())
            elif name in self.OUTPUT_TOOL_NAMES:
                if name in ROLE_OUTPUT_TOOLS.get(role, set()):
                    out.append(tool.spec())
        return out

    def make_executor(
        self,
        ctx: ToolContext,
        *,
        role: AgentRole,
        trace: TraceWriter | None = None,
        soft_limit: int | None = None,
        hard_limit: int | None = None,
        global_counter: dict[str, int] | None = None,
    ):
        """Create an async tool executor closure used by call_react_with_tools.

        Honors soft_limit (warning) and hard_limit (refuse new calls beyond).
        If `global_counter` is provided, every successful tool call increments its
        ``tool_calls`` key.
        """
        allowed = set(self.CODE_TOOL_NAMES) | (ROLE_OUTPUT_TOOLS.get(role, set()))
        counter = {"calls": 0}

        async def executor(tool_call: ToolCall) -> ToolResult:
            counter["calls"] += 1
            n = counter["calls"]
            if hard_limit and n > hard_limit:
                msg = (
                    f"[budget] Tool call limit exceeded ({hard_limit}). "
                    f"Stop calling tools and produce your final answer / summary."
                )
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=msg,
                    is_error=True,
                )
            if soft_limit and n == soft_limit + 1:
                logger.info(
                    "Agent %s exceeded soft tool call limit %d", ctx.agent_name, soft_limit
                )

            if tool_call.name not in allowed:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=f"[denied] Tool '{tool_call.name}' is not available to role '{role.value}'.",
                    is_error=True,
                )

            tool = self._tools.get(tool_call.name)
            if tool is None:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=f"[error] Unknown tool '{tool_call.name}'",
                    is_error=True,
                )

            # Cache lookup (only for cacheable code tools, not output tools)
            cached_used = False
            result_text: str
            t0 = time.perf_counter()
            try:
                if (
                    tool.cacheable
                    and ctx.enable_cache
                    and tool_call.name in self.CODE_TOOL_NAMES
                ):
                    cached = ctx.cache.get_tool(
                        ctx.commit_hash, tool_call.name, tool_call.arguments
                    )
                    if cached is not None:
                        result_text = (
                            cached if isinstance(cached, str) else json.dumps(cached, ensure_ascii=False)
                        )
                        cached_used = True
                    else:
                        result_text = await tool.execute(tool_call.arguments, ctx)
                        ctx.cache.set_tool(
                            ctx.commit_hash, tool_call.name, tool_call.arguments, result_text
                        )
                else:
                    result_text = await tool.execute(tool_call.arguments, ctx)
            except Exception as e:
                logger.exception("Tool %s failed", tool_call.name)
                result_text = f"[error] {type(e).__name__}: {e}"
                latency = (time.perf_counter() - t0) * 1000
                if trace:
                    trace.record_tool_call(
                        run_id=ctx.run_id,
                        trace_id=tool_call.id,
                        agent=ctx.agent_name,
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        result_size=len(result_text),
                        latency_ms=latency,
                        cached=False,
                        error=result_text,
                    )
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=result_text,
                    is_error=True,
                )

            latency = (time.perf_counter() - t0) * 1000
            if trace:
                trace.record_tool_call(
                    run_id=ctx.run_id,
                    trace_id=tool_call.id,
                    agent=ctx.agent_name,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    result_size=len(result_text),
                    latency_ms=latency,
                    cached=cached_used,
                )
            if global_counter is not None:
                global_counter["tool_calls"] = global_counter.get("tool_calls", 0) + 1

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=result_text,
                is_error=False,
            )

        return executor, counter
