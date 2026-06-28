"""Integration test for the A5 citation verifier guard in the orchestrator.

Walks the orchestrator's review-rewrite loop with a writer that keeps producing
specs whose ``code_references`` cite an *existing* symbol but at the wrong line
range. The mechanical verifier should catch the mismatch every iteration,
inject HIGH ``executability`` :class:`ReviewIssue` instances into the
consolidated review, and after the configured budget mark the spec
``needs_review``.
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


def _intent_handler():
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


def _explorer_handler():
    """Single mark_as_relevant tool call per perspective, then COMPLETE."""
    state = {"step": {}}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "**your perspective**" not in sl:
            return None
        perspective = next(
            (p for p in ["data", "api", "ui", "test", "history"] if f"perspective**: {p}" in sl),
            None,
        )
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


def _consolidator_handler():
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


def _approach_handler():
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


# The bad citation: ``User`` is on line 12 of app/models/user.py, but the
# spec claims it lives at lines 6-8 (which are blank line + two SQLAlchemy
# imports — none of which contain the substring "User"). The verifier must
# catch this every iteration and force rewrites until the budget runs out.
_BAD_LINE_RANGE = [[6, 8]]


def _bad_citation_spec(iter_n: int) -> dict:
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
                        "line_ranges": _BAD_LINE_RANGE,
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
                "related_user_stories": ["US-1"],
            }
        ],
        "key_entities": [{"name": "X", "description": "x", "fields": [], "references": []}],
        "edge_cases": [],
        "assumptions": [],
        "out_of_scope": [],
        "self_concerns": [],
    }


def _writer_handler():
    """Writer/rewriter that ALWAYS returns a spec with the same bad citation."""
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            return make_json_response(_bad_citation_spec(iter_n=1 + state["rewrites"]))
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(_bad_citation_spec(iter_n=1))
        return None

    return handler, state


def _reviewer_pass_handler():
    """A reviewer that always says PASS. We rely on the citation verifier
    to force the rewrites; if the reviewer never returns 'fail' the loop
    can only loop because of the synthetic injection.
    """

    def handler(model, system, messages, tools, response_format):
        if "reviewer" not in system.lower():
            return None
        return make_text_response("All good.\nVERDICT: pass")

    return handler


def _combined(*handlers):
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
    citation_max_attempts: int,
    max_total_iterations: int = 20,
) -> SpecOrchestrator:
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = False
    settings.orchestrator.max_total_iterations = max_total_iterations
    settings.orchestrator.citation_verify_max_attempts = citation_max_attempts

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
    return orchestrator


async def test_citation_guard_injects_high_executability_issue_and_marks_needs_review(
    tmp_path, fixture_repo
):
    """Bad-citation spec → HIGH executability issue injected → needs_review after budget."""
    writer_handler, _ws = _writer_handler()
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    citation_max_attempts = 2
    orchestrator = _build_orchestrator(
        tmp_path,
        combined,
        citation_max_attempts=citation_max_attempts,
        max_total_iterations=10,
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.spec is not None
    assert result.workspace is not None

    # After max_attempts citation problems persist → needs_review must be set.
    assert result.spec.metadata.needs_review is True

    # Inspect persisted review artifacts: at least one iteration must include
    # a HIGH-severity executability ReviewIssue authored by the citation
    # verifier, with the wrong line_range surfaced in its evidence.
    review_files = sorted((result.workspace / "spec_iterations").glob("review_v*_consolidated.json"))
    assert review_files, "expected at least one consolidated review artifact"

    import json

    found_citation_issue = False
    citation_evidence_seen = ""
    for rf in review_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                if (
                    issue.get("reviewer_type") == "executability"
                    and issue.get("severity") == "high"
                    and issue.get("id", "").startswith("CITE-")
                ):
                    found_citation_issue = True
                    citation_evidence_seen = issue.get("evidence", "")
                    break
            if found_citation_issue:
                break
        if found_citation_issue:
            break

    assert found_citation_issue, (
        "expected a HIGH-severity executability ReviewIssue authored by the "
        f"citation verifier in {review_files}"
    )
    # The evidence should mention the bad line range and/or the symbol that
    # didn't actually appear in it, giving the rewriter something actionable.
    assert "User" in citation_evidence_seen or "6, 8" in citation_evidence_seen
