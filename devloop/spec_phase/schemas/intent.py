"""Schemas for Stage 1: Deep Intent Understanding."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devloop.spec_phase.schemas.common import SCHEMA_VERSION, IntentType, ScopeType


class Hypothesis(BaseModel):
    """A candidate interpretation of the user's intent."""

    id: str = Field(..., description="H1, H2, ...")
    summary: str = Field(..., description="Concise restatement of what the user might want")
    indicators: list[str] = Field(
        default_factory=list,
        description="Signals from the user input or repo skeleton supporting this hypothesis",
    )
    counter_indicators: list[str] = Field(
        default_factory=list,
        description="Signals against this hypothesis",
    )


class SkepticChallenge(BaseModel):
    """A skeptic question targeted at a specific hypothesis."""

    target_hypothesis_id: str
    question: str
    rationale: str


class HypothesisVerdict(BaseModel):
    """Verifier's verdict on whether a hypothesis is supported by repo evidence."""

    hypothesis_id: str
    verdict: str = Field(..., description="confirmed | rejected | uncertain")
    evidence: str = Field(..., description="Concrete reason from RepoSkeleton or codebase")


class ExcludedHypothesis(BaseModel):
    """A hypothesis that has been ruled out."""

    hypothesis_id: str
    summary: str
    exclusion_reason: str


class ConfirmedIntent(BaseModel):
    """Final, validated intent after the multi-round intent loop."""

    schema_version: str = SCHEMA_VERSION
    primary: str = Field(..., description="The primary user intent in one sentence")
    intent_type: IntentType
    scope: list[ScopeType] = Field(default_factory=list)
    excluded: list[ExcludedHypothesis] = Field(default_factory=list)
    pending_clarification: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    rounds_used: int = 0
