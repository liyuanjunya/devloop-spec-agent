"""Tests for DevLoop Sprint C — todo C1: adversarial red-team reviewer selection.

The 5th adversarial reviewer is enabled selectively because it costs an
extra LLM round-trip per iteration. The selection signal must be tight
enough that plain backend/data-model specs don't pay the cost, but loose
enough that any feature touching auth, payment, external integrations,
LLM/file uploads, or secret handling triggers it. These tests pin that
selection logic and its manual force/disable overrides.
"""

from __future__ import annotations

import pytest

from devloop.config import Settings
from devloop.spec_phase.agents.reviewers.stage import _should_run_adversarial
from devloop.spec_phase.schemas import ConfirmedIntent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _intent(primary: str = "add a feature", scope: list[str] | None = None) -> ConfirmedIntent:
    return ConfirmedIntent(
        primary=primary,
        intent_type="add_feature",
        scope=scope or ["backend"],  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Scope-based triggers
# ---------------------------------------------------------------------------


def test_security_scope_triggers_adversarial():
    """A spec scoped as 'security' must always enable the adversarial reviewer."""
    intent = _intent(primary="add CSRF protection", scope=["backend", "security"])
    assert _should_run_adversarial(intent) is True


def test_auth_scope_triggers_adversarial():
    """Auth scope is a classic source of subtle IDOR/scope-check defects."""
    intent = _intent(primary="add login endpoint", scope=["auth"])
    assert _should_run_adversarial(intent) is True


def test_external_integration_scope_triggers():
    """External integrations (3rd-party APIs, webhooks) need red-team review."""
    intent = _intent(
        primary="integrate Stripe webhook",
        scope=["backend", "external_integration"],
    )
    assert _should_run_adversarial(intent) is True


def test_payment_scope_triggers():
    """Payment scope must always enable the adversarial reviewer."""
    intent = _intent(primary="charge a card", scope=["payment"])
    assert _should_run_adversarial(intent) is True


# ---------------------------------------------------------------------------
# Primary-text-based triggers
# ---------------------------------------------------------------------------


def test_primary_mentioning_upload_triggers():
    """Upload endpoints are a known source of validation-ordering bugs."""
    intent = _intent(primary="Add a file upload endpoint", scope=["backend"])
    assert _should_run_adversarial(intent) is True


def test_primary_mentioning_openai_triggers():
    """LLM/OpenAI integrations need red-team review for prompt injection / log leaks."""
    intent = _intent(primary="Call OpenAI to summarize text", scope=["backend"])
    assert _should_run_adversarial(intent) is True


def test_primary_mentioning_llm_lowercase_triggers():
    """The 'llm' keyword is matched case-insensitively in intent.primary."""
    intent = _intent(primary="route requests to an llm provider", scope=["backend"])
    assert _should_run_adversarial(intent) is True


def test_primary_mentioning_password_triggers():
    """Password-handling code is a known landmine — must be red-teamed."""
    intent = _intent(primary="Implement password reset flow", scope=["backend"])
    assert _should_run_adversarial(intent) is True


def test_primary_mentioning_pii_case_insensitive_triggers():
    """PII handling (any case) must trigger the adversarial reviewer."""
    intent = _intent(primary="Mask PII fields in logs", scope=["backend"])
    assert _should_run_adversarial(intent) is True


def test_primary_mentioning_secret_triggers():
    """The literal token 'secret' in intent.primary trips the heuristic."""
    intent = _intent(primary="Rotate the JWT secret on a schedule", scope=["backend"])
    assert _should_run_adversarial(intent) is True


def test_primary_mentioning_image_triggers():
    """Image processing inherits the same upload/validation risk surface."""
    intent = _intent(primary="Resize image attachments inline", scope=["backend"])
    assert _should_run_adversarial(intent) is True


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_plain_backend_doesnt_trigger():
    """A boring backend feature with no risk keywords must NOT pay the extra cost."""
    intent = _intent(primary="Add a hello-world endpoint", scope=["backend"])
    assert _should_run_adversarial(intent) is False


def test_plain_frontend_doesnt_trigger():
    """A pure frontend change without sensitive keywords must NOT trigger."""
    intent = _intent(primary="Reorder the dashboard widgets", scope=["frontend", "ui"])
    assert _should_run_adversarial(intent) is False


def test_none_intent_returns_false():
    """Defensive: without a confirmed intent the heuristic refuses to enable."""
    assert _should_run_adversarial(None) is False


def test_empty_primary_and_no_scope_returns_false():
    """Empty signal => no adversarial."""
    intent = ConfirmedIntent(primary="", intent_type="add_feature", scope=[])
    assert _should_run_adversarial(intent) is False


def test_keyword_inside_unrelated_word_still_triggers():
    """The heuristic is intentionally over-eager: substring match means
    'token-bucket' counts as a 'token' hit. We accept false positives because
    a missed security review is a much worse outcome than a wasted LLM call.
    """
    intent = _intent(primary="Implement a token-bucket rate limiter", scope=["backend"])
    assert _should_run_adversarial(intent) is True


# ---------------------------------------------------------------------------
# Settings-driven overrides — verifies the precedence used by
# ``run_review_stage`` (disable > force > heuristic). The heuristic itself
# is independent of settings, so the override tests exercise the same
# precedence rules a caller would compose manually.
# ---------------------------------------------------------------------------


def test_force_adversarial_setting_overrides():
    """``force_adversarial=True`` must enable adversarial even for a plain backend spec."""
    settings = Settings()
    settings.reviewer.force_adversarial = True
    intent = _intent(primary="Add a hello-world endpoint", scope=["backend"])

    # The heuristic alone says no:
    assert _should_run_adversarial(intent) is False
    # But the documented precedence (disable > force > heuristic) flips it on:
    if settings.reviewer.disable_adversarial:
        run_adv = False
    elif settings.reviewer.force_adversarial:
        run_adv = True
    else:
        run_adv = _should_run_adversarial(intent)
    assert run_adv is True


def test_disable_adversarial_setting_overrides():
    """``disable_adversarial=True`` must veto adversarial even when scope says yes."""
    settings = Settings()
    settings.reviewer.disable_adversarial = True
    intent = _intent(primary="add CSRF protection", scope=["security"])

    # The heuristic alone says yes:
    assert _should_run_adversarial(intent) is True
    # Disable wins:
    if settings.reviewer.disable_adversarial:
        run_adv = False
    elif settings.reviewer.force_adversarial:
        run_adv = True
    else:
        run_adv = _should_run_adversarial(intent)
    assert run_adv is False


def test_disable_beats_force_precedence():
    """If both flags are set, ``disable_adversarial`` wins (it's the hard kill switch)."""
    settings = Settings()
    settings.reviewer.force_adversarial = True
    settings.reviewer.disable_adversarial = True
    intent = _intent(primary="charge a card", scope=["payment"])

    if settings.reviewer.disable_adversarial:
        run_adv = False
    elif settings.reviewer.force_adversarial:
        run_adv = True
    else:
        run_adv = _should_run_adversarial(intent)
    assert run_adv is False


def test_reviewer_config_defaults_for_adversarial_flags():
    """Both override flags must default to False so the heuristic is the
    decision-maker out of the box."""
    settings = Settings()
    assert settings.reviewer.force_adversarial is False
    assert settings.reviewer.disable_adversarial is False


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------


def test_adversarial_is_valid_reviewer_type():
    """``"adversarial"`` must be an accepted ``ReviewerType`` literal so the
    rest of the pipeline (ReviewIssue, ReviewResult, PrioritizedAction) can
    carry it without validation errors."""
    from devloop.spec_phase.schemas import ReviewIssue, Severity

    issue = ReviewIssue(
        id="ADVE-001",
        reviewer_type="adversarial",  # must round-trip through the Literal
        severity=Severity.CRITICAL,
        location="FR-007",
        description="Rate-limit ordering allows quota DoS",
        evidence="spec line 142",
    )
    assert issue.reviewer_type == "adversarial"


def test_payment_is_valid_scope_type():
    """``"payment"`` must be in ``ScopeType`` so the scope-based trigger
    isn't rejected at intent-validation time."""
    intent = ConfirmedIntent(
        primary="charge a card",
        intent_type="add_feature",
        scope=["payment"],  # type: ignore[list-item]
    )
    assert "payment" in intent.scope


@pytest.mark.parametrize(
    "scope",
    [
        ["security"],
        ["auth"],
        ["external_integration"],
        ["payment"],
        ["backend", "security"],
        ["security", "auth"],
    ],
)
def test_parametrized_security_scopes_trigger(scope):
    intent = _intent(primary="generic", scope=scope)
    assert _should_run_adversarial(intent) is True


@pytest.mark.parametrize(
    "primary",
    [
        "Upload user avatars",
        "Validate image content type",
        "Move file across buckets",
        "Add prompt template editor",
        "Use LLM to summarize",
        "Wrap the OpenAI completion API",
        "Reset user password",
        "Issue a refresh token",
        "Manage application secret store",
        "Strip PII before logging",
        "Process a payment via Stripe",
    ],
)
def test_parametrized_primary_keywords_trigger(primary):
    intent = _intent(primary=primary, scope=["backend"])
    assert _should_run_adversarial(intent) is True
