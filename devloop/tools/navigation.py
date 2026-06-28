"""find_similar_files / list_directory."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from devloop.tools._paths import PathOutsideRepoError, resolve_repo_path
from devloop.tools.base import BaseTool, ToolContext


class FindSimilarFilesTool(BaseTool):
    name = "find_similar_files"
    description = (
        "Given a reference file, find other files in the repo with structurally "
        "similar content (similar imports, class/function names, file naming). "
        "Useful for 'show me how this kind of feature is usually done in this project'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Reference file (repo-relative)."},
            "max_results": {"type": "integer", "default": 10},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            ref = resolve_repo_path(ctx.repo_path, args["path"])
        except (PathOutsideRepoError, KeyError) as e:
            return f"[error] {e}"
        if not ref.is_file():
            return f"[error] not a file: {args['path']}"

        ref_features = _extract_features(ref)
        if not ref_features:
            return "[error] could not extract features from reference file"

        candidates: list[tuple[float, Path]] = []
        ext = ref.suffix
        for f in ctx.repo_path.rglob(f"*{ext}"):
            if not f.is_file() or f == ref:
                continue
            f_features = _extract_features(f)
            if not f_features:
                continue
            score = _jaccard(ref_features, f_features)
            if score > 0.05:
                candidates.append((score, f))

        candidates.sort(key=lambda kv: -kv[0])
        top = candidates[: int(args.get("max_results", 10))]
        if not top:
            return f"No structurally similar files found for {args['path']}."
        lines = [
            f"  {score:.2f}  {p.relative_to(ctx.repo_path).as_posix()}" for score, p in top
        ]
        return f"Files structurally similar to {args['path']} (by name+symbol overlap):\n" + "\n".join(lines)


def _extract_features(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    features: Counter[str] = Counter()
    for tok in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text):
        # bias against very common keywords
        if tok in {"self", "this", "true", "false", "null", "None", "True", "False"}:
            continue
        features[tok] += 1
    # Keep top 80 features
    return {k for k, _ in features.most_common(80)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = (
        "List files and subdirectories under a path (repo-relative). "
        "Use this for repo navigation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "default": ".",
                "description": "Repo-relative directory; '.' for repo root.",
            },
            "max_depth": {
                "type": "integer",
                "default": 1,
                "description": "1 = direct children only.",
            },
            "max_entries": {"type": "integer", "default": 200},
        },
    }

    cacheable = False  # cheap; no need to cache

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            full = resolve_repo_path(ctx.repo_path, args.get("path", "."))
        except PathOutsideRepoError as e:
            return f"[error] {e}"
        if not full.is_dir():
            return f"[error] not a directory: {args.get('path', '.')}"

        max_depth = max(1, int(args.get("max_depth", 1)))
        max_entries = int(args.get("max_entries", 200))

        excluded_top = {
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
        }

        out_lines = []
        count = 0
        for child in sorted(full.iterdir()):
            if child.name in excluded_top:
                continue
            rel = child.relative_to(ctx.repo_path).as_posix()
            if child.is_dir():
                out_lines.append(f"{rel}/")
                if max_depth > 1:
                    for sub in _walk(child, max_depth - 1, excluded_top):
                        out_lines.append(sub.relative_to(ctx.repo_path).as_posix())
                        count += 1
                        if count >= max_entries:
                            break
            else:
                out_lines.append(rel)
            count += 1
            if count >= max_entries:
                out_lines.append("... [truncated]")
                break
        if not out_lines:
            return f"Directory {args.get('path', '.')} is empty."
        return "\n".join(out_lines)


def _walk(root: Path, depth: int, excluded: set[str]):
    if depth <= 0:
        return
    for child in sorted(root.iterdir()):
        if child.name in excluded:
            continue
        yield child
        if child.is_dir():
            yield from _walk(child, depth - 1, excluded)
