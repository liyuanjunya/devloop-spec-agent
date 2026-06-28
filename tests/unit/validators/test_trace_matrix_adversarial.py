"""Adversarial unit probes for the FR↔SC↔US trace-matrix validator (B3).

These tests pound on the validator with malformed, degenerate, or
edge-case inputs that the LLM writer might plausibly produce — self
references, duplicated ids, empty/whitespace strings, case mismatches,
trailing whitespace, mixed-type batches, empty specs, and large specs.
The point is to lock down strict-vs-tolerant behaviour and make sure the
validator never crashes on malformed input. See the ANALYSIS section at
the bottom for an explicit boundary statement.

Complements ``test_trace_matrix.py`` (the canonical happy-path suite) and
``tests/integration/test_trace_matrix_e2e.py`` (the orchestrator-level
end-to-end injection path).
"""

from __future__ import annotations

import time
from typing import Any

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
    build_trace_matrix,
    find_trace_gaps,
)

# ---------------------------------------------------------------------------
# Local helpers — kept independent of the happy-path suite's helpers so
# this file is self-contained when read in isolation.
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
            {
                "path": "app/models/user.py",
                "symbols": ["User"],
                "line_ranges": [(1, 25)],
            }
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


def _sc(sc_id: str, *, related_requirements: list[str] | None = None) -> SuccessCriterion:
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
        metadata=SpecMetadata(feature_id="trace-adv", title="Trace adversarial test"),
        summary="Synthetic spec exercising adversarial trace-matrix cases.",
        user_stories=user_stories or [],
        functional_requirements=functional_requirements or [],
        success_criteria=success_criteria or [],
    )


def _kinds_for(actor: str, gaps) -> set[str]:
    return {g.kind for g in gaps if g.actor == actor}


# ---------------------------------------------------------------------------
# 1. FR referencing itself as an SC
# ---------------------------------------------------------------------------


def test_self_reference_fr_id_as_sc_produces_unknown_sc_gap():
    """An FR that lists *its own id* in ``related_success_criteria`` is
    pointing at a non-existent SC (the id namespace is FR, not SC). The
    validator must report a ``fr_references_unknown_sc`` gap for the FR
    and (because the self-ref doesn't connect to any real SC) ALSO an
    ``fr_without_sc`` orphan gap — the cross-ref report must come first
    so a reader sees the cause before the symptom.
    """
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["FR-001"],  # self-ref pretending to be an SC
            )
        ],
        success_criteria=[],
    )
    gaps = find_trace_gaps(spec)
    fr_kinds = _kinds_for("FR-001", gaps)
    assert GAP_FR_REF_UNKNOWN_SC in fr_kinds
    assert GAP_FR_WITHOUT_SC in fr_kinds
    # The dangling reference report must come strictly before the orphan
    # report so a reviewer reading top-down fixes the cause first.
    kinds_order = [g.kind for g in gaps if g.actor == "FR-001"]
    assert kinds_order.index(GAP_FR_REF_UNKNOWN_SC) < kinds_order.index(
        GAP_FR_WITHOUT_SC
    )
    # The dangling-reference detail must surface the bogus id so the
    # rewriter can fix it.
    dangling = next(g for g in gaps if g.kind == GAP_FR_REF_UNKNOWN_SC)
    assert "FR-001" in dangling.detail


# ---------------------------------------------------------------------------
# 2. Duplicate FR ids
# ---------------------------------------------------------------------------


def test_duplicate_fr_ids_do_not_crash_validator():
    """Pydantic does not enforce uniqueness on ``functional_requirements``
    item ids, so a model could plausibly emit the same FR-id twice. The
    matrix builder must not raise; the orphan walk runs once per list entry
    (so the same id may appear multiple times in the gap list). The
    validator behaviour we lock in: **no crash, and the gap-kind set
    remains a subset of VALID_GAP_KINDS**.
    """
    spec = _spec(
        functional_requirements=[
            _fr("FR-001"),  # functional, no SC link
            _fr("FR-001"),  # duplicate id
        ],
        success_criteria=[],
    )
    # Must not raise even though the FR id collides.
    matrix = build_trace_matrix(spec)
    # The set-keyed map dedupes silently — only one FR-001 entry survives.
    assert list(matrix["fr_to_sc"].keys()) == ["FR-001"]

    gaps = find_trace_gaps(spec)
    # The orphan walk iterates the list, so the SAME id can produce two
    # gap records. We do not assert the exact count (it's an implementation
    # detail); we only assert no crash and that every emitted kind is known.
    assert all(g.kind in VALID_GAP_KINDS for g in gaps)
    assert all(g.actor == "FR-001" for g in gaps if g.kind == GAP_FR_WITHOUT_SC)


# ---------------------------------------------------------------------------
# 3. Empty string in related_requirements
# ---------------------------------------------------------------------------


def test_empty_string_in_related_requirements_is_dangling_reference():
    """An empty string is not a valid FR id but pydantic does not police
    list contents. The validator must treat it as a dangling reference and
    report ``sc_references_unknown_fr`` rather than crashing or silently
    succeeding.
    """
    spec = _spec(
        functional_requirements=[
            _fr(
                "FR-001",
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["", "FR-001"])],
    )
    gaps = find_trace_gaps(spec)
    bad = [
        g for g in gaps if g.kind == GAP_SC_REF_UNKNOWN_FR and g.actor == "SC-001"
    ]
    assert len(bad) == 1, (
        "exactly one dangling-reference gap expected for the empty-string entry"
    )
    # SC-001 still has a valid link via 'FR-001' so it must NOT also be
    # reported as an orphan.
    assert not any(
        g.kind == GAP_SC_WITHOUT_FR and g.actor == "SC-001" for g in gaps
    )


# ---------------------------------------------------------------------------
# 4. Whitespace-only entry in related_requirements
# ---------------------------------------------------------------------------


def test_whitespace_only_string_in_related_requirements_is_dangling_reference():
    """A whitespace-only id like ``' '`` is treated as a literal id; since
    no FR has that id it produces a dangling-reference gap. Validator must
    not silently strip / normalise — that would mask writer bugs."""
    spec = _spec(
        functional_requirements=[_fr("FR-001", related_success_criteria=["SC-001"])],
        success_criteria=[
            _sc("SC-001", related_requirements=[" ", "FR-001"]),
        ],
    )
    gaps = find_trace_gaps(spec)
    bad = [g for g in gaps if g.kind == GAP_SC_REF_UNKNOWN_FR]
    assert len(bad) == 1
    # SC-001 still reaches FR-001 via the valid entry → no SC orphan gap.
    assert not any(g.kind == GAP_SC_WITHOUT_FR for g in gaps)


# ---------------------------------------------------------------------------
# 5. Case mismatch
# ---------------------------------------------------------------------------


def test_case_mismatched_reference_is_treated_as_unknown_id():
    """``'fr-001'`` vs ``'FR-001'``: the validator is intentionally
    case-sensitive (FR/SC ids are canonical, ALL-CAPS prefix + numeric
    suffix). Case-folding would let typos slip through and mask schema
    bugs. Lock the strict behaviour in.

    Two complementary scenarios:

    1. **One-sided case mismatch with a valid forward ref**: SC-001
       references ``'fr-001'`` (bad case) but FR-001 also lists SC-001
       as ``related_success_criteria``. The forward edge still connects
       the pair → no orphan gap, but the dangling-reference gap still
       fires so the rewriter is told about the typo.
    2. **Both sides typo'd**: nothing else links the pair → both the
       dangling-reference gap and the SC orphan gap fire, proving the
       case mismatch genuinely fails to bridge the pair.
    """
    # Scenario 1: valid forward edge from FR-001 still reaches SC-001
    spec1 = _spec(
        functional_requirements=[_fr("FR-001", related_success_criteria=["SC-001"])],
        success_criteria=[_sc("SC-001", related_requirements=["fr-001"])],
    )
    gaps1 = find_trace_gaps(spec1)
    bad1 = [g for g in gaps1 if g.kind == GAP_SC_REF_UNKNOWN_FR and g.actor == "SC-001"]
    assert len(bad1) == 1, (
        "case-insensitive matching would let typos slip through; "
        f"expected one dangling-reference gap, got {[(g.kind, g.actor) for g in gaps1]}"
    )
    # FR-001's forward reference still reaches SC-001 → SC-001 is NOT orphan.
    assert not any(
        g.kind == GAP_SC_WITHOUT_FR and g.actor == "SC-001" for g in gaps1
    ), "FR→SC edge is intact; SC-001 must not be reported as an SC orphan"

    # Scenario 2: case mismatch is the ONLY would-be link → SC-001 truly orphan
    spec2 = _spec(
        functional_requirements=[_fr("FR-001", related_success_criteria=[])],
        success_criteria=[_sc("SC-001", related_requirements=["fr-001"])],
    )
    gaps2 = find_trace_gaps(spec2)
    # Both dangling-reference AND SC orphan must fire when case mismatch
    # is the only would-be bridge.
    bad2 = [g for g in gaps2 if g.kind == GAP_SC_REF_UNKNOWN_FR and g.actor == "SC-001"]
    assert len(bad2) == 1
    assert any(
        g.kind == GAP_SC_WITHOUT_FR and g.actor == "SC-001" for g in gaps2
    ), (
        "case-mismatched 'fr-001' must NOT connect to 'FR-001'; "
        "SC-001 should still be reported as an orphan"
    )
    # And FR-001 (functional, no SC link) is itself an orphan.
    assert any(
        g.kind == GAP_FR_WITHOUT_SC and g.actor == "FR-001" for g in gaps2
    )


# ---------------------------------------------------------------------------
# 6. Trailing whitespace
# ---------------------------------------------------------------------------


def test_trailing_whitespace_reference_is_treated_as_unknown_id():
    """``'FR-001 '`` (trailing space) is a different string from
    ``'FR-001'``. The validator does NOT auto-strip; round-tripping
    through JSON would silently round-trip the whitespace too, masking a
    real writer bug. Locked: strict equality."""
    spec = _spec(
        functional_requirements=[_fr("FR-001", related_success_criteria=["SC-001"])],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001 "])],
    )
    gaps = find_trace_gaps(spec)
    bad = [g for g in gaps if g.kind == GAP_SC_REF_UNKNOWN_FR and g.actor == "SC-001"]
    assert len(bad) == 1
    # 'FR-001 ' is a real value the LLM emitted; the detail must surface
    # the exact (whitespace-included) string so a human reading the report
    # can spot the bug.
    assert "FR-001 " in bad[0].detail


# ---------------------------------------------------------------------------
# 7. Mixed functional / non-functional batch
# ---------------------------------------------------------------------------


def test_mixed_functional_and_nfr_batch_only_flags_functional_orphans():
    """In a batch of 5 FRs alternating functional/non_functional/functional/...,
    only the *functional* ones without an SC are gap-reported. The two
    non_functional FRs are exempt by design (the NFR-without-SC class is
    a smell but not a deterministic defect).
    """
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"]),  # functional, no SC
            _fr("FR-002", requirement_type="non_functional", code_references=[]),
            _fr("FR-003", related_user_stories=["US-1"]),  # functional, no SC
            _fr("FR-004", requirement_type="non_functional", code_references=[]),
            _fr("FR-005", related_user_stories=["US-1"]),  # functional, no SC
        ],
        success_criteria=[],
    )
    gaps = find_trace_gaps(spec)
    fr_orphans = {g.actor for g in gaps if g.kind == GAP_FR_WITHOUT_SC}
    assert fr_orphans == {"FR-001", "FR-003", "FR-005"}
    # The two NFRs must not appear in the orphan list.
    assert "FR-002" not in fr_orphans
    assert "FR-004" not in fr_orphans


# ---------------------------------------------------------------------------
# 8. Bidirectional ("circular") FR↔SC link is the *normal* case, not a gap
# ---------------------------------------------------------------------------


def test_bidirectional_fr_sc_link_is_not_a_gap():
    """The meta-reviewer-style "circular conflict_with" test would target a
    different validator (B4), not the trace matrix. But the trace matrix
    has its own version of the question: when FR.related_success_criteria
    references SC AND SC.related_requirements references back, do we
    accidentally flag the pair as a "circular" gap?

    No — bidirectional links are the *recommended* shape (rule 1/2 of
    :func:`find_trace_gaps`). This test locks that in so a future "smarter"
    matrix doesn't mistakenly add a cycle check that breaks the common case.
    """
    spec = _spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    assert find_trace_gaps(spec) == [], (
        "bidirectional FR↔SC link is the canonical happy path, not a gap"
    )


# ---------------------------------------------------------------------------
# 9. Empty spec
# ---------------------------------------------------------------------------


def test_empty_spec_produces_no_gaps_and_no_crash():
    """A spec with zero FRs, zero SCs, zero US is degenerate but valid.
    The validator must return an empty list, not crash or invent
    synthetic gaps."""
    spec = _spec()
    assert find_trace_gaps(spec) == []
    matrix = build_trace_matrix(spec)
    assert matrix == {
        "fr_to_sc": {},
        "sc_to_fr": {},
        "us_to_fr": {},
        "fr_to_us": {},
    }


# ---------------------------------------------------------------------------
# 10. All-NFR spec
# ---------------------------------------------------------------------------


def test_only_nonfunctional_frs_with_no_sc_produces_zero_gaps():
    """5 non_functional FRs and zero SCs is a valid (if unusual) spec —
    e.g. a security-hardening change with only NFR-style requirements. The
    NFR exemption means no orphan gaps fire; we lock that in."""
    spec = _spec(
        functional_requirements=[
            _fr(f"FR-{i:03d}", requirement_type="non_functional", code_references=[])
            for i in range(1, 6)
        ],
        success_criteria=[],
    )
    assert find_trace_gaps(spec) == []


# ---------------------------------------------------------------------------
# 11. P3 user story exemption
# ---------------------------------------------------------------------------


def test_p3_user_story_without_fr_is_not_a_gap():
    """Only P1 user stories must be implemented by an FR. P2 and P3 are
    explicitly exempt (per rule 4 of :func:`find_trace_gaps`); locking that
    in so a future "stricter" pass doesn't accidentally promote P3 to
    mandatory."""
    spec = _spec(
        user_stories=[_us("US-1", "P1"), _us("US-3", "P3")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
    )
    gaps = find_trace_gaps(spec)
    assert not any(
        g.kind == GAP_US_WITHOUT_FR and g.actor == "US-3" for g in gaps
    ), "P3 US-3 must not be reported as an orphan"


# ---------------------------------------------------------------------------
# 12. Large spec performance bound
# ---------------------------------------------------------------------------


def test_large_spec_with_100_frs_paired_1to1_completes_quickly():
    """100 FRs each paired 1:1 with a unique SC — the validator must remain
    linear: building the matrix and finding gaps together should complete
    in well under a second on any reasonable machine. We assert <1s as a
    generous soft cap so the test is not flaky on a loaded CI box."""
    n = 100
    frs = [
        _fr(
            f"FR-{i:03d}",
            related_user_stories=[],
            related_success_criteria=[f"SC-{i:03d}"],
        )
        for i in range(1, n + 1)
    ]
    scs = [
        _sc(f"SC-{i:03d}", related_requirements=[f"FR-{i:03d}"])
        for i in range(1, n + 1)
    ]
    spec = _spec(functional_requirements=frs, success_criteria=scs)

    start = time.perf_counter()
    matrix = build_trace_matrix(spec)
    gaps = find_trace_gaps(spec)
    elapsed = time.perf_counter() - start

    # All pairs are bidirectionally linked → zero gaps.
    assert gaps == []
    assert len(matrix["fr_to_sc"]) == n
    assert len(matrix["sc_to_fr"]) == n
    assert elapsed < 1.0, (
        f"trace matrix on {n}-FR/{n}-SC spec took {elapsed:.3f}s "
        "— validator should remain linear; investigate regression"
    )


# ===========================================================================
# ANALYSIS
# ===========================================================================
#
# What these adversarial probes lock in (the strictness contract)
# ---------------------------------------------------------------
# * **No normalisation**: the validator does not strip whitespace
#   (tests 3, 4, 6), does not lower-case (test 5), and does not auto-fix
#   self-references (test 1). All four of these would mask LLM writer
#   bugs by silently "rescuing" near-miss ids, so the validator is
#   intentionally strict.
# * **No crash on malformed input**: even with duplicated FR ids (test 2),
#   empty strings (test 3), or whitespace-only entries (test 4), the
#   matrix builder and gap finder both return successfully. The output
#   gap-kind set is always a subset of ``VALID_GAP_KINDS``.
# * **Exemption rules are stable**:
#     - non_functional FRs are exempt from the "must have SC" check
#       (tests 7, 10),
#     - P2 / P3 user stories are exempt from the "must be implemented by
#       an FR" check (test 11),
#     - the empty spec is trivially valid (test 9).
# * **Bidirectional FR↔SC link is the canonical happy path**, not a
#   "circular reference" defect (test 8). A future smarter validator
#   that adds cycle detection must not break this.
# * **Performance is linear**: 100 FRs + 100 SCs paired 1:1 completes
#   well under 1 s (test 12). This protects against an accidental
#   quadratic in either the matrix builder or the gap finder.
#
# What these probes intentionally do NOT cover
# --------------------------------------------
# * The orchestrator-level injection path (``inject_trace_gap_issues``,
#   verdict downgrade, ``needs_review`` escalation, persisted JSON
#   artifact shape) — that is the scope of
#   ``tests/integration/test_trace_matrix_e2e.py``.
# * Cross-validator interactions (e.g. trace gap + citation problem firing
#   on the same iteration) — out of scope for this task; each validator
#   is independent by design and injection is additive.
# * Meta-reviewer-style ``conflicts_with`` cycles between PrioritizedAction
#   items — explicitly called out in test 8's docstring as B4 scope, not
#   B3. The trace matrix is purely structural (FR ↔ SC ↔ US graph) and
#   has no concept of conflicting actions.
# * Schema-level validation (e.g. soft-language guards on
#   ``SuccessCriterion.metric``) — that is the A4 layer's responsibility
#   and runs at pydantic-validation time, before the trace matrix is even
#   constructed.
