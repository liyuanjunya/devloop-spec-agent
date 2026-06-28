"""Stage 1: Deep Intent Understanding — Analyzer / Skeptic / Verifier."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from devloop.llm import Message, call_strict_json
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.schemas import (
    ConfirmedIntent,
    Hypothesis,
    HypothesisVerdict,
    SkepticChallenge,
)

logger = logging.getLogger(__name__)


# ---- Phase output schemas ----


class AnalyzerOutput(BaseModel):
    hypotheses: list[Hypothesis]


class SkepticOutput(BaseModel):
    challenges: list[SkepticChallenge] = Field(default_factory=list)
    new_hypotheses: list[Hypothesis] = Field(default_factory=list)


class VerifierOutput(BaseModel):
    verdicts: list[HypothesisVerdict] = Field(default_factory=list)
    confirmed_intent: ConfirmedIntent
    request_another_round: bool = False


# ---- Agents ----


async def run_analyzer(ctx: SpecContext) -> AnalyzerOutput:
    sys = ctx.prompts.load(
        "intent/analyzer",
        user_input=ctx.user_input,
        repo_skeleton=ctx.repo_skeleton.text if ctx.repo_skeleton else "",
    )
    result = await call_strict_json(
        ctx.gateway,
        role="intent_analyzer",
        schema=AnalyzerOutput,
        messages=[Message(role="user", content="Generate hypotheses now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="intent.analyzer",
        agent="intent_analyzer",
    )
    return result


async def run_skeptic(
    ctx: SpecContext, hypotheses: list[Hypothesis]
) -> SkepticOutput:
    sys = ctx.prompts.load(
        "intent/skeptic",
        user_input=ctx.user_input,
        repo_skeleton=ctx.repo_skeleton.text if ctx.repo_skeleton else "",
        hypotheses=json.dumps([h.model_dump() for h in hypotheses], ensure_ascii=False, indent=2),
    )
    return await call_strict_json(
        ctx.gateway,
        role="intent_skeptic",
        schema=SkepticOutput,
        messages=[Message(role="user", content="Challenge the analyzer's hypotheses now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="intent.skeptic",
        agent="intent_skeptic",
    )


async def run_verifier(
    ctx: SpecContext,
    hypotheses: list[Hypothesis],
    challenges: list[SkepticChallenge],
    round_number: int,
) -> VerifierOutput:
    sys = ctx.prompts.load(
        "intent/verifier",
        user_input=ctx.user_input,
        repo_skeleton=ctx.repo_skeleton.text if ctx.repo_skeleton else "",
        hypotheses=json.dumps([h.model_dump() for h in hypotheses], ensure_ascii=False, indent=2),
        challenges=json.dumps([c.model_dump() for c in challenges], ensure_ascii=False, indent=2),
        round_number=round_number,
    )
    return await call_strict_json(
        ctx.gateway,
        role="intent_verifier",
        schema=VerifierOutput,
        messages=[Message(role="user", content="Verify and confirm intent now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="intent.verifier",
        agent="intent_verifier",
    )


async def run_intent_stage(
    ctx: SpecContext, *, max_rounds: int = 3
) -> ConfirmedIntent:
    """Full intent-understanding loop: analyze → skeptic → verify, repeat if needed."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")
    ctx.trace.record_stage_event(run_id=ctx.run_id, stage="intent", event="start", detail={})

    # Round 1: analyze
    analyzer_out = await run_analyzer(ctx)
    hypotheses = list(analyzer_out.hypotheses)
    _save_artifact(ctx, "intent/initial_hypotheses.json", [h.model_dump() for h in hypotheses])
    logger.info("intent: analyzer produced %d hypotheses", len(hypotheses))

    challenges: list[SkepticChallenge] = []
    verifier_out: VerifierOutput | None = None
    round_idx = 0  # Defensive default

    for round_idx in range(1, max_rounds + 1):
        # Skeptic
        skeptic_out = await run_skeptic(ctx, hypotheses)
        if skeptic_out.new_hypotheses:
            existing_ids = {h.id for h in hypotheses}
            for nh in skeptic_out.new_hypotheses:
                if nh.id not in existing_ids:
                    hypotheses.append(nh)
        challenges = list(skeptic_out.challenges)
        _save_artifact(
            ctx,
            f"intent/skeptic_round_{round_idx}.json",
            {
                "challenges": [c.model_dump() for c in challenges],
                "new_hypotheses": [h.model_dump() for h in skeptic_out.new_hypotheses],
            },
        )

        # Verifier
        verifier_out = await run_verifier(ctx, hypotheses, challenges, round_idx)
        _save_artifact(
            ctx,
            f"intent/verifier_round_{round_idx}.json",
            verifier_out.model_dump(),
        )

        if not verifier_out.request_another_round:
            break

    if verifier_out is None:
        # Should never happen given max_rounds >= 1, but defend.
        raise RuntimeError("Intent verifier produced no output")

    confirmed = verifier_out.confirmed_intent
    confirmed.rounds_used = round_idx

    _save_artifact(ctx, "intent/confirmed.json", confirmed.model_dump())
    ctx.trace.record_stage_event(
        run_id=ctx.run_id,
        stage="intent",
        event="complete",
        detail={"rounds_used": round_idx, "confidence": confirmed.confidence},
    )
    return confirmed


def _save_artifact(ctx: SpecContext, rel_path: str, data: Any) -> None:
    path = ctx.run_workspace / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
