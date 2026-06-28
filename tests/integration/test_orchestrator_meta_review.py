"""Integration test for B4: orchestrator wires meta-reviewer between
review and rewrite.

Verifies that with ``Settings.orchestrator.enable_meta_reviewer = True``
the rewriter's system prompt contains the meta-review block (i.e. the
rewriter sees the unified action list, not just raw issues).
"""

from __future__ import annotations

import json
from pathlib import Path

from devloop.cache import CacheBackend
from devloop.config import load_settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.orchestrator import SpecOrchestrator
from devloop.spec_phase.schemas import SCHEMA_VERSION
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import (
    MockProvider,
    make_json_response,
    make_text_response,
    make_tool_call_response,
)

# ---------------------------------------------------------------------------
# Spec fixture — picked carefully so the A5 citation verifier sees a valid
# line range (sample_repo's app/models/user.py has 21 lines).
# ---------------------------------------------------------------------------


def _sample_spec(iter_n: int = 1) -> dict:
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
                "code_references": [
                    {
                        "path": "app/models/user.py",
                        "symbols": ["User"],
                        "line_ranges": [[1, 20]],
                        "snippet": "",
                    }
                ],
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
# Mock stage handlers
# ---------------------------------------------------------------------------


def _mock_intent_handler():
    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "intent analyzer" in sl:
            return make_json_response(
                {
                    "hypotheses": [
                        {
                            "id": "H1",
                            "summary": "primary intent",
                            "indicators": ["x"],
                            "counter_indicators": [],
                        }
                    ]
                }
            )
        if "intent skeptic" in sl:
            return make_json_response({"challenges": [], "new_hypotheses": []})
        if "intent verifier" in sl:
            return make_json_response(
                {
                    "verdicts": [
                        {
                            "hypothesis_id": "H1",
                            "verdict": "confirmed",
                            "evidence": "ok",
                        }
                    ],
                    "confirmed_intent": {
                        "primary": "primary intent",
                        "intent_type": "add_feature",
                        "scope": ["backend"],
                        "excluded": [],
                        "pending_clarification": [],
                        "confidence": 0.9,
                        "rounds_used": 1,
                    },
                    "request_another_round": False,
                }
            )
        return None

    return handler


def _mock_explorer_handler():
    state = {"step": {}}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "**your perspective**" not in sl:
            return None
        perspective = None
        for p in ["data", "api", "ui", "test", "history"]:
            if f"perspective**: {p}" in sl:
                perspective = p
                break
        if perspective is None:
            return None
        step = state["step"].get(perspective, 0)
        state["step"][perspective] = step + 1
        if step == 0:
            return make_tool_call_response(
                name="mark_as_relevant",
                arguments={
                    "path": "app/models/user.py",
                    "importance": "critical",
                    "reason": "user model",
                },
            )
        return make_text_response("EXPLORATION COMPLETE.")

    return handler


def _mock_consolidator_handler():
    def handler(model, system, messages, tools, response_format):
        if "consolidator" not in system.lower():
            return None
        return make_json_response(
            {
                "consolidated_artifacts": [
                    {
                        "path": "app/models/user.py",
                        "symbols": ["User"],
                        "line_ranges": [[1, 20]],
                        "importance": "critical",
                        "reason": "core entity",
                        "snippet": "class User",
                    }
                ],
                "conflicts": [],
                "consolidated_conventions": ["pydantic v2 for validation"],
                "summary": "FastAPI + SQLAlchemy",
            }
        )

    return handler


def _mock_approach_handler():
    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "plan generator" in sl or "plan type for this call" in sl:
            pt = "balanced"
            for x in ("conservative", "balanced", "aggressive"):
                if f"plan type for this call**: {x}" in sl:
                    pt = x
                    break
            return make_json_response(
                {
                    "plan_type": pt,
                    "summary": f"{pt} plan",
                    "key_changes": ["add x"],
                    "reuses_existing": ["app/models/user.py"],
                    "new_components": [],
                    "estimated_effort": "S",
                    "risks": [],
                }
            )
        if "plan evaluator" in sl:
            return make_json_response(
                {
                    "evaluations": [
                        {
                            "plan_type": pt,
                            "implementation_effort": "S",
                            "architectural_fit": "high",
                            "long_term_maintainability": "high",
                            "user_story_coverage": "full",
                            "overall_recommendation": "prefer",
                            "rationale": "good",
                        }
                        for pt in ("conservative", "balanced", "aggressive")
                    ],
                    "pairwise_winner": "balanced",
                    "judge_model": "mock-gpt",
                }
            )
        if "plan selector" in sl:
            return make_json_response(
                {
                    "primary_plan_type": "balanced",
                    "integrated_strengths_from_others": [],
                    "rationale": "picked balanced",
                }
            )
        return None

    return handler


# ---------------------------------------------------------------------------
# Test plumbing
# ---------------------------------------------------------------------------


def _combined_handler(*handlers):
    def handler(*args, **kwargs):
        for h in handlers:
            r = h(*args, **kwargs)
            if r is not None:
                return r
        return make_text_response("(unhandled)")

    return handler


def _build_orchestrator(
    tmp_path: Path,
    handler,
    *,
    enable_meta_reviewer: bool,
    max_total_iterations: int = 5,
):
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = False  # single reviewer keeps the test focused
    settings.orchestrator.enable_meta_reviewer = enable_meta_reviewer
    settings.orchestrator.max_total_iterations = max_total_iterations

    a_prov = MockProvider("anthropic", handler)
    o_prov = MockProvider("openai", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
        stage_defaults={
            "intent_analyzer": "primary",
            "intent_skeptic": "cross_review",
            "intent_verifier": "primary",
            "explorer": "primary",
            "consolidator": "primary",
            "plan_generator": "primary",
            "plan_evaluator": "cross_review",
            "plan_selector": "primary",
            "writer": "primary",
            "reviewer": "cross_review",
        },
    )
    gateway = LLMGateway(
        providers={"anthropic": a_prov, "openai": o_prov},
        router=router,
        trace=NullTraceWriter(),
    )
    prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
    cache = CacheBackend(settings.paths.cache_dir / "test.db")
    orchestrator = SpecOrchestrator(
        settings=settings,
        cache=cache,
        tool_registry=build_default_registry(),
        prompts_dir=prompts_dir,
    )

    orig_run = orchestrator.run

    async def run_with_mock(user_input, repo_path):
        import devloop.spec_phase.orchestrator as orch_mod

        original_build = orch_mod.build_gateway
        orch_mod.build_gateway = lambda settings, trace=None: gateway
        try:
            return await orig_run(user_input, repo_path)
        finally:
            orch_mod.build_gateway = original_build

    orchestrator.run = run_with_mock  # type: ignore[assignment]
    return orchestrator, gateway, a_prov, o_prov


# ---------------------------------------------------------------------------
# The actual test
# ---------------------------------------------------------------------------


async def test_meta_reviewer_runs_and_rewriter_receives_action_list(
    tmp_path, fixture_repo
):
    """End-to-end: when ``enable_meta_reviewer=True`` and the reviewer flags
    a real issue, the orchestrator must

    1. Invoke the meta-reviewer agent (visible by the unique ``Meta-Reviewer``
       prompt header arriving at the provider).
    2. Pass the produced ``MetaReviewResult`` to the rewriter, which must
       include the meta-review block in its system prompt.
    3. Persist a ``meta_review_v{n}.json`` artifact.
    """

    meta_review_payload = {
        "schema_version": SCHEMA_VERSION,
        "actions": [
            {
                "id": "META-001",
                "priority": 1,
                "severity": "critical",
                "affected_axes": ["architecture"],
                "source_issue_ids": ["ARCH-001"],
                "description": "Rate-limit ordering wrong in FR-001",
                "rationale": "Single critical security defect.",
                "suggested_action": "Move rate-limit before validation.",
                "conflicts_with": [],
            }
        ],
        "cross_axis_conflicts": [],
        "summary": "1 critical action",
        "judge_model": "gpt",
    }

    # Per-stage state tracking
    state = {
        "writes": 0,
        "rewrites": 0,
        "reviewer_calls": 0,
        "meta_reviewer_calls": 0,
        "rewriter_systems": [],
        "meta_systems": [],
    }

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()

        # === 1. Rewriter (CHECK FIRST — its prompt now embeds the
        # meta-review block, which contains the substring "meta-reviewer")
        if "spec rewriter" in sl:
            state["rewrites"] += 1
            state["rewriter_systems"].append(system)
            return make_json_response(_sample_spec(iter_n=1 + state["rewrites"]))

        # === 2. Meta-reviewer (must come AFTER the rewriter check above)
        if "you are the **meta-reviewer**" in sl:
            state["meta_reviewer_calls"] += 1
            state["meta_systems"].append(system)
            return make_json_response(meta_review_payload)

        # === 3. Initial writer
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(_sample_spec(iter_n=1))

        # === 4. Axis reviewer (one critical issue on iter 1, then pass)
        if "reviewer" in sl:
            state["reviewer_calls"] += 1
            # iteration 1: flag once, then verdict fail
            # iteration 2: verdict pass
            if state["reviewer_calls"] == 1:
                return make_tool_call_response(
                    name="flag_issue",
                    arguments={
                        "severity": "critical",
                        "location": "FR-001",
                        "description": "Rate-limit ordering breaks security",
                        "evidence": "spec puts rate-limit after validation",
                    },
                )
            if state["reviewer_calls"] == 2:
                return make_text_response(
                    "Critical issue noted.\nVERDICT: fail"
                )
            return make_text_response("All good.\nVERDICT: pass")

        return None

    combined = _combined_handler(
        _mock_intent_handler(),
        _mock_explorer_handler(),
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        handler,
    )

    orchestrator, _gateway, _a_prov, _o_prov = _build_orchestrator(
        tmp_path,
        combined,
        enable_meta_reviewer=True,
        max_total_iterations=5,
    )

    result = await orchestrator.run("Add demo feature", fixture_repo)

    assert result.ok
    assert result.workspace is not None

    # 1. Meta-reviewer must have been called at least once (iter 1 had issues).
    assert state["meta_reviewer_calls"] >= 1, (
        "meta-reviewer should run when enable_meta_reviewer=True and the "
        "review surfaced issues"
    )

    # The meta-reviewer prompt must carry the consolidated review payload.
    meta_sys = state["meta_systems"][0]
    assert "Meta-Reviewer" in meta_sys
    assert "ARCH-001" in meta_sys or "Rate-limit" in meta_sys

    # 2. The rewriter must have received the meta-review block.
    assert state["rewrites"] >= 1, "at least one rewrite expected"
    rewriter_sys = state["rewriter_systems"][0]
    assert "Meta-reviewer (B4)" in rewriter_sys, (
        "rewriter system prompt must contain the meta-review section header"
    )
    assert "META-001" in rewriter_sys, (
        "rewriter system prompt must embed the prioritized action ids"
    )
    assert "Move rate-limit before validation" in rewriter_sys, (
        "rewriter system prompt must embed the suggested action text"
    )

    # 3. The meta-review artifact must be persisted.
    meta_artifact = (
        result.workspace / "spec_iterations" / "meta_review_v1.json"
    )
    assert meta_artifact.is_file(), (
        f"expected meta-review artifact at {meta_artifact}"
    )
    data = json.loads(meta_artifact.read_text(encoding="utf-8"))
    assert data["actions"][0]["id"] == "META-001"


async def test_meta_reviewer_disabled_skips_meta_call(tmp_path, fixture_repo):
    """When ``enable_meta_reviewer=False``, the meta-reviewer must NOT be invoked,
    and the rewriter's system prompt must NOT contain the meta-review block."""

    state = {
        "rewrites": 0,
        "reviewer_calls": 0,
        "meta_reviewer_calls": 0,
        "rewriter_systems": [],
    }

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl:
            state["rewrites"] += 1
            state["rewriter_systems"].append(system)
            return make_json_response(_sample_spec(iter_n=1 + state["rewrites"]))
        if "you are the **meta-reviewer**" in sl:
            state["meta_reviewer_calls"] += 1
            return make_json_response(
                {
                    "schema_version": SCHEMA_VERSION,
                    "actions": [],
                    "cross_axis_conflicts": [],
                    "summary": "",
                    "judge_model": "gpt",
                }
            )
        if "spec writer" in sl:
            return make_json_response(_sample_spec(iter_n=1))
        if "reviewer" in sl:
            state["reviewer_calls"] += 1
            if state["reviewer_calls"] == 1:
                return make_tool_call_response(
                    name="flag_issue",
                    arguments={
                        "severity": "critical",
                        "location": "FR-001",
                        "description": "x",
                        "evidence": "y",
                    },
                )
            if state["reviewer_calls"] == 2:
                return make_text_response("x\nVERDICT: fail")
            return make_text_response("ok\nVERDICT: pass")
        return None

    combined = _combined_handler(
        _mock_intent_handler(),
        _mock_explorer_handler(),
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        handler,
    )

    orchestrator, *_ = _build_orchestrator(
        tmp_path,
        combined,
        enable_meta_reviewer=False,
        max_total_iterations=5,
    )
    result = await orchestrator.run("Add demo feature", fixture_repo)

    assert result.ok
    assert state["meta_reviewer_calls"] == 0, (
        "meta-reviewer must not run when disabled"
    )
    # The rewriter ran but its system prompt has no meta-review block.
    if state["rewrites"]:
        assert "Meta-reviewer (B4)" not in state["rewriter_systems"][0]
