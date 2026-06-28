"""Integration tests for the B3 trace-matrix gap injection in the orchestrator.

These tests walk the orchestrator's review-rewrite loop with a mock writer
that *consistently* produces a spec with a specific FR↔SC↔US trace gap
(FR without SC / SC without FR / P1 US without FR). The mechanical
:func:`devloop.spec_phase.validators.find_trace_gaps` validator must catch
the gap each iteration and inject HIGH ``executability``
:class:`ReviewIssue` instances into the consolidated review so the
rewriter sees them next iteration. The fourth scenario covers the negative
path (clean spec — no synthetic injection, loop converges at iteration 1).

The integration angle (vs. the unit tests in
``tests/unit/validators/test_trace_matrix.py``) is that this exercises the
**full orchestrator pipeline**: writer → reviewer → ``inject_trace_gap_issues``
→ persisted ``review_v*_consolidated.json`` artifact, end-to-end. Boundary
documentation: see the ANALYSIS section at the bottom of this file.
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
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import (
    MockProvider,
    make_json_response,
    make_text_response,
    make_tool_call_response,
)

# ---------------------------------------------------------------------------
# Stage handlers (intent / explorer / consolidator / approach) — minimal
# valid responses; copied/adapted from test_orchestrator_citation_guard.py
# so each integration test in this file is self-contained.
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
    """Single mark_as_relevant tool call per perspective, then COMPLETE."""
    state = {"step": {}}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "**your perspective**" not in sl:
            return None
        perspective = next(
            (
                p
                for p in ["data", "api", "ui", "test", "history"]
                if f"perspective**: {p}" in sl
            ),
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


# ---------------------------------------------------------------------------
# Spec factories — each returns the same spec shape but flips one trace
# edge to induce the targeted gap. All citations are valid (User class
# really is on line 12 of app/models/user.py in the sample_repo fixture)
# so the A5 citation verifier does not also fire and pollute the
# assertions.
# ---------------------------------------------------------------------------


def _us(us_id: str, priority: str = "P1") -> dict:
    return {
        "id": us_id,
        "priority": priority,
        "title": f"Story {us_id}",
        "description": f"User does action {us_id}.",
        "why_this_priority": "core",
        "independent_test": "manual exercise",
        "acceptance": [{"given": "g", "when": "w", "then": "t"}],
    }


def _fr(
    fr_id: str,
    *,
    related_user_stories: list[str] | None = None,
    related_success_criteria: list[str] | None = None,
    requirement_type: str = "functional",
) -> dict:
    return {
        "id": fr_id,
        "text": f"Requirement {fr_id} performs an action.",
        "requirement_type": requirement_type,
        "related_user_stories": related_user_stories or [],
        "related_success_criteria": related_success_criteria or [],
        "code_references": (
            [
                {
                    "path": "app/models/user.py",
                    "symbols": ["User"],
                    "line_ranges": [[1, 21]],
                    "snippet": "",
                }
            ]
            if requirement_type == "functional"
            else []
        ),
        "testable": True,
    }


def _sc(sc_id: str, *, related_requirements: list[str] | None = None) -> dict:
    return {
        "id": sc_id,
        "text": f"Acceptance criterion {sc_id}.",
        "metric": f"p99 latency for {sc_id}",
        "threshold": "< 500ms",
        "technology_agnostic": True,
        "related_requirements": related_requirements or [],
    }


def _base_spec(
    *,
    user_stories: list[dict],
    functional_requirements: list[dict],
    success_criteria: list[dict],
    iter_n: int = 1,
) -> dict:
    return {
        "schema_version": "1.0",
        "metadata": {
            "feature_id": "trace-demo",
            "title": "Trace Demo Feature",
            "writer_model": "mock-claude",
            "reviewer_model": "mock-gpt",
            "iterations": iter_n,
            "needs_review": False,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
        },
        "summary": "Synthetic spec exercising the trace-matrix injection path.",
        "user_stories": user_stories,
        "functional_requirements": functional_requirements,
        "success_criteria": success_criteria,
        "key_entities": [
            {"name": "X", "description": "x", "fields": [], "references": []}
        ],
        "edge_cases": [],
        "assumptions": [],
        "out_of_scope": [],
        "self_concerns": [],
    }


def _spec_fr_without_sc(iter_n: int = 1) -> dict:
    """FR-001 (functional) has no SC link in either direction. No SCs at all
    means there is nothing for SC-orphan / cross-ref gaps to fire on, so the
    *only* injected issue is ``fr_without_sc`` for FR-001."""
    return _base_spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr("FR-001", related_user_stories=["US-1"], related_success_criteria=[])
        ],
        success_criteria=[],
        iter_n=iter_n,
    )


def _spec_sc_without_fr(iter_n: int = 1) -> dict:
    """SC-002 is orphan; FR-001↔SC-001 is bidirectionally linked so no FR
    orphan gap fires. The only injected issue is ``sc_without_fr`` for SC-002."""
    return _base_spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[
            _sc("SC-001", related_requirements=["FR-001"]),
            _sc("SC-002"),  # no related_requirements → orphan
        ],
        iter_n=iter_n,
    )


def _spec_p1_us_without_fr(iter_n: int = 1) -> dict:
    """US-2 (P1) is not referenced by any FR.related_user_stories. The
    only injected issue is ``us_without_fr`` for US-2."""
    return _base_spec(
        user_stories=[_us("US-1", "P1"), _us("US-2", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
        iter_n=iter_n,
    )


def _spec_clean(iter_n: int = 1) -> dict:
    """Clean spec: bidirectional FR↔SC link + P1 US claimed by FR. The
    validator finds zero gaps, so ``inject_trace_gap_issues`` returns the
    review unmodified and the loop converges at iteration 1."""
    return _base_spec(
        user_stories=[_us("US-1", "P1")],
        functional_requirements=[
            _fr(
                "FR-001",
                related_user_stories=["US-1"],
                related_success_criteria=["SC-001"],
            )
        ],
        success_criteria=[_sc("SC-001", related_requirements=["FR-001"])],
        iter_n=iter_n,
    )


# ---------------------------------------------------------------------------
# Writer / reviewer handlers + orchestrator factory
# ---------------------------------------------------------------------------


def _writer_handler(spec_factory):
    """Writer/rewriter that returns whatever ``spec_factory(iter_n)`` yields.

    Always returns the same gap shape — the rewriter never "fixes" the
    trace gap, so the orchestrator must rely on no-progress detection (or
    iteration cap) to terminate the loop.
    """
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl:
            state["rewrites"] += 1
            return make_json_response(spec_factory(iter_n=1 + state["rewrites"]))
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(spec_factory(iter_n=1))
        return None

    return handler


def _reviewer_pass_handler():
    """Architecture reviewer always says PASS — the only forcing pressure on
    the loop comes from B3 trace-matrix injection (when gaps exist)."""

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
    max_total_iterations: int = 5,
) -> SpecOrchestrator:
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    # Single reviewer keeps the angle count to 1 (architecture); the B3
    # injector then synthesises a separate executability ReviewResult, so
    # TRACE-* issues are easy to find in the persisted artifact without
    # noise from 3 other LLM-driven reviewers.
    settings.orchestrator.enable_multi_reviewer = False
    settings.orchestrator.enable_meta_reviewer = False
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
    return orchestrator


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------


def _collect_trace_issues(workspace: Path) -> list[dict]:
    """Read every persisted ``review_v*_consolidated.json`` and return all
    HIGH ``executability`` issues whose id starts with ``TRACE-``."""
    found: list[dict] = []
    review_files = sorted(
        (workspace / "spec_iterations").glob("review_v*_consolidated.json")
    )
    assert review_files, "expected at least one consolidated review artifact"
    for rf in review_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                if (
                    issue.get("reviewer_type") == "executability"
                    and issue.get("severity") == "high"
                    and issue.get("id", "").startswith("TRACE-")
                ):
                    found.append(issue)
    return found


def _trace_actors(issues: list[dict]) -> set[str]:
    return {i.get("location", "") for i in issues}


def _trace_kinds(issues: list[dict]) -> set[str]:
    """Return the gap-kind tags embedded in the ``[trace-matrix:KIND]`` prefix
    that ``inject_trace_gap_issues`` adds to every description."""
    kinds: set[str] = set()
    for i in issues:
        desc = i.get("description", "")
        # Format is "[trace-matrix:kind] detail..."
        if desc.startswith("[trace-matrix:"):
            kinds.add(desc.split("[trace-matrix:", 1)[1].split("]", 1)[0])
    return kinds


# ===========================================================================
# Integration tests
# ===========================================================================


async def test_fr_without_sc_injects_issue(tmp_path, fixture_repo):
    """Writer emits spec where FR-001 (functional) has no SC link in either
    direction. The orchestrator must inject a HIGH ``executability``
    ReviewIssue locating ``FR-001`` so the rewriter sees it next iteration.
    """
    writer = _writer_handler(_spec_fr_without_sc)
    handler = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(tmp_path, handler, max_total_iterations=4)
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok
    assert result.workspace is not None

    issues = _collect_trace_issues(result.workspace)
    assert issues, "expected at least one TRACE-* injected issue"
    actors = _trace_actors(issues)
    assert "FR-001" in actors, f"expected FR-001 actor; got {actors}"
    kinds = _trace_kinds(issues)
    assert "fr_without_sc" in kinds, (
        f"expected 'fr_without_sc' kind tag in description; got {kinds}"
    )

    # The HIGH executability issues should also mention FR-001 in their
    # human-readable description so the rewriter can act on them.
    fr_issues = [i for i in issues if i.get("location") == "FR-001"]
    assert fr_issues
    assert any("FR-001" in i.get("description", "") for i in fr_issues)

    # No-progress on a never-fixed gap → orchestrator marks needs_review.
    assert result.spec is not None
    assert result.spec.metadata.needs_review is True


async def test_sc_without_fr_injects_issue(tmp_path, fixture_repo):
    """Writer emits spec where SC-002 has no FR link. FR-001↔SC-001 stays
    bidirectional so the only TRACE-* issue is the SC orphan for SC-002.
    """
    writer = _writer_handler(_spec_sc_without_fr)
    handler = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(tmp_path, handler, max_total_iterations=4)
    result = await orchestrator.run("Add user comments", fixture_repo)
    assert result.ok
    assert result.workspace is not None

    issues = _collect_trace_issues(result.workspace)
    assert issues
    actors = _trace_actors(issues)
    assert "SC-002" in actors, f"expected SC-002 actor; got {actors}"
    # FR-001 is properly linked → no fr_without_sc gap should fire for it.
    assert "FR-001" not in actors, (
        f"FR-001 is properly linked, must not appear as a trace gap actor; got {actors}"
    )
    kinds = _trace_kinds(issues)
    assert kinds == {"sc_without_fr"}, (
        f"only sc_without_fr expected, got {kinds}"
    )

    assert result.spec is not None
    assert result.spec.metadata.needs_review is True


async def test_p1_us_without_fr_injects_issue(tmp_path, fixture_repo):
    """Writer emits spec where P1 US-2 is not claimed by any FR. The only
    TRACE-* injection should be ``us_without_fr`` for US-2."""
    writer = _writer_handler(_spec_p1_us_without_fr)
    handler = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(tmp_path, handler, max_total_iterations=4)
    result = await orchestrator.run("Add comments end-to-end", fixture_repo)
    assert result.ok
    assert result.workspace is not None

    issues = _collect_trace_issues(result.workspace)
    assert issues
    actors = _trace_actors(issues)
    assert "US-2" in actors, f"expected US-2 actor; got {actors}"
    # US-1 is claimed → no gap for it. FR-001 and SC-001 are bidirectional → no gaps either.
    assert "US-1" not in actors
    assert "FR-001" not in actors
    assert "SC-001" not in actors
    kinds = _trace_kinds(issues)
    assert kinds == {"us_without_fr"}, (
        f"only us_without_fr expected, got {kinds}"
    )

    assert result.spec is not None
    assert result.spec.metadata.needs_review is True


async def test_trace_complete_no_injection(tmp_path, fixture_repo):
    """Negative path: writer emits a fully-linked spec. ``find_trace_gaps``
    returns ``[]``, ``inject_trace_gap_issues`` is a no-op, reviewer says
    PASS, and the loop converges at iteration 1 with **zero** TRACE-* issues
    in any persisted review artifact.
    """
    writer = _writer_handler(_spec_clean)
    handler = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(tmp_path, handler, max_total_iterations=5)
    result = await orchestrator.run("Add a clean feature", fixture_repo)
    assert result.ok
    assert result.workspace is not None

    # With a clean trace, NO TRACE-* issue must appear in any persisted
    # review artifact. We can't reuse _collect_trace_issues' assertion that
    # at least one review file exists+is non-empty for TRACE-* (it would
    # fail the empty case), so we inline the scan.
    review_files = sorted(
        (result.workspace / "spec_iterations").glob("review_v*_consolidated.json")
    )
    assert review_files, "expected at least one consolidated review artifact"
    leaked: list[dict] = []
    for rf in review_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                if issue.get("id", "").startswith("TRACE-"):
                    leaked.append(issue)
    assert leaked == [], (
        f"expected zero TRACE-* injections on a clean spec; got {leaked}"
    )

    # Clean spec → all_pass at iteration 1 → no needs_review escalation.
    assert result.spec is not None
    assert result.spec.metadata.needs_review is False


# ===========================================================================
# ANALYSIS
# ===========================================================================
#
# What these tests verify (the B3 capability boundary)
# ----------------------------------------------------
# 1. ``find_trace_gaps`` + ``inject_trace_gap_issues`` correctly translate
#    each enumerated TraceGap.kind into one HIGH ``executability``
#    :class:`ReviewIssue` with ``location == gap.actor`` and a description
#    prefixed by ``[trace-matrix:<kind>]``. Verified on the disk artifact
#    that the rewriter actually consumes (``review_v*_consolidated.json``),
#    not just the in-memory return value.
# 2. The injection happens **regardless** of what the LLM reviewer says
#    (the mock reviewer here always returns ``VERDICT: pass``). This is the
#    whole point of B3 — mechanical gaps must fire even when the LLM
#    reviewers miss them, which was the empirical failure mode across
#    Mealie cases.
# 3. The injection downgrades the consolidated verdict from ``pass`` to
#    ``needs_refine``: with a writer that never fixes the gap, the loop
#    eventually exhausts no-progress retries and flips
#    ``spec.metadata.needs_review = True``. (Asserted in the three positive
#    tests.)
# 4. Negative path: a clean spec produces ZERO synthetic TRACE-* issues
#    and the loop converges at iteration 1 with ``needs_review = False``.
#
# What these tests intentionally DO NOT verify (boundary)
# -------------------------------------------------------
# * The exact iteration count at which no-progress trips — that's an A1
#   regression-guard / no-progress concern (covered separately) and would
#   tightly couple this test to unrelated orchestrator tuning. We only
#   assert the terminal state (``needs_review=True``) for the three "always
#   broken" scenarios.
# * Whether the LLM rewriter actually fixes the gap when shown the
#   injected issue — that requires a real LLM and is the domain of the
#   Mealie end-to-end evaluator (Track B), not Track A defense fires.
#   Our writer is hard-wired to return the same gapped spec every time so
#   we can isolate the injection signal.
# * The remaining two TraceGap kinds (``fr_references_unknown_sc`` and
#   ``sc_references_unknown_fr``) — covered by the existing unit suite at
#   ``tests/unit/validators/test_trace_matrix.py``. Repeating them at the
#   integration layer would add cost (~4-5 s each) without exercising a
#   new orchestrator code path: the injection wrapper handles all five
#   kinds identically.
# * Meta-reviewer behaviour: ``enable_meta_reviewer`` is set to ``False``
#   in the test harness so meta-review (B4) does not consume the injected
#   issues. Meta-reviewer integration is the scope of T-defense-fires-B4.
# * Multi-reviewer angles: ``enable_multi_reviewer`` is set to ``False``
#   so only the ``architecture`` angle runs. The B3 injector then
#   synthesises its own ``executability`` ReviewResult (judge_model
#   ``trace-matrix-validator``); the case where an LLM ``executability``
#   reviewer already exists and we *append* to it is covered by the unit
#   tests on ``inject_trace_gap_issues`` (orchestrator-level coupling
#   verified, branch coverage at unit level).
#
# Performance
# -----------
# Each integration test runs the full orchestrator pipeline against the
# sample_repo fixture using deterministic mock LLM providers. Expected
# runtime is comparable to the existing A5 citation-guard integration test
# (~4 s on the reference machine); the three "always broken" scenarios run
# for up to ``max_total_iterations=4`` review-rewrite iterations each,
# while the clean-trace scenario converges in a single iteration.
