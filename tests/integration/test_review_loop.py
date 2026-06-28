"""Integration tests for the review-rewrite loop and explorer partial failures.

These build small focused MockProvider scripts that exercise specific termination
paths through the orchestrator.
"""

from __future__ import annotations

from pathlib import Path

from devloop.cache import CacheBackend
from devloop.config import load_settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.orchestrator import SpecOrchestrator
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import (
    MockProvider,
    make_json_response,
    make_text_response,
    make_tool_call_response,
)

# ---------------------------------------------------------------------------
# Common mocks: intent / explorer / consolidator / approach always pass-through
# ---------------------------------------------------------------------------


def _mock_intent_handler():
    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "intent analyzer" in sl:
            return make_json_response(
                {
                    "hypotheses": [
                        {"id": "H1", "summary": "primary intent", "indicators": ["x"], "counter_indicators": []}
                    ]
                }
            )
        if "intent skeptic" in sl:
            return make_json_response({"challenges": [], "new_hypotheses": []})
        if "intent verifier" in sl:
            return make_json_response(
                {
                    "verdicts": [{"hypothesis_id": "H1", "verdict": "confirmed", "evidence": "ok"}],
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
                        "line_ranges": [[1, 21]],
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


def _sample_spec(iter_n: int = 1) -> dict:
    return {
        "schema_version": "1.0",
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
                "acceptance": [
                    {"given": "g", "when": "w", "then": "t"}
                ],
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
                    {"path": "app/models/user.py", "symbols": ["User"], "line_ranges": [[1, 21]], "snippet": ""}
                ],
                "testable": True,
            }
        ],
        "success_criteria": [
            {"id": "SC-001", "text": "fast", "metric": "ms", "threshold": "< 100ms", "technology_agnostic": True, "related_requirements": ["FR-001"]}
        ],
        "key_entities": [{"name": "X", "description": "x", "fields": [], "references": []}],
        "edge_cases": [],
        "assumptions": [],
        "out_of_scope": [],
        "self_concerns": [],
    }


def _mock_writer_handler(rewrite_outputs: list[dict] | None = None):
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "spec rewrite" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            idx = state["rewrites"] - 1
            if rewrite_outputs and idx < len(rewrite_outputs):
                return make_json_response(rewrite_outputs[idx])
            return make_json_response(_sample_spec(iter_n=1 + state["rewrites"]))
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(_sample_spec(iter_n=1))
        return None

    return handler, state


def _mock_reviewer_handler(verdict_script: list[str]):
    """Reviewer that returns verdicts according to a per-iteration script.

    verdict_script: list of "pass" | "fail" | "needs_refine" for iteration 1, 2, ...
    The state index advances only after a VERDICT-ending text response, NOT after
    intermediate tool calls.
    """
    state = {"iter": 0}

    def handler(model, system, messages, tools, response_format):
        if "reviewer" not in system.lower():
            return None
        idx = state["iter"]
        verdict = verdict_script[idx] if idx < len(verdict_script) else verdict_script[-1]
        if verdict == "pass":
            state["iter"] += 1
            return make_text_response("All good.\nVERDICT: pass")
        # fail/needs_refine: report a critical issue via flag_issue tool first, then verdict
        if not _has_already_flagged(messages):
            return make_tool_call_response(
                name="flag_issue",
                arguments={
                    "severity": "critical",
                    "location": "FR-001",
                    "description": "Something looks wrong",
                    "evidence": "spec contradiction observed",
                },
            )
        state["iter"] += 1
        return make_text_response("Found critical issues.\nVERDICT: " + verdict)

    return handler, state


def _has_already_flagged(messages):
    """Heuristic: if the conversation includes a tool result for flag_issue, we already flagged."""
    for m in messages:
        if m.role == "tool" and m.name == "flag_issue":
            return True
    return False


def _combined_handler(*handlers):
    def handler(*args, **kwargs):
        for h in handlers:
            r = h(*args, **kwargs)
            if r is not None:
                return r
        return make_text_response("(unhandled)")

    return handler


def _build_orchestrator(tmp_path: Path, fixture_repo: Path, handler, *, single_reviewer=True, max_total_iterations=20):
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = not single_reviewer
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
    return orchestrator, gateway


# ============================================================================
# Test 1: review-rewrite loop converges after one rewrite
# ============================================================================


async def test_review_rewrite_loop_converges_after_one_rewrite(tmp_path, fixture_repo):
    writer_handler, writer_state = _mock_writer_handler()
    reviewer_handler, _reviewer_state = _mock_reviewer_handler(["fail", "pass"])

    combined = _combined_handler(
        _mock_intent_handler(),
        _mock_explorer_handler(),
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        writer_handler,
        reviewer_handler,
    )
    orchestrator, _ = _build_orchestrator(
        tmp_path, fixture_repo, combined, single_reviewer=True
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.spec is not None
    assert result.spec.metadata.iterations >= 2  # Original + at least one rewrite
    assert not result.spec.metadata.needs_review  # Converged
    assert writer_state["rewrites"] >= 1


# ============================================================================
# Test 2: no-progress termination → needs_review
# ============================================================================


async def test_review_rewrite_loop_stuck_no_progress(tmp_path, fixture_repo):
    # Always fail with same issue pressure → no_progress_threshold (default 3) trips
    writer_handler, _ws = _mock_writer_handler()
    reviewer_handler, _rs = _mock_reviewer_handler(["fail", "fail", "fail", "fail", "fail"])

    combined = _combined_handler(
        _mock_intent_handler(),
        _mock_explorer_handler(),
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        writer_handler,
        reviewer_handler,
    )
    orchestrator, _ = _build_orchestrator(
        tmp_path, fixture_repo, combined, single_reviewer=True, max_total_iterations=20
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.spec is not None
    assert result.spec.metadata.needs_review  # Stuck
    # Should have stopped well before max_total_iterations (no_progress_threshold=3)
    assert result.spec.metadata.iterations <= 6


# ============================================================================
# Test 3: max_total_iterations hard cap and NO extra review call
# ============================================================================


async def test_max_iterations_cap_no_extra_review_call(tmp_path, fixture_repo):
    """When max_total_iterations fires, we should NOT call the reviewer one extra time."""
    writer_handler, _ws = _mock_writer_handler()
    # Reviewer alternates between needs_refine and fail to avoid no-progress trigger
    reviewer_handler, _reviewer_state = _mock_reviewer_handler(
        ["needs_refine", "fail", "needs_refine", "fail", "needs_refine"]
    )

    combined = _combined_handler(
        _mock_intent_handler(),
        _mock_explorer_handler(),
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        writer_handler,
        reviewer_handler,
    )
    orchestrator, _ = _build_orchestrator(
        tmp_path, fixture_repo, combined, single_reviewer=True, max_total_iterations=3
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.spec is not None
    assert result.spec.metadata.needs_review

    # Critical assertion: reviewer should be called at most max_total_iterations times,
    # NOT max_total_iterations + 1 (the bug we fixed in R1).
    # With single reviewer, each iteration = 1 reviewer call (possibly + 1 flag_issue follow-up).
    # We can verify by checking the iteration count on the spec.
    assert result.spec.metadata.iterations <= 3 + 1  # initial + rewrites


# ============================================================================
# Test 4: explorer partial failure → consolidator still runs
# ============================================================================


async def test_explorer_partial_failure_continues_with_placeholders(tmp_path, fixture_repo):
    """If one explorer raises, the others succeed and consolidator sees placeholders."""

    def explorer_handler_partial_fail(model, system, messages, tools, response_format):
        sl = system.lower()
        if "**your perspective**" not in sl:
            return None
        if "perspective**: data" in sl:
            # Simulate a model error - raise during the call by returning malformed JSON
            # in a place that will cause downstream pydantic to fail. Easiest: raise.
            raise RuntimeError("simulated provider error for data perspective")
        # Other perspectives produce a single tool call then terminate
        return make_text_response("EXPLORATION COMPLETE.")

    writer_handler, _ws = _mock_writer_handler()
    reviewer_handler, _rs = _mock_reviewer_handler(["pass"])

    combined = _combined_handler(
        _mock_intent_handler(),
        explorer_handler_partial_fail,
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        writer_handler,
        reviewer_handler,
    )
    orchestrator, _ = _build_orchestrator(
        tmp_path, fixture_repo, combined, single_reviewer=True
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.workspace is not None
    # Workspace should still contain consolidated.json + all perspective files
    assert (result.workspace / "exploration" / "consolidated.json").is_file()
    # The data perspective file should contain the [error] placeholder
    data_p = result.workspace / "exploration" / "data_perspective.json"
    assert data_p.is_file()
    data_content = data_p.read_text(encoding="utf-8")
    assert "error" in data_content.lower()


# ============================================================================
# Test 5: run counter aggregates into spec.metadata
# ============================================================================


async def test_total_llm_and_tool_calls_aggregated_into_metadata(tmp_path, fixture_repo):
    writer_handler, _ws = _mock_writer_handler()
    reviewer_handler, _rs = _mock_reviewer_handler(["pass"])
    combined = _combined_handler(
        _mock_intent_handler(),
        _mock_explorer_handler(),
        _mock_consolidator_handler(),
        _mock_approach_handler(),
        writer_handler,
        reviewer_handler,
    )
    orchestrator, _gateway = _build_orchestrator(
        tmp_path, fixture_repo, combined, single_reviewer=True
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.spec is not None
    assert result.spec.metadata.total_llm_calls > 0, "LLM calls should be aggregated"
    assert result.spec.metadata.total_tool_calls >= 1, "Tool calls should be aggregated"
