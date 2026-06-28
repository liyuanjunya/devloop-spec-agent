"""End-to-end integration test for the F3-A3 escalation validator guard.

Walks the orchestrator's review-rewrite loop with a writer that produces a
*clean* spec (passes pydantic) but whose ``self_concerns`` slot was tampered
with after construction to hold an under-escalated concern — simulating a
non-pydantic load path or a legacy spec deserialized via
``Spec.model_construct``.

The orchestrator-level backup validator (``find_underescalated_concerns``)
must catch this and inject one HIGH-severity ``executability``
``ReviewIssue`` (id prefix ``ESC-``) into the consolidated review for the
next rewrite iteration so the rewriter is told to move the concern into
``Spec.needs_clarification``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import devloop.spec_phase.orchestrator as orch_mod
from devloop.cache import CacheBackend
from devloop.config import load_settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.orchestrator import SpecOrchestrator
from devloop.spec_phase.validators.escalation import EscalationProblem
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import (
    MockProvider,
    make_json_response,
    make_text_response,
    make_tool_call_response,
)

# ---------------------------------------------------------------------------
# Mocked LLM stages — borrowed from the citation guard / review loop tests.
# These keep the orchestrator pipeline cheap so we can focus on the
# escalation injection behaviour.
# ---------------------------------------------------------------------------


def _intent_handler():
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
                        {"hypothesis_id": "H1", "verdict": "confirmed", "evidence": "ok"}
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


def _explorer_handler():
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


def _clean_spec(iter_n: int = 1) -> dict:
    """A spec that passes pydantic validation cleanly."""
    return {
        "schema_version": "1.0",
        "metadata": {
            "feature_id": "esc-e2e",
            "title": "Escalation e2e",
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
                        "line_ranges": [[1, 21]],
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
    """Writer/rewriter that always returns a clean spec (no concerns)."""
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            return make_json_response(_clean_spec(iter_n=1 + state["rewrites"]))
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(_clean_spec(iter_n=1))
        return None

    return handler, state


def _reviewer_pass_handler():
    """A reviewer that always says PASS — only the escalation backup can
    force the loop to inject issues."""

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
    max_total_iterations: int = 3,
) -> SpecOrchestrator:
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = False
    settings.orchestrator.enable_meta_reviewer = False
    settings.orchestrator.max_total_iterations = max_total_iterations
    settings.orchestrator.escalation_check_enabled = True

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
        original_build = orch_mod.build_gateway
        orch_mod.build_gateway = lambda settings, trace=None: gateway
        try:
            return await orig_run(user_input, repo_path)
        finally:
            orch_mod.build_gateway = original_build

    orchestrator.run = run_with_mock  # type: ignore[assignment]
    return orchestrator


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


async def test_underescalated_concern_injects_high_executability_issue(
    tmp_path, fixture_repo, monkeypatch
):
    """Writer produces a clean spec; the backup validator finds an
    under-escalated concern (simulated via monkey-patch) and the orchestrator
    must inject a HIGH-severity ``executability`` ReviewIssue with id prefix
    ``ESC-`` into the persisted consolidated review."""
    writer_handler, _state = _writer_handler()
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )

    # Simulate a spec loaded via a non-validated path: the pydantic guard
    # would normally block this at schema construction time, but the
    # orchestrator-level backup validator must still catch it. We patch
    # the symbol imported into the orchestrator module so the backup
    # validator returns a synthetic problem on every iteration.
    synthetic_problem = EscalationProblem(
        concern_location="FR-001",
        matched_text="3 implementation options",
        suggested_fix=(
            "Move 'FR-001' concern to needs_clarification (BlockingDecision) "
            "with explicit recommended_default + if_rejected."
        ),
    )

    call_log: list[int] = []

    def fake_find(spec):
        call_log.append(len(spec.self_concerns))
        return [synthetic_problem]

    monkeypatch.setattr(orch_mod, "find_underescalated_concerns", fake_find)

    orchestrator = _build_orchestrator(tmp_path, combined, max_total_iterations=2)
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.spec is not None
    assert result.workspace is not None

    # The backup validator should have been invoked at least once during
    # the review-rewrite loop.
    assert call_log, "expected find_underescalated_concerns to be called at least once"

    # Inspect persisted review artifacts: at least one iteration must contain
    # a HIGH-severity executability ReviewIssue authored by the escalation
    # validator with id prefix ``ESC-``.
    review_files = sorted(
        (result.workspace / "spec_iterations").glob("review_v*_consolidated.json")
    )
    assert review_files, "expected at least one consolidated review artifact"

    found_escalation_issue = False
    seen_evidence = ""
    seen_suggested = ""
    seen_location = ""
    for rf in review_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                if (
                    issue.get("reviewer_type") == "executability"
                    and issue.get("severity") == "high"
                    and issue.get("id", "").startswith("ESC-")
                ):
                    found_escalation_issue = True
                    seen_evidence = issue.get("evidence", "")
                    seen_suggested = issue.get("suggested_action", "")
                    seen_location = issue.get("location", "")
                    break
            if found_escalation_issue:
                break
        if found_escalation_issue:
            break

    assert found_escalation_issue, (
        "expected a HIGH-severity executability ReviewIssue authored by the "
        f"escalation validator in {review_files}"
    )
    # Evidence should reference the matched phrase + the concern's location.
    assert "3 implementation options" in seen_evidence
    assert "FR-001" in seen_evidence
    assert seen_location == "FR-001"
    # Suggested action should tell the rewriter where to escalate to.
    assert "needs_clarification" in seen_suggested
    assert "BlockingDecision" in seen_suggested


async def test_escalation_check_disabled_skips_validator(
    tmp_path, fixture_repo, monkeypatch
):
    """When ``settings.orchestrator.escalation_check_enabled`` is False,
    the orchestrator must skip the backup validator entirely so no ESC-
    issues land in the persisted review."""
    writer_handler, _state = _writer_handler()
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )

    # If the validator IS called, it would return a problem — but the
    # disabled flag should short-circuit before this is ever invoked.
    sentinel_problem = EscalationProblem(
        concern_location="FR-001",
        matched_text="3 implementation options",
        suggested_fix="should not happen",
    )

    def fake_find(spec):  # pragma: no cover - must not be called
        pytest.fail("find_underescalated_concerns must not be called when disabled")
        return [sentinel_problem]

    monkeypatch.setattr(orch_mod, "find_underescalated_concerns", fake_find)

    orchestrator = _build_orchestrator(tmp_path, combined, max_total_iterations=2)
    # Flip the toggle off after the orchestrator is built so the disabled
    # path is exercised end-to-end.
    orchestrator.settings.orchestrator.escalation_check_enabled = False

    result = await orchestrator.run("Add disabled run feature", fixture_repo)
    assert result.ok

    # No ESC- issues should appear anywhere in the persisted reviews.
    review_files = sorted(
        (result.workspace / "spec_iterations").glob("review_v*_consolidated.json")
    )
    for rf in review_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                assert not issue.get("id", "").startswith("ESC-"), (
                    f"unexpected ESC- issue in {rf}: {issue}"
                )
