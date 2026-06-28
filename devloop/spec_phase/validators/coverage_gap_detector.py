"""Detect cross-perspective coverage gaps in a ConsolidatedExploration.

When the 5-perspective parallel exploration completes, the consolidator
merges per-perspective reports but cannot synthesise *new* findings — if
all 5 perspectives missed a critical file, no amount of stitching will
recover it. (This is exactly the Mealie 6-case test failure mode where
``PublicRecipesController`` was discovered only by the v1 reviewer after
all 5 explorers had missed it.)

This module flags three coverage-gap patterns so the orchestrator can
fire focused targeted re-explorers to close them:

- ``singleton_critical``: an artifact marked ``importance='critical'``
  by exactly one perspective. High odds the others overlooked it — a
  second pair of eyes either validates or refutes the finding.
- ``unresolved_conflict``: a Conflict between perspectives whose
  ``resolution_suggestion`` is empty. Re-explore the specific claim to
  break the tie.
- ``sparse_perspective``: a perspective produced zero artifacts while
  its siblings produced ≥ :data:`SPARSE_SIBLING_THRESHOLD` each.
  Likely a failed / timed-out explorer; re-run focused on its beat.
  When *every* perspective is empty, no gap is flagged — that's the
  "nothing to find" case, not a failure.

Gaps are returned in a stable order (singleton_critical → unresolved_conflict
→ sparse_perspective; within each kind, in spec / perspective iteration
order) so downstream tests can rely on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from devloop.spec_phase.schemas import ConsolidatedExploration, PerspectiveType

# When the most-populated sibling perspective has ≥ this many artifacts,
# an empty perspective is treated as a likely explorer failure rather
# than a "this beat truly has nothing to report" case.
SPARSE_SIBLING_THRESHOLD = 3

# A conflict description must contain at least this many non-whitespace
# characters to be considered non-trivial — short blurbs like "TODO" or
# "?" are ignored to keep the re-exploration budget focused.
MIN_CONFLICT_DESCRIPTION_LEN = 10

GAP_SINGLETON_CRITICAL = "singleton_critical"
GAP_UNRESOLVED_CONFLICT = "unresolved_conflict"
GAP_SPARSE_PERSPECTIVE = "sparse_perspective"

VALID_GAP_KINDS = frozenset(
    {GAP_SINGLETON_CRITICAL, GAP_UNRESOLVED_CONFLICT, GAP_SPARSE_PERSPECTIVE}
)


@dataclass(slots=True, frozen=True)
class CoverageGap:
    """One coverage gap detected in a ConsolidatedExploration.

    Attributes:
        kind: one of :data:`VALID_GAP_KINDS` — selects how the orchestrator
            should prompt the targeted re-explorer.
        detail: human-readable summary of the gap, suitable for logs or a
            ReviewIssue body.
        suggested_re_explore_question: a concrete, self-contained question
            ready to be plugged into the targeted explorer prompt. Always
            mentions a concrete artifact path, conflict description, or
            perspective name so the re-explorer has somewhere to start.
        primary_perspective: optional hint identifying the perspective
            most directly involved in the gap — used by the orchestrator
            to pick an appropriate perspective label for the targeted
            re-explorer (e.g. a *different* perspective for singleton
            criticals, the *same* perspective for sparse perspectives).
            ``None`` when the gap is not perspective-specific.
    """

    kind: str
    detail: str
    suggested_re_explore_question: str
    primary_perspective: PerspectiveType | None = None


def detect_coverage_gaps(exploration: ConsolidatedExploration) -> list[CoverageGap]:
    """Inspect a consolidated exploration and return any gaps.

    Gap kinds:

    - ``singleton_critical``: an artifact marked importance='critical' that
      ONLY one perspective surfaced. High likelihood the others missed it.
      Re-explore to have a second perspective confirm or refute.
    - ``unresolved_conflict``: a Conflict entry whose description is non-trivial
      AND has no resolution. Re-explore the specific claim to break the tie.
    - ``sparse_perspective``: a perspective has ZERO relevant_artifacts despite
      its sibling perspectives finding many. Likely the explorer failed/timed
      out. Re-explore with a more focused prompt.

    Returns the gaps in a stable order: singleton_critical first (most
    likely to surface a missed essential artifact), then unresolved_conflict,
    then sparse_perspective. Returns an empty list when ``exploration`` has
    no detectable gaps (well-covered, all resolved, all populated — or the
    "nothing to find" case where every perspective is empty).
    """
    gaps: list[CoverageGap] = []
    gaps.extend(_find_singleton_criticals(exploration))
    gaps.extend(_find_unresolved_conflicts(exploration))
    gaps.extend(_find_sparse_perspectives(exploration))
    return gaps


def _find_singleton_criticals(
    exploration: ConsolidatedExploration,
) -> list[CoverageGap]:
    """Critical artifacts surfaced by exactly one perspective."""
    # Group critical artifacts by path. We track:
    #   - the set of perspective types that surfaced this path AS CRITICAL
    #   - a representative reason / symbol list for the gap description
    # Paths only mentioned at importance < critical are ignored — those
    # don't qualify even if mentioned by a single perspective.
    by_path: dict[str, _SingletonState] = {}
    for perspective in exploration.perspectives:
        ptype = perspective.perspective_type
        for art in perspective.relevant_artifacts:
            if art.importance != "critical":
                continue
            state = by_path.get(art.path)
            if state is None:
                state = _SingletonState(
                    path=art.path,
                    perspectives=set(),
                    reason=art.reason,
                    symbols=list(art.symbols),
                )
                by_path[art.path] = state
            state.perspectives.add(ptype)

    gaps: list[CoverageGap] = []
    for state in by_path.values():
        if len(state.perspectives) != 1:
            continue
        (only,) = tuple(state.perspectives)
        sym_part = f" (symbols={state.symbols})" if state.symbols else ""
        gaps.append(
            CoverageGap(
                kind=GAP_SINGLETON_CRITICAL,
                detail=(
                    f"Critical artifact {state.path!r}{sym_part} was surfaced "
                    f"ONLY by the {only!r} perspective. Reason given: "
                    f"{state.reason}"
                ),
                suggested_re_explore_question=(
                    f"Confirm or refute that {state.path!r} is critical to "
                    f"this feature. Only the {only!r} perspective flagged it; "
                    "verify by opening the file and checking how it actually "
                    "interacts with the feature's code paths."
                ),
                primary_perspective=only,
            )
        )
    return gaps


def _find_unresolved_conflicts(
    exploration: ConsolidatedExploration,
) -> list[CoverageGap]:
    """Conflicts without a meaningful resolution_suggestion."""
    gaps: list[CoverageGap] = []
    for conflict in exploration.conflicts:
        desc = (conflict.description or "").strip()
        if len(desc) < MIN_CONFLICT_DESCRIPTION_LEN:
            continue
        resolution = (conflict.resolution_suggestion or "").strip()
        if resolution:
            continue
        involved = ", ".join(conflict.perspectives_involved)
        gaps.append(
            CoverageGap(
                kind=GAP_UNRESOLVED_CONFLICT,
                detail=(
                    f"Unresolved conflict between perspectives "
                    f"[{involved}]: {desc}"
                ),
                suggested_re_explore_question=(
                    f"Break this tie between the [{involved}] perspectives: "
                    f"{desc} Open the relevant files yourself and produce a "
                    "concrete answer that settles the disagreement."
                ),
                primary_perspective=None,
            )
        )
    return gaps


def _find_sparse_perspectives(
    exploration: ConsolidatedExploration,
) -> list[CoverageGap]:
    """Perspectives with zero artifacts while siblings have many."""
    if not exploration.perspectives:
        return []
    counts = [
        (p.perspective_type, len(p.relevant_artifacts))
        for p in exploration.perspectives
    ]
    # If every perspective is empty, the codebase probably has nothing
    # to find for this feature — don't flag.
    if all(c == 0 for _, c in counts):
        return []
    max_sibling = max(c for _, c in counts)
    # If *no* perspective is well-populated, every empty perspective is
    # plausibly an honest "nothing here" rather than a failure.
    if max_sibling < SPARSE_SIBLING_THRESHOLD:
        return []

    gaps: list[CoverageGap] = []
    for ptype, count in counts:
        if count != 0:
            continue
        gaps.append(
            CoverageGap(
                kind=GAP_SPARSE_PERSPECTIVE,
                detail=(
                    f"Perspective {ptype!r} returned 0 relevant_artifacts "
                    f"while siblings returned up to {max_sibling} — likely a "
                    "failed or timed-out explorer."
                ),
                suggested_re_explore_question=(
                    f"Re-run the {ptype!r}-perspective exploration with a "
                    f"focused prompt: what code files relevant to this "
                    f"feature fall under the {ptype!r} concerns (e.g. for "
                    "'api' perspective: HTTP endpoints, routers, "
                    "request/response models; for 'data': models, "
                    "schema, persistence)?"
                ),
                primary_perspective=ptype,
            )
        )
    return gaps


@dataclass(slots=True)
class _SingletonState:
    """Mutable scratch state used while grouping critical artifacts by path."""

    path: str
    perspectives: set[PerspectiveType]
    reason: str
    symbols: list[str]
