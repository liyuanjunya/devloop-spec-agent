"""Run all 4 validators against the new pipeline spec for case-6 (live-new-20260620 run)."""
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

WORKSPACE = ROOT / "specs" / "case6-live-new-20260620"
MEALIE_ROOT = Path(r"C:\Users\v-liyuanjun\Downloads\mealie")


def validate_spec(spec_json_path: Path, spec_md_path: Path, label: str) -> int:
    print(f"\n{'='*72}\nValidating {label}: {spec_json_path}\n{'='*72}")
    raw = json.loads(spec_json_path.read_text(encoding="utf-8"))
    total_problems = 0

    print("\n=== A4 — pydantic schema + soft-language validator ===")
    try:
        spec: Spec = spec_from_json(raw)
        print(f"  PASS: Spec parsed cleanly with schema_version={spec.schema_version}")
        print(f"  Counts: {len(spec.user_stories)} stories, "
              f"{len(spec.functional_requirements)} FRs, "
              f"{len(spec.success_criteria)} SCs, "
              f"{len(spec.edge_cases)} edge cases, "
              f"{len(spec.needs_clarification)} blocking decisions, "
              f"{len(spec.self_concerns)} concerns")
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
        print(f"  PASS: 0 trace gaps "
              f"(every functional FR -> SC, every SC -> FR, every P1 US -> FR)")
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

    print(f"\n=== TOTAL PROBLEMS FOR {label}: {total_problems} ===")

    if total_problems == 0:
        md = spec_to_markdown(spec)
        spec_md_path.write_text(md, encoding="utf-8")
        print(f"Wrote rendered spec.md to {spec_md_path} ({len(md)} chars)")
    return total_problems


def main() -> int:
    # v1
    v1_problems = validate_spec(
        WORKSPACE / "spec.json", WORKSPACE / "spec.md", "v1 (initial writer output)"
    )
    # v2 if present
    v2_json = WORKSPACE / "spec_iterations" / "spec_v2.json"
    v2_md = WORKSPACE / "spec_iterations" / "spec_v2.md"
    v2_problems = 0
    if v2_json.exists():
        v2_problems = validate_spec(v2_json, v2_md, "v2 (post-review rewrite)")
    return 0 if (v1_problems == 0 and v2_problems == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
