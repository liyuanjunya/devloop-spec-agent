"""code_search — keyword search via ripgrep (with grep fallback)."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

from devloop.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


MAX_SUBPROCESS_BYTES = 5 * 1024 * 1024  # 5 MiB


class CodeSearchTool(BaseTool):
    name = "code_search"
    description = (
        "Search code in the repository for a keyword or regex. Returns matching "
        "file paths with line numbers and the matching line. Use this to find "
        "files relevant to a feature, locate where a symbol is defined, etc."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword or regex pattern to search for",
            },
            "mode": {
                "type": "string",
                "enum": ["keyword", "regex"],
                "default": "keyword",
                "description": "keyword = literal string; regex = regular expression",
            },
            "path_glob": {
                "type": "string",
                "description": "Optional glob to restrict search (e.g. '**/*.py'). Defaults to all files.",
            },
            "max_results": {
                "type": "integer",
                "default": 50,
                "description": "Max number of matching lines to return (1-200).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        query = args.get("query", "").strip()
        if not query:
            return "[error] empty query"
        mode = args.get("mode", "keyword")
        path_glob = args.get("path_glob")
        max_results = max(1, min(int(args.get("max_results", 50)), 200))

        rg = shutil.which("rg")
        if rg:
            return await self._run_rg(rg, query, mode, path_glob, max_results, ctx)
        return await self._run_python_fallback(query, mode, path_glob, max_results, ctx)

    async def _run_rg(
        self,
        rg_path: str,
        query: str,
        mode: str,
        path_glob: str | None,
        max_results: int,
        ctx: ToolContext,
    ) -> str:
        cmd: list[str] = [
            rg_path,
            "--line-number",
            "--no-heading",
            "--color=never",
            "--max-count",
            str(max_results),
        ]
        if mode == "keyword":
            cmd.append("--fixed-strings")
        if path_glob:
            cmd.extend(["-g", path_glob])
        cmd.append(query)
        cmd.append(str(ctx.repo_path))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except TimeoutError:
            proc.kill()
            return "[error] code_search timed out after 30s"

        if proc.returncode not in (0, 1):  # 1 = no matches, both OK
            return f"[error] rg failed: {stderr.decode(errors='replace')[:500]}"

        if len(stdout) > MAX_SUBPROCESS_BYTES:
            stdout = stdout[:MAX_SUBPROCESS_BYTES]
            truncated_note = "\n... [output truncated]"
        else:
            truncated_note = ""

        text = stdout.decode("utf-8", errors="replace")
        lines = text.splitlines()[:max_results]
        if not lines:
            return f"No matches for '{query}'."
        repo_prefix = str(ctx.repo_path).rstrip("/\\")
        out_lines = []
        for ln in lines:
            if ln.startswith(repo_prefix):
                ln = ln[len(repo_prefix) :].lstrip("/\\")
            out_lines.append(ln)
        body = "\n".join(out_lines)
        return f"Found {len(out_lines)} match(es) for '{query}':\n{body}{truncated_note}"

    async def _run_python_fallback(
        self,
        query: str,
        mode: str,
        path_glob: str | None,
        max_results: int,
        ctx: ToolContext,
    ) -> str:
        """Slow pure-Python search if rg is not installed."""
        import re

        matches = []
        if mode == "regex":
            try:
                pattern = re.compile(query)
            except re.error as e:
                return f"[error] invalid regex: {e}"
        else:
            pattern = re.compile(re.escape(query))

        glob_pattern = path_glob or "**/*"
        for f in ctx.repo_path.glob(glob_pattern):
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    rel = f.relative_to(ctx.repo_path).as_posix()
                    matches.append(f"{rel}:{i}:{line[:200]}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No matches for '{query}'."
        return f"Found {len(matches)} match(es) for '{query}':\n" + "\n".join(matches)
