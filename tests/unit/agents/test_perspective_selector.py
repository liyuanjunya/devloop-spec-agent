"""Tests for C3: intent-driven perspective auto-selection."""

from __future__ import annotations

import pytest

from devloop.spec_phase.agents.explorer.perspective_selector import (
    ALWAYS_INCLUDED,
    select_perspectives,
)
from devloop.spec_phase.schemas import ConfirmedIntent


def _make_intent(
    *,
    primary: str = "Add a small backend feature",
    intent_type: str = "add_feature",
    scope: list[str] | None = None,
) -> ConfirmedIntent:
    """Build a minimal ConfirmedIntent for selector tests."""
    return ConfirmedIntent(
        primary=primary,
        intent_type=intent_type,  # type: ignore[arg-type]
        scope=scope or [],  # type: ignore[arg-type]
        confidence=0.9,
    )


# ----------------------------------------------------------------------
# Required test cases (matches the task checklist)
# ----------------------------------------------------------------------


def test_default_always_includes_data_api_test_history():
    """A minimal backend intent must still get the 4 always-included perspectives."""
    intent = _make_intent(
        primary="Fix a small backend bug in the cache layer",
        intent_type="fix_bug",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    for required in ALWAYS_INCLUDED:
        assert required in result, f"Always-included perspective '{required}' missing"
    # No optional perspective should have been added for this plain backend bug
    assert "ui" not in result
    assert "security" not in result
    assert "performance" not in result


def test_ui_included_when_scope_has_ui():
    intent = _make_intent(
        primary="Add a settings page",
        intent_type="add_feature",
        scope=["ui"],
    )
    result = select_perspectives(intent)
    assert "ui" in result


def test_ui_included_when_scope_has_frontend():
    intent = _make_intent(
        primary="Add a settings page",
        intent_type="add_feature",
        scope=["frontend"],
    )
    result = select_perspectives(intent)
    assert "ui" in result


def test_ui_excluded_for_backend_only():
    intent = _make_intent(
        primary="Refactor the persistence module to use connection pooling",
        intent_type="refactor",
        scope=["backend", "data_model"],
    )
    result = select_perspectives(intent)
    assert "ui" not in result


def test_security_included_for_external_integration_scope():
    intent = _make_intent(
        primary="Wire up the third-party billing service",
        intent_type="add_feature",
        scope=["backend", "external_integration"],
    )
    result = select_perspectives(intent)
    assert "security" in result


def test_security_included_when_primary_mentions_upload():
    intent = _make_intent(
        primary="Allow users to upload profile pictures",
        intent_type="add_feature",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "security" in result


def test_security_included_when_primary_mentions_openai():
    intent = _make_intent(
        primary="Generate image alt-text via the OpenAI API",
        intent_type="add_feature",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "security" in result


def test_performance_included_for_perf_opt_intent_type():
    intent = _make_intent(
        primary="Make the dashboard render faster",
        intent_type="perf_opt",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "performance" in result


def test_performance_included_when_primary_mentions_n_plus_1():
    intent = _make_intent(
        primary="Fix the N+1 query problem in the order listing endpoint",
        intent_type="fix_bug",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "performance" in result


def test_explicit_override_wins():
    """An explicit override returns exactly that list and bypasses auto-selection."""
    intent = _make_intent(
        primary="Allow users to upload images via OpenAI vision",
        intent_type="perf_opt",
        scope=["ui", "external_integration"],
    )
    override: list = ["data", "api"]
    result = select_perspectives(intent, explicit_override=override)
    assert result == ["data", "api"]
    # Critically: the override returned the literal list — none of the
    # auto-selection triggers (security, performance, ui) leaked in.
    assert "security" not in result
    assert "performance" not in result
    assert "ui" not in result
    # And the always-included perspectives are NOT added on top.
    assert "test" not in result
    assert "history" not in result


# ----------------------------------------------------------------------
# Extra coverage: edge cases that protect against regressions
# ----------------------------------------------------------------------


def test_security_scope_auth_triggers_security():
    intent = _make_intent(
        primary="Refresh JWT signing keys monthly",
        intent_type="add_feature",
        scope=["backend", "auth"],
    )
    result = select_perspectives(intent)
    assert "security" in result


def test_security_scope_security_triggers_security():
    intent = _make_intent(
        primary="Tighten CSRF protection",
        intent_type="add_feature",
        scope=["backend", "security"],
    )
    result = select_perspectives(intent)
    assert "security" in result


@pytest.mark.parametrize(
    "keyword",
    ["upload", "image", "file", "prompt", "llm", "password", "token", "secret", "rate-limit"],
)
def test_security_primary_keywords_trigger_security(keyword: str):
    intent = _make_intent(
        primary=f"Add support for {keyword} handling in the API",
        intent_type="add_feature",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "security" in result, f"keyword '{keyword}' should trigger security perspective"


def test_security_primary_keyword_match_is_case_insensitive():
    intent = _make_intent(
        primary="Add OPENAI vision integration",
        intent_type="add_feature",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "security" in result


def test_performance_scope_performance_triggers_performance():
    intent = _make_intent(
        primary="Profile the report builder",
        intent_type="refactor",
        scope=["backend", "performance"],
    )
    result = select_perspectives(intent)
    assert "performance" in result


@pytest.mark.parametrize(
    "keyword",
    ["latency", "optimize", "slow", "performance", "query count"],
)
def test_performance_primary_keywords_trigger_performance(keyword: str):
    intent = _make_intent(
        primary=f"We need to reduce {keyword} in the orders endpoint",
        intent_type="fix_bug",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "performance" in result, f"keyword '{keyword}' should trigger performance perspective"


def test_combined_triggers_all_optional_perspectives():
    """A UI feature that also handles uploads and is perf-sensitive should fire all 3 optionals."""
    intent = _make_intent(
        primary="Optimize the image upload form for lower latency",
        intent_type="perf_opt",
        scope=["ui", "backend"],
    )
    result = select_perspectives(intent)
    for required in ALWAYS_INCLUDED:
        assert required in result
    assert "ui" in result
    assert "security" in result
    assert "performance" in result


def test_result_order_is_stable_and_canonical():
    """The selector returns a deterministic, canonical ordering."""
    intent = _make_intent(
        primary="Add image upload with N+1-free pagination",
        intent_type="perf_opt",
        scope=["ui", "backend"],
    )
    result = select_perspectives(intent)
    canonical = ["data", "api", "ui", "test", "history", "security", "performance"]
    # Filter canonical down to whatever the selector returned, preserving order.
    expected = [p for p in canonical if p in result]
    assert result == expected


def test_no_duplicate_perspectives_in_result():
    intent = _make_intent(
        primary="Optimize slow image upload latency for the UI",
        intent_type="perf_opt",
        scope=["ui", "frontend", "external_integration", "auth", "performance"],
    )
    result = select_perspectives(intent)
    assert len(result) == len(set(result))


def test_explicit_override_empty_list_returns_empty():
    """An empty override is honored verbatim — the caller is explicitly disabling exploration."""
    intent = _make_intent(primary="anything", intent_type="add_feature", scope=["backend"])
    result = select_perspectives(intent, explicit_override=[])
    assert result == []


def test_explicit_override_preserves_input_order():
    """The override is returned as-given, including unusual ordering."""
    intent = _make_intent(primary="anything", intent_type="add_feature")
    override: list = ["history", "data", "security"]
    result = select_perspectives(intent, explicit_override=override)
    assert result == ["history", "data", "security"]


def test_perf_opt_intent_without_perf_keyword_still_triggers_performance():
    """The intent_type alone is sufficient — no keyword needed in primary text."""
    intent = _make_intent(
        primary="Make the API a bit better",
        intent_type="perf_opt",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    assert "performance" in result


def test_returned_list_is_independent_of_always_included_tuple():
    """Mutating the returned list must not poison the module-level ALWAYS_INCLUDED constant."""
    intent = _make_intent(
        primary="Add a small feature",
        intent_type="add_feature",
        scope=["backend"],
    )
    result = select_perspectives(intent)
    result.append("ui")  # type: ignore[arg-type]
    # ALWAYS_INCLUDED is a tuple, but make sure a *fresh* call still returns
    # a list without our injected 'ui'.
    fresh = select_perspectives(intent)
    assert "ui" not in fresh
