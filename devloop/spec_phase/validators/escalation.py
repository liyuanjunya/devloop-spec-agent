"""Escalation validator — detect under-escalated multi-option concerns (DevLoop F3 — A3).

The spec writer is supposed to escalate multi-option implementation decisions to
:class:`BlockingDecision` (``Spec.needs_clarification``) so a reviewer/user can
choose before coding starts. Instead, it sometimes dumps the multi-option
uncertainty into a :class:`Concern.evidence_gap` string and moves on. That
silently passes the buck to the rewriter / coder.

The pydantic-level
:func:`devloop.spec_phase.schemas.spec.detect_underescalated_concern` validator
already rejects such concerns at schema-construction time. This module is a
*higher-level* backup that scans the assembled :class:`Spec` after writer /
rewriter so the orchestrator can:

1. surface a HIGH ``executability`` :class:`ReviewIssue` for any concern that
   somehow slipped past pydantic (legacy spec, non-validated load path, etc.),
2. give the rewriter an explicit, actionable suggested fix that points at the
   specific concern location and the required move to ``needs_clarification``.

Mirrors the citation / trace-matrix validator pattern so the orchestrator can
plug it into the existing inject_*_issues machinery.
"""

from __future__ import annotations

from dataclasses import dataclass

from devloop.spec_phase.schemas import Spec
from devloop.spec_phase.schemas.spec import detect_underescalated_concern


@dataclass(slots=True, frozen=True)
class EscalationProblem:
    """One self-concern that describes ≥3 options and should be escalated.

    Attributes:
        concern_location: the :attr:`Concern.location` of the offending
            concern (e.g. ``"FR-007"``), so the rewriter can find it.
        matched_text: the phrase that triggered the detector — included in
            the ReviewIssue evidence so the rewriter sees exactly what
            language to remove.
        suggested_fix: human-readable instruction telling the rewriter to
            move the concern into ``Spec.needs_clarification`` with the
            required :class:`BlockingDecision` fields.
    """

    concern_location: str
    matched_text: str
    suggested_fix: str


def find_underescalated_concerns(spec: Spec) -> list[EscalationProblem]:
    """Return all ``self_concerns`` that describe ≥3 options and should be escalated.

    Scans every :class:`Concern.evidence_gap` with
    :func:`detect_underescalated_concern`. Each match becomes one
    :class:`EscalationProblem`; the result is in source order so the rewriter
    can address them top-to-bottom.

    A clean spec (or one with only single-option / binary concerns) returns
    an empty list — the orchestrator skips the injection step entirely.
    """
    out: list[EscalationProblem] = []
    for c in spec.self_concerns:
        m = detect_underescalated_concern(c.evidence_gap)
        if m:
            out.append(
                EscalationProblem(
                    concern_location=c.location,
                    matched_text=m,
                    suggested_fix=(
                        f"Move '{c.location}' concern to needs_clarification "
                        f"(BlockingDecision) with explicit recommended_default + if_rejected."
                    ),
                )
            )
    return out
