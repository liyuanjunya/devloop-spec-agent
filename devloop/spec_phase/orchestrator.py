"""Spec phase orchestrator — the brain that runs all 9 stages.

Stage 0: preflight
Stage 1: repo skeleton scan
Stage 2: deep intent understanding
Stage 3: 5-perspective exploration + consolidation
Stage 4: 3-candidate approach brainstorm + evaluation + selection
Stage 5: spec writing (writer produces spec WITH self_concerns)
Stage 6-8: review-rewrite loop (quality-threshold driven, not iteration-count)
Stage 9: persist + finalize

Termination of Stage 6-8 loop:
- PASS: all reviewers verdict = pass
- STUCK_NEEDS_REVIEW: 3 consecutive rewrites with no shrinkage in critical+high issues
- Hard cap: max_total_iterations (default 20) as runaway protection
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog

from devloop.cache import CacheBackend
from devloop.config import Settings, load_settings
from devloop.llm import TraceWriter, build_gateway
from devloop.spec_phase.agents.approach import run_approach_stage
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.explorer import (
    merge_targeted_perspective,
    pick_perspective_for_gap,
    run_exploration_stage,
    run_targeted_reexploration,
    select_perspectives,
)
from devloop.spec_phase.agents.intent import run_intent_stage
from devloop.spec_phase.agents.reviewers import run_meta_reviewer, run_review_stage
from devloop.spec_phase.agents.writer import (
    run_rewriter,
    run_rewriter_segmented,
    run_writer,
)
from devloop.spec_phase.md_json_bridge import (
    assert_spec_roundtrip_consistent,
    find_md_only_content,
    spec_to_json,
    spec_to_markdown,
)
from devloop.spec_phase.preflight import preflight
from devloop.spec_phase.prompts_loader import PromptLoader
from devloop.spec_phase.regression_guard import (
    IssueCounts,
    RegressionGuardState,
    regression_feedback_message,
)
from devloop.spec_phase.repo_skeleton import RepoSkeleton, RepoSkeletonBuilder
from devloop.spec_phase.schemas import (
    ConsolidatedExploration,
    ConsolidatedReview,
    MetaReviewResult,
    PerspectiveType,
    ReviewIssue,
    ReviewResult,
    Severity,
    Spec,
)
from devloop.spec_phase.validators import (
    CitationProblem,
    CoverageGap,
    EscalationProblem,
    TestExecutabilityProblem,
    detect_coverage_gaps,
    find_trace_gaps,
    find_underescalated_concerns,
    verify_spec_citations,
    verify_spec_test_executability,
)
from devloop.tools import ToolRegistry, build_default_registry

logger = structlog.get_logger(__name__)


# Built-in default explorer perspectives. When ``settings.explorer.perspectives``
# matches this exactly, the orchestrator infers the user has *not* explicitly
# configured perspectives and falls back to intent-driven auto-selection (C3).
# Keep in sync with :class:`devloop.config.ExplorerConfig.perspectives` default.
DEFAULT_EXPLORER_PERSPECTIVES: tuple[PerspectiveType, ...] = (
    "data",
    "api",
    "ui",
    "test",
    "history",
)


@dataclass
class SpecRunResult:
    ok: bool
    run_id: str
    spec: Spec | None = None
    consolidated_review: ConsolidatedReview | None = None
    workspace: Path | None = None
    reason: str = ""
    suggestion: str = ""

    @classmethod
    def fail_preflight(cls, run_id: str, reason: str, suggestion: str) -> SpecRunResult:
        return cls(ok=False, run_id=run_id, reason=reason, suggestion=suggestion)


def _generate_run_id(user_input: str) -> str:
    """Compose a sortable, UTC-stamped run id with a short feature slug."""
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    short = re.sub(r"[^A-Za-z0-9_\-]+", "-", user_input)[:30].strip("-").lower() or "feature"
    return f"{ts}-{short}-{uuid.uuid4().hex[:6]}"


def inject_trace_gap_issues(spec: Spec, review: ConsolidatedReview) -> ConsolidatedReview:
    """Augment ``review`` with mechanical FR↔SC↔US trace-gap findings.

    For each :class:`TraceGap` returned by
    :func:`devloop.spec_phase.validators.find_trace_gaps`, append a HIGH
    ``executability`` :class:`ReviewIssue` so the next rewriter call sees it
    alongside the LLM reviewers' findings. The mutation is in-place and the
    same review object is returned for chaining convenience.

    When the LLM-driven reviewers said ``pass`` but mechanical gaps remain,
    the review is downgraded to ``needs_refine`` and any pre-existing
    ``executability`` reviewer's verdict is similarly downgraded so
    :pyattr:`ConsolidatedReview.all_pass` correctly returns ``False`` and the
    loop performs another rewrite. A synthetic ``executability`` review entry
    is added when none exists (e.g. single-reviewer mode running only the
    architecture angle).
    """
    gaps = find_trace_gaps(spec)
    if not gaps:
        return review

    issues = [
        ReviewIssue(
            id=f"TRACE-{i:03d}",
            reviewer_type="executability",
            severity=Severity.HIGH,
            location=gap.actor,
            description=f"[trace-matrix:{gap.kind}] {gap.detail}",
            evidence="Mechanical trace-matrix validator",
            suggested_action=(
                "Add the missing FR↔SC↔US cross-reference in "
                "related_success_criteria / related_requirements / "
                "related_user_stories so the trace matrix is complete."
            ),
        )
        for i, gap in enumerate(gaps, start=1)
    ]

    exec_review = next(
        (r for r in review.reviews if r.reviewer_type == "executability"),
        None,
    )
    if exec_review is None:
        review.reviews.append(
            ReviewResult(
                reviewer_type="executability",
                judge_model="trace-matrix-validator",
                verdict="needs_refine",
                issues=issues,
                summary=f"{len(issues)} trace-matrix gap(s) detected by mechanical validator.",
            )
        )
    else:
        exec_review.issues.extend(issues)
        if exec_review.verdict == "pass":
            exec_review.verdict = "needs_refine"

    # Recompute aggregates so downstream regression/no-progress logic sees them.
    review.total_issues = sum(len(r.issues) for r in review.reviews)
    review.critical_issues = sum(r.critical_issue_count for r in review.reviews)

    # Trace gaps are HIGH-severity, so they can flip a pass verdict to
    # needs_refine but never produce critical-class issues on their own.
    if review.overall_verdict == "pass":
        review.overall_verdict = "needs_refine"

    return review


def inject_citation_problem_issues(
    review: ConsolidatedReview,
    problems: list[CitationProblem],
    *,
    iteration: int,
) -> ConsolidatedReview:
    """Augment ``review`` with mechanical citation-verifier findings (A5).

    Each :class:`CitationProblem` becomes one HIGH ``executability``
    :class:`ReviewIssue` so the next rewriter call sees the mechanical
    findings alongside the LLM reviewers' feedback. Mirrors the
    :func:`inject_trace_gap_issues` pattern: when an ``executability``
    reviewer already exists we append to its issue list and downgrade its
    verdict from ``pass``; otherwise we synthesise a new ``executability``
    review entry. Mutates ``review`` in place and returns it for chaining.
    """
    if not problems:
        return review

    issues = [
        ReviewIssue(
            id=f"CITE-{iteration:02d}-{i:03d}",
            reviewer_type="executability",
            severity=Severity.HIGH,
            location=(
                f"{cp.fr_id}.code_references[{cp.ref_index}]"
                if cp.fr_id
                else f"code_references[{cp.ref_index}]"
            ),
            description=f"Citation verifier flagged: {cp.problem}",
            evidence=cp.detail,
            suggested_action=(
                "Open the cited file, locate the actual definition of the "
                "symbol, and update either the path, line_ranges, or symbols "
                "list so they match. If the symbol no longer applies, remove "
                "it from this code_reference."
            ),
        )
        for i, cp in enumerate(problems, start=1)
    ]

    exec_review = next(
        (r for r in review.reviews if r.reviewer_type == "executability"),
        None,
    )
    if exec_review is None:
        review.reviews.append(
            ReviewResult(
                reviewer_type="executability",
                judge_model="citation-verifier",
                verdict="needs_refine",
                issues=issues,
                summary=(
                    f"{len(issues)} mechanical citation problem(s) detected by "
                    "the citation verifier."
                ),
            )
        )
    else:
        exec_review.issues.extend(issues)
        if exec_review.verdict == "pass":
            exec_review.verdict = "needs_refine"

    # Recompute aggregates so downstream regression/no-progress logic sees them.
    review.total_issues = sum(len(r.issues) for r in review.reviews)
    review.critical_issues = sum(r.critical_issue_count for r in review.reviews)

    # Citation issues are HIGH-severity, so they can flip a pass verdict to
    # needs_refine but never produce critical-class issues on their own.
    if review.overall_verdict == "pass":
        review.overall_verdict = "needs_refine"

    return review


def inject_test_executability_issues(
    review: ConsolidatedReview,
    problems: list[TestExecutabilityProblem],
    *,
    iteration: int,
) -> ConsolidatedReview:
    """Augment ``review`` with mechanical test-executability findings (C2).

    Each :class:`TestExecutabilityProblem` becomes one HIGH ``executability``
    :class:`ReviewIssue` so the next rewriter call sees that pytest could
    not collect the spec-named test reference. Mirrors the
    :func:`inject_citation_problem_issues` and :func:`inject_trace_gap_issues`
    patterns: when an ``executability`` reviewer already exists we append
    to its issue list and downgrade its verdict from ``pass``; otherwise
    we synthesise a new ``executability`` review entry. Mutates ``review``
    in place and returns it for chaining.
    """
    if not problems:
        return review

    issues = [
        ReviewIssue(
            id=f"TEXEC-{iteration:02d}-{i:03d}",
            reviewer_type="executability",
            severity=Severity.HIGH,
            location=(
                f"{tp.test_path}::{tp.test_name}"
                if tp.test_name
                else tp.test_path
            ),
            description=f"Test-executability verifier flagged: {tp.problem}",
            evidence=tp.detail,
            suggested_action=(
                "Update the spec to reference a real, collectable pytest "
                "node id. Either fix the test path/function name to match a "
                "test that exists (or will exist) in the target repo, or "
                "remove the reference if no such test is planned."
            ),
        )
        for i, tp in enumerate(problems, start=1)
    ]

    exec_review = next(
        (r for r in review.reviews if r.reviewer_type == "executability"),
        None,
    )
    if exec_review is None:
        review.reviews.append(
            ReviewResult(
                reviewer_type="executability",
                judge_model="test-executability-verifier",
                verdict="needs_refine",
                issues=issues,
                summary=(
                    f"{len(issues)} mechanical test-executability problem(s) "
                    "detected by pytest --collect-only on generated stubs."
                ),
            )
        )
    else:
        exec_review.issues.extend(issues)
        if exec_review.verdict == "pass":
            exec_review.verdict = "needs_refine"

    # Recompute aggregates so downstream regression/no-progress logic sees them.
    review.total_issues = sum(len(r.issues) for r in review.reviews)
    review.critical_issues = sum(r.critical_issue_count for r in review.reviews)

    # Test-executability issues are HIGH-severity, so they can flip a pass
    # verdict to needs_refine but never produce critical-class issues on
    # their own.
    if review.overall_verdict == "pass":
        review.overall_verdict = "needs_refine"

    return review


def inject_escalation_problem_issues(
    review: ConsolidatedReview,
    problems: list[EscalationProblem],
    *,
    iteration: int,
) -> ConsolidatedReview:
    """Augment ``review`` with mechanical under-escalation findings (F3-A3).

    Each :class:`EscalationProblem` becomes one HIGH ``executability``
    :class:`ReviewIssue` so the next rewriter call sees the un-escalated
    multi-option concern and either moves it into ``needs_clarification``
    (a :class:`BlockingDecision`) or rewords it to a single-default
    concern. Mirrors the :func:`inject_test_executability_issues` /
    :func:`inject_citation_problem_issues` / :func:`inject_trace_gap_issues`
    patterns: when an ``executability`` reviewer already exists we append
    to its issue list and downgrade its verdict from ``pass``; otherwise
    we synthesise a new ``executability`` review entry. Mutates ``review``
    in place and returns it for chaining.
    """
    if not problems:
        return review

    issues = [
        ReviewIssue(
            id=f"ESC-{iteration:02d}-{i:03d}",
            reviewer_type="executability",
            severity=Severity.HIGH,
            location=ep.concern_location,
            description=(
                "Under-escalated multi-option concern detected by the "
                "escalation validator (F3-A3)."
            ),
            evidence=(
                f"Concern.evidence_gap at {ep.concern_location!r} contains "
                f"phrase {ep.matched_text!r}, which enumerates ≥3 "
                "implementation options. Self-concerns are for residual "
                "uncertainty the writer already resolved with a default; "
                "multi-option decisions must be escalated."
            ),
            suggested_action=ep.suggested_fix,
        )
        for i, ep in enumerate(problems, start=1)
    ]

    exec_review = next(
        (r for r in review.reviews if r.reviewer_type == "executability"),
        None,
    )
    if exec_review is None:
        review.reviews.append(
            ReviewResult(
                reviewer_type="executability",
                judge_model="escalation-validator",
                verdict="needs_refine",
                issues=issues,
                summary=(
                    f"{len(issues)} under-escalated self-concern(s) detected; "
                    "each describes ≥3 implementation options and should be "
                    "moved to needs_clarification (BlockingDecision)."
                ),
            )
        )
    else:
        exec_review.issues.extend(issues)
        if exec_review.verdict == "pass":
            exec_review.verdict = "needs_refine"

    # Recompute aggregates so downstream regression/no-progress logic sees them.
    review.total_issues = sum(len(r.issues) for r in review.reviews)
    review.critical_issues = sum(r.critical_issue_count for r in review.reviews)

    # Escalation issues are HIGH-severity, so they can flip a pass verdict to
    # needs_refine but never produce critical-class issues on their own.
    if review.overall_verdict == "pass":
        review.overall_verdict = "needs_refine"

    return review


class SpecOrchestrator:
    """End-to-end orchestrator for the spec phase."""

    def __init__(
        self,
        settings: Settings,
        *,
        cache: CacheBackend | None = None,
        tool_registry: ToolRegistry | None = None,
        prompts_dir: Path | None = None,
    ):
        self.settings = settings

        # Resolve prompts dir
        if prompts_dir is None:
            prompts_dir = Path.cwd() / "prompts"
            if not prompts_dir.is_dir():
                # Walk up looking for it
                for p in [*Path(__file__).resolve().parents]:
                    cand = p / "prompts"
                    if cand.is_dir():
                        prompts_dir = cand
                        break
        self.prompts = PromptLoader(prompts_dir)

        # Cache
        if cache is None:
            from devloop.cache import CacheBackend as CB

            settings.paths.cache_dir.mkdir(parents=True, exist_ok=True)
            cache = CB(
                settings.paths.cache_dir / "devloop.db",
                ttl_days=settings.cache.ttl_days,
            )
        self.cache = cache

        # Tools
        self.tools = tool_registry or build_default_registry()

        # Repo skeleton builder
        self.skeleton_builder = RepoSkeletonBuilder(
            cache=self.cache,
            target_tokens=settings.repo_skeleton.target_tokens,
            excluded_dirs=settings.repo_skeleton.excluded_dirs,
            supported_languages=settings.repo_skeleton.supported_languages,
        )

    async def run(self, user_input: str, repo_path: Path | str) -> SpecRunResult:
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            raise ValueError(f"Repo path is not a directory: {repo_path}")

        run_id = _generate_run_id(user_input)
        workspace = self.settings.paths.workspace_root.resolve() / run_id
        workspace.mkdir(parents=True, exist_ok=True)

        # Save input
        (workspace / "input.json").write_text(
            json.dumps(
                {
                    "user_input": user_input,
                    "repo_path": str(repo_path),
                    "run_id": run_id,
                    "started_at": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Trace writer for this run — created up-front so even preflight
        # events can be attributed to a named stage via trace.stage().
        trace = TraceWriter(workspace / "trace.jsonl")

        # Stage 0: preflight
        with trace.stage("preflight"):
            pre = preflight(user_input)
            if not pre.ok:
                logger.info("preflight rejected input: %s", pre.reason)
                (workspace / "preflight.json").write_text(
                    json.dumps(
                        {"reason": pre.reason, "suggestion": pre.suggestion},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return SpecRunResult.fail_preflight(run_id, pre.reason, pre.suggestion)

        # Build gateway with trace
        gateway = build_gateway(self.settings, trace=trace)

        ctx = SpecContext(
            run_id=run_id,
            user_input=user_input,
            repo_path=repo_path,
            workspace_root=self.settings.paths.workspace_root.resolve(),
            settings=self.settings,
            gateway=gateway,
            tools=self.tools,
            prompts=self.prompts,
            cache=self.cache,
            trace=trace,
            skeleton_builder=self.skeleton_builder,
        )

        trace.record_stage_event(run_id=run_id, stage="orchestrator", event="start", detail={})

        # Register run with gateway counter so it can aggregate per-run stats
        ctx.run_counter = gateway.register_run(run_id)
        try:
            # Stage 1: repo skeleton
            with ctx.trace.stage("skeleton"):
                ctx.repo_skeleton = await self._stage_skeleton(ctx)

            # Stage 2: intent
            with ctx.trace.stage("intent"):
                ctx.intent = await run_intent_stage(ctx, max_rounds=3)

            # Intent-driven perspective auto-selection (C3). If the user has
            # explicitly configured ``settings.explorer.perspectives`` (i.e. it
            # differs from the built-in default), that list wins; otherwise the
            # active list is derived from the confirmed intent.
            ctx.active_perspectives = self._resolve_active_perspectives(ctx)
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage="intent",
                event="perspectives_selected",
                detail={
                    "active_perspectives": list(ctx.active_perspectives),
                    "intent_type": ctx.intent.intent_type if ctx.intent else None,
                    "scope": list(ctx.intent.scope) if ctx.intent else [],
                },
            )
            logger.info(
                "perspectives selected",
                run_id=ctx.run_id,
                active_perspectives=list(ctx.active_perspectives),
                intent_type=ctx.intent.intent_type if ctx.intent else None,
                scope=list(ctx.intent.scope) if ctx.intent else [],
            )

            # Stage 3: exploration
            with ctx.trace.stage("exploration"):
                ctx.exploration = await run_exploration_stage(ctx)

            # Stage 3.5 (B2): cross-perspective coverage-gap re-exploration.
            # Fires up to N targeted explorers in parallel to plug gaps the
            # first-pass consolidation could not synthesise away (e.g. a
            # critical file flagged by exactly one perspective).
            with ctx.trace.stage("exploration_targeted_reexplore"):
                ctx.exploration = await self._run_targeted_reexplorations(
                    ctx, ctx.exploration
                )

            # Stage 4: approach
            with ctx.trace.stage("approach"):
                ctx.approach = await run_approach_stage(ctx)

            # Stage 5: write
            with ctx.trace.stage("writer"):
                ctx.spec = await run_writer(ctx)
                self._assert_spec_consistent(ctx, ctx.spec, stage="writer")

            # Stage 6-8: review-rewrite loop (each iteration is wrapped inside
            # _review_rewrite_loop with stage("review_iter_{n}") and
            # stage("rewriter_iter_{n}") so per-iteration cost is attributable).
            ctx.consolidated_review = await self._review_rewrite_loop(ctx)

            # Stage 9: finalize
            with ctx.trace.stage("finalize"):
                self._finalize(ctx)
        finally:
            gateway.unregister_run(run_id)

        trace.record_stage_event(
            run_id=run_id,
            stage="orchestrator",
            event="complete",
            detail={
                "verdict": ctx.consolidated_review.overall_verdict if ctx.consolidated_review else None,
                "iterations": ctx.spec.metadata.iterations if ctx.spec else 0,
                "needs_review": ctx.spec.metadata.needs_review if ctx.spec else False,
            },
        )

        return SpecRunResult(
            ok=True,
            run_id=run_id,
            spec=ctx.spec,
            consolidated_review=ctx.consolidated_review,
            workspace=workspace,
        )

    # -----------------------------------------------------------------

    def _assert_spec_consistent(
        self,
        ctx: SpecContext,
        spec: Spec,
        *,
        stage: str,
        iteration: int = 0,
    ) -> None:
        """Defensive md↔json drift check after writer/rewriter.

        Logs an error on drift but does not abort the pipeline — A5-style
        executability-issue plumbing isn't in place yet, so the run continues
        and downstream review will still surface real correctness problems.
        """
        try:
            assert_spec_roundtrip_consistent(spec)
        except ValueError as exc:
            logger.error(
                "spec md/json roundtrip drift detected",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                error=str(exc),
            )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="md_json_roundtrip_drift",
                detail={"iteration": iteration, "error": str(exc)},
            )
            return

        unmapped = find_md_only_content(spec)
        if unmapped:
            logger.error(
                "spec markdown contains content not derivable from Spec object",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                unmapped=unmapped,
            )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="md_only_content_detected",
                detail={"iteration": iteration, "unmapped": unmapped},
            )

    def _verify_citations(
        self,
        ctx: SpecContext,
        spec: Spec,
        *,
        stage: str,
        iteration: int,
    ) -> list[CitationProblem]:
        """Run the mechanical citation verifier and log + trace its findings.

        Returns the list of problems so the caller can decide whether to inject
        them into the current review iteration (and consume budget) or simply
        mark the spec ``needs_review``.
        """
        problems = verify_spec_citations(ctx.repo_path, spec)
        if problems:
            logger.warning(
                "citation verifier found problems",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                count=len(problems),
            )
            for cp in problems:
                logger.info(
                    "citation problem",
                    run_id=ctx.run_id,
                    fr_id=cp.fr_id,
                    ref_index=cp.ref_index,
                    path=cp.path,
                    problem=cp.problem,
                    detail=cp.detail,
                )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="citation_problems",
                detail={
                    "iteration": iteration,
                    "count": len(problems),
                    "problems": [
                        {
                            "fr_id": cp.fr_id,
                            "ref_index": cp.ref_index,
                            "path": cp.path,
                            "line_ranges": [list(r) for r in cp.line_ranges],
                            "problem": cp.problem,
                            "detail": cp.detail,
                        }
                        for cp in problems
                    ],
                },
            )
        return problems

    def _verify_test_executability(
        self,
        ctx: SpecContext,
        spec: Spec,
        *,
        stage: str,
        iteration: int,
    ) -> list[TestExecutabilityProblem]:
        """Run the mechanical test-executability verifier and log + trace findings (C2).

        Extracts every ``tests/.../*.py[::func]`` reference from ``spec``,
        generates pytest stubs in a tempdir, and runs
        ``pytest --collect-only`` to verify each reference would actually
        be collectable. Returns the resulting :class:`TestExecutabilityProblem`
        list so the caller can decide whether to inject the problems into
        the current review iteration (and consume budget) or mark the spec
        ``needs_review``.

        Errors raised by the validator itself are caught so a buggy
        subprocess can never halt the orchestrator — the executability
        check simply degrades to "no problems found" with a trace event.
        """
        try:
            problems = verify_spec_test_executability(
                spec,
                target_repo=ctx.repo_path,
                timeout_s=ctx.settings.orchestrator.test_executability_timeout_s,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "test-executability verifier raised; treating as no problems",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                error=f"{type(exc).__name__}: {exc}",
            )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="test_executability_error",
                detail={"iteration": iteration, "error": f"{type(exc).__name__}: {exc}"},
            )
            return []

        if problems:
            logger.warning(
                "test-executability verifier found problems",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                count=len(problems),
            )
            for tp in problems:
                logger.info(
                    "test executability problem",
                    run_id=ctx.run_id,
                    test_path=tp.test_path,
                    test_name=tp.test_name,
                    problem=tp.problem,
                    detail=tp.detail,
                )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="test_executability_problems",
                detail={
                    "iteration": iteration,
                    "count": len(problems),
                    "problems": [
                        {
                            "test_path": tp.test_path,
                            "test_name": tp.test_name,
                            "problem": tp.problem,
                            "detail": tp.detail,
                        }
                        for tp in problems
                    ],
                },
            )
        return problems

    def _verify_under_escalation(
        self,
        ctx: SpecContext,
        spec: Spec,
        *,
        stage: str,
        iteration: int,
    ) -> list[EscalationProblem]:
        """Run the F3-A3 under-escalation backup validator and log + trace findings.

        The pydantic ``Concern.evidence_gap`` validator already blocks new
        concerns at schema construction time, so this method is a defense
        in depth: it catches under-escalated concerns that somehow slipped
        past pydantic (e.g. a legacy spec deserialised from disk with
        validation skipped, or a non-pydantic load path).

        Returns the list of :class:`EscalationProblem` records so the
        caller can inject HIGH ``executability`` issues into the current
        review. An empty list means every self-concern is appropriately
        scoped (single-default uncertainty) or already escalated.

        Errors raised by the validator itself are caught so a buggy regex
        can never halt the orchestrator — the check degrades to "no
        problems found" with a trace event.
        """
        if not getattr(
            ctx.settings.orchestrator, "escalation_check_enabled", True
        ):
            return []

        try:
            problems = find_underescalated_concerns(spec)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "escalation validator raised; treating as no problems",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                error=f"{type(exc).__name__}: {exc}",
            )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="escalation_error",
                detail={"iteration": iteration, "error": f"{type(exc).__name__}: {exc}"},
            )
            return []

        if problems:
            logger.warning(
                "escalation validator found under-escalated concerns",
                run_id=ctx.run_id,
                stage=stage,
                iteration=iteration,
                count=len(problems),
            )
            for ep in problems:
                logger.info(
                    "escalation problem",
                    run_id=ctx.run_id,
                    concern_location=ep.concern_location,
                    matched_text=ep.matched_text,
                )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=stage,
                event="escalation_problems",
                detail={
                    "iteration": iteration,
                    "count": len(problems),
                    "problems": [
                        {
                            "concern_location": ep.concern_location,
                            "matched_text": ep.matched_text,
                            "suggested_fix": ep.suggested_fix,
                        }
                        for ep in problems
                    ],
                },
            )
        return problems

    async def _stage_skeleton(self, ctx: SpecContext) -> RepoSkeleton:
        ctx.trace.record_stage_event(
            run_id=ctx.run_id, stage="skeleton", event="start", detail={"repo": str(ctx.repo_path)}
        )
        # Scan blocks (tree-sitter is sync) — run in a thread to avoid blocking the loop
        skeleton = await asyncio.to_thread(self.skeleton_builder.build, ctx.repo_path)
        (ctx.run_workspace / "context").mkdir(exist_ok=True)
        (ctx.run_workspace / "context" / "skeleton.json").write_text(
            json.dumps(skeleton.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ctx.trace.record_stage_event(
            run_id=ctx.run_id,
            stage="skeleton",
            event="complete",
            detail={
                "commit_hash": skeleton.commit_hash[:12],
                "files": skeleton.total_files,
                "languages": skeleton.languages,
            },
        )
        return skeleton

    def _resolve_active_perspectives(self, ctx: SpecContext) -> list[PerspectiveType]:
        """Resolve the active explorer perspective list for this run.

        Honors an explicit user configuration on ``settings.explorer.perspectives``
        (anything that differs from the built-in default
        :data:`DEFAULT_EXPLORER_PERSPECTIVES` is treated as explicit); otherwise
        defers to :func:`select_perspectives` for intent-driven auto-selection.

        Falls back to the configured list when ``ctx.intent`` is unexpectedly
        missing, so the orchestrator never produces an empty perspective set.
        """
        configured = list(ctx.settings.explorer.perspectives)
        explicit_override: list[PerspectiveType] | None = None
        if tuple(configured) != DEFAULT_EXPLORER_PERSPECTIVES:
            explicit_override = configured  # type: ignore[assignment]

        if ctx.intent is None:
            # Should not happen in normal flow, but stay defensive: fall back
            # to whatever is configured (or the built-in default).
            return explicit_override if explicit_override is not None else list(configured)  # type: ignore[return-value]

        return select_perspectives(ctx.intent, explicit_override=explicit_override)

    async def _run_targeted_reexplorations(
        self,
        ctx: SpecContext,
        exploration: ConsolidatedExploration,
    ) -> ConsolidatedExploration:
        """B2: detect coverage gaps and fire targeted re-explorers in parallel.

        Inspects ``exploration`` for cross-perspective coverage gaps via
        :func:`detect_coverage_gaps`, fires up to
        ``settings.explorer.max_targeted_reexplorations`` focused re-explorers
        in parallel (one per gap), then merges each new :class:`Perspective`
        back into ``exploration`` via :func:`merge_targeted_perspective`.

        Hard caps and guards:

        - Setting ``max_targeted_reexplorations`` to ``0`` disables the
          stage entirely (returns ``exploration`` unchanged, no detection).
        - At most ``max_targeted_reexplorations`` gaps are processed even if
          the detector finds more — runaway re-exploration is the failure
          mode we are trying to *prevent*, so the cap is firm.
        - Per-call timeouts are enforced inside
          :func:`run_targeted_reexploration` itself; this method only
          surfaces unhandled exceptions via :func:`asyncio.gather` with
          ``return_exceptions=True`` so one bad re-explorer cannot poison
          the batch.

        Mutates ``exploration`` in place (also returns it for chaining) and
        re-saves ``exploration/consolidated.json`` with the augmented data
        so on-disk artifacts stay consistent with the in-memory state.
        """
        max_n = getattr(
            ctx.settings.explorer, "max_targeted_reexplorations", 0
        )
        if max_n <= 0:
            return exploration

        gaps: list[CoverageGap] = detect_coverage_gaps(exploration)
        if not gaps:
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage="exploration_targeted_reexplore",
                event="no_gaps",
                detail={"perspectives": len(exploration.perspectives)},
            )
            return exploration

        selected = gaps[:max_n]
        ctx.trace.record_stage_event(
            run_id=ctx.run_id,
            stage="exploration_targeted_reexplore",
            event="start",
            detail={
                "total_gaps": len(gaps),
                "running": len(selected),
                "kinds": [g.kind for g in selected],
            },
        )

        timeout_s = float(
            getattr(
                ctx.settings.explorer,
                "targeted_reexploration_timeout_s",
                120.0,
            )
        )

        pickers: list[PerspectiveType] = [
            pick_perspective_for_gap(g, exploration) for g in selected
        ]
        results = await asyncio.gather(
            *(
                run_targeted_reexploration(
                    ctx, g, perspective=p, timeout_s=timeout_s
                )
                for g, p in zip(selected, pickers, strict=True)
            ),
            return_exceptions=True,
        )

        merged_count = 0
        for gap, result in zip(selected, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "targeted re-explore failed for gap kind=%s: %s",
                    gap.kind,
                    result,
                )
                continue
            merge_targeted_perspective(exploration, result)
            merged_count += 1

        ctx.trace.record_stage_event(
            run_id=ctx.run_id,
            stage="exploration_targeted_reexplore",
            event="complete",
            detail={
                "gaps_total": len(gaps),
                "gaps_attempted": len(selected),
                "perspectives_merged": merged_count,
                "perspectives_total": len(exploration.perspectives),
                "consolidated_artifacts_total": len(
                    exploration.consolidated_artifacts
                ),
            },
        )

        try:
            _save_targeted_reexploration_artifact(ctx, exploration, gaps, selected)
        except Exception as exc:  # pragma: no cover - artifact write is best-effort
            logger.warning("failed to persist targeted re-exploration artifact: %s", exc)

        return exploration

    async def _run_meta_review(
        self,
        ctx: SpecContext,
        spec: Spec,
        review: ConsolidatedReview,
        *,
        iteration: int,
    ) -> MetaReviewResult | None:
        """Run the B4 meta-reviewer, persist the artifact, and trace events.

        Errors are caught so a meta-reviewer failure can never block the
        rewrite loop — it degrades gracefully to the pre-B4 behaviour
        (the rewriter falls back to raw issues).
        """
        ctx.trace.record_stage_event(
            run_id=ctx.run_id,
            stage=f"review_iter_{iteration}",
            event="meta_review_start",
            detail={
                "total_issues": review.total_issues,
                "reviewers": [r.reviewer_type for r in review.reviews],
            },
        )
        try:
            meta_review = await run_meta_reviewer(ctx, spec, review)
        except Exception as exc:
            logger.warning(
                "meta-reviewer failed at iteration %d: %s — falling back to raw issues",
                iteration,
                exc,
            )
            ctx.trace.record_stage_event(
                run_id=ctx.run_id,
                stage=f"review_iter_{iteration}",
                event="meta_review_error",
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None

        artifact_path = (
            ctx.run_workspace / "spec_iterations" / f"meta_review_v{iteration}.json"
        )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(
                meta_review.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        ctx.trace.record_stage_event(
            run_id=ctx.run_id,
            stage=f"review_iter_{iteration}",
            event="meta_review_complete",
            detail={
                "actions": len(meta_review.actions),
                "cross_axis_conflicts": len(meta_review.cross_axis_conflicts),
            },
        )
        return meta_review

    async def _review_rewrite_loop(self, ctx: SpecContext) -> ConsolidatedReview:
        spec = ctx.spec
        assert spec is not None

        max_iter = self.settings.orchestrator.max_total_iterations
        no_progress_threshold = self.settings.orchestrator.no_progress_threshold
        max_regression_retries = self.settings.orchestrator.max_regression_retries
        citation_max_attempts = self.settings.orchestrator.citation_verify_max_attempts
        test_exec_max_attempts = self.settings.orchestrator.test_executability_max_attempts

        # D3: choose between the single-shot rewriter and the segmented
        # rewriter (5 validated per-section LLM calls). Both share the same
        # call signature so the rest of the loop is rewriter-agnostic.
        rewriter_fn = (
            run_rewriter_segmented
            if self.settings.orchestrator.use_segmented_rewriter
            else run_rewriter
        )

        guard = RegressionGuardState()
        # Snapshot the last "good" spec for potential revert (A1)
        spec_snapshots: dict[int, Spec] = {0: spec.model_copy(deep=True)}

        issue_history: list[int] = []
        last_review: ConsolidatedReview | None = None
        last_delta_was_regression = False
        citation_attempts = 0
        test_exec_attempts = 0
        enable_meta = self.settings.orchestrator.enable_meta_reviewer

        for iteration in range(1, max_iter + 1):
            with ctx.trace.stage(f"review_iter_{iteration}"):
                review = await run_review_stage(ctx, spec, iteration=iteration)
                # B3: mechanical FR↔SC↔US trace-matrix gaps are surfaced as
                # HIGH executability issues so the rewriter sees them next
                # iteration. Done BEFORE the verdict / regression / no-progress
                # gates so all of them see the augmented counts.
                review = inject_trace_gap_issues(spec, review)
                # A5: mechanical citation verification — append HIGH
                # executability issues for any CodeRef whose path / line_ranges
                # / symbols don't actually line up with the file on disk. Has
                # its own per-spec retry budget to avoid infinite loops when
                # the writer keeps hallucinating.
                citation_problems = self._verify_citations(
                    ctx,
                    spec,
                    stage=f"review_iter_{iteration}",
                    iteration=iteration,
                )
                if citation_problems:
                    if citation_attempts < citation_max_attempts:
                        review = inject_citation_problem_issues(
                            review, citation_problems, iteration=iteration
                        )
                        citation_attempts += 1
                        logger.warning(
                            "forced citation rewrite %d/%d at iteration %d (%d problem(s))",
                            citation_attempts,
                            citation_max_attempts,
                            iteration,
                            len(citation_problems),
                        )
                    else:
                        logger.warning(
                            "citation problems persist after %d attempts at iteration %d; marking needs_review",
                            citation_max_attempts,
                            iteration,
                        )
                        spec.metadata.needs_review = True

                # C2: mechanical test-grounded executability check — extract
                # every ``tests/.../*.py[::func]`` reference from the spec,
                # generate pytest stubs, and run ``pytest --collect-only``
                # to verify each reference is actually collectable. Anything
                # pytest can't collect → HIGH executability ReviewIssue.
                # Has its own per-spec retry budget to avoid infinite loops
                # when the writer keeps naming bogus test paths.
                test_exec_problems = self._verify_test_executability(
                    ctx,
                    spec,
                    stage=f"review_iter_{iteration}",
                    iteration=iteration,
                )
                if test_exec_problems:
                    if test_exec_attempts < test_exec_max_attempts:
                        review = inject_test_executability_issues(
                            review, test_exec_problems, iteration=iteration
                        )
                        test_exec_attempts += 1
                        logger.warning(
                            "forced test-executability rewrite %d/%d at iteration %d (%d problem(s))",
                            test_exec_attempts,
                            test_exec_max_attempts,
                            iteration,
                            len(test_exec_problems),
                        )
                    else:
                        logger.warning(
                            "test-executability problems persist after %d attempts at iteration %d; marking needs_review",
                            test_exec_max_attempts,
                            iteration,
                        )
                        spec.metadata.needs_review = True

                # F3-A3: backup under-escalation check — surface any
                # self_concerns whose evidence_gap enumerates ≥3 options
                # as HIGH ``executability`` issues so the rewriter moves
                # them into ``needs_clarification`` (BlockingDecision).
                # Pydantic blocks new concerns at schema time, but a spec
                # loaded via a non-validated path could still slip
                # through; this is the orchestrator-level safety net.
                escalation_problems = self._verify_under_escalation(
                    ctx,
                    spec,
                    stage=f"review_iter_{iteration}",
                    iteration=iteration,
                )
                if escalation_problems:
                    review = inject_escalation_problem_issues(
                        review, escalation_problems, iteration=iteration
                    )
                    logger.warning(
                        "injected %d under-escalation issue(s) at iteration %d",
                        len(escalation_problems),
                        iteration,
                    )
                last_review = review

                # B4: meta-reviewer consolidates the (possibly augmented)
                # 4-axis review into a single prioritized action list so the
                # rewriter doesn't fix one axis and break another. Skipped
                # when the review is already all-pass (no actions needed) or
                # when there are no surfaced issues at all.
                meta_review: MetaReviewResult | None = None
                if (
                    enable_meta
                    and not review.all_pass
                    and review.total_issues > 0
                ):
                    meta_review = await self._run_meta_review(
                        ctx, spec, review, iteration=iteration
                    )

                # Persist a stamped spec at this iteration so the trail is complete
                (ctx.run_workspace / "spec_iterations").mkdir(parents=True, exist_ok=True)
                (ctx.run_workspace / "spec_iterations" / f"spec_v{iteration}.md").write_text(
                    spec_to_markdown(spec), encoding="utf-8"
                )

                # Re-persist the consolidated review *after* the B3/A5 mechanical
                # injections so the on-disk artifact reflects what the rewriter
                # actually saw (run_review_stage saves the pre-injection version).
                (ctx.run_workspace / "spec_iterations" / f"review_v{iteration}_consolidated.json").write_text(
                    json.dumps(
                        review.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                    encoding="utf-8",
                )

            # A1: regression guard — compare to previous iteration's issue counts.
            counts = IssueCounts.from_review(review)
            delta = guard.observe(iteration, counts)
            if delta.is_improved or delta.prev is None:
                spec_snapshots[iteration] = spec.model_copy(deep=True)
            last_delta_was_regression = delta.is_regression
            if delta.is_regression:
                logger.warning(
                    "REGRESSION at iteration %d: critical+high %d -> %d (delta %+d)",
                    iteration,
                    delta.prev.critical_plus_high if delta.prev else -1,
                    delta.curr.critical_plus_high,
                    delta.delta_critical_plus_high,
                )

            if review.all_pass:
                ctx.spec = spec
                logger.info("review-rewrite loop converged at iteration %d (all pass)", iteration)
                return review

            # A1: if this iteration was a regression and we still have retries,
            # revert to last good spec and force a regression-aware rewrite WITHOUT
            # advancing the no-progress counter.
            if last_delta_was_regression and guard.can_retry_regression(max_regression_retries):
                guard.consume_regression_retry()
                logger.info(
                    "Regression retry %d/%d: re-rewriting from last good spec (iter %d) with regression-aware feedback",
                    guard.regression_retries_used,
                    max_regression_retries,
                    guard.last_good_spec_iteration,
                )
                feedback = regression_feedback_message(delta)
                baseline = spec_snapshots.get(
                    guard.last_good_spec_iteration,
                    spec_snapshots[0],
                )
                with ctx.trace.stage(f"rewriter_iter_{iteration}"):
                    try:
                        spec = await rewriter_fn(
                            ctx,
                            baseline,
                            review,
                            iteration,
                            extra_context=feedback,
                            meta_review=meta_review,
                        )
                    except TypeError:
                        # Backward-compat fallback if rewriter signature is older
                        spec = await rewriter_fn(ctx, baseline, review, iteration)
                    ctx.spec = spec
                    self._assert_spec_consistent(ctx, spec, stage="rewriter", iteration=iteration)
                continue

            # If regression and budget exhausted: revert + bail out.
            if last_delta_was_regression and not guard.can_retry_regression(max_regression_retries):
                logger.error(
                    "Regression budget exhausted (%d retries used). Reverting to last good spec at iter %d.",
                    guard.regression_retries_used,
                    guard.last_good_spec_iteration,
                )
                reverted = spec_snapshots.get(
                    guard.last_good_spec_iteration,
                    spec_snapshots[0],
                )
                reverted.metadata.needs_review = True
                ctx.spec = reverted
                return review

            # No-progress detection: critical+high pressure strictly non-decreasing
            current_issue_pressure = review.critical_issues + sum(
                r.high_issue_count for r in review.reviews
            )
            issue_history.append(current_issue_pressure)
            if len(issue_history) > no_progress_threshold:
                window = issue_history[-no_progress_threshold:]
                if all(window[i] >= window[i - 1] for i in range(1, len(window))) and window[-1] > 0:
                    logger.warning(
                        "review-rewrite loop stuck: no progress for %d iterations, marking needs_review",
                        no_progress_threshold,
                    )
                    spec.metadata.needs_review = True
                    ctx.spec = spec
                    return review

            # Last iteration: don't rewrite (would just discard work)
            if iteration == max_iter:
                logger.warning("review-rewrite loop hit max_total_iterations=%d", max_iter)
                spec.metadata.needs_review = True
                ctx.spec = spec
                return review

            # Rewrite based on this iteration's findings
            logger.info(
                "review-rewrite iter %d: %d critical, %d total issues — rewriting",
                iteration,
                review.critical_issues,
                review.total_issues,
            )
            with ctx.trace.stage(f"rewriter_iter_{iteration}"):
                spec = await rewriter_fn(
                    ctx, spec, review, iteration, meta_review=meta_review
                )
                ctx.spec = spec
                self._assert_spec_consistent(ctx, spec, stage="rewriter", iteration=iteration)

        # Shouldn't reach here, but be safe
        assert last_review is not None
        spec.metadata.needs_review = True
        ctx.spec = spec
        return last_review

    def _finalize(self, ctx: SpecContext) -> None:
        if ctx.spec is None:
            return
        # Aggregate metadata from gateway run counter (filled by every LLM/tool call)
        counter = ctx.gateway.get_run_counter(ctx.run_id) or {}
        ctx.spec.metadata.total_llm_calls = counter.get("llm_calls", 0)
        ctx.spec.metadata.total_tool_calls = counter.get("tool_calls", 0)
        ctx.total_llm_calls = counter.get("llm_calls", 0)
        ctx.total_tool_calls = counter.get("tool_calls", 0)

        # Final spec.md + spec.json at top of workspace
        (ctx.run_workspace / "spec.md").write_text(
            spec_to_markdown(ctx.spec), encoding="utf-8"
        )
        (ctx.run_workspace / "spec.json").write_text(
            spec_to_json(ctx.spec), encoding="utf-8"
        )
        if ctx.consolidated_review:
            (ctx.run_workspace / "review.json").write_text(
                json.dumps(
                    ctx.consolidated_review.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )


def create_orchestrator(
    settings: Settings | None = None,
    *,
    prompts_dir: Path | None = None,
) -> SpecOrchestrator:
    """Convenience: build an orchestrator with defaults."""
    if settings is None:
        settings = load_settings()
    return SpecOrchestrator(settings, prompts_dir=prompts_dir)


def _save_targeted_reexploration_artifact(
    ctx: SpecContext,
    exploration: ConsolidatedExploration,
    all_gaps: list[CoverageGap],
    attempted_gaps: list[CoverageGap],
) -> None:
    """Re-save consolidated.json and write a B2 audit trail of the gaps.

    The audit file (``exploration/targeted_reexplore.json``) records what
    the detector found vs. what we actually fired re-explorers for, so
    a reader can later see whether the cap clipped useful work.
    """
    workspace = ctx.run_workspace
    (workspace / "exploration").mkdir(parents=True, exist_ok=True)
    (workspace / "exploration" / "consolidated.json").write_text(
        json.dumps(
            exploration.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (workspace / "exploration" / "targeted_reexplore.json").write_text(
        json.dumps(
            {
                "gaps_total": len(all_gaps),
                "gaps_attempted": len(attempted_gaps),
                "gaps": [
                    {
                        "kind": g.kind,
                        "detail": g.detail,
                        "suggested_re_explore_question": (
                            g.suggested_re_explore_question
                        ),
                        "primary_perspective": g.primary_perspective,
                        "attempted": g in attempted_gaps,
                    }
                    for g in all_gaps
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
