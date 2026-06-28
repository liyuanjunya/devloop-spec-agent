"""Schemas for Stage 2: Multi-Perspective Exploration."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devloop.spec_phase.schemas.common import (
    SCHEMA_VERSION,
    ImportanceLevel,
    PerspectiveType,
)


class RelevantArtifact(BaseModel):
    """A specific code location an Explorer marked as relevant.

    Granularity is at symbol/line level — not whole-file — so the Writer
    can cite precise FR references.
    """

    path: str = Field(..., description="Repo-relative path")
    symbols: list[str] = Field(default_factory=list, description="e.g. ['User.username']")
    line_ranges: list[tuple[int, int]] = Field(
        default_factory=list, description="Inclusive line ranges [(45,67), ...]"
    )
    importance: ImportanceLevel
    reason: str = Field(..., description="Why this is relevant")
    snippet: str = Field("", description="Key code snippet, ≤30 lines")


class HypothesisCheck(BaseModel):
    """An exploration-time check against an intent hypothesis."""

    hypothesis_id: str
    verdict: str = Field(..., description="confirmed | rejected | refined")
    evidence: str


class Perspective(BaseModel):
    """Output of one explorer (data, api, ui, test, or history)."""

    schema_version: str = SCHEMA_VERSION
    perspective_type: PerspectiveType
    relevant_artifacts: list[RelevantArtifact] = Field(default_factory=list)
    conventions_discovered: list[str] = Field(default_factory=list)
    hypotheses_checked: list[HypothesisCheck] = Field(default_factory=list)
    notable_findings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    iterations_used: int = 0
    tool_calls_used: int = 0


class Conflict(BaseModel):
    """An inconsistency between two perspectives."""

    perspectives_involved: list[PerspectiveType]
    description: str
    resolution_suggestion: str | None = None


class ConsolidatedExploration(BaseModel):
    """Output of the consolidator merging all perspectives."""

    schema_version: str = SCHEMA_VERSION
    perspectives: list[Perspective] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    consolidated_artifacts: list[RelevantArtifact] = Field(default_factory=list)
    consolidated_conventions: list[str] = Field(default_factory=list)
    summary: str = Field("", description="High-level summary of what we found")
