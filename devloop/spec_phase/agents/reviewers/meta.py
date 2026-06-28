"""Stage 6.5: Meta-reviewer that consolidates 4 axis reviews into a single
prioritized action list.

Background (B4): the rewriter previously digested all 4 axis reviewers'
issues in parallel, which led to "fix one, break another" — observed in
case-6 v2 where the rewriter re-ordered rate-limiting and introduced a new
critical security defect. The meta-reviewer takes the 4 reports + the spec
+ intent, dedupes/merges overlapping issues, prioritizes them, and
surfaces cross-axis conflicts up front so the rewriter can sequence its
edits deliberately.
"""

from __future__ import annotations

import json
import logging

from devloop.llm import Message, call_strict_json
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.schemas import (
    ConsolidatedReview,
    MetaReviewResult,
    Spec,
)

logger = logging.getLogger(__name__)


async def run_meta_reviewer(
    ctx: SpecContext,
    spec: Spec,
    consolidated_review: ConsolidatedReview,
) -> MetaReviewResult:
    """Run the meta-reviewer agent.

    Reads all 4 axis review reports, dedupes/merges overlapping issues,
    prioritizes by severity + impact + conflict risk, surfaces cross-axis
    conflicts, and returns a unified ordered action list.
    """
    sys = ctx.prompts.load(
        "reviewer/meta",
        spec=json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        consolidated_review=json.dumps(
            consolidated_review.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        intent_primary=ctx.intent.primary if ctx.intent else "",
    )

    result = await call_strict_json(
        ctx.gateway,
        role="reviewer",
        schema=MetaReviewResult,
        messages=[
            Message(
                role="user",
                content=(
                    "Consolidate the 4 axis reviews into a unified, "
                    "prioritized action list with cross-axis conflict "
                    "annotations. Respond with ONLY the MetaReviewResult JSON."
                ),
            )
        ],
        system=sys,
        run_id=ctx.run_id,
        stage="review.meta",
        agent="reviewer_meta",
        max_tokens=8192,
        max_repair_attempts=2,
    )

    if not result.judge_model:
        result.judge_model = ctx.settings.llm.cross_review_model

    logger.info(
        "meta-reviewer produced %d action(s), %d cross-axis conflict(s)",
        len(result.actions),
        len(result.cross_axis_conflicts),
    )
    return result
