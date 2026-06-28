"""Adversarial boundary tests for the mechanical citation verifier (A5).

This file probes corner cases the writer/orchestrator stack will eventually
hit in production — symbols hiding in imports, docstrings, or inline
comments; empty / binary / very-large files; symlinks; path traversal —
and *documents the actual behavior* of
:func:`devloop.spec_phase.validators.citation_verifier.verify_citation`
under each scenario.

Per T-defense-fires-A5: **we do not fix bugs found here**. Tests assert
the current observable behavior. When the verifier silently accepts a
citation that should be rejected (e.g. a symbol that only appears in an
import line, or a path with ``..`` that escapes the repo root), the test
records the limitation in the assertion message via a ``LIMITATION:``
prefix and the analysis block at the bottom of this docstring.

Limitations observed (each cross-referenced from the relevant test):

* **L1** — substring symbol matching has no syntactic awareness:
  ``def foo`` vs ``class foo:`` are indistinguishable, and a symbol that
  only appears inside ``from x import Foo`` is treated as defined.
  See ``test_symbol_only_in_import_line_passes`` and
  ``test_class_vs_def_keyword_indistinguishable``.
* **L2** — substring matching also accepts symbols that appear only in
  docstrings. See ``test_symbol_only_in_docstring_passes``.
* **L3** — inline ``# comment`` text after code is NOT stripped, so
  symbols hidden in trailing comments are treated as definitions. See
  ``test_symbol_only_in_inline_comment_passes``.
* **L4** — symlinks are silently followed (``Path.is_file()`` returns
  True for a symlink to a real file). On Windows the test is skipped
  when the runtime lacks Developer Mode / admin and can't create
  symlinks. See ``test_symlink_is_silently_followed``.
* **L5** — binary files do NOT crash. ``read_text(errors="replace")``
  decodes them into garbled text; the verifier proceeds as if the file
  were text. See ``test_binary_file_decoded_with_replacement_chars``.
* **L6** — paths containing ``..`` are NOT rejected; the verifier
  resolves them with ``repo_root / rel_path`` and reads whatever the
  filesystem returns. Inside the repo this is harmless; outside, it is
  a confused-deputy risk. See ``test_path_traversal_escapes_repo_root``.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from devloop.spec_phase.schemas import CodeRef
from devloop.spec_phase.validators.citation_verifier import (
    PROBLEM_RANGE_OUT_OF_BOUNDS,
    PROBLEM_SYMBOLS_MISSING,
    verify_citation,
)


def _write(tmp_path: Path, rel: str, content: str, *, encoding: str = "utf-8") -> Path:
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding=encoding)
    return full


def _write_bytes(tmp_path: Path, rel: str, data: bytes) -> Path:
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full


# ---------------------------------------------------------------------------
# 1. Symbol-like-but-different (def vs class). [L1]
# ---------------------------------------------------------------------------


def test_class_vs_def_keyword_indistinguishable(tmp_path: Path) -> None:
    """``def foo`` vs ``class foo:`` — both contain the substring ``foo`` so
    the verifier accepts either. It is a substring-match validator, not an
    AST validator, and does not distinguish "function defined here" from
    "class defined here" from "name referenced here".

    LIMITATION L1: a writer that cites ``def foo`` but the file actually
    has ``class foo:`` will pass. The verifier cannot catch this.
    """
    content = "class foo:\n    pass\n"
    _write(tmp_path, "src/m.py", content)
    ref = CodeRef(path="src/m.py", symbols=["foo"], line_ranges=[(1, 2)])
    assert verify_citation(tmp_path, ref) == [], (
        "LIMITATION L1: substring match accepts class-vs-def confusion"
    )


# ---------------------------------------------------------------------------
# 2. Symbol present only in an import line. [L1]
# ---------------------------------------------------------------------------


def test_symbol_only_in_import_line_passes(tmp_path: Path) -> None:
    """Cite ``Foo`` but the cited range contains only ``from m import Foo``,
    not the actual class/function definition.

    LIMITATION L1: ``import Foo`` lines contain the substring ``Foo`` so the
    verifier treats this as a valid definition. The writer can satisfy A5
    by pointing at any line that mentions the symbol — including imports.
    """
    content = "from m import Foo\n"
    _write(tmp_path, "src/m.py", content)
    ref = CodeRef(path="src/m.py", symbols=["Foo"], line_ranges=[(1, 1)])
    assert verify_citation(tmp_path, ref) == [], (
        "LIMITATION L1: substring match treats import statements as definitions"
    )


# ---------------------------------------------------------------------------
# 3. Symbol present only inside a docstring. [L2]
# ---------------------------------------------------------------------------


def test_symbol_only_in_docstring_passes(tmp_path: Path) -> None:
    """Cite ``Foo`` but the cited range only mentions ``Foo`` inside a
    triple-quoted docstring.

    LIMITATION L2: the verifier does not parse Python AST so docstring
    text is searched the same as code text. A writer can satisfy A5 by
    citing a range that *mentions* the symbol in prose.
    """
    content = '"""docstring mentioning Foo"""\n'
    _write(tmp_path, "src/m.py", content)
    ref = CodeRef(path="src/m.py", symbols=["Foo"], line_ranges=[(1, 1)])
    assert verify_citation(tmp_path, ref) == [], (
        "LIMITATION L2: docstring mentions count as definitions"
    )


# ---------------------------------------------------------------------------
# 4. Symbol present only in an inline ``# comment``. [L3]
# ---------------------------------------------------------------------------


def test_symbol_only_in_inline_comment_passes(tmp_path: Path) -> None:
    """The Python-comment stripper only drops lines whose **first**
    non-whitespace char is ``#``. An inline trailing comment after code is
    preserved verbatim, so symbols hidden in trailing comments match.

    LIMITATION L3: ``def real_thing():  # alias for Foo`` would let a
    writer satisfy a citation for ``Foo`` even though ``Foo`` is only a
    word in a comment, never a real definition.
    """
    content = "def real_thing():  # alias for Foo\n    return 1\n"
    _write(tmp_path, "src/m.py", content)
    ref = CodeRef(path="src/m.py", symbols=["Foo"], line_ranges=[(1, 2)])
    assert verify_citation(tmp_path, ref) == [], (
        "LIMITATION L3: inline `# comment` text is NOT stripped"
    )

    # Contrast: a FULL-line comment IS stripped, so the same symbol in a
    # ``# Foo bar`` line on its own does NOT match. This confirms the
    # asymmetric behaviour we're documenting above.
    full_comment = "# Foo lives somewhere else\npass\n"
    _write(tmp_path, "src/m2.py", full_comment)
    ref2 = CodeRef(path="src/m2.py", symbols=["Foo"], line_ranges=[(1, 2)])
    problems = verify_citation(tmp_path, ref2)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_SYMBOLS_MISSING, (
        "regression: full-line `#` comments should still be stripped"
    )


# ---------------------------------------------------------------------------
# 5. Empty file — range_out_of_bounds. [behaves correctly]
# ---------------------------------------------------------------------------


def test_empty_file_zero_lines_range_one_one_is_out_of_bounds(tmp_path: Path) -> None:
    """Empty file: 0 lines. ``range=[1,1]`` requires ``end <= 0`` to be
    in-bounds, which fails → ``range_out_of_bounds``. This is the *expected*
    behavior; the test pins it so a future refactor that quietly accepts
    [1,1] on empty files (e.g. by clamping) fails loudly.
    """
    _write(tmp_path, "src/empty.py", "")
    ref = CodeRef(path="src/empty.py", symbols=[], line_ranges=[(1, 1)])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_RANGE_OUT_OF_BOUNDS
    # Detail should communicate the actual file length (0 lines) so the
    # rewriter knows the file is empty rather than guess.
    assert "0 lines" in problems[0].detail, problems[0].detail


# ---------------------------------------------------------------------------
# 6. Symlink to a real file is silently followed. [L4]
# ---------------------------------------------------------------------------


def test_symlink_is_silently_followed(tmp_path: Path) -> None:
    """A citation to a symlink that points at a real file is accepted; the
    verifier follows the link via ``Path.is_file()`` and reads the target.

    LIMITATION L4: there is no symlink-aware check, so a writer (or
    upstream actor) can hide a target behind a symlink. On a hardened
    repo this is a confused-deputy concern.

    On Windows the test skips when the runtime can't create symlinks
    (Developer Mode disabled / no admin), since that's an OS limitation,
    not a verifier limitation.
    """
    target = _write(tmp_path, "real/target.py", "class Real:\n    pass\n")
    link = tmp_path / "link.py"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink creation not available on this runtime")

    # Sanity: the link must actually behave like a file to the OS, otherwise
    # the assertion below isn't testing what we think it's testing.
    assert link.is_file(), "symlink should be a file on this runtime"

    ref = CodeRef(path="link.py", symbols=["Real"], line_ranges=[(1, 2)])
    problems = verify_citation(tmp_path, ref)
    assert problems == [], (
        "LIMITATION L4: symlinks are silently followed with no audit trail"
    )


# ---------------------------------------------------------------------------
# 7. Binary file — UTF-8 errors="replace" prevents crash. [L5]
# ---------------------------------------------------------------------------


def test_binary_file_decoded_with_replacement_chars(tmp_path: Path) -> None:
    """A ``.png``-flavoured citation does not crash the verifier. The
    underlying ``read_text(errors="replace")`` substitutes U+FFFD for
    invalid byte sequences, so the verifier sees garbled text and proceeds
    as if the file were source code.

    LIMITATION L5: the verifier has no MIME / extension guard. Symbol
    matching against the resulting garbled text is essentially undefined
    behaviour, but it is *defined to not crash*. We pin both halves: the
    out-of-bounds branch must still trigger for clearly bad ranges, AND
    no exception propagates for a binary read of a present symbol.
    """
    # 1KB of pseudo-PNG: magic bytes + filler zeros + IEND-ish tail.
    png = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 1024) + b"IEND"
    _write_bytes(tmp_path, "art/blob.png", png)

    # Citation with a clearly bad range — must still fire range_out_of_bounds
    # without raising on the underlying binary read.
    huge_range = CodeRef(
        path="art/blob.png", symbols=[], line_ranges=[(1, 999999)]
    )
    problems = verify_citation(tmp_path, huge_range)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_RANGE_OUT_OF_BOUNDS

    # Citation for a present (raw) byte sequence — IEND is a real ASCII
    # marker so it survives the replace-decode and the symbol is "found".
    # The point of this assertion is to prove the verifier doesn't crash on
    # binary input, not to endorse citing binaries.
    ok_ref = CodeRef(
        path="art/blob.png", symbols=["IEND"], line_ranges=[(1, 1)]
    )
    no_crash = verify_citation(tmp_path, ok_ref)
    # We don't assert empty — the binary may or may not collapse to one
    # line after decode — only that the call returned without raising.
    assert isinstance(no_crash, list), (
        "LIMITATION L5: binary read should not raise; returned non-list"
    )


# ---------------------------------------------------------------------------
# 8. Very large file (≈10MB) — should complete within a reasonable time.
# ---------------------------------------------------------------------------


def test_very_large_file_handled_within_reasonable_time(tmp_path: Path) -> None:
    """A 10MB file (~100K lines) must verify in well under any sane CI
    budget. The verifier reads the file fully, so this also exercises
    the worst-case substring-match path over a large blob.

    A 5s ceiling is generous: on a developer laptop the actual time is
    typically < 500ms. A regression that makes the verifier O(n²) over
    the file would push it past the ceiling and fail loudly.
    """
    # ~10MB: each of 100,000 lines is "line {i}" plus newline. Inject the
    # target symbol on a single mid-file line so we test the full scan.
    n_lines = 100_000
    chunks = [f"line {i}\n" for i in range(n_lines)]
    chunks[n_lines // 2] = "needle_symbol_xyz\n"
    big = "".join(chunks)
    big_path = tmp_path / "big.py"
    big_path.write_text(big, encoding="utf-8")
    # Sanity: ~10MB total
    assert big_path.stat().st_size > 1_000_000

    ref = CodeRef(
        path="big.py",
        symbols=["needle_symbol_xyz"],
        line_ranges=[(1, n_lines)],
    )
    start = time.monotonic()
    problems = verify_citation(tmp_path, ref)
    elapsed = time.monotonic() - start
    assert problems == [], f"unexpected problems on large file: {problems!r}"
    assert elapsed < 5.0, (
        f"large-file verification took {elapsed:.2f}s, exceeds 5s budget; "
        "possible regression to O(n^2) symbol matching"
    )


# ---------------------------------------------------------------------------
# 9. Range covering the entire file — must verify cleanly.
# ---------------------------------------------------------------------------


def test_range_equal_to_whole_file_passes(tmp_path: Path) -> None:
    """Citing ``[1, file_length]`` is the most common pattern when the
    writer doesn't know the precise definition line. The verifier must
    accept it without an off-by-one error.

    We use a 100-line file with the cited symbol on a non-edge line so
    no off-by-one (start=1 vs 0, end=100 vs len+1) can hide as a false pass.
    """
    lines = [f"# filler {i}" for i in range(1, 101)]
    lines[49] = "class WidgetMaker:"  # line 50 (1-indexed)
    _write(tmp_path, "src/big_module.py", "\n".join(lines) + "\n")

    ref = CodeRef(
        path="src/big_module.py",
        symbols=["WidgetMaker"],
        line_ranges=[(1, 100)],
    )
    assert verify_citation(tmp_path, ref) == []

    # Off-by-one regression guard: cite end=101 (past EOF by 1) → must fail.
    ref_off = CodeRef(
        path="src/big_module.py",
        symbols=["WidgetMaker"],
        line_ranges=[(1, 101)],
    )
    problems = verify_citation(tmp_path, ref_off)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_RANGE_OUT_OF_BOUNDS


# ---------------------------------------------------------------------------
# 10. Path with ``..`` — escape attempt. [L6]
# ---------------------------------------------------------------------------


def test_path_traversal_escapes_repo_root(tmp_path: Path) -> None:
    """A citation whose ``path`` contains ``..`` resolves OUTSIDE the cited
    repo root. The verifier MUST reject this — even if the out-of-repo
    file exists.

    L6 FIXED (post-T-defense-fires-A5): the verifier now returns
    ``PROBLEM_INVALID_PATH`` when the resolved target escapes the repo.
    This protects against the confused-deputy / path-traversal class.
    """
    from devloop.spec_phase.validators.citation_verifier import (
        PROBLEM_INVALID_PATH,
    )

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    # Out-of-repo file with a real, matchable symbol.
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    (secret_dir / "leak.py").write_text(
        "class SecretClass:\n    api_key = 'hunter2'\n",
        encoding="utf-8",
    )

    # ../secret/leak.py resolves outside repo_root → must be rejected.
    ref = CodeRef(
        path="../secret/leak.py",
        symbols=["SecretClass"],
        line_ranges=[(1, 2)],
    )
    problems = verify_citation(repo_root, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_INVALID_PATH
    assert "escapes the repo root" in problems[0].detail


# ---------------------------------------------------------------------------
# 11. Bonus: path with ``..`` that does NOT escape but normalises inside
#     the repo still works. (Pinned so we don't accidentally over-block
#     when adding containment.)
# ---------------------------------------------------------------------------


def test_path_with_dotdot_that_stays_in_repo_works(tmp_path: Path) -> None:
    """``app/models/../models/user.py`` resolves back to ``app/models/user.py``
    and the verifier accepts it. The containment guard MUST be smart enough
    to allow this benign case (resolve first, then assert containment).
    """
    _write(tmp_path, "app/models/user.py", "class User:\n    pass\n")
    ref = CodeRef(
        path="app/models/../models/user.py",
        symbols=["User"],
        line_ranges=[(1, 2)],
    )
    assert verify_citation(tmp_path, ref) == []


# ---------------------------------------------------------------------------
# 12. Bonus: absolute paths — MUST be rejected as invalid path. The
#     post-T-defense-fires-A5 fix added explicit absolute-path rejection.
# ---------------------------------------------------------------------------


def test_absolute_path_rejected_as_invalid(tmp_path: Path) -> None:
    """Absolute paths bypass the repo-relative contract. They MUST be
    rejected with PROBLEM_INVALID_PATH regardless of whether the absolute
    target exists.
    """
    from devloop.spec_phase.validators.citation_verifier import (
        PROBLEM_INVALID_PATH,
    )

    if sys.platform == "win32":
        bad_abs = r"Z:\definitely\not\here\__missing__.py"
    else:
        bad_abs = "/__nonexistent__/__definitely_not_here__.py"

    ref = CodeRef(path=bad_abs, symbols=[], line_ranges=[(1, 1)])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_INVALID_PATH


def test_drive_letter_path_rejected_as_invalid(tmp_path: Path) -> None:
    """Windows-style drive-letter paths (``X:/...``) must be rejected even
    on POSIX (they look like absolute paths to the user and are still
    semantically not-repo-relative)."""
    from devloop.spec_phase.validators.citation_verifier import (
        PROBLEM_INVALID_PATH,
    )

    ref = CodeRef(path="C:/Windows/System32/cmd.exe", symbols=[], line_ranges=[])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_INVALID_PATH


def test_leading_slash_path_rejected(tmp_path: Path) -> None:
    """Even on POSIX where ``/foo`` is technically absolute, the leading
    separator should be rejected unambiguously."""
    from devloop.spec_phase.validators.citation_verifier import (
        PROBLEM_INVALID_PATH,
    )

    ref = CodeRef(path="/etc/passwd", symbols=[], line_ranges=[])
    problems = verify_citation(tmp_path, ref)
    assert len(problems) == 1
    assert problems[0].problem == PROBLEM_INVALID_PATH


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
