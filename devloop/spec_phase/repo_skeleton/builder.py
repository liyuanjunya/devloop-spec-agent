"""RepoSkeleton builder — scan + compress + cache."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from devloop.cache import CacheBackend
from devloop.spec_phase.repo_skeleton.compressor import RepoSkeleton, compress
from devloop.spec_phase.repo_skeleton.scanner import scan_repo

logger = logging.getLogger(__name__)


def git_commit_hash(repo_path: Path) -> str:
    """Best-effort `git rev-parse HEAD`. Returns 'no-git' if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Fallback: use mtime of repo root + a marker
    return f"nogit-{int(repo_path.stat().st_mtime)}"


class RepoSkeletonBuilder:
    def __init__(
        self,
        cache: CacheBackend,
        *,
        target_tokens: int = 1024,
        excluded_dirs: list[str] | None = None,
        supported_languages: list[str] | None = None,
        max_files: int = 5000,
    ):
        self.cache = cache
        self.target_tokens = target_tokens
        self.excluded_dirs = set(
            excluded_dirs
            or [
                "node_modules",
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                "dist",
                "build",
                "target",
            ]
        )
        self.supported_languages = set(
            supported_languages
            or ["python", "javascript", "typescript", "go", "rust", "java"]
        )
        self.max_files = max_files

    def build(self, repo_path: Path, *, force_refresh: bool = False) -> RepoSkeleton:
        repo_path = Path(repo_path).resolve()
        commit_hash = git_commit_hash(repo_path)

        if not force_refresh:
            cached = self.cache.get_skeleton(commit_hash)
            if cached:
                logger.debug("RepoSkeleton cache HIT for %s", commit_hash[:12])
                return RepoSkeleton.from_dict(cached)

        logger.info("Scanning repo %s (commit %s)", repo_path, commit_hash[:12])
        scans = scan_repo(
            repo_path,
            excluded_dirs=self.excluded_dirs,
            supported_languages=self.supported_languages,
            max_files=self.max_files,
        )
        skeleton = compress(
            scans,
            repo_root=str(repo_path),
            commit_hash=commit_hash,
            target_tokens=self.target_tokens,
        )
        self.cache.set_skeleton(commit_hash, str(repo_path), skeleton.to_dict())
        return skeleton
