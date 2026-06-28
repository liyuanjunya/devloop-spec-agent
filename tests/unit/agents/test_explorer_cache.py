"""Tests for DevLoop Sprint D — todo D2: per-perspective explorer cache.

Covers the cache helpers (key derivation, get/set roundtrip) and the
integration into ``run_one_explorer``:

* Cache HIT must skip the LLM ReAct loop entirely.
* Cache MISS must execute the ReAct loop and store the Perspective.
* The key must change with commit, perspective type, and intent.
* ``settings.explorer.use_cache = False`` must fully bypass the cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devloop.cache import CacheBackend
from devloop.config import Settings
from devloop.llm.trace import NullTraceWriter
from devloop.llm.types import LLMResponse, Usage
from devloop.spec_phase.agents.context import SpecContext
from devloop.spec_phase.agents.explorer.cache import (
    compute_perspective_cache_key,
    get_cached_perspective,
    intent_summary_from,
    set_cached_perspective,
)
from devloop.spec_phase.agents.explorer.stage import run_one_explorer
from devloop.spec_phase.schemas import (
    ConfirmedIntent,
    Perspective,
    RelevantArtifact,
)
from devloop.tools import build_default_registry

# --------------------------- Stubs / fixtures ---------------------------


class _CountingGateway:
    """Minimal LLMGateway stub.

    Tracks ``call_count`` so tests can assert the ReAct loop was (not) run.
    Always returns a no-tool-call response so :func:`call_react_with_tools`
    terminates after a single iteration.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def register_run(self, run_id: str) -> dict[str, int]:
        return {}

    async def call(self, **_: Any) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content="EXPLORATION COMPLETE",
            tool_calls=[],
            stop_reason="end_turn",
            model="mock",
            usage=Usage(input_tokens=1, output_tokens=1),
        )


class _ExplodingGateway:
    """LLMGateway stub whose ``call`` raises if ever invoked."""

    def __init__(self) -> None:
        self.call_count = 0

    def register_run(self, run_id: str) -> dict[str, int]:
        return {}

    async def call(self, **_: Any) -> LLMResponse:  # pragma: no cover - must not fire
        self.call_count += 1
        raise AssertionError(
            "Gateway must not be invoked when a cache hit is available"
        )


class _FakeRepoSkeleton:
    def __init__(self, commit_hash: str = "abc123def456") -> None:
        self.commit_hash = commit_hash
        self.text = "fake-skeleton"


class _FakePromptLoader:
    """Returns a stable string for any prompt key; never touches disk."""

    def load(self, name: str, **kwargs: Any) -> str:
        return f"<prompt {name}>"


def _make_ctx(
    *,
    tmp_path: Path,
    cache: CacheBackend,
    gateway: Any,
    repo_path: Path | None = None,
    commit_hash: str = "abc123def456",
    intent_primary: str = "Add user comments to product pages",
    use_cache: bool = True,
) -> SpecContext:
    """Build a SpecContext suitable for driving ``run_one_explorer`` in tests."""
    settings = Settings()
    settings.explorer.use_cache = use_cache

    ctx = SpecContext.__new__(SpecContext)
    ctx.run_id = "test-run"
    ctx.user_input = intent_primary
    ctx.repo_path = (repo_path or tmp_path).resolve()
    ctx.workspace_root = tmp_path
    ctx.settings = settings
    ctx.gateway = gateway
    ctx.tools = build_default_registry()
    ctx.prompts = _FakePromptLoader()
    ctx.cache = cache
    ctx.trace = NullTraceWriter()
    ctx.skeleton_builder = None  # type: ignore[assignment]
    ctx.repo_skeleton = _FakeRepoSkeleton(commit_hash=commit_hash)  # type: ignore[assignment]
    ctx.intent = ConfirmedIntent(
        primary=intent_primary,
        intent_type="add_feature",
        scope=["backend"],
    )
    ctx.exploration = None
    ctx.approach = None
    ctx.spec = None
    ctx.consolidated_review = None
    ctx.total_llm_calls = 0
    ctx.total_tool_calls = 0
    ctx.iterations = 0
    ctx.run_counter = {}
    ctx.metadata = {}
    return ctx


def _sample_perspective(perspective_type: str = "data") -> Perspective:
    return Perspective(
        perspective_type=perspective_type,  # type: ignore[arg-type]
        relevant_artifacts=[
            RelevantArtifact(
                path="app/models/product.py",
                symbols=["Product"],
                line_ranges=[(1, 10)],
                importance="critical",
                reason="cached-fixture",
                snippet="class Product: ...",
            )
        ],
        conventions_discovered=["from-cache"],
    )


@pytest.fixture
def cache(tmp_path: Path) -> CacheBackend:
    cb = CacheBackend(tmp_path / "explorer-cache.db")
    yield cb
    cb.close()


# --------------------------- Key derivation tests ---------------------------


def test_compute_perspective_cache_key_is_stable() -> None:
    """Same inputs must always produce the same key."""
    k1 = compute_perspective_cache_key("/repo", "abc", "data", "intent")
    k2 = compute_perspective_cache_key("/repo", "abc", "data", "intent")
    assert k1 == k2
    assert len(k1) == 64  # full SHA-256 hex


def test_cache_key_changes_with_commit() -> None:
    """Same path/perspective/intent, different commit ⇒ different key."""
    base = compute_perspective_cache_key("/repo", "abc", "data", "intent")
    different = compute_perspective_cache_key("/repo", "xyz", "data", "intent")
    assert base != different


def test_cache_key_changes_with_perspective_type() -> None:
    """Same repo/commit/intent, different perspective ⇒ different key."""
    base = compute_perspective_cache_key("/repo", "abc", "data", "intent")
    for other in ("api", "ui", "test", "history"):
        assert compute_perspective_cache_key("/repo", "abc", other, "intent") != base


def test_cache_key_changes_with_intent() -> None:
    """Same repo/commit/perspective, different intent ⇒ different key."""
    base = compute_perspective_cache_key("/repo", "abc", "data", "add comments")
    different = compute_perspective_cache_key("/repo", "abc", "data", "fix login bug")
    assert base != different


def test_intent_summary_truncates_at_200_chars() -> None:
    long_primary = "x" * 500
    intent = ConfirmedIntent(primary=long_primary, intent_type="add_feature", scope=[])
    assert intent_summary_from(intent) == "x" * 200


def test_intent_summary_handles_none() -> None:
    assert intent_summary_from(None) == ""


# --------------------------- Roundtrip tests ---------------------------


def test_set_then_get_perspective_roundtrip(cache: CacheBackend) -> None:
    """Storing and retrieving a Perspective preserves all fields."""
    key = compute_perspective_cache_key("/repo", "abc", "data", "intent")
    original = _sample_perspective("data")
    set_cached_perspective(cache, key, original)
    restored = get_cached_perspective(cache, key)
    assert restored is not None
    assert restored.perspective_type == "data"
    assert restored.conventions_discovered == ["from-cache"]
    assert restored.relevant_artifacts[0].path == "app/models/product.py"
    assert restored.relevant_artifacts[0].symbols == ["Product"]


def test_get_perspective_returns_none_on_miss(cache: CacheBackend) -> None:
    assert get_cached_perspective(cache, "nonexistent-key") is None


# --------------------------- Integration with run_one_explorer ---------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_llm_call(
    tmp_path: Path, cache: CacheBackend
) -> None:
    """Pre-populating the cache must short-circuit the explorer ReAct loop."""
    gateway = _ExplodingGateway()
    ctx = _make_ctx(tmp_path=tmp_path, cache=cache, gateway=gateway)

    pre = _sample_perspective("data")
    key = compute_perspective_cache_key(
        str(ctx.repo_path),
        ctx.commit_hash,
        "data",
        intent_summary_from(ctx.intent),
    )
    set_cached_perspective(cache, key, pre)

    result = await run_one_explorer(ctx, "data")

    assert gateway.call_count == 0, "LLM gateway must not be called on cache HIT"
    assert result.perspective_type == "data"
    assert result.conventions_discovered == ["from-cache"]
    assert result.relevant_artifacts[0].path == "app/models/product.py"


@pytest.mark.asyncio
async def test_cache_miss_runs_and_stores(
    tmp_path: Path, cache: CacheBackend
) -> None:
    """Empty cache: explorer runs, then the result is stored under the expected key."""
    gateway = _CountingGateway()
    ctx = _make_ctx(tmp_path=tmp_path, cache=cache, gateway=gateway)

    expected_key = compute_perspective_cache_key(
        str(ctx.repo_path),
        ctx.commit_hash,
        "data",
        intent_summary_from(ctx.intent),
    )
    assert get_cached_perspective(cache, expected_key) is None

    result = await run_one_explorer(ctx, "data")

    assert gateway.call_count >= 1, "LLM must be invoked on cache MISS"
    assert result.perspective_type == "data"

    stored = get_cached_perspective(cache, expected_key)
    assert stored is not None, "Perspective must be stored after a successful run"
    assert stored.perspective_type == "data"


@pytest.mark.asyncio
async def test_no_explorer_cache_flag_bypasses(
    tmp_path: Path, cache: CacheBackend
) -> None:
    """``settings.explorer.use_cache = False`` ⇒ neither read nor write happens."""
    gateway = _CountingGateway()
    ctx = _make_ctx(tmp_path=tmp_path, cache=cache, gateway=gateway, use_cache=False)

    expected_key = compute_perspective_cache_key(
        str(ctx.repo_path),
        ctx.commit_hash,
        "data",
        intent_summary_from(ctx.intent),
    )
    # Pre-populate with a sentinel value — bypass means it must NOT be returned.
    sentinel = _sample_perspective("data")
    sentinel.conventions_discovered = ["sentinel-should-not-be-returned"]
    set_cached_perspective(cache, expected_key, sentinel)

    result = await run_one_explorer(ctx, "data")

    assert gateway.call_count >= 1, "Bypass flag must still execute the explorer"
    assert (
        "sentinel-should-not-be-returned" not in result.conventions_discovered
    ), "Cache must be ignored when use_cache=False"

    # And the bypass run must NOT overwrite the pre-existing entry either.
    still_sentinel = get_cached_perspective(cache, expected_key)
    assert still_sentinel is not None
    assert still_sentinel.conventions_discovered == [
        "sentinel-should-not-be-returned"
    ], "Bypass flag must not write back to the cache"
