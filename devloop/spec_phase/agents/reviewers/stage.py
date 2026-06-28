"""Stage 6 + 8: Multi-angle independent reviewers.

Base angles: architecture / completeness / executability / consistency.
Optional 5th angle (Sprint C — C1): ``adversarial`` — red-team reviewer that
imagines a literal-minded code agent and surfaces scenarios where strictly
following the spec ships wrong, insecure, or exploitable code. Enabled
selectively via :func:`_should_run_adversarial` and the
``settings.reviewer.force_adversarial`` / ``disable_adversarial`` flags.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from devloop.llm import Message, call_react_with_tools
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.schemas import (
    ConcernVerdict,
    ConfirmedIntent,
    ConsolidatedReview,
    ReviewerType,
    ReviewIssue,
    ReviewResult,
    Severity,
    Spec,
    Verdict,
)
from devloop.tools import AgentRole, AgentScratchpad, ToolContext

logger = logging.getLogger(__name__)


ANGLE_DESCRIPTIONS = {
    "architecture": "alignment with project's existing architecture, patterns, and conventions",
    "completeness": "coverage of all aspects implied by user intent (user stories, edge cases, NFRs)",
    "executability": "whether a downstream plan/code agent can act on this spec without further clarification",
    "consistency": "internal self-consistency (no contradictions between FRs, entities, assumptions)",
    "adversarial": (
        "adversarial red-team analysis — find scenarios where a literal-minded code agent "
        "strictly following this spec would ship wrong, insecure, or exploitable code"
    ),
}


# Sprint C — C1: scopes whose mere presence triggers the adversarial reviewer.
_ADVERSARIAL_SCOPE_TRIGGERS: frozenset[str] = frozenset(
    {"security", "auth", "external_integration", "payment"}
)

# Sprint C — C1: substrings whose appearance in intent.primary triggers the
# adversarial reviewer. The list is intentionally aggressive: each keyword
# names a feature surface that has historically produced a class of subtle
# defects when shipped by a literal-minded code agent (e.g. raw LLM output
# in logs, image-upload size-vs-rate-limit ordering, password reset flows
# that leak account existence).
_ADVERSARIAL_PRIMARY_KEYWORDS: frozenset[str] = frozenset(
    {
        "upload",
        "image",
        "file",
        "prompt",
        "llm",
        "openai",
        "password",
        "token",
        "secret",
        "pii",
        "payment",
    }
)


def _should_run_adversarial(intent: ConfirmedIntent | None) -> bool:
    """Decide whether to run the adversarial red-team reviewer for ``intent``.

    Returns ``True`` when the spec covers a security-relevant surface where
    a literal-minded code agent tends to ship subtle defects (auth, payment,
    LLM/file uploads, secret handling, etc.). The signal is:

    * the confirmed intent's ``scope`` overlaps
      :data:`_ADVERSARIAL_SCOPE_TRIGGERS`, **or**
    * its ``primary`` text (lowercased) contains any of the
      :data:`_ADVERSARIAL_PRIMARY_KEYWORDS`.

    ``None`` intent returns ``False`` — without a confirmed intent we cannot
    justify the extra LLM cost.
    """
    if intent is None:
        return False
    scope_lc = {str(s).lower() for s in intent.scope}
    if scope_lc & _ADVERSARIAL_SCOPE_TRIGGERS:
        return True
    primary_lc = (intent.primary or "").lower()
    return any(kw in primary_lc for kw in _ADVERSARIAL_PRIMARY_KEYWORDS)


def _intent_specific_guidance(intent_type: str) -> str:
    """Return reviewer guidance tailored to the intent type.

    P0-3 fix: different intent types require different mental models. A
    spec for ``add_feature`` describes what to BUILD; reviewers must not
    fault it for "code doesn't exist" (that's the point — we're adding it).
    A spec for ``fix_bug`` describes existing buggy code; reviewers must
    verify the spec accurately reflects current source.
    """
    it = (intent_type or "").lower()
    if it in {"add_feature", "remove_feature"}:
        verb = "ADD" if it == "add_feature" else "REMOVE"
        return (
            f"## Intent context: this spec is for a NEW capability ({verb})\n\n"
            "**MANDATORY MENTAL MODEL**: the spec describes work to be implemented. "
            "It is NOT a description of code that already exists. Therefore:\n"
            "- ✅ DO check that the spec's *plan* would integrate cleanly with existing code "
            "(layer boundaries, existing entity names, existing patterns).\n"
            "- ✅ DO verify cited code references for *existing* code that the new feature "
            "will touch or extend (e.g. existing schemas, services to call, routes to mount under).\n"
            "- ❌ DO NOT flag 'X function does not exist in the checkout' for symbols the "
            "spec proposes to CREATE — that's the goal of the feature.\n"
            "- ❌ DO NOT require evidence that the new feature is already implemented.\n"
            "- ❌ DO NOT mark CRITICAL for 'spec changes not present in worktree' — the worktree "
            "is the baseline; the spec describes what comes next.\n"
        )
    if it == "fix_bug":
        return (
            "## Intent context: this spec is for a BUG FIX\n\n"
            "**MANDATORY MENTAL MODEL**: there is existing buggy code, and the spec "
            "must accurately reflect it. Therefore:\n"
            "- ✅ DO verify the spec accurately names the buggy function / file / line.\n"
            "- ✅ DO check that the fix is minimal (per typical bug-fix discipline).\n"
            "- ✅ DO require a reproduction test that FAILS before the fix and PASSES after.\n"
            "- ❌ DO NOT accept hand-wavy bug attribution — the spec must point at the "
            "actual defect with evidence.\n"
            "- ❌ DO NOT accept fixes that change unrelated behavior — bug fixes should be surgical.\n"
        )
    if it == "refactor":
        return (
            "## Intent context: this spec is for a REFACTOR\n\n"
            "**MANDATORY MENTAL MODEL**: existing code works; the spec describes "
            "structural changes that must preserve behavior. Therefore:\n"
            "- ✅ DO verify the spec preserves the public contract (response shape, "
            "API path, behavior).\n"
            "- ✅ DO require regression-test coverage proving no behavior change.\n"
            "- ✅ DO verify the new structure aligns with existing conventions.\n"
            "- ❌ DO NOT accept refactors that change observable behavior unless the "
            "spec explicitly calls out and justifies the behavior change.\n"
        )
    if it == "perf_opt":
        return (
            "## Intent context: this spec is for a PERFORMANCE OPTIMIZATION\n\n"
            "**MANDATORY MENTAL MODEL**: existing code is functionally correct but slow; "
            "the spec describes how to make it faster WITHOUT changing observable behavior. Therefore:\n"
            "- ✅ DO verify the spec quantifies the target (e.g. query count, p95 latency, "
            "throughput) with a concrete threshold.\n"
            "- ✅ DO require a regression test that proves the speed-up (e.g. query-count assertion).\n"
            "- ✅ DO require behavior-preservation tests (all existing tests still pass + a "
            "byte-for-byte response equivalence check where applicable).\n"
            "- ❌ DO NOT accept optimization specs without a measurable target.\n"
            "- ❌ DO NOT accept optimizations that change response shape, even subtly "
            "(e.g. nested array order under selectinload vs joinedload).\n"
        )
    return (
        "## Intent context: general spec\n\n"
        "Apply the angle-specific checks below without a preset mental model. "
        "If the intent_type was not classified, do not assume the spec must reference "
        "already-existing code OR must propose only new code — verify according to "
        "what the spec itself claims.\n"
    )


def _render_reviewer_prompt(ctx: SpecContext, angle: ReviewerType, spec: Spec) -> str:
    angle_prompt = ctx.prompts.load(f"reviewer/{angle}")
    intent_type = ctx.intent.intent_type if ctx.intent else ""
    base = ctx.prompts.load(
        "reviewer/_base",
        angle_title=angle.title(),
        angle_description=ANGLE_DESCRIPTIONS[angle],
        spec=json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        consolidated_exploration=json.dumps(
            ctx.exploration.model_dump(mode="json") if ctx.exploration else {},
            ensure_ascii=False,
            indent=2,
        ),
        intent_primary=ctx.intent.primary if ctx.intent else "",
        intent_type=intent_type,
        intent_specific_guidance=_intent_specific_guidance(intent_type),
    )
    return angle_prompt.replace("{{base_prompt}}", base)


VERDICT_RE = re.compile(
    r"^\s*(?:final\s+)?verdict\s*:\s*(pass|fail|needs_refine)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CONCERN_VERDICT_RE = re.compile(
    r"^\s*[-*]\s*\*?\*?(?P<loc>[^*:\n]+?)\*?\*?\s*[:\-]\s*"
    r"(?P<vdict>resolved|confirmed_problem|uncertain)\b[\s\-:]*"
    r"(?P<expl>.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_verdict(text: str) -> Verdict:
    """Find the last well-formed VERDICT: line. Defaults to needs_refine on absence."""
    matches = list(VERDICT_RE.finditer(text))
    if not matches:
        return "needs_refine"
    v = matches[-1].group(1).lower()
    if v == "pass":
        return "pass"
    if v == "fail":
        return "fail"
    return "needs_refine"


def _extract_concern_verdicts(
    text: str, spec_concern_locations: list[str]
) -> list[ConcernVerdict]:
    out: list[ConcernVerdict] = []
    for m in CONCERN_VERDICT_RE.finditer(text):
        loc = m.group("loc").strip()
        verdict = m.group("vdict").lower()
        expl = m.group("expl").strip() or f"Reviewer indicated {verdict}"
        out.append(ConcernVerdict(concern_location=loc, verdict=verdict, explanation=expl))
    if not out and spec_concern_locations:
        # Fall back: assume all concerns are uncertain
        out = [
            ConcernVerdict(
                concern_location=loc, verdict="uncertain", explanation="No explicit verdict from reviewer."
            )
            for loc in spec_concern_locations
        ]
    return out


async def run_one_reviewer(
    ctx: SpecContext, angle: ReviewerType, spec: Spec
) -> ReviewResult:
    sys = _render_reviewer_prompt(ctx, angle, spec)

    scratchpad = AgentScratchpad()
    tool_ctx = ToolContext(
        repo_path=ctx.repo_path,
        commit_hash=ctx.commit_hash,
        scratchpad=scratchpad,
        cache=ctx.cache,
        run_id=ctx.run_id,
        agent_name=f"reviewer_{angle}",
        enable_cache=True,
    )

    tool_specs = ctx.tools.specs_for(AgentRole.REVIEWER)
    executor, _counter = ctx.tools.make_executor(
        tool_ctx,
        role=AgentRole.REVIEWER,
        trace=ctx.trace,
        soft_limit=ctx.settings.reviewer.max_tool_calls_soft,
        hard_limit=ctx.settings.reviewer.max_tool_calls_hard,
        global_counter=ctx.run_counter,
    )

    user_msg = Message(
        role="user",
        content=(
            f"Review the spec from the {angle} angle. Verify spec claims with the "
            "tools. Flag any critical/high/medium issues via flag_issue. End your "
            "message with exactly 'VERDICT: pass | fail | needs_refine'."
        ),
    )

    final_text, tool_calls_made = await call_react_with_tools(
        ctx.gateway,
        role="reviewer",
        messages=[user_msg],
        system=sys,
        tools=tool_specs,
        tool_executor=executor,
        max_iterations=40,
        max_tokens=8192,
        run_id=ctx.run_id,
        stage=f"review.{angle}",
        agent=f"reviewer_{angle}",
    )

    issues: list[ReviewIssue] = []
    for i, rec in enumerate(scratchpad.issues, start=1):
        issues.append(
            ReviewIssue(
                id=f"{angle.upper()[:4]}-{i:03d}",
                reviewer_type=angle,
                severity=Severity(rec["severity"]),
                location=rec["location"],
                description=rec["description"],
                evidence=rec["evidence"],
                suggested_action=rec.get("suggested_action"),
            )
        )

    verdict = _extract_verdict(final_text)
    concern_verdicts = _extract_concern_verdicts(
        final_text, [c.location for c in spec.self_concerns]
    )

    return ReviewResult(
        reviewer_type=angle,
        judge_model=ctx.settings.llm.cross_review_model,
        verdict=verdict,
        issues=issues,
        self_concerns_verdicts=concern_verdicts,
        tool_calls_used=tool_calls_made,
        summary=final_text[-500:] if final_text else "",
    )


async def run_review_stage(
    ctx: SpecContext, spec: Spec, *, iteration: int
) -> ConsolidatedReview:
    """Run the configured reviewers in parallel, then consolidate.

    Runs the 4 base angles plus an optional 5th adversarial red-team angle
    when :func:`_should_run_adversarial` (or the manual ``force_adversarial``
    setting) indicates the spec covers a security-relevant surface.
    """
    angles_enabled = ctx.settings.orchestrator.enable_multi_reviewer
    angles: list[ReviewerType] = list(ctx.settings.reviewer.angles)  # type: ignore[arg-type]
    if not angles_enabled:
        # MVP single reviewer
        angles = ["architecture"]

    # Sprint C — C1: 5th adversarial red-team reviewer (selective).
    # Precedence: disable_adversarial (hard kill switch) > force_adversarial
    # (manual on) > intent-based heuristic. This is also applied in MVP
    # single-reviewer mode so that ``force_adversarial`` works there.
    reviewer_cfg = ctx.settings.reviewer
    if reviewer_cfg.disable_adversarial:
        run_adversarial = False
    elif reviewer_cfg.force_adversarial:
        run_adversarial = True
    else:
        run_adversarial = _should_run_adversarial(ctx.intent)
    if run_adversarial and "adversarial" not in angles:
        angles.append("adversarial")
    elif not run_adversarial and "adversarial" in angles:
        angles = [a for a in angles if a != "adversarial"]

    ctx.trace.record_stage_event(
        run_id=ctx.run_id, stage=f"review.iter_{iteration}", event="start", detail={"angles": angles}
    )

    if ctx.settings.reviewer.parallel and len(angles) > 1:
        results = await asyncio.gather(
            *[run_one_reviewer(ctx, a, spec) for a in angles],
            return_exceptions=True,
        )
    else:
        results = []
        for a in angles:
            try:
                results.append(await run_one_reviewer(ctx, a, spec))
            except Exception as e:
                results.append(e)

    reviews: list[ReviewResult] = []
    for a, r in zip(angles, results, strict=False):
        if isinstance(r, Exception):
            logger.warning("Reviewer %s failed: %s", a, r)
            reviews.append(
                ReviewResult(
                    reviewer_type=a,
                    judge_model=ctx.settings.llm.cross_review_model,
                    verdict="needs_refine",
                    issues=[
                        ReviewIssue(
                            id=f"{a.upper()[:4]}-ERR",
                            reviewer_type=a,
                            severity=Severity.HIGH,
                            location="reviewer-process",
                            description=f"Reviewer {a} crashed during review",
                            evidence=f"{type(r).__name__}: {r}",
                        )
                    ],
                    summary=f"[error] {r}",
                )
            )
        else:
            reviews.append(r)

    for r in reviews:
        _save_artifact(
            ctx,
            f"spec_iterations/review_v{iteration}_{r.reviewer_type}.json",
            r.model_dump(mode="json"),
        )

    total_issues = sum(len(r.issues) for r in reviews)
    critical_issues = sum(r.critical_issue_count for r in reviews)

    if all(r.verdict == "pass" for r in reviews):
        overall: Verdict = "pass"
    elif any(r.verdict == "fail" for r in reviews) or critical_issues > 0:
        overall = "fail"
    else:
        overall = "needs_refine"

    consolidated = ConsolidatedReview(
        reviews=reviews,
        overall_verdict=overall,
        total_issues=total_issues,
        critical_issues=critical_issues,
    )
    _save_artifact(
        ctx,
        f"spec_iterations/review_v{iteration}_consolidated.json",
        consolidated.model_dump(mode="json"),
    )
    ctx.trace.record_stage_event(
        run_id=ctx.run_id,
        stage=f"review.iter_{iteration}",
        event="complete",
        detail={"verdict": overall, "total_issues": total_issues, "critical": critical_issues},
    )
    return consolidated


def _save_artifact(ctx: SpecContext, rel_path: str, data: Any) -> None:
    path = ctx.run_workspace / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
