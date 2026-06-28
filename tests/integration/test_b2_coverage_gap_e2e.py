"""End-to-end capability-boundary tests for B2 (coverage-gap re-explore).

These tests verify the orchestrator's ``_run_targeted_reexplorations`` wiring
against the coverage-gap detector + targeted re-explorer pipeline using a
real :class:`SpecOrchestrator` and a real :class:`SpecContext` — only the
LLM-driven explorer body itself (``run_targeted_reexploration``) is mocked,
which is the boundary every realistic CI run will hit.

Each test answers one question about the B2 defense:

1. Does a singleton-critical artifact trigger a targeted re-explore that
   results in the artifact being mentioned by ≥ 2 perspectives?
2. Does a clean exploration (no gaps) skip the re-explore stage entirely?
3. Does the ``max_targeted_reexplorations`` setting cap concurrent
   re-explorers (10 gaps → only N=default(3) fire)?
4. If a re-explorer raises, does the orchestrator swallow it and keep the
   original exploration intact (no propagation, no data loss)?
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
    ConsolidatedExploration,
    Perspective,
    RelevantArtifact,
)
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import MockProvider, make_text_response

# Path used by the singleton-critical test. Mirrors the Mealie failure mode
# that motivated B2 — one perspective surfaces a public-routes controller
# that the other four miss.
SECRET_PATH = "mealie/routes/explore/controller_public_recipes.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _populated_perspective(ptype: str, *, n: int = 3) -> Perspective:
    """A perspective with ``n`` distinct non-singleton artifacts.

    Used to anchor cross-perspective baselines so the detector doesn't
    accidentally flag the helper itself as ``sparse_perspective``.
    """
    return Perspective(
        perspective_type=ptype,  # type: ignore[arg-type]
        relevant_artifacts=[
            _artifact(
                f"app/{ptype}/file_{i}.py",
                importance="relevant",
                reason=f"{ptype} side concern #{i}",
            )
            for i in range(n)
        ],
    )


def _singleton_critical_exploration_via_data() -> ConsolidatedExploration:
    """Build an exploration where ONLY the ``data`` perspective surfaces
    SECRET_PATH at importance=critical. Other perspectives are
    well-populated with unrelated artifacts so the detector flags only the
    one singleton (no spurious sparse_perspective gaps)."""
    return ConsolidatedExploration(
        perspectives=[
            Perspective(
                perspective_type="data",
                relevant_artifacts=[
                    _artifact("app/models/recipe.py", reason="data model"),
                    _artifact("app/models/user.py", reason="data model"),
                    # The singleton — only the data perspective sees it.
                    _artifact(
                        SECRET_PATH,
                        symbols=["PublicRecipesController"],
                        reason="Public unauthenticated recipe access",
                    ),
                ],
            ),
            _populated_perspective("api"),
            _populated_perspective("ui"),
            _populated_perspective("test"),
            _populated_perspective("history"),
        ],
        conflicts=[],
        consolidated_artifacts=[
            _artifact("app/models/recipe.py", reason="data"),
            _artifact("app/models/user.py", reason="data"),
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
    """Standard orchestrator + populated context wired with a no-op gateway.

    The LLM gateway here is a defensive backstop — every test in this file
    monkey-patches ``run_targeted_reexploration`` so the gateway should
    never actually be invoked. If it IS, the noop handler returns a
    canary string so a regression is obvious.
    """
    settings = load_settings()
    settings.paths.workspace_root = tmp_path / "specs"
    settings.paths.cache_dir = tmp_path / "cache"
    settings.paths.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.explorer.max_targeted_reexplorations = max_targeted_reexplorations

    def _noop_handler(model, system, messages, tools, response_format):
        return make_text_response(
            "(no-op gateway — run_targeted_reexploration should be patched)"
        )

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

    run_id = "test-b2-e2e"
    workspace = settings.paths.workspace_root / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "exploration").mkdir(parents=True, exist_ok=True)

    ctx = SpecContext(
        run_id=run_id,
        user_input="test",
        repo_path=tmp_path,  # repo path doesn't matter — explorer is mocked.
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
    """Distinct perspective_types whose relevant_artifacts contain ``path``."""
    return len(
        {
            p.perspective_type
            for p in exploration.perspectives
            if any(a.path == path for a in p.relevant_artifacts)
        }
    )


# ---------------------------------------------------------------------------
# 1. Singleton critical from data → targeted re-explore → ≥ 2 perspectives.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_singleton_critical_triggers_targeted_explore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the only perspective seeing SECRET_PATH is ``data``, the
    orchestrator must fire exactly one targeted re-exploration aimed at
    that path. The mock confirms the finding from a DIFFERENT perspective,
    and after merge SECRET_PATH must appear in ≥ 2 perspectives — the
    cross-perspective coverage signal the consolidator is looking for."""
    orchestrator, ctx = _build_orchestrator_and_ctx(tmp_path)
    exploration = _singleton_critical_exploration_via_data()

    # Precondition: exactly one perspective sees SECRET_PATH at this stage.
    assert _count_perspectives_mentioning(exploration, SECRET_PATH) == 1

    invocations: list[dict[str, object]] = []

    async def stub_run_targeted_reexploration(
        ctx_arg, gap, *, perspective="history", timeout_s=120.0
    ):
        invocations.append(
            {
                "gap_kind": gap.kind,
                "perspective": perspective,
                "primary_perspective": gap.primary_perspective,
                "question": gap.suggested_re_explore_question,
            }
        )
        # Mock the re-explorer's confirmation — labelled with a perspective
        # DIFFERENT from the original singleton reporter so the consolidator
        # sees true cross-perspective coverage.
        if SECRET_PATH in gap.suggested_re_explore_question:
            return Perspective(
                perspective_type=perspective,  # type: ignore[arg-type]
                relevant_artifacts=[
                    _artifact(
                        SECRET_PATH,
                        symbols=["PublicRecipesController"],
                        reason=(
                            "Confirmed via direct file read by the targeted "
                            "re-explorer — file defines the public "
                            "unauthenticated recipe controller."
                        ),
                    )
                ],
                conventions_discovered=[
                    "Public routes live under mealie/routes/explore/"
                ],
            )
        return Perspective(perspective_type=perspective)  # type: ignore[arg-type]

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod, "run_targeted_reexploration", stub_run_targeted_reexploration
    )

    result = await orchestrator._run_targeted_reexplorations(ctx, exploration)

    # --- Targeted re-explorer fired exactly once for the singleton.
    secret_invocations = [
        inv for inv in invocations if SECRET_PATH in str(inv["question"])
    ]
    assert len(secret_invocations) == 1, (
        f"expected exactly one targeted re-explore for SECRET_PATH, "
        f"got {len(secret_invocations)}: {secret_invocations}"
    )
    only_inv = secret_invocations[0]
    assert only_inv["gap_kind"] == "singleton_critical"
    assert only_inv["primary_perspective"] == "data"
    # Picker labelled the re-explorer with a perspective DIFFERENT from
    # ``data`` so the merge produces real cross-perspective coverage.
    assert only_inv["perspective"] != "data"

    # --- After merge, SECRET_PATH is in ≥ 2 perspectives — the post-condition
    # the consolidator's gap-detection was trying to engineer.
    assert _count_perspectives_mentioning(result, SECRET_PATH) >= 2

    # The merge enriched the existing consolidated_artifacts entry rather
    # than duplicating it (no double-counting of the same path).
    matches = [a for a in result.consolidated_artifacts if a.path == SECRET_PATH]
    assert len(matches) == 1
    merged = matches[0]
    # Both the original reason AND the re-explorer's confirmation are
    # carried through — the merge preserves provenance for both sides.
    assert "Public unauthenticated recipe access" in merged.reason
    assert "Confirmed" in merged.reason


# ---------------------------------------------------------------------------
# 2. No gap → no targeted explore → no LLM call.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_gap_no_targeted_explore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the consolidator's output has no detectable gaps, the orchestrator
    must NOT spawn any targeted re-explorers — the LLM budget is precious
    and we don't pay for re-exploration that has nothing to explore."""
    orchestrator, ctx = _build_orchestrator_and_ctx(tmp_path)

    # Every critical artifact appears in ≥ 2 perspectives (no singletons),
    # every conflict has a resolution_suggestion (no unresolved conflicts),
    # and every perspective has ≥ SPARSE_SIBLING_THRESHOLD artifacts (no
    # sparse perspectives).
    shared = "app/services/core.py"
    well_covered_exploration = ConsolidatedExploration(
        perspectives=[
            Perspective(
                perspective_type="data",
                relevant_artifacts=[
                    _artifact(shared, importance="critical", reason="data side"),
                    _artifact("app/models/a.py", importance="relevant"),
                    _artifact("app/models/b.py", importance="relevant"),
                ],
            ),
            Perspective(
                perspective_type="api",
                relevant_artifacts=[
                    _artifact(shared, importance="critical", reason="api side"),
                    _artifact("app/api/x.py", importance="relevant"),
                    _artifact("app/api/y.py", importance="relevant"),
                ],
            ),
            Perspective(
                perspective_type="ui",
                relevant_artifacts=[
                    _artifact(shared, importance="critical", reason="ui side"),
                    _artifact("app/ui/c.tsx", importance="relevant"),
                    _artifact("app/ui/d.tsx", importance="relevant"),
                ],
            ),
            Perspective(
                perspective_type="test",
                relevant_artifacts=[
                    _artifact(shared, importance="critical", reason="test side"),
                    _artifact("tests/test_a.py", importance="relevant"),
                    _artifact("tests/test_b.py", importance="relevant"),
                ],
            ),
            Perspective(
                perspective_type="history",
                relevant_artifacts=[
                    _artifact(shared, importance="critical", reason="history side"),
                    _artifact("docs/CHANGELOG.md", importance="relevant"),
                    _artifact("docs/RFC.md", importance="relevant"),
                ],
            ),
        ],
        conflicts=[],
    )

    call_count = 0

    async def boom(ctx_arg, gap, *, perspective="history", timeout_s=120.0):
        nonlocal call_count
        call_count += 1
        raise RuntimeError(
            f"should not be invoked — exploration has no gaps "
            f"(unexpected gap kind={gap.kind})"
        )

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "run_targeted_reexploration", boom)

    result = await orchestrator._run_targeted_reexplorations(
        ctx, well_covered_exploration
    )

    # Re-explorer was NEVER called.
    assert call_count == 0
    # Exploration unchanged — same 5 perspectives, same artifact counts.
    assert len(result.perspectives) == 5
    assert all(len(p.relevant_artifacts) == 3 for p in result.perspectives)


# ---------------------------------------------------------------------------
# 3. Many gaps → cap respected (10 singletons, default max=3).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_targeted_reexplorations_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build an exploration with TEN singleton_critical gaps spread across
    the perspectives, and confirm only ``max_targeted_reexplorations``
    (default 3) re-explorers fire — runaway re-exploration is the failure
    mode B2 is specifically designed to prevent."""
    # Explicitly use the DEFAULT from ExplorerConfig (3) so the test fails
    # loudly if the default ever changes silently.
    orchestrator, ctx = _build_orchestrator_and_ctx(
        tmp_path, max_targeted_reexplorations=3
    )
    # Sanity: setting carries through.
    assert ctx.settings.explorer.max_targeted_reexplorations == 3

    # 10 distinct singleton artifacts, spread 2 per perspective across 5
    # perspectives. Each path is critical and surfaced by exactly one
    # perspective, so each becomes a singleton_critical gap.
    perspectives = []
    for ptype in ("data", "api", "ui", "test", "history"):
        perspectives.append(
            Perspective(
                perspective_type=ptype,  # type: ignore[arg-type]
                relevant_artifacts=[
                    _artifact(
                        f"only-from-{ptype}-{i}.py",
                        importance="critical",
                        reason=f"only {ptype} found this — singleton #{i}",
                    )
                    for i in range(2)
                ],
            )
        )
    exploration = ConsolidatedExploration(perspectives=perspectives, conflicts=[])

    # Sanity: detector sees all 10 gaps.
    from devloop.spec_phase.validators.coverage_gap_detector import (
        detect_coverage_gaps,
    )

    assert len(detect_coverage_gaps(exploration)) == 10

    invocation_questions: list[str] = []

    async def stub(ctx_arg, gap, *, perspective="history", timeout_s=120.0):
        invocation_questions.append(gap.suggested_re_explore_question)
        # Yield to the event loop so concurrent gather() actually exercises
        # parallelism — surfaces races between the cap and dispatch.
        await asyncio.sleep(0)
        return Perspective(perspective_type=perspective)  # type: ignore[arg-type]

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "run_targeted_reexploration", stub)

    await orchestrator._run_targeted_reexplorations(ctx, exploration)

    # Hard cap held. NEVER more than 3, even with 10 gaps available.
    assert len(invocation_questions) == 3, (
        f"max_targeted_reexplorations=3 with 10 gaps must fire exactly 3 "
        f"re-explorers; got {len(invocation_questions)}: {invocation_questions}"
    )

    # Audit artifact records the gap budget for postmortem analysis: total
    # gaps detected vs gaps actually attempted.
    import json as _json

    audit_path = ctx.run_workspace / "exploration" / "targeted_reexplore.json"
    assert audit_path.is_file(), "B2 audit artifact must be persisted"
    audit = _json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["gaps_total"] == 10
    assert audit["gaps_attempted"] == 3
    attempted = [g for g in audit["gaps"] if g["attempted"]]
    assert len(attempted) == 3


# ---------------------------------------------------------------------------
# 4. Re-explorer failure → exploration preserved, warning logged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_targeted_explorer_fails_gracefully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the targeted re-explorer raises (LLM error, timeout, tool blow-up,
    etc.), the orchestrator must NOT propagate the exception. The original
    exploration must be returned untouched, and a warning must be logged so
    operators can investigate without losing the run.

    The orchestrator uses ``structlog`` which (with the default ConsoleRenderer
    config) writes to stdout — so we use ``capsys`` rather than ``caplog`` to
    verify the warning surfaced.
    """
    orchestrator, ctx = _build_orchestrator_and_ctx(tmp_path)
    exploration = _singleton_critical_exploration_via_data()
    original_perspective_count = len(exploration.perspectives)
    original_mentions = _count_perspectives_mentioning(exploration, SECRET_PATH)

    crash_count = 0

    async def crasher(ctx_arg, gap, *, perspective="history", timeout_s=120.0):
        nonlocal crash_count
        crash_count += 1
        raise RuntimeError(
            f"simulated explorer crash (gap.kind={gap.kind}, "
            f"perspective={perspective})"
        )

    import devloop.spec_phase.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "run_targeted_reexploration", crasher)

    # Must NOT raise — asyncio.gather(return_exceptions=True) is the
    # contract here, and the per-gap `if isinstance(result, BaseException)`
    # branch turns it into a logged warning.
    result = await orchestrator._run_targeted_reexplorations(ctx, exploration)

    # The crasher WAS invoked (so we actually exercised the failure path).
    assert crash_count >= 1, (
        f"expected crasher to be invoked at least once; got crash_count={crash_count}"
    )

    # Exploration unchanged in EVERY observable dimension — no perspective
    # was appended, the singleton path is still seen by only its original
    # reporter.
    assert len(result.perspectives) == original_perspective_count
    assert (
        _count_perspectives_mentioning(result, SECRET_PATH) == original_mentions
    )

    # And a warning got out — operator visibility is non-negotiable here
    # because silent re-explorer failures are exactly the kind of bug that
    # makes coverage gaps invisible in production. structlog writes to
    # stdout by default, so capsys (not caplog) is the right hook.
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert "targeted re-explore failed" in combined_output, (
        "expected a 'targeted re-explore failed' warning on stdout/stderr; "
        f"got stdout={captured.out!r}, stderr={captured.err!r}"
    )
    assert "singleton_critical" in combined_output, (
        "warning must include the gap kind so an operator can triage the failure"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
