"""Mock LLM provider for integration tests — deterministic, no network."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from devloop.llm.providers.base import BaseProvider
from devloop.llm.types import LLMResponse, Message, ToolCall, ToolResult, ToolSpec, Usage


class MockProvider(BaseProvider):
    """Scriptable mock: respond based on the system prompt (which identifies the agent).

    The response handler is a callable mapping (model, system, messages, tools) -> LLMResponse.
    """

    def __init__(self, name: str, handler: Callable):
        self.name = name
        self._handler = handler
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def call(
        self,
        *,
        model: str,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        response_format: str | None = None,
        timeout: float = 120.0,
    ) -> LLMResponse:
        self.call_count += 1
        call_log = {
            "model": model,
            "system_head": system[:300] if system else "",
            "messages_count": len(messages),
            "tools": [t.name for t in (tools or [])],
            "response_format": response_format,
        }
        self.calls.append(call_log)
        return self._handler(model, system, messages, tools, response_format)

    def format_tool_result(self, result: ToolResult) -> Message:
        return Message(
            role="tool",
            tool_call_id=result.tool_call_id,
            name=result.name,
            content=result.content,
        )


def make_text_response(text: str, *, model: str = "mock") -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=[],
        stop_reason="end_turn",
        model=model,
        usage=Usage(input_tokens=10, output_tokens=10),
    )


def make_json_response(data: dict, *, model: str = "mock") -> LLMResponse:
    return make_text_response(json.dumps(data), model=model)


def make_tool_call_response(
    *, name: str, arguments: dict, model: str = "mock"
) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id=f"tc_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments)
        ],
        stop_reason="tool_use",
        model=model,
        usage=Usage(input_tokens=10, output_tokens=10),
    )
