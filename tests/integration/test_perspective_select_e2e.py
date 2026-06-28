"""End-to-end integration tests for Sprint C — C3: intent-driven
perspective auto-selection.

The orchestrator calls
:func:`devloop.spec_phase.agents.explorer.perspective_selector.select_perspectives`
after Stage 2 (intent) confirms an intent, and stores the result on
``ctx.active_perspectives``. :func:`run_exploration_stage` then iterates
that list to fire one explorer per perspective. These tests drive the
full pipeline against the ``sample_repo`` fixture with a deterministic
:class:`MockProvider` and spy on ``run_exploration_stage`` to capture the
exact ``active_perspectives`` the orchestrator computed for each intent.

Boundary conditions covered:

* ``add_feature`` + ``scope=['backend']`` → no ``ui``
* ``add_feature`` + ``scope=['backend','ui']`` → ``ui`` included
* ``intent_type=perf_opt`` → ``performance`` included
* ``intent.primary`` keyword (``"upload"``) → ``security`` included
* explicit ``settings.explorer.perspectives`` configuration → wins
  over auto-selection (returns the user's list verbatim)
"""

from __future__ import annotations

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
# Spec fixture (matches sample_repo file line counts)
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
# Stage handlers
# ---------------------------------------------------------------------------


def _make_intent_handler(
    *,
    primary: str,
    scope: list[str],
    intent_type: str = "add_feature",
):
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
    """Generic explorer handler that handles any perspective (data, api, ui,
    test, history, security, performance) — important because the auto-
    selector may activate security / performance, and the mock must answer."""
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
                "consolidated_conventions": ["pydantic v2"],
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


def _make_writer_handler():
    state = {"writes": 0, "rewrites": 0}

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "spec rewriter" in sl:
            state["rewrites"] += 1
            return make_json_response(_sample_spec(iter_n=1 + state["rewrites"]))
        if "spec writer" in sl:
            state["writes"] += 1
            return make_json_response(_sample_spec(iter_n=1))
        return None

    return handler, state


def _make_reviewer_pass_handler():
    """All reviewers pass immediately so the run terminates after iter 1."""

    def handler(model, system, messages, tools, response_format):
        sl = system.lower()
        if "meta-reviewer" in sl:
            return None
        # Match any reviewer prompt header
        if "reviewer" in sl and ("# architecture reviewer" in sl
                                 or "# completeness reviewer" in sl
                                 or "# executability reviewer" in sl
                                 or "# consistency reviewer" in sl
                                 or "# adversarial red-team reviewer" in sl):
            return make_text_response("No issues found.\nVERDICT: pass")
        return None

    return handler


def _combined_handler(*handlers):
    def handler(*args, **kwargs):
        for h in handlers:
            r = h(*args, **kwargs)
            if r is not None:
                return r
        return make_text_response("(unhandled)")

    return handler


# ---------------------------------------------------------------------------
# Orchestrator builder + spy on run_exploration_stage
# ---------------------------------------------------------------------------


def _build_orchestrator(
    tmp_path: Path,
    handler,
    *,
    explicit_perspectives: list[str] | None = None,
    max_total_iterations: int = 3,
):
    """Build an orchestrator. When ``explicit_perspectives`` is given, that
    list replaces ``settings.explorer.perspectives`` so the orchestrator's
    ``_resolve_active_perspectives`` treats it as an explicit user override
    (matches the contract documented in
    :func:`SpecOrchestrator._resolve_active_perspectives`)."""
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)

    settings.orchestrator.enable_multi_view_explorer = True
    settings.orchestrator.enable_multi_candidate_approach = True
    settings.orchestrator.enable_multi_reviewer = False  # single reviewer is enough
    settings.orchestrator.enable_meta_reviewer = False
    settings.orchestrator.max_total_iterations = max_total_iterations

    if explicit_perspectives is not None:
        settings.explorer.perspectives = explicit_perspectives  # type: ignore[assignment]

    # Disable the explorer cache so each test sees a fresh dispatch — the
    # spy MUST observe a real call to run_exploration_stage, not a cached
    # return value.
    settings.explorer.use_cache = False
    # Disable targeted re-exploration (B2) so the spy sees only the
    # first-pass run and active_perspectives isn't mutated by re-explorers.
    settings.explorer.max_targeted_reexplorations = 0

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


class _ExplorationSpy:
    """Capture-only spy around :func:`run_exploration_stage`.

    Installed via monkey-patching the orchestrator module's binding so the
    spy sees every dispatch with the active perspective list the
    orchestrator selected. Wraps and re-invokes the real function so the
    rest of the pipeline still runs.
    """

    def __init__(self):
        self.calls: list[list[str]] = []
        self._original = None

    def __enter__(self):
        import devloop.spec_phase.orchestrator as orch_mod

        self._original = orch_mod.run_exploration_stage

        async def spy(ctx):
            # Snapshot active_perspectives at dispatch time
            active = list(ctx.active_perspectives or [])
            self.calls.append(active)
            return await self._original(ctx)  # type: ignore[misc]

        orch_mod.run_exploration_stage = spy  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type, exc, tb):
        import devloop.spec_phase.orchestrator as orch_mod

        if self._original is not None:
            orch_mod.run_exploration_stage = self._original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Provider-call counting (defensive sanity check that the spy result and
# the actual provider dispatches agree — i.e. only the recorded
# perspectives were actually launched).
# ---------------------------------------------------------------------------


def _perspectives_launched_on_providers(*providers: MockProvider) -> set[str]:
    """Return the set of explorer perspectives whose system prompt arrived
    at any of the given providers.

    Identifies perspectives by their unique prompt header (e.g.
    ``# Explorer — UI Perspective``) which appears in the first 300
    characters of the rendered system prompt that ``MockProvider``
    captures into its call log. We cannot rely on the deeper
    ``**Your perspective**: <name>`` marker because that lives in the
    base prompt fragment which is appended later in the rendered
    template and may fall outside the 300-char ``system_head`` window.
    """
    headers: dict[str, str] = {
        "data": "# explorer — data perspective",
        "api": "# explorer — api perspective",
        "ui": "# explorer — ui perspective",
        "test": "# explorer — test perspective",
        "history": "# explorer — history perspective",
        "security": "# explorer — security perspective",
        "performance": "# explorer — performance perspective",
    }
    out: set[str] = set()
    for prov in providers:
        for call in prov.calls:
            sh = (call.get("system_head") or "").lower()
            for perspective, marker in headers.items():
                if marker in sh:
                    out.add(perspective)
    return out


# ===========================================================================
# Test 1: add_feature + scope=['backend'] → no 'ui'
# ===========================================================================


async def test_add_feature_backend_skips_ui(tmp_path, fixture_repo):
    """A backend-only feature must NOT pay the cost of the UI explorer."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Add a small backend feature", scope=["backend"]
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    with _ExplorationSpy() as spy:
        result = await orchestrator.run(
            "Add a small backend feature", fixture_repo
        )
    assert result.ok, f"orchestrator failed: {result.reason}"

    assert spy.calls, "run_exploration_stage was never invoked"
    active = spy.calls[0]
    assert "ui" not in active, (
        f"backend-only intent must NOT include 'ui' perspective; got {active}"
    )
    # The always-included perspectives must still be present
    for required in ("data", "api", "test", "history"):
        assert required in active, f"missing always-included perspective {required}"
    # Defensive: the actual provider dispatches match the spy capture
    launched = _perspectives_launched_on_providers(a_prov, o_prov)
    assert "ui" not in launched, (
        f"no explorer system prompt for 'ui' should reach the provider; "
        f"launched={sorted(launched)}"
    )


# ===========================================================================
# Test 2: add_feature + scope=['backend','ui'] → 'ui' included
# ===========================================================================


async def test_add_feature_with_ui_scope_includes_ui(tmp_path, fixture_repo):
    """Explicit ``ui`` in scope must opt the UI explorer back in."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Add a settings page", scope=["backend", "ui"]
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    with _ExplorationSpy() as spy:
        result = await orchestrator.run("Add a settings page", fixture_repo)
    assert result.ok

    assert spy.calls
    active = spy.calls[0]
    assert "ui" in active, (
        f"scope including 'ui' must enable the UI explorer; got {active}"
    )
    # Defensive: confirm the UI explorer system prompt actually reached
    # a provider this run.
    launched = _perspectives_launched_on_providers(a_prov, o_prov)
    assert "ui" in launched


# ===========================================================================
# Test 3: intent_type=perf_opt → 'performance' included
# ===========================================================================


async def test_perf_opt_includes_performance(tmp_path, fixture_repo):
    """``intent_type=perf_opt`` alone (no keyword match) must enable the
    performance explorer."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Make the dashboard a bit better",
            scope=["backend"],
            intent_type="perf_opt",
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    with _ExplorationSpy() as spy:
        result = await orchestrator.run(
            "Optimize the dashboard speed", fixture_repo
        )
    assert result.ok

    assert spy.calls
    active = spy.calls[0]
    assert "performance" in active, (
        f"perf_opt intent_type must enable the performance explorer; got {active}"
    )
    launched = _perspectives_launched_on_providers(a_prov, o_prov)
    assert "performance" in launched


# ===========================================================================
# Test 4: security keyword ('upload') in primary → 'security' included
# ===========================================================================


async def test_security_keyword_in_primary_includes_security(
    tmp_path, fixture_repo
):
    """A primary-text keyword (here: ``upload``) must enable the security
    explorer even when scope is plain backend."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Add image upload for user avatars",
            scope=["backend"],
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(tmp_path, handler)

    with _ExplorationSpy() as spy:
        result = await orchestrator.run(
            "Add image upload for user avatars", fixture_repo
        )
    assert result.ok

    assert spy.calls
    active = spy.calls[0]
    assert "security" in active, (
        f"'upload' keyword in primary must enable security explorer; got {active}"
    )
    launched = _perspectives_launched_on_providers(a_prov, o_prov)
    assert "security" in launched


# ===========================================================================
# Test 5: explicit settings.explorer.perspectives → only those run
# ===========================================================================


async def test_explicit_settings_override_wins(tmp_path, fixture_repo):
    """When the user sets ``settings.explorer.perspectives = ['data','api']``
    (a non-default custom list), the orchestrator must honor it verbatim
    and skip auto-selection — even though the intent says ``perf_opt``
    with a UI scope (which would normally trigger ``performance`` and
    ``ui``)."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Optimize the image upload form for lower latency",
            scope=["ui", "backend"],
            intent_type="perf_opt",
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    # Pass an explicit custom list — anything that differs from
    # DEFAULT_EXPLORER_PERSPECTIVES is treated as an explicit user
    # configuration by SpecOrchestrator._resolve_active_perspectives.
    orchestrator, _gw, a_prov, o_prov = _build_orchestrator(
        tmp_path, handler, explicit_perspectives=["data", "api"]
    )

    with _ExplorationSpy() as spy:
        result = await orchestrator.run(
            "Optimize the image upload form", fixture_repo
        )
    assert result.ok

    assert spy.calls
    active = spy.calls[0]
    assert active == ["data", "api"], (
        f"explicit settings.explorer.perspectives must win over auto-selection; "
        f"got {active}"
    )
    # And critically: none of the auto-selection triggers leaked in,
    # nor were the always-included perspectives bolted back on.
    for forbidden in ("ui", "security", "performance", "test", "history"):
        assert forbidden not in active, (
            f"explicit override must NOT auto-add '{forbidden}'; got {active}"
        )
    # Confirm at the provider level too — no explorer for the
    # unconfigured perspectives ran.
    launched = _perspectives_launched_on_providers(a_prov, o_prov)
    assert launched == {"data", "api"}, (
        f"only the explicitly configured explorers should have dispatched; "
        f"launched={sorted(launched)}"
    )


# ===========================================================================
# Extra coverage: combined triggers (security + performance + ui all on)
# ===========================================================================


async def test_combined_intent_triggers_all_optional_perspectives(
    tmp_path, fixture_repo
):
    """A UI feature that mentions upload AND is perf_opt should activate
    ui + security + performance simultaneously (canonical order
    preserved)."""
    writer_handler, _ws = _make_writer_handler()
    handler = _combined_handler(
        _make_intent_handler(
            primary="Optimize the image upload form for lower latency",
            scope=["ui", "backend"],
            intent_type="perf_opt",
        ),
        _make_explorer_handler(),
        _make_consolidator_handler(),
        _make_approach_handler(),
        writer_handler,
        _make_reviewer_pass_handler(),
    )
    orchestrator, _gw, _a_prov, _o_prov = _build_orchestrator(tmp_path, handler)

    with _ExplorationSpy() as spy:
        result = await orchestrator.run(
            "Optimize the image upload form for lower latency", fixture_repo
        )
    assert result.ok

    assert spy.calls
    active = spy.calls[0]
    for required in ("data", "api", "ui", "test", "history", "security", "performance"):
        assert required in active, (
            f"combined trigger intent missing '{required}'; got {active}"
        )
    # Canonical ordering is documented behaviour (perspective_selector.py)
    canonical = ["data", "api", "ui", "test", "history", "security", "performance"]
    expected = [p for p in canonical if p in active]
    assert active == expected, (
        f"active_perspectives must follow the canonical order; got {active}"
    )


