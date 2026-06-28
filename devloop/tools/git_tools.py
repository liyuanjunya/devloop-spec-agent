"""git_log / git_blame — history tools via subprocess."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from devloop.tools._paths import PathOutsideRepoError, resolve_repo_path
from devloop.tools.base import BaseTool, ToolContext

MAX_GIT_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MiB


async def _run_git(args: list[str], cwd: str, timeout: float = 15.0) -> tuple[int, str, str]:
    git = shutil.which("git")
    if not git:
        return 127, "", "git executable not found"
    proc = await asyncio.create_subprocess_exec(
        git,
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return 124, "", "git command timed out"
    # Cap output size
    if len(out) > MAX_GIT_OUTPUT_BYTES:
        out = out[:MAX_GIT_OUTPUT_BYTES] + b"\n... [git output truncated]"
    return (
        proc.returncode or 0,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


class GitLogTool(BaseTool):
    name = "git_log"
    description = (
        "Read git commit history for the repo or a specific file/directory. "
        "Returns commit hash, author, date, and subject. Use this to understand "
        "design evolution and recent changes."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional: restrict log to changes in this path.",
            },
            "last_n": {"type": "integer", "default": 15},
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        n = max(1, min(int(args.get("last_n", 15)), 100))
        cmd = ["log", f"-n{n}", "--pretty=format:%h | %an | %ad | %s", "--date=short"]
        path = args.get("path")
        if path:
            try:
                full = resolve_repo_path(ctx.repo_path, path)
                cmd.extend(["--", str(full)])
            except PathOutsideRepoError as e:
                return f"[error] {e}"
        rc, out, err = await _run_git(cmd, str(ctx.repo_path))
        if rc == 127:
            return "[error] git not installed"
        if rc != 0:
            return f"[error] git log failed: {err.strip()[:300]}"
        if not out.strip():
            return f"No git history for path '{path}'." if path else "No git history found."
        scope = f" for {path}" if path else ""
        return f"Last {n} commit(s){scope}:\n{out}"


class GitBlameTool(BaseTool):
    name = "git_blame"
    description = (
        "Get git blame for a file showing the last commit hash, author, and date "
        "for each line. Use this to identify who/when introduced specific code."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repo-relative file path."},
            "start_line": {"type": "integer", "default": 1},
            "end_line": {
                "type": "integer",
                "description": "Default: start_line + 50, capped to file length.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            full = resolve_repo_path(ctx.repo_path, args["path"])
        except (PathOutsideRepoError, KeyError) as e:
            return f"[error] {e}"
        if not full.is_file():
            return f"[error] not a file: {args['path']}"
        start = max(1, int(args.get("start_line", 1)))
        end = args.get("end_line")
        if end is None:
            end = start + 50
        end = max(start, int(end))
        cmd = [
            "blame",
            "-L",
            f"{start},{end}",
            "--date=short",
            "--",
            str(full),
        ]
        rc, out, err = await _run_git(cmd, str(ctx.repo_path))
        if rc == 127:
            return "[error] git not installed"
        if rc != 0:
            return f"[error] git blame failed: {err.strip()[:300]}"
        return out or "(empty)"
