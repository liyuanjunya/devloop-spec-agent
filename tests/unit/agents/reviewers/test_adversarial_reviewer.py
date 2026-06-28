"""Tests for DevLoop Sprint C — todo C1: adversarial reviewer integration in
``run_review_stage``.

These tests verify the wiring between the selection heuristic /
settings overrides and the actual review stage: an "enabled" decision
must result in a 5th reviewer call with ``reviewer_type == "adversarial"``
in the consolidated output, and a "disabled" decision must not. We mock
the LLM gateway so each reviewer terminates immediately with
``VERDICT: pass`` and we can count which angles were exercised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devloop.cache import NullCache
from devloop.config import Settings
from devloop.llm.gateway import LLMGateway
from devloop.llm.routing import ModelRouter
from devloop.llm.trace import NullTraceWriter
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.reviewers.stage import run_review_stage
from devloop.spec_phase.prompts_loader import PromptLoader
from devloop.spec_phase.schemas import (
    ConfirmedIntent,
    Spec,
    SpecMetadata,
)
from devloop.tools import build_default_registry
from tests.fixtures.mock_provider import MockProvider, make_text_response

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_angle(system: str) -> str | None:
    """Identify which reviewer angle is being prompted from the system text.

    Each reviewer prompt opens with ``# <Angle> Reviewer``, so the angle is
    cheap to pick out without coupling the test to any other prompt detail.
    """
    head = system.lstrip().splitlines()[0] if system.strip() else ""
    head_low = head.lower()
    for angle in (
        "architecture",
        "completeness",
        "executability",
        "consistency",
        "adversarial",
    ):
        if angle in head_low:
            return angle
    return None


def _pass_reviewer_handler():
    """LLM handler that records the angle for each call and returns VERDICT: pass.

    Returning an empty tool-call list lets ``call_react_with_tools`` terminate
    immediately, so each reviewer = exactly one LLM call.
    """
    called_angles: list[str] = []

    def handler(model, system, messages, tools, response_format):
        angle = _detect_angle(system)
        if angle is not None:
            called_angles.append(angle)
        return make_text_response("All clean.\nVERDICT: pass")

    return handler, called_angles


def _sample_spec() -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="demo", title="Demo"),
        summary="demo spec for adversarial-reviewer integration tests",
    )


def _build_ctx(
    tmp_path: Path,
    handler,
    *,
    intent: ConfirmedIntent,
    settings: Settings | None = None,
) -> SpecContext:
    """Build a ``SpecContext`` wired to a MockProvider for review-stage tests."""
    settings = settings or Settings()
    a_prov = MockProvider("anthropic", handler)
    o_prov = MockProvider("openai", handler)
    router = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
        stage_defaults={"writer": "primary", "reviewer": "cross_review"},
    )
    gateway = LLMGateway(
        providers={"anthropic": a_prov, "openai": o_prov},
        router=router,
        trace=NullTraceWriter(),
    )

    workspace_root = tmp_path / "specs"
    workspace_root.mkdir(parents=True, exist_ok=True)

    ctx = SpecContext.__new__(SpecContext)
    ctx.run_id = "test-run"
    ctx.user_input = intent.primary
    ctx.repo_path = tmp_path.resolve()
    ctx.workspace_root = workspace_root
    ctx.settings = settings
    ctx.gateway = gateway
    ctx.tools = build_default_registry()
    ctx.prompts = PromptLoader(PROMPTS_DIR)
    ctx.cache = NullCache()
    ctx.trace = NullTraceWriter()
    ctx.skeleton_builder = None  # type: ignore[assignment]
    ctx.repo_skeleton = None
    ctx.intent = intent
    ctx.exploration = None
    ctx.approach = None
    ctx.spec = None
    ctx.consolidated_review = None
    ctx.total_llm_calls = 0
    ctx.total_tool_calls = 0
    ctx.iterations = 0
    ctx.run_counter = {}
    ctx.metadata: dict[str, Any] = {}
    return ctx


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_adversarial_runs_when_intent_triggers(tmp_path):
    """A security-scoped intent must add the 5th adversarial reviewer to the stage."""
    handler, called_angles = _pass_reviewer_handler()
    intent = ConfirmedIntent(
        primary="add CSRF protection to write endpoints",
        intent_type="add_feature",
        scope=["backend", "security"],
    )
    ctx = _build_ctx(tmp_path, handler, intent=intent)

    consolidated = await run_review_stage(ctx, _sample_spec(), iteration=1)

    reviewer_types = sorted(r.reviewer_type for r in consolidated.reviews)
    assert reviewer_types == [
        "adversarial",
        "architecture",
        "completeness",
        "consistency",
        "executability",
    ], f"Expected all 5 angles to run, got {reviewer_types}"
    assert "adversarial" in called_angles
    assert consolidated.overall_verdict == "pass"


async def test_adversarial_skipped_for_plain_backend_intent(tmp_path):
    """A plain backend intent with no risk keywords must NOT pay the 5th-call cost."""
    handler, called_angles = _pass_reviewer_handler()
    intent = ConfirmedIntent(
        primary="add a healthcheck endpoint",
        intent_type="add_feature",
        scope=["backend"],
    )
    ctx = _build_ctx(tmp_path, handler, intent=intent)

    consolidated = await run_review_stage(ctx, _sample_spec(), iteration=1)

    reviewer_types = sorted(r.reviewer_type for r in consolidated.reviews)
    assert reviewer_types == [
        "architecture",
        "completeness",
        "consistency",
        "executability",
    ], f"Expected only the 4 base angles, got {reviewer_types}"
    assert "adversarial" not in called_angles


async def test_force_adversarial_overrides_plain_backend(tmp_path):
    """``force_adversarial=True`` must enable adversarial even with a plain backend intent."""
    handler, called_angles = _pass_reviewer_handler()
    settings = Settings()
    settings.reviewer.force_adversarial = True
    intent = ConfirmedIntent(
        primary="add a healthcheck endpoint",
        intent_type="add_feature",
        scope=["backend"],
    )
    ctx = _build_ctx(tmp_path, handler, intent=intent, settings=settings)

    consolidated = await run_review_stage(ctx, _sample_spec(), iteration=1)

    reviewer_types = sorted(r.reviewer_type for r in consolidated.reviews)
    assert "adversarial" in reviewer_types
    assert len(consolidated.reviews) == 5
    assert "adversarial" in called_angles


async def test_disable_adversarial_overrides_security_scope(tmp_path):
    """``disable_adversarial=True`` must veto adversarial even when scope says yes."""
    handler, called_angles = _pass_reviewer_handler()
    settings = Settings()
    settings.reviewer.disable_adversarial = True
    intent = ConfirmedIntent(
        primary="add CSRF protection to write endpoints",
        intent_type="add_feature",
        scope=["backend", "security"],
    )
    ctx = _build_ctx(tmp_path, handler, intent=intent, settings=settings)

    consolidated = await run_review_stage(ctx, _sample_spec(), iteration=1)

    reviewer_types = sorted(r.reviewer_type for r in consolidated.reviews)
    assert "adversarial" not in reviewer_types
    assert len(consolidated.reviews) == 4
    assert "adversarial" not in called_angles


async def test_disable_strips_adversarial_even_when_in_angles_config(tmp_path):
    """If YAML accidentally lists ``"adversarial"`` in ``reviewer.angles``,
    ``disable_adversarial=True`` must still strip it out — the kill switch
    is the strongest signal."""
    handler, called_angles = _pass_reviewer_handler()
    settings = Settings()
    settings.reviewer.angles = [
        "architecture",
        "completeness",
        "executability",
        "consistency",
        "adversarial",
    ]
    settings.reviewer.disable_adversarial = True
    intent = ConfirmedIntent(
        primary="add CSRF protection",
        intent_type="add_feature",
        scope=["security"],
    )
    ctx = _build_ctx(tmp_path, handler, intent=intent, settings=settings)

    consolidated = await run_review_stage(ctx, _sample_spec(), iteration=1)

    reviewer_types = sorted(r.reviewer_type for r in consolidated.reviews)
    assert "adversarial" not in reviewer_types, (
        "disable_adversarial must remove the angle even when YAML config lists it"
    )
    assert "adversarial" not in called_angles


async def test_adversarial_artifact_is_written(tmp_path):
    """When adversarial runs, its per-angle review artifact must land alongside
    the other 4 so downstream tooling (meta-reviewer, eval) can read it."""
    handler, _ = _pass_reviewer_handler()
    intent = ConfirmedIntent(
        primary="Implement OpenAI summarization of user notes",
        intent_type="add_feature",
        scope=["backend"],
    )
    ctx = _build_ctx(tmp_path, handler, intent=intent)

    await run_review_stage(ctx, _sample_spec(), iteration=1)

    artifact = ctx.run_workspace / "spec_iterations" / "review_v1_adversarial.json"
    assert artifact.is_file(), f"Expected adversarial artifact at {artifact}"


@pytest.mark.parametrize(
    "primary,scope,expect_adversarial",
    [
        ("Add a file upload endpoint", ["backend"], True),
        ("Wrap the OpenAI completion API", ["backend"], True),
        ("Process payments via Stripe webhook", ["external_integration"], True),
        ("Reset user password by email", ["auth"], True),
        ("Render the dashboard widgets", ["frontend", "ui"], False),
        ("Migrate users table to UUID PK", ["data_model"], False),
    ],
)
async def test_adversarial_selection_end_to_end(tmp_path, primary, scope, expect_adversarial):
    """Spot-check several realistic intents end-to-end through ``run_review_stage``."""
    handler, _ = _pass_reviewer_handler()
    intent = ConfirmedIntent(
        primary=primary,
        intent_type="add_feature",
        scope=scope,  # type: ignore[arg-type]
    )
    # Use a fresh sub-dir per parametrize case to avoid artifact collisions.
    case_dir = tmp_path / primary.replace(" ", "_").replace("/", "_")[:40]
    case_dir.mkdir()
    ctx = _build_ctx(case_dir, handler, intent=intent)

    consolidated = await run_review_stage(ctx, _sample_spec(), iteration=1)

    has_adv = any(r.reviewer_type == "adversarial" for r in consolidated.reviews)
    assert has_adv is expect_adversarial, (
        f"For primary={primary!r} scope={scope} expected adversarial={expect_adversarial}, "
        f"got reviews={[r.reviewer_type for r in consolidated.reviews]}"
    )
