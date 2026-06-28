"""Safe path resolution helpers — every file-reading tool MUST go through these."""

from __future__ import annotations

from pathlib import Path


class PathOutsideRepoError(Exception):
    pass


def resolve_repo_path(repo_root: Path, target: str | Path) -> Path:
    """Resolve `target` (possibly relative) against repo_root, ensuring it stays inside.

    Raises PathOutsideRepoError if the resolved path escapes the repo.
    """
    repo_root = Path(repo_root).resolve()
    p = Path(target)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    else:
        p = p.resolve()

    try:
        p.relative_to(repo_root)
    except ValueError as e:
        raise PathOutsideRepoError(
            f"Path '{target}' resolves outside the repo root '{repo_root}'"
        ) from e
    return p
