"""DevLoop CLI — entry point for running the spec phase."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from devloop.config import load_settings
from devloop.spec_phase import create_orchestrator

app = typer.Typer(
    name="devloop",
    help="DevLoop full-pipeline development agent — spec phase CLI",
    no_args_is_help=True,
)
console = Console()


# Coarse $-per-1K-token estimates (update as model pricing changes).
COST_PER_1K_INPUT = {
    "claude-opus-4-7": 0.015,
    "claude-opus-4.7": 0.015,
    "claude-sonnet-4-6": 0.003,
    "gpt-5.5": 0.010,
    "gpt-5.4": 0.005,
}
COST_PER_1K_OUTPUT = {
    "claude-opus-4-7": 0.075,
    "claude-opus-4.7": 0.075,
    "claude-sonnet-4-6": 0.015,
    "gpt-5.5": 0.040,
    "gpt-5.4": 0.020,
}


def _configure_logging(level: str) -> None:
    """Unified structlog configuration with stdlib bridge.

    All modules use either `logging.getLogger(__name__)` or
    `structlog.get_logger(__name__)`; both end up rendered consistently here.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=[logging.StreamHandler()],
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )


def _estimate_cost_usd(spec_metadata, trace_path: Path | None) -> tuple[float, dict]:
    """Estimate cost from the trace.jsonl using the per-stage cost summary module.

    Falls back to the older coarse $-per-1K-token heuristic only if the new
    parser raises — keeps behavior robust against malformed trace files.
    """
    if trace_path is None or not trace_path.exists():
        return 0.0, {}
    from devloop.llm.trace_analyzer import parse_trace
    from devloop.tools.cost_summary import parse_trace_file

    try:
        cs = parse_trace_file(trace_path)
        cost = cs.total_estimated_cost_usd
        totals = {
            "total_input_tokens": cs.total_input_tokens,
            "total_output_tokens": cs.total_output_tokens,
            "total_llm_calls": cs.total_llm_calls,
            "total_tool_calls": 0,
        }
    except Exception:
        summary = parse_trace(trace_path)
        input_rate = max(COST_PER_1K_INPUT.values(), default=0.005)
        output_rate = max(COST_PER_1K_OUTPUT.values(), default=0.020)
        cost = (summary.total_input_tokens / 1000.0) * input_rate + (
            summary.total_output_tokens / 1000.0
        ) * output_rate
        totals = {
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
            "total_llm_calls": summary.total_llm_calls,
            "total_tool_calls": summary.total_tool_calls,
        }
        return cost, totals

    # Pull tool-call count from the legacy analyzer (cost_summary only tracks LLMs).
    try:
        legacy = parse_trace(trace_path)
        totals["total_tool_calls"] = legacy.total_tool_calls
    except Exception:
        pass
    return cost, totals


@app.command()
def spec(
    description: str = typer.Argument(
        ...,
        help="Feature description in natural language (Chinese or English)",
    ),
    repo: Path = typer.Option(
        Path.cwd(),
        "--repo",
        "-r",
        help="Path to the target repository (defaults to current directory)",
    ),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Override workspace root (defaults to ./specs)",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="DEBUG | INFO | WARNING | ERROR"),
    enable_multi_explorer: bool = typer.Option(
        True, "--multi-explorer/--single-explorer", help="Use all 5 explorers vs single explorer (MVP)"
    ),
    enable_multi_reviewer: bool = typer.Option(
        True, "--multi-reviewer/--single-reviewer", help="Use 4 reviewers vs single reviewer (MVP)"
    ),
    enable_multi_candidate: bool = typer.Option(
        True, "--multi-candidate/--single-candidate", help="Generate 3 candidate plans vs 1 (MVP)"
    ),
    no_explorer_cache: bool = typer.Option(
        False,
        "--no-explorer-cache",
        help=(
            "Disable the per-perspective Perspective cache for this run "
            "(default: cache is enabled, keyed by repo+commit+perspective+intent)."
        ),
    ),
) -> None:
    """Generate a feature specification from a natural-language description."""
    _configure_logging(log_level)

    settings = load_settings()
    if workspace:
        settings.paths.workspace_root = workspace
    settings.orchestrator.enable_multi_view_explorer = enable_multi_explorer
    settings.orchestrator.enable_multi_reviewer = enable_multi_reviewer
    settings.orchestrator.enable_multi_candidate_approach = enable_multi_candidate
    if no_explorer_cache:
        settings.explorer.use_cache = False

    table = Table(title="Spec phase run", show_header=False)
    table.add_row("Feature", description)
    table.add_row("Repo", str(repo.resolve()))
    table.add_row(
        "Writer",
        f"{settings.llm.primary_model} ({settings.llm.primary_provider})",
    )
    table.add_row(
        "Reviewer",
        f"{settings.llm.cross_review_model} ({settings.llm.cross_review_provider})",
    )
    table.add_row(
        "Explorer mode",
        "5-perspective parallel" if enable_multi_explorer else "single (MVP)",
    )
    table.add_row(
        "Reviewer mode",
        "4-angle parallel" if enable_multi_reviewer else "single (MVP)",
    )
    console.print(Panel.fit(table))

    if not settings.llm.anthropic_api_key and settings.llm.primary_provider == "anthropic":
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY env var is required.")
        sys.exit(2)
    if not settings.llm.openai_api_key and settings.llm.cross_review_provider == "openai":
        console.print("[red]Error:[/red] OPENAI_API_KEY env var is required.")
        sys.exit(2)

    orchestrator = create_orchestrator(settings)

    try:
        result = asyncio.run(orchestrator.run(description, repo))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Partial artifacts may exist in ./specs/[/yellow]")
        sys.exit(130)

    if not result.ok:
        console.print(f"[red]Preflight failed:[/red] {result.reason}")
        if result.suggestion:
            console.print(f"[yellow]Suggestion:[/yellow] {result.suggestion}")
        sys.exit(3)

    # Cost summary
    trace_path = (result.workspace / "trace.jsonl") if result.workspace else None
    cost, totals = _estimate_cost_usd(result.spec.metadata if result.spec else None, trace_path)

    console.print()
    console.print(
        Panel.fit(
            f"[bold green]Spec produced[/bold green]\n"
            f"Workspace: {result.workspace}\n"
            f"Feature ID: {result.spec.metadata.feature_id if result.spec else '<unknown>'}\n"
            f"Iterations: {result.spec.metadata.iterations if result.spec else 0}\n"
            f"Needs review: {result.spec.metadata.needs_review if result.spec else 'N/A'}\n"
            f"LLM calls: {totals.get('total_llm_calls', 0)} | "
            f"tool calls: {totals.get('total_tool_calls', 0)}\n"
            f"Tokens: in={totals.get('total_input_tokens', 0):,} "
            f"out={totals.get('total_output_tokens', 0):,}\n"
            f"Estimated cost: ${cost:.4f}\n"
            f"Spec MD: {result.workspace / 'spec.md' if result.workspace else ''}\n"
            f"Spec JSON: {result.workspace / 'spec.json' if result.workspace else ''}",
            title="Done",
        )
    )

    # Top 3 stages by cost — gives the user a quick bottleneck signal.
    _print_top_stages(trace_path, n=3)


def _print_top_stages(trace_path: Path | None, *, n: int = 3) -> None:
    """Print the top-N stages by estimated cost. Silent on missing trace."""
    if trace_path is None or not trace_path.exists():
        return
    try:
        from devloop.tools.cost_summary import parse_trace_file
        summary = parse_trace_file(trace_path)
    except Exception as exc:  # pragma: no cover - best effort
        console.print(f"[yellow]cost summary unavailable: {exc}[/yellow]")
        return
    if not summary.per_stage:
        return
    top = summary.per_stage[:n]
    t = Table(title=f"Top {len(top)} stages by cost", show_header=True)
    t.add_column("Stage")
    t.add_column("Calls", justify="right")
    t.add_column("Tokens (in/out)", justify="right")
    t.add_column("Cost (USD)", justify="right")
    t.add_column("p95 latency (ms)", justify="right")
    for s in top:
        t.add_row(
            s.stage,
            str(s.llm_calls),
            f"{s.input_tokens:,}/{s.output_tokens:,}",
            f"${s.estimated_cost_usd:.4f}",
            f"{s.latency_ms_p95:.0f}",
        )
    console.print(t)


@app.command()
def version() -> None:
    """Print version."""
    from devloop import __version__

    typer.echo(f"devloop {__version__}")


@app.command(name="list-prompts")
def list_prompts(
    prompts_dir: Path = typer.Option(
        Path.cwd() / "prompts",
        "--dir",
        help="Path to prompts directory",
    ),
) -> None:
    """List all available prompts."""
    from devloop.spec_phase.prompts_loader import PromptLoader

    loader = PromptLoader(prompts_dir)
    names = loader.list_available()
    for n in names:
        typer.echo(n)


@app.command(name="analyze-trace")
def analyze_trace(
    workspace: Path = typer.Argument(
        ..., help="Path to a spec run workspace (specs/<run_id>/)"
    ),
) -> None:
    """Analyze the trace.jsonl from a spec phase run."""
    from devloop.llm.trace_analyzer import parse_trace, render_summary_markdown

    trace_path = workspace / "trace.jsonl"
    if not trace_path.exists():
        console.print(f"[red]trace.jsonl not found at {trace_path}[/red]")
        raise typer.Exit(1)
    summary = parse_trace(trace_path)
    console.print(render_summary_markdown(summary))


@app.command(name="cost-summary")
def cost_summary(
    trace_path: Path = typer.Argument(
        ..., help="Path to trace.jsonl from a spec run (e.g. specs/<run_id>/trace.jsonl)"
    ),
    output_format: str = typer.Option(
        "markdown", "--format", "-f", help="Output format: markdown | json"
    ),
) -> None:
    """Compute per-stage cost & latency summary from a trace.jsonl file."""
    from devloop.tools.cost_summary import (
        parse_trace_file,
        render_summary_json,
    )
    from devloop.tools.cost_summary import (
        render_summary_markdown as render_cost_md,
    )

    if not trace_path.exists():
        console.print(f"[red]trace file not found:[/red] {trace_path}")
        raise typer.Exit(1)

    summary = parse_trace_file(trace_path)
    fmt = output_format.lower()
    if fmt == "json":
        # typer.echo (not console.print) so JSON output is pipe-friendly.
        typer.echo(render_summary_json(summary))
    elif fmt == "markdown":
        console.print(render_cost_md(summary))
    else:
        console.print(f"[red]unknown format:[/red] {output_format} (use markdown|json)")
        raise typer.Exit(2)


cache_app = typer.Typer(
    name="cache",
    help="Manage the local DevLoop cache (skeletons, tool results, explorer perspectives).",
    no_args_is_help=True,
)
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear(
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="Override the cache directory (defaults to settings.paths.cache_dir).",
    ),
    perspectives_only: bool = typer.Option(
        False,
        "--perspectives-only",
        help="Only wipe the explorer perspective cache; keep skeletons and tool calls.",
    ),
) -> None:
    """Wipe cached entries from the DevLoop SQLite cache.

    By default removes every cached row (skeletons, tool calls, explorer
    perspectives). Use ``--perspectives-only`` to clear just the explorer
    cache added in Sprint D.
    """
    from devloop.cache import CacheBackend

    settings = load_settings()
    resolved_dir = (cache_dir or settings.paths.cache_dir).resolve()
    db_path = resolved_dir / "devloop.db"
    if not db_path.exists():
        console.print(
            f"[yellow]No cache database found at {db_path}; nothing to clear.[/yellow]"
        )
        return

    with CacheBackend(db_path, ttl_days=settings.cache.ttl_days) as cache:
        if perspectives_only:
            removed = cache.clear_perspectives()
            scope = "explorer perspective"
        else:
            removed = cache.clear_all()
            scope = "cached"
    console.print(
        f"[green]Cleared {removed} {scope} row(s) from[/green] {db_path}"
    )


if __name__ == "__main__":
    app()
