"""Tests for the soft-language schema validators (DevLoop Sprint A — A4).

The writer prompt forbids vague hedging phrases like "or equivalent" / "TBD" /
"if needed" but the LLM emits them anyway. These tests pin down the schema-layer
defense — pydantic ``@field_validator`` rejections on the guarded fields, with a
backtick escape hatch for legitimate literal uses.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from devloop.spec_phase.agents.writer import detect_soft_language_in_spec_dict
from devloop.spec_phase.schemas import (
    BlockingDecision,
    Concern,
    EdgeCase,
    Entity,
    FunctionalRequirement,
    Spec,
    SpecMetadata,
    SuccessCriterion,
)
from devloop.spec_phase.schemas.spec import (
    _FORBIDDEN_PHRASES_RE,
    find_forbidden_phrase,
    validate_no_soft_language,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_spec() -> Spec:
    """Build a minimal but realistic Spec that passes all validators."""
    return Spec(
        metadata=SpecMetadata(feature_id="f1", title="Feature One"),
        summary="Allow logged-in users to favorite recipes via a star button.",
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="System must persist a favorite when the star is clicked.",
                requirement_type="functional",
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="Favorite action latency stays below threshold under load.",
                metric="p99 latency of POST /favorite",
                threshold="< 200 ms at 100 rps",
            )
        ],
        key_entities=[
            Entity(name="Favorite", description="A user-recipe pairing flag.")
        ],
        edge_cases=[
            EdgeCase(
                description="User double-clicks the star",
                handling="Idempotent — second click returns 200 with existing row.",
            )
        ],
        needs_clarification=[
            BlockingDecision(
                id="NC-001",
                title="Data model conflict",
                conflict="Input requests new table but is_favorite already exists.",
                recommended_default="Reuse UserToRecipe.is_favorite.",
                if_rejected="Create new table with backfill from is_favorite.",
            )
        ],
        self_concerns=[
            Concern(
                location="FR-001",
                concern="Anonymous favorite path not specified.",
                evidence_gap="No test pins anonymous behavior.",
                suggested_resolution="Require login; redirect anonymous users to /login.",
            )
        ],
    )


# ---------------------------------------------------------------------------
# 8 positive tests — one per forbidden phrase, on a different guarded field
# ---------------------------------------------------------------------------


def test_rejects_or_equivalent_in_functional_requirement_text() -> None:
    with pytest.raises(ValidationError) as exc:
        FunctionalRequirement(
            id="FR-001",
            text="System must persist favorites in UserToRecipe or equivalent table.",
            requirement_type="functional",
        )
    assert "or equivalent" in str(exc.value).lower()
    assert "FunctionalRequirement.text" in str(exc.value)


def test_rejects_or_similar_in_success_criterion_threshold() -> None:
    with pytest.raises(ValidationError) as exc:
        SuccessCriterion(
            id="SC-001",
            text="latency is OK",
            metric="p99 latency",
            threshold="< 200 ms or similar",
        )
    assert "or similar" in str(exc.value).lower()
    assert "SuccessCriterion.threshold" in str(exc.value)


def test_rejects_tbd_in_success_criterion_metric() -> None:
    with pytest.raises(ValidationError) as exc:
        SuccessCriterion(
            id="SC-001",
            text="latency",
            metric="TBD",
            threshold="< 200 ms",
        )
    assert "tbd" in str(exc.value).lower()
    assert "SuccessCriterion.metric" in str(exc.value)


def test_rejects_to_be_decided_in_blocking_decision_recommended_default() -> None:
    with pytest.raises(ValidationError) as exc:
        BlockingDecision(
            id="NC-001",
            title="t",
            conflict="c",
            recommended_default="Strategy is to be decided by the user.",
            if_rejected="Implement new table.",
        )
    assert "to be decided" in str(exc.value).lower()
    assert "BlockingDecision.recommended_default" in str(exc.value)


def test_rejects_to_be_determined_in_blocking_decision_if_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        BlockingDecision(
            id="NC-001",
            title="t",
            conflict="c",
            recommended_default="Reuse existing field.",
            if_rejected="Schema to be determined later.",
        )
    assert "to be determined" in str(exc.value).lower()
    assert "BlockingDecision.if_rejected" in str(exc.value)


def test_rejects_if_needed_in_concern_suggested_resolution() -> None:
    with pytest.raises(ValidationError) as exc:
        Concern(
            location="FR-001",
            concern="x",
            evidence_gap="y",
            suggested_resolution="Add a unique index if needed.",
        )
    assert "if needed" in str(exc.value).lower()
    assert "Concern.suggested_resolution" in str(exc.value)


def test_rejects_as_needed_in_spec_summary() -> None:
    with pytest.raises(ValidationError) as exc:
        Spec(
            metadata=SpecMetadata(feature_id="f1", title="t"),
            summary="Persist favorites and migrate data as needed.",
        )
    assert "as needed" in str(exc.value).lower()
    assert "Spec.summary" in str(exc.value)


def test_rejects_tba_in_edge_case_handling() -> None:
    with pytest.raises(ValidationError) as exc:
        EdgeCase(
            description="user clicks twice",
            handling="TBA — pending UX review.",
        )
    assert "tba" in str(exc.value).lower()
    assert "EdgeCase.handling" in str(exc.value)


def test_rejects_placeholder_in_entity_description() -> None:
    with pytest.raises(ValidationError) as exc:
        Entity(name="Favorite", description="placeholder for the favorite entity")
    assert "placeholder" in str(exc.value).lower()
    assert "Entity.description" in str(exc.value)


# ---------------------------------------------------------------------------
# 5 edge / negative tests
# ---------------------------------------------------------------------------


def test_clean_text_passes_on_all_guarded_fields() -> None:
    """A fully populated, soft-language-free Spec validates cleanly."""
    spec = _clean_spec()
    assert spec.summary.startswith("Allow logged-in users")
    assert spec.functional_requirements[0].text.startswith("System must persist")
    assert spec.success_criteria[0].metric == "p99 latency of POST /favorite"
    assert spec.success_criteria[0].threshold == "< 200 ms at 100 rps"
    assert spec.key_entities[0].description == "A user-recipe pairing flag."
    assert spec.edge_cases[0].handling.startswith("Idempotent")
    assert spec.needs_clarification[0].recommended_default == "Reuse UserToRecipe.is_favorite."
    assert spec.needs_clarification[0].if_rejected.startswith("Create new table")
    assert spec.self_concerns[0].suggested_resolution.startswith("Require login")


def test_backtick_fenced_soft_phrases_pass() -> None:
    """The escape hatch: phrases in backticks are stripped before matching.

    Legitimate use of the literal word (e.g. an HTML attribute named
    ``placeholder``) must still be expressible inside backticks.
    """
    # Inline backticks
    fr = FunctionalRequirement(
        id="FR-001",
        text="Form field uses an HTML `placeholder` attribute for hints.",
        requirement_type="functional",
    )
    assert "placeholder" in fr.text

    # Triple-backtick fenced block
    ent = Entity(
        name="HelpText",
        description="Renders as:\n```\nor equivalent\n```\n(literal example).",
    )
    assert "or equivalent" in ent.description

    # And multiple forbidden phrases inside backticks all escape
    ec = EdgeCase(
        description="Bad outputs to avoid",
        handling="Never emit `TBD`, `TBA`, or `to be decided` in the spec text.",
    )
    assert "TBD" in ec.handling


def test_soft_phrase_in_summary_rejected_via_spec_construction() -> None:
    """Soft language in ``Spec.summary`` raises during Spec(...) construction."""
    with pytest.raises(ValidationError) as exc:
        Spec(
            metadata=SpecMetadata(feature_id="f", title="t"),
            summary="Persist favorites; migration TBD.",
        )
    err = str(exc.value)
    assert "Spec.summary" in err
    assert "tbd" in err.lower()


def test_concern_suggested_resolution_none_is_skipped() -> None:
    """When ``suggested_resolution`` is None the validator must not raise."""
    c = Concern(
        location="FR-001",
        concern="anonymous path",
        evidence_gap="no test",
        suggested_resolution=None,
    )
    assert c.suggested_resolution is None

    # Also: omitting the field entirely (default None) must work
    c2 = Concern(location="FR-002", concern="x", evidence_gap="y")
    assert c2.suggested_resolution is None


def test_case_insensitivity_is_enforced() -> None:
    """Forbidden phrases match regardless of letter case."""
    # lowercase
    with pytest.raises(ValidationError):
        SuccessCriterion(id="SC-1", text="t", metric="tbd", threshold="< 1s")
    # mixed case
    with pytest.raises(ValidationError):
        SuccessCriterion(id="SC-1", text="t", metric="Tbd", threshold="< 1s")
    # uppercase phrase
    with pytest.raises(ValidationError):
        FunctionalRequirement(
            id="FR-001",
            text="Persist data OR EQUIVALENT for resilience.",
            requirement_type="functional",
        )
    # mixed case multi-word
    with pytest.raises(ValidationError):
        EdgeCase(description="d", handling="Field is To Be Determined later.")

    # Sanity: the regex itself is built with IGNORECASE
    assert _FORBIDDEN_PHRASES_RE.flags & 2  # re.IGNORECASE == 2


# ---------------------------------------------------------------------------
# 1 roundtrip test — clean Spec validates, surgery to inject soft-language fails revalidate
# ---------------------------------------------------------------------------


def test_roundtrip_clean_spec_then_inject_soft_language_fails_revalidate() -> None:
    """A clean Spec roundtrips through model_dump/model_validate. After we
    inject a forbidden phrase into the dumped dict, revalidation must fail."""
    spec = _clean_spec()

    # Clean roundtrip succeeds and is idempotent
    dumped = spec.model_dump(mode="json")
    spec2 = Spec.model_validate(dumped)
    assert spec2.summary == spec.summary
    # Idempotence: dump again should equal the first dump
    assert spec2.model_dump(mode="json") == dumped

    # Surgery: inject "or equivalent" into FR.text and revalidate
    poisoned = spec.model_dump(mode="json")
    poisoned["functional_requirements"][0]["text"] = (
        "System must persist favorites in UserToRecipe or equivalent table."
    )
    with pytest.raises(ValidationError) as exc:
        Spec.model_validate(poisoned)
    err = str(exc.value)
    assert "FunctionalRequirement.text" in err
    assert "or equivalent" in err.lower()


# ---------------------------------------------------------------------------
# 1 integration test — detect_soft_language_in_spec_dict on a known-bad dict
# ---------------------------------------------------------------------------


def test_detect_soft_language_in_spec_dict_finds_all_offenses() -> None:
    """The writer's pre-check helper finds every forbidden phrase across the
    guarded fields and ignores unguarded ones (conflict, out_of_scope)."""
    bad = {
        "summary": "Persist favorites; migration TBD.",
        "functional_requirements": [
            {"id": "FR-001", "text": "Use UserToRecipe or equivalent.", "requirement_type": "functional"},
            {"id": "FR-002", "text": "Sanitize user input.", "requirement_type": "functional"},
        ],
        "success_criteria": [
            {"id": "SC-001", "text": "t", "metric": "p99 latency", "threshold": "TBA"},
        ],
        "key_entities": [
            {"name": "Favorite", "description": "placeholder description"},
        ],
        "edge_cases": [
            {"description": "double-click", "handling": "idempotent retry"},
            {"description": "race", "handling": "lock if needed"},
        ],
        "needs_clarification": [
            {
                "id": "NC-001",
                "title": "t",
                # NOTE: ``conflict`` is intentionally NOT validated — soft
                # language here is fine because it describes the conflict.
                "conflict": "Strategy or equivalent path is unclear.",
                "recommended_default": "Strategy to be decided.",
                "if_rejected": "Migrate as needed.",
            }
        ],
        "self_concerns": [
            {
                "location": "FR-001",
                "concern": "x",
                "evidence_gap": "y",
                "suggested_resolution": "Wire it up if needed.",
            },
            {
                "location": "FR-002",
                "concern": "no resolution",
                "evidence_gap": "n/a",
                "suggested_resolution": None,  # must be skipped
            },
        ],
        # out_of_scope items must also be skipped (allowed to contain "if needed")
        "out_of_scope": ["Backfilling historical favorites if needed."],
    }

    findings = detect_soft_language_in_spec_dict(bad)
    paths = {p for p, _ in findings}
    phrases = {(p, ph.lower()) for p, ph in findings}

    assert ("summary", "tbd") in phrases
    assert ("functional_requirements[0].text", "or equivalent") in phrases
    assert ("success_criteria[0].threshold", "tba") in phrases
    assert ("key_entities[0].description", "placeholder") in phrases
    assert ("edge_cases[1].handling", "if needed") in phrases
    assert ("needs_clarification[0].recommended_default", "to be decided") in phrases
    assert ("needs_clarification[0].if_rejected", "as needed") in phrases
    assert ("self_concerns[0].suggested_resolution", "if needed") in phrases

    # Unguarded fields are NOT reported
    assert "needs_clarification[0].conflict" not in paths
    assert not any(p.startswith("out_of_scope") for p in paths)
    # None suggested_resolution is skipped
    assert "self_concerns[1].suggested_resolution" not in paths
    # Clean FR-002.text is NOT reported
    assert "functional_requirements[1].text" not in paths

    # And a fully clean spec dict returns []
    assert detect_soft_language_in_spec_dict(_clean_spec().model_dump(mode="json")) == []


# ---------------------------------------------------------------------------
# Bonus: tiny direct-helper test for symmetry / future maintainers
# ---------------------------------------------------------------------------


def test_validate_no_soft_language_helper_returns_value_on_clean() -> None:
    """The helper is the body of every @field_validator; pin its contract."""
    assert validate_no_soft_language("X.y", "clean text") == "clean text"
    assert find_forbidden_phrase("clean text") is None
    assert find_forbidden_phrase("") is None
    # Backtick stripping inside the helper
    assert find_forbidden_phrase("use `TBD` literally") is None
    # Detection outside backticks even when backticks present
    assert find_forbidden_phrase("use `foo` but really TBD") == "TBD"
