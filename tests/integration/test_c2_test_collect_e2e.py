"""End-to-end capability-boundary tests for C2 (test-grounded executability).

These tests exercise the full validator pipeline (extract refs → generate
stubs → pytest --collect-only → classify failures → produce
:class:`TestExecutabilityProblem`) against real spec objects and a real
pytest subprocess (one exception — see ``test_spec_with_unknown_fixture_fails``,
which can't depend on pytest --collect-only emitting fixture errors because
fixture resolution is a *setup-time* concern, not collection-time).

Each test answers one question:

1. Does the C2 defense let a clean spec through?
2. Does it catch a syntactically broken stub?
3. Does it catch a stub whose top-level import doesn't resolve?
4. Does it catch a stub whose fixture isn't defined?
5. Does it skip subprocess entirely when the spec has no test references
   (efficiency property)?
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from devloop.spec_phase.schemas import (
    AcceptanceScenario,
    FunctionalRequirement,
    Spec,
    SpecMetadata,
    SuccessCriterion,
    UserStory,
)
from devloop.spec_phase.validators.test_executability import (
    PROBLEM_COLLECT_ERROR,
    PROBLEM_FIXTURE_NOT_FOUND,
    PROBLEM_IMPORT_ERROR,
    verify_spec_test_executability,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    *,
    summary: str = "Demo spec for the C2 e2e suite.",
    user_stories: list[UserStory] | None = None,
    functional_requirements: list[FunctionalRequirement] | None = None,
    success_criteria: list[SuccessCriterion] | None = None,
) -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="c2-e2e", title="C2 e2e"),
        summary=summary,
        user_stories=user_stories or [],
        functional_requirements=functional_requirements or [],
        success_criteria=success_criteria or [],
    )


def _us_referencing(test_ref: str) -> UserStory:
    """Build a UserStory whose ``independent_test`` carries one test ref."""
    return UserStory(
        id="US-1",
        priority="P1",
        title="Story 1",
        description="A user story.",
        why_this_priority="core",
        independent_test=test_ref,
        acceptance=[AcceptanceScenario(given="g", when="w", then="t")],
    )


def _fr(fr_id: str, text: str) -> FunctionalRequirement:
    return FunctionalRequirement(
        id=fr_id,
        text=text,
        requirement_type="functional",
        related_user_stories=[],
        related_success_criteria=[],
        code_references=[],
    )


def _fake_completed(
    *, returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["pytest", "--collect-only"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# 1. Happy path — a clean reference produces zero problems.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_spec_with_collectible_test_passes(tmp_path: Path) -> None:
    """Spec references ``tests/integration/test_foo.py::test_bar`` and that
    test exists + collects cleanly in a tmpdir scratch. Validator returns []."""
    spec = _spec(
        user_stories=[
            _us_referencing("tests/integration/test_foo.py::test_bar")
        ],
    )
    scratch = tmp_path / "scratch"

    problems = verify_spec_test_executability(
        spec,
        target_repo=tmp_path,
        scratch_dir=scratch,
        timeout_s=60,
    )

    assert problems == [], f"clean spec should produce no problems, got: {problems}"
    # The validator generated a stub at the cited path so pytest had something
    # to collect — confirms the happy-path stub-generation was exercised.
    stub_path = scratch / "tests" / "integration" / "test_foo.py"
    assert stub_path.is_file(), f"expected generated stub at {stub_path}"
    assert "def test_bar()" in stub_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. Syntactically broken stub — SyntaxError surfaces as collect_error /
#    import_error.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_spec_with_syntactically_broken_stub_fails(tmp_path: Path) -> None:
    """Pre-placed file with ``def test_x(:`` cannot be collected — validator
    must surface this as a problem keyed to the spec-named test."""
    spec = _spec(
        functional_requirements=[
            _fr(
                "FR-001",
                "Verified by tests/unit/test_syntaxbad.py::test_x.",
            )
        ],
    )
    scratch = tmp_path / "scratch"
    broken = scratch / "tests" / "unit" / "test_syntaxbad.py"
    broken.parent.mkdir(parents=True, exist_ok=True)
    # The unclosed paren after ``test_x`` makes the file fail at parse time,
    # so pytest's collector raises a SyntaxError before discovering any tests.
    broken.write_text(
        textwrap.dedent(
            """
            def test_x(:
                pass
            """
        ).strip(),
        encoding="utf-8",
    )

    problems = verify_spec_test_executability(
        spec,
        target_repo=tmp_path,
        scratch_dir=scratch,
        timeout_s=60,
    )

    assert problems, "expected at least one problem for the syntactically broken stub"
    flagged = next(
        (p for p in problems if p.test_path == "tests/unit/test_syntaxbad.py"),
        None,
    )
    assert flagged is not None, (
        f"expected problem for tests/unit/test_syntaxbad.py, got: {problems}"
    )
    # Syntax errors are classified as import_error (per _classify_error) when
    # pytest mentions SyntaxError/IndentationError in output, otherwise the
    # generic collect_error fallback fires. Both are valid evidence that the
    # defense detected the broken stub.
    assert flagged.problem in {PROBLEM_IMPORT_ERROR, PROBLEM_COLLECT_ERROR}
    assert flagged.test_name == "test_x"
    # The detail must include enough context for the rewriter to act on it —
    # at minimum the path and the kind.
    assert "tests/unit/test_syntaxbad.py" in flagged.detail


# ---------------------------------------------------------------------------
# 3. Missing import — top-level ImportError must classify as import_error.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_spec_with_missing_import_fails(tmp_path: Path) -> None:
    """Pre-placed stub that imports a nonexistent module must be flagged as
    ``import_error`` so the rewriter can fix the dependency reference."""
    spec = _spec(
        functional_requirements=[
            _fr(
                "FR-IMP",
                "Coverage: tests/unit/test_missing_import.py::test_alpha.",
            )
        ],
    )
    scratch = tmp_path / "scratch"
    stub = scratch / "tests" / "unit" / "test_missing_import.py"
    stub.parent.mkdir(parents=True, exist_ok=True)
    # `devloop_definitely_not_installed_xyz_42` is guaranteed not to resolve,
    # so pytest's collection import raises ModuleNotFoundError → ImportError.
    stub.write_text(
        textwrap.dedent(
            """
            import devloop_definitely_not_installed_xyz_42  # noqa: F401


            def test_alpha() -> None:
                pass
            """
        ).strip(),
        encoding="utf-8",
    )

    problems = verify_spec_test_executability(
        spec,
        target_repo=tmp_path,
        scratch_dir=scratch,
        timeout_s=60,
    )

    assert problems, "expected at least one problem for the missing-import stub"
    flagged = next(
        (
            p
            for p in problems
            if p.test_path == "tests/unit/test_missing_import.py"
        ),
        None,
    )
    assert flagged is not None, (
        f"expected problem for tests/unit/test_missing_import.py, got: {problems}"
    )
    assert flagged.problem == PROBLEM_IMPORT_ERROR, (
        f"expected import_error classification, got: {flagged.problem} "
        f"(detail={flagged.detail!r})"
    )
    # The pytest output snippet in detail should mention the missing module
    # so the rewriter knows exactly what to fix.
    assert "devloop_definitely_not_installed_xyz_42" in flagged.detail


# ---------------------------------------------------------------------------
# 4. Unknown fixture — classifier must pick fixture_not_found from pytest output.
#
# Note: pytest --collect-only does NOT actually resolve fixtures (verified
# empirically on pytest 9.0.3 — see commit history). Fixture resolution is a
# *setup-time* concern, so a stub using a nonexistent fixture still collects
# successfully under --collect-only. To exercise the C2 defense's
# classification path end-to-end without depending on pytest run-time
# semantics, we patch the subprocess to return the realistic pytest output
# that would surface if the test were actually invoked, and verify the
# validator's classifier picks `fixture_not_found` from that output. The
# spec, ref extraction, stub generation, scratchpad I/O, and classifier
# remain real.
# ---------------------------------------------------------------------------


def test_spec_with_unknown_fixture_fails(tmp_path: Path) -> None:
    """Realistic pytest fixture-not-found output must classify as
    PROBLEM_FIXTURE_NOT_FOUND so the rewriter knows to declare the missing
    fixture (rather than guessing it's an import or syntax problem)."""
    spec = _spec(
        functional_requirements=[
            _fr(
                "FR-FX",
                "Covered by tests/unit/test_needs_fixture.py::test_y.",
            )
        ],
    )
    scratch = tmp_path / "scratch"
    stub = scratch / "tests" / "unit" / "test_needs_fixture.py"
    stub.parent.mkdir(parents=True, exist_ok=True)
    # Real, syntactically valid stub that subscribes to an undefined fixture.
    # This file will collect cleanly under --collect-only; the simulated
    # subprocess output below is what pytest emits when this test is actually
    # invoked, which is what the orchestrator would see in a downstream run.
    stub.write_text(
        textwrap.dedent(
            """
            def test_y(devloop_unknown_fixture):
                assert devloop_unknown_fixture is not None
            """
        ).strip(),
        encoding="utf-8",
    )

    realistic_stderr = (
        "ERRORS\n"
        "_____ ERROR at setup of test_y _____\n"
        "file C:\\repo\\tests\\unit\\test_needs_fixture.py, line 1\n"
        "  def test_y(devloop_unknown_fixture):\n"
        "E       fixture 'devloop_unknown_fixture' not found\n"
        "available fixtures: cache, capsys, monkeypatch, ...\n"
    )

    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only",
        return_value=_fake_completed(returncode=2, stderr=realistic_stderr),
    ):
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=scratch,
            timeout_s=60,
        )

    assert problems, "expected a problem for the unknown-fixture stub"
    flagged = next(
        (
            p
            for p in problems
            if p.test_path == "tests/unit/test_needs_fixture.py"
        ),
        None,
    )
    assert flagged is not None, (
        f"expected problem for tests/unit/test_needs_fixture.py, got: {problems}"
    )
    assert flagged.problem == PROBLEM_FIXTURE_NOT_FOUND, (
        f"expected fixture_not_found, got: {flagged.problem} "
        f"(detail={flagged.detail!r})"
    )
    # The missing fixture name must be propagated to the rewriter context.
    assert "devloop_unknown_fixture" in flagged.detail


# ---------------------------------------------------------------------------
# 5. Efficiency property — no refs ⇒ no subprocess, no scratch dir touched.
# ---------------------------------------------------------------------------


def test_no_test_references_no_problems_no_subprocess(tmp_path: Path) -> None:
    """A spec that mentions no ``tests/`` paths must short-circuit before
    spawning pytest. Spawning pytest on every spec — even ones with no test
    refs — would be a serious efficiency regression for the orchestrator."""
    spec = _spec(
        summary="Refactor the price calculator in app/services/pricing.py.",
        functional_requirements=[
            _fr(
                "FR-001",
                "The calculator must continue to support discounts as in "
                "app/services/discounts.py.",
            ),
            _fr(
                "FR-002",
                "Performance must not regress more than 5% on the existing "
                "benchmark.",
            ),
        ],
    )
    scratch = tmp_path / "scratch"

    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only"
    ) as run_mock:
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=scratch,
            timeout_s=60,
        )

    assert problems == []
    run_mock.assert_not_called(), (
        "verify_spec_test_executability MUST short-circuit before spawning "
        "pytest when the spec contains no test references — otherwise every "
        "review iteration pays a pytest startup cost for nothing."
    )
    # Scratch dir was not even created — the `_scratch_dir_context` body
    # never executed because of the early `if not refs: return []`.
    assert not scratch.exists(), (
        "no refs ⇒ no scratch dir creation; got an unexpected scratch dir at "
        f"{scratch}"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
