"""Tests for the F3-A3 under-escalation validator.

The spec writer sometimes dumps "I see 3 implementation options, not sure which"
into ``Concern.evidence_gap`` instead of escalating the decision to a top-of-spec
``BlockingDecision`` in ``Spec.needs_clarification``. These tests pin down:

* :func:`detect_underescalated_concern` — the regex / numeric-threshold helper.
* The pydantic ``@field_validator`` on ``Concern.evidence_gap`` — schema-time
  rejection so new specs literally cannot construct an under-escalated concern.
* :func:`find_underescalated_concerns` — the higher-level validator the
  orchestrator runs as a backup against non-validated load paths.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from devloop.spec_phase.schemas import (
    Concern,
    Spec,
    SpecMetadata,
)
from devloop.spec_phase.schemas.spec import detect_underescalated_concern
from devloop.spec_phase.validators.escalation import (
    EscalationProblem,
    find_underescalated_concerns,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec_with_concerns(concerns: list[Concern]) -> Spec:
    """Minimal Spec wrapping a self_concerns list, bypassing the
    Concern field_validator when needed by constructing the Concern via
    ``model_construct`` (skip validation)."""
    return Spec(
        metadata=SpecMetadata(feature_id="esc-test", title="esc test"),
        summary="A minimal spec for the escalation validator tests.",
        self_concerns=concerns,
    )


def _unvalidated_concern(
    *,
    location: str,
    concern: str,
    evidence_gap: str,
) -> Concern:
    """Construct a Concern *without* running the field_validator.

    Used by the higher-level :func:`find_underescalated_concerns` tests
    to simulate legacy / non-validated load paths where the pydantic
    guard didn't run (e.g. specs deserialized via
    ``Spec.model_construct``)."""
    return Concern.model_construct(
        location=location,
        concern=concern,
        evidence_gap=evidence_gap,
        suggested_resolution=None,
    )


# ---------------------------------------------------------------------------
# Required tests (per F3 plan)
# ---------------------------------------------------------------------------


def test_three_options_caught() -> None:
    """English digit '3 implementation options' is detected as under-escalated."""
    with pytest.raises(ValidationError) as ei:
        Concern(
            location="FR-007",
            concern="Implementation choice unclear.",
            evidence_gap="I see 3 implementation options, not sure which.",
        )
    msg = str(ei.value)
    assert "underescalation" in msg.lower() or "escalat" in msg.lower()
    assert "needs_clarification" in msg or "BlockingDecision" in msg


def test_three_alternatives_caught() -> None:
    """English word 'three alternatives' is detected as under-escalated."""
    with pytest.raises(ValidationError) as ei:
        Concern(
            location="FR-002",
            concern="Algorithm choice ambiguous.",
            evidence_gap="three alternatives exist for the sort algorithm.",
        )
    msg = str(ei.value)
    assert "three alternatives" in msg.lower()


def test_chinese_3_options_caught() -> None:
    """Chinese '3 种选项' is detected as under-escalated."""
    with pytest.raises(ValidationError) as ei:
        Concern(
            location="FR-010",
            concern="存储方案不明确。",
            evidence_gap="有 3 种选项可选,需要确认。",
        )
    msg = str(ei.value)
    assert "3" in msg and ("种选项" in msg or "选项" in msg)


def test_chinese_multiple_approaches_caught() -> None:
    """Chinese '多个备选方案' is detected as under-escalated."""
    with pytest.raises(ValidationError) as ei:
        Concern(
            location="FR-011",
            concern="Multiple plausible designs.",
            evidence_gap="有多个备选方案,无法确定。",
        )
    msg = str(ei.value)
    # The match should include one of the Chinese keywords.
    assert "多" in msg


def test_two_options_not_caught() -> None:
    """A binary 'two options' choice is NOT under-escalated (< 3 threshold)."""
    # Direct detector check — must return None.
    assert detect_underescalated_concern("there are two options here") is None
    # And pydantic must accept it.
    c = Concern(
        location="FR-003",
        concern="Binary choice on framework.",
        evidence_gap="there are two options here — picked the simpler one.",
    )
    assert c.evidence_gap.startswith("there are two options")


def test_option_as_preposition_not_caught() -> None:
    """The standalone word 'option to' (preposition) must not match."""
    assert detect_underescalated_concern("we have an option to do X") is None
    c = Concern(
        location="FR-004",
        concern="Optional behaviour.",
        evidence_gap="we have an option to do X if the user opts in.",
    )
    assert "option to do X" in c.evidence_gap


def test_several_reasons_not_caught() -> None:
    """'several reasons' must not match — 'reasons' is not in the keyword set."""
    assert detect_underescalated_concern("for several reasons we deferred this") is None
    c = Concern(
        location="FR-005",
        concern="Deferral rationale.",
        evidence_gap="for several reasons we deferred this scope to a later release.",
    )
    assert "several reasons" in c.evidence_gap


def test_options_A_B_C_caught() -> None:
    """Enumerated 'Options 1, 2, and 3 are viable' is detected as under-escalated."""
    with pytest.raises(ValidationError) as ei:
        Concern(
            location="FR-006",
            concern="Three viable plans.",
            evidence_gap="Options 1, 2, and 3 are viable; need a reviewer to choose.",
        )
    msg = str(ei.value)
    assert "options 1" in msg.lower() or "Options 1" in msg


def test_find_underescalated_concerns_returns_locations() -> None:
    """Spec with two concerns (one clean, one under-escalated) returns exactly one problem."""
    clean = _unvalidated_concern(
        location="FR-100",
        concern="Auth flow ambiguity.",
        evidence_gap="No test exercises the anonymous path.",
    )
    bad = _unvalidated_concern(
        location="FR-200",
        concern="Multiple plausible designs.",
        evidence_gap="There are 4 implementation candidates to choose from.",
    )
    spec = _spec_with_concerns([clean, bad])

    problems = find_underescalated_concerns(spec)
    assert len(problems) == 1
    p = problems[0]
    assert isinstance(p, EscalationProblem)
    assert p.concern_location == "FR-200"
    assert "4 implementation" in p.matched_text
    assert "FR-200" in p.suggested_fix
    assert "needs_clarification" in p.suggested_fix
    assert "BlockingDecision" in p.suggested_fix


def test_pydantic_validator_blocks_at_schema_level() -> None:
    """Constructing a Concern with under-escalated evidence_gap raises ValidationError."""
    with pytest.raises(ValidationError) as ei:
        Concern(
            location="FR-001",
            concern="Multi-option ambiguity.",
            evidence_gap="3 options",
        )
    # The error must originate from the evidence_gap field.
    errors = ei.value.errors()
    assert any(err["loc"] == ("evidence_gap",) for err in errors), (
        f"expected an evidence_gap field error, got {errors}"
    )
    # And must point the rewriter at the right escalation path.
    msg = str(ei.value)
    assert "needs_clarification" in msg
    assert "BlockingDecision" in msg


# ---------------------------------------------------------------------------
# Additional unit coverage for the helper edge cases (defensive)
# ---------------------------------------------------------------------------


def test_detect_returns_none_on_empty_string() -> None:
    assert detect_underescalated_concern("") is None


def test_detect_returns_none_on_clean_text() -> None:
    assert detect_underescalated_concern("The spec is unambiguous here.") is None


def test_detect_catches_capitalised_keyword() -> None:
    # Case-insensitive English pattern.
    assert detect_underescalated_concern("THREE OPTIONS are open") is not None


def test_detect_catches_multiple_choices_phrase() -> None:
    assert detect_underescalated_concern("There are multiple choices on the table") is not None


def test_detect_catches_n_options_with_explicit_N() -> None:
    # The literal letter 'N' (as in "N options") is in the keyword set.
    assert detect_underescalated_concern("we have N options to evaluate") is not None


def test_detect_rejects_one_or_two_options() -> None:
    assert detect_underescalated_concern("1 option") is None
    assert detect_underescalated_concern("2 options") is None
    # Boundary: exactly 3 must match.
    assert detect_underescalated_concern("3 options") is not None


def test_find_underescalated_concerns_empty_spec_returns_empty_list() -> None:
    spec = _spec_with_concerns([])
    assert find_underescalated_concerns(spec) == []


def test_find_underescalated_concerns_all_clean_returns_empty_list() -> None:
    clean1 = _unvalidated_concern(
        location="FR-001",
        concern="x",
        evidence_gap="No fixture covers the error path.",
    )
    clean2 = _unvalidated_concern(
        location="FR-002",
        concern="y",
        evidence_gap="There is one obvious implementation here.",
    )
    spec = _spec_with_concerns([clean1, clean2])
    assert find_underescalated_concerns(spec) == []


def test_find_underescalated_concerns_preserves_source_order() -> None:
    bad1 = _unvalidated_concern(
        location="FR-A",
        concern="multi",
        evidence_gap="three alternatives surfaced during exploration.",
    )
    clean = _unvalidated_concern(
        location="FR-B",
        concern="single",
        evidence_gap="Resolved with the obvious default.",
    )
    bad2 = _unvalidated_concern(
        location="FR-C",
        concern="multi",
        evidence_gap="There are 5 candidates that all look viable.",
    )
    spec = _spec_with_concerns([bad1, clean, bad2])
    problems = find_underescalated_concerns(spec)
    assert [p.concern_location for p in problems] == ["FR-A", "FR-C"]
