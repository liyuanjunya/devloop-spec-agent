"""End-to-end integration tests for Sprint C — C1: the 5th adversarial
red-team reviewer.

These tests drive the whole orchestrator pipeline against the
``sample_repo`` fixture with a deterministic :class:`MockProvider`, then
count how many distinct reviewer agents the orchestrator dispatched by
inspecting the provider call log. Each reviewer angle uses a unique
prompt header (e.g. ``# Architecture Reviewer``, ``# Adversarial
Red-Team Reviewer``), so the system prompts arriving at the provider
unambiguously identify the angle. By controlling the confirmed intent
(via the intent-handler mock) and the ``force_adversarial`` /
``disable_adversarial`` flags we exercise every precedence path through
``run_review_stage``.

Boundary conditions covered:

* security/auth/external_integration/payment scope triggers adversarial
* plain backend scope does NOT pay the extra reviewer cost
* ``force_adversarial`` overrides the negative heuristic
* ``disable_adversarial`` overrides positive heuristic
* adversarial findings flow into the consolidated review and the
  rewriter's ``all_issues`` JSON payload
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
# Reviewer marker → angle identification
# ---------------------------------------------------------------------------
# Each reviewer's prompt header is unique (the `prompts/reviewer/*.md`
# files start with `# <Angle> Reviewer`). We match against the rendered
# system prompt that arrives at the mock provider so we can count how
# many distinct angles were dispatched per run.
_REVIEWER_MARKERS: dict[str, str] = {
    "architecture": "# architecture reviewer",
    "completeness": "# completeness reviewer",
    "executability": "# executability reviewer",
    "consistency": "# consistency reviewer",
    "adversarial": "# adversarial red-team reviewer",
}


def _collect_reviewer_angles(provider: MockProvider) -> set[str]:
    """Return the set of reviewer angles invoked on ``provider``.

    Filters the provider's call log to entries whose system prompt
    matches one of the reviewer headers AND whose system prompt is
    NOT a meta-reviewer (the meta-reviewer also contains the word
    "reviewer" but uses a different unique header).
    """
    angles: set[str] = set()
    for call in provider.calls:
        sys_head = (call.get("system_head") or "").lower()
        # Meta-reviewer header: "you are the **meta-reviewer**". Skip it
        # so we don't double-count B4's consolidator.
        if "meta-reviewer" in sys_head:
            continue
        for angle, marker in _REVIEWER_MARKERS.items():
            if marker in sys_head:
                angles.add(angle)
    return angles


# ---------------------------------------------------------------------------
# Spec fixture matching sample_repo line counts (mirrors the pattern used
# by tests/integration/test_orchestrator_meta_review.py)
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
# Stage handlers (mirrors tests/integration/test_review_loop.py patterns)
# ---------------------------------------------------------------------------


def _make_intent_handler(*, primary: str, scope: list[str], intent_type: str = "add_feature"):
    """Return an intent-stage handler that injects a specific scope/primary
    so we can drive the adversarial heuristic from the test."""

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
                        "primary": primary,
                        "intent_type": intent_type,
                        "scope": scope,
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


def _make_explorer_handler():
    """Trivial explorer handler — every perspective marks one file relevant and exits.

    Matches the pattern in test_review_loop.py / test_orchestrator_meta_review.py
    and is robust against the orchestrator firing additional perspectives
    (security / performance) when the auto-selector activates them.
    """
    state = {"step": {}}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "**your perspective**" not in sl:
            return None
        perspective = None
        for p in ["data", "api", "ui", "test", "history", "security", "performance"]:
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


def _make_consolidator_handler():
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


def _make_approach_handler():
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


def _make_writer_handler(*, rewrites_capture: list[str] | None = None):
    """Default writer handler — always emits the same valid spec and (when
    given) records each rewriter system prompt for later assertions."""
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl:
            state["rewrites"] += 1
            if rewrites_capture is not None:
                rewrites_capture.append(system)
            return make_json_response(_sample_spec(iter_n=1 + state["rewrites"]))
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(_sample_spec(iter_n=1))
        return None

    return handler, state


def _make_reviewer_pass_handler():
    """Every reviewer angle immediately verdicts pass. Used when we just
    want to count which angles were invoked without driving any rewrites."""

    def handler(model, system, messages, tools, response_format):
        # Match any of the angle prompts (their headers contain "Reviewer")
        # but NOT the meta-reviewer (skipped explicitly).
        sl = system.lower()
        if "meta-reviewer" in sl:
            return None
        if " reviewer" in sl and "review the spec" in (messages[-1].content.lower() if messages else ""):
            return make_text_response("No issues found.\nVERDICT: pass")
        # Defensive: still match plain reviewer prompts if last message check fails
        if any(marker in sl for marker in _REVIEWER_MARKERS.values()):
            return make_text_response("No issues found.\nVERDICT: pass")
        return None

    return handler


def _make_adversarial_findings_reviewer_handler(state: dict):
    """Reviewer handler used for test 6.

    Each reviewer angle (architecture, completeness, executability,
    consistency) passes immediately. The adversarial angle first flags
    a critical issue via ``flag_issue``, then on the next call emits
    VERDICT: fail. After one successful rewrite, every reviewer (including
    adversarial) passes so the loop terminates and the orchestrator returns.
    """
    state.setdefault("adv_calls", 0)
    state.setdefault("non_adv_calls", 0)
    state.setdefault("iteration_after_rewrite", False)

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "meta-reviewer" in sl:
            return None
        is_adversarial = _REVIEWER_MARKERS["adversarial"] in sl
        is_reviewer = any(m in sl for m in _REVIEWER_MARKERS.values())
        if not is_reviewer:
            return None

        if is_adversarial:
            state["adv_calls"] += 1
            # On iteration 1, flag once then verdict fail; on subsequent
            # iterations, pass.
            if not state["iteration_after_rewrite"]:
                if not _has_flagged_in_messages(messages):
                    return make_tool_call_response(
                        name="flag_issue",
                        arguments={
                            "severity": "critical",
                            "location": "FR-001",
                            "description": "Rate-limit ordering allows quota DoS",
                            "evidence": "spec processes rate-limit AFTER input validation",
                            "suggested_action": "Reorder to rate-limit BEFORE validation",
                        },
                    )
                return make_text_response(
                    "Found a critical adversarial issue.\nVERDICT: fail"
                )
            return make_text_response("Adversarial review clean.\nVERDICT: pass")

        state["non_adv_calls"] += 1
        return make_text_response("Base review clean.\nVERDICT: pass")

    return handler


def _has_flagged_in_messages(messages) -> bool:
    """True if the conversation already includes a flag_issue tool result."""
    for m in messages:
        if getattr(m, "role", None) == "tool" and getattr(m, "name", None) == "flag_issue":
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


# ---------------------------------------------------------------------------
# Orchestrator builder — multi-reviewer ON so all 4 base angles run by
# default; the adversarial 5th angle is layered on by the selector under
# test (or forced via settings).
# ---------------------------------------------------------------------------


def _build_orchestrator(
    tmp_path: Path,
    handler,
    *,
    force_adversarial: bool = False,
    disable_adversarial: bool = False,
    max_total_iterations: int = 3,
):
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)

    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = True  # Need all 4 base angles
    # Keep meta-reviewer OFF so its system prompt doesn't pollute counts
    # and so the test doesn't have to script a meta-reviewer response.
    settings.orchestrator.enable_meta_reviewer = False
    settings.orchestrator.max_total_iterations = max_total_iterations

    settings.reviewer.force_adversarial = force_adversarial
    settings.reviewer.disable_adversarial = disable_adversarial
    # Run reviewers sequentially so call-order assertions are deterministic
    # (parallel reviewer launches don't change the counts but make logs noisier).
    settings.reviewer.parallel = False

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


# ===========================================================================
# Test 1: security scope → 5 reviewers (base 4 + adversarial)
# ===========================================================================


async def test_security_scope_runs_5_reviewers(tmp_path, fixture_repo):
    """``intent.scope = ['security']`` MUST trigger the 5th adversarial
    reviewer in addition to the 4 base angles."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(primary="Add CSRF protection", scope=["security"]),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    result = await orchestrator.run("Add CSRF protection middleware", fixture_repo)
    assert result.ok, f"orchestrator failed: {result.reason}"

    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert angles == {
        "architecture",
        "completeness",
        "executability",
        "consistency",
        "adversarial",
    }, (
        f"expected all 5 reviewer angles to fire for security scope, got {sorted(angles)}"
    )


# ===========================================================================
# Test 2: external_integration scope → 5 reviewers
# ===========================================================================


async def test_external_integration_runs_5_reviewers(tmp_path, fixture_repo):
    """``intent.scope = ['external_integration']`` is another adversarial-
    trigger scope (Stripe webhooks, third-party APIs, etc.)."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Wire up the third-party billing webhook",
            scope=["backend", "external_integration"],
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    result = await orchestrator.run(
        "Integrate the third-party billing webhook", fixture_repo
    )
    assert result.ok

    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert "adversarial" in angles, (
        f"external_integration must trigger adversarial; got angles={sorted(angles)}"
    )
    assert angles == {
        "architecture",
        "completeness",
        "executability",
        "consistency",
        "adversarial",
    }


# ===========================================================================
# Test 3: plain backend → ONLY 4 reviewers (no adversarial)
# ===========================================================================


async def test_plain_backend_runs_4_reviewers(tmp_path, fixture_repo):
    """A boring backend feature with no security keywords must NOT pay the
    extra LLM cost for adversarial review."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Add a hello-world endpoint", scope=["backend"]
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    result = await orchestrator.run("Add a hello-world endpoint", fixture_repo)
    assert result.ok

    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert "adversarial" not in angles, (
        f"plain backend must NOT trigger adversarial; got angles={sorted(angles)}"
    )
    assert angles == {
        "architecture",
        "completeness",
        "executability",
        "consistency",
    }


# ===========================================================================
# Test 4: scope=['backend'] + force_adversarial=True → 5 reviewers
# ===========================================================================


async def test_force_adversarial_override_works(tmp_path, fixture_repo):
    """Even when the heuristic would skip adversarial,
    ``settings.reviewer.force_adversarial=True`` must enable it."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Add a hello-world endpoint", scope=["backend"]
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(
        tmp_path, handler, force_adversarial=True
    )

    result = await orchestrator.run("Add a hello-world endpoint", fixture_repo)
    assert result.ok

    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert "adversarial" in angles, (
        "force_adversarial=True must enable adversarial even for plain backend; "
        f"got angles={sorted(angles)}"
    )
    assert angles == {
        "architecture",
        "completeness",
        "executability",
        "consistency",
        "adversarial",
    }


# ===========================================================================
# Test 5: scope=['security'] + disable_adversarial=True → 4 reviewers
# ===========================================================================


async def test_disable_adversarial_override_works(tmp_path, fixture_repo):
    """``settings.reviewer.disable_adversarial=True`` is the hard kill
    switch — it wins over the positive heuristic and even over
    ``force_adversarial`` (precedence documented in stage.py)."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Add CSRF protection", scope=["security"]
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(
        tmp_path, handler, disable_adversarial=True
    )

    result = await orchestrator.run("Add CSRF protection middleware", fixture_repo)
    assert result.ok

    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert "adversarial" not in angles, (
        "disable_adversarial=True must veto adversarial even for security scope; "
        f"got angles={sorted(angles)}"
    )
    assert angles == {
        "architecture",
        "completeness",
        "executability",
        "consistency",
    }


# ===========================================================================
# Test 6: adversarial issues flow into the consolidated review AND the
# rewriter's all_issues payload
# ===========================================================================


async def test_adversarial_issues_appear_in_consolidated_review(
    tmp_path, fixture_repo
):
    """When the adversarial reviewer flags a critical issue, that issue
    MUST appear in ``ConsolidatedReview.reviews`` AND the rewriter's
    system prompt must include it in ``all_issues`` (JSON) so the next
    rewrite has a chance to fix it.

    Verifies the end-to-end flow:

    1. Adversarial reviewer fires (security scope)
    2. It calls ``flag_issue`` with reviewer_type=adversarial implicit
    3. The orchestrator persists the issue into ConsolidatedReview
    4. The rewriter sees the issue (reviewer_type='adversarial') in its
       system prompt
    """
    rewriter_prompts: list[str] = []
    writer_handler, _ws = _make_writer_handler(rewrites_capture=rewriter_prompts)
    reviewer_state: dict = {}
    handler = _combined_handler(
        _make_intent_handler(
            primary="Charge a credit card", scope=["payment"]
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_adversarial_findings_reviewer_handler(reviewer_state),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(
        tmp_path, handler, max_total_iterations=4
    )

    # Reviewer_state must be mutated by the handler when iter > 1; flip
    # the flag right before each iteration via a small wrapper. The
    # mock reviewer uses ``state["iteration_after_rewrite"]`` to decide
    # whether to flag or pass; we set it True after the first rewrite by
    # snapshotting how many writes the writer has performed.
    # The simplest approach: rely on the writer-state — once a rewrite
    # has happened, the reviewer should pass everything.
    # We implement that here by patching the reviewer state inline.

    # Wrap the existing handler so we can flip the bit after any rewrite.
    original = handler

    def wrapped(model, system, messages, tools, response_format):
        # If the writer state shows we've done >=1 rewrite, mark
        # reviewer "iteration after rewrite" so adversarial returns pass
        # next call. We read from the captured writer prompts list.
        if len(rewriter_prompts) >= 1:
            reviewer_state["iteration_after_rewrite"] = True
        return original(model, system, messages, tools, response_format)

    # Re-bind handler on both providers
    a_prov._handler = wrapped  # type: ignore[attr-defined]
    o_prov._handler = wrapped  # type: ignore[attr-defined]

    result = await orchestrator.run(
        "Add payment charging via Stripe", fixture_repo
    )
    assert result.ok, f"orchestrator failed: {result.reason}"

    # --- 1. Adversarial reviewer was invoked ---
    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert "adversarial" in angles, (
        f"adversarial reviewer must fire for payment scope; got {sorted(angles)}"
    )

    # --- 2. The consolidated review on disk records the adversarial issue
    workspace = result.workspace
    assert workspace is not None
    iter1_consolidated = workspace / "spec_iterations" / "review_v1_consolidated.json"
    assert iter1_consolidated.is_file(), (
        f"missing consolidated review artifact at {iter1_consolidated}"
    )
    import json as _json

    consolidated = _json.loads(iter1_consolidated.read_text(encoding="utf-8"))
    adversarial_reviews = [
        r for r in consolidated["reviews"] if r["reviewer_type"] == "adversarial"
    ]
    assert adversarial_reviews, (
        "ConsolidatedReview is missing an adversarial reviewer entry"
    )
    adv_issues = adversarial_reviews[0]["issues"]
    assert adv_issues, "Adversarial reviewer entry has no issues"
    assert any(
        i["reviewer_type"] == "adversarial" and i["severity"] == "critical"
        for i in adv_issues
    ), f"expected an adversarial critical issue; got {adv_issues}"
    # Concrete signal that this is the issue our mock raised
    assert any(
        "rate-limit" in i["description"].lower() for i in adv_issues
    ), f"adversarial issue payload not propagated: {adv_issues}"

    # --- 3. The rewriter saw the adversarial issue in all_issues ---
    assert rewriter_prompts, (
        "expected the rewriter to be invoked at least once when a critical "
        "issue was flagged"
    )
    first_rewriter_sys = rewriter_prompts[0]
    assert '"reviewer_type": "adversarial"' in first_rewriter_sys, (
        "rewriter system prompt must carry the adversarial issue in all_issues"
    )
    assert "rate-limit" in first_rewriter_sys.lower(), (
        "rewriter system prompt must carry the adversarial issue text"
    )


# ===========================================================================
# Optional belt-and-braces: parametrized scope coverage
# ===========================================================================


@pytest.mark.parametrize("scope", [["auth"], ["security"], ["payment"], ["external_integration"]])
async def test_all_adversarial_scopes_trigger_5_reviewers(
    tmp_path, fixture_repo, scope
):
    """Belt-and-braces: every documented adversarial-scope trigger fires
    the 5th reviewer end-to-end. Complements tests 1+2 (which pin only
    two of the four)."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(primary="some feature", scope=scope),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)
    result = await orchestrator.run(
        "Add a generic " + " ".join(scope) + " feature", fixture_repo
    )
    assert result.ok
    angles = _collect_reviewer_angles(a_prov) | _collect_reviewer_angles(o_prov)
    assert "adversarial" in angles
