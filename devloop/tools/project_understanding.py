"""Project understanding tools: read_tests / read_docs_and_readme / read_configs / find_data_migrations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from devloop.tools.base import BaseTool, ToolContext

MAX_SNIPPET_CHARS = 8000


def _read_safe(path: Path, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... [truncated, full size {len(text)} chars]"
    return text


class ReadTestsTool(BaseTool):
    name = "read_tests"
    description = (
        "Find and read test files related to a given symbol, path, or topic. "
        "Tests are often the clearest specification of how something is expected "
        "to work — use this to understand requirements and conventions."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Symbol name, module path, or topic keyword to find tests for.",
            },
            "max_files": {"type": "integer", "default": 5},
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        topic = args.get("topic", "").strip()
        if not topic:
            return "[error] missing 'topic'"
        max_files = int(args.get("max_files", 5))

        test_dirs: list[Path] = [
            ctx.repo_path / d for d in ["tests", "test", "__tests__", "spec"]
            if (ctx.repo_path / d).is_dir()
        ]
        candidates: list[Path] = []

        # Pattern 1: filename contains topic
        topic_norm = re.sub(r"[^A-Za-z0-9_]", "", topic).lower()
        for d in test_dirs or [ctx.repo_path]:
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                if not _looks_like_test_file(f):
                    continue
                if topic_norm in f.name.lower().replace(".", "").replace("_", ""):
                    candidates.append(f)

        # Pattern 2: file content mentions topic
        if len(candidates) < max_files:
            for d in test_dirs or [ctx.repo_path]:
                for f in d.rglob("*"):
                    if not f.is_file() or not _looks_like_test_file(f) or f in candidates:
                        continue
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if topic in content:
                        candidates.append(f)
                    if len(candidates) >= max_files:
                        break
                if len(candidates) >= max_files:
                    break

        candidates = candidates[:max_files]
        if not candidates:
            return f"No test files found for topic '{topic}'."

        parts = [f"Found {len(candidates)} test file(s) for '{topic}':"]
        for f in candidates:
            rel = f.relative_to(ctx.repo_path).as_posix()
            parts.append(f"\n## {rel}\n```")
            parts.append(_read_safe(f, max_chars=4000))
            parts.append("```")
        return "\n".join(parts)


def _looks_like_test_file(f: Path) -> bool:
    name = f.name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.js")
        or name.endswith("_test.go")
        or "/tests/" in f.as_posix()
        or "/test/" in f.as_posix()
        or "/__tests__/" in f.as_posix()
    )


class ReadDocsAndReadmeTool(BaseTool):
    name = "read_docs_and_readme"
    description = (
        "Read project README.md and docs/ markdown files. Use this to learn the "
        "project's architecture, conventions, and design intent."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Optional: filter docs by keyword (case-insensitive substring match in filename or first paragraph).",
            },
            "max_files": {"type": "integer", "default": 4},
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        topic = (args.get("topic") or "").strip().lower()
        max_files = int(args.get("max_files", 4))

        candidates: list[Path] = []
        for name in ["README.md", "README", "ARCHITECTURE.md", "CONTRIBUTING.md", "DEVELOPMENT.md"]:
            p = ctx.repo_path / name
            if p.is_file():
                candidates.append(p)
        docs_dir = ctx.repo_path / "docs"
        if docs_dir.is_dir():
            for f in docs_dir.rglob("*.md"):
                candidates.append(f)

        if topic:
            filtered = []
            for f in candidates:
                if topic in f.name.lower():
                    filtered.append(f)
                    continue
                head = _read_safe(f, max_chars=2000).lower()
                if topic in head:
                    filtered.append(f)
            candidates = filtered

        candidates = candidates[:max_files]
        if not candidates:
            return "No documentation files found."

        parts = [f"Found {len(candidates)} doc file(s):"]
        for f in candidates:
            rel = f.relative_to(ctx.repo_path).as_posix()
            parts.append(f"\n## {rel}\n")
            parts.append(_read_safe(f, max_chars=3500))
        return "\n".join(parts)


class ReadConfigsTool(BaseTool):
    name = "read_configs"
    description = (
        "Read project configuration files: pyproject.toml, package.json, "
        "settings.py, .env.example, Dockerfile, Cargo.toml, go.mod etc. "
        "Use this to learn what libraries/tooling the project uses."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: subset of file names to read.",
            },
        },
    }

    KNOWN_CONFIGS = [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "requirements-dev.txt",
        "Pipfile",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "tsconfig.json",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
        ".env.sample",
        "settings.py",
        "config.py",
        "Makefile",
    ]

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        names = args.get("names") or self.KNOWN_CONFIGS
        found: list[Path] = []
        for n in names:
            # Top-level only — avoid scanning entire tree
            p = ctx.repo_path / n
            if p.is_file():
                found.append(p)
        # Also scan some common app dirs for settings.py
        for sub in ["app", "src", "backend", "server", "config"]:
            d = ctx.repo_path / sub
            if d.is_dir():
                for n in ["settings.py", "config.py", "config.yaml", "config.yml"]:
                    p = d / n
                    if p.is_file():
                        found.append(p)

        if not found:
            return "No standard config files found."

        parts = [f"Found {len(found)} config file(s):"]
        for f in found[:8]:
            rel = f.relative_to(ctx.repo_path).as_posix()
            parts.append(f"\n## {rel}\n```")
            parts.append(_read_safe(f, max_chars=3000))
            parts.append("```")
        return "\n".join(parts)


class FindDataMigrationsTool(BaseTool):
    name = "find_data_migrations"
    description = (
        "Find and read database migration files (Alembic / Django / Prisma / "
        "Sequelize / Knex). Useful to understand data model evolution."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Optional: keyword/table name to filter migrations.",
            },
            "max_files": {"type": "integer", "default": 5},
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        table = (args.get("table") or "").strip().lower()
        max_files = int(args.get("max_files", 5))

        candidate_dirs = []
        for d in ["alembic/versions", "migrations", "prisma/migrations", "db/migrate"]:
            full = ctx.repo_path / d
            if full.is_dir():
                candidate_dirs.append(full)
        if not candidate_dirs:
            return "No migration directories found (looked for alembic/versions, migrations/, prisma/migrations, db/migrate)."

        files: list[Path] = []
        for d in candidate_dirs:
            for f in sorted(d.rglob("*"), reverse=True):
                if not f.is_file():
                    continue
                if f.suffix not in {".py", ".sql", ".ts", ".js", ".rb"}:
                    continue
                if table:
                    try:
                        if table not in f.read_text(encoding="utf-8", errors="replace").lower():
                            continue
                    except OSError:
                        continue
                files.append(f)
                if len(files) >= max_files * 3:
                    break

        files = files[:max_files]
        if not files:
            return f"No migration files matched table='{table}'." if table else "No migration files found."

        parts = [f"Found {len(files)} migration file(s):"]
        for f in files:
            rel = f.relative_to(ctx.repo_path).as_posix()
            parts.append(f"\n## {rel}\n```")
            parts.append(_read_safe(f, max_chars=2500))
            parts.append("```")
        return "\n".join(parts)
