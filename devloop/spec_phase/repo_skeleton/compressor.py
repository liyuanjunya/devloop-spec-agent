"""Compress a full repo scan into a ~1K-token RepoSkeleton.

Strategy:
1. Top-level directory listing (always)
2. Major modules (top N by file count)
3. Per-module top symbols (limited)
4. Token-budget-aware truncation
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import tiktoken

from devloop.spec_phase.repo_skeleton.scanner import FileScan

_ENCODER_CACHE: Any = None


def _encoder():
    global _ENCODER_CACHE
    if _ENCODER_CACHE is None:
        try:
            _ENCODER_CACHE = tiktoken.encoding_for_model("gpt-4")
        except Exception:
            _ENCODER_CACHE = tiktoken.get_encoding("cl100k_base")
    return _ENCODER_CACHE


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text))


@dataclass
class ModuleSummary:
    name: str
    file_count: int
    languages: list[str]
    top_symbols: list[str] = field(default_factory=list)


@dataclass
class RepoSkeleton:
    """Compact, LLM-friendly project map."""

    repo_root: str
    commit_hash: str
    languages: dict[str, int]  # language → file count
    top_level_dirs: list[str]
    modules: list[ModuleSummary]
    total_files: int
    total_lines: int
    text: str  # The compressed, LLM-ready string representation

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "commit_hash": self.commit_hash,
            "languages": self.languages,
            "top_level_dirs": self.top_level_dirs,
            "modules": [
                {
                    "name": m.name,
                    "file_count": m.file_count,
                    "languages": m.languages,
                    "top_symbols": m.top_symbols,
                }
                for m in self.modules
            ],
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoSkeleton:
        return cls(
            repo_root=data["repo_root"],
            commit_hash=data["commit_hash"],
            languages=data["languages"],
            top_level_dirs=data["top_level_dirs"],
            modules=[
                ModuleSummary(
                    name=m["name"],
                    file_count=m["file_count"],
                    languages=m["languages"],
                    top_symbols=m["top_symbols"],
                )
                for m in data["modules"]
            ],
            total_files=data["total_files"],
            total_lines=data["total_lines"],
            text=data["text"],
        )


def _top_level_dir_of(rel_path: str) -> str:
    parts = rel_path.replace("\\", "/").split("/")
    return parts[0] if parts else "."


def _module_name_of(rel_path: str) -> str:
    """Module = first 2 directory components, e.g. 'app/api'."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _enforce_budget(
    text: str,
    budget: int,
    *,
    repo_root: str,
    languages: dict[str, int],
    modules: list[ModuleSummary],
    top_level_dirs: list[str],
) -> str:
    """If text exceeds budget, drop the per-module symbol details progressively."""
    if count_tokens(text) <= budget:
        return text

    # Round 1: drop symbol lists, keep top_level_dirs + module names + file counts
    modules_no_sym = [
        ModuleSummary(
            name=m.name,
            file_count=m.file_count,
            languages=m.languages,
            top_symbols=[],
        )
        for m in modules
    ]
    text2 = _render(
        repo_root=repo_root,
        languages=languages,
        top_level_dirs=top_level_dirs,
        modules=modules_no_sym,
        total_files=sum(languages.values()),
        total_lines=0,
    )
    if count_tokens(text2) <= budget:
        return text2

    # Round 2: keep only top 10 modules
    trimmed = modules_no_sym[:10]
    text3 = _render(
        repo_root=repo_root,
        languages=languages,
        top_level_dirs=top_level_dirs[:20],
        modules=trimmed,
        total_files=sum(languages.values()),
        total_lines=0,
    )
    if count_tokens(text3) <= budget:
        return text3

    # Final: hard cut by tokens
    enc = _encoder()
    tokens = enc.encode(text)
    return enc.decode(tokens[:budget])


def compress(
    scans: list[FileScan],
    *,
    repo_root: str,
    commit_hash: str,
    target_tokens: int = 1024,
    max_modules: int = 15,
    max_symbols_per_module: int = 6,
) -> RepoSkeleton:
    """Build a compressed RepoSkeleton from a full scan."""

    # Stats
    languages: dict[str, int] = defaultdict(int)
    top_dirs: set[str] = set()
    files_by_module: dict[str, list[FileScan]] = defaultdict(list)
    total_lines = 0

    for s in scans:
        languages[s.language] += 1
        top_dirs.add(_top_level_dir_of(s.path))
        files_by_module[_module_name_of(s.path)].append(s)
        total_lines += s.line_count

    # Rank modules by file count
    ranked_modules = sorted(
        files_by_module.items(), key=lambda kv: -len(kv[1])
    )[:max_modules]

    modules: list[ModuleSummary] = []
    for mod_name, files in ranked_modules:
        mod_langs = sorted({f.language for f in files})
        symbols_with_counts: dict[str, int] = defaultdict(int)
        for f in files:
            for sym in f.symbols:
                if sym.parent:
                    continue
                key = f"{sym.kind}:{sym.name}"
                symbols_with_counts[key] += 1

        top_symbols = [
            k for k, _ in sorted(symbols_with_counts.items(), key=lambda kv: -kv[1])
        ][:max_symbols_per_module]

        modules.append(
            ModuleSummary(
                name=mod_name,
                file_count=len(files),
                languages=mod_langs,
                top_symbols=top_symbols,
            )
        )

    top_level_dirs = sorted(top_dirs)

    text = _render(
        repo_root=repo_root,
        languages=dict(languages),
        top_level_dirs=top_level_dirs,
        modules=modules,
        total_files=len(scans),
        total_lines=total_lines,
    )

    text = _enforce_budget(
        text,
        target_tokens,
        repo_root=repo_root,
        languages=dict(languages),
        modules=modules,
        top_level_dirs=top_level_dirs,
    )

    return RepoSkeleton(
        repo_root=repo_root,
        commit_hash=commit_hash,
        languages=dict(languages),
        top_level_dirs=top_level_dirs,
        modules=modules,
        total_files=len(scans),
        total_lines=total_lines,
        text=text,
    )


def _render(
    *,
    repo_root: str,
    languages: dict[str, int],
    top_level_dirs: list[str],
    modules: list[ModuleSummary],
    total_files: int,
    total_lines: int,
) -> str:
    lines: list[str] = []
    lines.append(f"# Repo skeleton: {repo_root}")
    lines.append("")
    lines.append(f"Total source files: {total_files}, total lines: {total_lines}")
    lang_str = ", ".join(
        f"{k}={v}" for k, v in sorted(languages.items(), key=lambda kv: -kv[1])
    )
    lines.append(f"Languages: {lang_str}")
    lines.append("")
    lines.append("## Top-level directories")
    lines.append(", ".join(top_level_dirs))
    lines.append("")
    lines.append(f"## Modules (top {len(modules)} by file count)")
    for m in modules:
        lang_part = "/".join(m.languages)
        line = f"- {m.name} ({m.file_count} files, {lang_part})"
        if m.top_symbols:
            line += f": {', '.join(m.top_symbols[:6])}"
        lines.append(line)
    return "\n".join(lines)


def _enforce_budget_legacy_disabled():
    """Removed; superseded by the new _enforce_budget above."""
    raise NotImplementedError
