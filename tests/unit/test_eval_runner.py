"""Tests for the eval harness validation logic."""

from pathlib import Path

from devloop.eval.runner import GoldenCase, validate_spec
from devloop.spec_phase.schemas import (
    CodeRef,
    FunctionalRequirement,
    Spec,
    SpecMetadata,
    SuccessCriterion,
)


def _make_case(repo: Path, **kwargs):
    return GoldenCase(name="case", description="d", repo=repo, **kwargs)


def make_minimal_spec(*, with_code_ref_path: str = "app/models/user.py") -> Spec:
    return Spec(
        metadata=SpecMetadata(feature_id="x", title="Y"),
        summary="...",
        user_stories=[],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="t",
                requirement_type="functional",
                code_references=[CodeRef(path=with_code_ref_path)],
            )
        ],
        success_criteria=[
            SuccessCriterion(id="SC-001", text="t", metric="x", threshold="y")
        ],
    )


def test_validate_spec_warns_on_missing_user_story(fixture_repo):
    spec = make_minimal_spec()
    case = _make_case(fixture_repo, min_user_stories=1, min_fr_count=1)
    failures, _warnings, _metrics = validate_spec(spec, case)
    # No user stories → failure
    assert any("User story count" in f for f in failures)


def test_validate_spec_detects_missing_referenced_path(fixture_repo):
    spec = make_minimal_spec(with_code_ref_path="not/a/real/file.py")
    case = _make_case(fixture_repo, min_fr_count=1, min_user_stories=0)
    failures, _, metrics = validate_spec(spec, case)
    assert metrics["missing_path_count"] == 1
    assert any("non-existent" in f for f in failures)


def test_validate_spec_passes_when_paths_real(fixture_repo):
    spec = make_minimal_spec(with_code_ref_path="app/models/user.py")
    case = _make_case(fixture_repo, min_fr_count=1, min_user_stories=0)
    failures, _, metrics = validate_spec(spec, case)
    assert metrics["missing_path_count"] == 0
    # Still fails because no user stories
    # but with min_user_stories=0, no failure
    user_story_failures = [f for f in failures if "User story" in f]
    assert not user_story_failures
