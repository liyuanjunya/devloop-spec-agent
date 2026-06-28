"""Anthropic provider for Claude models.

Notes
-----
* Real Anthropic model IDs include a date suffix (e.g. ``claude-3-5-sonnet-20241022``).
  We pass the user-provided model name through unchanged — callers are responsible
  for using the actual model ID. The ``MODEL_ALIASES`` dict is intentionally empty
  to avoid silently misrouting to a non-existent model.
* When ``system`` exceeds a few thousand characters we mark it for ephemeral
  prompt caching (``cache_control = ephemeral``) which can reduce input cost up
  to 90% on repeated runs (per Anthropic's 2025 prompt caching docs).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from devloop.llm.providers.base import BaseProvider
from devloop.llm.types import LLMResponse, Message, ToolCall, ToolResult, ToolSpec, Usage

logger = logging.getLogger(__name__)


# Empty by default — pass-through user-provided model IDs. Add entries only when
# Anthropic publishes a stable alias.
MODEL_ALIASES: dict[str, str] = {}

# Prompt-cache threshold: cache system prompts longer than this many chars.
_PROMPT_CACHE_THRESHOLD = 2000


class AnthropicProvider(BaseProvider):
    """Anthropic provider implementation using the official SDK."""

    name = "anthropic"

    def __init__(self, api_key: str, *, max_retries: int = 3, enable_prompt_cache: bool = True):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for AnthropicProvider")
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self._max_retries = max_retries
        self._enable_prompt_cache = enable_prompt_cache

    def _resolve_model(self, model: str) -> str:
        return MODEL_ALIASES.get(model, model)

    def _convert_tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                # System content is passed separately in Anthropic API
                continue
            if m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.content
                                if isinstance(m.content, str)
                                else json.dumps(m.content),
                            }
                        ],
                    }
                )
                continue
            if m.role == "assistant" and m.tool_calls:
                blocks: list[dict[str, Any]] = []
                if isinstance(m.content, str) and m.content:
                    blocks.append({"type": "text", "text": m.content})
                for call in m.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id"),
                            "name": call.get("name"),
                            "input": call.get("arguments", {}),
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                continue
            if isinstance(m.content, list):
                out.append({"role": m.role, "content": m.content})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _extract_system(self, messages: list[Message], explicit_system: str) -> str:
        if explicit_system:
            return explicit_system
        sys_parts = [
            m.content for m in messages if m.role == "system" and isinstance(m.content, str)
        ]
        return "\n\n".join(sys_parts)

    def _system_block(self, system: str) -> Any:
        """Wrap system into a content-blocks list with cache_control when long enough."""
        if not system:
            return None
        if self._enable_prompt_cache and len(system) >= _PROMPT_CACHE_THRESHOLD:
            return [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return system

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
        sys = self._extract_system(messages, system)
        msgs = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._resolve_model(model),
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": timeout,
        }
        sys_block = self._system_block(sys)
        if sys_block is not None:
            kwargs["system"] = sys_block
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["tool_choice"] = {"type": "auto"}

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(
                (
                    anthropic.APIConnectionError,
                    anthropic.APITimeoutError,
                    anthropic.RateLimitError,
                    anthropic.APIStatusError,
                )
            ),
            reraise=True,
        )
        async def _call_with_retry() -> Any:
            return await self._client.messages.create(**kwargs)

        try:
            resp = await _call_with_retry()
        except Exception as e:
            logger.exception("Anthropic call failed after retries: %s", e)
            raise

        content_text = ""
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                content_text += block.text
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                    )
                )

        usage = Usage(
            input_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "",
            model=resp.model,
            usage=usage,
            raw=None,
        )

    def format_tool_result(self, result: ToolResult) -> Message:
        return Message(
            role="tool",
            tool_call_id=result.tool_call_id,
            name=result.name,
            content=result.content,
        )
