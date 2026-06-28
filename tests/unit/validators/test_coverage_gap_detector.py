"""Tests for the cross-perspective coverage-gap detector (DevLoop Sprint B — B2)."""

from __future__ import annotations

import pytest

from devloop.spec_phase.schemas import (
    Conflict,
    ConsolidatedExploration,
    Perspective,
    PerspectiveType,
    RelevantArtifact,
)
from devloop.spec_phase.validators.coverage_gap_detector import (
    GAP_SINGLETON_CRITICAL,
    GAP_SPARSE_PERSPECTIVE,
    GAP_UNRESOLVED_CONFLICT,
    MIN_CONFLICT_DESCRIPTION_LEN,
    SPARSE_SIBLING_THRESHOLD,
    VALID_GAP_KINDS,
    CoverageGap,
    detect_coverage_gaps,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _artifact(
    path: str,
    *,
    importance: str = "critical",
    symbols: list[str] | None = None,
    reason: str = "matters because reasons",
) -> RelevantArtifact:
    return RelevantArtifact(
        path=path,
        symbols=symbols or [],
        line_ranges=[(1, 30)],
        importance=importance,  # type: ignore[arg-type]
        reason=reason,
    )


def _perspective(
    ptype: PerspectiveType,
    *,
    artifacts: list[RelevantArtifact] | None = None,
) -> Perspective:
    return Perspective(
        perspective_type=ptype,
        relevant_artifacts=artifacts or [],
    )


def _exploration(
    perspectives: list[Perspective] | None = None,
    *,
    conflicts: list[Conflict] | None = None,
) -> ConsolidatedExploration:
    return ConsolidatedExploration(
        perspectives=perspectives or [],
        conflicts=conflicts or [],
    )


def _populated_perspective(
    ptype: PerspectiveType,
    *,
    n: int = SPARSE_SIBLING_THRESHOLD,
    path_prefix: str = "src/",
    importance: str = "relevant",
) -> Perspective:
    """Build a perspective with ``n`` distinct non-singleton-triggering artifacts."""
    return _perspective(
        ptype,
        artifacts=[
            _artifact(f"{path_prefix}{ptype}_{i}.py", importance=importance)
            for i in range(n)
        ],
    )


# ---------------------------------------------------------------------------
# 1. test_no_gaps_when_artifacts_well_covered
# ---------------------------------------------------------------------------


def test_no_gaps_when_artifacts_well_covered():
    """A critical artifact surfaced by multiple perspectives is not flagged."""
    shared = "app/models/recipe.py"
    exploration = _exploration(
        perspectives=[
            _perspective(
                "data",
                artifacts=[
                    _artifact(shared, importance="critical", reason="data side"),
                    _artifact("app/models/extra.py", importance="critical"),
                ],
            ),
            _perspective(
                "api",
                artifacts=[
                    _artifact(shared, importance="critical", reason="api side"),
                    _artifact("app/api/extras.py", importance="critical"),
                ],
            ),
            _perspective(
                "ui",
                artifacts=[
                    _artifact(shared, importance="critical", reason="ui side"),
                    _artifact("app/ui/extras.tsx", importance="critical"),
                ],
            ),
            _perspective(
                "test",
                artifacts=[
                    _artifact(shared, importance="critical", reason="test side"),
                    _artifact("tests/test_extra.py", importance="critical"),
                ],
            ),
            _perspective(
                "history",
                artifacts=[
                    _artifact(shared, importance="critical", reason="history side"),
                    _artifact("docs/CHANGELOG.md", importance="critical"),
                ],
            ),
        ]
    )

    gaps = detect_coverage_gaps(exploration)

    # The shared critical artifact is well-covered (5 perspectives) — no gap.
    # All the per-perspective `extras` ARE singletons; this test exists to
    # demonstrate the well-covered case, so verify the shared one is *not*
    # in the singleton gap list specifically.
    singleton_paths = {
        g.suggested_re_explore_question
        for g in gaps
        if g.kind == GAP_SINGLETON_CRITICAL and shared in g.suggested_re_explore_question
    }
    assert singleton_paths == set()


# ---------------------------------------------------------------------------
# 2. test_singleton_critical_detected
# ---------------------------------------------------------------------------


def test_singleton_critical_detected():
    """A critical artifact surfaced by exactly one perspective IS a gap."""
    secret_path = "mealie/routes/explore/controller_public_recipes.py"
    exploration = _exploration(
        perspectives=[
            _perspective("data"),
            _perspective(
                "api",
                artifacts=[
                    _artifact(
                        secret_path,
                        importance="critical",
                        symbols=["PublicRecipesController"],
                        reason="Public endpoints for unauthenticated access",
                    ),
                ],
            ),
            _perspective("ui"),
            _perspective("test"),
            _perspective("history"),
        ]
    )

    gaps = detect_coverage_gaps(exploration)

    singleton_gaps = [g for g in gaps if g.kind == GAP_SINGLETON_CRITICAL]
    assert len(singleton_gaps) == 1
    g = singleton_gaps[0]
    assert secret_path in g.detail
    assert "api" in g.detail
    assert g.primary_perspective == "api"
    assert "PublicRecipesController" in g.detail


# ---------------------------------------------------------------------------
# 3. test_singleton_relevant_artifact_ok
# ---------------------------------------------------------------------------


def test_singleton_relevant_artifact_ok():
    """A *relevant* (non-critical) artifact surfaced once is NOT a gap."""
    exploration = _exploration(
        perspectives=[
            _perspective(
                "data",
                artifacts=[
                    _artifact(
                        "app/utils/helpers.py",
                        importance="relevant",
                        reason="convenience helper",
                    ),
                ],
            ),
            _perspective("api"),
            _perspective("ui"),
            _perspective("test"),
            _perspective("history"),
        ]
    )

    gaps = detect_coverage_gaps(exploration)
    assert [g for g in gaps if g.kind == GAP_SINGLETON_CRITICAL] == []


# ---------------------------------------------------------------------------
# 4. test_unresolved_conflict_detected
# ---------------------------------------------------------------------------


def test_unresolved_conflict_detected():
    """A conflict with a non-trivial description AND no resolution IS a gap."""
    exploration = _exploration(
        perspectives=[
            _populated_perspective("data"),
            _populated_perspective("api"),
        ],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "history"],
                description=(
                    "Data explorer says Alembic is the migration tool, but "
                    "history found commit 'deprecate Alembic, use Django'."
                ),
                resolution_suggestion=None,
            )
        ],
    )

    gaps = detect_coverage_gaps(exploration)
    unresolved = [g for g in gaps if g.kind == GAP_UNRESOLVED_CONFLICT]
    assert len(unresolved) == 1
    assert "Alembic" in unresolved[0].detail
    assert "data" in unresolved[0].detail and "history" in unresolved[0].detail


# ---------------------------------------------------------------------------
# 5. test_resolved_conflict_not_a_gap
# ---------------------------------------------------------------------------


def test_resolved_conflict_not_a_gap():
    """A conflict whose resolution_suggestion is non-empty is NOT a gap."""
    exploration = _exploration(
        perspectives=[_populated_perspective("data"), _populated_perspective("api")],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "api"],
                description="This is a sufficiently long description "
                "of a real disagreement between perspectives.",
                resolution_suggestion="Trust the API explorer; data was stale.",
            )
        ],
    )

    gaps = detect_coverage_gaps(exploration)
    assert [g for g in gaps if g.kind == GAP_UNRESOLVED_CONFLICT] == []


# ---------------------------------------------------------------------------
# 6. test_sparse_perspective_detected
# ---------------------------------------------------------------------------


def test_sparse_perspective_detected():
    """A perspective with 0 artifacts while siblings have many IS a gap."""
    exploration = _exploration(
        perspectives=[
            _populated_perspective("data", n=5),
            _populated_perspective("api", n=4),
            _populated_perspective("ui", n=3),
            _perspective("test"),  # ← the sparse one
            _populated_perspective("history", n=3),
        ]
    )

    gaps = detect_coverage_gaps(exploration)
    sparse_gaps = [g for g in gaps if g.kind == GAP_SPARSE_PERSPECTIVE]
    assert len(sparse_gaps) == 1
    assert sparse_gaps[0].primary_perspective == "test"
    assert "test" in sparse_gaps[0].detail


# ---------------------------------------------------------------------------
# 7. test_all_empty_not_a_gap
# ---------------------------------------------------------------------------


def test_all_empty_not_a_gap():
    """When every perspective is empty there's no failure to flag."""
    exploration = _exploration(
        perspectives=[
            _perspective("data"),
            _perspective("api"),
            _perspective("ui"),
            _perspective("test"),
            _perspective("history"),
        ]
    )

    gaps = detect_coverage_gaps(exploration)
    assert gaps == []


# ---------------------------------------------------------------------------
# 8. test_question_text_is_concrete
# ---------------------------------------------------------------------------


def test_question_text_is_concrete():
    """Every gap's suggested_re_explore_question must reference a real anchor."""
    secret_path = "mealie/routes/explore/controller_public_recipes.py"
    conflict_desc = (
        "Data explorer says SQLAlchemy 2.0 but API explorer says 1.4 syntax is used"
    )
    exploration = _exploration(
        perspectives=[
            _populated_perspective("data", n=5),
            _perspective(
                "api",
                artifacts=[
                    _artifact(secret_path, importance="critical"),
                ],
            ),
            _populated_perspective("ui", n=4),
            _perspective("test"),  # sparse
            _populated_perspective("history", n=3),
        ],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "api"],
                description=conflict_desc,
                resolution_suggestion=None,
            )
        ],
    )

    gaps = detect_coverage_gaps(exploration)

    # We expect at least one of each kind given the setup.
    assert {g.kind for g in gaps} == {
        GAP_SINGLETON_CRITICAL,
        GAP_UNRESOLVED_CONFLICT,
        GAP_SPARSE_PERSPECTIVE,
    }
    for g in gaps:
        assert g.suggested_re_explore_question.strip(), "question must be non-empty"
        if g.kind == GAP_SINGLETON_CRITICAL:
            assert secret_path in g.suggested_re_explore_question
        elif g.kind == GAP_UNRESOLVED_CONFLICT:
            # Conflict description must be reflected in the question so the
            # targeted re-explorer has a concrete claim to investigate.
            assert "SQLAlchemy" in g.suggested_re_explore_question
        elif g.kind == GAP_SPARSE_PERSPECTIVE:
            # The empty perspective's name must appear so the re-explorer
            # knows which beat to cover.
            assert "test" in g.suggested_re_explore_question


# ---------------------------------------------------------------------------
# Additional defensive tests
# ---------------------------------------------------------------------------


def test_only_one_perspective_populated_does_not_flag_others_as_sparse():
    """If only 2 perspectives ran and 1 has < SPARSE_SIBLING_THRESHOLD, the
    other is not flagged as sparse — no perspective is *well*-populated."""
    exploration = _exploration(
        perspectives=[
            _perspective(
                "data",
                artifacts=[
                    _artifact("a.py", importance="relevant"),
                    _artifact("b.py", importance="relevant"),
                ],  # only 2 — below threshold
            ),
            _perspective("api"),
        ]
    )

    gaps = detect_coverage_gaps(exploration)
    assert [g for g in gaps if g.kind == GAP_SPARSE_PERSPECTIVE] == []


def test_unresolved_conflict_with_trivial_description_skipped():
    """Conflicts with description shorter than the min length are ignored."""
    short = "x" * (MIN_CONFLICT_DESCRIPTION_LEN - 1)
    exploration = _exploration(
        perspectives=[_populated_perspective("data"), _populated_perspective("api")],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "api"],
                description=short,
                resolution_suggestion=None,
            )
        ],
    )

    gaps = detect_coverage_gaps(exploration)
    assert [g for g in gaps if g.kind == GAP_UNRESOLVED_CONFLICT] == []


def test_resolved_conflict_with_whitespace_only_resolution_is_still_a_gap():
    """A conflict whose resolution is only whitespace counts as unresolved."""
    exploration = _exploration(
        perspectives=[_populated_perspective("data"), _populated_perspective("api")],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "api"],
                description=(
                    "Data and API disagree on whether comments table exists "
                    "in the schema."
                ),
                resolution_suggestion="   \n\t  ",
            )
        ],
    )

    gaps = detect_coverage_gaps(exploration)
    assert any(g.kind == GAP_UNRESOLVED_CONFLICT for g in gaps)


def test_all_gap_kinds_in_constant_match_emitted_kinds():
    """Sanity: every kind emitted must be in VALID_GAP_KINDS."""
    exploration = _exploration(
        perspectives=[
            _populated_perspective("data", n=5),
            _perspective(
                "api",
                artifacts=[_artifact("singleton.py", importance="critical")],
            ),
            _populated_perspective("ui", n=4),
            _perspective("test"),
            _populated_perspective("history", n=3),
        ],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "ui"],
                description="non-trivial description that exceeds the min len",
                resolution_suggestion=None,
            )
        ],
    )
    for g in detect_coverage_gaps(exploration):
        assert g.kind in VALID_GAP_KINDS


def test_coverage_gap_is_frozen_and_hashable():
    """CoverageGap must be hashable so callers can dedupe in sets."""
    g1 = CoverageGap(
        kind=GAP_SINGLETON_CRITICAL,
        detail="d",
        suggested_re_explore_question="q",
        primary_perspective="api",
    )
    g2 = CoverageGap(
        kind=GAP_SINGLETON_CRITICAL,
        detail="d",
        suggested_re_explore_question="q",
        primary_perspective="api",
    )
    assert {g1, g2} == {g1}
    with pytest.raises(AttributeError):
        g1.kind = "mutated"  # type: ignore[misc]


def test_gap_order_is_stable():
    """Gaps must come out in singleton → unresolved → sparse order."""
    exploration = _exploration(
        perspectives=[
            _populated_perspective("data", n=5),
            _perspective(
                "api",
                artifacts=[_artifact("only-api.py", importance="critical")],
            ),
            _populated_perspective("ui", n=4),
            _perspective("test"),  # sparse
            _populated_perspective("history", n=3),
        ],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "history"],
                description="this disagreement is sufficiently described here",
                resolution_suggestion=None,
            )
        ],
    )

    gaps = detect_coverage_gaps(exploration)
    kinds = [g.kind for g in gaps]
    # Find the first index of each kind
    sing_idx = kinds.index(GAP_SINGLETON_CRITICAL)
    conf_idx = kinds.index(GAP_UNRESOLVED_CONFLICT)
    spar_idx = kinds.index(GAP_SPARSE_PERSPECTIVE)
    assert sing_idx < conf_idx < spar_idx


def test_empty_exploration_returns_no_gaps():
    """An empty ConsolidatedExploration triggers no gaps."""
    assert detect_coverage_gaps(_exploration()) == []
