"""Test-grounded executability validator (DevLoop Sprint C — C2).

The LLM executability reviewer judges whether a spec is "executable" by
*reading* the spec, which is a soft signal at best. This module produces
mechanical evidence by extracting every ``tests/...`` reference mentioned
in the spec (typically in ``UserStory.independent_test``,
``FunctionalRequirement.text``, or ``SuccessCriterion.text``), generating
minimal pytest stubs for them, and running ``pytest --collect-only`` to
verify the named tests would actually be discoverable.

Each (test_path, test_name) reference that pytest can't collect becomes a
:class:`TestExecutabilityProblem`. The orchestrator wraps each one in a
HIGH ``executability`` :class:`ReviewIssue` and feeds it into the next
review iteration so the rewriter can fix the reference — exactly mirroring
the A5 (citation_verifier) and B3 (trace_matrix) integrations.

Problem kinds:

* ``no_such_file`` — the path extracted from the spec didn't correspond to
  any file we could verify (e.g. extraction parsed something that wasn't a
  real path).
* ``collect_error`` — pytest exited non-zero (or 5 = "no tests collected")
  for reasons not classified more specifically below.
* ``fixture_not_found`` — pytest's collection output mentions a missing
  fixture for the cited test.
* ``import_error`` — pytest's collection output mentions an ImportError /
  syntax error for the cited test module.

Notes
-----
We invoke pytest via ``subprocess`` rather than the in-process API to keep
the validator side-effect-free relative to the orchestrator's own pytest
session (if any). A short timeout guards against runaway collection.

The ``target_repo`` parameter is currently reserved for future use (e.g.
fast-path validation against tests that already exist in the repo). The v1
implementation always validates via generated stubs in ``scratch_dir``.
"""

from __future__ import annotations

import contextlib
import keyword
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from devloop.spec_phase.schemas import Spec

PROBLEM_NO_SUCH_FILE = "no_such_file"
PROBLEM_COLLECT_ERROR = "collect_error"
PROBLEM_FIXTURE_NOT_FOUND = "fixture_not_found"
PROBLEM_IMPORT_ERROR = "import_error"

VALID_PROBLEM_KINDS = frozenset(
    {
        PROBLEM_NO_SUCH_FILE,
        PROBLEM_COLLECT_ERROR,
        PROBLEM_FIXTURE_NOT_FOUND,
        PROBLEM_IMPORT_ERROR,
    }
)

DEFAULT_TIMEOUT_S = 30

# Anchored on ``tests/`` so we only pick up first-class test references and
# not arbitrary file paths mentioned in the spec. Accepts forward or back
# slashes for cross-platform robustness, an optional ``::function_name``
# suffix (pytest node id), and is case-sensitive (test_*.py convention).
_TEST_REF_RE = re.compile(
    r"\btests[\\/][\w\\/\-.]*?test_[\w\-.]+\.py(?:::([A-Za-z_]\w*))?",
)


@dataclass(slots=True, frozen=True)
class TestExecutabilityProblem:
    """One test the spec named but pytest couldn't collect.

    Attributes:
        test_path: forward-slash-normalized path as written in the spec
            (e.g. ``tests/integration_tests/test_foo.py``).
        test_name: the function name after ``::``, or ``None`` if the spec
            referenced the file without naming a specific test.
        problem: one of :data:`VALID_PROBLEM_KINDS`.
        detail: human-readable description for the rewriter, including the
            relevant pytest output where applicable.
    """

    test_path: str
    test_name: str | None
    problem: str
    detail: str

    # The class name starts with ``Test`` (matches the validator's purpose)
    # which would otherwise make pytest try to collect it as a test case
    # whenever the module is imported by a test file.
    __test__ = False


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _iter_spec_text_fields(spec: Spec) -> Iterable[str]:
    """Yield every string-typed Spec field that might mention a test path."""
    yield spec.summary
    for us in spec.user_stories:
        yield us.title
        yield us.description
        yield us.why_this_priority
        yield us.independent_test
        for acc in us.acceptance:
            yield acc.given
            yield acc.when
            yield acc.then
    for fr in spec.functional_requirements:
        yield fr.text
    for sc in spec.success_criteria:
        yield sc.text
        yield sc.metric
        yield sc.threshold
    for ent in spec.key_entities:
        yield ent.description
    for ec in spec.edge_cases:
        yield ec.description
        yield ec.handling
    yield from spec.assumptions
    yield from spec.out_of_scope
    for concern in spec.self_concerns:
        yield concern.concern
        yield concern.evidence_gap
        if concern.suggested_resolution:
            yield concern.suggested_resolution
    for bd in spec.needs_clarification:
        yield bd.title
        yield bd.conflict
        yield bd.recommended_default
        yield bd.if_rejected


def _normalize_path(path: str) -> str:
    """Forward-slash-normalize a path string, stripping trailing punctuation."""
    return path.replace("\\", "/").rstrip(".,;:)>]\"'")


def extract_test_references(spec: Spec) -> list[tuple[str, str | None]]:
    """Scan all string fields of ``spec`` for ``tests/.../*.py[::func]`` references.

    Returns a deduplicated list of ``(file_path, function_name_or_None)``
    tuples in first-seen order. File paths are normalized to forward
    slashes so downstream stub generation can apply consistent ``Path``
    construction regardless of how the writer typed them.
    """
    seen: set[tuple[str, str | None]] = set()
    out: list[tuple[str, str | None]] = []
    for text in _iter_spec_text_fields(spec):
        if not text:
            continue
        for match in _TEST_REF_RE.finditer(text):
            raw = match.group(0)
            func = match.group(1)
            # match.group(0) includes the optional ::function; isolate the file part.
            file_part = raw.split("::", 1)[0]
            path = _normalize_path(file_part)
            key = (path, func)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


# ---------------------------------------------------------------------------
# Stub generation
# ---------------------------------------------------------------------------


def _safe_identifier(name: str) -> str | None:
    """Return ``name`` if it's a valid (non-keyword) Python identifier, else None."""
    if not name or not name.isidentifier() or keyword.iskeyword(name):
        return None
    return name


def generate_stub_test_file(
    test_path: str, function_names: list[str], target_dir: Path
) -> Path:
    """Create a minimal pytest stub at ``<target_dir>/<test_path>``.

    The stub contains ``pass``-only bodies for each function in
    ``function_names`` (filtered to valid Python identifiers). When the
    function list is empty, a single ``test_stub_placeholder`` is emitted
    so pytest still has something to collect from the file.

    An empty ``conftest.py`` is dropped at the scratch root if not already
    present so pytest doesn't walk up to a real conftest from the
    surrounding project — keeping fixture resolution self-contained.

    Returns the absolute path of the file that was written.
    """
    norm = _normalize_path(test_path)
    rel = Path(*[seg for seg in norm.split("/") if seg])
    file_path = (target_dir / rel).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    root_conftest = target_dir / "conftest.py"
    if not root_conftest.exists():
        root_conftest.write_text("", encoding="utf-8")

    body_lines: list[str] = []
    safe_funcs = [n for n in (_safe_identifier(f) for f in function_names) if n]
    if not safe_funcs:
        safe_funcs = ["test_stub_placeholder"]
    for func in safe_funcs:
        body_lines.append(f"def {func}() -> None:")
        body_lines.append("    pass")
        body_lines.append("")

    header = [
        '"""Auto-generated test stub for executability check.',
        "",
        "Do not edit — regenerated each verify_spec_test_executability run.",
        '"""',
        "",
    ]
    file_path.write_text("\n".join(header + body_lines), encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# Pytest invocation + parsing
# ---------------------------------------------------------------------------


_NODE_ID_RE = re.compile(r"^([\w./\\\-]+\.py)::([\w\-:]+?)(?:\[[^\]]*\])?\s*$")


def _parse_collected_node_ids(stdout: str) -> set[tuple[str, str]]:
    """Parse ``pytest --collect-only -q`` stdout into a set of (path, leaf_func).

    Each node id of the form ``a/b/test_foo.py::Class::test_method`` is
    reduced to ``("a/b/test_foo.py", "test_method")``. Parametrize
    suffixes (``[param-id]``) are stripped. Paths are normalized to
    forward slashes so callers can compare against extracted references
    without worrying about platform separators.
    """
    collected: set[tuple[str, str]] = set()
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or "::" not in line:
            continue
        m = _NODE_ID_RE.match(line)
        if not m:
            continue
        path = m.group(1).replace("\\", "/")
        # The last ``::`` segment is the leaf function; intermediate segments
        # (e.g. test class names) are dropped because spec references rarely
        # spell the class out.
        leaf = m.group(2).split("::")[-1]
        collected.add((path, leaf))
    return collected


def _classify_error(combined_output: str, path: str) -> str:
    """Classify a pytest collection failure for ``path`` from its output text.

    Order matters: ``fixture_not_found`` is matched before generic
    ``import_error`` because pytest's "fixture '...' not found" messages
    are unambiguous, whereas ImportError can leak into other tracebacks.
    """
    lower = combined_output.lower()
    if "fixture" in lower and "not found" in lower:
        return PROBLEM_FIXTURE_NOT_FOUND
    if "importerror" in lower or "modulenotfounderror" in lower:
        return PROBLEM_IMPORT_ERROR
    if "syntaxerror" in lower or "indentationerror" in lower:
        return PROBLEM_IMPORT_ERROR
    # Pytest message for "doesn't exist": ``ERROR: file or directory not found``
    if "file or directory not found" in lower or "no such file" in lower:
        return PROBLEM_NO_SUCH_FILE
    return PROBLEM_COLLECT_ERROR


@contextlib.contextmanager
def _scratch_dir_context(scratch_dir: Path | None) -> Iterator[Path]:
    """Yield a usable scratch directory; clean up only if we created it."""
    if scratch_dir is None:
        td = tempfile.TemporaryDirectory(prefix="devloop_testexec_")
        try:
            yield Path(td.name)
        finally:
            td.cleanup()
    else:
        scratch_dir.mkdir(parents=True, exist_ok=True)
        yield scratch_dir


def _run_pytest_collect_only(
    scratch_dir: Path, timeout_s: int
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m pytest --collect-only`` on ``scratch_dir``."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(scratch_dir),
        "--collect-only",
        "-q",
        f"--rootdir={scratch_dir}",
        "-p",
        "no:cacheprovider",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        cwd=str(scratch_dir),
    )


def verify_spec_test_executability(
    spec: Spec,
    *,
    target_repo: Path,
    scratch_dir: Path | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> list[TestExecutabilityProblem]:
    """Extract test refs from ``spec``, generate stubs, and verify collection.

    For each ``tests/.../*.py[::func]`` mentioned anywhere in ``spec``,
    create a minimal pytest stub in ``scratch_dir`` (unless a file is
    already present at that path — useful for tests that pre-place a
    broken stub to verify failure detection). Then invoke
    ``python -m pytest --collect-only`` against ``scratch_dir`` and
    cross-check the collected node ids against the extracted references.

    Each reference pytest didn't collect becomes one
    :class:`TestExecutabilityProblem`. References without an explicit
    function name only require *some* test from the file to collect (the
    "file collects at all" check); references with a function name
    require ``path::func`` to appear in the collected set.

    Args:
        spec: the spec being validated.
        target_repo: the repository the spec applies to. Reserved for
            future use; the v1 implementation always validates via
            generated stubs in ``scratch_dir``.
        scratch_dir: if provided, stubs are written under this directory
            and it is **not** cleaned up after the call. If ``None``, a
            tempdir is created and removed.
        timeout_s: per-call ceiling on the ``pytest --collect-only``
            subprocess.

    Returns the (possibly empty) list of problems. An empty list means
    every test reference in the spec is collectable.
    """
    _ = target_repo  # Reserved; see module docstring.

    refs = extract_test_references(spec)
    if not refs:
        return []

    by_file: dict[str, list[str]] = {}
    for path, func in refs:
        funcs = by_file.setdefault(path, [])
        if func and func not in funcs:
            funcs.append(func)

    with _scratch_dir_context(scratch_dir) as work_dir:
        for path, funcs in by_file.items():
            rel = Path(*[seg for seg in path.split("/") if seg])
            target_file = work_dir / rel
            if not target_file.exists():
                generate_stub_test_file(path, funcs, work_dir)

        try:
            result = _run_pytest_collect_only(work_dir, timeout_s)
        except subprocess.TimeoutExpired:
            return [
                TestExecutabilityProblem(
                    test_path=p,
                    test_name=None,
                    problem=PROBLEM_COLLECT_ERROR,
                    detail=(
                        f"pytest --collect-only timed out after {timeout_s}s "
                        "while verifying spec test references."
                    ),
                )
                for p in sorted(by_file)
            ]
        except FileNotFoundError as exc:
            # ``python -m pytest`` missing from the runtime — degrade gracefully
            # so the orchestrator doesn't crash; surface as one problem per file.
            return [
                TestExecutabilityProblem(
                    test_path=p,
                    test_name=None,
                    problem=PROBLEM_COLLECT_ERROR,
                    detail=f"could not invoke pytest: {exc}",
                )
                for p in sorted(by_file)
            ]

        collected = _parse_collected_node_ids(result.stdout)
        collected_paths = {path for path, _ in collected}
        combined = (result.stdout or "") + "\n" + (result.stderr or "")

        problems: list[TestExecutabilityProblem] = []
        for path, func in refs:
            if func is None:
                # File-only reference: at least one test from this file
                # must appear in the collected set.
                if path in collected_paths:
                    continue
                kind = _classify_error(combined, path)
                problems.append(
                    TestExecutabilityProblem(
                        test_path=path,
                        test_name=None,
                        problem=kind,
                        detail=_format_failure_detail(
                            path, None, result, kind
                        ),
                    )
                )
            else:
                if (path, func) in collected:
                    continue
                # Function-specific miss — distinguish "file failed to load
                # at all" from "file loaded but this function isn't there"
                # so the rewriter knows what to fix.
                if path in collected_paths:
                    kind = PROBLEM_COLLECT_ERROR
                    detail = (
                        f"pytest collected {path} but the spec-named test "
                        f"function {func!r} was not present. Update the spec "
                        "to use the actual function name or add the missing "
                        "test to the file."
                    )
                else:
                    kind = _classify_error(combined, path)
                    detail = _format_failure_detail(path, func, result, kind)
                problems.append(
                    TestExecutabilityProblem(
                        test_path=path,
                        test_name=func,
                        problem=kind,
                        detail=detail,
                    )
                )

        return problems


def _format_failure_detail(
    path: str,
    func: str | None,
    result: subprocess.CompletedProcess[str],
    kind: str,
) -> str:
    """Build a human-readable failure detail with a short pytest snippet."""
    head = f"pytest --collect-only did not collect {path}"
    if func:
        head += f"::{func}"
    head += f" (kind={kind}, exit={result.returncode})."
    snippet_source = result.stderr.strip() or result.stdout.strip()
    if snippet_source:
        # Keep the detail compact so it fits comfortably in a ReviewIssue.
        snippet = "\n".join(snippet_source.splitlines()[-12:])
        return f"{head}\n--- pytest output (tail) ---\n{snippet}"
    return head
