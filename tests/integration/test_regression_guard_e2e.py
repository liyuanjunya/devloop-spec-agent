"""End-to-end integration tests for the A1 regression guard.

T-defense-fires-A1 — capability-boundary tests proving that
:meth:`SpecOrchestrator._review_rewrite_loop` correctly:

* detects when a rewrite *regresses* (critical+high issues went UP) and forces
  a regression-aware retry with extra_context fed to the rewriter,
* feeds the LAST GOOD baseline spec (not the bad v2) into the regression
  retry,
* reverts to the last good baseline and marks ``needs_review`` when the
  configured ``max_regression_retries`` budget is exhausted,
* does NOT trigger any of the above when the rewrite genuinely improved,
* respects a custom ``max_regression_retries`` setting,
* picks the most-recent improved snapshot as the revert baseline (NOT the
  initial writer spec) when an intermediate iteration improved before the
  regression hit.

Each test scripts the LLM responses through :class:`MockProvider` so the
full orchestrator pipeline runs deterministically without network. The
review-rewrite loop is exercised end-to-end via ``orchestrator.run`` so the
test cuts across the writer / reviewer / regression-guard wiring inside
the orchestrator itself.
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
# Markers — embedded into spec.summary so a test can identify which spec was
# fed into a given rewriter call by string-searching the captured system prompt.
# ---------------------------------------------------------------------------

WRITER_BASELINE_MARKER = "SPECMARK_WRITER_BASELINE_V1"


def _rewriter_output_marker(call_index: int) -> str:
    """Stable, search-friendly marker for the Nth rewriter call output."""
    return f"SPECMARK_REWRITER_OUTPUT_C{call_index}"


REGRESSION_EXTRA_CONTEXT_HEADER = "REGRESSION CONTEXT"
REGRESSION_FEEDBACK_PREFIX = "REGRESSION DETECTED"


# ---------------------------------------------------------------------------
# Common scaffolding: intent / explorer / consolidator / approach handlers.
# Lifted from tests/integration/test_review_loop.py and pared to the minimum
# the regression-guard tests need.
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
            (
                p
                for p in ("data", "api", "ui", "test", "history")
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
# Writer + rewriter handler — tags each produced spec with a unique marker
# baked into ``spec.summary`` so the test can identify *which* spec was fed
# into a downstream rewriter call by string-searching the captured system
# prompt. Also records every rewriter call's full system prompt in
# ``state['rewriter_calls']`` for direct assertions.
# ---------------------------------------------------------------------------


def _make_spec(*, iter_n: int, marker: str) -> dict:
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
        "summary": marker,
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
        "key_entities": [
            {"name": "X", "description": "x", "fields": [], "references": []}
        ],
        "edge_cases": [],
        "assumptions": [],
        "out_of_scope": [],
        "self_concerns": [],
    }


def _writer_handler():
    """Writer + rewriter handler with full system-prompt capture.

    Each rewriter output spec embeds a unique marker into ``summary`` so
    later assertions can pin down which spec was fed back into the next
    rewriter call (regression retries should feed the BASELINE spec, not
    the bad v2 spec).
    """

    state = {
        "writes": 0,
        "rewrites": 0,
        # Each entry: {"system": str, "call_index": int}
        "rewriter_calls": [],
    }

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl or "you are the **spec rewriter**" in sl:
            state["rewrites"] += 1
            call_idx = state["rewrites"]
            state["rewriter_calls"].append(
                {"system": system, "call_index": call_idx}
            )
            marker = _rewriter_output_marker(call_idx)
            # iter_n on the OUTPUT spec is overridden by the orchestrator
            # (which sets iterations = iteration + 1) — value here is a
            # placeholder.
            return make_json_response(
                _make_spec(iter_n=call_idx + 1, marker=marker)
            )
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(
                _make_spec(iter_n=1, marker=WRITER_BASELINE_MARKER)
            )
        return None

    return handler, state


# ---------------------------------------------------------------------------
# Reviewer handler — flags a *scripted* number of critical issues per
# iteration via the flag_issue tool, then emits VERDICT. The per-iteration
# count comes from ``crit_per_iter``; when iter > len(script) the last
# count is reused (so a trailing infinite stream of regressions is easy).
# ---------------------------------------------------------------------------


def _counting_reviewer_handler(crit_per_iter: list[int]):
    """Architecture-only reviewer scripted by per-iteration critical count.

    Counts the existing ``flag_issue`` tool results in the messages to know
    how many flags the current iteration has already emitted; emits more
    until the target for this iteration is met, then emits a VERDICT and
    advances the iteration index.
    """

    state = {"iter_idx": 0, "flag_counts": []}

    def _target_for_current_iter() -> int:
        idx = state["iter_idx"]
        if idx < len(crit_per_iter):
            return crit_per_iter[idx]
        # If the script runs short, repeat the last value (stream of
        # regressions in budget-exhaustion tests just keeps escalating).
        return crit_per_iter[-1]

    def handler(model, system, messages, tools, response_format):
        if "reviewer" not in system.lower():
            return None
        flagged_so_far = sum(
            1
            for m in messages
            if m.role == "tool" and m.name == "flag_issue"
        )
        target = _target_for_current_iter()
        if flagged_so_far < target:
            return make_tool_call_response(
                name="flag_issue",
                arguments={
                    "severity": "critical",
                    "location": f"FR-001#{flagged_so_far + 1}",
                    "description": f"Scripted critical issue {flagged_so_far + 1}",
                    "evidence": "deterministic mock reviewer",
                },
            )
        # Done flagging this iteration. Advance, then emit verdict.
        state["flag_counts"].append(flagged_so_far)
        state["iter_idx"] += 1
        verdict = "pass" if target == 0 else "fail"
        return make_text_response(f"Scripted reviewer output.\nVERDICT: {verdict}")

    return handler, state


def _combined(*handlers):
    def handler(*args, **kwargs):
        for h in handlers:
            r = h(*args, **kwargs)
            if r is not None:
                return r
        return make_text_response("(unhandled)")

    return handler


# ---------------------------------------------------------------------------
# Orchestrator builder. Deliberately disables meta-reviewer and segmented
# rewriter to keep the regression-guard path the only thing under test.
# Single-reviewer mode also guarantees exactly one reviewer-call thread per
# iteration so the scripted ``crit_per_iter`` is unambiguous.
# ---------------------------------------------------------------------------


def _build_orchestrator(
    tmp_path: Path,
    handler,
    *,
    max_regression_retries: int = 2,
    max_total_iterations: int = 20,
):
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)

    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = False
    settings.orchestrator.enable_meta_reviewer = False
    settings.orchestrator.use_segmented_rewriter = False
    settings.orchestrator.max_total_iterations = max_total_iterations
    settings.orchestrator.max_regression_retries = max_regression_retries
    # Bump no-progress threshold above any iteration count any test uses so
    # we don't accidentally exit via the no-progress path instead of the
    # regression guard. The regression-retry branch `continue`s past the
    # issue-history append, but defensive — keep the budget large.
    settings.orchestrator.no_progress_threshold = 100

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


def _run_pipeline(
    tmp_path: Path,
    fixture_repo: Path,
    *,
    crit_per_iter: list[int],
    max_regression_retries: int = 2,
    max_total_iterations: int = 20,
):
    """Build all the handlers + orchestrator and return (result, writer_state, reviewer_state)."""
    writer_h, writer_state = _writer_handler()
    reviewer_h, reviewer_state = _counting_reviewer_handler(crit_per_iter)
    combined = _combined(
        _intent_handler(),
        _explorer_handler(),
        _consolidator_handler(),
        _approach_handler(),
        writer_h,
        reviewer_h,
    )
    orchestrator = _build_orchestrator(
        tmp_path,
        combined,
        max_regression_retries=max_regression_retries,
        max_total_iterations=max_total_iterations,
    )
    return orchestrator, writer_state, reviewer_state


# ============================================================================
# Test 1: regression fires → rewriter is re-invoked with extra_context
# ============================================================================


async def test_regression_triggers_retry(tmp_path, fixture_repo):
    """When iter 2 regresses vs iter 1, the orchestrator must re-invoke the
    rewriter with a non-empty ``extra_context`` carrying the regression
    feedback message.

    Scripted critical counts: [2, 5, 0] →
      * iter 1: 2 crit (fail) → rewrite #1 (normal, no extra_context).
      * iter 2: 5 crit (fail, REGRESSION 5>2) → rewrite #2 (regression
        retry, MUST have extra_context).
      * iter 3: 0 crit (pass) → loop exits.
    """
    orchestrator, writer_state, reviewer_state = _run_pipeline(
        tmp_path, fixture_repo, crit_per_iter=[2, 5, 0]
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)

    assert result.ok, "orchestrator should complete successfully"
    assert result.spec is not None

    # Exactly two rewriter calls — the post-iter-1 normal rewrite and the
    # post-iter-2 regression retry. (No further rewrite after iter 3 because
    # iter 3 is all_pass.)
    assert writer_state["rewrites"] == 2, (
        f"expected 2 rewriter calls, got {writer_state['rewrites']}"
    )
    rewriter_calls = writer_state["rewriter_calls"]

    # Call #1: normal rewrite after iter-1 review — NO regression context.
    call1_sys = rewriter_calls[0]["system"]
    assert REGRESSION_EXTRA_CONTEXT_HEADER not in call1_sys, (
        "first (normal) rewrite must NOT carry the REGRESSION CONTEXT block"
    )
    assert REGRESSION_FEEDBACK_PREFIX not in call1_sys

    # Call #2: regression retry after iter-2 review — MUST carry the
    # regression-context block AND the regression-feedback message text.
    call2_sys = rewriter_calls[1]["system"]
    assert REGRESSION_EXTRA_CONTEXT_HEADER in call2_sys, (
        "second (regression retry) rewrite must carry the REGRESSION "
        "CONTEXT system block — header missing from rewriter system prompt"
    )
    assert REGRESSION_FEEDBACK_PREFIX in call2_sys, (
        "second rewrite must include the regression-feedback prefix "
        "produced by regression_feedback_message()"
    )
    # The feedback message must include the actual before/after counts so
    # the rewriter knows WHAT regressed (critical+high: 2 → 5).
    assert "Critical issues: 2" in call2_sys
    assert "5" in call2_sys

    # iter-3 reviewer call advanced the reviewer-state idx to 3.
    assert reviewer_state["iter_idx"] == 3
    assert reviewer_state["flag_counts"] == [2, 5, 0]


# ============================================================================
# Test 2: regression retry is fed the BASELINE spec, not the regressed v2
# ============================================================================


async def test_regression_retry_uses_baseline_not_bad_v2(tmp_path, fixture_repo):
    """The regression-aware rewrite must be invoked with the LAST GOOD
    baseline spec as ``previous_spec`` — NOT the bad v2 spec.

    Each spec is tagged via a unique ``summary`` marker so we can detect
    which one was passed in:

    * spec_v1 (initial writer output) → ``WRITER_BASELINE_MARKER``.
    * spec_v2 (output of rewriter call #1) → ``_rewriter_output_marker(1)``.

    Same script as test 1 (``[2, 5, 0]``). After iter-2's regression, the
    rewriter call #2's system prompt's previous_spec section must contain
    the WRITER baseline marker, NOT the rewriter-output marker.
    """
    orchestrator, writer_state, _ = _run_pipeline(
        tmp_path, fixture_repo, crit_per_iter=[2, 5, 0]
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)

    assert result.ok
    assert writer_state["rewrites"] == 2
    call2_sys = writer_state["rewriter_calls"][1]["system"]

    bad_v2_marker = _rewriter_output_marker(1)
    assert WRITER_BASELINE_MARKER in call2_sys, (
        f"regression-retry rewrite must receive the iter-1 baseline spec "
        f"as previous_spec — marker '{WRITER_BASELINE_MARKER}' missing"
    )
    assert bad_v2_marker not in call2_sys, (
        f"regression-retry rewrite must NOT receive the iter-2 bad spec "
        f"as previous_spec — marker '{bad_v2_marker}' should be absent"
    )

    # Sanity: the FIRST (normal) rewriter call was fed the writer baseline
    # — that's the post-iter-1 rewrite where the only spec we've reviewed
    # so far is the writer output.
    call1_sys = writer_state["rewriter_calls"][0]["system"]
    assert WRITER_BASELINE_MARKER in call1_sys


# ============================================================================
# Test 3: regression budget exhausted → revert to baseline + needs_review,
# and the returned review is the LAST (bad) review
# ============================================================================


async def test_regression_budget_exhausted_reverts(tmp_path, fixture_repo):
    """When every retry regresses too, the orchestrator must:

    * stop the loop,
    * set ``result.spec`` to the baseline (last good) spec — NOT any of the
      regressed rewriter outputs,
    * mark ``spec.metadata.needs_review = True``,
    * return the LAST (bad) consolidated review so downstream callers can
      see why the loop bailed.

    Scripted critical counts: [2, 5, 8, 11] with ``max_regression_retries=2``.

    * iter 1: 2 crit. last_good=1, snapshots[1]=writer baseline. Rewrite #1.
    * iter 2: 5 crit (regression 5>2). Used=0<2 → retry #2 from baseline.
    * iter 3: 8 crit (regression 8>5). Used=1<2 → retry #3 from baseline.
    * iter 4: 11 crit (regression 11>8). Used=2, budget exhausted → revert.
    """
    orchestrator, writer_state, reviewer_state = _run_pipeline(
        tmp_path,
        fixture_repo,
        crit_per_iter=[2, 5, 8, 11],
        max_regression_retries=2,
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)

    assert result.ok
    assert result.spec is not None

    # The reverted spec must be the writer baseline (snapshots[1]) — its
    # marker is the only one that should appear in the final ``summary``.
    assert result.spec.summary == WRITER_BASELINE_MARKER, (
        f"expected revert to the writer baseline spec (marker "
        f"'{WRITER_BASELINE_MARKER}'), got summary='{result.spec.summary}'"
    )

    # The revert path must set needs_review so downstream callers know
    # the run did NOT converge cleanly.
    assert result.spec.metadata.needs_review is True

    # Three rewriter calls: normal #1, regression retries #2 and #3.
    # No #4 because iter-4 hit the budget-exhausted branch which RETURNS
    # before rewriting.
    assert writer_state["rewrites"] == 3, (
        f"expected exactly 3 rewriter calls (1 normal + 2 regression "
        f"retries), got {writer_state['rewrites']}"
    )
    # The two regression retries must each carry the REGRESSION CONTEXT
    # block.
    for i in (1, 2):
        sys_i = writer_state["rewriter_calls"][i]["system"]
        assert REGRESSION_EXTRA_CONTEXT_HEADER in sys_i
        assert REGRESSION_FEEDBACK_PREFIX in sys_i
        # And the baseline they were fed is still the writer baseline.
        assert WRITER_BASELINE_MARKER in sys_i

    # The returned consolidated review must be the LAST (bad iter-4) one
    # with 11 critical issues — the orchestrator returns ``review`` from
    # the budget-exhausted branch.
    assert result.consolidated_review is not None
    assert result.consolidated_review.critical_issues == 11, (
        f"expected last (bad) review to surface 11 critical issues, got "
        f"{result.consolidated_review.critical_issues}"
    )

    # Reviewer-state confirms we got through 4 iterations exactly.
    assert reviewer_state["flag_counts"] == [2, 5, 8, 11]


# ============================================================================
# Test 4: no regression → no retry, no extra_context, no revert
# ============================================================================


async def test_no_regression_no_retry(tmp_path, fixture_repo):
    """Normal converging run — iter 1 has issues, iter 2 fixes them. No
    rewriter call should carry the REGRESSION CONTEXT block, no revert,
    and ``needs_review`` should stay False.

    Scripted critical counts: [2, 0].
    """
    orchestrator, writer_state, reviewer_state = _run_pipeline(
        tmp_path, fixture_repo, crit_per_iter=[2, 0]
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)

    assert result.ok
    assert result.spec is not None
    assert result.spec.metadata.needs_review is False, (
        "clean convergence should not flip needs_review"
    )

    # Exactly one rewriter call (post-iter-1).
    assert writer_state["rewrites"] == 1
    sys_0 = writer_state["rewriter_calls"][0]["system"]
    assert REGRESSION_EXTRA_CONTEXT_HEADER not in sys_0, (
        "no rewrite should carry the REGRESSION CONTEXT block when there "
        "is no regression"
    )
    assert REGRESSION_FEEDBACK_PREFIX not in sys_0

    # The final spec must be the rewriter-1 output (iter-2 reviewed it and
    # said pass), NOT the writer baseline.
    expected_marker = _rewriter_output_marker(1)
    assert result.spec.summary == expected_marker, (
        f"final spec should be the iter-2 spec (rewriter call #1 output, "
        f"marker '{expected_marker}'), got '{result.spec.summary}'"
    )

    assert reviewer_state["flag_counts"] == [2, 0]


# ============================================================================
# Test 5: max_regression_retries setting is honored
# ============================================================================


async def test_max_regression_retries_setting_respected(tmp_path, fixture_repo):
    """With ``max_regression_retries=1``, only ONE regression retry should
    fire before the orchestrator bails out via revert.

    Scripted critical counts: [2, 5, 8].

    * iter 1: 2 crit. Rewrite #1.
    * iter 2: 5 crit (regression). Used=0<1 → retry #2 from baseline.
    * iter 3: 8 crit (regression). Used=1, budget exhausted → revert.
    """
    orchestrator, writer_state, reviewer_state = _run_pipeline(
        tmp_path,
        fixture_repo,
        crit_per_iter=[2, 5, 8],
        max_regression_retries=1,
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)

    assert result.ok
    assert result.spec is not None
    assert result.spec.metadata.needs_review is True

    # Exactly two rewriter calls: 1 normal + 1 regression retry.
    assert writer_state["rewrites"] == 2, (
        f"max_regression_retries=1 should permit exactly 1 retry; saw "
        f"{writer_state['rewrites']} total rewriter calls"
    )

    # Call #1: normal. Call #2: regression-aware retry. No call #3 because
    # budget was exhausted before any further rewrite.
    sys_0 = writer_state["rewriter_calls"][0]["system"]
    sys_1 = writer_state["rewriter_calls"][1]["system"]
    assert REGRESSION_EXTRA_CONTEXT_HEADER not in sys_0
    assert REGRESSION_EXTRA_CONTEXT_HEADER in sys_1
    assert REGRESSION_FEEDBACK_PREFIX in sys_1

    # Revert to baseline + last bad review returned.
    assert result.spec.summary == WRITER_BASELINE_MARKER
    assert result.consolidated_review is not None
    assert result.consolidated_review.critical_issues == 8

    assert reviewer_state["flag_counts"] == [2, 5, 8]


# ============================================================================
# Test 6: intermediate improvement updates the revert baseline
# ============================================================================


async def test_intermediate_improvement_updates_last_good(tmp_path, fixture_repo):
    """If iter 2 IMPROVED on iter 1 (5 → 3 critical), the regression
    baseline must move forward to iter 2's spec, NOT stay at iter 1's
    writer baseline. The subsequent regression at iter 3 (3 → 6) must
    therefore replay from the iter-2 spec.

    Scripted critical counts: [5, 3, 6, 0].

    * iter 1: 5 crit. last_good=1, snapshots[1] = writer baseline. Rewrite #1.
    * iter 2: 3 crit (improved 3<5). last_good=2, snapshots[2] = rewrite #1
      output. Rewrite #2.
    * iter 3: 6 crit (regression 6>3). Retry #3 from snapshots[2]
      (iter-2 spec), WITH extra_context.
    * iter 4: 0 crit (pass) → loop exits.
    """
    orchestrator, writer_state, reviewer_state = _run_pipeline(
        tmp_path, fixture_repo, crit_per_iter=[5, 3, 6, 0]
    )
    result = await orchestrator.run("Add comments to product", fixture_repo)

    assert result.ok
    assert result.spec is not None

    # Three rewriter calls — #1 after iter 1, #2 after iter 2, #3
    # regression-retry after iter 3. (No #4 because iter 4 is all_pass.)
    assert writer_state["rewrites"] == 3, (
        f"expected 3 rewriter calls, got {writer_state['rewrites']}"
    )

    sys_0, sys_1, sys_2 = (
        writer_state["rewriter_calls"][0]["system"],
        writer_state["rewriter_calls"][1]["system"],
        writer_state["rewriter_calls"][2]["system"],
    )

    # The first two rewrites are normal (no extra_context).
    assert REGRESSION_EXTRA_CONTEXT_HEADER not in sys_0
    assert REGRESSION_EXTRA_CONTEXT_HEADER not in sys_1
    # The third is the regression retry — extra_context present.
    assert REGRESSION_EXTRA_CONTEXT_HEADER in sys_2
    assert REGRESSION_FEEDBACK_PREFIX in sys_2

    # CRITICAL: the third (regression retry) rewriter call must receive
    # the iter-2 spec (= output of rewriter call #1, marker
    # `_rewriter_output_marker(1)`) as previous_spec — NOT the writer
    # baseline (which would mean the baseline never advanced).
    iter2_baseline_marker = _rewriter_output_marker(1)
    assert iter2_baseline_marker in sys_2, (
        f"regression retry must replay from iter-2 (the most-recent "
        f"IMPROVED baseline, marker '{iter2_baseline_marker}'), but its "
        f"marker is missing from the rewriter system prompt"
    )
    assert WRITER_BASELINE_MARKER not in sys_2, (
        "regression retry must NOT fall back to the writer-iter-1 "
        "baseline when an intermediate improvement (iter 2) exists — "
        "the writer baseline marker must be absent from the retry's "
        "previous_spec slot"
    )

    # And we delivered iter 4 with all_pass; no revert, no needs_review.
    assert result.spec.metadata.needs_review is False
    # iter-4 reviewed spec = output of regression-retry rewrite (#3).
    assert result.spec.summary == _rewriter_output_marker(3)

    assert reviewer_state["flag_counts"] == [5, 3, 6, 0]
