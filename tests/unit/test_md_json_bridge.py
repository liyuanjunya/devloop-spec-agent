"""Tests for the md ↔ json bridge."""

import pytest

from devloop.spec_phase import md_json_bridge
from devloop.spec_phase.md_json_bridge import (
    assert_spec_roundtrip_consistent,
    find_md_only_content,
    spec_from_json,
    spec_to_json,
    spec_to_markdown,
)
from devloop.spec_phase.schemas import (
    AcceptanceScenario,
    BlockingDecision,
    CodeRef,
    Concern,
    EdgeCase,
    Entity,
    FunctionalRequirement,
    Priority,
    Spec,
    SpecMetadata,
    SuccessCriterion,
    UserStory,
)


def make_full_spec() -> Spec:
    return Spec(
        metadata=SpecMetadata(
            feature_id="product-comments",
            title="Product Comments",
            writer_model="claude",
            reviewer_model="gpt",
            iterations=2,
        ),
        summary="Allow users to comment on products.",
        user_stories=[
            UserStory(
                id="US-1",
                priority=Priority.P1,
                title="Submit a comment",
                description="Logged-in user can write a comment on a product page.",
                acceptance=[
                    AcceptanceScenario(
                        given="I am logged in",
                        when="I submit a comment on a product page",
                        then="the comment is shown immediately under the product",
                    )
                ],
            )
        ],
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="Comments must be associated with a logged-in user.",
                requirement_type="functional",
                code_references=[
                    CodeRef(path="app/models/user.py", symbols=["User"])
                ],
            ),
            FunctionalRequirement(
                id="FR-002",
                text="System should support up to 1000 comments per product.",
                requirement_type="non_functional",
            ),
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="99% of comment submissions complete in under 1s.",
                metric="p99 latency",
                threshold="< 1s",
            )
        ],
        key_entities=[
            Entity(name="Comment", description="A user-authored comment on a product."),
        ],
        assumptions=["Comments are visible immediately, no moderation queue."],
        self_concerns=[
            Concern(
                location="FR-001",
                concern="not 100% sure if anonymous comments should be supported",
                evidence_gap="no existing test pins this behavior down",
            )
        ],
    )


def test_spec_to_markdown_renders_all_sections():
    s = make_full_spec()
    md = spec_to_markdown(s)
    assert "# Feature Specification: Product Comments" in md
    assert "US-1" in md
    assert "FR-001" in md
    assert "FR-002" in md
    assert "[NFR]" in md
    assert "SC-001" in md
    assert "p99 latency" in md
    assert "Comment" in md
    assert "Self-Concerns" in md


def test_spec_to_json_roundtrip():
    s = make_full_spec()
    data = spec_to_json(s)
    assert '"product-comments"' in data
    assert '"FR-001"' in data
    assert '"non_functional"' in data


def test_blocking_decisions_render_before_user_stories():
    """Convergence learning: NEEDS_CLARIFICATION blockers must render at the
    top of the spec (before user stories), so a downstream reader/code-agent
    sees them first and refuses to proceed until they are resolved.
    """
    s = make_full_spec()
    s.needs_clarification = [
        BlockingDecision(
            id="NC-001",
            title="Data model: new table vs reuse",
            conflict="Input requests new table but code already has equivalent.",
            recommended_default="Reuse existing field.",
            if_rejected="Implement new table with backfill.",
            related_requirements=["FR-001"],
        )
    ]
    md = spec_to_markdown(s)

    # Blocker section is present
    assert "NEEDS_CLARIFICATION" in md
    assert "NC-001" in md
    assert "Reuse existing field." in md
    assert "Implement new table" in md

    # Blocker is BEFORE user stories
    blocker_pos = md.index("NEEDS_CLARIFICATION")
    us_pos = md.index("US-1")
    assert blocker_pos < us_pos, "Blocking decisions must render before user stories"

    # JSON roundtrip preserves the blocker
    j = spec_to_json(s)
    s2 = spec_from_json(j)
    assert len(s2.needs_clarification) == 1
    assert s2.needs_clarification[0].id == "NC-001"


# ---------------------------------------------------------------------------
# B1: md/json roundtrip drift detection
# ---------------------------------------------------------------------------


def _spec_with_blocking_decisions() -> Spec:
    s = make_full_spec()
    s.needs_clarification = [
        BlockingDecision(
            id="NC-001",
            title="Data model: new table vs reuse",
            conflict="Input requests new table but code already has equivalent.",
            recommended_default="Reuse existing field.",
            if_rejected="Implement new table with backfill.",
            related_requirements=["FR-001"],
        )
    ]
    return s


def _spec_with_extra_self_concerns() -> Spec:
    s = make_full_spec()
    s.self_concerns.extend(
        [
            Concern(
                location="FR-002",
                concern="1000-comment threshold may be too tight for hot products",
                evidence_gap="no analytics data on top-product comment counts",
                suggested_resolution="bump to 10000 or paginate",
            ),
            Concern(
                location="SC-001",
                concern="p99 latency target may be unrealistic on cold caches",
                evidence_gap="no baseline benchmark for the current endpoint",
            ),
        ]
    )
    s.edge_cases.append(
        EdgeCase(
            description="user submits an empty comment",
            handling="reject with 400 before persisting",
        )
    )
    return s


def test_assert_spec_roundtrip_consistent_passes_for_clean_spec():
    s = make_full_spec()
    # Sanity precondition — the fixture exercises most sections
    assert s.user_stories and s.functional_requirements and s.self_concerns
    # Must not raise
    assert_spec_roundtrip_consistent(s)


def test_assert_spec_roundtrip_consistent_passes_for_spec_with_blocking_decisions():
    s = _spec_with_blocking_decisions()
    assert_spec_roundtrip_consistent(s)


def test_assert_spec_roundtrip_consistent_passes_for_spec_with_self_concerns():
    s = _spec_with_extra_self_concerns()
    assert_spec_roundtrip_consistent(s)


def test_assert_spec_roundtrip_consistent_catches_added_md_only_attribute(monkeypatch):
    """If a hypothetical future spec_to_json drops a field, the assertion
    must catch it via the json-roundtrip deep-equal check.
    """
    s = make_full_spec()
    real_spec_to_json = md_json_bridge.spec_to_json

    def lossy_spec_to_json(spec: Spec) -> str:
        # Simulate a buggy bridge that silently omits self_concerns and edge_cases
        # — exactly the kind of drift the Mealie case-1 v2 sub-agent run showed.
        import json as _json

        data = spec.model_dump(mode="json")
        data["self_concerns"] = []
        data["edge_cases"] = []
        return _json.dumps(data, ensure_ascii=False, indent=2)

    monkeypatch.setattr(md_json_bridge, "spec_to_json", lossy_spec_to_json)

    with pytest.raises(ValueError) as exc_info:
        assert_spec_roundtrip_consistent(s)

    msg = str(exc_info.value)
    assert "roundtrip" in msg.lower()
    # The dropped field name must appear in the diff so a human can locate the bug
    assert "self_concerns" in msg

    # And the original function must still work after the monkeypatch is reverted
    monkeypatch.setattr(md_json_bridge, "spec_to_json", real_spec_to_json)
    assert_spec_roundtrip_consistent(s)


def test_assert_spec_roundtrip_consistent_catches_markdown_only_drift(monkeypatch):
    """If markdown rendering emits content not derivable from the Spec object,
    the byte-equivalence check must surface it.
    """
    s = make_full_spec()
    real_to_md = md_json_bridge.spec_to_markdown
    call_state = {"n": 0}

    def drifting_to_md(spec: Spec) -> str:
        # Inject extra content only on the very first call (the "original" render),
        # so the round-tripped render diverges.
        call_state["n"] += 1
        base = real_to_md(spec)
        if call_state["n"] == 1:
            return base + "\n## Extra Free-Form Section\n\nOnly in md.\n"
        return base

    monkeypatch.setattr(md_json_bridge, "spec_to_markdown", drifting_to_md)

    with pytest.raises(ValueError) as exc_info:
        assert_spec_roundtrip_consistent(s)
    assert "markdown roundtrip differs" in str(exc_info.value)


def test_find_md_only_content_clean():
    """The stock renderer must not emit any unmapped H2 sections."""
    for s in (
        make_full_spec(),
        _spec_with_blocking_decisions(),
        _spec_with_extra_self_concerns(),
    ):
        assert find_md_only_content(s) == []


def test_find_md_only_content_with_injected_extra_section(monkeypatch):
    """If spec_to_markdown is extended to emit a section not backed by a
    Spec attribute, find_md_only_content must surface it.
    """
    s = make_full_spec()
    real_to_md = md_json_bridge.spec_to_markdown

    def drifting_to_md(spec: Spec) -> str:
        base = real_to_md(spec)
        # Append an extra section that does NOT correspond to any Spec field.
        return base + "\n## Implementation Notes\n\nAuthor-only scratch.\n"

    monkeypatch.setattr(md_json_bridge, "spec_to_markdown", drifting_to_md)

    unmapped = find_md_only_content(s)
    assert len(unmapped) == 1
    assert "Implementation Notes" in unmapped[0]
    assert "unknown" in unmapped[0].lower() or "no entry" in unmapped[0].lower()
