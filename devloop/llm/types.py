"""Provider-agnostic types for the LLM gateway."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class Message(BaseModel):
    """A single message in a conversation."""

    role: Role
    content: str | list[dict[str, Any]]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ToolSpec(BaseModel):
    """Provider-agnostic tool/function definition.

    Internally converted to Anthropic tool format or OpenAI tools schema.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = Field(
        ...,
        description="JSON Schema for the tool's input arguments",
    )


class ToolCall(BaseModel):
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """Result of executing a tool call."""

    tool_call_id: str
    name: str
    content: str = Field(..., description="String representation of the tool output")
    is_error: bool = False


class Usage(BaseModel):
    """Token usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class LLMResponse(BaseModel):
    """Provider-agnostic LLM response."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
