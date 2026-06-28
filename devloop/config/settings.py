"""Configuration system using pydantic-settings + YAML overlay.

Load order:
  1. configs/default.yaml          (committed defaults)
  2. configs/local.yaml             (developer overrides, gitignored)
  3. environment variables          (DEVLOOP__SECTION__KEY)
  4. constructor kwargs             (test overrides)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    primary_model: str = "claude-opus-4-7"
    cross_review_model: str = "gpt-5.5"
    primary_provider: str = "anthropic"
    cross_review_provider: str = "openai"
    max_retries: int = 3
    timeout_seconds: int = 120
    max_tokens_default: int = 8192
    anthropic_api_key: str = ""
    openai_api_key: str = ""


class ExplorerConfig(BaseModel):
    max_tool_calls_soft: int = 50
    max_tool_calls_hard: int = 100
    parallel: bool = True
    perspectives: list[str] = Field(
        default_factory=lambda: ["data", "api", "ui", "test", "history"]
    )
    # B2 — Cross-perspective coverage-gap re-exploration.
    max_targeted_reexplorations: int = 3
    """Hard cap on the number of targeted re-explorers fired after the
    consolidator detects coverage gaps. Set to 0 to disable."""
    targeted_reexploration_timeout_s: float = 120.0
    """Per-call timeout (seconds) applied to each targeted re-exploration."""
    use_cache: bool = True
    """If True, cache per-perspective Perspective outputs keyed by
    (cwd_path, head_commit, perspective_type, intent_summary). TTL comes from
    settings.cache.ttl_days. Set False (or pass --no-explorer-cache on the CLI)
    to bypass the cache entirely for a run."""


class ReviewerConfig(BaseModel):
    max_tool_calls_soft: int = 30
    max_tool_calls_hard: int = 80
    parallel: bool = True
    angles: list[str] = Field(
        default_factory=lambda: [
            "architecture",
            "completeness",
            "executability",
            "consistency",
        ]
    )
    # Sprint C — C1: adversarial red-team reviewer (5th angle).
    # The adversarial reviewer is enabled selectively by
    # ``_should_run_adversarial`` (security/auth/external_integration/payment
    # scopes, or LLM/upload/payment/PII keywords in intent.primary). These
    # flags are manual escape hatches.
    force_adversarial: bool = False
    """If True, always run the adversarial red-team reviewer even when the
    intent heuristic would skip it. Wins over the heuristic; loses to
    ``disable_adversarial`` (the disable flag is the hard kill switch)."""
    disable_adversarial: bool = False
    """If True, never run the adversarial red-team reviewer, even when the
    intent heuristic or ``force_adversarial`` would enable it. Hard kill
    switch — wins over every other adversarial-enablement signal, including
    YAML ``angles`` config that already lists ``"adversarial"``."""


class OrchestratorConfig(BaseModel):
    max_total_iterations: int = 20
    no_progress_threshold: int = 3
    enable_multi_view_explorer: bool = True
    enable_multi_candidate_approach: bool = True
    enable_multi_reviewer: bool = True
    # B4 — Meta-reviewer (consolidates 4 axis reviews into a single
    # prioritized action list so the rewriter doesn't fix one axis and
    # break another).
    enable_meta_reviewer: bool = True
    # A1 — Rewriter regression guard
    max_regression_retries: int = 2
    """If a rewrite increases critical+high issues, force this many regression-aware re-rewrites before reverting."""
    # A5 — Citation verifier integration
    citation_verify_max_attempts: int = 3
    """Max forced rewrites triggered by citation verification failures."""
    # C2 — Test-grounded executability check
    test_executability_max_attempts: int = 2
    """Max forced rewrites triggered by spec-named test references that
    pytest --collect-only can't actually collect (broken test paths,
    invalid function names, import errors in stubs, etc.)."""
    test_executability_timeout_s: int = 30
    """Per-call timeout (seconds) for the ``pytest --collect-only``
    subprocess used by the C2 test-grounded executability validator."""
    # F3 — A3 escalation validator (multi-option self_concerns must be
    # escalated to BlockingDecision, not buried in evidence_gap).
    escalation_check_enabled: bool = True
    """If true, the orchestrator runs the under-escalation backup
    validator after each review iteration. The pydantic
    ``Concern.evidence_gap`` validator already blocks new concerns at
    schema time; this orchestrator-level check is a backup for legacy /
    non-validated spec load paths."""
    # D3 — Segmented rewriter (opt-in)
    use_segmented_rewriter: bool = False
    """If true, the orchestrator drives the spec rewrite in 5 validated LLM
    calls (head, stories, FRs, SCs, tail) instead of one ~30KB single-shot
    call. Each segment is validated against a partial schema and falls back
    to the previous spec's section on failure. Starts opt-in until the
    Mealie eval re-measures parity with the single-shot rewriter."""


class CacheConfig(BaseModel):
    backend: str = "sqlite"
    ttl_days: int = 7


class PathsConfig(BaseModel):
    workspace_root: Path = Path("./specs")
    prompts_dir: Path = Path("./prompts")
    cache_dir: Path = Path("./.cache/devloop")


class RepoSkeletonConfig(BaseModel):
    target_tokens: int = 1024
    max_files_per_module: int = 5
    excluded_dirs: list[str] = Field(
        default_factory=lambda: [
            "node_modules",
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "dist",
            "build",
            "target",
            ".idea",
            ".vscode",
            ".pytest_cache",
            ".mypy_cache",
        ]
    )
    supported_languages: list[str] = Field(
        default_factory=lambda: [
            "python",
            "javascript",
            "typescript",
            "go",
            "rust",
            "java",
        ]
    )


class ToolsConfig(BaseModel):
    """Limits applied across the tool layer."""

    file_read_max_lines: int = 200
    file_read_max_bytes: int = 256 * 1024  # 256 KiB
    subprocess_max_bytes: int = 5 * 1024 * 1024  # 5 MiB
    project_understanding_max_snippet_chars: int = 8000
    git_command_timeout_s: int = 15
    rg_command_timeout_s: int = 30


class Settings(BaseSettings):
    """Top-level settings, loaded from YAML + env."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    explorer: ExplorerConfig = Field(default_factory=ExplorerConfig)
    reviewer: ReviewerConfig = Field(default_factory=ReviewerConfig)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    repo_skeleton: RepoSkeletonConfig = Field(default_factory=RepoSkeletonConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    model_config = SettingsConfigDict(
        env_prefix="DEVLOOP__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into `base`."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge_dicts(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(
    config_dir: Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Build Settings from default.yaml + local.yaml + env + overrides."""
    if config_dir is None:
        config_dir = _find_configs_dir()

    default_path = config_dir / "default.yaml"
    local_path = config_dir / "local.yaml"

    data = load_yaml(default_path)
    if local_path.exists():
        data = merge_dicts(data, load_yaml(local_path))
    if overrides:
        data = merge_dicts(data, overrides)

    # API keys come exclusively from env to avoid committing secrets
    import os

    if "ANTHROPIC_API_KEY" in os.environ:
        data.setdefault("llm", {})["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if "OPENAI_API_KEY" in os.environ:
        data.setdefault("llm", {})["openai_api_key"] = os.environ["OPENAI_API_KEY"]

    return Settings(**data)


def _find_configs_dir() -> Path:
    """Find configs/ by walking up from cwd."""
    here = Path.cwd().resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "configs"
        if candidate.is_dir() and (candidate / "default.yaml").exists():
            return candidate
    # Fallback: alongside the package
    pkg_root = Path(__file__).resolve().parent.parent.parent
    candidate = pkg_root / "configs"
    if candidate.is_dir():
        return candidate
    return here / "configs"


def load_model_routing(config_dir: Path | None = None) -> dict[str, Any]:
    """Load configs/models.yaml."""
    if config_dir is None:
        config_dir = _find_configs_dir()
    return load_yaml(config_dir / "models.yaml")
