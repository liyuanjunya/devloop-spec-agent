"""Tests for LLM gateway routing and provider abstraction."""

from pathlib import Path

import pytest

from devloop.llm.routing import ModelAssignment, ModelRouter, load_router_from_yaml


def test_router_enforces_cross_company():
    with pytest.raises(ValueError, match="Cross-company"):
        ModelRouter(
            primary_provider="anthropic",
            primary_model="claude-opus-4-7",
            cross_review_provider="anthropic",
            cross_review_model="claude-sonnet-4-6",
        )


def test_router_assigns_primary_for_writer():
    r = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude-opus-4-7",
        cross_review_provider="openai",
        cross_review_model="gpt-5.5",
        stage_defaults={"writer": "primary", "reviewer": "cross_review"},
    )
    a = r.assign("writer")
    assert a == ModelAssignment("anthropic", "claude-opus-4-7")


def test_router_assigns_cross_review_for_reviewer():
    r = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude-opus-4-7",
        cross_review_provider="openai",
        cross_review_model="gpt-5.5",
        stage_defaults={"reviewer": "cross_review"},
    )
    a = r.assign("reviewer")
    assert a == ModelAssignment("openai", "gpt-5.5")


def test_router_unknown_role_defaults_primary():
    r = ModelRouter(
        primary_provider="anthropic",
        primary_model="x",
        cross_review_provider="openai",
        cross_review_model="y",
    )
    a = r.assign("some_made_up_role")
    assert a.provider == "anthropic"
    assert a.model == "x"


def test_router_opposite():
    r = ModelRouter(
        primary_provider="anthropic",
        primary_model="claude",
        cross_review_provider="openai",
        cross_review_model="gpt",
    )
    assert r.opposite("anthropic") == ModelAssignment("openai", "gpt")
    assert r.opposite("openai") == ModelAssignment("anthropic", "claude")


def test_load_router_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text(
        """
stage_defaults:
  writer: primary
  reviewer: cross_review
""",
        encoding="utf-8",
    )
    r = load_router_from_yaml(
        yaml_path,
        primary_provider="anthropic",
        primary_model="claude-opus-4-7",
        cross_review_provider="openai",
        cross_review_model="gpt-5.5",
    )
    assert r.stage_defaults["writer"] == "primary"
    assert r.stage_defaults["reviewer"] == "cross_review"
