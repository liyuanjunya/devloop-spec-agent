"""Base provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from devloop.llm.types import LLMResponse, Message, ToolResult, ToolSpec


class BaseProvider(ABC):
    """Abstract LLM provider."""

    name: str

    @abstractmethod
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
        """Make an LLM call. Returns a unified LLMResponse."""

    @abstractmethod
    def format_tool_result(self, result: ToolResult) -> Message:
        """Convert a ToolResult into a provider-appropriate Message."""
