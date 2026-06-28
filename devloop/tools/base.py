"""Base tool interface and shared context."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devloop.cache import CacheBackend, NullCache
from devloop.llm.types import ToolCall, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class AgentScratchpad:
    """Mutable scratchpad shared by an agent's tools.

    Used by output tools (mark_as_relevant / take_note / flag_issue) to
    accumulate state without round-tripping through LLM responses.
    """

    relevant_artifacts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    arbitrary: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    """Per-call context passed to every tool.

    Provides repo path, cache, scratchpad, and metadata for tracing.
    """

    repo_path: Path
    commit_hash: str
    scratchpad: AgentScratchpad
    cache: CacheBackend = field(default_factory=NullCache)
    run_id: str = ""
    agent_name: str = ""
    enable_cache: bool = True


class BaseTool(ABC):
    """All tools implement this minimal contract."""

    name: str
    description: str
    input_schema: dict[str, Any]

    # Default: tools are cacheable by their args within a commit
    cacheable: bool = True

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        """Run the tool. Return a string the LLM can read."""


ToolExecutor = Callable[[ToolCall], Awaitable[ToolResult]]
