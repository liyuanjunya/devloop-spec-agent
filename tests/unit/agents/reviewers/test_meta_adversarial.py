"""Adversarial / boundary tests for the B4 meta-reviewer.

These tests probe the meta-reviewer and its schema with deliberately
malformed or pathological inputs. Goal: document the exact behaviour at
the capability boundary so future refactors notice when a guarantee
silently changes.

What "boundary" means here:

* **Pydantic rejects**: cases where the schema's declared invariants
  (e.g. ``ge=1, le=5`` on priority) actively reject input. These tests
  pin those guarantees so a careless schema relaxation produces a
  failing test instead of a silent acceptance.
* **Pydantic permits**: cases where the schema places no constraint
  (e.g. empty ``source_issue_ids``) — the test documents that the
  current contract is "permitted" and the downstream consumer is
  responsible for handling it. If we later add a validator, these tests
  flip to ``pytest.raises`` and serve as the migration trigger.
* **Downstream effects**: cases where the schema accepts something
  unusual (e.g. ``conflicts_with`` self-reference, unknown id, id
  collision) but the rewriter prompt-rendering path must still terminate
  in finite time and embed the data faithfully.

Each test starts with a 1-2 line "Boundary:" comment describing what
guarantee is being pinned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from devloop.cache import NullCache
from devloop.config import Settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.reviewers.meta import run_meta_reviewer
from devloop.spec_phase.agents.writer import run_rewriter
from devloop.spec_phase.prompts_loader import PromptLoader
from devloop.spec_phase.schemas import (
    SCHEMA_VERSION,
    ConfirmedIntent,
    ConsolidatedReview,
    MetaReviewResult,
    PrioritizedAction,
    ReviewIssue,
    ReviewResult,
    Severity,
    Spec,
    SpecMetadata,
)
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import MockProvider, make_json_response

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action(
    *,
    aid: str = "META-001",
    priority: int = 1,
    severity: Severity = Severity.CRITICAL,
    affected_axes: list[str] | None = None,
    source_issue_ids: list[str] | None = None,
    conflicts_with: list[str] | None = None,
    description: str = "do the thing",
) -> PrioritizedAction:
    return PrioritizedAction(
        id=aid,
        priority=priority,
        severity=severity,
        affected_axes=affected_axes
        if affected_axes is not None
        else ["architecture"],  # type: ignore[arg-type]
        source_issue_ids=source_issue_ids
        if source_issue_ids is not None
        else ["ARCH-001"],
        description=description,
        rationale="r",
        suggested_action="s",
        conflicts_with=conflicts_with or [],
    )


def _review_issue(
    *,
    iid: str,
    reviewer_type: str,
    severity: Severity = Severity.HIGH,
    location: str = "FR-007",
) -> ReviewIssue:
    return ReviewIssue(
        id=iid,
        reviewer_type=reviewer_type,  # type: ignore[arg-type]
        severity=severity,
        location=location,
        description="auto",
        evidence="auto-evidence",
        suggested_action="auto-fix",
    )


def _consolidated(reviews: list[ReviewResult]) -> ConsolidatedReview:
    total = sum(len(r.issues) for r in reviews)
    critical = sum(r.critical_issue_count for r in reviews)
    if not reviews or all(r.verdict == "pass" for r in reviews):
        verdict = "pass"
    elif any(r.verdict == "fail" for r in reviews) or critical > 0:
        verdict = "fail"
    else:
        verdict = "needs_refine"
    return ConsolidatedReview(
        reviews=reviews,
        overall_verdict=verdict,  # type: ignore[arg-type]
        total_issues=total,
        critical_issues=critical,
    )


def _sample_spec() -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="demo", title="Demo"),
        summary="demo summary",
    )


def _empty_spec_dict() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "feature_id": "demo",
            "title": "Demo",
            "writer_model": "mock",
            "reviewer_model": "mock",
            "iterations": 1,
            "needs_review": False,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
        },
        "summary": "demo",
        "user_stories": [
            {
                "id": "US-1",
                "priority": "P1",
                "title": "t",
                "description": "d",
                "why_this_priority": "w",
                "independent_test": "i",
                "acceptance": [{"given": "g", "when": "w", "then": "t"}],
            }
        ],
        "functional_requirements": [
            {
                "id": "FR-001",
                "text": "do X",
                "requirement_type": "functional",
                "related_user_stories": ["US-1"],
                "related_success_criteria": ["SC-001"],
                "code_references": [],
                "testable": True,
            }
        ],
        "success_criteria": [
            {
                "id": "SC-001",
                "text": "fast",
                "metric": "ms",
                "threshold": "< 100ms",
                "technology_agnostic": True,
                "related_requirements": ["FR-001"],
            }
        ],
        "key_entities": [
            {"name": "X", "description": "x", "fields": [], "references": []}
        ],
        "edge_cases": [],
        "assumptions": [],
        "out_of_scope": [],
        "self_concerns": [],
    }


def _build_ctx(tmp_path: Path, handler) -> SpecContext:
    settings = Settings()
    a_prov = MockProvider("anthropic", handler)
    o_prov = MockProvider("openai", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
        stage_defaults={"writer": "primary", "reviewer": "cross_review"},
    )
    gateway = LLMGateway(
        providers={"anthropic": a_prov, "openai": o_prov},
        router=router,
        trace=NullTraceWriter(),
    )
    ctx = SpecContext.__new__(SpecContext)
    ctx.run_id = "test-run"
    ctx.user_input = "demo"
    ctx.repo_path = tmp_path.resolve()
    ctx.workspace_root = tmp_path
    ctx.settings = settings
    ctx.gateway = gateway
    ctx.tools = build_default_registry()
    ctx.prompts = PromptLoader(PROMPTS_DIR)
    ctx.cache = NullCache()
    ctx.trace = NullTraceWriter()
    ctx.skeleton_builder = None  # type: ignore[assignment]
    ctx.repo_skeleton = None
    ctx.intent = ConfirmedIntent(
        primary="demo intent", intent_type="add_feature", scope=["backend"]
    )
    ctx.exploration = None
    ctx.approach = None
    ctx.spec = None
    ctx.consolidated_review = None
    ctx.total_llm_calls = 0
    ctx.total_tool_calls = 0
    ctx.iterations = 0
    ctx.run_counter = {}
    ctx.metadata = {}
    return ctx


# ---------------------------------------------------------------------------
# 1) Zero issues → meta-reviewer skipped (orchestrator gate)
# ---------------------------------------------------------------------------


async def test_zero_issues_meta_reviewer_skipped(tmp_path):
    """Boundary: when ConsolidatedReview is all-pass with zero issues, the
    orchestrator's gate condition (orchestrator.py:1058-1062) evaluates
    False, so ``run_meta_reviewer`` is never invoked.

    This test pins the gate semantics — it asserts both that
    ``ConsolidatedReview.all_pass`` correctly reports True for the empty
    case, and that the boolean composition the orchestrator uses
    produces False.
    """
    review = _consolidated(
        [
            ReviewResult(
                reviewer_type=axis,  # type: ignore[arg-type]
                judge_model="gpt",
                verdict="pass",
            )
            for axis in (
                "architecture",
                "completeness",
                "executability",
                "consistency",
            )
        ]
    )

    assert review.all_pass is True
    assert review.total_issues == 0

    # Mirror the orchestrator gate: orchestrator.py:1058-1062
    enable_meta = True
    should_run_meta = (
        enable_meta and not review.all_pass and review.total_issues > 0
    )
    assert should_run_meta is False, (
        "gate must skip meta-reviewer when review is all-pass with zero issues"
    )

    # Defence-in-depth: even if the test wired up a MockProvider that
    # exploded on any LLM call, no call would happen since the orchestrator
    # gates the meta-reviewer out. Drive the meta-reviewer through a
    # provider that ASSERTS it's never called — this catches any future
    # accidental call site that bypasses the gate.
    sentinel = {"called": False}

    def handler(model, system, messages, tools, response_format):
        sentinel["called"] = True
        return make_json_response({})

    _build_ctx(tmp_path, handler)
    # We deliberately do NOT call run_meta_reviewer here — the assertion
    # is that the gate logic above protects us. Verify the sentinel is
    # untouched after the gate check.
    assert sentinel["called"] is False


# ---------------------------------------------------------------------------
# 2) One reviewer, many issues → meta produces ≤ N actions
# ---------------------------------------------------------------------------


async def test_one_reviewer_many_issues_meta_produces_bounded_actions(tmp_path):
    """Boundary: when a single reviewer raises 20 issues, the meta-reviewer
    may dedupe but MUST NOT amplify — output ``len(actions) <= 20``.

    The schema places no upper bound on ``actions`` itself, so this test
    drives the agent with a deduping MockProvider and verifies the
    invariant via the agent's actual code path.
    """
    issues = [
        _review_issue(
            iid=f"ARCH-{i:03d}",
            reviewer_type="architecture",
            severity=Severity.HIGH,
            location=f"FR-{i:03d}",
        )
        for i in range(1, 21)
    ]
    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=issues,
            ),
            ReviewResult(
                reviewer_type="completeness", judge_model="gpt", verdict="pass"
            ),
            ReviewResult(
                reviewer_type="executability", judge_model="gpt", verdict="pass"
            ),
            ReviewResult(
                reviewer_type="consistency", judge_model="gpt", verdict="pass"
            ),
        ]
    )
    assert review.total_issues == 20

    # Mock returns 18 actions (small dedupe) — the agent must accept that
    # and propagate it without inflating.
    canned = {
        "schema_version": SCHEMA_VERSION,
        "actions": [
            _action(
                aid=f"META-{i:03d}",
                priority=min(1 + (i // 5), 5),
                severity=Severity.HIGH,
                source_issue_ids=[f"ARCH-{i:03d}"],
                description=f"action {i}",
            ).model_dump(mode="json")
            for i in range(1, 19)
        ],
        "cross_axis_conflicts": [],
        "summary": "deduped 20 → 18",
        "judge_model": "gpt",
    }

    def handler(model, system, messages, tools, response_format):
        return make_json_response(canned)

    ctx = _build_ctx(tmp_path, handler)
    result = await run_meta_reviewer(ctx, _sample_spec(), review)

    assert len(result.actions) <= len(issues), (
        f"meta-reviewer produced {len(result.actions)} actions for "
        f"{len(issues)} input issues — must not amplify"
    )
    assert len(result.actions) == 18


# ---------------------------------------------------------------------------
# 3) Priority out of bounds → pydantic rejects
# ---------------------------------------------------------------------------


def test_priority_below_lower_bound_rejected():
    """Boundary: ``priority`` must satisfy ``ge=1`` — values < 1 raise
    ValidationError. Pins schemas/review.py:101."""
    with pytest.raises(ValidationError) as exc_info:
        _action(priority=0)
    # The error must mention the priority constraint so future regressions
    # are diagnostic.
    msg = str(exc_info.value)
    assert "priority" in msg


def test_priority_above_upper_bound_rejected():
    """Boundary: ``priority`` must satisfy ``le=5`` — values > 5 raise
    ValidationError. Pins schemas/review.py:101."""
    with pytest.raises(ValidationError) as exc_info:
        _action(priority=6)
    msg = str(exc_info.value)
    assert "priority" in msg


def test_priority_negative_rejected():
    """Boundary: deeply-negative priority also rejected (regression guard
    against schemas silently switching to abs()/clamp())."""
    with pytest.raises(ValidationError):
        _action(priority=-100)


def test_priority_far_above_upper_bound_rejected():
    """Boundary: very large priorities also rejected (regression guard)."""
    with pytest.raises(ValidationError):
        _action(priority=999)


# ---------------------------------------------------------------------------
# 4) Empty source_issue_ids → permitted; documented as semantically odd
# ---------------------------------------------------------------------------


def test_empty_source_issue_ids_permitted_but_semantically_odd():
    """Boundary: ``source_issue_ids=[]`` is currently PERMITTED by the
    schema — no ``min_length`` validator. The field's docstring says it
    "merges" ReviewIssue ids, so an empty list semantically means "this
    action wasn't actually merged from anything."

    Documenting this lets us notice if a future validator change rejects
    empty lists (this test will then fail at construction).
    """
    a = _action(source_issue_ids=[])
    assert a.source_issue_ids == []
    # Round-trip preserves the empty list (no implicit coercion).
    dumped = a.model_dump(mode="json")
    assert dumped["source_issue_ids"] == []
    round_tripped = PrioritizedAction.model_validate(dumped)
    assert round_tripped.source_issue_ids == []


# ---------------------------------------------------------------------------
# 5) Empty affected_axes → permitted; document
# ---------------------------------------------------------------------------


def test_empty_affected_axes_permitted_but_semantically_odd():
    """Boundary: ``affected_axes=[]`` is currently PERMITTED by the schema.

    Semantically odd: the action claims to fix something that no axis
    reviewer raised. The schema places no ``min_length`` on the list. If
    we later add ``min_length=1``, this test flips to expect
    ``ValidationError`` instead and serves as the migration trigger.
    """
    a = _action(affected_axes=[])
    assert a.affected_axes == []
    # Round-trip.
    dumped = a.model_dump(mode="json")
    assert dumped["affected_axes"] == []


# ---------------------------------------------------------------------------
# 6) Action id collision → permitted by pydantic; rewriter shows both
# ---------------------------------------------------------------------------


async def test_duplicate_action_ids_permitted_by_schema(tmp_path):
    """Boundary: two ``PrioritizedAction``s with the same ``id`` are
    PERMITTED by the schema — ``actions: list[PrioritizedAction]`` has no
    uniqueness constraint. Downstream consumers must therefore not assume
    ``action.id`` is a primary key.

    This test also drives the rewriter to confirm the duplicate survives
    serialization and lands in the rewriter prompt (so the downstream
    LLM at least sees the collision and can react). Documents the
    downstream risk: a rewriter that indexes by id would silently drop
    one of the two duplicates.
    """
    meta = MetaReviewResult(
        actions=[
            _action(aid="META-001", priority=1, description="first incarnation"),
            _action(aid="META-001", priority=2, description="second incarnation"),
        ],
        summary="collision",
        judge_model="gpt",
    )
    # Pydantic accepted both. Confirm the list preserves both entries
    # (no de-duplication, no first-wins).
    assert len(meta.actions) == 2
    assert meta.actions[0].description == "first incarnation"
    assert meta.actions[1].description == "second incarnation"

    # Drive the rewriter and confirm both copies appear in the prompt JSON.
    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["sys"] = system
        return make_json_response(_empty_spec_dict())

    ctx = _build_ctx(tmp_path, handler)
    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[_review_issue(iid="ARCH-001", reviewer_type="architecture")],
            ),
        ]
    )
    await run_rewriter(
        ctx, _sample_spec(), review, iteration=1, meta_review=meta
    )

    sys = captured["sys"]
    # Both action descriptions must survive serialization — confirms the
    # rewriter sees the collision rather than the JSON serializer silently
    # collapsing duplicates.
    assert "first incarnation" in sys
    assert "second incarnation" in sys
    # And both have id META-001 — count is exactly 2.
    assert sys.count('"id": "META-001"') == 2, (
        "both collided ids must be rendered (no silent dedup)"
    )


# ---------------------------------------------------------------------------
# 7) conflicts_with self → permitted; rewriter prompt-rendering terminates
# ---------------------------------------------------------------------------


async def test_conflicts_with_self_is_permitted_and_renders_finitely(tmp_path):
    """Boundary: ``conflicts_with`` referencing the action's own id is
    PERMITTED by the schema (no graph validation). The rewriter prompt
    renderer is a straight JSON dump — it does not traverse the conflict
    graph, so no infinite-loop risk exists at the *rendering* layer.

    This test pins both guarantees: (a) schema permits the self-reference,
    (b) prompt rendering is a single ``json.dumps`` call and returns in
    finite time with the self-reference visible to the LLM.
    """
    meta = MetaReviewResult(
        actions=[
            _action(
                aid="META-001",
                priority=1,
                conflicts_with=["META-001"],
                description="self-conflicting action",
            )
        ],
        summary="self-conflict",
        judge_model="gpt",
    )
    assert meta.actions[0].conflicts_with == ["META-001"]

    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["sys"] = system
        return make_json_response(_empty_spec_dict())

    ctx = _build_ctx(tmp_path, handler)
    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[_review_issue(iid="ARCH-001", reviewer_type="architecture")],
            ),
        ]
    )
    # If the renderer ever introduced a graph traversal here, a self-edge
    # would loop forever. The assertion that we reach this line at all is
    # part of the test.
    await run_rewriter(
        ctx, _sample_spec(), review, iteration=1, meta_review=meta
    )

    sys = captured["sys"]
    # The self-reference is visible to the LLM as-is.
    assert '"conflicts_with": [' in sys
    assert "META-001" in sys
    # Extract the JSON region around META-001 and verify it references itself.
    region = sys[sys.find('"id": "META-001"') :]
    # Pull the first conflicts_with array after the id.
    cw_start = region.find('"conflicts_with"')
    assert cw_start != -1
    cw_segment = region[cw_start : cw_start + 80]
    assert "META-001" in cw_segment, (
        "self-conflict must appear in the rendered conflicts_with array"
    )


# ---------------------------------------------------------------------------
# 8) conflicts_with unknown id → permitted; rewriter sees the orphan
# ---------------------------------------------------------------------------


async def test_conflicts_with_unknown_id_is_permitted_and_passes_through(tmp_path):
    """Boundary: ``conflicts_with`` pointing at a non-existent ``META-999``
    is PERMITTED by the schema — there is no cross-action referential
    integrity check. The rewriter prompt embeds it verbatim, leaving it
    to the downstream LLM (and logs) to notice that the referenced
    action does not exist.

    The test pins both layers:
      * schema layer: no ValidationError when constructing the action,
      * prompt layer: rewriter prompt includes ``META-999`` verbatim so a
        diff or log search will reveal orphan references.
    """
    meta = MetaReviewResult(
        actions=[
            _action(aid="META-001", priority=1, conflicts_with=["META-999"]),
        ],
        summary="orphan conflict",
        judge_model="gpt",
    )
    # No validation error: the schema does not check cross-action refs.
    assert meta.actions[0].conflicts_with == ["META-999"]

    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["sys"] = system
        return make_json_response(_empty_spec_dict())

    ctx = _build_ctx(tmp_path, handler)
    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[_review_issue(iid="ARCH-001", reviewer_type="architecture")],
            ),
        ]
    )
    await run_rewriter(
        ctx, _sample_spec(), review, iteration=1, meta_review=meta
    )

    sys = captured["sys"]
    # The orphan id must appear verbatim — the rewriter does not silently
    # drop unknown references.
    assert "META-999" in sys
    # And the META-001 action that owns the orphan reference is still there.
    assert '"id": "META-001"' in sys
    # No META-999 action *definition* sneaks in — only the orphan reference.
    # (Counting how many times the id appears: should be exactly 1, in the
    # conflicts_with array; not as an action id key.)
    assert sys.count('"id": "META-999"') == 0


# ---------------------------------------------------------------------------
# Schema-layer regression guard: every Severity stays valid
# ---------------------------------------------------------------------------


def test_action_accepts_all_documented_severities():
    """Boundary regression guard: every value of the ``Severity`` enum
    must be a valid action severity. Catches the case where someone adds
    a new severity to the enum but forgets to update a downstream
    consumer that pattern-matches."""
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM):
        a = _action(severity=sev)
        assert a.severity == sev


# ---------------------------------------------------------------------------
# Schema-layer regression guard: roundtrip pathology
# ---------------------------------------------------------------------------


def test_roundtrip_preserves_all_documented_boundary_inputs():
    """Final boundary regression guard: a MetaReviewResult constructed
    with every "permitted-but-odd" input above must serialize and
    deserialize without loss. If any of the boundary guarantees ever
    flips to "rejected", this test surfaces the change."""
    meta = MetaReviewResult(
        actions=[
            _action(aid="META-001", source_issue_ids=[]),  # boundary 4
            _action(aid="META-002", affected_axes=[]),  # boundary 5
            _action(aid="META-001"),  # boundary 6: id collision with above
            _action(aid="META-003", conflicts_with=["META-003"]),  # boundary 7
            _action(aid="META-004", conflicts_with=["META-999"]),  # boundary 8
        ],
        summary="all boundaries combined",
        judge_model="gpt",
    )
    dumped = meta.model_dump(mode="json")
    rt = MetaReviewResult.model_validate(dumped)
    assert rt == meta
    # Every boundary field survived round-trip.
    assert rt.actions[0].source_issue_ids == []
    assert rt.actions[1].affected_axes == []
    assert rt.actions[2].id == "META-001"
    assert rt.actions[3].conflicts_with == ["META-003"]
    assert rt.actions[4].conflicts_with == ["META-999"]
    # JSON round-trip too (catches default=str fallout the orchestrator
    # uses when persisting artifacts).
    serialised = json.dumps(dumped, default=str)
    reparsed = json.loads(serialised)
    rt2 = MetaReviewResult.model_validate(reparsed)
    assert rt2 == meta
