"""file_read — read a slice of a file, with strict line-range bounds."""

from __future__ import annotations

from typing import Any

from devloop.tools._paths import PathOutsideRepoError, resolve_repo_path
from devloop.tools.base import BaseTool, ToolContext

MAX_LINES = 200
MAX_BYTES = 256 * 1024  # 256 KB


class FileReadTool(BaseTool):
    name = "file_read"
    description = (
        "Read a slice of a file from the repository. Always provide line_range "
        "for large files; single read returns at most 200 lines."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repo-relative path (e.g. 'app/models/user.py')",
            },
            "start_line": {
                "type": "integer",
                "default": 1,
                "description": "1-based starting line (inclusive)",
            },
            "end_line": {
                "type": "integer",
                "description": "1-based ending line (inclusive). If omitted, returns up to 200 lines from start_line.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        rel = args.get("path", "")
        if not rel:
            return "[error] missing 'path'"
        try:
            full = resolve_repo_path(ctx.repo_path, rel)
        except PathOutsideRepoError as e:
            return f"[error] {e}"

        if not full.exists():
            return f"[error] file not found: {rel}"
        if not full.is_file():
            return f"[error] not a file: {rel}"

        start = max(1, int(args.get("start_line", 1)))
        end_arg = args.get("end_line")

        try:
            stat = full.stat()
        except OSError as e:
            return f"[error] could not stat {rel}: {e}"

        if stat.st_size > MAX_BYTES and end_arg is None:
            return (
                f"[error] {rel} is large ({stat.st_size} bytes > {MAX_BYTES}). "
                f"Provide explicit start_line and end_line (max {MAX_LINES} lines per call)."
            )

        try:
            # Stream lines to avoid loading huge files entirely
            collected: list[str] = []
            total = 0
            with full.open("r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, start=1):
                    total = i
                    if i < start:
                        continue
                    if end_arg is not None and i > int(end_arg):
                        # We may not yet know `total` (rest of file), but for the slice
                        # we have enough — break and continue counting separately.
                        break
                    collected.append(line.rstrip("\n"))
                    if len(collected) >= MAX_LINES:
                        break
                # Continue to count remaining lines to report `total` accurately
                for line in f:
                    total += 1
        except OSError as e:
            return f"[error] could not read {rel}: {e}"

        if not collected:
            return f"# {rel} (no content in requested range; file has {total} lines total)"

        end = start + len(collected) - 1
        # Only mark as truncated when we actually hit MAX_LINES (genuine cut-off)
        # OR when the caller asked for a range that ends past the actual file end.
        # An end_line > end after MAX_LINES is genuine truncation; an end_line > end
        # when we returned the full requested slice (i.e. EOF was reached before
        # end_line, but we DID collect every requested line that exists) is NOT
        # truncation — the file simply ended. Fixes PR Assistant AI Code Review #44884.
        requested_end = int(end_arg) if end_arg is not None else None
        hit_max_lines = len(collected) == MAX_LINES
        truncated = hit_max_lines and (
            requested_end is None or requested_end > end
        )

        body = "\n".join(
            f"{start + i:>6}: {line}" for i, line in enumerate(collected)
        )
        header = f"# {rel} (lines {start}-{end} of {total})"
        if truncated:
            header += f" [truncated to {MAX_LINES} lines]"
        return f"{header}\n{body}"
