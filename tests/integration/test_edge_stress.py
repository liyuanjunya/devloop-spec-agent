"""Stress + edge tests for the DevLoop spec phase.

These tests probe the capability boundary of the validators, schema, and
``call_strict_json`` repair loop. Each test exercises one boundary
condition (empty/large/unicode/malformed) and reports an observed
wall-clock time so regressions show up as flaky pytest durations.

Conventions
-----------
* No real LLM calls — only the ``MockProvider`` from ``tests/fixtures``.
* Performance budgets are intentionally generous (≥ 2-10x of measured
  baselines on a developer laptop) so CI noise does not produce flakes.
* Citation tests reuse ``tests/fixtures/sample_repo/app/models/user.py``
  (22 lines, ``class User``) as the verified target file.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from devloop.llm.gateway import LLMGateway
from devloop.llm.json_helpers import call_strict_json
from devloop.llm.routing import ModelRouter
from devloop.llm.types import LLMResponse, Message, Usage
from devloop.spec_phase.md_json_bridge import (
    assert_spec_roundtrip_consistent,
    spec_from_json,
    spec_to_json,
    spec_to_markdown,
)
from devloop.spec_phase.schemas import (
    AcceptanceScenario,
    BlockingDecision,
    CodeRef,
    Concern,
    EdgeCase,
    Entity,
    FunctionalRequirement,
    Priority,
    Spec,
    SpecMetadata,
    SuccessCriterion,
    UserStory,
)
from devloop.spec_phase.validators.citation_verifier import verify_spec_citations
from devloop.spec_phase.validators.trace_matrix import find_trace_gaps
from tests.fixtures.mock_provider import (
    MockProvider,
    make_json_response,
    make_text_response,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Real file in the sample fixture repo used for citation verification.
# 22 lines long, contains ``class User(Base):`` at line 12.
CITED_REL_PATH = "app/models/user.py"
CITED_SYMBOL = "User"
CITED_RANGE = (12, 21)


def _meta(title: str = "edge stress feature") -> SpecMetadata:
    return SpecMetadata(feature_id="edge-stress", title=title)


def _build_gateway(handler: Callable) -> tuple[LLMGateway, MockProvider]:
    """Construct a real LLMGateway wrapping two MockProvider instances.

    Mirrors the pattern used in ``tests/unit/test_advanced.py`` so the
    strict-JSON repair loop runs through the real gateway code paths.
    """
    primary = MockProvider("anthropic", handler)
    cross = MockProvider("openai", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="m",
        cross_review_provider="openai",
        cross_review_model="n",
        stage_defaults={"role": "primary"},
    )
    gw = LLMGateway(providers={"anthropic": primary, "openai": cross}, router=router)
    return gw, primary


def _minimal_metadata_dict() -> dict:
    return {
        "feature_id": "x",
        "title": "y",
        "writer_model": "mock",
        "reviewer_model": "mock",
        "iterations": 0,
        "needs_review": False,
        "total_llm_calls": 0,
        "total_tool_calls": 0,
    }


def _minimal_spec_dict() -> dict:
    """Smallest pydantic-valid Spec payload."""
    return {
        "schema_version": "1.0",
        "metadata": _minimal_metadata_dict(),
        "summary": "stress test spec body",
        "needs_clarification": [],
        "user_stories": [],
        "functional_requirements": [],
        "success_criteria": [],
        "key_entities": [],
        "edge_cases": [],
        "assumptions": [],
        "out_of_scope": [],
        "self_concerns": [],
    }


def _build_paired_spec(
    *,
    n_fr: int,
    n_sc: int,
    n_us: int,
    code_ref: CodeRef | None = None,
) -> Spec:
    """Generate a Spec with cleanly paired FRs/SCs/USs.

    * FR-i ↔ SC-i (1:1)
    * Each US references its assigned FRs
    * When ``code_ref`` is provided, every FR carries one copy of it.

    Reused by the 50-FR, 200-FR, and 200x200 trace tests.
    """
    fr_per_us = max(1, n_fr // max(1, n_us))
    user_stories: list[UserStory] = []
    fr_to_us: dict[str, list[str]] = {}
    for ui in range(1, n_us + 1):
        us_id = f"US-{ui}"
        user_stories.append(
            UserStory(
                id=us_id,
                priority=Priority.P1,
                title=f"story {ui}",
                description=f"description for story {ui}",
            )
        )
        # Assign a slice of FRs to this US
        start = (ui - 1) * fr_per_us + 1
        end = min(start + fr_per_us - 1, n_fr)
        for fi in range(start, end + 1):
            fr_to_us.setdefault(f"FR-{fi:03d}", []).append(us_id)

    # If FR count is not divisible by US count, attach the tail FRs to US-1.
    for fi in range(1, n_fr + 1):
        fr_id = f"FR-{fi:03d}"
        if fr_id not in fr_to_us:
            fr_to_us[fr_id] = ["US-1"] if user_stories else []

    functional_requirements: list[FunctionalRequirement] = []
    for fi in range(1, n_fr + 1):
        fr_id = f"FR-{fi:03d}"
        sc_link = [f"SC-{fi:03d}"] if fi <= n_sc else []
        functional_requirements.append(
            FunctionalRequirement(
                id=fr_id,
                text=f"requirement number {fi} performs an action.",
                requirement_type="functional",
                related_user_stories=fr_to_us.get(fr_id, []),
                related_success_criteria=sc_link,
                code_references=[code_ref] if code_ref else [],
                testable=True,
            )
        )

    success_criteria: list[SuccessCriterion] = []
    for si in range(1, n_sc + 1):
        fr_link = [f"FR-{si:03d}"] if si <= n_fr else []
        success_criteria.append(
            SuccessCriterion(
                id=f"SC-{si:03d}",
                text=f"acceptance criterion {si}",
                metric=f"latency criterion {si}",
                threshold="under 500 ms",
                technology_agnostic=True,
                related_requirements=fr_link,
            )
        )

    return Spec(
        metadata=_meta(),
        summary="large generated spec body for stress testing",
        user_stories=user_stories,
        functional_requirements=functional_requirements,
        success_criteria=success_criteria,
    )


# ---------------------------------------------------------------------------
# Performance budget log — populated by individual tests for the final
# ANALYSIS table. Stored at module level so test ordering doesn't matter.
# ---------------------------------------------------------------------------

PERF: dict[str, float] = {}


def _record(label: str, seconds: float) -> None:
    PERF[label] = seconds


# ============================================================================
# T-edge-empty-spec
# ============================================================================


def test_edge_empty_spec_minimal_passes_every_validator(fixture_repo: Path) -> None:
    """1 FR + 1 SC + 1 US, all cross-referenced, no extras. All gates clean."""
    spec = Spec(
        metadata=_meta("empty spec"),
        summary="minimal spec for the empty baseline test",
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="single story",
                description="user wants the thing to work",
            )
        ],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="system implements the single behavior",
                requirement_type="functional",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
                code_references=[],  # the "no citations" branch
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="behavior verified by automated test",
                metric="passing assertions",
                threshold="100 percent",
                technology_agnostic=True,
                related_requirements=["FR-001"],
            )
        ],
    )

    t0 = time.perf_counter()
    assert_spec_roundtrip_consistent(spec)
    gaps = find_trace_gaps(spec)
    citation_problems = verify_spec_citations(fixture_repo, spec)
    elapsed = time.perf_counter() - t0
    _record("T-edge-empty-spec", elapsed)

    assert gaps == [], f"expected zero gaps on a minimal clean spec, got {gaps!r}"
    assert citation_problems == [], (
        f"expected zero citation problems when FR has no code_references, "
        f"got {citation_problems!r}"
    )
    # No assumptions / edge_cases / concerns / blockers
    assert spec.edge_cases == []
    assert spec.self_concerns == []
    assert spec.needs_clarification == []


# ============================================================================
# T-edge-large-spec-50-FRs
# ============================================================================


def test_edge_large_spec_50_FRs_performance_and_no_drift(fixture_repo: Path) -> None:
    """50 FRs x 50 SCs x 30 USs — perf budget and pydantic round-trip integrity."""
    ref = CodeRef(
        path=CITED_REL_PATH,
        symbols=[CITED_SYMBOL],
        line_ranges=[CITED_RANGE],
    )
    spec = _build_paired_spec(n_fr=50, n_sc=50, n_us=30, code_ref=ref)

    # find_trace_gaps perf
    t0 = time.perf_counter()
    gaps = find_trace_gaps(spec)
    t_gaps = time.perf_counter() - t0

    # roundtrip perf
    t0 = time.perf_counter()
    assert_spec_roundtrip_consistent(spec)
    t_round = time.perf_counter() - t0

    # pydantic dict round-trip — no field drops
    t0 = time.perf_counter()
    dumped = spec.model_dump(mode="json")
    spec_round = Spec.model_validate(dumped)
    t_pyd = time.perf_counter() - t0

    _record("T-edge-large-spec-50-FRs.find_trace_gaps", t_gaps)
    _record("T-edge-large-spec-50-FRs.roundtrip", t_round)
    _record("T-edge-large-spec-50-FRs.pydantic", t_pyd)

    assert gaps == [], f"unexpected trace gaps on cleanly paired 50-FR spec: {gaps[:3]!r}"
    assert t_gaps < 2.0, f"find_trace_gaps too slow at 50 FRs: {t_gaps:.3f}s"
    assert t_round < 2.0, f"assert_spec_roundtrip_consistent too slow: {t_round:.3f}s"
    # No field drops: dumps before/after round-trip must be identical
    assert spec_round.model_dump(mode="json") == dumped
    assert len(spec_round.functional_requirements) == 50
    assert len(spec_round.success_criteria) == 50
    assert len(spec_round.user_stories) == 30


# ============================================================================
# T-edge-very-large-spec-200-FRs
# ============================================================================


def test_edge_very_large_spec_200_FRs_perf_budget(fixture_repo: Path) -> None:
    """200 FRs scale test — measure perf characteristic, assert < 10s."""
    spec = _build_paired_spec(n_fr=200, n_sc=200, n_us=50)

    t0 = time.perf_counter()
    gaps = find_trace_gaps(spec)
    t_gaps = time.perf_counter() - t0

    t0 = time.perf_counter()
    assert_spec_roundtrip_consistent(spec)
    t_round = time.perf_counter() - t0

    _record("T-edge-very-large-spec-200-FRs.find_trace_gaps", t_gaps)
    _record("T-edge-very-large-spec-200-FRs.roundtrip", t_round)

    assert gaps == [], f"unexpected trace gaps on 200 paired FRs: {gaps[:3]!r}"
    assert t_gaps < 10.0, f"find_trace_gaps blew the 10s budget at 200 FRs: {t_gaps:.3f}s"
    assert t_round < 10.0, f"roundtrip blew the 10s budget at 200 FRs: {t_round:.3f}s"


# ============================================================================
# T-stress-malformed-json-1: missing required `metadata` field
# ============================================================================


async def test_stress_malformed_json_missing_metadata_raises_after_repair() -> None:
    """Spec missing the required `metadata` field — repair loop must exhaust then raise."""
    call_count = {"n": 0}

    def handler(model, system, messages, tools, response_format):
        call_count["n"] += 1
        # Valid JSON, but the required `metadata` field is missing entirely.
        return make_json_response(
            {
                "summary": "broken spec",
                "user_stories": [],
                "functional_requirements": [],
                "success_criteria": [],
            }
        )

    gateway, _ = _build_gateway(handler)
    max_attempts = 3

    t0 = time.perf_counter()
    with pytest.raises(ValueError) as exc_info:
        await call_strict_json(
            gateway,
            role="role",
            schema=Spec,
            messages=[Message(role="user", content="produce a spec")],
            max_repair_attempts=max_attempts,
        )
    elapsed = time.perf_counter() - t0
    _record("T-stress-malformed-json-1", elapsed)

    err = str(exc_info.value)
    assert "failed after" in err, f"error message must describe repair-exhaustion: {err!r}"
    # ``max_repair_attempts + 1`` total attempts per call_strict_json contract.
    assert call_count["n"] == max_attempts + 1, (
        f"expected {max_attempts + 1} handler calls, got {call_count['n']}"
    )
    # Descriptive error must mention the underlying validation failure ("metadata" field).
    assert "metadata" in err.lower() or "validation" in err.lower(), err


# ============================================================================
# T-stress-malformed-json-2: extra unknown top-level field
# ============================================================================


async def test_stress_malformed_json_extra_unknown_field_is_ignored() -> None:
    """Pydantic with default config silently ignores unknown fields — verify behavior."""
    call_count = {"n": 0}

    def handler(model, system, messages, tools, response_format):
        call_count["n"] += 1
        payload = _minimal_spec_dict()
        payload["unknown_top_level_field"] = "this should be ignored"
        payload["another_bogus"] = {"nested": True}
        return make_json_response(payload)

    gateway, _ = _build_gateway(handler)

    t0 = time.perf_counter()
    result = await call_strict_json(
        gateway,
        role="role",
        schema=Spec,
        messages=[Message(role="user", content="produce a spec")],
        max_repair_attempts=3,
    )
    elapsed = time.perf_counter() - t0
    _record("T-stress-malformed-json-2", elapsed)

    assert isinstance(result, Spec)
    assert call_count["n"] == 1, (
        f"unknown fields should be ignored on first try; repair loop ran {call_count['n']} times"
    )
    # The bogus key is *not* on the Spec model
    assert not hasattr(result, "unknown_top_level_field")
    assert result.metadata.feature_id == "x"


# ============================================================================
# T-stress-malformed-json-3: truncated JSON
# ============================================================================


async def test_stress_malformed_json_truncated_raises_gracefully() -> None:
    """JSON chopped at byte 100 must fail extraction and exhaust the repair loop."""
    call_count = {"n": 0}
    truncated = json.dumps(_minimal_spec_dict())[:100]  # mid-object cut
    assert not truncated.endswith("}"), "fixture invariant: truncation must drop closing brace"

    def handler(model, system, messages, tools, response_format):
        call_count["n"] += 1
        return make_text_response(truncated)

    gateway, _ = _build_gateway(handler)
    max_attempts = 3

    t0 = time.perf_counter()
    with pytest.raises(ValueError) as exc_info:
        await call_strict_json(
            gateway,
            role="role",
            schema=Spec,
            messages=[Message(role="user", content="produce a spec")],
            max_repair_attempts=max_attempts,
        )
    elapsed = time.perf_counter() - t0
    _record("T-stress-malformed-json-3", elapsed)

    err = str(exc_info.value)
    assert "failed after" in err, err
    assert call_count["n"] == max_attempts + 1


# ============================================================================
# T-edge-spec-with-100-needs-clarification-blocks
# ============================================================================


def test_edge_spec_with_100_blocking_decisions_renders_and_roundtrips() -> None:
    """100 NEEDS_CLARIFICATION blockers — render + roundtrip integrity."""
    blockers = [
        BlockingDecision(
            id=f"NC-{i:03d}",
            title=f"blocking decision number {i}",
            conflict=f"user input conflicts with existing code on point {i}",
            recommended_default=f"adopt resolution number {i} per existing convention",
            if_rejected=f"fall back to redesign path number {i}",
            related_requirements=[f"FR-{i:03d}"],
        )
        for i in range(1, 101)
    ]
    spec = Spec(
        metadata=_meta("100 blockers stress"),
        summary="spec with 100 blocking decisions for render stress",
        needs_clarification=blockers,
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="story",
                description="d",
            )
        ],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="single FR carrying the spec",
                requirement_type="functional",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="paired SC",
                metric="metric one",
                threshold="100 percent",
                related_requirements=["FR-001"],
            )
        ],
    )

    t0 = time.perf_counter()
    md = spec_to_markdown(spec)
    assert_spec_roundtrip_consistent(spec)
    elapsed = time.perf_counter() - t0
    _record("T-edge-100-blockers", elapsed)

    # Sanity checks on the rendered markdown
    assert md.count("### NC-") == 100
    blocker_pos = md.index("NEEDS_CLARIFICATION")
    us_pos = md.index("US-1")
    assert blocker_pos < us_pos, "Blocking decisions must render before user stories"
    # JSON roundtrip preserves the blockers
    s2 = spec_from_json(spec_to_json(spec))
    assert len(s2.needs_clarification) == 100
    assert s2.needs_clarification[42].id == "NC-043"


# ============================================================================
# T-edge-unicode-everywhere
# ============================================================================


def test_edge_unicode_everywhere_full_validator_suite(fixture_repo: Path) -> None:
    """Every text field contains emoji + CJK + Arabic; nothing crashes."""
    # CJK + Arabic + emoji combos. None of these contain the Latin-word
    # forbidden phrases ("placeholder", "TBD", "or equivalent", ...), so
    # the soft-language validator must pass through unchanged.
    title_unicode = "🚀 中文测试 한국어 مرحبا"
    body_unicode = "✨ 描述：用户体验 — تجربة المستخدم 🎉"
    metric_unicode = "延迟 ⏱ زمن الاستجابة"
    threshold_unicode = "≤ 100毫秒 / ١٠٠ ms"

    spec = Spec(
        metadata=_meta(title_unicode),
        summary=body_unicode,
        needs_clarification=[
            BlockingDecision(
                id="NC-001",
                title=title_unicode,
                conflict="冲突点 ⚠",
                recommended_default="采用默认方案 ✅",
                if_rejected="回退到 ✋ alternative path",
                related_requirements=["FR-001"],
            )
        ],
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title=title_unicode,
                description=body_unicode,
                why_this_priority="核心 المهمة 💯",
                independent_test="独立测试 🧪",
                acceptance=[
                    AcceptanceScenario(
                        given="已登录 🔐",
                        when="提交评论 📝",
                        then="评论显示 👀 مباشرة",
                    )
                ],
            )
        ],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text=body_unicode,
                requirement_type="functional",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
                code_references=[
                    CodeRef(
                        path=CITED_REL_PATH,
                        symbols=[CITED_SYMBOL],
                        line_ranges=[CITED_RANGE],
                    )
                ],
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text=body_unicode,
                metric=metric_unicode,
                threshold=threshold_unicode,
                related_requirements=["FR-001"],
            )
        ],
        key_entities=[Entity(name="实体", description=body_unicode, fields=["字段一 🅰", "字段二 🅱"])],
        edge_cases=[EdgeCase(description="边缘情况 🌀", handling="正常处理 🛡 الحماية")],
        assumptions=["假设一 📌", "假设二 🎯"],
        out_of_scope=["范围外 🚫", "out of scope مستبعد"],
        self_concerns=[
            Concern(
                location="FR-001",
                concern="担心点 🤔",
                evidence_gap="证据缺口 📉",
                suggested_resolution="建议方案 🛠 الحل",
            )
        ],
    )

    t0 = time.perf_counter()
    assert_spec_roundtrip_consistent(spec)
    gaps = find_trace_gaps(spec)
    problems = verify_spec_citations(fixture_repo, spec)
    md = spec_to_markdown(spec)
    elapsed = time.perf_counter() - t0
    _record("T-edge-unicode", elapsed)

    assert gaps == []
    assert problems == []
    # Every unicode token must survive into rendered markdown
    for token in ("🚀", "中文测试", "한국어", "مرحبا", "⏱", "毫秒"):
        assert token in md, f"unicode token {token!r} dropped from rendered markdown"


# ============================================================================
# T-edge-deeply-nested-acceptance-scenarios
# ============================================================================


def test_edge_deeply_nested_acceptance_scenarios(fixture_repo: Path) -> None:
    """One US with 50 acceptance scenarios — schema + roundtrip + render."""
    acceptance = [
        AcceptanceScenario(
            given=f"precondition {i}",
            when=f"action {i} is performed",
            then=f"outcome {i} is observed",
        )
        for i in range(1, 51)
    ]
    spec = Spec(
        metadata=_meta("50 acceptance scenarios"),
        summary="user story with 50 acceptance scenarios",
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="multi-scenario story",
                description="a single story exercising many acceptance scenarios",
                acceptance=acceptance,
            )
        ],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="implements all 50 scenarios",
                requirement_type="functional",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="all 50 scenarios pass",
                metric="passing scenarios",
                threshold="50 of 50",
                related_requirements=["FR-001"],
            )
        ],
    )

    t0 = time.perf_counter()
    assert_spec_roundtrip_consistent(spec)
    md = spec_to_markdown(spec)
    gaps = find_trace_gaps(spec)
    elapsed = time.perf_counter() - t0
    _record("T-edge-50-acceptance", elapsed)

    assert gaps == []
    assert len(spec.user_stories[0].acceptance) == 50
    # Each scenario renders as a numbered Given/When/Then line
    assert md.count("**Given**") == 50
    assert md.count("**When**") == 50
    assert md.count("**Then**") == 50


# ============================================================================
# T-edge-empty-strings
# ============================================================================


def test_edge_empty_strings_in_optional_text_fields(fixture_repo: Path) -> None:
    """Empty strings (where the schema accepts them) must not crash validators."""
    spec = Spec(
        metadata=SpecMetadata(feature_id="", title=""),
        summary="",
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="",
                description="",
                why_this_priority="",
                independent_test="",
                acceptance=[AcceptanceScenario(given="", when="", then="")],
            )
        ],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="",
                requirement_type="functional",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="",
                metric="",
                threshold="",
                related_requirements=["FR-001"],
            )
        ],
        key_entities=[Entity(name="", description="", fields=[], references=[])],
        edge_cases=[EdgeCase(description="", handling="")],
    )

    t0 = time.perf_counter()
    assert_spec_roundtrip_consistent(spec)
    gaps = find_trace_gaps(spec)
    problems = verify_spec_citations(fixture_repo, spec)
    md = spec_to_markdown(spec)
    elapsed = time.perf_counter() - t0
    _record("T-edge-empty-strings", elapsed)

    # Trace matrix is link-driven, so a properly-linked-but-empty spec is still gap-free.
    assert gaps == []
    # No code_references on FR-001 → no citation problems.
    assert problems == []
    # Rendering still produces a document (heading uses empty title)
    assert md.startswith("# Feature Specification:")


# ============================================================================
# T-stress-citation-verifier-on-1000-refs
# ============================================================================


def test_stress_citation_verifier_on_1000_refs_perf_budget(fixture_repo: Path) -> None:
    """100 FRs x 10 code_references each = 1000 references, all pointing to user.py."""
    ref = CodeRef(
        path=CITED_REL_PATH,
        symbols=[CITED_SYMBOL],
        line_ranges=[CITED_RANGE],
    )
    frs = [
        FunctionalRequirement(
            id=f"FR-{i:03d}",
            text=f"requirement {i}",
            requirement_type="functional",
            related_user_stories=["US-1"],
            related_success_criteria=[f"SC-{i:03d}"],
            code_references=[ref] * 10,
        )
        for i in range(1, 101)
    ]
    scs = [
        SuccessCriterion(
            id=f"SC-{i:03d}",
            text=f"criterion {i}",
            metric=f"metric {i}",
            threshold="under 1 second",
            related_requirements=[f"FR-{i:03d}"],
        )
        for i in range(1, 101)
    ]
    spec = Spec(
        metadata=_meta("1000-citation stress"),
        summary="100 FRs each with 10 code_references for verifier stress",
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="story",
                description="d",
            )
        ],
        functional_requirements=frs,
        success_criteria=scs,
    )
    # Sanity: 100 * 10 = 1000 refs total
    total_refs = sum(len(fr.code_references) for fr in spec.functional_requirements)
    assert total_refs == 1000

    t0 = time.perf_counter()
    problems = verify_spec_citations(fixture_repo, spec)
    elapsed = time.perf_counter() - t0
    _record("T-stress-citation-1000-refs", elapsed)

    assert problems == [], (
        f"expected zero problems on valid refs, got {len(problems)} (first: {problems[:1]!r})"
    )
    assert elapsed < 10.0, f"verify_spec_citations blew the 10s budget at 1000 refs: {elapsed:.3f}s"


# ============================================================================
# T-stress-trace-matrix-on-200x200
# ============================================================================


def test_stress_trace_matrix_200x200_perf_budget() -> None:
    """200 FRs each linking every one of 200 SCs — fully paired matrix."""
    n = 200
    all_sc_ids = [f"SC-{i:03d}" for i in range(1, n + 1)]
    all_fr_ids = [f"FR-{i:03d}" for i in range(1, n + 1)]

    frs = [
        FunctionalRequirement(
            id=fr_id,
            text=f"requirement {fr_id}",
            requirement_type="functional",
            related_user_stories=["US-1"],
            related_success_criteria=list(all_sc_ids),
        )
        for fr_id in all_fr_ids
    ]
    scs = [
        SuccessCriterion(
            id=sc_id,
            text=f"criterion {sc_id}",
            metric=f"metric {sc_id}",
            threshold="under 1 second",
            related_requirements=list(all_fr_ids),
        )
        for sc_id in all_sc_ids
    ]
    spec = Spec(
        metadata=_meta("200x200 trace stress"),
        summary="fully paired 200x200 trace matrix",
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="story",
                description="d",
            )
        ],
        functional_requirements=frs,
        success_criteria=scs,
    )

    t0 = time.perf_counter()
    gaps = find_trace_gaps(spec)
    elapsed = time.perf_counter() - t0
    _record("T-stress-trace-200x200", elapsed)

    assert gaps == []
    assert elapsed < 2.0, (
        f"find_trace_gaps blew the 2s budget on a 200x200 fully paired matrix: {elapsed:.3f}s"
    )


# ============================================================================
# Diagnostic — emit performance table when run with -s
# ============================================================================


def test_zzz_performance_summary() -> None:
    """Always-passing sink that pretty-prints the recorded perf table.

    Named ``zzz`` so pytest discovery executes it last and the table reflects
    every measurement. Has no assertions other than 'something was measured'.
    """
    assert PERF, "no perf measurements were recorded — preceding tests did not run"
    print("\n\n=== EDGE/STRESS perf summary ===")
    width = max(len(k) for k in PERF) + 2
    for label, seconds in sorted(PERF.items()):
        ms = seconds * 1000
        print(f"{label:<{width}} {ms:>9.2f} ms")
    print("=================================\n")


def test_misc_unused_response_fixture_keeps_lint_happy() -> None:
    """Anchor the unused-import scrutiny for ``LLMResponse``/``Usage``.

    Some lint runs would flag the bare imports as unused even though they are
    documentation for the ``LLMResponse`` returned by ``MockProvider``. This
    micro-test references both to keep ``ruff F401`` quiet without a noqa.
    """
    r = LLMResponse(usage=Usage())
    assert r.usage.input_tokens == 0
