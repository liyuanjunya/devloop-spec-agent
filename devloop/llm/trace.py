"""LLM call tracing — every call writes one JSONL line to a per-run trace file."""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# Per-asyncio-task / per-thread stage stack. ContextVar correctly propagates
# across `await`, `asyncio.gather()`, and asyncio.to_thread boundaries, so
# parallel sub-agents launched inside `with trace.stage("exploration"):` all
# see "exploration" as their enclosing stage.
_stage_stack_var: ContextVar[tuple[str, ...]] = ContextVar(
    "devloop_trace_stage_stack", default=()
)


class TraceWriter:
    """Thread-safe JSONL writer for LLM and tool call traces.

    Each `record()` call appends one line atomically and is auto-tagged with
    the innermost active orchestrator stage if one is set via `stage()`:

        with trace.stage("writer"):
            ...  # every record() called inside gets current_stage="writer"
    """

    def __init__(self, trace_path: Path):
        self.path = trace_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Touch
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    # -----------------------------------------------------------------
    # Stage context

    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Push `name` onto the per-task stage stack for the duration of the block.

        Nested stages stack; the innermost name becomes `current_stage` for any
        event recorded inside. The stack is per-async-task / per-thread, so
        parallel work launched inside the block all sees the same enclosing
        stage.
        """
        prev = _stage_stack_var.get()
        token = _stage_stack_var.set((*prev, name))
        try:
            yield
        finally:
            _stage_stack_var.reset(token)

    @property
    def current_stage(self) -> str | None:
        """Innermost active stage name, or None."""
        stack = _stage_stack_var.get()
        return stack[-1] if stack else None

    @property
    def stage_stack(self) -> tuple[str, ...]:
        """Full stage stack, outermost first. Empty tuple if no stage is active."""
        return _stage_stack_var.get()

    # -----------------------------------------------------------------
    # Write

    def record(self, event: dict[str, Any]) -> None:
        """Append `event` to the trace, auto-tagging with `current_stage` if set."""
        if "current_stage" not in event:
            cs = self.current_stage
            if cs is not None:
                event["current_stage"] = cs
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def write_event(self, event: dict[str, Any]) -> None:
        """Alias of `record()` — appends one event to the trace JSONL."""
        self.record(event)

    def record_llm_call(
        self,
        *,
        run_id: str,
        trace_id: str,
        stage: str,
        agent: str,
        provider: str,
        model: str,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        response: dict[str, Any] | None = None,
        latency_ms: float = 0.0,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.record(
            {
                "type": "llm_call",
                "run_id": run_id,
                "trace_id": trace_id,
                "stage": stage,
                "agent": agent,
                "provider": provider,
                "model": model,
                "messages_count": len(messages or []),
                "tools_count": len(tools or []),
                "latency_ms": latency_ms,
                "usage": usage or {},
                "stop_reason": (response or {}).get("stop_reason"),
                "tool_calls_count": len((response or {}).get("tool_calls", [])),
                "error": error,
            }
        )

    def record_tool_call(
        self,
        *,
        run_id: str,
        trace_id: str,
        agent: str,
        tool_name: str,
        arguments: dict[str, Any],
        result_size: int = 0,
        latency_ms: float = 0.0,
        cached: bool = False,
        error: str | None = None,
    ) -> None:
        self.record(
            {
                "type": "tool_call",
                "run_id": run_id,
                "trace_id": trace_id,
                "agent": agent,
                "tool_name": tool_name,
                "arguments": arguments,
                "result_size": result_size,
                "latency_ms": latency_ms,
                "cached": cached,
                "error": error,
            }
        )

    def record_stage_event(
        self,
        *,
        run_id: str,
        stage: str,
        event: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.record(
            {
                "type": "stage_event",
                "run_id": run_id,
                "stage": stage,
                "event": event,
                "detail": detail or {},
            }
        )


class NullTraceWriter(TraceWriter):
    """No-op trace writer for tests."""

    def __init__(self) -> None:
        self.path = Path("/dev/null")
        self._lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> None:
        pass
