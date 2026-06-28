"""Stage 3: Plan Brainstorm + Evaluation + Selection."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel

from devloop.llm import Message, call_strict_json
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.schemas import (
    ApproachEvaluation,
    CandidatePlan,
    PlanType,
    SelectedApproach,
)

logger = logging.getLogger(__name__)


PLAN_TYPES: tuple[PlanType, PlanType, PlanType] = ("conservative", "balanced", "aggressive")


async def generate_candidate(ctx: SpecContext, plan_type: PlanType) -> CandidatePlan:
    sys = ctx.prompts.load(
        "approach/plan_generator",
        plan_type=plan_type,
        intent_primary=ctx.intent.primary if ctx.intent else "",
        intent_scope=", ".join(ctx.intent.scope) if ctx.intent else "",
        consolidated_exploration=json.dumps(
            ctx.exploration.model_dump(mode="json") if ctx.exploration else {},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return await call_strict_json(
        ctx.gateway,
        role="plan_generator",
        schema=CandidatePlan,
        messages=[Message(role="user", content=f"Produce the {plan_type} plan now.")],
        system=sys,
        run_id=ctx.run_id,
        stage=f"approach.generator.{plan_type}",
        agent=f"plan_generator_{plan_type}",
    )


async def run_plan_evaluator(
    ctx: SpecContext, candidates: list[CandidatePlan]
) -> ApproachEvaluation:
    sys = ctx.prompts.load(
        "approach/plan_evaluator",
        intent_primary=ctx.intent.primary if ctx.intent else "",
        consolidated_exploration=json.dumps(
            ctx.exploration.model_dump(mode="json") if ctx.exploration else {},
            ensure_ascii=False,
            indent=2,
        ),
        candidate_plans=json.dumps(
            [c.model_dump() for c in candidates], ensure_ascii=False, indent=2
        ),
    )
    return await call_strict_json(
        ctx.gateway,
        role="plan_evaluator",
        schema=ApproachEvaluation,
        messages=[Message(role="user", content="Evaluate the candidates now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="approach.evaluator",
        agent="plan_evaluator",
    )


class SelectorOutput(BaseModel):
    primary_plan_type: PlanType
    integrated_strengths_from_others: list[str]
    rationale: str


async def run_plan_selector(
    ctx: SpecContext,
    candidates: list[CandidatePlan],
    evaluation: ApproachEvaluation,
) -> SelectedApproach:
    sys = ctx.prompts.load(
        "approach/plan_selector",
        intent_primary=ctx.intent.primary if ctx.intent else "",
        candidate_plans=json.dumps(
            [c.model_dump() for c in candidates], ensure_ascii=False, indent=2
        ),
        evaluation=json.dumps(evaluation.model_dump(), ensure_ascii=False, indent=2),
    )
    sel = await call_strict_json(
        ctx.gateway,
        role="plan_selector",
        schema=SelectorOutput,
        messages=[Message(role="user", content="Select the final plan now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="approach.selector",
        agent="plan_selector",
    )
    by_type = {c.plan_type: c for c in candidates}
    if sel.primary_plan_type not in by_type:
        raise ValueError(
            f"Selector returned unknown plan_type '{sel.primary_plan_type}'; "
            f"candidates: {list(by_type.keys())}"
        )
    return SelectedApproach(
        primary_plan=by_type[sel.primary_plan_type],
        integrated_strengths_from_others=sel.integrated_strengths_from_others,
        rationale=sel.rationale,
        candidate_plans=candidates,
        evaluation=evaluation,
    )


async def run_approach_stage(ctx: SpecContext) -> SelectedApproach:
    """Generate candidate plans, evaluate them, then select.

    When multi_candidate_approach is disabled, falls back to the configured single
    plan type (default: "balanced") for fast / cheap MVP runs.
    """
    ctx.trace.record_stage_event(run_id=ctx.run_id, stage="approach", event="start", detail={})

    if ctx.settings.orchestrator.enable_multi_candidate_approach:
        candidates = await asyncio.gather(
            *[generate_candidate(ctx, pt) for pt in PLAN_TYPES]
        )
    else:
        # MVP single candidate — choose via config
        single_plan_type = ctx.metadata.get("single_plan_type", "balanced")
        if single_plan_type not in PLAN_TYPES:
            single_plan_type = "balanced"
        candidates = [await generate_candidate(ctx, single_plan_type)]

    for c in candidates:
        _save_artifact(ctx, f"approach/candidate_{c.plan_type}.json", c.model_dump())

    if len(candidates) >= 2:
        evaluation = await run_plan_evaluator(ctx, candidates)
        _save_artifact(ctx, "approach/evaluation.json", evaluation.model_dump())
        selected = await run_plan_selector(ctx, candidates, evaluation)
    else:
        selected = SelectedApproach(
            primary_plan=candidates[0],
            integrated_strengths_from_others=[],
            rationale="Single-candidate mode (multi_candidate_approach disabled).",
            candidate_plans=candidates,
            evaluation=None,
        )

    _save_artifact(ctx, "approach/selected.json", selected.model_dump())
    ctx.trace.record_stage_event(
        run_id=ctx.run_id,
        stage="approach",
        event="complete",
        detail={
            "candidates": len(candidates),
            "selected": selected.primary_plan.plan_type,
        },
    )
    return selected


def _save_artifact(ctx: SpecContext, rel_path: str, data: Any) -> None:
    path = ctx.run_workspace / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
