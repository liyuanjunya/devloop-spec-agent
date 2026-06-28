"""OpenAI provider for GPT models."""

from __future__ import annotations

import json
import logging
from typing import Any

import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from devloop.llm.providers.base import BaseProvider
from devloop.llm.types import LLMResponse, Message, ToolCall, ToolResult, ToolSpec, Usage

logger = logging.getLogger(__name__)


MODEL_ALIASES: dict[str, str] = {}


class OpenAIProvider(BaseProvider):
    """OpenAI provider implementation using the official SDK."""

    name = "openai"

    def __init__(self, api_key: str, *, max_retries: int = 3):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIProvider")
        self._client = openai.AsyncOpenAI(api_key=api_key, max_retries=0)
        self._max_retries = max_retries

    def _resolve_model(self, model: str) -> str:
        return MODEL_ALIASES.get(model, model)

    def _convert_tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def _convert_messages(
        self, messages: list[Message], system_override: str
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        if system_override:
            out.append({"role": "system", "content": system_override})
        else:
            # If no override, keep first system message from list (others concatenated)
            sys_parts = [
                m.content for m in messages if m.role == "system" and isinstance(m.content, str)
            ]
            if sys_parts:
                out.append({"role": "system", "content": "\n\n".join(sys_parts)})

        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or "",
                        "content": m.content
                        if isinstance(m.content, str)
                        else json.dumps(m.content),
                    }
                )
                continue
            if m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content if isinstance(m.content, str) else None,
                        "tool_calls": [
                            {
                                "id": tc.get("id"),
                                "type": "function",
                                "function": {
                                    "name": tc.get("name"),
                                    "arguments": json.dumps(tc.get("arguments", {})),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
                continue
            # Plain text user/assistant
            out.append(
                {
                    "role": m.role,
                    "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
                }
            )
        return out

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
        msgs = self._convert_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._resolve_model(model),
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": timeout,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["tool_choice"] = "auto"
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(
                (
                    openai.APIConnectionError,
                    openai.APITimeoutError,
                    openai.RateLimitError,
                    openai.APIStatusError,
                )
            ),
            reraise=True,
        )
        async def _call_with_retry() -> Any:
            return await self._client.chat.completions.create(**kwargs)

        try:
            resp = await _call_with_retry()
        except Exception as e:
            logger.exception("OpenAI call failed after retries: %s", e)
            raise

        choice = resp.choices[0]
        message = choice.message
        content_text = message.content or ""
        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage = Usage(
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason or "",
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
