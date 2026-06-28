"""find_references / find_callees — symbol-relationship search.

Implementation strategy:
- find_references: grep the symbol name across the repo, filter false positives
  (string literals, comments where possible).
- find_callees: best-effort by reading the file/symbol and extracting names that
  look like calls (`foo(...)`). For higher accuracy, future work uses tree-sitter
  call expressions; we expose a usable v1 here.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Any

from devloop.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FindReferencesTool(BaseTool):
    name = "find_references"
    description = (
        "Find places in the repo that reference a symbol (class, function, "
        "method or constant). Returns file paths and line numbers. Uses repository "
        "grep — may include false positives from comments or strings."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol name to find."},
            "max_results": {"type": "integer", "default": 30},
            "path_glob": {
                "type": "string",
                "description": "Optional glob to restrict search.",
            },
        },
        "required": ["symbol"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        sym = args.get("symbol", "").strip()
        if not _IDENTIFIER_RE.match(sym):
            return "[error] symbol must be a single identifier"
        max_results = int(args.get("max_results", 30))
        path_glob = args.get("path_glob")

        rg = shutil.which("rg")
        if rg:
            pattern = r"\b" + re.escape(sym) + r"\b"
            cmd: list[str] = [
                rg,
                "--line-number",
                "--no-heading",
                "--color=never",
                "--max-count",
                str(max_results),
                pattern,
            ]
            if path_glob:
                cmd.extend(["-g", path_glob])
            cmd.append(str(ctx.repo_path))

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            except TimeoutError:
                proc.kill()
                return "[error] find_references timed out"
            text = stdout.decode("utf-8", errors="replace")
            lines = text.splitlines()[:max_results]
        else:
            lines = []
            import fnmatch
            pat = re.compile(r"\b" + re.escape(sym) + r"\b")
            for f in ctx.repo_path.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(ctx.repo_path).as_posix()
                # Honor path_glob in the fallback too (fixes PR Assistant AI Code Review #44882).
                if path_glob and not fnmatch.fnmatch(rel, path_glob):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    if pat.search(line):
                        lines.append(f"{rel}:{i}:{line[:200]}")
                        if len(lines) >= max_results:
                            break
                if len(lines) >= max_results:
                    break

        repo_prefix = str(ctx.repo_path).rstrip("/\\")
        out_lines = []
        for ln in lines:
            if ln.startswith(repo_prefix):
                ln = ln[len(repo_prefix) :].lstrip("/\\")
            out_lines.append(ln)
        if not out_lines:
            return f"No references found for '{sym}'."
        return f"Found {len(out_lines)} reference(s) to '{sym}':\n" + "\n".join(out_lines)


class FindCalleesTool(BaseTool):
    name = "find_callees"
    description = (
        "Given a file path and an optional symbol name, find what functions/methods "
        "are called inside. Best-effort heuristic — useful for tracing internal flow."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repo-relative path to the source file."},
            "symbol": {
                "type": "string",
                "description": "Optional: focus only on calls inside this top-level symbol.",
            },
            "max_results": {"type": "integer", "default": 50},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        from devloop.tools._paths import PathOutsideRepoError, resolve_repo_path

        path_str = args.get("path", "")
        sym = args.get("symbol")
        max_results = int(args.get("max_results", 50))

        try:
            full = resolve_repo_path(ctx.repo_path, path_str)
        except PathOutsideRepoError as e:
            return f"[error] {e}"
        if not full.is_file():
            return f"[error] not a file: {path_str}"

        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"[error] {e}"

        # Optional: narrow to a symbol's region using tree-sitter if available.
        # If the caller specified a symbol but we cannot locate it, surface an
        # explicit error instead of silently scanning the full file — otherwise
        # the output's "within {sym}" reporting would be misleading.
        # Fixes PR Assistant AI Code Review #44883.
        if sym:
            isolated = _isolate_symbol_text(text, full.suffix.lower(), sym)
            if isolated is None:
                return f"[error] symbol not found in {path_str}: {sym}"
            text = isolated

        # Heuristic: extract `name(` occurrences, skipping keywords
        call_re = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
        keywords = {
            "if", "while", "for", "switch", "return", "and", "or", "not",
            "in", "is", "print", "len", "str", "int", "list", "dict", "set",
            "tuple", "range", "type", "func", "def", "fn", "match",
        }
        from collections import Counter

        counts: Counter[str] = Counter()
        for _line_no, line in enumerate(text.splitlines(), 1):
            for m in call_re.finditer(line):
                name = m.group(1)
                if name in keywords:
                    continue
                counts[name] += 1
        if not counts:
            return f"No callee patterns found in {path_str}."
        top = counts.most_common(max_results)
        lines = [f"  {name}: {n}" for name, n in top]
        scope = f" within {sym}" if sym else ""
        return (
            f"Callees in {path_str}{scope} (top {len(top)} by frequency):\n"
            + "\n".join(lines)
        )


def _isolate_symbol_text(text: str, ext: str, sym: str) -> str | None:
    """Naive isolation: find `def sym` / `function sym` / `class sym` then read until dedent / next top-level."""
    lines = text.splitlines()
    patterns = [
        f"def {sym}",
        f"async def {sym}",
        f"function {sym}",
        f"class {sym}",
        f"func {sym}",
        f"fn {sym}",
    ]
    start = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        for p in patterns:
            if stripped.startswith(p):
                start = i
                break
        if start is not None:
            break
    if start is None:
        return None
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and line.strip():
            end = j
            break
    return "\n".join(lines[start:end])
