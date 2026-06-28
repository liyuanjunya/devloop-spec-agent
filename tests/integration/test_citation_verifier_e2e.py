"""End-to-end integration tests for the A5 citation verifier guard.

Complements ``test_orchestrator_citation_guard.py`` with broader coverage of
the writer → review → mechanical-verifier → rewriter → consolidated_review
data flow. Each test mocks the writer to emit a spec with one specific
class of citation defect (missing file / out-of-bounds range / missing
symbol), runs the full :class:`SpecOrchestrator`, and asserts that the
orchestrator surfaces the defect as a HIGH-severity ``executability``
:class:`ReviewIssue` whose evidence/description identifies the bad
citation.

Test inventory (≥6, per T-defense-fires-A5):

1. ``test_writer_emits_bad_citation_orchestrator_injects_high_issue`` —
   FR-001 cites a file that doesn't exist on disk.
2. ``test_writer_emits_wrong_line_range_orchestrator_injects`` — file
   exists but the line range is past EOF.
3. ``test_writer_emits_missing_symbol_orchestrator_injects`` — range is
   valid but the cited symbol does not appear inside it.
4. ``test_rewriter_fixes_citation_loop_terminates`` — first writer
   iteration is bad, second (rewriter) iteration is good; the loop must
   stop flagging the citation and converge.
5. ``test_citation_verify_budget_exhausted`` — writer keeps producing
   bad citations; after ``citation_verify_max_attempts`` the orchestrator
   marks ``needs_review=True`` instead of looping forever.
6. ``test_no_citations_passes`` — spec with only non-functional FRs
   (no ``code_references``) never triggers the verifier; review converges
   on iteration 1 with ``needs_review=False``.
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
# Shared upstream handlers (intent / explorer / consolidator / approach /
# reviewer). These mirror the ones used in
# ``test_orchestrator_citation_guard.py`` so the writer is the only variable
# we change per test.
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
    """One mark_as_relevant tool call per perspective, then COMPLETE."""
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


def _reviewer_pass_handler():
    """A reviewer that always says PASS. The mechanical citation verifier is
    the only thing that can flag (or stop flagging) citation problems, so
    pass-verdicts isolate the A5 plumbing from LLM reviewer noise."""

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


# ---------------------------------------------------------------------------
# Spec factories — one per citation-defect class.
# ---------------------------------------------------------------------------


def _base_spec(*, iter_n: int, code_references: list[dict], requirement_type: str = "functional") -> dict:
    """Skeleton spec parameterized by the FR's citation list and type.

    Keeps every other field constant so each test's bad ``code_references``
    is the only difference the orchestrator can react to.
    """
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
                "requirement_type": requirement_type,
                "related_user_stories": ["US-1"],
                "related_success_criteria": ["SC-001"],
                "code_references": code_references,
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


def _missing_file_refs() -> list[dict]:
    """FR-001 cites a file that doesn't exist on disk → file_not_found."""
    return [
        {
            "path": "app/models/does_not_exist.py",
            "symbols": ["GhostModel"],
            "line_ranges": [[1, 10]],
            "snippet": "",
        }
    ]


def _bad_range_refs() -> list[dict]:
    """File exists; range is past EOF → range_out_of_bounds.

    ``app/models/user.py`` has 21 content lines (``splitlines()`` doesn't
    count the trailing newline as a separate line), so any end > 21 is out
    of bounds. We pick 9999 so the bad number is clearly an LLM-style
    "I made up a line number" defect.
    """
    return [
        {
            "path": "app/models/user.py",
            "symbols": ["User"],
            "line_ranges": [[1, 9999]],
            "snippet": "",
        }
    ]


def _missing_symbol_refs() -> list[dict]:
    """Range is valid (lines 6-8 are SQLAlchemy imports) but the symbol
    ``User`` (which lives on line 12) is absent from that range →
    symbols_missing."""
    return [
        {
            "path": "app/models/user.py",
            "symbols": ["User"],
            "line_ranges": [[6, 8]],
            "snippet": "",
        }
    ]


def _good_refs() -> list[dict]:
    """A correct citation: lines 1-21 of user.py contain ``class User``."""
    return [
        {
            "path": "app/models/user.py",
            "symbols": ["User"],
            "line_ranges": [[1, 21]],
            "snippet": "class User",
        }
    ]


# ---------------------------------------------------------------------------
# Writer handlers.
#
# Each writer handler is a closure: the writer call returns the initial bad
# spec; subsequent rewriter calls behave per-strategy (always-bad / fixes /
# never-bad). Returning the closure's mutable state lets tests assert the
# exact number of writer / rewriter invocations.
# ---------------------------------------------------------------------------


def _writer_handler_always(refs_factory):
    """Writer + rewriter both keep emitting the same defective citation."""
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            return make_json_response(
                _base_spec(iter_n=1 + state["rewrites"], code_references=refs_factory())
            )
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(
                _base_spec(iter_n=1, code_references=refs_factory())
            )
        return None

    return handler, state


def _writer_handler_fixes_after_one_rewrite(bad_refs_factory):
    """Writer emits a bad citation; first rewriter call returns a GOOD spec."""
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            return make_json_response(
                _base_spec(iter_n=1 + state["rewrites"], code_references=_good_refs())
            )
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(
                _base_spec(iter_n=1, code_references=bad_refs_factory())
            )
        return None

    return handler, state


def _writer_handler_no_citations():
    """Writer emits a spec with a non-functional FR and no code_references."""
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            return make_json_response(
                _base_spec(
                    iter_n=1 + state["rewrites"],
                    code_references=[],
                    requirement_type="non_functional",
                )
            )
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(
                _base_spec(
                    iter_n=1,
                    code_references=[],
                    requirement_type="non_functional",
                )
            )
        return None

    return handler, state


# ---------------------------------------------------------------------------
# Orchestrator harness.
# ---------------------------------------------------------------------------


def _build_orchestrator(
    tmp_path: Path,
    handler,
    *,
    citation_max_attempts: int = 3,
    max_total_iterations: int = 10,
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


def _find_citation_issues(workspace: Path) -> list[dict]:
    """Walk every persisted ``review_v*_consolidated.json`` and return every
    HIGH-severity ``executability`` issue whose id starts with ``CITE-``."""
    review_files = sorted(
        (workspace / "spec_iterations").glob("review_v*_consolidated.json")
    )
    out: list[dict] = []
    for rf in review_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                if (
                    issue.get("reviewer_type") == "executability"
                    and issue.get("severity") == "high"
                    and str(issue.get("id", "")).startswith("CITE-")
                ):
                    out.append(issue)
    return out


# ---------------------------------------------------------------------------
# 1. Bad path → file_not_found injected as HIGH executability issue.
# ---------------------------------------------------------------------------


async def test_writer_emits_bad_citation_orchestrator_injects_high_issue(
    tmp_path, fixture_repo
):
    """FR-001 cites a path that doesn't exist; orchestrator surfaces CITE-* HIGH issue."""
    writer_handler, _state = _writer_handler_always(_missing_file_refs)
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(
        tmp_path, combined, citation_max_attempts=2, max_total_iterations=6
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok and result.spec is not None and result.workspace is not None

    cite_issues = _find_citation_issues(result.workspace)
    assert cite_issues, "expected at least one CITE-* HIGH executability issue"
    # The description must name the failing verifier check (file_not_found)
    # and the evidence must include the bad path so the rewriter has something
    # actionable to grab and edit.
    descriptions = [i.get("description", "") for i in cite_issues]
    evidences = [i.get("evidence", "") for i in cite_issues]
    locations = [i.get("location", "") for i in cite_issues]
    assert any("file_not_found" in d for d in descriptions), descriptions
    assert any("app/models/does_not_exist.py" in e for e in evidences), evidences
    # location follows the contract "<FR_id>.code_references[<idx>]"
    assert any("FR-001.code_references[0]" == loc for loc in locations), locations


# ---------------------------------------------------------------------------
# 2. Out-of-bounds line range → range_out_of_bounds injected.
# ---------------------------------------------------------------------------


async def test_writer_emits_wrong_line_range_orchestrator_injects(
    tmp_path, fixture_repo
):
    """FR-001 cites valid file with end-of-range past EOF; orchestrator flags it."""
    writer_handler, _state = _writer_handler_always(_bad_range_refs)
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(
        tmp_path, combined, citation_max_attempts=2, max_total_iterations=6
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok and result.spec is not None and result.workspace is not None

    cite_issues = _find_citation_issues(result.workspace)
    assert cite_issues, "expected at least one CITE-* HIGH executability issue"
    descriptions = [i.get("description", "") for i in cite_issues]
    evidences = [i.get("evidence", "") for i in cite_issues]
    assert any("range_out_of_bounds" in d for d in descriptions), descriptions
    # Evidence should surface the wildly-wrong end value so the writer knows
    # *which* range to shrink.
    assert any("9999" in e for e in evidences), evidences
    # The verifier must report the actual file line count (21 — splitlines()
    # excludes the trailing newline) without it the writer has no anchor to
    # clamp the bad range against.
    assert any("21" in e for e in evidences), evidences


# ---------------------------------------------------------------------------
# 3. Symbol present in file but not in the cited range → symbols_missing.
# ---------------------------------------------------------------------------


async def test_writer_emits_missing_symbol_orchestrator_injects(
    tmp_path, fixture_repo
):
    """Range is valid but symbol ``User`` isn't in lines 6-8 (imports only)."""
    writer_handler, _state = _writer_handler_always(_missing_symbol_refs)
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(
        tmp_path, combined, citation_max_attempts=2, max_total_iterations=6
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok and result.spec is not None and result.workspace is not None

    cite_issues = _find_citation_issues(result.workspace)
    assert cite_issues, "expected at least one CITE-* HIGH executability issue"
    descriptions = [i.get("description", "") for i in cite_issues]
    evidences = [i.get("evidence", "") for i in cite_issues]
    assert any("symbols_missing" in d for d in descriptions), descriptions
    # The missing symbol name must appear in evidence so the rewriter can
    # locate the real definition and update line_ranges.
    assert any("User" in e for e in evidences), evidences


# ---------------------------------------------------------------------------
# 4. Rewriter fixes the citation; orchestrator stops flagging it.
# ---------------------------------------------------------------------------


async def test_rewriter_fixes_citation_loop_terminates(tmp_path, fixture_repo):
    """First iteration: bad citation → injected issue. Rewriter returns a good
    spec on iteration 2 → no more CITE-* issues on the v2 review; loop
    converges with ``needs_review=False``."""
    writer_handler, state = _writer_handler_fixes_after_one_rewrite(
        _missing_symbol_refs
    )
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(
        tmp_path, combined, citation_max_attempts=3, max_total_iterations=10
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok and result.spec is not None and result.workspace is not None

    # The loop must converge: a single rewriter call is enough because the
    # reviewer says PASS and the rewriter fixes the only outstanding issue.
    assert state["rewrites"] >= 1
    # The final spec must NOT be marked needs_review — the budget was never
    # exhausted because the second iteration came back clean.
    assert result.spec.metadata.needs_review is False, (
        "loop should converge cleanly when the rewriter actually fixes the citation"
    )

    # Inspect the per-iteration artifacts: iteration 1 must have a CITE-*
    # issue (the bad citation surfaced once); the LAST iteration must have
    # zero CITE-* issues so we can prove the verifier stopped flagging.
    sp_dir = result.workspace / "spec_iterations"
    review_files = sorted(sp_dir.glob("review_v*_consolidated.json"))
    assert len(review_files) >= 2, (
        f"expected at least 2 review iterations, found {len(review_files)}"
    )

    def _cite_count(path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        n = 0
        for r in data.get("reviews", []):
            for issue in r.get("issues", []):
                if str(issue.get("id", "")).startswith("CITE-"):
                    n += 1
        return n

    assert _cite_count(review_files[0]) >= 1, "iteration 1 should flag the bad citation"
    assert _cite_count(review_files[-1]) == 0, (
        "final iteration must have no CITE-* issues after the rewriter fixed the citation"
    )


# ---------------------------------------------------------------------------
# 5. Budget exhausted → orchestrator marks needs_review (no infinite loop).
# ---------------------------------------------------------------------------


async def test_citation_verify_budget_exhausted(tmp_path, fixture_repo):
    """When the writer keeps producing bad citations, the orchestrator must
    exhaust ``citation_verify_max_attempts`` and mark ``needs_review=True``
    rather than loop forever."""
    writer_handler, _state = _writer_handler_always(_missing_symbol_refs)
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    citation_max_attempts = 2
    # Cap iterations far above the citation budget so the test fails loudly
    # if the verifier ever forgets to exit (i.e. real infinite loop).
    orchestrator = _build_orchestrator(
        tmp_path,
        combined,
        citation_max_attempts=citation_max_attempts,
        max_total_iterations=8,
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok and result.spec is not None and result.workspace is not None

    # Budget exhaustion path: needs_review MUST flip True.
    assert result.spec.metadata.needs_review is True, (
        "budget-exhausted citation problems must mark the spec needs_review"
    )

    # The verifier injects one issue per iteration up to citation_max_attempts;
    # CITE-iteration ids should appear with iterations <= the budget. We
    # collect all CITE- ids and assert the iteration numbers are bounded.
    cite_issues = _find_citation_issues(result.workspace)
    assert cite_issues, "expected at least one CITE-* issue across the run"

    # Issue ids follow CITE-<iter>-<idx>; extract iteration numbers and
    # confirm no iteration above citation_max_attempts ever sees a fresh
    # injection (the orchestrator may continue running other stages but it
    # should not keep appending citation issues once the budget is spent).
    iteration_nums: set[int] = set()
    for i in cite_issues:
        cid = i["id"]  # CITE-NN-NNN
        parts = cid.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            iteration_nums.add(int(parts[1]))
    assert iteration_nums, f"could not parse CITE- ids: {cite_issues!r}"
    assert max(iteration_nums) <= citation_max_attempts, (
        f"citation issues injected past budget: {sorted(iteration_nums)}; "
        f"budget was {citation_max_attempts}"
    )


# ---------------------------------------------------------------------------
# 6. Spec with no code_references never triggers the verifier.
# ---------------------------------------------------------------------------


async def test_no_citations_passes(tmp_path, fixture_repo):
    """Non-functional FRs without ``code_references`` produce zero citation
    problems; the orchestrator converges cleanly on iteration 1 and does not
    set ``needs_review``."""
    writer_handler, state = _writer_handler_no_citations()
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_handler,
        _reviewer_pass_handler(),
    )
    orchestrator = _build_orchestrator(
        tmp_path, combined, citation_max_attempts=3, max_total_iterations=6
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)
    assert result.ok and result.spec is not None and result.workspace is not None

    assert state["writes"] == 1, f"expected single writer call, got {state['writes']}"

    # No citation problems → zero injected CITE-* issues anywhere.
    cite_issues = _find_citation_issues(result.workspace)
    assert cite_issues == [], (
        f"expected no CITE-* issues for a no-code-reference spec, got: "
        f"{[i['id'] for i in cite_issues]}"
    )

    # The spec must NOT be flagged needs_review on the no-citation happy path.
    assert result.spec.metadata.needs_review is False, (
        "needs_review should remain False when no citation problems exist"
    )
