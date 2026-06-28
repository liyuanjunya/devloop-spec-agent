"""Output tools: mark_as_relevant / take_note / flag_issue.

These are stateful "side-effect" tools that write to the AgentScratchpad
instead of returning information. They give the LLM a structured way to
publish findings beyond the chat transcript.
"""

from __future__ import annotations

from typing import Any

from devloop.tools.base import BaseTool, ToolContext


class MarkAsRelevantTool(BaseTool):
    name = "mark_as_relevant"
    description = (
        "Mark a file (with optional symbols/line ranges) as relevant to the "
        "feature being analyzed. Provide importance: 'critical' (must understand "
        "to write the spec), 'relevant' (provides useful context), 'peripheral' "
        "(loosely related). Always provide a clear reason."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repo-relative path."},
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional symbols within the file, e.g. ['User.username'].",
            },
            "line_ranges": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "Optional list of [start, end] inclusive line ranges.",
            },
            "importance": {
                "type": "string",
                "enum": ["critical", "relevant", "peripheral"],
            },
            "reason": {"type": "string", "description": "Why is this relevant?"},
            "snippet": {
                "type": "string",
                "description": "Optional: ≤30-line code snippet to remember.",
            },
        },
        "required": ["path", "importance", "reason"],
    }

    cacheable = False  # side-effect, never cache

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        rec = {
            "path": args["path"],
            "symbols": list(args.get("symbols", [])),
            "line_ranges": [tuple(lr) for lr in args.get("line_ranges", [])],
            "importance": args["importance"],
            "reason": args["reason"],
            "snippet": args.get("snippet", "")[:2000],
        }
        ctx.scratchpad.relevant_artifacts.append(rec)
        return f"Noted: {args['path']} marked as {args['importance']}."


class TakeNoteTool(BaseTool):
    name = "take_note"
    description = (
        "Record a project convention, finding, or observation you want to "
        "remember for the spec-writing phase. Use short, declarative statements "
        "(e.g. 'Project uses pydantic v2 for input validation', 'Migrations use Alembic')."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Short declarative note."},
        },
        "required": ["note"],
    }

    cacheable = False

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        note = args["note"].strip()
        if not note:
            return "[error] empty note"
        ctx.scratchpad.notes.append(note)
        return f"Noted: {note[:120]}"


class FlagIssueTool(BaseTool):
    name = "flag_issue"
    description = (
        "Report a problem with the spec. severity ∈ {critical, high, medium}. "
        "ALWAYS provide concrete evidence — quote spec text and/or cite code via "
        "path:line. Do NOT give scores, praise, or rewrite suggestions; only "
        "list issues."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium"],
            },
            "location": {
                "type": "string",
                "description": "e.g. 'FR-007' or 'Key Entity Comment' or 'spec.md:123'.",
            },
            "description": {"type": "string", "description": "What is the problem?"},
            "evidence": {
                "type": "string",
                "description": "Concrete proof: quote spec text, cite code path:line, etc.",
            },
            "suggested_action": {
                "type": "string",
                "description": "Optional: a suggested correction.",
            },
        },
        "required": ["severity", "location", "description", "evidence"],
    }

    cacheable = False

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        rec = {
            "severity": args["severity"],
            "location": args["location"],
            "description": args["description"],
            "evidence": args["evidence"],
            "suggested_action": args.get("suggested_action"),
        }
        ctx.scratchpad.issues.append(rec)
        return f"Issue flagged: [{args['severity']}] {args['location']}"
