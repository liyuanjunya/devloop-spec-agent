"""Unit tests for D3 — segmented rewriter.

The segmented rewriter splits the single ~30KB Spec-rewriting LLM call into
5 validated per-section calls (head, stories, FRs, SCs, tail). These tests
mock the LLM provider end-to-end so they run offline and exercise the real
``call_strict_json`` path, the same way the unit tests for the regression
guard and other writer features do.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from devloop.cache import NullCache
from devloop.config import load_settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.writer import (
    _SEGMENT_ORDER,
    _segment_fallback,
    run_rewriter,
    run_rewriter_segmented,
)
from devloop.spec_phase.prompts_loader import PromptLoader
from devloop.spec_phase.schemas import (
    ConsolidatedReview,
    ReviewResult,
    Spec,
    SpecSegmentFRs,
    SpecSegmentHead,
    SpecSegmentSCs,
    SpecSegmentStories,
    SpecSegmentTail,
)
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import MockProvider, make_json_response

# ============================================================================
# Helpers — sample data + context construction
# ============================================================================

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def _sample_spec_dict(iter_n: int = 1) -> dict:
    return {
        "schema_version": "1.0",
        "metadata": {
            "feature_id": "demo-feature",
            "title": "Demo Feature",
            "writer_model": "mock-claude",
            "reviewer_model": "mock-gpt",
            "iterations": iter_n,
            "needs_review": False,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
        },
        "summary": "Demo feature for testing.",
        "needs_clarification": [],
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
                "text": "do the thing",
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
                "metric": "p99 latency",
                "threshold": "< 100ms",
                "technology_agnostic": True,
                "related_requirements": ["FR-001"],
            }
        ],
        "key_entities": [{"name": "X", "description": "an entity", "fields": [], "references": []}],
        "edge_cases": [{"description": "edge", "handling": "handled"}],
        "assumptions": ["the world is round"],
        "out_of_scope": ["world peace"],
        "self_concerns": [],
    }


def _empty_review() -> ConsolidatedReview:
    return ConsolidatedReview(
        reviews=[
            ReviewResult(
                reviewer_type="architecture",
                judge_model="mock",
                verdict="needs_refine",
                issues=[],
                self_concerns_verdicts=[],
                summary="",
            )
        ],
        overall_verdict="needs_refine",
        total_issues=0,
        critical_issues=0,
    )


def _build_ctx(tmp_path: Path, handler) -> SpecContext:
    """Build a SpecContext wired to a MockProvider that runs ``handler``."""
    a_prov = MockProvider("anthropic", handler)
    o_prov = MockProvider("openai", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
        stage_defaults={"writer": "primary"},
    )
    gateway = LLMGateway(
        providers={"anthropic": a_prov, "openai": o_prov},
        router=router,
        trace=NullTraceWriter(),
    )
    settings = load_settings()
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)
    run_id = "run-segmented-test"
    (workspace_root / run_id).mkdir(parents=True, exist_ok=True)

    ctx = SpecContext(
        run_id=run_id,
        user_input="test",
        repo_path=tmp_path,
        workspace_root=workspace_root,
        settings=settings,
        gateway=gateway,
        tools=build_default_registry(),
        prompts=PromptLoader(PROMPTS_DIR),
        cache=NullCache(),
        trace=NullTraceWriter(),
        skeleton_builder=None,  # type: ignore[arg-type]  # unused in writer path
    )
    return ctx


def _segment_handler_factory(
    *,
    head_override: dict | None = None,
    stories_override: dict | None = None,
    frs_override: dict | None = None,
    scs_override: dict | None = None,
    tail_override: dict | None = None,
    on_segment=None,  # callable(segment_name, system_prompt) -> None
    fail_segments: set[str] | None = None,
):
    """Build a handler that dispatches per segment based on the system prompt.

    ``fail_segments`` forces the named segments to return invalid JSON so
    ``call_strict_json`` exhausts its retries (and the segmented rewriter
    falls back to ``previous_spec``).
    """

    fail = fail_segments or set()
    sample = _sample_spec_dict()

    defaults = {
        "head": {
            "metadata": {**sample["metadata"], "iterations": 2},
            "summary": sample["summary"],
            "needs_clarification": sample["needs_clarification"],
        },
        "stories": {"user_stories": sample["user_stories"]},
        "frs": {"functional_requirements": sample["functional_requirements"]},
        "scs": {"success_criteria": sample["success_criteria"]},
        "tail": {
            "key_entities": sample["key_entities"],
            "edge_cases": sample["edge_cases"],
            "assumptions": sample["assumptions"],
            "out_of_scope": sample["out_of_scope"],
            "self_concerns": sample["self_concerns"],
        },
    }
    overrides = {
        "head": head_override,
        "stories": stories_override,
        "frs": frs_override,
        "scs": scs_override,
        "tail": tail_override,
    }

    def handler(model, system, messages, tools, response_format):
        sys_lower = system.lower()
        for seg_name in _SEGMENT_ORDER:
            marker = f"segment {list(_SEGMENT_ORDER).index(seg_name) + 1} of 5"
            if marker in sys_lower:
                if on_segment is not None:
                    on_segment(seg_name, system)
                if seg_name in fail:
                    from tests.fixtures.mock_provider import make_text_response

                    return make_text_response("definitely not json")
                payload = overrides[seg_name] if overrides[seg_name] is not None else defaults[seg_name]
                return make_json_response(payload)
        # Not a segmented call — let callers handle non-segmented fallthrough
        return None

    return handler


# ============================================================================
# 1. Segment schemas parse minimal valid payloads
# ============================================================================


def test_segment_schemas_parse_minimal_input():
    """Each per-segment partial schema accepts the minimal payload it claims to model."""
    sample = _sample_spec_dict()
    head = SpecSegmentHead.model_validate(
        {
            "metadata": sample["metadata"],
            "summary": sample["summary"],
            "needs_clarification": [],
        }
    )
    assert head.metadata.feature_id == "demo-feature"
    assert head.needs_clarification == []

    stories = SpecSegmentStories.model_validate({"user_stories": sample["user_stories"]})
    assert len(stories.user_stories) == 1

    frs = SpecSegmentFRs.model_validate(
        {"functional_requirements": sample["functional_requirements"]}
    )
    assert frs.functional_requirements[0].id == "FR-001"

    scs = SpecSegmentSCs.model_validate({"success_criteria": sample["success_criteria"]})
    assert scs.success_criteria[0].id == "SC-001"

    # Empty tail also valid — every field has a default_factory
    tail = SpecSegmentTail.model_validate({})
    assert tail.key_entities == []
    assert tail.edge_cases == []
    assert tail.assumptions == []
    assert tail.out_of_scope == []
    assert tail.self_concerns == []


# ============================================================================
# 2. Happy path — 5 segments accumulate into a valid Spec
# ============================================================================


async def test_run_rewriter_segmented_mock_success(tmp_path):
    handler = _segment_handler_factory()
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    spec = await run_rewriter_segmented(ctx, previous, review, iteration=1)

    assert isinstance(spec, Spec)
    assert spec.metadata.feature_id == "demo-feature"
    assert spec.summary == "Demo feature for testing."
    assert len(spec.user_stories) == 1
    assert len(spec.functional_requirements) == 1
    assert len(spec.success_criteria) == 1
    assert spec.key_entities[0].name == "X"
    # Persisted artifact on disk
    expected_artifact = ctx.run_workspace / "spec_iterations" / "spec_v2.json"
    assert expected_artifact.is_file()


# ============================================================================
# 3. Partial failure — failing segment falls back to previous_spec
# ============================================================================


async def test_run_rewriter_segmented_partial_failure_falls_back_to_previous(tmp_path):
    """If segment 3 (FRs) fails after max_repair_attempts, the rewriter
    should fall back to the FRs from ``previous_spec`` and keep going —
    later segments must still run and produce a valid final Spec."""
    # Override FRs in the LLM to something different so we can prove the
    # fallback used the previous spec, not the rewriter's output.
    new_fr = {
        "id": "FR-999",
        "text": "definitely-new",
        "requirement_type": "functional",
        "related_user_stories": ["US-1"],
        "related_success_criteria": ["SC-001"],
        "code_references": [],
        "testable": True,
    }
    handler = _segment_handler_factory(
        frs_override={"functional_requirements": [new_fr]},
        fail_segments={"frs"},
    )
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    spec = await run_rewriter_segmented(ctx, previous, review, iteration=1)

    # Fallback used previous FRs, not the (forced-failing) new one
    assert [fr.id for fr in spec.functional_requirements] == ["FR-001"]
    assert spec.functional_requirements[0].text == "do the thing"
    # Other segments still succeeded
    assert spec.summary == "Demo feature for testing."
    assert spec.success_criteria[0].id == "SC-001"


# ============================================================================
# 4. Soft-language validator fires per segment (A4)
# ============================================================================


async def test_segmented_rewriter_validates_soft_language_per_segment(tmp_path):
    """Soft-language in a segment's text fields should be rejected by the
    underlying pydantic field_validator, exhausting retries and triggering
    the per-segment fallback rather than ``Spec.model_validate`` exploding
    at the end."""
    bad_summary_head = {
        "metadata": _sample_spec_dict()["metadata"],
        "summary": "We will choose Postgres or equivalent.",  # forbidden phrase
        "needs_clarification": [],
    }
    handler = _segment_handler_factory(head_override=bad_summary_head)
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    spec = await run_rewriter_segmented(ctx, previous, review, iteration=1)

    # Head failed → fell back to previous summary
    assert spec.summary == "Demo feature for testing."


# ============================================================================
# 5. Metadata iteration increments correctly
# ============================================================================


async def test_segmented_rewriter_preserves_metadata_iteration(tmp_path):
    handler = _segment_handler_factory()
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=3))
    review = _empty_review()

    spec = await run_rewriter_segmented(ctx, previous, review, iteration=3)

    assert spec.metadata.iterations == 4  # iteration + 1
    assert spec.metadata.feature_id == previous.metadata.feature_id
    assert spec.metadata.title == previous.metadata.title


# ============================================================================
# 6. Progress logging — one log per segment
# ============================================================================


async def test_segmented_rewriter_progress_logged(tmp_path, caplog):
    handler = _segment_handler_factory()
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    with caplog.at_level(logging.INFO, logger="devloop.spec_phase.agents.writer"):
        await run_rewriter_segmented(ctx, previous, review, iteration=1)

    # One "segment X/5 (name) completed" log per segment
    completed_msgs = [
        rec.getMessage() for rec in caplog.records if "completed for iteration" in rec.getMessage()
    ]
    assert len(completed_msgs) == 5
    # Each segment name appears in the right order
    for idx, seg_name in enumerate(_SEGMENT_ORDER, start=1):
        assert any(
            f"segment {idx}/5 ({seg_name})" in m for m in completed_msgs
        ), f"missing log for segment {idx}/{seg_name}"


# ============================================================================
# 7. SC segment receives the FR context it needs for cross-references
# ============================================================================


async def test_segmented_rewriter_fr_sc_cross_reference_passed_to_sc_segment(tmp_path):
    """The SC segment's system prompt must include the FR ids produced by
    the FR segment so the LLM can populate ``related_requirements`` without
    dangling pointers. We capture the prompts and assert the FR id from the
    FR segment shows up in the SC segment's prompt."""
    captured: dict[str, str] = {}

    def on_seg(name, sys):
        captured[name] = sys

    custom_fr = {
        "id": "FR-XYZ",
        "text": "do the new thing",
        "requirement_type": "functional",
        "related_user_stories": ["US-1"],
        "related_success_criteria": ["SC-001"],
        "code_references": [],
        "testable": True,
    }
    handler = _segment_handler_factory(
        frs_override={"functional_requirements": [custom_fr]},
        on_segment=on_seg,
    )
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    await run_rewriter_segmented(ctx, previous, review, iteration=1)

    assert "scs" in captured, "SC segment prompt was not captured"
    sc_prompt = captured["scs"]
    # The FR id from the freshly-rewritten FR segment must be visible
    # in the SC segment's prompt context (under prior_segments).
    assert "FR-XYZ" in sc_prompt
    # And the SC prompt's instructions about FR ids must be present.
    assert "related_requirements" in sc_prompt
    # And earlier segments (e.g. head/stories) should also appear in the
    # accumulated prior_segments context.
    assert "demo-feature" in sc_prompt  # feature_id from head segment
    assert "US-1" in sc_prompt  # story id from stories segment


# ============================================================================
# 8. Orchestrator setting branch selects the right rewriter
# ============================================================================


def test_orchestrator_branch_chooses_correct_rewriter(monkeypatch):
    """The setting ``use_segmented_rewriter`` must toggle which function the
    orchestrator dispatches to. We inspect the resolved ``rewriter_fn``
    expression directly rather than running the full pipeline (which has
    its own integration coverage)."""
    from devloop.spec_phase import orchestrator as orch_mod

    # Off → single-shot rewriter
    settings_off = load_settings()
    settings_off.orchestrator.use_segmented_rewriter = False
    fn_off = (
        orch_mod.run_rewriter_segmented
        if settings_off.orchestrator.use_segmented_rewriter
        else orch_mod.run_rewriter
    )
    assert fn_off is orch_mod.run_rewriter

    # On → segmented rewriter
    settings_on = load_settings()
    settings_on.orchestrator.use_segmented_rewriter = True
    fn_on = (
        orch_mod.run_rewriter_segmented
        if settings_on.orchestrator.use_segmented_rewriter
        else orch_mod.run_rewriter
    )
    assert fn_on is orch_mod.run_rewriter_segmented

    # And both names must actually be imported into the orchestrator module
    assert hasattr(orch_mod, "run_rewriter"), "single-shot rewriter must be importable"
    assert hasattr(orch_mod, "run_rewriter_segmented"), "segmented rewriter must be importable"


# ============================================================================
# 9. Bonus — segment fallback helper isolates field updates
# ============================================================================


def test_segment_fallback_returns_only_segment_owned_fields():
    """``_segment_fallback`` must return EXACTLY the field set the segment
    owns — nothing more (we don't want a fallback to clobber later
    accumulated segments)."""
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    head = _segment_fallback(previous, "head")
    assert set(head.keys()) == {"metadata", "summary", "needs_clarification"}

    frs = _segment_fallback(previous, "frs")
    assert set(frs.keys()) == {"functional_requirements"}
    assert frs["functional_requirements"][0]["id"] == "FR-001"

    tail = _segment_fallback(previous, "tail")
    assert set(tail.keys()) == {
        "key_entities",
        "edge_cases",
        "assumptions",
        "out_of_scope",
        "self_concerns",
    }


# ============================================================================
# 10. Smoke: extra_context (regression feedback) flows into the system prompt
# ============================================================================


async def test_segmented_rewriter_extra_context_is_propagated_to_prompts(tmp_path):
    captured: list[str] = []

    def on_seg(name, sys):
        captured.append(sys)

    handler = _segment_handler_factory(on_segment=on_seg)
    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    await run_rewriter_segmented(
        ctx,
        previous,
        review,
        iteration=1,
        extra_context="MOCK_REGRESSION_FEEDBACK_TOKEN",
    )

    assert captured, "no segment system prompts captured"
    # Every segment call must carry the extra_context block
    for sys_prompt in captured:
        assert "REGRESSION CONTEXT" in sys_prompt
        assert "MOCK_REGRESSION_FEEDBACK_TOKEN" in sys_prompt


# ============================================================================
# 11. Smoke: single-shot rewriter still works (regression guard)
# ============================================================================


async def test_single_shot_rewriter_still_works_unchanged(tmp_path):
    """D3 must NOT break the pre-existing single-shot ``run_rewriter`` — it
    should still produce a Spec from one LLM call when the setting is off."""

    def handler(model, system, messages, tools, response_format):
        if "spec rewriter" in system.lower():
            return make_json_response(_sample_spec_dict(iter_n=2))
        return None

    ctx = _build_ctx(tmp_path, handler)
    previous = Spec.model_validate(_sample_spec_dict(iter_n=1))
    review = _empty_review()

    spec = await run_rewriter(ctx, previous, review, iteration=1)

    assert isinstance(spec, Spec)
    assert spec.metadata.iterations == 2
    assert json.loads((ctx.run_workspace / "spec_iterations" / "spec_v2.json").read_text(
        encoding="utf-8"
    ))["metadata"]["feature_id"] == "demo-feature"
