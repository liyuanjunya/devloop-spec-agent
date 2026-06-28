"""spec.md ↔ spec.json bridge.

The writer produces a Spec pydantic model — this module renders it to
human-readable markdown and parses markdown back to a Spec (best effort,
used by V2 incremental update).
"""

from __future__ import annotations

import json
from typing import Any

from devloop.spec_phase.schemas import (
    Spec,
)

# Map of H2 section heading text (exact text after "## ") → Spec attribute name.
# Used by find_md_only_content to verify every rendered section corresponds
# to a normative Spec field. Keep in lock-step with spec_to_markdown.
_KNOWN_H2_SECTIONS: dict[str, str] = {
    "Summary": "summary",
    "NEEDS_CLARIFICATION (blocking decisions)": "needs_clarification",
    "User Scenarios & Testing": "user_stories",
    "Requirements": "functional_requirements",
    "Success Criteria": "success_criteria",
    "Key Entities": "key_entities",
    "Edge Cases": "edge_cases",
    "Assumptions": "assumptions",
    "Out of Scope": "out_of_scope",
    "Self-Concerns (writer self-reflection)": "self_concerns",
}


def spec_to_markdown(spec: Spec) -> str:
    """Render Spec as well-structured markdown."""
    lines: list[str] = []
    lines.append(f"# Feature Specification: {spec.metadata.title}")
    lines.append("")
    lines.append(f"**Feature ID**: `{spec.metadata.feature_id}`")
    lines.append(f"**Schema version**: {spec.schema_version}")
    if spec.metadata.needs_review:
        lines.append("**Status**: ⚠ NEEDS HUMAN REVIEW")
    lines.append("")

    if spec.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(spec.summary)
        lines.append("")

    # Blocking decisions (NEEDS_CLARIFICATION) — render BEFORE user stories
    # so a downstream reader sees blockers first.
    if spec.needs_clarification:
        lines.append("## NEEDS_CLARIFICATION (blocking decisions)")
        lines.append("")
        for nc in spec.needs_clarification:
            lines.append(f"### {nc.id} — {nc.title}")
            lines.append("")
            lines.append(f"**Conflict**: {nc.conflict}")
            lines.append("")
            lines.append(f"**Recommended default**: {nc.recommended_default}")
            lines.append("")
            lines.append(f"**If rejected**: {nc.if_rejected}")
            if nc.related_requirements:
                lines.append("")
                lines.append(f"**Related**: {', '.join(nc.related_requirements)}")
            lines.append("")

    # User Stories
    if spec.user_stories:
        lines.append("## User Scenarios & Testing")
        lines.append("")
        for us in spec.user_stories:
            lines.append(f"### {us.id} — {us.title} (Priority: {us.priority.value})")
            lines.append("")
            lines.append(us.description)
            lines.append("")
            if us.why_this_priority:
                lines.append(f"**Why this priority**: {us.why_this_priority}")
                lines.append("")
            if us.independent_test:
                lines.append(f"**Independent test**: {us.independent_test}")
                lines.append("")
            if us.acceptance:
                lines.append("**Acceptance Scenarios**:")
                lines.append("")
                for i, ac in enumerate(us.acceptance, 1):
                    lines.append(f"{i}. **Given** {ac.given}, **When** {ac.when}, **Then** {ac.then}")
                lines.append("")

    # Functional Requirements
    if spec.functional_requirements:
        lines.append("## Requirements")
        lines.append("")
        lines.append("### Functional Requirements")
        lines.append("")
        for fr in spec.functional_requirements:
            tag = "[NFR]" if fr.requirement_type == "non_functional" else "[FR]"
            lines.append(f"- **{fr.id}** {tag}: {fr.text}")
            if fr.code_references:
                refs = []
                for ref in fr.code_references:
                    parts = [f"`{ref.path}`"]
                    if ref.line_ranges:
                        ranges_str = ", ".join(
                            f"{s}-{e}" if s != e else f"{s}" for s, e in ref.line_ranges
                        )
                        parts.append(f"L{ranges_str}")
                    if ref.symbols:
                        parts.append(f"({', '.join(ref.symbols)})")
                    refs.append(" ".join(parts))
                lines.append(f"  - Code references: {', '.join(refs)}")
            if fr.related_user_stories:
                lines.append(f"  - Related: {', '.join(fr.related_user_stories)}")
        lines.append("")

    # Success Criteria
    if spec.success_criteria:
        lines.append("## Success Criteria")
        lines.append("")
        for sc in spec.success_criteria:
            lines.append(f"- **{sc.id}**: {sc.text}")
            lines.append(f"  - Metric: {sc.metric} | Threshold: {sc.threshold}")
        lines.append("")

    # Key Entities
    if spec.key_entities:
        lines.append("## Key Entities")
        lines.append("")
        for e in spec.key_entities:
            lines.append(f"- **{e.name}**: {e.description}")
            if e.fields:
                lines.append(f"  - Fields: {', '.join(e.fields)}")
            if e.references:
                lines.append(f"  - References: {', '.join(e.references)}")
        lines.append("")

    # Edge cases
    if spec.edge_cases:
        lines.append("## Edge Cases")
        lines.append("")
        for ec in spec.edge_cases:
            line = f"- {ec.description}"
            if ec.handling:
                line += f" → {ec.handling}"
            lines.append(line)
        lines.append("")

    if spec.assumptions:
        lines.append("## Assumptions")
        lines.append("")
        for a in spec.assumptions:
            lines.append(f"- {a}")
        lines.append("")

    if spec.out_of_scope:
        lines.append("## Out of Scope")
        lines.append("")
        for o in spec.out_of_scope:
            lines.append(f"- {o}")
        lines.append("")

    if spec.self_concerns:
        lines.append("## Self-Concerns (writer self-reflection)")
        lines.append("")
        for c in spec.self_concerns:
            lines.append(f"- **{c.location}**: {c.concern}")
            lines.append(f"  - Evidence gap: {c.evidence_gap}")
            if c.suggested_resolution:
                lines.append(f"  - Suggested resolution: {c.suggested_resolution}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"_Generated by DevLoop spec phase — writer={spec.metadata.writer_model}, "
        f"reviewer={spec.metadata.reviewer_model}, "
        f"iterations={spec.metadata.iterations}_"
    )

    return "\n".join(lines)


def spec_to_json(spec: Spec) -> str:
    """Serialize Spec to indented JSON."""
    return json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)


def spec_from_json(data: str | dict[str, Any]) -> Spec:
    if isinstance(data, str):
        data = json.loads(data)
    return Spec.model_validate(data)


def _find_first_dict_diff(
    a: Any, b: Any, *, path: str = ""
) -> tuple[str, Any, Any] | None:
    """Walk two JSON-like structures, return (field_path, a_value, b_value) on first diff.

    Returns None when fully equal.
    """
    if type(a) is not type(b):
        return (path or "<root>", a, b)
    if isinstance(a, dict):
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        if a_keys != b_keys:
            missing_in_b = sorted(a_keys - b_keys)
            missing_in_a = sorted(b_keys - a_keys)
            return (
                path or "<root>",
                {"missing_in_round": missing_in_b, "extra_in_round": missing_in_a},
                None,
            )
        for k in a:
            sub = _find_first_dict_diff(a[k], b[k], path=f"{path}.{k}" if path else k)
            if sub is not None:
                return sub
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return (path or "<root>", f"len={len(a)}", f"len={len(b)}")
        for i, (av, bv) in enumerate(zip(a, b, strict=True)):
            sub = _find_first_dict_diff(av, bv, path=f"{path}[{i}]")
            if sub is not None:
                return sub
        return None
    if a != b:
        return (path or "<root>", a, b)
    return None


def _first_line_diff(a: str, b: str) -> tuple[int, str, str]:
    """Return (line_no_1based, a_line, b_line) of the first differing line.

    If one string has trailing lines the other lacks, the missing side is "".
    Both strings are assumed to differ; behaviour when equal is undefined.
    """
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    for i in range(max(len(a_lines), len(b_lines))):
        a_line = a_lines[i] if i < len(a_lines) else ""
        b_line = b_lines[i] if i < len(b_lines) else ""
        if a_line != b_line:
            return (i + 1, a_line, b_line)
    # Strings differ only in trailing newline / whitespace
    return (len(a_lines) + 1, "<EOF>", "<EOF>")


def assert_spec_roundtrip_consistent(spec: Spec) -> None:
    """Verify md and json renderings encode the same Spec.

    Raises ValueError with a diff if any normative field differs after roundtrip.
    Renders spec -> json -> Spec -> md vs spec -> md, then deep-equal.
    """
    json_str = spec_to_json(spec)
    spec_round = spec_from_json(json_str)

    original_dump = spec.model_dump(mode="json")
    round_dump = spec_round.model_dump(mode="json")
    if original_dump != round_dump:
        diff = _find_first_dict_diff(original_dump, round_dump)
        if diff is not None:
            field_path, a_val, b_val = diff
            raise ValueError(
                "spec json roundtrip lost data: "
                f"field={field_path!r} original={a_val!r} after_roundtrip={b_val!r}"
            )
        # Defensive: dicts differ but walker found nothing — should not happen
        raise ValueError("spec json roundtrip differs but no field diff located")

    md_original = spec_to_markdown(spec)
    md_round = spec_to_markdown(spec_round)
    if md_original != md_round:
        line_no, a_line, b_line = _first_line_diff(md_original, md_round)
        raise ValueError(
            "spec markdown roundtrip differs: "
            f"line={line_no} original={a_line!r} after_roundtrip={b_line!r}"
        )


def find_md_only_content(spec: Spec) -> list[str]:
    """Return descriptions of any rendered markdown sections that don't map to a Spec field.

    Every ## H2 heading in the rendered spec.md MUST correspond to a normative
    Spec attribute (per _KNOWN_H2_SECTIONS). The trailing '_Generated by
    DevLoop ..._' footer line is non-normative and ignored.

    Returns an empty list when the rendering is consistent.
    """
    md = spec_to_markdown(spec)
    spec_field_names = set(Spec.model_fields.keys())
    unmapped: list[str] = []

    for line in md.splitlines():
        if not line.startswith("## "):
            continue
        heading = line[3:].strip()
        mapped_attr = _KNOWN_H2_SECTIONS.get(heading)
        if mapped_attr is None:
            unmapped.append(
                f"unknown H2 section in rendered markdown: {heading!r} "
                "(no entry in _KNOWN_H2_SECTIONS)"
            )
        elif mapped_attr not in spec_field_names:
            unmapped.append(
                f"H2 section {heading!r} maps to attribute {mapped_attr!r} "
                "which is not a Spec field"
            )

    return unmapped
