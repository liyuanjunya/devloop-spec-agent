"""Tests for config loading."""

from devloop.config import Settings, load_settings


def test_default_settings_have_sensible_values():
    s = Settings()
    assert s.llm.primary_model.startswith("claude")
    assert s.llm.cross_review_model.startswith("gpt")
    assert s.explorer.max_tool_calls_hard >= s.explorer.max_tool_calls_soft
    assert s.orchestrator.max_total_iterations > 0


def test_load_settings_from_default_yaml():
    # Should not raise even if local.yaml doesn't exist
    s = load_settings()
    assert s.llm.primary_model
    assert isinstance(s.explorer.perspectives, list)
    assert "data" in s.explorer.perspectives
    assert "history" in s.explorer.perspectives


def test_settings_overrides_apply():
    s = load_settings(overrides={"explorer": {"parallel": False, "max_tool_calls_hard": 200}})
    assert s.explorer.parallel is False
    assert s.explorer.max_tool_calls_hard == 200
