"""Schemas for Stage 6-8: Multi-angle independent review."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devloop.spec_phase.schemas.common import (
    SCHEMA_VERSION,
    ReviewerType,
    Severity,
    Verdict,
)

__all__ = [
    "ConcernVerdict",
    "ConsolidatedReview",
    "MetaReviewResult",
    "PrioritizedAction",
    "ReviewIssue",
    "ReviewResult",
]


class ReviewIssue(BaseModel):
    """A specific, evidence-backed issue found by a reviewer."""

    id: str = Field(..., description="ISSUE-001 etc.")
    reviewer_type: ReviewerType
    severity: Severity
    location: str = Field(
        ..., description="e.g. 'FR-007' or 'spec.md:123' or 'Key Entity Comment'"
    )
    description: str
    evidence: str = Field(
        ...,
        description="Code snippet, file path, or concrete reasoning that supports this issue",
    )
    suggested_action: str | None = None


class ConcernVerdict(BaseModel):
    """Reviewer's verdict on each writer self-concern."""

    concern_location: str
    verdict: str = Field(..., description="resolved | confirmed_problem | uncertain")
    explanation: str


class ReviewResult(BaseModel):
    """Output of one reviewer (one of the 4 base angles, or the optional
    5th adversarial red-team angle)."""

    schema_version: str = SCHEMA_VERSION
    reviewer_type: ReviewerType
    judge_model: str
    verdict: Verdict = Field(..., description="pass | fail | needs_refine")
    issues: list[ReviewIssue] = Field(default_factory=list)
    self_concerns_verdicts: list[ConcernVerdict] = Field(default_factory=list)
    tool_calls_used: int = 0
    summary: str = ""

    @property
    def critical_issue_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def high_issue_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.HIGH)


class ConsolidatedReview(BaseModel):
    """Aggregated outcome across all 4 reviewers."""

    schema_version: str = SCHEMA_VERSION
    reviews: list[ReviewResult] = Field(default_factory=list)
    overall_verdict: Verdict
    total_issues: int = 0
    critical_issues: int = 0

    @property
    def all_pass(self) -> bool:
        return all(r.verdict == "pass" for r in self.reviews)

    @property
    def has_critical(self) -> bool:
        return any(r.critical_issue_count > 0 for r in self.reviews)


class PrioritizedAction(BaseModel):
    """One prioritized action item synthesized by the meta-reviewer.

    The meta-reviewer (B4) reads the 4 independent axis reviews
    (architecture / completeness / executability / consistency), dedupes
    overlapping findings, and emits a single ordered list of actions
    annotated with cross-axis conflict pointers. The rewriter consumes this
    list IN ORDER so it can apply higher-priority fixes first and explicitly
    consider conflicts before changing axes that disagree.
    """

    id: str = Field(..., description="META-001, META-002, ...")
    priority: int = Field(..., ge=1, le=5, description="1 = highest priority, 5 = lowest")
    severity: Severity
    affected_axes: list[ReviewerType] = Field(
        ..., description="Which axes raised this issue (may be merged across reviewers)"
    )
    source_issue_ids: list[str] = Field(
        ..., description="The ReviewIssue.id values this action merges"
    )
    description: str = Field(..., description="What needs to change")
    rationale: str = Field(..., description="Why this priority and severity")
    suggested_action: str = Field(..., description="Concrete action for the rewriter")
    conflicts_with: list[str] = Field(
        default_factory=list,
        description=(
            "META-xxx ids that this action conflicts with "
            "(changing one might break another)"
        ),
    )


class MetaReviewResult(BaseModel):
    """Unified output of the meta-reviewer agent.

    Produced after the 4 axis reviewers run; consumed by the rewriter in
    place of (or alongside) the raw issue list. Resolves "fix one, break
    another" rewriter behaviour by sequencing fixes deliberately and
    flagging cross-axis conflicts up front.
    """

    schema_version: str = SCHEMA_VERSION
    actions: list[PrioritizedAction] = Field(default_factory=list)
    cross_axis_conflicts: list[str] = Field(
        default_factory=list,
        description=(
            "Plain-English notes about places where two reviewers ask for "
            "opposite changes"
        ),
    )
    summary: str = ""
    judge_model: str = ""
