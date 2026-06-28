"""Tests for the test-grounded executability validator (DevLoop Sprint C — C2)."""

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
    PROBLEM_NO_SUCH_FILE,
    TestExecutabilityProblem,
    _classify_error,
    _parse_collected_node_ids,
    extract_test_references,
    generate_stub_test_file,
    verify_spec_test_executability,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    *,
    summary: str = "demo spec",
    user_stories: list[UserStory] | None = None,
    functional_requirements: list[FunctionalRequirement] | None = None,
    success_criteria: list[SuccessCriterion] | None = None,
) -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="demo", title="Demo"),
        summary=summary,
        user_stories=user_stories or [],
        functional_requirements=functional_requirements or [],
        success_criteria=success_criteria or [],
    )


def _us(
    us_id: str,
    independent_test: str = "",
    description: str = "story description",
) -> UserStory:
    return UserStory(
        id=us_id,
        priority="P1",
        title=f"Story {us_id}",
        description=description,
        why_this_priority="core",
        independent_test=independent_test,
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


def _sc(sc_id: str, text: str = "fast") -> SuccessCriterion:
    return SuccessCriterion(
        id=sc_id,
        text=text,
        metric="latency",
        threshold="< 500ms",
    )


# ---------------------------------------------------------------------------
# extract_test_references
# ---------------------------------------------------------------------------


def test_extract_test_references_from_independent_test_field() -> None:
    spec = _spec(
        user_stories=[
            _us(
                "US-1",
                independent_test=(
                    "Run `tests/integration_tests/test_recipe_list_query_count.py"
                    "::test_recipe_list_query_count_constant`."
                ),
            )
        ]
    )
    refs = extract_test_references(spec)
    assert (
        "tests/integration_tests/test_recipe_list_query_count.py",
        "test_recipe_list_query_count_constant",
    ) in refs


def test_extract_test_references_from_fr_text() -> None:
    spec = _spec(
        functional_requirements=[
            _fr(
                "FR-001",
                "Implementation must be covered by tests/unit/test_dispatcher.py::test_dispatch_basic.",
            )
        ]
    )
    refs = extract_test_references(spec)
    assert ("tests/unit/test_dispatcher.py", "test_dispatch_basic") in refs


def test_extract_test_references_from_success_criterion() -> None:
    spec = _spec(
        success_criteria=[
            _sc(
                "SC-001",
                text="Covered by tests/e2e/test_smoke.py::test_smoke_runs",
            )
        ]
    )
    refs = extract_test_references(spec)
    assert ("tests/e2e/test_smoke.py", "test_smoke_runs") in refs


def test_extract_test_references_dedupes() -> None:
    """The same (path, func) pair mentioned in two places yields one entry."""
    spec = _spec(
        summary="see tests/test_x.py::test_a",
        user_stories=[_us("US-1", independent_test="tests/test_x.py::test_a")],
        functional_requirements=[_fr("FR-001", "see tests/test_x.py::test_a too")],
    )
    refs = extract_test_references(spec)
    assert refs.count(("tests/test_x.py", "test_a")) == 1


def test_extract_test_references_with_function_name() -> None:
    spec = _spec(summary="tests/unit/test_foo.py::test_bar")
    refs = extract_test_references(spec)
    assert refs == [("tests/unit/test_foo.py", "test_bar")]


def test_extract_test_references_without_function_name() -> None:
    spec = _spec(summary="see tests/unit/test_foo.py for details")
    refs = extract_test_references(spec)
    assert refs == [("tests/unit/test_foo.py", None)]


def test_extract_test_references_normalizes_backslashes() -> None:
    """Windows-style paths in the spec should be normalized to forward slashes."""
    spec = _spec(summary=r"tests\unit\test_foo.py::test_bar")
    refs = extract_test_references(spec)
    assert refs == [("tests/unit/test_foo.py", "test_bar")]


def test_extract_test_references_empty_spec_returns_empty_list() -> None:
    spec = _spec()
    assert extract_test_references(spec) == []


def test_extract_test_references_ignores_non_test_paths() -> None:
    spec = _spec(
        summary="see app/models/user.py and src/handlers/test_helper.py",
        functional_requirements=[
            _fr("FR-001", "implementation in app/services/foo.py")
        ],
    )
    assert extract_test_references(spec) == []


def test_extract_test_references_handles_punctuation_after_path() -> None:
    spec = _spec(
        summary=(
            "See (tests/unit/test_foo.py::test_bar), "
            "tests/unit/test_baz.py."
        )
    )
    refs = extract_test_references(spec)
    assert ("tests/unit/test_foo.py", "test_bar") in refs
    # ``.`` after the .py extension should not be swallowed into the path.
    assert ("tests/unit/test_baz.py", None) in refs


# ---------------------------------------------------------------------------
# generate_stub_test_file
# ---------------------------------------------------------------------------


def test_generate_stub_creates_minimum_pytest_file(tmp_path: Path) -> None:
    out = generate_stub_test_file(
        "tests/unit/test_foo.py", ["test_one", "test_two"], tmp_path
    )
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "def test_one() -> None:" in text
    assert "def test_two() -> None:" in text
    # And an empty conftest at scratch root to insulate from outer projects.
    assert (tmp_path / "conftest.py").is_file()


def test_generate_stub_no_function_names_emits_placeholder(tmp_path: Path) -> None:
    out = generate_stub_test_file("tests/unit/test_foo.py", [], tmp_path)
    text = out.read_text(encoding="utf-8")
    # Some test function must exist or pytest collects 0 from the file.
    assert "def test_" in text


def test_generate_stub_filters_invalid_identifiers(tmp_path: Path) -> None:
    """Non-identifier function names must be replaced (no SyntaxError)."""
    out = generate_stub_test_file(
        "tests/unit/test_bad.py", ["not a valid name", "class"], tmp_path
    )
    text = out.read_text(encoding="utf-8")
    assert "not a valid name" not in text
    # ``class`` is a Python keyword and must not be emitted as a function name.
    assert "def class(" not in text
    assert "def test_" in text


# ---------------------------------------------------------------------------
# verify_spec_test_executability — real subprocess (one integration test)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_verify_collects_clean_stub(tmp_path: Path) -> None:
    """End-to-end: generate a valid stub, verify pytest --collect-only collects it."""
    spec = _spec(
        user_stories=[
            _us(
                "US-1",
                independent_test=(
                    "tests/unit/test_clean.py::test_alpha and "
                    "tests/unit/test_clean.py::test_beta"
                ),
            )
        ]
    )
    scratch = tmp_path / "scratch"
    problems = verify_spec_test_executability(
        spec,
        target_repo=tmp_path,
        scratch_dir=scratch,
        timeout_s=60,
    )
    assert problems == []
    # Stub file exists and was generated by the validator.
    assert (scratch / "tests" / "unit" / "test_clean.py").is_file()


@pytest.mark.integration
def test_verify_flags_syntactically_broken_stub(tmp_path: Path) -> None:
    """Pre-place a Python file with a syntax error and confirm it's flagged."""
    spec = _spec(
        functional_requirements=[
            _fr(
                "FR-001",
                "Verified by tests/unit/test_broken.py::test_thing.",
            )
        ]
    )
    scratch = tmp_path / "scratch"
    target = scratch / "tests" / "unit" / "test_broken.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Unclosed bracket => SyntaxError on import-time collection.
    target.write_text(
        textwrap.dedent(
            """
            def test_thing(:
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
    assert problems, "expected at least one problem for the broken stub"
    flagged = next(
        (p for p in problems if p.test_path == "tests/unit/test_broken.py"),
        None,
    )
    assert flagged is not None
    assert flagged.problem in {PROBLEM_IMPORT_ERROR, PROBLEM_COLLECT_ERROR}
    assert flagged.test_name == "test_thing"


# ---------------------------------------------------------------------------
# verify_spec_test_executability — mocked subprocess (fast, deterministic)
# ---------------------------------------------------------------------------


def _fake_completed(
    *, returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["pytest", "--collect-only"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_verify_flags_missing_function(tmp_path: Path) -> None:
    """Stub collects test_a; spec wanted test_b → spec-named function flagged."""
    spec = _spec(
        functional_requirements=[
            _fr("FR-001", "Covered by tests/unit/test_present.py::test_b")
        ]
    )
    fake_stdout = "tests/unit/test_present.py::test_a\n\n1 tests collected in 0.01s\n"
    scratch = tmp_path / "scratch"
    # Pre-place a stub that only defines test_a so the validator doesn't overwrite.
    (scratch / "tests" / "unit").mkdir(parents=True)
    (scratch / "tests" / "unit" / "test_present.py").write_text(
        "def test_a() -> None:\n    pass\n", encoding="utf-8"
    )
    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only",
        return_value=_fake_completed(returncode=0, stdout=fake_stdout),
    ):
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=scratch,
        )
    assert len(problems) == 1
    assert problems[0].test_path == "tests/unit/test_present.py"
    assert problems[0].test_name == "test_b"
    assert problems[0].problem == PROBLEM_COLLECT_ERROR
    # Detail tells the rewriter the file collected fine, just not this name.
    assert "test_b" in problems[0].detail


def test_verify_handles_no_test_refs_gracefully(tmp_path: Path) -> None:
    """A spec with no test references yields no problems and runs no pytest."""
    spec = _spec()
    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only"
    ) as run_mock:
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=tmp_path / "scratch",
        )
    assert problems == []
    run_mock.assert_not_called()


def test_verify_classifies_import_error(tmp_path: Path) -> None:
    spec = _spec(
        functional_requirements=[
            _fr("FR-001", "Covered by tests/unit/test_import.py::test_x")
        ]
    )
    err_stderr = (
        "ERRORS\n"
        "______________ ERROR collecting tests/unit/test_import.py ______________\n"
        "ImportError while importing test module 'tests/unit/test_import.py'.\n"
        "ModuleNotFoundError: No module named 'this_does_not_exist'\n"
    )
    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only",
        return_value=_fake_completed(returncode=2, stdout="", stderr=err_stderr),
    ):
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=tmp_path / "scratch",
        )
    assert problems
    assert any(p.problem == PROBLEM_IMPORT_ERROR for p in problems)


def test_verify_classifies_fixture_not_found(tmp_path: Path) -> None:
    spec = _spec(
        functional_requirements=[
            _fr("FR-001", "Covered by tests/unit/test_fixture.py::test_x")
        ]
    )
    err_output = (
        "ERROR: fixture 'unknown_fixture' not found in tests/unit/test_fixture.py\n"
    )
    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only",
        return_value=_fake_completed(returncode=2, stdout="", stderr=err_output),
    ):
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=tmp_path / "scratch",
        )
    assert problems
    assert any(p.problem == PROBLEM_FIXTURE_NOT_FOUND for p in problems)


def test_verify_handles_subprocess_timeout(tmp_path: Path) -> None:
    spec = _spec(
        functional_requirements=[
            _fr("FR-001", "tests/unit/test_slow.py::test_x")
        ]
    )
    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only",
        side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=1),
    ):
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=tmp_path / "scratch",
            timeout_s=1,
        )
    assert problems
    assert all(p.problem == PROBLEM_COLLECT_ERROR for p in problems)
    assert any("timed out" in p.detail for p in problems)


def test_verify_file_only_reference_collects_when_any_test_present(
    tmp_path: Path,
) -> None:
    """A bare ``tests/foo.py`` reference passes if at least one test collects."""
    spec = _spec(summary="background in tests/unit/test_general.py and elsewhere")
    fake_stdout = (
        "tests/unit/test_general.py::test_anything\n\n1 tests collected in 0.01s\n"
    )
    with patch(
        "devloop.spec_phase.validators.test_executability._run_pytest_collect_only",
        return_value=_fake_completed(returncode=0, stdout=fake_stdout),
    ):
        problems = verify_spec_test_executability(
            spec,
            target_repo=tmp_path,
            scratch_dir=tmp_path / "scratch",
        )
    assert problems == []


# ---------------------------------------------------------------------------
# parser / classifier internals
# ---------------------------------------------------------------------------


def test_parse_collected_node_ids_strips_parametrize_and_class() -> None:
    stdout = (
        "tests/test_a.py::test_one\n"
        "tests/test_a.py::test_two[param-1]\n"
        "tests/test_b.py::TestClass::test_method\n"
        "\n"
        "3 tests collected in 0.02s\n"
    )
    collected = _parse_collected_node_ids(stdout)
    assert ("tests/test_a.py", "test_one") in collected
    assert ("tests/test_a.py", "test_two") in collected
    assert ("tests/test_b.py", "test_method") in collected


def test_classify_error_picks_most_specific() -> None:
    assert (
        _classify_error("fixture 'foo' not found in test_x", "tests/test_x.py")
        == PROBLEM_FIXTURE_NOT_FOUND
    )
    assert (
        _classify_error("ImportError while importing test module", "tests/test_x.py")
        == PROBLEM_IMPORT_ERROR
    )
    assert (
        _classify_error("SyntaxError: invalid syntax", "tests/test_x.py")
        == PROBLEM_IMPORT_ERROR
    )
    assert (
        _classify_error("ERROR: file or directory not found", "tests/test_x.py")
        == PROBLEM_NO_SUCH_FILE
    )
    assert (
        _classify_error("some other failure mode", "tests/test_x.py")
        == PROBLEM_COLLECT_ERROR
    )


def test_test_executability_problem_is_frozen_dataclass() -> None:
    """Problems must be hashable/immutable so they can be safely deduped/logged."""
    p = TestExecutabilityProblem(
        test_path="tests/foo.py",
        test_name="test_x",
        problem=PROBLEM_COLLECT_ERROR,
        detail="d",
    )
    with pytest.raises((AttributeError, Exception)):
        p.problem = PROBLEM_IMPORT_ERROR  # type: ignore[misc]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
