"""A1 — Rewriter regression guard.

When a rewrite increases the number of critical+high issues vs the previous
spec, we say the rewrite has *regressed*. The orchestrator should detect
this, log it, and either:

1. Force a regression-aware retry (with extra context about what got worse), or
2. After ``max_regression_retries``, revert to the prior spec and mark it
   ``needs_review``.

This guards against the observed case-6 v2 failure where the rewriter, in
fixing one issue, introduced two new critical issues elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from devloop.spec_phase.schemas import ConsolidatedReview, Severity


@dataclass(slots=True, frozen=True)
class IssueCounts:
    """Per-severity issue counts collected from a ConsolidatedReview."""

    critical: int
    high: int
    medium: int
    low: int

    @property
    def critical_plus_high(self) -> int:
        return self.critical + self.high

    @property
    def total(self) -> int:
        return self.critical + self.high + self.medium + self.low

    @classmethod
    def from_review(cls, review: ConsolidatedReview) -> IssueCounts:
        c = h = m = lo = 0
        for r in review.reviews:
            for issue in r.issues:
                if issue.severity == Severity.CRITICAL:
                    c += 1
                elif issue.severity == Severity.HIGH:
                    h += 1
                elif issue.severity == Severity.MEDIUM:
                    m += 1
                else:
                    lo += 1
        return cls(critical=c, high=h, medium=m, low=lo)


@dataclass(slots=True, frozen=True)
class IterationDelta:
    """Comparison between two consecutive iterations of the review loop."""

    iteration: int
    """The iteration number of the *current* review (the one being judged)."""

    prev: IssueCounts | None
    """Counts from the previous iteration's review. ``None`` for the first iteration."""

    curr: IssueCounts
    """Counts from the current iteration's review."""

    @property
    def delta_critical_plus_high(self) -> int:
        """Negative = improved; positive = regressed; zero = stagnant."""
        if self.prev is None:
            return 0
        return self.curr.critical_plus_high - self.prev.critical_plus_high

    @property
    def is_regression(self) -> bool:
        """True iff the current review has strictly MORE critical+high than prev.

        First iteration is never a regression (there's no prior to compare to).
        """
        if self.prev is None:
            return False
        return self.curr.critical_plus_high > self.prev.critical_plus_high

    @property
    def is_improved(self) -> bool:
        if self.prev is None:
            return False
        return self.curr.critical_plus_high < self.prev.critical_plus_high

    @property
    def is_stagnant(self) -> bool:
        """Stagnant means SAME critical+high. Could be terminal if it persists."""
        if self.prev is None:
            return False
        return self.curr.critical_plus_high == self.prev.critical_plus_high


@dataclass(slots=True)
class RegressionGuardState:
    """Tracks regression-aware retries within a review-rewrite loop run."""

    history: list[IssueCounts] = field(default_factory=list)
    """Issue counts for each iteration, in order."""

    regression_retries_used: int = 0
    """How many times we've forced a regression-aware retry this run."""

    last_good_spec_iteration: int = 0
    """The iteration whose spec we'd revert to if budget runs out. 0 = initial writer output."""

    def observe(self, iteration: int, counts: IssueCounts) -> IterationDelta:
        """Record an iteration's counts and return the delta vs previous."""
        prev = self.history[-1] if self.history else None
        delta = IterationDelta(iteration=iteration, prev=prev, curr=counts)
        self.history.append(counts)
        if delta.is_improved or prev is None:
            self.last_good_spec_iteration = iteration
        return delta

    def can_retry_regression(self, max_retries: int) -> bool:
        return self.regression_retries_used < max_retries

    def consume_regression_retry(self) -> None:
        self.regression_retries_used += 1


def regression_feedback_message(delta: IterationDelta) -> str:
    """Human-readable explanation of WHY a rewrite is being forced again.

    Fed to the rewriter as additional context so it can avoid repeating the mistake.
    """
    if not delta.is_regression:
        return ""
    prev = delta.prev
    curr = delta.curr
    assert prev is not None
    delta_c = curr.critical - prev.critical
    delta_h = curr.high - prev.high
    parts = ["REGRESSION DETECTED: your previous rewrite made the spec WORSE."]
    parts.append(
        f"Critical issues: {prev.critical} → {curr.critical} "
        f"({'+' if delta_c >= 0 else ''}{delta_c})."
    )
    parts.append(
        f"High issues: {prev.high} → {curr.high} "
        f"({'+' if delta_h >= 0 else ''}{delta_h})."
    )
    parts.append(
        "Look carefully at the NEW critical/high issues — those are bugs you introduced. "
        "Preserve everything that was good about the previous spec and resolve the issues "
        "WITHOUT regressing on what was already correct."
    )
    return "\n".join(parts)
