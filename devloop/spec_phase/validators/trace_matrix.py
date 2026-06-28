"""Mechanical FR ↔ SC ↔ US trace-matrix validation (DevLoop Sprint B — B3).

The LLM reviewers consistently miss a deterministic class of spec defects that
showed up across multiple Mealie convergence cases:

* functional FRs with no success criterion verifying them (untestable
  requirement smell),
* SCs not exercised by any FR (orphan acceptance criterion),
* broken cross-references such as ``SC-001.related_requirements = ['FR-999']``
  pointing at a non-existent FR,
* P1 user stories that no FR claims via ``related_user_stories``.

These are surfaced as :class:`TraceGap` records by :func:`find_trace_gaps`; the
orchestrator wraps each gap in a HIGH ``executability`` :class:`ReviewIssue`
and feeds it into the next review iteration so the rewriter can close it.

Reachability is bipartite: a FR↔SC edge counts when **either**
``FR.related_success_criteria`` references the SC **or**
``SC.related_requirements`` references the FR. A gap is only reported when
**both** sides are silent — a one-directional link is enough for the trace
matrix to consider the pair connected. Mismatched ids (dangling references)
are reported as their own kind of gap regardless of reachability.
"""

from __future__ import annotations

from dataclasses import dataclass

from devloop.spec_phase.schemas import Spec
from devloop.spec_phase.schemas.common import Priority

GAP_FR_WITHOUT_SC = "fr_without_sc"
GAP_SC_WITHOUT_FR = "sc_without_fr"
GAP_SC_REF_UNKNOWN_FR = "sc_references_unknown_fr"
GAP_FR_REF_UNKNOWN_SC = "fr_references_unknown_sc"
GAP_US_WITHOUT_FR = "us_without_fr"

VALID_GAP_KINDS = frozenset(
    {
        GAP_FR_WITHOUT_SC,
        GAP_SC_WITHOUT_FR,
        GAP_SC_REF_UNKNOWN_FR,
        GAP_FR_REF_UNKNOWN_SC,
        GAP_US_WITHOUT_FR,
    }
)


@dataclass(slots=True, frozen=True)
class TraceGap:
    """One mechanical trace-matrix defect found in a Spec.

    Attributes:
        kind: one of :data:`VALID_GAP_KINDS` — used by the orchestrator and
            downstream tooling to group / filter gaps.
        actor: the FR/SC/US id that owns the gap (e.g. ``"FR-007"``).
        detail: human-readable description suitable for a ReviewIssue body.
    """

    kind: str
    actor: str
    detail: str


def build_trace_matrix(spec: Spec) -> dict[str, dict[str, list[str]]]:
    """Build the FR ↔ SC ↔ US trace matrix as four sorted adjacency maps.

    Returns a dict with the following shape::

        {
            'fr_to_sc': {'FR-001': ['SC-001', 'SC-003'], ...},
            'sc_to_fr': {'SC-001': ['FR-001'], ...},
            'us_to_fr': {'US-1':   ['FR-001', 'FR-002'], ...},
            'fr_to_us': {'FR-001': ['US-1'], ...},
        }

    FR↔SC edges are derived from both ``FR.related_success_criteria`` and
    ``SC.related_requirements`` and merged symmetrically so a single
    one-directional declaration shows up on both sides. Dangling references
    (e.g. an id that doesn't exist on the opposite side) are silently
    dropped from the matrix; they are reported separately by
    :func:`find_trace_gaps`. Every FR/SC/US in the spec is guaranteed to
    appear as a key, even when its adjacency list is empty.
    """
    fr_ids = {fr.id for fr in spec.functional_requirements}
    sc_ids = {sc.id for sc in spec.success_criteria}
    us_ids = {us.id for us in spec.user_stories}

    fr_to_sc: dict[str, set[str]] = {fid: set() for fid in fr_ids}
    sc_to_fr: dict[str, set[str]] = {sid: set() for sid in sc_ids}

    for fr in spec.functional_requirements:
        for sc_id in fr.related_success_criteria:
            if sc_id in sc_ids:
                fr_to_sc[fr.id].add(sc_id)
                sc_to_fr[sc_id].add(fr.id)

    for sc in spec.success_criteria:
        for fr_id in sc.related_requirements:
            if fr_id in fr_ids:
                sc_to_fr[sc.id].add(fr_id)
                fr_to_sc[fr_id].add(sc.id)

    us_to_fr: dict[str, set[str]] = {uid: set() for uid in us_ids}
    fr_to_us: dict[str, set[str]] = {fid: set() for fid in fr_ids}
    for fr in spec.functional_requirements:
        for us_id in fr.related_user_stories:
            fr_to_us[fr.id].add(us_id)
            if us_id in us_ids:
                us_to_fr[us_id].add(fr.id)

    def _sorted_map(m: dict[str, set[str]]) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in m.items()}

    return {
        "fr_to_sc": _sorted_map(fr_to_sc),
        "sc_to_fr": _sorted_map(sc_to_fr),
        "us_to_fr": _sorted_map(us_to_fr),
        "fr_to_us": _sorted_map(fr_to_us),
    }


def find_trace_gaps(spec: Spec) -> list[TraceGap]:
    """Return all FR↔SC↔US trace gaps detected in ``spec``. ``[]`` = clean.

    Rules:

    1. Every functional FR (``requirement_type == "functional"``) MUST have
       at least one SC linked in either direction. Non-functional FRs are
       exempt (an NFR with no SC is OK but not encouraged).
    2. Every SC MUST have at least one FR linked in either direction.
    3. Cross-references MUST resolve to real ids — a
       ``related_success_criteria`` entry that names an SC that doesn't
       exist (or vice versa for ``related_requirements``) is its own gap
       even if the owning entity is otherwise reachable.
    4. Every P1 user story MUST be referenced by at least one
       ``FR.related_user_stories``. P2/P3 stories are exempt.

    Gaps are returned in a stable order (cross-reference gaps first, then
    FR-without-SC, then SC-without-FR, then US-without-FR; within each
    kind, in spec declaration order) so downstream tests can rely on it.
    """
    gaps: list[TraceGap] = []

    fr_ids = {fr.id for fr in spec.functional_requirements}
    sc_ids = {sc.id for sc in spec.success_criteria}

    matrix = build_trace_matrix(spec)
    fr_to_sc = matrix["fr_to_sc"]
    sc_to_fr = matrix["sc_to_fr"]
    us_to_fr = matrix["us_to_fr"]

    # Rule 3 — cross-reference validity. Reported first so a reviewer reading
    # top-down sees the cause (bad id) before the symptom (missing trace).
    for fr in spec.functional_requirements:
        for sc_id in fr.related_success_criteria:
            if sc_id not in sc_ids:
                gaps.append(
                    TraceGap(
                        kind=GAP_FR_REF_UNKNOWN_SC,
                        actor=fr.id,
                        detail=(
                            f"{fr.id}.related_success_criteria references "
                            f"unknown SC '{sc_id}'. Either remove the entry or "
                            "add the missing success criterion."
                        ),
                    )
                )
    for sc in spec.success_criteria:
        for fr_id in sc.related_requirements:
            if fr_id not in fr_ids:
                gaps.append(
                    TraceGap(
                        kind=GAP_SC_REF_UNKNOWN_FR,
                        actor=sc.id,
                        detail=(
                            f"{sc.id}.related_requirements references unknown "
                            f"FR '{fr_id}'. Either remove the entry or add the "
                            "missing functional requirement."
                        ),
                    )
                )

    # Rule 1 — every functional FR must reach an SC in either direction.
    for fr in spec.functional_requirements:
        if fr.requirement_type != "functional":
            continue
        if not fr_to_sc.get(fr.id):
            gaps.append(
                TraceGap(
                    kind=GAP_FR_WITHOUT_SC,
                    actor=fr.id,
                    detail=(
                        f"Functional requirement {fr.id} has no success "
                        "criterion verifying it. Either add an SC id to "
                        f"{fr.id}.related_success_criteria, or list {fr.id} "
                        "in some SC.related_requirements."
                    ),
                )
            )

    # Rule 2 — every SC must reach an FR in either direction.
    for sc in spec.success_criteria:
        if not sc_to_fr.get(sc.id):
            gaps.append(
                TraceGap(
                    kind=GAP_SC_WITHOUT_FR,
                    actor=sc.id,
                    detail=(
                        f"Success criterion {sc.id} is not linked to any "
                        "functional requirement. Either add an FR id to "
                        f"{sc.id}.related_requirements, or list {sc.id} in "
                        "some FR.related_success_criteria."
                    ),
                )
            )

    # Rule 4 — every P1 user story must be claimed by some FR.
    for us in spec.user_stories:
        if us.priority != Priority.P1:
            continue
        if not us_to_fr.get(us.id):
            gaps.append(
                TraceGap(
                    kind=GAP_US_WITHOUT_FR,
                    actor=us.id,
                    detail=(
                        f"P1 user story {us.id} has no functional requirement "
                        f"implementing it. Add an FR.related_user_stories "
                        f"entry that references {us.id}."
                    ),
                )
            )

    return gaps
