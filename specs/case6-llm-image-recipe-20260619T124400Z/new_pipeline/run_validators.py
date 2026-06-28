"""Run all 4 validators against the new pipeline spec for case-6."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\v-liyuanjun\source\repos\devloop")
sys.path.insert(0, str(ROOT))

from devloop.spec_phase.md_json_bridge import (
    assert_spec_roundtrip_consistent,
    find_md_only_content,
    spec_from_json,
    spec_to_markdown,
)
from devloop.spec_phase.schemas import Spec
from devloop.spec_phase.validators import (
    find_trace_gaps,
    verify_spec_citations,
)

SPEC_PATH = ROOT / "specs" / "case6-llm-image-recipe-20260619T124400Z" / "new_pipeline" / "spec.json"
MEALIE_ROOT = Path(r"C:\Users\v-liyuanjun\Downloads\mealie")
MD_PATH = ROOT / "specs" / "case6-llm-image-recipe-20260619T124400Z" / "new_pipeline" / "spec.md"


def main() -> int:
    print(f"Loading {SPEC_PATH}")
    raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    total_problems = 0

    print("\n=== A4 — pydantic schema + soft-language validator ===")
    try:
        spec: Spec = spec_from_json(raw)
        print(f"  PASS: Spec parsed cleanly with schema_version={spec.schema_version}")
        print(f"  Counts: {len(spec.user_stories)} stories, {len(spec.functional_requirements)} FRs, "
              f"{len(spec.success_criteria)} SCs, {len(spec.edge_cases)} edge cases, "
              f"{len(spec.needs_clarification)} blocking decisions, {len(spec.self_concerns)} concerns")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1

    print("\n=== A5 — citation verifier (line ranges + symbols against actual code) ===")
    citation_problems = verify_spec_citations(MEALIE_ROOT, spec)
    if not citation_problems:
        print(f"  PASS: 0 citation problems across "
              f"{sum(len(fr.code_references) for fr in spec.functional_requirements)} citations")
    else:
        print(f"  FAIL: {len(citation_problems)} citation problems")
        for cp in citation_problems:
            print(f"    - {cp.fr_id} ref#{cp.ref_index} {cp.problem}: {cp.detail}")
        total_problems += len(citation_problems)

    print("\n=== B3 — trace matrix (FR<->SC<->US reachability) ===")
    trace_gaps = find_trace_gaps(spec)
    if not trace_gaps:
        print(f"  PASS: 0 trace gaps (every functional FR -> SC, every SC -> FR, every P1 US -> FR)")
    else:
        print(f"  FAIL: {len(trace_gaps)} trace gaps")
        for tg in trace_gaps:
            print(f"    - {tg.kind} actor={tg.actor}: {tg.detail}")
        total_problems += len(trace_gaps)

    print("\n=== B1 — JSON/MD roundtrip ===")
    try:
        assert_spec_roundtrip_consistent(spec)
        print("  PASS: Spec round-trips json -> Spec -> md without data loss")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {e}")
        total_problems += 1

    print("\n=== B1b — find_md_only_content (no markdown-only sections) ===")
    md_only = find_md_only_content(spec)
    if not md_only:
        print("  PASS: every rendered H2 section maps to a normative Spec field")
    else:
        print(f"  FAIL: {len(md_only)} unmapped sections")
        for m in md_only:
            print(f"    - {m}")
        total_problems += len(md_only)

    print(f"\n=== TOTAL PROBLEMS ACROSS ALL VALIDATORS: {total_problems} ===")

    # Render spec.md as part of a successful run so downstream consumers see the rendered form.
    md = spec_to_markdown(spec)
    MD_PATH.write_text(md, encoding="utf-8")
    print(f"\nWrote rendered spec.md to {MD_PATH} ({len(md)} chars)")

    return 0 if total_problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
