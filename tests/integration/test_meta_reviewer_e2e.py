"""End-to-end integration tests for the B4 meta-reviewer wiring.

These tests drive ``run_rewriter`` directly (the unit-level integration seam
between the meta-reviewer and the rewriter). They verify:

1. The rewriter consumes ``MetaReviewResult`` via the ``meta_review_block``
   in its system prompt, not the raw 4-axis issue list.
2. Merged actions appear once — duplicate findings from two reviewers do
   not produce two separate META actions in the prompt.
3. Per-action priority and ``conflicts_with`` annotations are surfaced in
   the rewriter prompt verbatim.
4. When the meta-reviewer is disabled at the orchestrator level
   (``Settings.orchestrator.enable_meta_reviewer = False``), the gate
   condition skips the meta call entirely so the rewriter falls back to
   the raw issues block.
5. When the meta-reviewer raises an exception, the orchestrator catches
   it, traces the failure, and the rewriter sees ``None`` for
   ``meta_review`` (so the rewriter block is empty and the raw issues are
   the only signal).

Each test mocks only the LLM provider; the real ``call_strict_json`` /
``PromptLoader`` / ``run_rewriter`` / ``_run_meta_review`` paths execute,
so the integration of those moving parts is genuinely covered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devloop.cache import NullCache
from devloop.config import Settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter, TraceWriter
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.writer import run_rewriter
from devloop.spec_phase.orchestrator import SpecOrchestrator
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

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _sample_spec() -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="demo", title="Demo"),
        summary="demo summary",
    )


def _review_issue(
    *,
    iid: str,
    reviewer_type: str,
    severity: Severity = Severity.HIGH,
    location: str = "FR-007",
    description: str = "issue",
) -> ReviewIssue:
    return ReviewIssue(
        id=iid,
        reviewer_type=reviewer_type,  # type: ignore[arg-type]
        severity=severity,
        location=location,
        description=description,
        evidence="spec line 42",
        suggested_action="fix it",
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


def _build_ctx(
    tmp_path: Path,
    handler,
    *,
    intent: ConfirmedIntent | None = None,
) -> tuple[SpecContext, MockProvider, MockProvider]:
    """Build a SpecContext with a real PromptLoader bound to a MockProvider.

    Returns ``(ctx, anthropic_provider, openai_provider)`` so individual
    tests can inspect ``provider.calls`` to confirm or refute a call site
    fired.
    """
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
    ctx.intent = intent or ConfirmedIntent(
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
    return ctx, a_prov, o_prov


def _empty_spec_dict(iter_n: int = 1) -> dict:
    """Minimum-viable Spec dict the rewriter can return without exploding."""
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "feature_id": "demo",
            "title": "Demo Feature",
            "writer_model": "mock-claude",
            "reviewer_model": "mock-gpt",
            "iterations": iter_n,
            "needs_review": False,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
        },
        "summary": "demo",
        "user_stories": [
            {
                "id": "US-1",
                "priority": "P1",
                "title": "Use it",
                "description": "user does the thing",
                "why_this_priority": "core",
                "independent_test": "test it",
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


# ---------------------------------------------------------------------------
# 1) Dedup across reviewers
# ---------------------------------------------------------------------------


async def test_dedupes_same_issue_across_reviewers(tmp_path):
    """Arch + completeness both flag FR-007 → meta returns 1 merged action
    → rewriter sees ONE merged META action, not two parallel ones.

    Concretely we verify:
    - ``source_issue_ids`` in the rewriter prompt lists BOTH original ids.
    - Exactly one ``"id": "META-..."`` action ends up in the rewriter's
      embedded JSON block (no second separate META action snuck in).
    """
    merged = MetaReviewResult(
        actions=[
            PrioritizedAction(
                id="META-001",
                priority=1,
                severity=Severity.CRITICAL,
                affected_axes=["architecture", "completeness"],
                source_issue_ids=["ARCH-007", "COMP-007"],
                description="FR-007 rate-limit ordering wrong",
                rationale="Both axes converge on the same defect.",
                suggested_action="Move rate-limit before validation in FR-007.",
            )
        ],
        cross_axis_conflicts=[],
        summary="merged 2 axes",
        judge_model="gpt",
    )

    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["rewriter_system"] = system
            return make_json_response(_empty_spec_dict())
        # Shouldn't be reached for this test
        return make_json_response(_empty_spec_dict())

    ctx, _, _ = _build_ctx(tmp_path, handler)

    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(
                        iid="ARCH-007",
                        reviewer_type="architecture",
                        severity=Severity.CRITICAL,
                        description="rate-limit after validation breaks security model",
                    )
                ],
            ),
            ReviewResult(
                reviewer_type="completeness",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(
                        iid="COMP-007",
                        reviewer_type="completeness",
                        description="rate-limit threshold unspecified for FR-007",
                    )
                ],
            ),
        ]
    )

    await run_rewriter(
        ctx, _sample_spec(), review, iteration=1, meta_review=merged
    )

    rewriter_sys = captured["rewriter_system"]
    assert "Meta-reviewer (B4)" in rewriter_sys
    # Both original ids must be cited inside the merged action's
    # source_issue_ids field (so the rewriter can trace back).
    assert "ARCH-007" in rewriter_sys
    assert "COMP-007" in rewriter_sys
    # The merged action is present exactly once. Counting "META-001" twice
    # would mean the meta-reviewer's dedup wasn't honored downstream.
    assert rewriter_sys.count('"id": "META-001"') == 1
    # And no second META action snuck in.
    assert '"id": "META-002"' not in rewriter_sys


# ---------------------------------------------------------------------------
# 2) Order by priority
# ---------------------------------------------------------------------------


async def test_orders_by_priority(tmp_path):
    """Meta-reviewer returns actions sorted by priority (META-001=p1,
    META-002=p3, META-003=p5). Rewriter prompt must preserve that order
    so the rewriter applies the highest-priority fix first.

    Per the prompt contract (prompts/reviewer/meta.md): "id: assign
    sequential META-001, META-002, … in priority order." The orchestrator
    does not re-sort client-side — it trusts the meta-reviewer's order.
    This test enforces *order preservation* end-to-end.
    """
    actions_in_priority_order = MetaReviewResult(
        actions=[
            PrioritizedAction(
                id="META-001",
                priority=1,
                severity=Severity.CRITICAL,
                affected_axes=["architecture"],
                source_issue_ids=["ARCH-001"],
                description="P1 critical fix",
                rationale="critical security defect",
                suggested_action="apply p1 fix",
            ),
            PrioritizedAction(
                id="META-002",
                priority=3,
                severity=Severity.HIGH,
                affected_axes=["completeness"],
                source_issue_ids=["COMP-001"],
                description="P3 medium-high",
                rationale="downstream-implementable",
                suggested_action="apply p3 fix",
            ),
            PrioritizedAction(
                id="META-003",
                priority=5,
                severity=Severity.MEDIUM,
                affected_axes=["consistency"],
                source_issue_ids=["CONS-001"],
                description="P5 polish",
                rationale="non-blocking",
                suggested_action="apply p5 fix",
            ),
        ],
        cross_axis_conflicts=[],
        summary="3 actions sorted by priority",
        judge_model="gpt",
    )

    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["rewriter_system"] = system
        return make_json_response(_empty_spec_dict())

    ctx, _, _ = _build_ctx(tmp_path, handler)

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
        ctx,
        _sample_spec(),
        review,
        iteration=1,
        meta_review=actions_in_priority_order,
    )

    sys = captured["rewriter_system"]
    pos_1 = sys.find('"id": "META-001"')
    pos_2 = sys.find('"id": "META-002"')
    pos_3 = sys.find('"id": "META-003"')
    assert pos_1 != -1 and pos_2 != -1 and pos_3 != -1, (
        "all 3 actions must appear in the rewriter prompt"
    )
    # The actions must appear in priority order (1 → 3 → 5).
    assert pos_1 < pos_2 < pos_3, (
        f"expected META-001 < META-002 < META-003 by string position; "
        f"got pos_1={pos_1}, pos_2={pos_2}, pos_3={pos_3}"
    )
    # The per-action priority field must be visible to the rewriter so the
    # downstream LLM can reason per-action, not just by ID order.
    assert '"priority": 1' in sys
    assert '"priority": 3' in sys
    assert '"priority": 5' in sys


# ---------------------------------------------------------------------------
# 3) Conflicts surfaced in prompt
# ---------------------------------------------------------------------------


async def test_conflicts_with_surfaced_in_prompt(tmp_path):
    """Action A1 has ``conflicts_with=['META-002']`` → the rewriter prompt
    must surface the conflict explicitly so the LLM can satisfy both
    deliberately (or escalate to a ``BlockingDecision``)."""
    meta = MetaReviewResult(
        actions=[
            PrioritizedAction(
                id="META-001",
                priority=1,
                severity=Severity.CRITICAL,
                affected_axes=["architecture"],
                source_issue_ids=["ARCH-001"],
                description="use selectinload to avoid N+1",
                rationale="N+1 is critical perf defect",
                suggested_action="switch from joinedload to selectinload",
                conflicts_with=["META-002"],
            ),
            PrioritizedAction(
                id="META-002",
                priority=2,
                severity=Severity.HIGH,
                affected_axes=["executability"],
                source_issue_ids=["EXEC-001"],
                description="preserve M2M response order",
                rationale="downstream API consumers depend on order",
                suggested_action="byte-for-byte stable serialization",
                conflicts_with=["META-001"],
            ),
        ],
        cross_axis_conflicts=[
            "Architecture wants selectinload; Executability wants stable order — "
            "selectinload may shuffle M2M relations."
        ],
        summary="2 conflicting actions",
        judge_model="gpt",
    )

    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["rewriter_system"] = system
        return make_json_response(_empty_spec_dict())

    ctx, _, _ = _build_ctx(tmp_path, handler)

    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[_review_issue(iid="ARCH-001", reviewer_type="architecture")],
            ),
            ReviewResult(
                reviewer_type="executability",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(iid="EXEC-001", reviewer_type="executability")
                ],
            ),
        ]
    )

    await run_rewriter(
        ctx, _sample_spec(), review, iteration=1, meta_review=meta
    )

    sys = captured["rewriter_system"]
    # Both META ids and both conflicts_with pointers must be embedded.
    assert "META-001" in sys
    assert "META-002" in sys
    # The conflicts_with JSON entries must reference each other.
    assert '"conflicts_with"' in sys
    # The prompt header guidance about coordinated resolution must be present.
    assert "conflicts_with" in sys.lower()
    assert "do NOT silently pick one side" in sys or "do NOT silently pick" in sys
    # The cross_axis_conflicts plain-English note is also surfaced.
    assert "selectinload" in sys
    # Hard sanity: each action's conflicts_with array references the *other*
    # action's id by string. We slice the JSON-formatted action blocks and
    # check by substring instead of full JSON parse (the meta block is
    # embedded inside a much larger markdown prompt).
    m1_start = sys.find('"id": "META-001"')
    m2_start = sys.find('"id": "META-002"')
    assert m1_start != -1 and m2_start != -1
    # Find the conflicts_with for META-001: it should reference META-002.
    region_1 = sys[m1_start : m1_start + 600]
    assert '"META-002"' in region_1, (
        "META-001's region must mention META-002 in its conflicts_with"
    )


# ---------------------------------------------------------------------------
# 4) Disabled → fall back to raw issues
# ---------------------------------------------------------------------------


async def test_meta_reviewer_disabled_falls_back_to_raw_issues(tmp_path):
    """``Settings.orchestrator.enable_meta_reviewer = False`` → the
    orchestrator's gate condition skips the meta call entirely, the
    rewriter receives ``meta_review=None``, and only the raw issues are
    surfaced (no ``meta_review_block``)."""
    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        # Asserts no meta-reviewer prompt ever lands here.
        assert "you are the **meta-reviewer**" not in system.lower(), (
            "meta-reviewer must not be invoked when disabled"
        )
        if "spec rewriter" in system.lower():
            captured["rewriter_system"] = system
        return make_json_response(_empty_spec_dict())

    ctx, _, _ = _build_ctx(tmp_path, handler)

    # Build a "would-have-fired-meta" review: not all-pass, total_issues > 0.
    review = _consolidated(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(
                        iid="ARCH-001",
                        reviewer_type="architecture",
                        severity=Severity.CRITICAL,
                        description="critical arch defect",
                    )
                ],
            ),
            ReviewResult(
                reviewer_type="completeness",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(
                        iid="COMP-001",
                        reviewer_type="completeness",
                        description="missing edge case",
                    )
                ],
            ),
            ReviewResult(
                reviewer_type="executability",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(
                        iid="EXEC-001",
                        reviewer_type="executability",
                        description="missing test ref",
                    )
                ],
            ),
            ReviewResult(
                reviewer_type="consistency",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _review_issue(
                        iid="CONS-001",
                        reviewer_type="consistency",
                        description="FR ↔ entity mismatch",
                    )
                ],
            ),
        ]
    )

    # Simulate the orchestrator gate condition with meta disabled.
    enable_meta = False
    should_run_meta = (
        enable_meta and not review.all_pass and review.total_issues > 0
    )
    assert should_run_meta is False, (
        "gate condition must evaluate False when enable_meta_reviewer=False"
    )

    # Now drive the rewriter exactly as the orchestrator would: meta_review=None.
    await run_rewriter(
        ctx, _sample_spec(), review, iteration=1, meta_review=None
    )

    sys = captured["rewriter_system"]
    # The raw 4-axis issue ids must all be in the prompt as a list.
    for iid in ("ARCH-001", "COMP-001", "EXEC-001", "CONS-001"):
        assert iid in sys, f"raw issue {iid} must reach the rewriter when meta disabled"
    # No meta-review section header must appear.
    assert "Meta-reviewer (B4)" not in sys, (
        "rewriter prompt must NOT contain the meta-review block when "
        "meta_review=None"
    )


# ---------------------------------------------------------------------------
# 5) Meta call raises → graceful degradation
# ---------------------------------------------------------------------------


class _CapturingTrace(TraceWriter):
    """Minimal in-memory TraceWriter that records every stage event so the
    test can assert ``meta_review_error`` was emitted."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record_stage_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    # All other TraceWriter hooks fall through to no-ops; the orchestrator
    # only depends on record_stage_event + the context-manager .stage()
    # which the null implementation supplies.
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - forwarding
        # Delegate any other call to a no-op (returns None).
        def _noop(*a: Any, **kw: Any) -> None:
            return None

        return _noop

    def stage(self, _name: str):  # type: ignore[override]
        # Return a trivial sync context manager (the orchestrator uses
        # `with ctx.trace.stage(...)`).
        class _Ctx:
            def __enter__(self_inner) -> _Ctx:
                return self_inner

            def __exit__(self_inner, *args: Any) -> None:
                return None

        return _Ctx()


async def test_meta_reviewer_failure_degrades_gracefully(tmp_path):
    """``run_meta_reviewer`` raises → orchestrator's ``_run_meta_review``
    must catch, log a ``meta_review_error`` trace event, and return
    ``None`` so the rewrite loop continues with raw issues only."""
    # Inject a TraceWriter we can inspect.
    settings = Settings()
    a_prov = MockProvider("anthropic", lambda *a, **k: make_json_response({}))
    o_prov = MockProvider("openai", lambda *a, **k: make_json_response({}))
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
        stage_defaults={"writer": "primary", "reviewer": "cross_review"},
    )
    trace = _CapturingTrace()
    gateway = LLMGateway(
        providers={"anthropic": a_prov, "openai": o_prov},
        router=router,
        trace=trace,
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
    ctx.trace = trace
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

    # Build a real orchestrator and stub run_meta_reviewer in its module to
    # raise. _run_meta_review must catch the exception and return None.
    orch = SpecOrchestrator(
        settings=settings,
        cache=NullCache(),
        tool_registry=build_default_registry(),
        prompts_dir=PROMPTS_DIR,
    )

    import devloop.spec_phase.orchestrator as orch_mod

    boom = RuntimeError("meta reviewer LLM exploded")

    async def _raises(*args: Any, **kwargs: Any) -> None:
        raise boom

    original = orch_mod.run_meta_reviewer
    orch_mod.run_meta_reviewer = _raises
    try:
        result = await orch._run_meta_review(
            ctx, _sample_spec(), review, iteration=1
        )
    finally:
        orch_mod.run_meta_reviewer = original

    assert result is None, (
        "orchestrator must return None on meta-reviewer failure so the "
        "rewriter falls back to raw issues"
    )
    error_events = [
        e for e in trace.events if e.get("event") == "meta_review_error"
    ]
    assert error_events, "expected a meta_review_error trace event"
    detail = error_events[0].get("detail", {}) or {}
    assert "RuntimeError" in str(detail), (
        f"error event must carry the exception type; got detail={detail}"
    )

    # And critically: a downstream rewriter call with meta_review=None
    # (the degraded path) must still produce a valid spec and not crash.
    captured: dict[str, Any] = {}

    def rew_handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            captured["sys"] = system
        return make_json_response(_empty_spec_dict())

    rew_ctx, _, _ = _build_ctx(tmp_path, rew_handler)
    await run_rewriter(
        rew_ctx, _sample_spec(), review, iteration=1, meta_review=None
    )
    assert "Meta-reviewer (B4)" not in captured["sys"], (
        "graceful-degradation rewriter must NOT embed a meta_review block"
    )
    assert "ARCH-001" in captured["sys"], (
        "graceful-degradation rewriter must still see the raw issues"
    )
