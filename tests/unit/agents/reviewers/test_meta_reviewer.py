"""Unit tests for the meta-reviewer (B4): schema, prompt, and LLM mock parsing."""

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
from tests.fixtures.mock_provider import MockProvider, make_json_response, make_text_response

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    *,
    aid: str = "META-001",
    priority: int = 1,
    severity: Severity = Severity.CRITICAL,
    affected_axes: list[str] | None = None,
    source_issue_ids: list[str] | None = None,
    conflicts_with: list[str] | None = None,
) -> PrioritizedAction:
    return PrioritizedAction(
        id=aid,
        priority=priority,
        severity=severity,
        affected_axes=affected_axes or ["architecture"],  # type: ignore[arg-type]
        source_issue_ids=source_issue_ids or ["ARCH-001"],
        description="Move rate-limit before validation in FR-007.",
        rationale="Both reviewers flagged ordering; security-critical.",
        suggested_action="Edit FR-007 to require rate-limit middleware to run before request validation.",
        conflicts_with=conflicts_with or [],
    )


def _make_review_issue(
    *,
    iid: str,
    reviewer_type: str = "architecture",
    severity: Severity = Severity.HIGH,
    location: str = "FR-007",
    description: str = "Rate-limit ordering",
) -> ReviewIssue:
    return ReviewIssue(
        id=iid,
        reviewer_type=reviewer_type,  # type: ignore[arg-type]
        severity=severity,
        location=location,
        description=description,
        evidence="case-6 spec line 142 lists rate-limit AFTER validation",
        suggested_action="Move rate-limit before validation.",
    )


def _consolidated_review(reviews: list[ReviewResult]) -> ConsolidatedReview:
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
        summary="demo",
    )


def _build_ctx(
    tmp_path: Path,
    handler,
    *,
    intent: ConfirmedIntent | None = None,
) -> tuple[SpecContext, MockProvider]:
    """Build a SpecContext bound to a MockProvider for unit tests.

    Uses the real ``PromptLoader`` so we exercise the prompt template too.
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
    return ctx, o_prov


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_meta_review_result_schema_roundtrip():
    """MetaReviewResult + PrioritizedAction must serialize and deserialize cleanly."""
    result = MetaReviewResult(
        actions=[
            _make_action(aid="META-001", priority=1),
            _make_action(
                aid="META-002",
                priority=2,
                severity=Severity.HIGH,
                affected_axes=["architecture", "executability"],
                source_issue_ids=["ARCH-002", "EXEC-001"],
                conflicts_with=["META-001"],
            ),
        ],
        cross_axis_conflicts=[
            "Architecture says use selectinload; Executability says preserve response order — selectinload may change M2M order.",
        ],
        summary="2 actions, 1 cross-axis conflict",
        judge_model="gpt-5.5",
    )

    assert result.schema_version == SCHEMA_VERSION
    assert len(result.actions) == 2
    assert result.actions[1].conflicts_with == ["META-001"]
    assert result.actions[1].affected_axes == ["architecture", "executability"]

    dumped = result.model_dump(mode="json")
    assert dumped["actions"][1]["conflicts_with"] == ["META-001"]
    assert dumped["schema_version"] == SCHEMA_VERSION

    round_tripped = MetaReviewResult.model_validate(dumped)
    assert round_tripped == result


def test_meta_review_result_defaults_empty_collections():
    """Empty MetaReviewResult must still be constructible with sensible defaults."""
    result = MetaReviewResult()
    assert result.actions == []
    assert result.cross_axis_conflicts == []
    assert result.summary == ""
    assert result.judge_model == ""
    assert result.schema_version == SCHEMA_VERSION


def test_prioritized_action_priority_bounds():
    """priority must be in the closed range [1, 5]."""
    for valid in (1, 2, 3, 4, 5):
        a = _make_action(priority=valid)
        assert a.priority == valid

    for invalid in (0, -1, 6, 100):
        with pytest.raises(ValidationError):
            _make_action(priority=invalid)


def test_prioritized_action_affected_axes_must_be_valid_reviewer_types():
    """affected_axes is typed as list[ReviewerType] — invalid values should fail."""
    with pytest.raises(ValidationError):
        PrioritizedAction(
            id="META-001",
            priority=1,
            severity=Severity.HIGH,
            affected_axes=["not_a_real_axis"],  # type: ignore[list-item]
            source_issue_ids=["X-1"],
            description="d",
            rationale="r",
            suggested_action="s",
        )


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


async def test_meta_reviewer_with_mock_gateway(tmp_path):
    """Mock the LLM to return a known MetaReviewResult JSON; verify parsing + judge_model."""
    canned = {
        "schema_version": SCHEMA_VERSION,
        "actions": [
            {
                "id": "META-001",
                "priority": 1,
                "severity": "critical",
                "affected_axes": ["architecture", "completeness"],
                "source_issue_ids": ["ARCH-001", "COMP-001"],
                "description": "FR-007 rate-limit ordering is wrong",
                "rationale": "Two axes flagged it; security-critical.",
                "suggested_action": "Rewrite FR-007 to place rate-limit before validation.",
                "conflicts_with": [],
            }
        ],
        "cross_axis_conflicts": ["Arch vs exec on selectinload vs response shape"],
        "summary": "1 action",
        "judge_model": "",  # left blank, agent should fill it
    }

    def handler(model, system, messages, tools, response_format):
        return make_json_response(canned)

    review = _consolidated_review(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _make_review_issue(iid="ARCH-001", severity=Severity.CRITICAL)
                ],
            ),
            ReviewResult(
                reviewer_type="completeness",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _make_review_issue(
                        iid="COMP-001",
                        reviewer_type="completeness",
                        severity=Severity.HIGH,
                    )
                ],
            ),
        ]
    )

    ctx, _prov = _build_ctx(tmp_path, handler)
    result = await run_meta_reviewer(ctx, _sample_spec(), review)

    assert isinstance(result, MetaReviewResult)
    assert len(result.actions) == 1
    assert result.actions[0].id == "META-001"
    assert result.actions[0].affected_axes == ["architecture", "completeness"]
    assert result.actions[0].source_issue_ids == ["ARCH-001", "COMP-001"]
    # When the LLM leaves judge_model blank, the agent should populate it
    # with the configured cross-review model.
    assert result.judge_model == ctx.settings.llm.cross_review_model


async def test_meta_reviewer_handles_zero_issues(tmp_path):
    """All-clean review: the meta-reviewer must return an empty action list cleanly."""
    canned = {
        "schema_version": SCHEMA_VERSION,
        "actions": [],
        "cross_axis_conflicts": [],
        "summary": "no issues",
        "judge_model": "judge",
    }

    seen_prompts: list[str] = []

    def handler(model, system, messages, tools, response_format):
        seen_prompts.append(system)
        return make_json_response(canned)

    review = _consolidated_review(
        [
            ReviewResult(
                reviewer_type=axis,  # type: ignore[arg-type]
                judge_model="gpt",
                verdict="pass",
            )
            for axis in ("architecture", "completeness", "executability", "consistency")
        ]
    )

    ctx, _prov = _build_ctx(tmp_path, handler)
    result = await run_meta_reviewer(ctx, _sample_spec(), review)

    assert result.actions == []
    assert result.cross_axis_conflicts == []
    # Even for the trivial case, the prompt must still be rendered with the
    # consolidated review payload embedded.
    assert "Meta-Reviewer" in seen_prompts[0]


async def test_meta_reviewer_handles_single_axis(tmp_path):
    """Only one reviewer has issues — the agent still emits a coherent action list."""
    canned = {
        "schema_version": SCHEMA_VERSION,
        "actions": [
            {
                "id": "META-001",
                "priority": 2,
                "severity": "high",
                "affected_axes": ["executability"],
                "source_issue_ids": ["EXEC-001"],
                "description": "FR-001 missing test reference",
                "rationale": "Single executability finding; should be fixed.",
                "suggested_action": "Add an independent_test for FR-001.",
                "conflicts_with": [],
            }
        ],
        "cross_axis_conflicts": [],
        "summary": "1 exec action",
        "judge_model": "gpt-5.5",
    }

    def handler(model, system, messages, tools, response_format):
        return make_json_response(canned)

    review = _consolidated_review(
        [
            ReviewResult(
                reviewer_type="architecture", judge_model="gpt", verdict="pass"
            ),
            ReviewResult(
                reviewer_type="completeness", judge_model="gpt", verdict="pass"
            ),
            ReviewResult(
                reviewer_type="executability",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _make_review_issue(
                        iid="EXEC-001",
                        reviewer_type="executability",
                        severity=Severity.HIGH,
                        location="FR-001",
                        description="missing test ref",
                    )
                ],
            ),
            ReviewResult(
                reviewer_type="consistency", judge_model="gpt", verdict="pass"
            ),
        ]
    )

    ctx, _prov = _build_ctx(tmp_path, handler)
    result = await run_meta_reviewer(ctx, _sample_spec(), review)

    assert len(result.actions) == 1
    assert result.actions[0].affected_axes == ["executability"]
    assert result.actions[0].source_issue_ids == ["EXEC-001"]


async def test_meta_reviewer_dedupes_similar_issues_via_prompt(tmp_path):
    """Verify the rendered prompt embeds BOTH source issues so the LLM can dedupe."""
    captured: dict[str, Any] = {}

    def handler(model, system, messages, tools, response_format):
        captured["system"] = system
        # Return a deduped action that explicitly lists both source issue ids.
        return make_json_response(
            {
                "schema_version": SCHEMA_VERSION,
                "actions": [
                    {
                        "id": "META-001",
                        "priority": 1,
                        "severity": "critical",
                        "affected_axes": ["architecture", "completeness"],
                        "source_issue_ids": ["ARCH-007", "COMP-007"],
                        "description": "FR-007 missing rate-limit",
                        "rationale": "two axes converge on the same defect",
                        "suggested_action": "Add rate-limit middleware before validation in FR-007.",
                        "conflicts_with": [],
                    }
                ],
                "cross_axis_conflicts": [],
                "summary": "deduped",
                "judge_model": "gpt-5.5",
            }
        )

    review = _consolidated_review(
        [
            ReviewResult(
                reviewer_type="architecture",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _make_review_issue(
                        iid="ARCH-007",
                        reviewer_type="architecture",
                        severity=Severity.CRITICAL,
                        location="FR-007",
                        description="rate-limit ordering breaks security model",
                    )
                ],
            ),
            ReviewResult(
                reviewer_type="completeness",
                judge_model="gpt",
                verdict="fail",
                issues=[
                    _make_review_issue(
                        iid="COMP-007",
                        reviewer_type="completeness",
                        severity=Severity.HIGH,
                        location="FR-007",
                        description="rate-limit threshold not specified",
                    )
                ],
            ),
        ]
    )

    ctx, _prov = _build_ctx(tmp_path, handler)
    result = await run_meta_reviewer(ctx, _sample_spec(), review)

    system_prompt = captured["system"]
    # Both raw issues must appear in the prompt so the LLM has the evidence
    # it needs to merge them.
    assert "ARCH-007" in system_prompt
    assert "COMP-007" in system_prompt
    # Intent must be embedded so the meta-reviewer can prioritize against it.
    assert "demo intent" in system_prompt
    # The deduped action must reference both sources.
    assert result.actions[0].source_issue_ids == ["ARCH-007", "COMP-007"]
    assert set(result.actions[0].affected_axes) == {
        "architecture",
        "completeness",
    }


async def test_meta_reviewer_strict_json_repairs_invalid_first_response(tmp_path):
    """If the LLM returns non-JSON first, the strict-JSON wrapper must repair."""
    state = {"attempt": 0}

    def handler(model, system, messages, tools, response_format):
        state["attempt"] += 1
        if state["attempt"] == 1:
            return make_text_response("oops not json at all")
        return make_json_response(
            {
                "schema_version": SCHEMA_VERSION,
                "actions": [],
                "cross_axis_conflicts": [],
                "summary": "ok",
                "judge_model": "gpt",
            }
        )

    review = _consolidated_review(
        [
            ReviewResult(
                reviewer_type="architecture", judge_model="gpt", verdict="pass"
            ),
        ]
    )

    ctx, _prov = _build_ctx(tmp_path, handler)
    result = await run_meta_reviewer(ctx, _sample_spec(), review)
    assert isinstance(result, MetaReviewResult)
    assert state["attempt"] == 2


def test_meta_review_prompt_template_exists_and_renders():
    """The on-disk prompt template must exist and render with the expected vars."""
    loader = PromptLoader(PROMPTS_DIR)
    text = loader.load(
        "reviewer/meta",
        spec=json.dumps({"summary": "demo"}),
        consolidated_review=json.dumps({"reviews": []}),
        intent_primary="primary intent",
    )
    assert "Meta-Reviewer" in text
    # Every placeholder used by the agent must be substituted (no leftover {{x}}).
    for placeholder in ("{{spec}}", "{{consolidated_review}}", "{{intent_primary}}"):
        assert placeholder not in text
    assert "primary intent" in text
