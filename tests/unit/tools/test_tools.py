"""Tests for tools — focus on file_read, code_search, output tools, path safety."""

from pathlib import Path

import pytest

from devloop.cache import NullCache
from devloop.tools import (
    AgentRole,
    AgentScratchpad,
    CodeSearchTool,
    FileReadTool,
    FindReferencesTool,
    FindSimilarFilesTool,
    FlagIssueTool,
    GitLogTool,
    ListDirectoryTool,
    MarkAsRelevantTool,
    ReadConfigsTool,
    ReadDocsAndReadmeTool,
    ReadTestsTool,
    TakeNoteTool,
    ToolContext,
    build_default_registry,
)
from devloop.tools._paths import PathOutsideRepoError, resolve_repo_path


def make_ctx(repo_path: Path) -> ToolContext:
    return ToolContext(
        repo_path=repo_path,
        commit_hash="testcommit",
        scratchpad=AgentScratchpad(),
        cache=NullCache(),
        run_id="test-run",
        agent_name="test_agent",
        enable_cache=False,
    )


# --- Path safety ---


def test_resolve_repo_path_blocks_escape(fixture_repo, tmp_path):
    with pytest.raises(PathOutsideRepoError):
        resolve_repo_path(fixture_repo, "../../etc/passwd")


def test_resolve_repo_path_allows_subpath(fixture_repo):
    p = resolve_repo_path(fixture_repo, "app/models/user.py")
    assert p.is_file()


# --- file_read ---


async def test_file_read_basic(fixture_repo):
    tool = FileReadTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": "app/models/user.py"}, ctx)
    assert "User" in res
    assert "lines" in res


async def test_file_read_with_line_range(fixture_repo):
    tool = FileReadTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": "app/models/user.py", "start_line": 1, "end_line": 5}, ctx)
    assert "lines 1-5" in res


async def test_file_read_caps_at_200_lines(fixture_repo, tmp_path):
    # Create a large file
    big = tmp_path / "repo"
    big.mkdir()
    (big / "big.py").write_text("\n".join(f"x = {i}" for i in range(500)))
    tool = FileReadTool()
    ctx = make_ctx(big)
    res = await tool.execute({"path": "big.py", "start_line": 1, "end_line": 500}, ctx)
    assert "truncated to 200 lines" in res


async def test_file_read_nonexistent(fixture_repo):
    tool = FileReadTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": "no_such_file.py"}, ctx)
    assert "[error]" in res


async def test_file_read_blocks_path_escape(fixture_repo):
    tool = FileReadTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": "../../etc/passwd"}, ctx)
    assert "[error]" in res


# --- code_search ---


async def test_code_search_finds_user_class(fixture_repo):
    tool = CodeSearchTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"query": "class User"}, ctx)
    assert "user.py" in res.lower() or "match" in res.lower()


async def test_code_search_empty_query_errors(fixture_repo):
    tool = CodeSearchTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"query": ""}, ctx)
    assert "[error]" in res


# --- list_directory ---


async def test_list_directory_root(fixture_repo):
    tool = ListDirectoryTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": ".", "max_depth": 1}, ctx)
    assert "app/" in res or "app" in res


async def test_list_directory_blocks_path_escape(fixture_repo):
    tool = ListDirectoryTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": "../../../"}, ctx)
    assert "[error]" in res


# --- read_tests / docs / configs ---


async def test_read_tests_finds_test_files(fixture_repo):
    tool = ReadTestsTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"topic": "products"}, ctx)
    assert "test_products" in res


async def test_read_docs_finds_readme(fixture_repo):
    tool = ReadDocsAndReadmeTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({}, ctx)
    assert "README" in res or "ARCHITECTURE" in res


async def test_read_configs_finds_pyproject(fixture_repo):
    tool = ReadConfigsTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({}, ctx)
    assert "pyproject" in res.lower()


# --- references ---


async def test_find_references_finds_user(fixture_repo):
    tool = FindReferencesTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"symbol": "User"}, ctx)
    # User is referenced in user.py; may or may not be in other files
    assert "user.py" in res or "No references" in res


async def test_find_references_rejects_bad_symbol(fixture_repo):
    tool = FindReferencesTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"symbol": "not a symbol"}, ctx)
    assert "[error]" in res


# --- find_similar_files ---


async def test_find_similar_files(fixture_repo):
    tool = FindSimilarFilesTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"path": "app/models/user.py"}, ctx)
    # Should find product.py as similar
    assert "product.py" in res or "No structurally" in res


# --- Output tools ---


async def test_mark_as_relevant_writes_to_scratchpad(fixture_repo):
    tool = MarkAsRelevantTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute(
        {
            "path": "app/models/user.py",
            "importance": "critical",
            "reason": "defines the user entity",
        },
        ctx,
    )
    assert len(ctx.scratchpad.relevant_artifacts) == 1
    assert "Noted" in res


async def test_take_note_writes_to_scratchpad(fixture_repo):
    tool = TakeNoteTool()
    ctx = make_ctx(fixture_repo)
    await tool.execute({"note": "project uses pydantic v2"}, ctx)
    assert "pydantic" in ctx.scratchpad.notes[0]


async def test_flag_issue_writes_to_scratchpad(fixture_repo):
    tool = FlagIssueTool()
    ctx = make_ctx(fixture_repo)
    await tool.execute(
        {
            "severity": "critical",
            "location": "FR-001",
            "description": "FR uses term `User account` but project uses `User`",
            "evidence": "app/models/user.py defines class User",
        },
        ctx,
    )
    assert len(ctx.scratchpad.issues) == 1
    assert ctx.scratchpad.issues[0]["severity"] == "critical"


# --- Registry visibility ---


def test_registry_exposes_correct_tool_counts():
    reg = build_default_registry()
    explorer_specs = reg.specs_for(AgentRole.EXPLORER)
    reviewer_specs = reg.specs_for(AgentRole.REVIEWER)
    # Explorer: 12 code tools + 2 output tools = 14
    assert len(explorer_specs) == 14
    # Reviewer: 12 code tools + 1 output tool (flag_issue) = 13
    assert len(reviewer_specs) == 13


def test_registry_denies_disallowed_tool_for_reviewer():
    reg = build_default_registry()
    reviewer_specs = reg.specs_for(AgentRole.REVIEWER)
    names = {s.name for s in reviewer_specs}
    assert "mark_as_relevant" not in names
    assert "take_note" not in names
    assert "flag_issue" in names


# --- git_log (best-effort, may skip if not a git repo) ---


async def test_git_log_returns_string(fixture_repo):
    tool = GitLogTool()
    ctx = make_ctx(fixture_repo)
    res = await tool.execute({"last_n": 5}, ctx)
    # Either commits, no history, or error — but always a string
    assert isinstance(res, str)
    assert len(res) > 0
