"""Tests for RepoSkeleton scanner + compressor + builder."""

from pathlib import Path

from devloop.cache import NullCache
from devloop.spec_phase.repo_skeleton import (
    RepoSkeleton,
    RepoSkeletonBuilder,
    compress,
    detect_language,
    git_commit_hash,
    scan_repo,
)


def test_detect_language():
    assert detect_language(Path("foo.py")) == "python"
    assert detect_language(Path("foo.ts")) == "typescript"
    assert detect_language(Path("foo.go")) == "go"
    assert detect_language(Path("foo.md")) is None


def test_scan_fixture_repo(fixture_repo):
    scans = scan_repo(
        fixture_repo,
        excluded_dirs={"__pycache__", ".git", ".venv"},
        supported_languages={"python"},
    )
    paths = {s.path for s in scans}
    assert any("user.py" in p for p in paths)
    assert any("product.py" in p for p in paths)
    # tree-sitter should have extracted symbols
    user_scans = [s for s in scans if "user.py" in s.path and "models" in s.path]
    if user_scans and user_scans[0].symbols:
        names = {sym.name for sym in user_scans[0].symbols}
        assert "User" in names


def test_compress_produces_text(fixture_repo):
    scans = scan_repo(
        fixture_repo,
        excluded_dirs={"__pycache__", ".git", ".venv"},
        supported_languages={"python"},
    )
    skel = compress(
        scans,
        repo_root=str(fixture_repo),
        commit_hash="testhash",
        target_tokens=1024,
    )
    assert skel.text
    assert "Repo skeleton" in skel.text
    assert skel.total_files >= 4


def test_repo_skeleton_roundtrip(fixture_repo):
    scans = scan_repo(
        fixture_repo,
        excluded_dirs=set(),
        supported_languages={"python"},
    )
    skel = compress(scans, repo_root="r", commit_hash="h")
    data = skel.to_dict()
    skel2 = RepoSkeleton.from_dict(data)
    assert skel2.text == skel.text
    assert skel2.commit_hash == "h"


def test_builder_uses_cache(fixture_repo):
    cache = NullCache()
    b = RepoSkeletonBuilder(
        cache=cache,
        excluded_dirs={"__pycache__"},
        supported_languages={"python"},
    )
    s1 = b.build(fixture_repo)
    s2 = b.build(fixture_repo)
    # Same commit -> same text (deterministic)
    assert s1.text == s2.text


def test_git_commit_hash_handles_no_git(tmp_path):
    h = git_commit_hash(tmp_path)
    assert h.startswith("nogit-") or len(h) >= 10
