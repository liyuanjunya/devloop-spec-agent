"""Stage 4-5: Writer (produces Spec, self-reflects) and Rewriter (responds to reviews)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError

from devloop.llm import Message, call_strict_json
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.schemas import (
    ConsolidatedReview,
    MetaReviewResult,
    Spec,
    SpecMetadata,
    SpecSegmentFRs,
    SpecSegmentHead,
    SpecSegmentSCs,
    SpecSegmentStories,
    SpecSegmentTail,
)
from devloop.spec_phase.schemas.spec import find_forbidden_phrase

logger = logging.getLogger(__name__)


def detect_soft_language_in_spec_dict(spec_dict: dict) -> list[tuple[str, str]]:
    """Walk a (raw) Spec dict and report any soft-language phrases on guarded fields.

    Returns a list of ``(field_path, matched_phrase)`` tuples; empty if clean.
    Intended as a cheap local pre-check the writer can run before the strict-JSON
    LLM call, so we can short-circuit obvious failures without burning a roundtrip.

    Guarded fields mirror the pydantic ``@field_validator``s in
    :mod:`devloop.spec_phase.schemas.spec`:

    * ``summary``
    * ``functional_requirements[i].text``
    * ``success_criteria[i].metric`` / ``.threshold``
    * ``key_entities[i].description``
    * ``edge_cases[i].handling``
    * ``needs_clarification[i].recommended_default`` / ``.if_rejected``
    * ``self_concerns[i].suggested_resolution`` (when non-None)
    """
    if not isinstance(spec_dict, dict):
        return []

    findings: list[tuple[str, str]] = []

    def _check(path: str, value: Any) -> None:
        if not isinstance(value, str):
            return
        matched = find_forbidden_phrase(value)
        if matched:
            findings.append((path, matched))

    _check("summary", spec_dict.get("summary"))

    for i, fr in enumerate(spec_dict.get("functional_requirements", []) or []):
        if isinstance(fr, dict):
            _check(f"functional_requirements[{i}].text", fr.get("text"))

    for i, sc in enumerate(spec_dict.get("success_criteria", []) or []):
        if isinstance(sc, dict):
            _check(f"success_criteria[{i}].metric", sc.get("metric"))
            _check(f"success_criteria[{i}].threshold", sc.get("threshold"))

    for i, ent in enumerate(spec_dict.get("key_entities", []) or []):
        if isinstance(ent, dict):
            _check(f"key_entities[{i}].description", ent.get("description"))

    for i, ec in enumerate(spec_dict.get("edge_cases", []) or []):
        if isinstance(ec, dict):
            _check(f"edge_cases[{i}].handling", ec.get("handling"))

    for i, bd in enumerate(spec_dict.get("needs_clarification", []) or []):
        if isinstance(bd, dict):
            _check(f"needs_clarification[{i}].recommended_default", bd.get("recommended_default"))
            _check(f"needs_clarification[{i}].if_rejected", bd.get("if_rejected"))

    for i, c in enumerate(spec_dict.get("self_concerns", []) or []):
        if isinstance(c, dict):
            sr = c.get("suggested_resolution")
            if sr is not None:
                _check(f"self_concerns[{i}].suggested_resolution", sr)

    return findings


def _make_default_metadata(
    ctx: SpecContext, *, feature_id: str | None = None, title: str = ""
) -> SpecMetadata:
    return SpecMetadata(
        feature_id=feature_id or f"feature-{uuid.uuid4().hex[:8]}",
        title=title,
        writer_model=ctx.settings.llm.primary_model,
        reviewer_model=ctx.settings.llm.cross_review_model,
        iterations=0,
    )


async def run_writer(ctx: SpecContext) -> Spec:
    """Stage 4: produce initial Spec (with mandatory self_concerns from Stage 5)."""
    sys = ctx.prompts.load(
        "writer",
        user_input=ctx.user_input,
        intent_primary=ctx.intent.primary if ctx.intent else "",
        intent_type=ctx.intent.intent_type if ctx.intent else "",
        intent_scope=", ".join(ctx.intent.scope) if ctx.intent else "",
        intent_confidence=f"{ctx.intent.confidence:.2f}" if ctx.intent else "",
        selected_approach=json.dumps(
            ctx.approach.model_dump(mode="json") if ctx.approach else {},
            ensure_ascii=False,
            indent=2,
        ),
        consolidated_exploration=json.dumps(
            ctx.exploration.model_dump(mode="json") if ctx.exploration else {},
            ensure_ascii=False,
            indent=2,
        ),
        repo_skeleton=ctx.repo_skeleton.text if ctx.repo_skeleton else "",
    )
    spec = await call_strict_json(
        ctx.gateway,
        role="writer",
        schema=Spec,
        messages=[Message(role="user", content="Write the specification now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="writer.initial",
        agent="writer",
        max_tokens=16384,
        max_repair_attempts=3,
    )
    # Ensure metadata is populated; LLMs sometimes omit it
    if not spec.metadata.writer_model:
        spec.metadata.writer_model = ctx.settings.llm.primary_model
    if not spec.metadata.reviewer_model:
        spec.metadata.reviewer_model = ctx.settings.llm.cross_review_model
    if not spec.metadata.feature_id:
        spec.metadata.feature_id = _make_default_metadata(ctx).feature_id
    spec.metadata.iterations = 1
    _save_artifact(ctx, "spec_iterations/spec_v1.json", spec.model_dump(mode="json"))
    return spec


async def run_rewriter(
    ctx: SpecContext,
    previous_spec: Spec,
    consolidated_review: ConsolidatedReview,
    iteration: int,
    *,
    extra_context: str = "",
    meta_review: MetaReviewResult | None = None,
) -> Spec:
    """Stage 7: rewrite spec based on reviewer findings.

    ``extra_context`` is optional additional system-level guidance to feed
    the rewriter — e.g. A1 regression-aware feedback when the previous
    rewrite made things worse.

    ``meta_review`` is the optional unified action list produced by the B4
    meta-reviewer. When present, the rewriter follows it IN ORDER as the
    primary plan-of-record (the raw axis issues are still passed for
    reference). When absent, behaviour matches the pre-B4 baseline.
    """
    all_issues = []
    for r in consolidated_review.reviews:
        for issue in r.issues:
            all_issues.append(issue.model_dump())
    all_verdicts = []
    for r in consolidated_review.reviews:
        for v in r.self_concerns_verdicts:
            all_verdicts.append(v.model_dump())

    if meta_review is not None:
        meta_review_json = json.dumps(
            meta_review.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        meta_review_block = (
            "## Meta-reviewer (B4): unified prioritized action list\n\n"
            "A meta-reviewer has read all 4 axis reviews, deduped overlapping "
            "findings, and ordered every action. **Apply these actions in ID "
            "order (META-001 first).** For any pair listed under "
            "`conflicts_with`, decide deliberately how to satisfy both — do "
            "NOT silently pick one side. If two conflicting actions cannot "
            "be reconciled, surface a `BlockingDecision` in "
            "`needs_clarification` instead of guessing.\n\n"
            f"```json\n{meta_review_json}\n```\n"
        )
    else:
        meta_review_block = ""

    sys = ctx.prompts.load(
        "writer_rewrite",
        previous_spec=json.dumps(previous_spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        all_issues=json.dumps(all_issues, ensure_ascii=False, indent=2),
        concern_verdicts=json.dumps(all_verdicts, ensure_ascii=False, indent=2),
        consolidated_exploration=json.dumps(
            ctx.exploration.model_dump(mode="json") if ctx.exploration else {},
            ensure_ascii=False,
            indent=2,
        ),
        meta_review_block=meta_review_block,
    )
    if extra_context:
        sys = sys + "\n\n## REGRESSION CONTEXT (read carefully)\n\n" + extra_context

    spec = await call_strict_json(
        ctx.gateway,
        role="writer",
        schema=Spec,
        messages=[Message(role="user", content="Rewrite the spec now.")],
        system=sys,
        run_id=ctx.run_id,
        stage=f"writer.rewrite_{iteration}",
        agent="writer_rewriter",
        max_tokens=16384,
        max_repair_attempts=3,
    )
    # Preserve identifying metadata
    spec.metadata.feature_id = previous_spec.metadata.feature_id
    if not spec.metadata.title:
        spec.metadata.title = previous_spec.metadata.title
    spec.metadata.writer_model = ctx.settings.llm.primary_model
    spec.metadata.reviewer_model = ctx.settings.llm.cross_review_model
    spec.metadata.iterations = iteration + 1
    _save_artifact(
        ctx,
        f"spec_iterations/spec_v{iteration + 1}.json",
        spec.model_dump(mode="json"),
    )
    return spec


def _save_artifact(ctx: SpecContext, rel_path: str, data: Any) -> None:
    path = ctx.run_workspace / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Segmented rewriter (DevLoop Sprint D — D3)
#
# The single-shot rewriter (``run_rewriter``) produces an entire ~30KB Spec
# JSON in one LLM call. In real runs we observed 15-30 minute calls and
# mid-call failures that lost all progress. The segmented rewriter splits
# the work into 5 dependent LLM calls — each validated independently and
# the segment-specific fields are taken from ``previous_spec`` as a
# graceful-degradation fallback if a segment fails after retries.
# ---------------------------------------------------------------------------


_SEGMENT_PROMPT_NAMES: dict[str, str] = {
    "head": "writer_rewrite_segment_head",
    "stories": "writer_rewrite_segment_stories",
    "frs": "writer_rewrite_segment_frs",
    "scs": "writer_rewrite_segment_scs",
    "tail": "writer_rewrite_segment_tail",
}

# Maps each segment name to the schema enforced and the Spec field names it
# owns (used for graceful-degradation fallback to ``previous_spec``).
_SEGMENT_FIELDS: dict[str, tuple[type[BaseModel], tuple[str, ...]]] = {
    "head": (SpecSegmentHead, ("metadata", "summary", "needs_clarification")),
    "stories": (SpecSegmentStories, ("user_stories",)),
    "frs": (SpecSegmentFRs, ("functional_requirements",)),
    "scs": (SpecSegmentSCs, ("success_criteria",)),
    "tail": (
        SpecSegmentTail,
        (
            "key_entities",
            "edge_cases",
            "assumptions",
            "out_of_scope",
            "self_concerns",
        ),
    ),
}

# Run order is fixed: head must be first (others depend on summary), stories
# must precede FRs (FRs reference US ids), FRs must precede SCs (SCs
# reference FR ids), and the tail is bundled at the end where it can see
# everything.
_SEGMENT_ORDER: tuple[str, ...] = ("head", "stories", "frs", "scs", "tail")


def _segment_fallback(previous_spec: Spec, segment: str) -> dict[str, Any]:
    """Return the fields of ``previous_spec`` owned by ``segment`` as a dict.

    Used when a segment fails after ``max_repair_attempts`` so the rest of
    the rewrite can continue with the previously-good content for that
    section instead of crashing the whole rewriter call.
    """
    _, fields = _SEGMENT_FIELDS[segment]
    dumped = previous_spec.model_dump(mode="json")
    return {f: dumped.get(f) for f in fields if f in dumped}


def _build_meta_review_block(meta_review: MetaReviewResult | None) -> str:
    """Render the meta-reviewer block exactly like ``run_rewriter`` does.

    Kept here as a small helper so the segmented rewriter shares the same
    rendering rules as the single-shot path — the prompt language stays
    consistent across the two code paths.
    """
    if meta_review is None:
        return ""
    meta_review_json = json.dumps(
        meta_review.model_dump(mode="json"), ensure_ascii=False, indent=2
    )
    return (
        "## Meta-reviewer (B4): unified prioritized action list\n\n"
        "A meta-reviewer has read all 4 axis reviews, deduped overlapping "
        "findings, and ordered every action. **Apply these actions in ID "
        "order (META-001 first).** For any pair listed under "
        "`conflicts_with`, decide deliberately how to satisfy both — do "
        "NOT silently pick one side. If two conflicting actions cannot "
        "be reconciled, surface a `BlockingDecision` in "
        "`needs_clarification` instead of guessing.\n\n"
        f"```json\n{meta_review_json}\n```\n"
    )


async def run_rewriter_segmented(
    ctx: SpecContext,
    previous_spec: Spec,
    consolidated_review: ConsolidatedReview,
    iteration: int,
    *,
    extra_context: str = "",
    meta_review: MetaReviewResult | None = None,
) -> Spec:
    """Segmented rewriter — produces Spec in 5 validated LLM calls.

    The single-shot ``run_rewriter`` packs the entire ~30KB Spec into one
    LLM call, which is slow (15-30 minute calls observed in the Mealie
    eval) and brittle (mid-call failures lose all progress). This
    implementation issues 5 dependent calls — head, stories, FRs, SCs,
    tail — and validates each independently against a per-segment partial
    schema.

    Each segment receives the previously-produced segments as context so
    the LLM can keep cross-references (e.g. FR ↔ US, SC ↔ FR) consistent.

    If a segment fails after ``max_repair_attempts``, the corresponding
    fields of ``previous_spec`` are used in its place (graceful
    degradation). The orchestrator's downstream review will surface any
    issues introduced by the fallback on the next iteration.

    Signature parity with :func:`run_rewriter` is intentional so the
    orchestrator can branch between the two via a single ``rewriter_fn``
    variable without further adaptation.
    """
    all_issues = [
        issue.model_dump()
        for r in consolidated_review.reviews
        for issue in r.issues
    ]
    all_verdicts = [
        v.model_dump()
        for r in consolidated_review.reviews
        for v in r.self_concerns_verdicts
    ]

    base_sys = ctx.prompts.load(
        "writer_rewrite",
        previous_spec=json.dumps(
            previous_spec.model_dump(mode="json"), ensure_ascii=False, indent=2
        ),
        all_issues=json.dumps(all_issues, ensure_ascii=False, indent=2),
        concern_verdicts=json.dumps(all_verdicts, ensure_ascii=False, indent=2),
        consolidated_exploration=json.dumps(
            ctx.exploration.model_dump(mode="json") if ctx.exploration else {},
            ensure_ascii=False,
            indent=2,
        ),
        meta_review_block=_build_meta_review_block(meta_review),
    )
    if extra_context:
        base_sys = (
            base_sys + "\n\n## REGRESSION CONTEXT (read carefully)\n\n" + extra_context
        )

    accumulated: dict[str, Any] = {}
    total_segments = len(_SEGMENT_ORDER)
    for idx, segment in enumerate(_SEGMENT_ORDER, start=1):
        schema, _fields = _SEGMENT_FIELDS[segment]
        prior_segments_json = json.dumps(accumulated, ensure_ascii=False, indent=2)
        suffix = ctx.prompts.load(
            _SEGMENT_PROMPT_NAMES[segment],
            prior_segments=prior_segments_json,
        )
        segment_sys = base_sys + "\n\n" + suffix

        try:
            segment_obj = await call_strict_json(
                ctx.gateway,
                role="writer",
                schema=schema,
                messages=[
                    Message(
                        role="user",
                        content=(
                            f"Rewrite segment {idx}/{total_segments} ({segment}) now."
                        ),
                    )
                ],
                system=segment_sys,
                run_id=ctx.run_id,
                stage=f"writer.rewrite_segmented_{iteration}.{segment}",
                agent="writer_rewriter_segmented",
                max_tokens=16384,
                max_repair_attempts=3,
            )
            segment_dict = segment_obj.model_dump(mode="json")
            logger.info(
                "rewriter segment %d/%d (%s) completed for iteration %d",
                idx,
                total_segments,
                segment,
                iteration,
            )
        except (ValueError, ValidationError) as exc:
            logger.error(
                "rewriter segment %d/%d (%s) failed for iteration %d: %s — "
                "falling back to previous_spec",
                idx,
                total_segments,
                segment,
                iteration,
                exc,
            )
            segment_dict = _segment_fallback(previous_spec, segment)
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=f"writer.rewrite_segmented_{iteration}.{segment}",
                event="segment_fallback",
                detail={
                    "iteration": iteration,
                    "segment": segment,
                    "error": str(exc),
                },
            )

        accumulated.update(segment_dict)

    accumulated.setdefault("schema_version", previous_spec.schema_version)

    spec = Spec.model_validate(accumulated)

    # Preserve identifying metadata (mirrors ``run_rewriter``)
    spec.metadata.feature_id = previous_spec.metadata.feature_id
    if not spec.metadata.title:
        spec.metadata.title = previous_spec.metadata.title
    spec.metadata.writer_model = ctx.settings.llm.primary_model
    spec.metadata.reviewer_model = ctx.settings.llm.cross_review_model
    spec.metadata.iterations = iteration + 1
    _save_artifact(
        ctx,
        f"spec_iterations/spec_v{iteration + 1}.json",
        spec.model_dump(mode="json"),
    )
    return spec
