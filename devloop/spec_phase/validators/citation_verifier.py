"""Mechanical citation verifier.

Spec writers regularly produce ``FunctionalRequirement.code_references``
with line ranges that don't line up with the cited symbols (the Mealie
case-6 v2 spec, for example, claimed ``duplicate_one`` was at line 358
of recipe_crud_routes.py when it actually lives at lines 450-451). The
LLM was instructed to verify but didn't, so we do it deterministically
at the orchestrator level.

Each citation is checked for:

* ``file_not_found`` — the cited path doesn't exist on disk.
* ``range_out_of_bounds`` — ``start < 1``, ``end`` past the file length,
  or ``start > end``. One problem per bad range.
* ``symbols_missing`` — a listed symbol is absent from every cited line
  range (after stripping pure-comment lines in Python). One problem per
  missing symbol.
* ``no_line_ranges_with_symbols`` — symbols are listed but no line
  ranges exist to verify them against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devloop.spec_phase.schemas import CodeRef, Spec

PROBLEM_FILE_NOT_FOUND = "file_not_found"
PROBLEM_RANGE_OUT_OF_BOUNDS = "range_out_of_bounds"
PROBLEM_SYMBOLS_MISSING = "symbols_missing"
PROBLEM_NO_RANGES_WITH_SYMBOLS = "no_line_ranges_with_symbols"
PROBLEM_INVALID_PATH = "invalid_path"


@dataclass(slots=True, frozen=True)
class CitationProblem:
    """One verification failure to surface back to the writer."""

    fr_id: str
    ref_index: int
    path: str
    line_ranges: list[tuple[int, int]]
    problem: str
    detail: str


def _strip_comment_lines(lines: list[str], path: str) -> list[str]:
    """Drop pure-comment lines so symbols only mentioned in comments don't match.

    For Python files: lines whose first non-whitespace char is ``#`` are
    removed. For other languages, every line is preserved verbatim — we
    don't pretend to know every comment syntax.
    """
    if not path.endswith(".py"):
        return list(lines)
    return [ln for ln in lines if not ln.lstrip().startswith("#")]


def _is_path_safe(repo_root: Path, rel_path: str) -> bool:
    """Reject absolute paths and paths that escape the repo root.

    A code reference must point INSIDE the target repo. Absolute paths
    (``/etc/passwd``, ``C:\\Windows\\...``) and traversal (``../../etc/passwd``,
    ``mealie/../../etc/passwd``) are rejected to prevent the writer from
    citing things outside the project — which would also bypass the
    repo-scoped grounding the spec is supposed to verify against.
    """
    p = Path(rel_path)
    if p.is_absolute() or rel_path.startswith(("/", "\\")):
        return False
    # Drive-letter paths on Windows also count as absolute (handled by is_absolute()
    # on Windows) but be defensive for cross-platform: explicit ``X:`` detection.
    if len(rel_path) >= 2 and rel_path[1] == ":":
        return False
    try:
        target = (repo_root / rel_path).resolve(strict=False)
        root = repo_root.resolve(strict=False)
    except (OSError, ValueError):
        return False
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _read_file_lines(repo_root: Path, rel_path: str) -> list[str] | None:
    """Read the file as a list of lines; ``None`` if missing or unreadable."""
    if not _is_path_safe(repo_root, rel_path):
        return None
    file_path = repo_root / rel_path
    if not file_path.is_file():
        return None
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text.splitlines()


def _slice_range(lines: list[str], start: int, end: int) -> list[str]:
    """Return lines[start-1:end] clamped to the available range (inclusive on both ends)."""
    s = max(start - 1, 0)
    e = min(end, len(lines))
    if s >= e:
        return []
    return lines[s:e]


def verify_citation(repo_root: Path, ref: CodeRef) -> list[CitationProblem]:
    """Verify a single CodeRef. Returns an empty list if everything checks out."""
    problems: list[CitationProblem] = []

    # Path-safety check first — never traverse outside the repo root.
    if not _is_path_safe(repo_root, ref.path):
        problems.append(
            CitationProblem(
                fr_id="",
                ref_index=0,
                path=ref.path,
                line_ranges=list(ref.line_ranges),
                problem=PROBLEM_INVALID_PATH,
                detail=(
                    f"Path {ref.path!r} is absolute or escapes the repo root via "
                    f"'..' / drive-letter / leading separator. Code references "
                    "must be repo-relative and stay inside the repo."
                ),
            )
        )
        return problems

    file_path = repo_root / ref.path
    if not file_path.is_file():
        problems.append(
            CitationProblem(
                fr_id="",
                ref_index=0,
                path=ref.path,
                line_ranges=list(ref.line_ranges),
                problem=PROBLEM_FILE_NOT_FOUND,
                detail=f"File not found at {ref.path!r} relative to repo root.",
            )
        )
        return problems

    lines = _read_file_lines(repo_root, ref.path)
    if lines is None:
        # File existed at the stat check but became unreadable — surface it the same way.
        problems.append(
            CitationProblem(
                fr_id="",
                ref_index=0,
                path=ref.path,
                line_ranges=list(ref.line_ranges),
                problem=PROBLEM_FILE_NOT_FOUND,
                detail=f"File at {ref.path!r} is not readable as UTF-8 text.",
            )
        )
        return problems

    file_line_count = len(lines)

    # Symbols-without-ranges is independent of range/symbol verification.
    if ref.symbols and not ref.line_ranges:
        problems.append(
            CitationProblem(
                fr_id="",
                ref_index=0,
                path=ref.path,
                line_ranges=[],
                problem=PROBLEM_NO_RANGES_WITH_SYMBOLS,
                detail=(
                    f"Symbols {list(ref.symbols)} are listed but no line_ranges "
                    "were provided to verify them against. Either omit the "
                    "symbols or supply at least one line range that contains them."
                ),
            )
        )

    # Range validation — one problem per bad range; track survivors for symbol check.
    valid_ranges: list[tuple[int, int]] = []
    for rng in ref.line_ranges:
        start, end = rng
        if start < 1 or end > file_line_count or start > end:
            problems.append(
                CitationProblem(
                    fr_id="",
                    ref_index=0,
                    path=ref.path,
                    line_ranges=[(start, end)],
                    problem=PROBLEM_RANGE_OUT_OF_BOUNDS,
                    detail=(
                        f"Range ({start}, {end}) is out of bounds: file "
                        f"{ref.path!r} has {file_line_count} lines; require "
                        "1 <= start <= end <= file_line_count."
                    ),
                )
            )
        else:
            valid_ranges.append((start, end))

    # Symbol presence — checked over the concatenation of all valid ranges.
    if ref.symbols and valid_ranges:
        cited_lines: list[str] = []
        for start, end in valid_ranges:
            cited_lines.extend(_slice_range(lines, start, end))
        searchable = "\n".join(_strip_comment_lines(cited_lines, ref.path))
        for symbol in ref.symbols:
            if symbol not in searchable:
                problems.append(
                    CitationProblem(
                        fr_id="",
                        ref_index=0,
                        path=ref.path,
                        line_ranges=list(ref.line_ranges),
                        problem=PROBLEM_SYMBOLS_MISSING,
                        detail=(
                            f"Symbol {symbol!r} not found in cited line ranges "
                            f"{list(ref.line_ranges)} of {ref.path!r}. Either fix "
                            "the line ranges so they include the symbol's "
                            "definition, or remove the symbol from this reference."
                        ),
                    )
                )

    return problems


def verify_spec_citations(repo_root: Path, spec: Spec) -> list[CitationProblem]:
    """Verify every CodeRef in every FunctionalRequirement. Returns all problems."""
    all_problems: list[CitationProblem] = []
    for fr in spec.functional_requirements:
        for idx, ref in enumerate(fr.code_references):
            for problem in verify_citation(repo_root, ref):
                all_problems.append(
                    CitationProblem(
                        fr_id=fr.id,
                        ref_index=idx,
                        path=problem.path,
                        line_ranges=problem.line_ranges,
                        problem=problem.problem,
                        detail=problem.detail,
                    )
                )
    return all_problems
