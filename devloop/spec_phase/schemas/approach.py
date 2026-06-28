"""Schemas for Stage 3: Plan Brainstorm + Evaluation + Selection."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devloop.spec_phase.schemas.common import SCHEMA_VERSION, PlanType


class CandidatePlan(BaseModel):
    """One candidate approach (conservative / balanced / aggressive)."""

    plan_type: PlanType
    summary: str = Field(..., description="High-level description in 2-4 sentences")
    key_changes: list[str] = Field(
        default_factory=list,
        description="Bullet list of major changes this plan introduces",
    )
    reuses_existing: list[str] = Field(
        default_factory=list,
        description="Existing components/code this plan reuses",
    )
    new_components: list[str] = Field(
        default_factory=list, description="New components this plan adds"
    )
    estimated_effort: str = Field("", description="rough effort qualitative estimate")
    risks: list[str] = Field(default_factory=list)


class TradeoffEvaluation(BaseModel):
    """Cross-company evaluator's tradeoff assessment for one plan."""

    plan_type: PlanType
    implementation_effort: str
    architectural_fit: str
    long_term_maintainability: str
    user_story_coverage: str
    overall_recommendation: str = Field(..., description="prefer | acceptable | discouraged")
    rationale: str


class ApproachEvaluation(BaseModel):
    """Evaluator output across all candidates."""

    schema_version: str = SCHEMA_VERSION
    evaluations: list[TradeoffEvaluation] = Field(default_factory=list)
    pairwise_winner: PlanType | None = None
    judge_model: str = ""


class SelectedApproach(BaseModel):
    """Selector output: chosen primary plan + integrated strengths."""

    schema_version: str = SCHEMA_VERSION
    primary_plan: CandidatePlan
    integrated_strengths_from_others: list[str] = Field(default_factory=list)
    rationale: str = Field(..., description="Why this plan was selected")
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    evaluation: ApproachEvaluation | None = None
