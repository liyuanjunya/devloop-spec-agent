"""Tests for A1 — regression guard + A2 — multi-iteration loop hardening."""

from devloop.spec_phase.regression_guard import (
    IssueCounts,
    IterationDelta,
    RegressionGuardState,
    regression_feedback_message,
)
from devloop.spec_phase.schemas import (
    ConsolidatedReview,
    ReviewIssue,
    ReviewResult,
    Severity,
)


def _mk_review(critical: int = 0, high: int = 0, medium: int = 0, low: int = 0) -> ConsolidatedReview:
    """Build a ConsolidatedReview with one ReviewResult containing the given counts."""
    issues = []
    for _ in range(critical):
        issues.append(ReviewIssue(
            id="C", reviewer_type="architecture", severity=Severity.CRITICAL,
            location="FR-1", description="x", evidence="x",
        ))
    for _ in range(high):
        issues.append(ReviewIssue(
            id="H", reviewer_type="architecture", severity=Severity.HIGH,
            location="FR-1", description="x", evidence="x",
        ))
    for _ in range(medium):
        issues.append(ReviewIssue(
            id="M", reviewer_type="architecture", severity=Severity.MEDIUM,
            location="FR-1", description="x", evidence="x",
        ))
    return ConsolidatedReview(
        reviews=[
            ReviewResult(
                reviewer_type="architecture",
                judge_model="x",
                verdict="needs_refine",
                issues=issues,
            ),
        ],
        overall_verdict="needs_refine",
        total_issues=critical + high + medium,
        critical_issues=critical,
    )


def test_issue_counts_from_review_simple():
    r = _mk_review(critical=2, high=3, medium=1)
    counts = IssueCounts.from_review(r)
    assert counts.critical == 2
    assert counts.high == 3
    assert counts.medium == 1
    assert counts.critical_plus_high == 5


def test_issue_counts_aggregates_across_multiple_reviewers():
    rev1 = _mk_review(critical=1, high=2).reviews[0]
    rev2 = _mk_review(critical=2, high=0).reviews[0]
    rev2.reviewer_type = "completeness"
    cr = ConsolidatedReview(reviews=[rev1, rev2], overall_verdict="fail", total_issues=5, critical_issues=3)
    counts = IssueCounts.from_review(cr)
    assert counts.critical == 3
    assert counts.high == 2


def test_iteration_delta_first_iteration_never_regression():
    delta = IterationDelta(iteration=1, prev=None, curr=IssueCounts(critical=10, high=5, medium=0, low=0))
    assert not delta.is_regression
    assert not delta.is_improved
    assert not delta.is_stagnant
    assert delta.delta_critical_plus_high == 0


def test_iteration_delta_detects_regression():
    prev = IssueCounts(critical=2, high=3, medium=0, low=0)  # 5 critical+high
    curr = IssueCounts(critical=3, high=4, medium=0, low=0)  # 7 critical+high
    delta = IterationDelta(iteration=2, prev=prev, curr=curr)
    assert delta.is_regression
    assert not delta.is_improved
    assert delta.delta_critical_plus_high == 2


def test_iteration_delta_detects_improvement():
    prev = IssueCounts(critical=5, high=2, medium=0, low=0)  # 7
    curr = IssueCounts(critical=2, high=1, medium=10, low=0)  # 3 (med doesn't count)
    delta = IterationDelta(iteration=2, prev=prev, curr=curr)
    assert not delta.is_regression
    assert delta.is_improved
    assert delta.delta_critical_plus_high == -4


def test_iteration_delta_detects_stagnation():
    prev = IssueCounts(critical=2, high=3, medium=0, low=0)  # 5
    curr = IssueCounts(critical=4, high=1, medium=99, low=0)  # also 5
    delta = IterationDelta(iteration=2, prev=prev, curr=curr)
    assert delta.is_stagnant
    assert not delta.is_regression
    assert not delta.is_improved


def test_regression_guard_observe_updates_history():
    g = RegressionGuardState()
    c1 = IssueCounts(critical=3, high=2, medium=0, low=0)
    d1 = g.observe(1, c1)
    assert d1.prev is None
    assert g.history == [c1]

    c2 = IssueCounts(critical=2, high=1, medium=0, low=0)
    d2 = g.observe(2, c2)
    assert d2.prev == c1
    assert d2.is_improved
    assert g.last_good_spec_iteration == 2


def test_regression_guard_tracks_last_good_iteration():
    g = RegressionGuardState()
    c1 = IssueCounts(critical=5, high=0, medium=0, low=0)  # iter 1 = baseline
    g.observe(1, c1)
    assert g.last_good_spec_iteration == 1

    c2 = IssueCounts(critical=2, high=0, medium=0, low=0)  # improved
    g.observe(2, c2)
    assert g.last_good_spec_iteration == 2

    c3 = IssueCounts(critical=4, high=0, medium=0, low=0)  # regressed!
    g.observe(3, c3)
    # Last good still 2, not 3
    assert g.last_good_spec_iteration == 2


def test_regression_guard_retry_budget():
    g = RegressionGuardState()
    assert g.can_retry_regression(2)
    g.consume_regression_retry()
    assert g.can_retry_regression(2)
    g.consume_regression_retry()
    assert not g.can_retry_regression(2)


def test_regression_feedback_message_includes_counts_and_delta():
    prev = IssueCounts(critical=1, high=2, medium=0, low=0)
    curr = IssueCounts(critical=3, high=4, medium=0, low=0)
    delta = IterationDelta(iteration=2, prev=prev, curr=curr)
    msg = regression_feedback_message(delta)
    assert "REGRESSION DETECTED" in msg
    assert ("1 \u2192 3" in msg) or ("1 -> 3" in msg.replace("\u2192", "->"))
    assert "+2" in msg


def test_regression_feedback_empty_for_non_regression():
    prev = IssueCounts(critical=5, high=0, medium=0, low=0)
    curr = IssueCounts(critical=2, high=0, medium=0, low=0)
    delta = IterationDelta(iteration=2, prev=prev, curr=curr)
    msg = regression_feedback_message(delta)
    assert msg == ""


def test_max_total_iterations_default_is_at_least_5():
    """A2: ensure default cap is generous enough for slow convergence."""
    from devloop.config.settings import OrchestratorConfig
    c = OrchestratorConfig()
    assert c.max_total_iterations >= 5
    # max_regression_retries is the A1 budget
    assert c.max_regression_retries >= 1
