"""Integration test: full orchestrator pipeline against the sample_repo fixture,
using a deterministic mock LLM that mimics what real Claude/GPT would do."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def _make_intent_handler():
    """Simulate the intent stage: analyzer / skeptic / verifier."""

    def handler(model, system, messages, tools, response_format):
        sys_lower = system.lower()
        if "intent analyzer" in sys_lower:
            return make_json_response(
                {
                    "hypotheses": [
                        {
                            "id": "H1",
                            "summary": "Add user comments on products",
                            "indicators": [
                                "User mentions 'comment'",
                                "Repo has Product and User models",
                            ],
                            "counter_indicators": [],
                        },
                        {
                            "id": "H2",
                            "summary": "Add product reviews/ratings",
                            "indicators": ["'comment' could mean rating"],
                            "counter_indicators": ["No rating field in repo"],
                        },
                    ]
                }
            )
        if "intent skeptic" in sys_lower:
            return make_json_response(
                {
                    "challenges": [
                        {
                            "target_hypothesis_id": "H1",
                            "question": "Could this also mean comments between users?",
                            "rationale": "'user comments' is ambiguous",
                        }
                    ],
                    "new_hypotheses": [],
                }
            )
        if "intent verifier" in sys_lower:
            return make_json_response(
                {
                    "verdicts": [
                        {"hypothesis_id": "H1", "verdict": "confirmed", "evidence": "Repo has Product and User"},
                        {"hypothesis_id": "H2", "verdict": "rejected", "evidence": "No rating field"},
                    ],
                    "confirmed_intent": {
                        "primary": "Allow logged-in users to comment on products",
                        "intent_type": "add_feature",
                        "scope": ["backend", "data_model", "api"],
                        "excluded": [
                            {
                                "hypothesis_id": "H2",
                                "summary": "Add product reviews/ratings",
                                "exclusion_reason": "No rating field exists; comment is distinct",
                            }
                        ],
                        "pending_clarification": ["Is moderation needed?"],
                        "confidence": 0.85,
                        "rounds_used": 1,
                    },
                    "request_another_round": False,
                }
            )
        return None  # signal not handled

    return handler


def _make_explorer_handler():
    """Simulate explorer ReAct loops with 1-2 tool calls and then a final assistant message."""

    state = {"step": {}}  # per-call-context tracker

    def handler(model, system, messages, tools, response_format):
        sys_lower = system.lower()
        # Distinct marker — explorer/_base.md has this exact phrase
        if "**your perspective**" not in sys_lower:
            return None
        # Identify which perspective
        perspective = None
        for p in ["data", "api", "ui", "test", "history"]:
            # Match "your perspective**: data" form
            if f"perspective**: {p}" in sys_lower:
                perspective = p
                break
        if perspective is None:
            return None

        step = state["step"].get(perspective, 0)
        state["step"][perspective] = step + 1

        if step == 0:
            return make_tool_call_response(
                name="list_directory", arguments={"path": ".", "max_depth": 1}
            )
        if step == 1:
            target_path = {
                "data": "app/models/product.py",
                "api": "app/api/products.py",
                "ui": "README.md",
                "test": "tests/test_products.py",
                "history": "app/models/user.py",
            }.get(perspective, "README.md")
            return make_tool_call_response(
                name="mark_as_relevant",
                arguments={
                    "path": target_path,
                    "importance": "critical",
                    "reason": f"Key file from {perspective} perspective",
                },
            )
        if step == 2:
            return make_tool_call_response(
                name="take_note",
                arguments={
                    "note": f"Project uses pydantic v2 and FastAPI ({perspective} pov)"
                },
            )
        return make_text_response(
            f"EXPLORATION COMPLETE from {perspective} perspective.\nOpen question: Should comments support edits?"
        )

    return handler


def _make_consolidator_handler():
    def handler(model, system, messages, tools, response_format):
        if "consolidator" in system.lower():
            return make_json_response(
                {
                    "consolidated_artifacts": [
                        {
                            "path": "app/models/product.py",
                            "symbols": ["Product"],
                            "line_ranges": [[1, 22]],
                            "importance": "critical",
                            "reason": "Comment entity will reference Product",
                            "snippet": "class Product: id, name, ...",
                        },
                        {
                            "path": "app/models/user.py",
                            "symbols": ["User"],
                            "line_ranges": [[1, 21]],
                            "importance": "critical",
                            "reason": "Comment author references User",
                            "snippet": "class User: id, username, email",
                        },
                    ],
                    "conflicts": [],
                    "consolidated_conventions": [
                        "Project uses SQLAlchemy 2.0 declarative_base",
                        "Project uses pydantic v2 for input validation",
                        "IDs are UUID strings",
                    ],
                    "summary": "The project is a FastAPI+SQLAlchemy app with User and Product models. Comment feature should follow the same patterns.",
                }
            )
        return None

    return handler


def _make_approach_handler():
    def handler(model, system, messages, tools, response_format):
        sys_lower = system.lower()
        if "plan generator" in sys_lower or "plan type for this call" in sys_lower:
            # Identify requested plan type from the rendered marker
            plan_type = "balanced"
            for pt in ("conservative", "balanced", "aggressive"):
                if f"plan type for this call**: {pt}" in sys_lower:
                    plan_type = pt
                    break
            return make_json_response(
                {
                    "plan_type": plan_type,
                    "summary": f"{plan_type} plan: add Comment model + simple API",
                    "key_changes": [
                        "Add Comment model",
                        "Add /products/{id}/comments endpoints",
                    ],
                    "reuses_existing": ["app/models/base.py", "app/api/products.py"],
                    "new_components": ["Comment ORM model"]
                    if plan_type != "conservative"
                    else [],
                    "estimated_effort": "S — minimal new code",
                    "risks": ["may need pagination later"],
                }
            )
        if "plan evaluator" in sys_lower:
            return make_json_response(
                {
                    "evaluations": [
                        {
                            "plan_type": "conservative",
                            "implementation_effort": "S",
                            "architectural_fit": "high",
                            "long_term_maintainability": "medium",
                            "user_story_coverage": "partial",
                            "overall_recommendation": "acceptable",
                            "rationale": "smallest diff",
                        },
                        {
                            "plan_type": "balanced",
                            "implementation_effort": "M",
                            "architectural_fit": "high",
                            "long_term_maintainability": "high",
                            "user_story_coverage": "full",
                            "overall_recommendation": "prefer",
                            "rationale": "best fit",
                        },
                        {
                            "plan_type": "aggressive",
                            "implementation_effort": "L",
                            "architectural_fit": "medium",
                            "long_term_maintainability": "high",
                            "user_story_coverage": "full",
                            "overall_recommendation": "discouraged",
                            "rationale": "overkill",
                        },
                    ],
                    "pairwise_winner": "balanced",
                    "judge_model": "mock-gpt",
                }
            )
        if "plan selector" in sys_lower:
            return make_json_response(
                {
                    "primary_plan_type": "balanced",
                    "integrated_strengths_from_others": [
                        "Adopt conservative reuse of base.py",
                    ],
                    "rationale": "Balanced fits best per evaluator",
                }
            )
        return None

    return handler


def _make_writer_handler():
    state = {"rewrite_count": 0}

    def handler(model, system, messages, tools, response_format):
        sys_lower = system.lower()
        if "spec rewriter" in sys_lower or "rewrite" in sys_lower:
            state["rewrite_count"] += 1
            # Return improved spec
            return make_json_response(_sample_spec(rewrite=state["rewrite_count"]))
        if "spec writer" in sys_lower:
            return make_json_response(_sample_spec(rewrite=0))
        return None

    return handler


def _sample_spec(rewrite: int = 0) -> dict:
    """A valid Spec payload, slightly tweaked across iterations."""
    return {
        "schema_version": "1.0",
        "metadata": {
            "feature_id": "product-comments",
            "title": "Product Comments",
            "writer_model": "mock-claude",
            "reviewer_model": "mock-gpt",
            "iterations": 1 + rewrite,
            "needs_review": False,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
        },
        "summary": "Allow logged-in users to comment on products.",
        "user_stories": [
            {
                "id": "US-1",
                "priority": "P1",
                "title": "Submit a comment",
                "description": "A logged-in user submits a comment on a product page.",
                "why_this_priority": "Core feature",
                "independent_test": "Submit a comment via API and verify it appears in GET /products/{id}/comments",
                "acceptance": [
                    {
                        "given": "I am logged in",
                        "when": "I submit a comment on a product",
                        "then": "the comment is associated with my user and visible in the comments list",
                    }
                ],
            }
        ],
        "functional_requirements": [
            {
                "id": "FR-001",
                "text": "Comments are associated with a logged-in User.",
                "requirement_type": "functional",
                "related_user_stories": ["US-1"],
                "related_success_criteria": ["SC-001"],
                "code_references": [
                    {"path": "app/models/user.py", "symbols": ["User"], "line_ranges": [[1, 21]], "snippet": ""}
                ],
                "testable": True,
            },
            {
                "id": "FR-002",
                "text": "Comments are associated with a Product.",
                "requirement_type": "functional",
                "related_user_stories": ["US-1"],
                "related_success_criteria": ["SC-001"],
                "code_references": [
                    {"path": "app/models/product.py", "symbols": ["Product"], "line_ranges": [[1, 22]], "snippet": ""}
                ],
                "testable": True,
            },
            {
                "id": "FR-003",
                "text": "System scales to 10000 concurrent comment writes.",
                "requirement_type": "non_functional",
                "related_user_stories": [],
                "code_references": [],
                "testable": True,
            },
        ],
        "success_criteria": [
            {
                "id": "SC-001",
                "text": "99% of comment submissions complete in under 1s.",
                "metric": "p99 submit latency",
                "threshold": "< 1s",
                "technology_agnostic": True,
                "related_requirements": ["FR-001", "FR-002"],
            }
        ],
        "key_entities": [
            {
                "name": "Comment",
                "description": "A user-authored comment on a product.",
                "fields": ["id (UUID)", "product_id", "user_id", "content", "created_at"],
                "references": ["Product", "User"],
            }
        ],
        "edge_cases": [
            {"description": "Comment longer than 500 chars", "handling": "reject with 422"}
        ],
        "assumptions": ["Comments visible immediately, no moderation queue"],
        "out_of_scope": ["Threaded replies", "Comment editing"],
        "self_concerns": [
            {
                "location": "FR-003",
                "concern": "10000 concurrent writes target is unverified",
                "evidence_gap": "no load test exists",
                "suggested_resolution": "agree threshold with infra team",
            }
        ],
    }


def _make_reviewer_handler():
    """Return a 'pass' verdict on first iteration so the loop terminates fast."""

    def handler(model, system, messages, tools, response_format):
        if "architecture reviewer" in system.lower() or "reviewer" in system.lower():
            # No tool calls — just give verdict
            return make_text_response(
                "I reviewed the spec and found no critical issues.\n"
                "- FR-003: uncertain — not enough info to verify\n"
                "VERDICT: pass"
            )
        return None

    return handler


def _make_combined_handler():
    """Combine all stage handlers into one. Falls through in order."""

    handlers = [
        _make_intent_handler(),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        _make_writer_handler(),
        _make_reviewer_handler(),
    ]

    def handler(model, system, messages, tools, response_format):
        for h in handlers:
            r = h(model, system, messages, tools, response_format)
            if r is not None:
                return r
        # Fallback empty text
        return make_text_response("(unhandled mock call)")

    return handler


@pytest.fixture
def mock_orchestrator(tmp_path, fixture_repo):
    """Build an orchestrator with mock LLM providers."""
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = False  # single reviewer is enough for mock test

    # We need to monkey-patch build_gateway path: the orchestrator's run() calls
    # build_gateway(settings, trace=...) internally. We'll instead directly inject
    # a gateway by subclassing.
    handler = _make_combined_handler()
    mock_anthropic = MockProvider("anthropic", handler)
    mock_openai = MockProvider("openai", handler)

    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude-opus-4-7",
        cross_review_provider="openai",
        cross_review_model="gpt-5.5",
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

    trace = NullTraceWriter()
    gateway = LLMGateway(
        providers={"anthropic": mock_anthropic, "openai": mock_openai},
        router=router,
        trace=trace,
    )

    prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
    cache = CacheBackend(settings.paths.cache_dir / "test.db")
    tool_registry = build_default_registry()

    orchestrator = SpecOrchestrator(
        settings=settings,
        cache=cache,
        tool_registry=tool_registry,
        prompts_dir=prompts_dir,
    )

    # Override the orchestrator's gateway-building by replacing run's gateway hook
    # Simplest: monkey-patch build_gateway via attribute on instance
    orchestrator._test_gateway = gateway  # type: ignore[attr-defined]

    # Patch run to use our gateway
    orig_run = orchestrator.run

    async def run_with_mock_gateway(user_input, repo_path):
        # Mirror orig_run but inject the mock gateway by patching the module
        import devloop.spec_phase.orchestrator as orch_mod

        original_build = orch_mod.build_gateway
        orch_mod.build_gateway = lambda settings, trace=None: gateway
        try:
            return await orig_run(user_input, repo_path)
        finally:
            orch_mod.build_gateway = original_build

    orchestrator.run = run_with_mock_gateway  # type: ignore[assignment]
    return orchestrator, mock_anthropic, mock_openai


async def test_full_pipeline_with_mock_llm(mock_orchestrator, fixture_repo):
    orchestrator, mock_anthropic, mock_openai = mock_orchestrator

    result = await orchestrator.run("Add user comments to product pages", fixture_repo)

    assert result.ok, f"Expected ok run, got reason={result.reason}"
    assert result.spec is not None
    assert result.workspace is not None
    assert result.spec.metadata.feature_id == "product-comments"
    assert len(result.spec.functional_requirements) >= 2
    assert len(result.spec.self_concerns) >= 1

    # Both providers should have been called
    assert mock_anthropic.call_count > 0
    assert mock_openai.call_count > 0

    # Artifacts on disk
    ws = result.workspace
    assert (ws / "spec.md").is_file()
    assert (ws / "spec.json").is_file()
    assert (ws / "intent" / "confirmed.json").is_file()
    assert (ws / "exploration" / "consolidated.json").is_file()
    assert (ws / "approach" / "selected.json").is_file()

    # Validate the spec.json on disk parses back to a Spec
    from devloop.spec_phase.md_json_bridge import spec_from_json

    spec_disk = spec_from_json((ws / "spec.json").read_text(encoding="utf-8"))
    assert spec_disk.metadata.feature_id == result.spec.metadata.feature_id


async def test_preflight_rejection(mock_orchestrator, fixture_repo):
    orchestrator, _, _ = mock_orchestrator
    result = await orchestrator.run("x", fixture_repo)
    assert not result.ok
    assert "short" in result.reason.lower()
