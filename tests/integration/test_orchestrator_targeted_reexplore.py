"""Integration test for B2: orchestrator wires targeted re-exploration
after the first-pass consolidator surfaces coverage gaps.

The test:

1. Builds a synthetic :class:`ConsolidatedExploration` that contains a
   known ``singleton_critical`` gap — exactly one perspective (``api``)
   surfaced ``mealie/routes/explore/controller_public_recipes.py`` at
   ``importance="critical"``.
2. Monkeypatches :func:`devloop.spec_phase.orchestrator.run_targeted_reexploration`
   with a stub that returns a confirming :class:`Perspective` (labelled
   with a *different* perspective_type so the cross-perspective signal
   is real).
3. Invokes :meth:`SpecOrchestrator._run_targeted_reexplorations` directly.
4. Asserts the resulting exploration has the artifact mentioned by ≥ 2
   perspectives and that the consolidated artifact set was merged.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from devloop.cache import CacheBackend
from devloop.config import load_settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.orchestrator import SpecOrchestrator
from devloop.spec_phase.repo_skeleton import RepoSkeletonBuilder
from devloop.spec_phase.schemas import (
    ConfirmedIntent,
    Conflict,
    ConsolidatedExploration,
    Perspective,
    RelevantArtifact,
)
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import MockProvider, make_text_response

# Path the singleton-critical artifact lives at — same shape as the real
# Mealie 6-case failure that motivated B2.
SECRET_PATH = "mealie/routes/explore/controller_public_recipes.py"


def _artifact(
    path: str,
    *,
    importance: str = "critical",
    symbols: list[str] | None = None,
    reason: str = "Important for the feature",
) -> RelevantArtifact:
    return RelevantArtifact(
        path=path,
        symbols=symbols or [],
        line_ranges=[(1, 30)],
        importance=importance,  # type: ignore[arg-type]
        reason=reason,
    )


def _make_synthetic_exploration() -> ConsolidatedExploration:
    """Build an exploration whose ONLY singleton_critical is SECRET_PATH.

    Three "well-covered" artifacts (covered by 2+ perspectives at importance
    'critical') anchor the artifact map so the detector sees a normal
    cross-perspective picture; the test rebroadcasts SECRET_PATH from only
    the ``api`` perspective so it is the sole singleton_critical gap.
    """
    shared_a = "app/models/recipe.py"
    shared_b = "app/models/user.py"
    shared_c = "app/api/routes_recipes.py"
    return ConsolidatedExploration(
        perspectives=[
            Perspective(
                perspective_type="data",
                relevant_artifacts=[
                    _artifact(shared_a, reason="data model"),
                    _artifact(shared_b, reason="data model"),
                ],
            ),
            Perspective(
                perspective_type="api",
                relevant_artifacts=[
                    _artifact(shared_c, reason="api routes"),
                    _artifact(shared_a, reason="api uses recipe model"),
                    _artifact(
                        SECRET_PATH,
                        symbols=["PublicRecipesController"],
                        reason="Public unauthenticated recipe access",
                    ),
                ],
            ),
            Perspective(
                perspective_type="ui",
                relevant_artifacts=[
                    _artifact(shared_c, reason="ui calls these routes"),
                    _artifact(shared_b, reason="ui shows user"),
                ],
            ),
            Perspective(
                perspective_type="test",
                relevant_artifacts=[
                    _artifact(shared_a, reason="recipe model tests"),
                    _artifact(shared_c, reason="route tests"),
                ],
            ),
            Perspective(
                perspective_type="history",
                relevant_artifacts=[
                    _artifact(shared_a, reason="recipe model history"),
                    _artifact(shared_b, reason="user model history"),
                ],
            ),
        ],
        conflicts=[
            Conflict(
                perspectives_involved=["data", "api"],
                description="agreed",
                resolution_suggestion="Both align on SQLAlchemy 2.0 style",
            ),
        ],
        consolidated_artifacts=[
            _artifact(shared_a, reason="data + api + test + history"),
            _artifact(shared_b, reason="data + ui + history"),
            _artifact(shared_c, reason="api + ui + test"),
            _artifact(
                SECRET_PATH,
                symbols=["PublicRecipesController"],
                reason="Public unauthenticated recipe access",
            ),
        ],
        consolidated_conventions=["Uses pydantic v2"],
        summary="Recipe service with public read-only endpoints",
    )


def _build_orchestrator_and_ctx(
    tmp_path: Path,
    *,
    max_targeted_reexplorations: int = 3,
) -> tuple[SpecOrchestrator, SpecContext]:
    """Build a real :class:`SpecOrchestrator` + populated :class:`SpecContext`.

    The gateway is a no-op mock — the test patches
    ``run_targeted_reexploration`` so no actual LLM calls happen.
    """
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.explorer.max_targeted_reexplorations = max_targeted_reexplorations

    def _noop_handler(model, system, messages, tools, response_format):
        return make_text_response("(should not be called)")

    a_prov = MockProvider("anthropic", _noop_handler)
    o_prov = MockProvider("openai", _noop_handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
        stage_defaults={"explorer": "primary"},
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

    run_id = "test-b2-run"
    workspace = settings.paths.workspace_root / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "exploration").mkdir(parents=True, exist_ok=True)

    ctx = SpecContext(
        run_id=run_id,
        user_input="test",
        repo_path=tmp_path,  # repo doesn't matter — explorer is mocked
        workspace_root=settings.paths.workspace_root,
        settings=settings,
        gateway=gateway,
        tools=orchestrator.tools,
        prompts=orchestrator.prompts,
        cache=cache,
        trace=NullTraceWriter(),
        skeleton_builder=RepoSkeletonBuilder(cache=cache),
    )
    ctx.intent = ConfirmedIntent(
        primary="Expose recipes via a public endpoint",
        intent_type="add_feature",
        scope=["api", "backend"],
        excluded=[],
        pending_clarification=[],
        confidence=0.9,
        rounds_used=1,
    )
    return orchestrator, ctx


def _count_perspectives_mentioning(
    exploration: ConsolidatedExploration, path: str
) -> int:
    """Return how many distinct perspectives surfaced ``path``."""
    perspectives = {
        p.perspective_type
        for p in exploration.perspectives
        if any(a.path == path for a in p.relevant_artifacts)
    }
    return len(perspectives)


@pytest.mark.asyncio
async def test_orchestrator_fires_targeted_reexplore_on_singleton_critical(
    tmp_path, monkeypatch
):
    """End-to-end: singleton_critical → targeted re-explorer → merged result."""
    orchestrator, ctx = _build_orchestrator_and_ctx(tmp_path)
    exploration = _make_synthetic_exploration()

    # Sanity: precondition for the test — exactly one perspective surfaces
    # the secret path before we re-explore.
    assert _count_perspectives_mentioning(exploration, SECRET_PATH) == 1

    invocations: list[dict] = []

    async def stub_run_targeted_reexploration(
        ctx_arg, gap, *, perspective="history", timeout_s=120.0
    ):
        invocations.append(
            {
                "gap_kind": gap.kind,
                "perspective": perspective,
                "primary_perspective": gap.primary_perspective,
                "timeout_s": timeout_s,
                "question": gap.suggested_re_explore_question,
            }
        )
        # The mock confirms the singleton finding from a DIFFERENT
        # perspective so the consolidator sees true cross-perspective
        # coverage when the result is merged.
        if SECRET_PATH in gap.suggested_re_explore_question:
            return Perspective(
                perspective_type=perspective,
                relevant_artifacts=[
                    _artifact(
                        SECRET_PATH,
                        symbols=["PublicRecipesController"],
                        reason=(
                            "Confirmed: file defines the public unauthenticated "
                            "recipe controller used by the feature."
                        ),
                    )
                ],
                conventions_discovered=[
                    "Public routes live under mealie/routes/explore/"
                ],
                notable_findings=[f"[targeted-re-explore:{gap.kind}] {gap.detail}"],
            )
        return Perspective(perspective_type=perspective)

    # Patch the module-level reference used by SpecOrchestrator.
    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod, "run_targeted_reexploration", stub_run_targeted_reexploration
    )

    result = await orchestrator._run_targeted_reexplorations(ctx, exploration)

    # --- Targeted re-explorer was invoked at least once for the singleton ---
    assert invocations, "expected at least one targeted re-exploration"
    singleton_invocations = [
        inv for inv in invocations if SECRET_PATH in inv["question"]
    ]
    assert len(singleton_invocations) == 1
    only_inv = singleton_invocations[0]
    assert only_inv["gap_kind"] == "singleton_critical"
    assert only_inv["primary_perspective"] == "api"
    # Picker must label the re-explorer with a perspective DIFFERENT from
    # the original sole reporter, so the consolidator sees cross-perspective
    # coverage rather than the same eyes echoing themselves.
    assert only_inv["perspective"] != "api"
    # Default timeout from ExplorerConfig flowed through.
    assert only_inv["timeout_s"] == 120.0

    # --- The merged exploration now has the artifact in ≥ 2 perspectives ---
    assert (
        _count_perspectives_mentioning(result, SECRET_PATH) >= 2
    ), "artifact should be mentioned by the original perspective AND the new one"

    # The original 5 perspectives are still there, plus the new one(s).
    assert len(result.perspectives) >= 6

    # consolidated_artifacts merged the confirmation reason into the
    # existing entry (no duplication, just enrichment).
    matching = [a for a in result.consolidated_artifacts if a.path == SECRET_PATH]
    assert len(matching) == 1
    merged = matching[0]
    assert "Public unauthenticated recipe access" in merged.reason
    assert "Confirmed" in merged.reason

    # New convention from the re-explorer made it into consolidated_conventions.
    assert any(
        "mealie/routes/explore" in c for c in result.consolidated_conventions
    )

    # B2 audit artifact persisted to disk for postmortem analysis.
    audit_path = ctx.run_workspace / "exploration" / "targeted_reexplore.json"
    assert audit_path.is_file()


@pytest.mark.asyncio
async def test_orchestrator_skips_reexplore_when_disabled(tmp_path, monkeypatch):
    """Setting max_targeted_reexplorations=0 disables the stage entirely."""
    orchestrator, ctx = _build_orchestrator_and_ctx(
        tmp_path, max_targeted_reexplorations=0
    )
    exploration = _make_synthetic_exploration()

    calls = 0

    async def boom(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("should not be invoked when disabled")

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "run_targeted_reexploration", boom)

    result = await orchestrator._run_targeted_reexplorations(ctx, exploration)
    assert calls == 0
    # Exploration is unchanged: still 5 perspectives, still 1 mention.
    assert len(result.perspectives) == 5
    assert _count_perspectives_mentioning(result, SECRET_PATH) == 1


@pytest.mark.asyncio
async def test_orchestrator_caps_reexplore_at_max_setting(tmp_path, monkeypatch):
    """At most ``max_targeted_reexplorations`` re-explorers run even with many gaps."""
    orchestrator, ctx = _build_orchestrator_and_ctx(
        tmp_path, max_targeted_reexplorations=2
    )

    # Build an exploration with FIVE singleton_critical gaps.
    exploration = ConsolidatedExploration(
        perspectives=[
            Perspective(
                perspective_type=ptype,
                relevant_artifacts=[
                    _artifact(f"only-from-{ptype}.py", reason=f"singleton from {ptype}")
                ],
            )
            for ptype in ("data", "api", "ui", "test", "history")
        ],
    )

    invocations: list[str] = []

    async def stub(ctx_arg, gap, *, perspective="history", timeout_s=120.0):
        invocations.append(gap.suggested_re_explore_question)
        await asyncio.sleep(0)  # yield to the loop so we see real concurrency
        return Perspective(perspective_type=perspective)

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "run_targeted_reexploration", stub)

    await orchestrator._run_targeted_reexplorations(ctx, exploration)

    # Cap was 2 — exactly 2 re-explorers ran even though 5 gaps were available.
    assert len(invocations) == 2

    # And the audit artifact recorded both the total gap count and the
    # attempted subset so a reader can see the cap clipped useful work.
    import json as _json

    audit = _json.loads(
        (ctx.run_workspace / "exploration" / "targeted_reexplore.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["gaps_total"] == 5
    assert audit["gaps_attempted"] == 2
    attempted_kinds = [g for g in audit["gaps"] if g["attempted"]]
    assert len(attempted_kinds) == 2


@pytest.mark.asyncio
async def test_orchestrator_swallows_reexplorer_exception(tmp_path, monkeypatch):
    """A single bad re-explorer must not poison the batch."""
    orchestrator, ctx = _build_orchestrator_and_ctx(
        tmp_path, max_targeted_reexplorations=3
    )
    exploration = _make_synthetic_exploration()

    async def crasher(ctx_arg, gap, *, perspective="history", timeout_s=120.0):
        raise RuntimeError("simulated explorer crash")

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "run_targeted_reexploration", crasher)

    # Must NOT raise — the orchestrator catches exceptions via
    # asyncio.gather(return_exceptions=True) and logs them.
    result = await orchestrator._run_targeted_reexplorations(ctx, exploration)

    # Exploration is unchanged because every re-explorer crashed.
    assert _count_perspectives_mentioning(result, SECRET_PATH) == 1
    assert len(result.perspectives) == 5
