"""Stage 2: Multi-perspective active code exploration.

Each perspective explorer runs a ReAct loop with the 11 code tools +
mark_as_relevant + take_note. All 5 perspectives run in parallel
via asyncio.gather. Output is then merged by a Consolidator agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from devloop.llm import Message, call_react_with_tools, call_strict_json
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.explorer.cache import (
    compute_perspective_cache_key,
    get_cached_perspective,
    intent_summary_from,
    set_cached_perspective,
)
from devloop.spec_phase.schemas import (
    Conflict,
    ConsolidatedExploration,
    Perspective,
    PerspectiveType,
    RelevantArtifact,
)
from devloop.spec_phase.validators.coverage_gap_detector import CoverageGap
from devloop.tools import AgentRole, AgentScratchpad, ToolContext

logger = logging.getLogger(__name__)


PERSPECTIVE_FOCUS = {
    "data": "data models, persistence, schema, migrations",
    "api": "HTTP endpoints, request/response models, middleware",
    "ui": "frontend components, routes, state management",
    "test": "tests, testing frameworks, conventions",
    "history": "git log, commit history, design evolution",
    "security": "auth flows, input validation, secrets, rate-limit, file upload, prompt-injection defense",
    "performance": "N+1 patterns, missing indexes, eager-loading opportunities, async bottlenecks",
}


def _render_explorer_prompt(
    ctx: SpecContext, perspective: str
) -> str:
    """Build a per-perspective system prompt by combining the perspective .md and the _base."""
    perspective_prompt = ctx.prompts.load(f"explorer/{perspective}")
    base_prompt = ctx.prompts.load(
        "explorer/_base",
        perspective=perspective,
        perspective_focus=PERSPECTIVE_FOCUS.get(perspective, perspective),
        intent_primary=ctx.intent.primary if ctx.intent else "",
        intent_scope=", ".join(ctx.intent.scope) if ctx.intent else "",
        repo_skeleton=ctx.repo_skeleton.text if ctx.repo_skeleton else "",
    )
    # Replace {{base_prompt}} marker in perspective prompt with the full base
    return perspective_prompt.replace("{{base_prompt}}", base_prompt)


async def run_one_explorer(
    ctx: SpecContext,
    perspective: PerspectiveType,
) -> Perspective:
    """Run a single perspective explorer through a ReAct loop.

    If ``settings.explorer.use_cache`` is enabled (default) the result is keyed
    by ``(cwd_path, head_commit, perspective_type, intent.primary[:200])`` and
    served from the SQLite cache on subsequent runs. TTL is governed by
    ``settings.cache.ttl_days``.
    """
    use_cache = getattr(ctx.settings.explorer, "use_cache", True)
    cache_key: str | None = None
    if use_cache:
        cache_key = compute_perspective_cache_key(
            str(ctx.repo_path),
            ctx.commit_hash,
            perspective,
            intent_summary_from(ctx.intent),
        )
        cached = get_cached_perspective(ctx.cache, cache_key)
        if cached is not None:
            logger.info(
                "explorer cache HIT perspective=%s key=%s",
                perspective,
                cache_key[:12],
            )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=f"exploration.{perspective}",
                event="cache_hit",
                detail={"cache_key": cache_key[:12]},
            )
            return cached
        logger.info(
            "explorer cache MISS perspective=%s key=%s",
            perspective,
            cache_key[:12],
        )
        ctx.trace.record_stage_event(
            run_id=ctx.run_id,
            stage=f"exploration.{perspective}",
            event="cache_miss",
            detail={"cache_key": cache_key[:12]},
        )

    perspective_obj = await _run_one_explorer_uncached(ctx, perspective)

    if use_cache and cache_key is not None:
        try:
            set_cached_perspective(ctx.cache, cache_key, perspective_obj)
        except Exception as exc:  # pragma: no cover - defensive, cache is best-effort
            logger.warning(
                "explorer cache write failed perspective=%s err=%s", perspective, exc
            )
    return perspective_obj


async def _run_one_explorer_uncached(
    ctx: SpecContext,
    perspective: PerspectiveType,
) -> Perspective:
    """Execute the explorer ReAct loop without consulting the perspective cache."""
    sys = _render_explorer_prompt(ctx, perspective)

    scratchpad = AgentScratchpad()
    tool_ctx = ToolContext(
        repo_path=ctx.repo_path,
        commit_hash=ctx.commit_hash,
        scratchpad=scratchpad,
        cache=ctx.cache,
        run_id=ctx.run_id,
        agent_name=f"explorer_{perspective}",
        enable_cache=True,
    )

    tool_specs = ctx.tools.specs_for(AgentRole.EXPLORER)
    executor, _counter = ctx.tools.make_executor(
        tool_ctx,
        role=AgentRole.EXPLORER,
        trace=ctx.trace,
        soft_limit=ctx.settings.explorer.max_tool_calls_soft,
        hard_limit=ctx.settings.explorer.max_tool_calls_hard,
        global_counter=ctx.run_counter,
    )

    user_msg = Message(
        role="user",
        content=(
            f"Begin exploration from the {perspective} perspective. "
            "Make extensive use of the tools — your goal is comprehensive understanding "
            "of code relevant to the feature. End with EXPLORATION COMPLETE when you've "
            "marked all critical artifacts and noted all key conventions."
        ),
    )

    final_text, tool_calls_made = await call_react_with_tools(
        ctx.gateway,
        role="explorer",
        messages=[user_msg],
        system=sys,
        tools=tool_specs,
        tool_executor=executor,
        max_iterations=40,  # Generous — relies on tool budget hard cap to terminate
        max_tokens=8192,
        run_id=ctx.run_id,
        stage=f"exploration.{perspective}",
        agent=f"explorer_{perspective}",
    )

    # Materialize Perspective from scratchpad
    relevant_artifacts = [
        RelevantArtifact(
            path=r["path"],
            symbols=r.get("symbols", []),
            line_ranges=[tuple(lr) for lr in r.get("line_ranges", [])],
            importance=r["importance"],
            reason=r["reason"],
            snippet=r.get("snippet", ""),
        )
        for r in scratchpad.relevant_artifacts
    ]

    # Extract any open questions from final_text (free-form)
    open_questions = _extract_open_questions(final_text)

    perspective_obj = Perspective(
        perspective_type=perspective,
        relevant_artifacts=relevant_artifacts,
        conventions_discovered=list(scratchpad.notes),
        hypotheses_checked=[],  # Not used in V1 — could be extracted from notes later
        notable_findings=[],
        open_questions=open_questions,
        iterations_used=1,
        tool_calls_used=tool_calls_made,
    )
    return perspective_obj


def _extract_open_questions(text: str) -> list[str]:
    """Extract free-form open questions from explorer final message."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # Look for lines starting with question markers
        if (
            s.endswith("?")
            or s.lower().startswith(("open question", "question:", "todo", "uncertain"))
            or (s.startswith("- ") and "?" in s)
        ):
            cleaned = s.lstrip("- ").strip()
            if cleaned and cleaned.endswith("?"):
                out.append(cleaned)
    return out[:10]


# ---- Consolidator ----


class ConsolidatorOutput(BaseModel):
    consolidated_artifacts: list[RelevantArtifact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    consolidated_conventions: list[str] = Field(default_factory=list)
    summary: str = ""


async def run_consolidator(
    ctx: SpecContext, perspectives: list[Perspective]
) -> ConsolidatedExploration:
    sys = ctx.prompts.load(
        "explorer/consolidator",
        intent_primary=ctx.intent.primary if ctx.intent else "",
        perspectives=json.dumps(
            [p.model_dump(mode="json") for p in perspectives],
            ensure_ascii=False,
            indent=2,
        ),
    )
    out = await call_strict_json(
        ctx.gateway,
        role="consolidator",
        schema=ConsolidatorOutput,
        messages=[Message(role="user", content="Consolidate the perspectives now.")],
        system=sys,
        run_id=ctx.run_id,
        stage="exploration.consolidator",
        agent="consolidator",
        max_tokens=16384,
    )

    return ConsolidatedExploration(
        perspectives=perspectives,
        conflicts=out.conflicts,
        consolidated_artifacts=out.consolidated_artifacts,
        consolidated_conventions=out.consolidated_conventions,
        summary=out.summary,
    )


async def run_exploration_stage(ctx: SpecContext) -> ConsolidatedExploration:
    """Run all selected perspectives in parallel, then consolidate.

    The set of perspectives to run is taken from ``ctx.active_perspectives``
    if it has been set (typically by the orchestrator after Stage 2 intent
    confirmation, via :func:`select_perspectives`); otherwise it falls
    back to ``ctx.settings.explorer.perspectives``.
    """
    perspectives_to_run: list[PerspectiveType] = list(
        ctx.active_perspectives or ctx.settings.explorer.perspectives
    )  # type: ignore[arg-type]
    ctx.trace.record_stage_event(
        run_id=ctx.run_id,
        stage="exploration",
        event="start",
        detail={"perspectives": perspectives_to_run},
    )

    if ctx.settings.explorer.parallel:
        results = await asyncio.gather(
            *[run_one_explorer(ctx, p) for p in perspectives_to_run],
            return_exceptions=True,
        )
    else:
        results = []
        for p in perspectives_to_run:
            try:
                results.append(await run_one_explorer(ctx, p))
            except Exception as e:
                results.append(e)

    perspectives: list[Perspective] = []
    for p, r in zip(perspectives_to_run, results, strict=False):
        if isinstance(r, Exception):
            logger.warning("Perspective %s failed: %s", p, r)
            # Insert empty placeholder so consolidator sees the gap
            perspectives.append(
                Perspective(
                    perspective_type=p,
                    relevant_artifacts=[],
                    conventions_discovered=[f"[error] perspective failed: {type(r).__name__}: {r}"],
                )
            )
        else:
            perspectives.append(r)

    # Save individual perspectives
    for p in perspectives:
        _save_artifact(
            ctx,
            f"exploration/{p.perspective_type}_perspective.json",
            p.model_dump(mode="json"),
        )

    consolidated = await run_consolidator(ctx, perspectives)
    _save_artifact(
        ctx,
        "exploration/consolidated.json",
        consolidated.model_dump(mode="json"),
    )
    ctx.trace.record_stage_event(
        run_id=ctx.run_id,
        stage="exploration",
        event="complete",
        detail={
            "artifacts": len(consolidated.consolidated_artifacts),
            "conflicts": len(consolidated.conflicts),
            "conventions": len(consolidated.consolidated_conventions),
        },
    )
    return consolidated


def _save_artifact(ctx: SpecContext, rel_path: str, data: Any) -> None:
    path = ctx.run_workspace / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ----------------------------------------------------------------------------
# B2 — Targeted re-exploration of cross-perspective coverage gaps.
#
# After the consolidator merges all parallel-explorer Perspectives, the
# orchestrator calls
# :func:`devloop.spec_phase.validators.detect_coverage_gaps` to find
# missed criticals, unresolved conflicts, and failed-explorer slots.
# For each gap it fires :func:`run_targeted_reexploration` — a single
# focused ReAct loop with a narrow prompt — and merges the resulting
# Perspective back into the ConsolidatedExploration via
# :func:`merge_targeted_perspective`.
# ----------------------------------------------------------------------------


_IMPORTANCE_PRIORITY: dict[str, int] = {
    "critical": 3,
    "relevant": 2,
    "peripheral": 1,
}


def _render_targeted_prompt(
    ctx: SpecContext, gap: CoverageGap, perspective: PerspectiveType
) -> str:
    """Build the targeted re-explorer system prompt."""
    return ctx.prompts.load(
        "explorer/targeted",
        gap_question=gap.suggested_re_explore_question,
        gap_kind=gap.kind,
        gap_detail=gap.detail,
        perspective=perspective,
        intent_primary=ctx.intent.primary if ctx.intent else "",
        intent_scope=", ".join(ctx.intent.scope) if ctx.intent else "",
        repo_skeleton=ctx.repo_skeleton.text if ctx.repo_skeleton else "",
    )


async def run_targeted_reexploration(
    ctx: SpecContext,
    gap: CoverageGap,
    *,
    perspective: PerspectiveType = "history",
    timeout_s: float = 120.0,
) -> Perspective:
    """Run a single explorer agent focused on one coverage gap.

    Uses the ``prompts/explorer/targeted.md`` system prompt rendered with the
    gap's question, so the LLM has a narrow scope: verify, refute, or close
    the specific gap rather than re-exploring the whole repo. The standard
    explorer tool budget (``settings.explorer.max_tool_calls_*``) applies, and
    a hard ``timeout_s`` wall-clock cap is enforced via :func:`asyncio.wait_for`
    so a hung agent cannot block the orchestrator's overall progress.

    The returned :class:`Perspective` is labelled with ``perspective`` (the
    caller is expected to pick a label that the original parallel run either
    failed to populate or didn't already cover — see
    :func:`pick_perspective_for_gap`) so that, once merged, the consolidator
    sees true cross-perspective coverage rather than a self-confirming echo.

    On timeout the function returns a placeholder :class:`Perspective` with
    one ``conventions_discovered`` entry describing the timeout, so the caller
    can still merge it without special-casing.
    """
    try:
        return await asyncio.wait_for(
            _run_targeted_reexploration_inner(ctx, gap, perspective=perspective),
            timeout=timeout_s,
        )
    except TimeoutError:
        logger.warning(
            "targeted re-exploration timed out after %.1fs for gap kind=%s "
            "perspective=%s",
            timeout_s,
            gap.kind,
            perspective,
        )
        return Perspective(
            perspective_type=perspective,
            relevant_artifacts=[],
            conventions_discovered=[
                f"[targeted-re-explore:timeout] gap={gap.kind} "
                f"after {timeout_s:.1f}s"
            ],
            notable_findings=[f"[targeted-re-explore:{gap.kind}] {gap.detail}"],
        )


async def _run_targeted_reexploration_inner(
    ctx: SpecContext,
    gap: CoverageGap,
    *,
    perspective: PerspectiveType,
) -> Perspective:
    """Inner body of :func:`run_targeted_reexploration` (no timeout wrapping).

    Split out so :func:`asyncio.wait_for` can wrap the entire ReAct loop and
    the timeout fallback in :func:`run_targeted_reexploration` stays simple.
    """
    sys = _render_targeted_prompt(ctx, gap, perspective)

    scratchpad = AgentScratchpad()
    tool_ctx = ToolContext(
        repo_path=ctx.repo_path,
        commit_hash=ctx.commit_hash,
        scratchpad=scratchpad,
        cache=ctx.cache,
        run_id=ctx.run_id,
        agent_name=f"explorer_targeted_{perspective}",
        enable_cache=True,
    )

    tool_specs = ctx.tools.specs_for(AgentRole.EXPLORER)
    executor, _counter = ctx.tools.make_executor(
        tool_ctx,
        role=AgentRole.EXPLORER,
        trace=ctx.trace,
        soft_limit=ctx.settings.explorer.max_tool_calls_soft,
        hard_limit=ctx.settings.explorer.max_tool_calls_hard,
        global_counter=ctx.run_counter,
    )

    user_msg = Message(
        role="user",
        content=(
            "Begin the targeted re-exploration now. Stay narrowly focused on "
            "the question above. End your final message with EXPLORATION "
            "COMPLETE when you have a concrete answer."
        ),
    )

    final_text, tool_calls_made = await call_react_with_tools(
        ctx.gateway,
        role="explorer",
        messages=[user_msg],
        system=sys,
        tools=tool_specs,
        # Targeted re-exploration is meant to be FOCUSED — a much lower
        # iteration ceiling than the 40 used for first-pass explorers
        # forces termination if the model starts wandering.
        max_iterations=20,
        max_tokens=8192,
        tool_executor=executor,
        run_id=ctx.run_id,
        stage=f"exploration.targeted_{gap.kind}",
        agent=f"explorer_targeted_{perspective}",
    )

    relevant_artifacts = [
        RelevantArtifact(
            path=r["path"],
            symbols=r.get("symbols", []),
            line_ranges=[tuple(lr) for lr in r.get("line_ranges", [])],
            importance=r["importance"],
            reason=r["reason"],
            snippet=r.get("snippet", ""),
        )
        for r in scratchpad.relevant_artifacts
    ]

    return Perspective(
        perspective_type=perspective,
        relevant_artifacts=relevant_artifacts,
        conventions_discovered=list(scratchpad.notes),
        hypotheses_checked=[],
        notable_findings=[f"[targeted-re-explore:{gap.kind}] {gap.detail}"],
        open_questions=_extract_open_questions(final_text),
        iterations_used=1,
        tool_calls_used=tool_calls_made,
    )


def pick_perspective_for_gap(
    gap: CoverageGap,
    exploration: ConsolidatedExploration,
    *,
    available: tuple[PerspectiveType, ...] = (
        "data",
        "api",
        "ui",
        "test",
        "history",
        "security",
        "performance",
    ),
) -> PerspectiveType:
    """Pick which perspective label to give a targeted re-explorer.

    Strategy:

    - ``sparse_perspective`` — re-use the same label as the empty
      perspective so its slot gets populated (the re-explorer is filling
      in for a failed first-pass agent).
    - ``singleton_critical`` / ``unresolved_conflict`` — pick a label
      *different* from the one that originally surfaced the singleton (or
      from the conflict's involved perspectives), so the detector sees
      true cross-perspective confirmation rather than the same eyes
      reporting the same finding.
    - Fallback — ``"history"`` if it is in the available set, otherwise
      the first available perspective.
    """
    primary = gap.primary_perspective
    if gap.kind == "sparse_perspective" and primary is not None:
        return primary

    perspectives_present = {p.perspective_type for p in exploration.perspectives}
    candidates = [p for p in available if p != primary]
    # Prefer a perspective that DID participate in the first pass so the
    # re-explorer's label aligns with one the consolidator already knows.
    for c in candidates:
        if c in perspectives_present:
            return c
    if candidates:
        return candidates[0]
    return "history"


def merge_targeted_perspective(
    exploration: ConsolidatedExploration,
    new_perspective: Perspective,
) -> None:
    """Merge a targeted re-exploration's :class:`Perspective` into ``exploration``.

    Appends the new Perspective to ``exploration.perspectives`` and folds
    its artifacts into ``exploration.consolidated_artifacts``:

    - same path already consolidated → keep the highest importance,
      union symbols and line_ranges, concatenate distinct reasons, prefer
      the first non-empty snippet
    - new path → append as-is

    Conventions are dedup-appended. Mutates ``exploration`` in place; no
    return value.
    """
    exploration.perspectives.append(new_perspective)

    by_path: dict[str, int] = {
        a.path: i for i, a in enumerate(exploration.consolidated_artifacts)
    }
    for art in new_perspective.relevant_artifacts:
        existing_idx = by_path.get(art.path)
        if existing_idx is None:
            exploration.consolidated_artifacts.append(art)
            by_path[art.path] = len(exploration.consolidated_artifacts) - 1
            continue
        existing = exploration.consolidated_artifacts[existing_idx]
        merged_importance: str = (
            art.importance
            if _IMPORTANCE_PRIORITY[art.importance]
            > _IMPORTANCE_PRIORITY[existing.importance]
            else existing.importance
        )
        merged_symbols = sorted(set(existing.symbols) | set(art.symbols))
        merged_ranges_set: set[tuple[int, int]] = set(existing.line_ranges) | set(
            art.line_ranges
        )
        merged_ranges = sorted(merged_ranges_set)
        merged_reason = existing.reason
        if art.reason and art.reason not in existing.reason:
            merged_reason = (
                f"{existing.reason}; {art.reason}"
                if existing.reason
                else art.reason
            )
        merged_snippet = existing.snippet or art.snippet
        exploration.consolidated_artifacts[existing_idx] = RelevantArtifact(
            path=existing.path,
            symbols=merged_symbols,
            line_ranges=merged_ranges,
            importance=merged_importance,  # type: ignore[arg-type]
            reason=merged_reason,
            snippet=merged_snippet,
        )

    seen_conventions = set(exploration.consolidated_conventions)
    for c in new_perspective.conventions_discovered:
        if c and c not in seen_conventions:
            exploration.consolidated_conventions.append(c)
            seen_conventions.add(c)
