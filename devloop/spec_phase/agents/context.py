"""Shared agent base context object passed through stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devloop.cache import CacheBackend
from devloop.config import Settings
from devloop.llm import LLMGateway, TraceWriter
from devloop.spec_phase.prompts_loader import PromptLoader
from devloop.spec_phase.repo_skeleton import RepoSkeleton, RepoSkeletonBuilder
from devloop.spec_phase.schemas import (
    ConfirmedIntent,
    ConsolidatedExploration,
    ConsolidatedReview,
    PerspectiveType,
    SelectedApproach,
    Spec,
)
from devloop.tools import ToolRegistry


@dataclass
class SpecContext:
    """The end-to-end context passed across stages.

    Each stage reads what it needs and writes its output back to this object.
    """

    run_id: str
    user_input: str
    repo_path: Path
    workspace_root: Path

    # Infra
    settings: Settings
    gateway: LLMGateway
    tools: ToolRegistry
    prompts: PromptLoader
    cache: CacheBackend
    trace: TraceWriter
    skeleton_builder: RepoSkeletonBuilder

    # Stage outputs
    repo_skeleton: RepoSkeleton | None = None
    intent: ConfirmedIntent | None = None
    active_perspectives: list[PerspectiveType] | None = None
    exploration: ConsolidatedExploration | None = None
    approach: SelectedApproach | None = None
    spec: Spec | None = None
    consolidated_review: ConsolidatedReview | None = None

    # Aggregates
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    iterations: int = 0
    run_counter: dict[str, int] | None = None  # shared with LLMGateway, updated per call

    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def commit_hash(self) -> str:
        return self.repo_skeleton.commit_hash if self.repo_skeleton else ""

    @property
    def run_workspace(self) -> Path:
        return self.workspace_root / self.run_id
