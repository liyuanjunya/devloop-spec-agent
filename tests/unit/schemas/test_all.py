"""Tests for pydantic schemas."""


from devloop.spec_phase.schemas import (
    SCHEMA_VERSION,
    BlockingDecision,
    ConfirmedIntent,
    Conflict,
    ConsolidatedExploration,
    ConsolidatedReview,
    Hypothesis,
    Perspective,
    RelevantArtifact,
    ReviewIssue,
    ReviewResult,
    Severity,
    Spec,
    SpecMetadata,
)


def test_schema_version_set():
    assert SCHEMA_VERSION == "1.0"


def test_hypothesis_minimum():
    h = Hypothesis(id="H1", summary="user wants login")
    assert h.id == "H1"
    assert h.indicators == []
    assert h.counter_indicators == []


def test_confirmed_intent_basic():
    intent = ConfirmedIntent(
        primary="Add product comments",
        intent_type="add_feature",
        scope=["backend", "data_model"],
    )
    assert intent.schema_version == "1.0"
    assert intent.confidence == 0.0
    assert intent.rounds_used == 0


def test_relevant_artifact_with_full_fields():
    ra = RelevantArtifact(
        path="app/models/user.py",
        symbols=["User", "User.username"],
        line_ranges=[(1, 30)],
        importance="critical",
        reason="defines User entity",
        snippet="class User: ...",
    )
    assert ra.importance == "critical"


def test_perspective_consolidated_artifacts_roundtrip():
    p = Perspective(
        perspective_type="data",
        relevant_artifacts=[
            RelevantArtifact(
                path="app/models/x.py",
                importance="relevant",
                reason="r",
            )
        ],
    )
    dumped = p.model_dump(mode="json")
    p2 = Perspective.model_validate(dumped)
    assert p2.perspective_type == "data"
    assert len(p2.relevant_artifacts) == 1


def test_consolidated_exploration_helpers():
    ce = ConsolidatedExploration(
        perspectives=[Perspective(perspective_type="data")],
        conflicts=[
            Conflict(perspectives_involved=["data", "api"], description="x")
        ],
    )
    assert len(ce.conflicts) == 1


def test_spec_required_metadata():
    spec = Spec(
        metadata=SpecMetadata(feature_id="x", title="Y"),
        summary="...",
    )
    assert spec.schema_version == "1.0"
    assert spec.metadata.iterations == 0
    assert spec.self_concerns == []
    assert spec.needs_clarification == []


def test_spec_with_blocking_decisions():
    """Convergence learning: when user input materially conflicts with
    existing code, the writer must surface a top-of-spec BlockingDecision
    rather than burying it in self_concerns. Validates schema round-trip."""
    spec = Spec(
        metadata=SpecMetadata(feature_id="x", title="Y"),
        summary="...",
        needs_clarification=[
            BlockingDecision(
                id="NC-001",
                title="Data model: new table vs reuse existing field",
                conflict=(
                    "User input requests new user_favorite_recipe table, "
                    "but UserToRecipe.is_favorite already exists in the code."
                ),
                recommended_default=(
                    "Reuse UserToRecipe.is_favorite; the 2024 migration "
                    "already consolidated favorites there."
                ),
                if_rejected=(
                    "Implement new table with FKs, backfill, and "
                    "dual-read compatibility from UserToRecipe.is_favorite."
                ),
                related_requirements=["FR-001", "US-1", "US-6"],
            )
        ],
    )
    assert len(spec.needs_clarification) == 1
    nc = spec.needs_clarification[0]
    assert nc.id == "NC-001"
    assert "FR-001" in nc.related_requirements

    # Roundtrip
    dumped = spec.model_dump(mode="json")
    assert dumped["needs_clarification"][0]["id"] == "NC-001"
    spec2 = Spec.model_validate(dumped)
    assert spec2.needs_clarification[0].id == "NC-001"


def test_review_result_critical_count_property():
    r = ReviewResult(
        reviewer_type="architecture",
        judge_model="gpt-5.5",
        verdict="fail",
        issues=[
            ReviewIssue(
                id="A1",
                reviewer_type="architecture",
                severity=Severity.CRITICAL,
                location="FR-001",
                description="d",
                evidence="e",
            ),
            ReviewIssue(
                id="A2",
                reviewer_type="architecture",
                severity=Severity.HIGH,
                location="FR-002",
                description="d",
                evidence="e",
            ),
        ],
    )
    assert r.critical_issue_count == 1
    assert r.high_issue_count == 1


def test_consolidated_review_all_pass_helper():
    cr = ConsolidatedReview(
        overall_verdict="pass",
        reviews=[
            ReviewResult(
                reviewer_type="architecture",
                judge_model="m",
                verdict="pass",
            ),
            ReviewResult(
                reviewer_type="completeness",
                judge_model="m",
                verdict="pass",
            ),
        ],
    )
    assert cr.all_pass
    assert not cr.has_critical
