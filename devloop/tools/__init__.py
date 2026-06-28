"""Tool package exports + convenience builders."""

from devloop.tools.base import AgentScratchpad, BaseTool, ToolContext
from devloop.tools.code_search import CodeSearchTool
from devloop.tools.file_read import FileReadTool
from devloop.tools.git_tools import GitBlameTool, GitLogTool
from devloop.tools.navigation import FindSimilarFilesTool, ListDirectoryTool
from devloop.tools.output_tools import (
    FlagIssueTool,
    MarkAsRelevantTool,
    TakeNoteTool,
)
from devloop.tools.project_understanding import (
    FindDataMigrationsTool,
    ReadConfigsTool,
    ReadDocsAndReadmeTool,
    ReadTestsTool,
)
from devloop.tools.references import FindCalleesTool, FindReferencesTool
from devloop.tools.registry import AgentRole, ToolRegistry


def build_default_registry() -> ToolRegistry:
    """Create a registry with all 11 code tools + 3 output tools."""
    reg = ToolRegistry()
    reg.register_many(
        [
            # Code navigation (5)
            CodeSearchTool(),
            FileReadTool(),
            FindReferencesTool(),
            FindCalleesTool(),
            FindSimilarFilesTool(),
            # Project understanding (4)
            ReadTestsTool(),
            ReadDocsAndReadmeTool(),
            ReadConfigsTool(),
            FindDataMigrationsTool(),
            # History (2)
            GitLogTool(),
            GitBlameTool(),
            # Navigation extra
            ListDirectoryTool(),
            # Output tools (3)
            MarkAsRelevantTool(),
            TakeNoteTool(),
            FlagIssueTool(),
        ]
    )
    return reg


__all__ = [
    "AgentRole",
    "AgentScratchpad",
    "BaseTool",
    # Tools
    "CodeSearchTool",
    "FileReadTool",
    "FindCalleesTool",
    "FindDataMigrationsTool",
    "FindReferencesTool",
    "FindSimilarFilesTool",
    "FlagIssueTool",
    "GitBlameTool",
    "GitLogTool",
    "ListDirectoryTool",
    "MarkAsRelevantTool",
    "ReadConfigsTool",
    "ReadDocsAndReadmeTool",
    "ReadTestsTool",
    "TakeNoteTool",
    "ToolContext",
    "ToolRegistry",
    "build_default_registry",
]
