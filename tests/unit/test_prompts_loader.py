"""Tests for prompt loader."""

from pathlib import Path

import pytest

from devloop.spec_phase.prompts_loader import PromptLoader, PromptNotFoundError


def test_loads_basic_prompt(tmp_path: Path):
    (tmp_path / "writer.md").write_text("Hello {{name}}!", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    assert loader.load("writer", name="World") == "Hello World!"


def test_no_substitution_when_no_vars(tmp_path: Path):
    (tmp_path / "x.md").write_text("Hello {{x}}!", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    assert loader.load("x") == "Hello {{x}}!"


def test_overrides_take_precedence(tmp_path: Path):
    (tmp_path / "x.md").write_text("default", encoding="utf-8")
    (tmp_path / "overrides").mkdir()
    (tmp_path / "overrides" / "x.md").write_text("OVERRIDE", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    assert loader.load("x") == "OVERRIDE"


def test_falls_back_to_spec_kit_reference(tmp_path: Path):
    (tmp_path / "reference" / "spec-kit").mkdir(parents=True)
    (tmp_path / "reference" / "spec-kit" / "speckit_only.md").write_text(
        "vendored", encoding="utf-8"
    )
    loader = PromptLoader(tmp_path)
    assert loader.load("speckit_only") == "vendored"


def test_missing_prompt_raises(tmp_path: Path):
    loader = PromptLoader(tmp_path)
    with pytest.raises(PromptNotFoundError):
        loader.load("nonexistent")


def test_list_available_includes_subdirectories(tmp_path: Path):
    (tmp_path / "intent").mkdir()
    (tmp_path / "intent" / "analyzer.md").write_text("x", encoding="utf-8")
    (tmp_path / "writer.md").write_text("y", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    avail = loader.list_available()
    assert "writer" in avail
    assert "intent/analyzer" in avail


def test_load_real_devloop_prompts():
    """Sanity check: every prompt referenced in code must exist in prompts/."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    prompts_dir = repo_root / "prompts"
    loader = PromptLoader(prompts_dir)
    required = [
        "intent/analyzer",
        "intent/skeptic",
        "intent/verifier",
        "explorer/_base",
        "explorer/data",
        "explorer/api",
        "explorer/ui",
        "explorer/test",
        "explorer/history",
        "explorer/consolidator",
        "approach/plan_generator",
        "approach/plan_evaluator",
        "approach/plan_selector",
        "writer",
        "writer_rewrite",
        "reviewer/_base",
        "reviewer/architecture",
        "reviewer/completeness",
        "reviewer/executability",
        "reviewer/consistency",
    ]
    for name in required:
        assert loader.load(name)
