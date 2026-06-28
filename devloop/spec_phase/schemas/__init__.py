"""Schema package exports."""

from devloop.spec_phase.schemas.approach import (
    ApproachEvaluation,
    CandidatePlan,
    SelectedApproach,
    TradeoffEvaluation,
)
from devloop.spec_phase.schemas.common import (
    SCHEMA_VERSION,
    CodeRef,
    ImportanceLevel,
    IntentType,
    PerspectiveType,
    PlanType,
    Priority,
    RequirementType,
    ReviewerType,
    ScopeType,
    Severity,
    Verdict,
)
from devloop.spec_phase.schemas.exploration import (
    Conflict,
    ConsolidatedExploration,
    HypothesisCheck,
    Perspective,
    RelevantArtifact,
)
from devloop.spec_phase.schemas.intent import (
    ConfirmedIntent,
    ExcludedHypothesis,
    Hypothesis,
    HypothesisVerdict,
    SkepticChallenge,
)
from devloop.spec_phase.schemas.review import (
    ConcernVerdict,
    ConsolidatedReview,
    MetaReviewResult,
    PrioritizedAction,
    ReviewIssue,
    ReviewResult,
)
from devloop.spec_phase.schemas.spec import (
    AcceptanceScenario,
    BlockingDecision,
    Concern,
    EdgeCase,
    Entity,
    FunctionalRequirement,
    Spec,
    SpecMetadata,
    SpecSegmentFRs,
    SpecSegmentHead,
    SpecSegmentSCs,
    SpecSegmentStories,
    SpecSegmentTail,
    SuccessCriterion,
    UserStory,
)

__all__ = [
    "SCHEMA_VERSION",
    # spec
    "AcceptanceScenario",
    "ApproachEvaluation",
    "BlockingDecision",
    # approach
    "CandidatePlan",
    # common
    "CodeRef",
    "Concern",
    "ConcernVerdict",
    "ConfirmedIntent",
    "Conflict",
    "ConsolidatedExploration",
    "ConsolidatedReview",
    "EdgeCase",
    "Entity",
    "ExcludedHypothesis",
    "FunctionalRequirement",
    # intent
    "Hypothesis",
    "HypothesisCheck",
    "HypothesisVerdict",
    "ImportanceLevel",
    "IntentType",
    "MetaReviewResult",
    "Perspective",
    "PerspectiveType",
    "PlanType",
    "PrioritizedAction",
    "Priority",
    # exploration
    "RelevantArtifact",
    "RequirementType",
    # review
    "ReviewIssue",
    "ReviewResult",
    "ReviewerType",
    "ScopeType",
    "SelectedApproach",
    "Severity",
    "SkepticChallenge",
    "Spec",
    "SpecMetadata",
    "SpecSegmentFRs",
    "SpecSegmentHead",
    "SpecSegmentSCs",
    "SpecSegmentStories",
    "SpecSegmentTail",
    "SuccessCriterion",
    "TradeoffEvaluation",
    "UserStory",
    "Verdict",
]
