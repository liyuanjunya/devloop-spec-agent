"""Unit tests for the mechanical citation verifier."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devloop.spec_phase.schemas import (
    CodeRef,
    FunctionalRequirement,
    Spec,
    SpecMetadata,
)
from devloop.spec_phase.validators.citation_verifier import (
    PROBLEM_FILE_NOT_FOUND,
    PROBLEM_NO_RANGES_WITH_SYMBOLS,
    PROBLEM_RANGE_OUT_OF_BOUNDS,
    PROBLEM_SYMBOLS_MISSING,
    verify_citation,
    verify_spec_citations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PY_CONTENT = """\
class FooBar:
    def __init__(self) -> None:
        self.value = 42

    def duplicate_one(self, x: int) -> int:
        return x + x


def free_function() -> None:
    return None


CONSTANT_FOO = "bar"
"""


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    """Write content under tmp_path and return the absolute file path."""
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def _spec_with_refs(*frs: tuple[str, list[CodeRef]]) -> Spec:
    """Build a minimal Spec containing one FR per (fr_id, refs) pair."""
    return Spec(
        metadata=SpecMetadata(feature_id="test", title="test"),
        summary="test spec",
        functional_requirements=[
            FunctionalRequirement(
                id=fr_id,
                text=f"{fr_id} text",
                requirement_type="functional",
                code_references=refs,
            )
            for fr_id, refs in frs
        ],
    )


def _problems_by_kind(problems: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in problems:
        out[p.problem] = out.get(p.problem, 0) + 1
    return out


# ---------------------------------------------------------------------------
# verify_citation
# ---------------------------------------------------------------------------


def test_file_not_found_reports_single_problem(tmp_path: Path) -> None:
    ref = CodeRef(path="missing/file.py", symbols=["Foo"], line_ranges=[(1, 10)])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_FILE_NOT_FOUND
    assert problems[0].path == "missing/file.py"
    # Detail should mention the path so the rewriter has something actionable.
    assert "missing/file.py" in problems[0].detail


def test_range_out_of_bounds_start_zero(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ref = CodeRef(path="src/mod.py", symbols=[], line_ranges=[(0, 5)])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_RANGE_OUT_OF_BOUNDS
    assert problems[0].line_ranges == [(0, 5)]
    assert "0" in problems[0].detail


def test_range_out_of_bounds_end_exceeds_file(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    # file has 13 lines
    ref = CodeRef(path="src/mod.py", symbols=[], line_ranges=[(1, 9999)])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_RANGE_OUT_OF_BOUNDS
    assert "9999" in problems[0].detail
    # Detail should include the actual file length so the writer knows where to look.
    assert "13" in problems[0].detail


def test_range_out_of_bounds_start_greater_than_end(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ref = CodeRef(path="src/mod.py", symbols=[], line_ranges=[(5, 3)])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_RANGE_OUT_OF_BOUNDS


def test_symbols_missing_symbol_absent_from_all_ranges(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    # duplicate_one lives on line 5; cite lines 1-3 only
    ref = CodeRef(
        path="src/mod.py",
        symbols=["duplicate_one"],
        line_ranges=[(1, 3)],
    )
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_SYMBOLS_MISSING
    assert "duplicate_one" in problems[0].detail


def test_symbols_missing_symbol_present_only_in_comment(tmp_path: Path) -> None:
    # Python file: `# duplicate_one` comment shouldn't count as a definition.
    content = """\
class Helper:
    # duplicate_one is intentionally NOT defined here yet
    pass
"""
    _write(tmp_path, "src/comment_only.py", content)
    ref = CodeRef(
        path="src/comment_only.py",
        symbols=["duplicate_one"],
        line_ranges=[(1, 3)],
    )
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_SYMBOLS_MISSING


def test_symbols_missing_multiple_symbols_one_missing(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    # FooBar is at line 1; nonexistent is not in the file at all
    ref = CodeRef(
        path="src/mod.py",
        symbols=["FooBar", "nonexistent_symbol"],
        line_ranges=[(1, 5)],
    )
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_SYMBOLS_MISSING
    assert "nonexistent_symbol" in problems[0].detail


def test_no_line_ranges_with_symbols(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ref = CodeRef(path="src/mod.py", symbols=["FooBar"], line_ranges=[])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_NO_RANGES_WITH_SYMBOLS
    assert "FooBar" in problems[0].detail


def test_ok_file_and_range_and_symbol_all_present(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ref = CodeRef(
        path="src/mod.py",
        symbols=["FooBar", "duplicate_one"],
        line_ranges=[(1, 7)],
    )
    assert verify_citation(tmp_path, ref) == []


def test_ok_empty_symbols_empty_ranges_is_path_only(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ref = CodeRef(path="src/mod.py", symbols=[], line_ranges=[])
    assert verify_citation(tmp_path, ref) == []


def test_ok_multiple_ranges_symbol_in_second_range(tmp_path: Path) -> None:
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    # CONSTANT_FOO is on line 13. Cite lines 1-2 AND 12-13.
    ref = CodeRef(
        path="src/mod.py",
        symbols=["CONSTANT_FOO"],
        line_ranges=[(1, 2), (12, 13)],
    )
    assert verify_citation(tmp_path, ref) == []


def test_multiple_problems_reported_independently(tmp_path: Path) -> None:
    """Range out of bounds + valid-range-without-symbol both surface."""
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ref = CodeRef(
        path="src/mod.py",
        symbols=["nonexistent"],
        line_ranges=[(0, 5), (1, 3)],  # first range bad; second valid but no symbol
    )
    problems = verify_citation(tmp_path, ref)
    counts = _problems_by_kind(problems)
    assert counts.get(PROBLEM_RANGE_OUT_OF_BOUNDS) == 1
    assert counts.get(PROBLEM_SYMBOLS_MISSING) == 1


def test_non_python_files_do_not_strip_comments(tmp_path: Path) -> None:
    """Outside Python, every line is searched verbatim including `#` lines."""
    js = """\
// duplicate_one is referenced here
function helper() { return 1; }
"""
    _write(tmp_path, "src/file.js", js)
    ref = CodeRef(
        path="src/file.js",
        symbols=["duplicate_one"],
        line_ranges=[(1, 2)],
    )
    # `duplicate_one` appears only in a JS comment, but we don't strip
    # JS comments — so the substring match succeeds and verification passes.
    assert verify_citation(tmp_path, ref) == []


def test_python_partial_comment_lines_are_kept(tmp_path: Path) -> None:
    """Inline `# ...` comments on a code line should NOT be stripped."""
    content = """\
class Adder:
    value = 0  # holds running total

    def add(self, x: int) -> int:
        self.value += x  # mutate value
        return self.value
"""
    _write(tmp_path, "src/partial.py", content)
    # `value` appears on a code line with a trailing comment — must match.
    ref = CodeRef(
        path="src/partial.py",
        symbols=["value"],
        line_ranges=[(1, 2)],
    )
    assert verify_citation(tmp_path, ref) == []


def test_path_outside_repo_root_treated_as_invalid(tmp_path: Path) -> None:
    """A path that escapes the repo root MUST be reported as invalid_path
    (not silently treated as missing). This enforces the security boundary."""
    from devloop.spec_phase.validators.citation_verifier import (
        PROBLEM_INVALID_PATH,
    )

    ref = CodeRef(path="../escapes/out.py", symbols=[], line_ranges=[])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_INVALID_PATH


# ---------------------------------------------------------------------------
# verify_spec_citations
# ---------------------------------------------------------------------------


def test_verify_spec_citations_three_frs_one_bad(tmp_path: Path) -> None:
    """End-to-end: a spec with 3 FRs (2 ok, 1 bad) reports just the bad one."""
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    _write(tmp_path, "src/other.py", "class Other:\n    pass\n")

    ok1 = CodeRef(path="src/mod.py", symbols=["FooBar"], line_ranges=[(1, 5)])
    ok2 = CodeRef(path="src/other.py", symbols=["Other"], line_ranges=[(1, 2)])
    bad = CodeRef(
        path="src/mod.py",
        symbols=["duplicate_one"],
        line_ranges=[(1, 2)],  # symbol lives on line 5, not in [1,2]
    )

    spec = _spec_with_refs(
        ("FR-001", [ok1]),
        ("FR-002", [bad]),
        ("FR-003", [ok2]),
    )

    problems = verify_spec_citations(tmp_path, spec)
    assert len(problems) == 1
    assert problems[0].fr_id == "FR-002"
    assert problems[0].ref_index == 0
    assert problems[0].problem == PROBLEM_SYMBOLS_MISSING


def test_verify_spec_citations_attaches_correct_ref_index(tmp_path: Path) -> None:
    """When multiple refs in the same FR have problems, ref_index matches the position."""
    _write(tmp_path, "src/mod.py", PY_CONTENT)
    ok = CodeRef(path="src/mod.py", symbols=["FooBar"], line_ranges=[(1, 5)])
    bad = CodeRef(path="src/missing.py", symbols=["Anything"], line_ranges=[(1, 1)])
    spec = _spec_with_refs(("FR-007", [ok, bad, ok]))
    problems = verify_spec_citations(tmp_path, spec)
    assert len(problems) == 1
    assert problems[0].fr_id == "FR-007"
    assert problems[0].ref_index == 1
    assert problems[0].problem == PROBLEM_FILE_NOT_FOUND


def test_verify_spec_citations_empty_spec_returns_empty_list(tmp_path: Path) -> None:
    spec = Spec(metadata=SpecMetadata(feature_id="t", title="t"), summary="t")
    assert verify_spec_citations(tmp_path, spec) == []


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
