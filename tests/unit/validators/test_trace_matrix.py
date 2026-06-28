"""Tests for the FR↔SC↔US trace-matrix validator (DevLoop Sprint B — B3)."""

from __future__ import annotations

from typing import Any

import pytest

from devloop.spec_phase.schemas import (
    FunctionalRequirement,
    Spec,
    SpecMetadata,
    SuccessCriterion,
    UserStory,
)
from devloop.spec_phase.validators.trace_matrix import (
    GAP_FR_REF_UNKNOWN_SC,
    GAP_FR_WITHOUT_SC,
    GAP_SC_REF_UNKNOWN_FR,
    GAP_SC_WITHOUT_FR,
    GAP_US_WITHOUT_FR,
    VALID_GAP_KINDS,
    TraceGap,
    build_trace_matrix,
    find_trace_gaps,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _us(us_id: str, priority: str = "P1") -> UserStory:
    return UserStory(
        id=us_id,
        priority=priority,  # type: ignore[arg-type]
        title=f"Story {us_id}",
        description=f"description of {us_id}",
    )


def _fr(
    fr_id: str,
    *,
    related_user_stories: list[str] | None = None,
    related_success_criteria: list[str] | None = None,
    requirement_type: str = "functional",
    code_references: list[dict[str, Any]] | None = None,
) -> FunctionalRequirement:
    if code_references is None and requirement_type == "functional":
        code_references = [
            {"path": "app/models/user.py", "symbols": ["User"], "line_ranges": [(1, 25)]}
        ]
    payload: dict[str, Any] = {
        "id": fr_id,
        "text": f"Requirement {fr_id} performs an action.",
        "requirement_type": requirement_type,
        "related_user_stories": related_user_stories or [],
        "related_success_criteria": related_success_criteria or [],
        "code_references": code_references or [],
        "testable": True,
    }
    return FunctionalRequirement.model_validate(payload)


def _sc(
    sc_id: str,
    *,
    related_requirements: list[str] | None = None,
) -> SuccessCriterion:
    return SuccessCriterion.model_validate(
        {
            "id": sc_id,
            "text": f"Acceptance criterion {sc_id}",
            "metric": f"latency for {sc_id}",
            "threshold": "< 500ms",
            "technology_agnostic": True,
            "related_requirements": related_requirements or [],
        }
    )


def _spec(
    *,
    user_stories: list[UserStory] | None = None,
    functional_requirements: list[FunctionalRequirement] | None = None,
    success_criteria: list[SuccessCriterion] | None = None,
) -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="trace-test", title="Trace test feature"),
        summary="Synthetic spec used to exercise the trace-matrix validator.",
        user_stories=user_stories or [],
        functional_requirements=functional_requirements or [],
        success_criteria=success_criteria or [],
    )


def _gap_kinds(gaps: list[TraceGap]) -> list[str]:
    return [g.kind for g in gaps]


# ---------------------------------------------------------------------------
# Required tests (the 10 enumerated in the task spec)
# ---------------------------------------------------------------------------


def test_clean_spec_has_no_gaps():
    """Bidirectional FR↔SC links + P1 US covered = zero gaps."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"])
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    assert find_trace_gaps(spec) == []


def test_fr_without_sc_is_a_gap():
    """A functional FR with no SC link in either direction is a gap."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[_fr("FR-001", related_user_stories=["US-1"])],
        success_criteria=[_sc("SC-001", related_requirements=[])],
    )
    gaps = find_trace_gaps(spec)
    fr_gaps = [g for g in gaps if g.kind == GAP_FR_WITHOUT_SC]
    assert len(fr_gaps) == 1
    assert fr_gaps[0].actor == "FR-001"


def test_sc_without_fr_is_a_gap():
    """An SC with no FR linking to it in either direction is a gap."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"])
        ],
        success_criteria=[
            _sc("SC-001", related_requirements=["FR-001"]),
            _sc("SC-002"),
        ],
    )
    gaps = find_trace_gaps(spec)
    sc_gaps = [g for g in gaps if g.kind == GAP_SC_WITHOUT_FR]
    assert len(sc_gaps) == 1
    assert sc_gaps[0].actor == "SC-002"


def test_one_directional_reference_is_ok():
    """FR→SC alone (without the reverse SC→FR) keeps the pair reachable."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"])
        ],
        # SC-001.related_requirements deliberately empty — should still be reachable
        success_criteria=[_sc("SC-001")],
    )
    gaps = find_trace_gaps(spec)
    assert all(g.kind not in (GAP_FR_WITHOUT_SC, GAP_SC_WITHOUT_FR) for g in gaps)
    assert gaps == []


def test_sc_references_unknown_fr():
    """SC.related_requirements pointing at a missing FR id is a gap."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"])
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-999"])],
    )
    gaps = find_trace_gaps(spec)
    bad = [g for g in gaps if g.kind == GAP_SC_REF_UNKNOWN_FR]
    assert len(bad) == 1
    assert bad[0].actor == "SC-001"
    assert "FR-999" in bad[0].detail


def test_fr_references_unknown_sc():
    """FR.related_success_criteria pointing at a missing SC id is a gap."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001", "SC-999"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    gaps = find_trace_gaps(spec)
    bad = [g for g in gaps if g.kind == GAP_FR_REF_UNKNOWN_SC]
    assert len(bad) == 1
    assert bad[0].actor == "FR-001"
    assert "SC-999" in bad[0].detail


def test_nonfunctional_fr_with_no_sc_is_ok():
    """Non-functional FRs are exempt from the must-have-SC rule."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"]),
            _fr(
                "FR-002",
                requirement_type="non_functional",
                code_references=[],
            ),
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    gaps = find_trace_gaps(spec)
    fr_gaps = [g for g in gaps if g.kind == GAP_FR_WITHOUT_SC]
    assert fr_gaps == []  # FR-002 is non-functional => exempt


def test_p1_user_story_without_fr_is_a_gap():
    """A P1 user story not claimed by any FR.related_user_stories is a gap."""
    spec = _spec(
        user_stories=[_us("US-1", "P1"), _us("US-2", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"])
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    gaps = find_trace_gaps(spec)
    us_gaps = [g for g in gaps if g.kind == GAP_US_WITHOUT_FR]
    assert len(us_gaps) == 1
    assert us_gaps[0].actor == "US-2"


def test_p2_user_story_without_fr_is_ok():
    """Only P1 user stories must be implemented; P2/P3 are exempt."""
    spec = _spec(
        user_stories=[_us("US-1", "P1"), _us("US-2", "P2"), _us("US-3", "P3")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-001"])
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    gaps = find_trace_gaps(spec)
    us_gaps = [g for g in gaps if g.kind == GAP_US_WITHOUT_FR]
    assert us_gaps == []


def test_build_trace_matrix_correct_shape():
    """Matrix returns four maps, every node appears as a key (even with no edges),
    and FR↔SC edges are merged symmetrically from both directions."""
    spec = _spec(
        user_stories=[_us("US-1", "P1"), _us("US-2", "P2")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1", "US-2"],
                related_success_criteria=["SC-001"],
            ),
            _fr(
                "FR-002",
                related_user_stories=["US-2"],
                # No FR→SC edge from FR-002; rely on SC-002 → FR-002 for symmetry
            ),
        ],
        success_criteria=[
            # SC-001 declares no FR; should still show FR-001 thanks to the FR→SC edge
            _sc("SC-001"),
            _sc("SC-002", related_requirements=["FR-002"]),
        ],
    )
    matrix = build_trace_matrix(spec)
    assert set(matrix.keys()) == {"fr_to_sc", "sc_to_fr", "us_to_fr", "fr_to_us"}

    assert matrix["fr_to_sc"] == {
        "FR-001": ["SC-001"],
        "FR-002": ["SC-002"],
    }
    assert matrix["sc_to_fr"] == {
        "SC-001": ["FR-001"],
        "SC-002": ["FR-002"],
    }
    assert matrix["us_to_fr"] == {
        "US-1": ["FR-001"],
        "US-2": ["FR-001", "FR-002"],
    }
    assert matrix["fr_to_us"] == {
        "FR-001": ["US-1", "US-2"],
        "FR-002": ["US-2"],
    }


# ---------------------------------------------------------------------------
# Additional safety-net tests
# ---------------------------------------------------------------------------


def test_empty_spec_has_no_gaps():
    """An entirely empty spec (no FRs/SCs/US) trivially has no trace gaps."""
    assert find_trace_gaps(_spec()) == []


def test_unknown_us_in_fr_related_user_stories_is_not_a_trace_gap():
    """Dangling US ids in FR.related_user_stories are out of scope for this
    validator (the per-field schema validator can take that on)."""
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1", "US-999"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    assert find_trace_gaps(spec) == []


def test_all_emitted_gap_kinds_are_known():
    """Every gap kind we emit must be in :data:`VALID_GAP_KINDS` so downstream
    handlers can rely on the set being closed."""
    spec = _spec(
        user_stories=[_us("US-1", "P1"), _us("US-2", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=["SC-999"]),
            _fr("FR-002", related_user_stories=["US-1"]),  # functional, no SC link
        ],
        success_criteria=[
            _sc("SC-001", related_requirements=["FR-999"]),  # dangling FR
            _sc("SC-002"),  # no FR link
        ],
    )
    gaps = find_trace_gaps(spec)
    assert gaps, "Expected gaps but got none"
    for gap in gaps:
        assert gap.kind in VALID_GAP_KINDS, f"Unknown kind: {gap.kind}"
    kinds_seen = set(_gap_kinds(gaps))
    assert {
        GAP_FR_REF_UNKNOWN_SC,
        GAP_SC_REF_UNKNOWN_FR,
        GAP_FR_WITHOUT_SC,
        GAP_SC_WITHOUT_FR,
        GAP_US_WITHOUT_FR,
    }.issubset(kinds_seen)


def test_cross_reference_gaps_reported_before_orphan_gaps():
    """Cause (bad id) is reported before symptom (orphan) so a reviewer can
    fix the root issue first."""
    spec = _spec(
        functional_requirements=[
            _fr("FR-001", related_success_criteria=["SC-999"]),  # FR-001 dangling -> also orphan
        ],
        success_criteria=[
            _sc("SC-001", related_requirements=["FR-999"]),  # SC-001 dangling -> also orphan
        ],
    )
    kinds = _gap_kinds(find_trace_gaps(spec))
    # First two entries must be the dangling-reference reports (in spec order)
    assert kinds[0] == GAP_FR_REF_UNKNOWN_SC
    assert kinds[1] == GAP_SC_REF_UNKNOWN_FR
    # Then orphans
    assert GAP_FR_WITHOUT_SC in kinds[2:]
    assert GAP_SC_WITHOUT_FR in kinds[2:]


def test_trace_gap_is_frozen_and_hashable():
    """TraceGap is a frozen slots dataclass — usable as a set key for dedup."""
    g = TraceGap(kind=GAP_FR_WITHOUT_SC, actor="FR-001", detail="x")
    # Frozen dataclass: mutation raises FrozenInstanceError (a subclass of AttributeError).
    with pytest.raises((AttributeError, TypeError)):
        g.kind = "other"  # type: ignore[misc]
    # frozen dataclasses are hashable, so this should work
    assert {g, g} == {g}
