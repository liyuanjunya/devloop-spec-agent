"""Build spec_v2.json — resolve the 3 High issues from v1 self-review.

Changes vs v1:

1. SC-008 (completeness H1): tighten the metric/threshold to explicitly
   require `archived_at`/`archived_by` to be `null` in default-mode rows
   AND populated on archived rows when `?archived=all`. Removes
   the implicit contract risk a test author could trip over.

2. NC-001 (consistency H2): expand `related_requirements` to include
   FR-010 and FR-016 so a downstream rewriter sees every spec field
   that has to move if the reviewer decides to freeze all 7
   list-mutating routes.

3. NC-002 (consistency H1): expand `if_rejected` to also instruct the
   rewriter to amend SC-006 (drop `total_estimated_amount` from the
   8-key threshold) if the field is dropped.

All other content from v1 is preserved verbatim. Citations re-verified.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, r"C:\Users\v-liyuanjun\source\repos\devloop")

from devloop.spec_phase.schemas import Spec
from devloop.spec_phase.validators.citation_verifier import verify_spec_citations
from devloop.spec_phase.validators.trace_matrix import find_trace_gaps
from devloop.spec_phase.md_json_bridge import (
    assert_spec_roundtrip_consistent,
    spec_to_markdown,
)

WORKSPACE = pathlib.Path(
    r"C:\Users\v-liyuanjun\source\repos\devloop\specs\case2-shopping-archive-live-new-20260620T120351Z"
)
MEALIE = pathlib.Path(r"C:\Users\v-liyuanjun\Downloads\mealie")


v1 = json.loads((WORKSPACE / "spec.json").read_text(encoding="utf-8"))

# ---- Fix 1: NC-001 related_requirements ----
for nc in v1["needs_clarification"]:
    if nc["id"] == "NC-001":
        nc["related_requirements"] = ["FR-007", "FR-008", "FR-010", "FR-016", "SC-004"]

# ---- Fix 2: NC-002 if_rejected expansion ----
for nc in v1["needs_clarification"]:
    if nc["id"] == "NC-002":
        nc["if_rejected"] = (
            "If reviewer prefers to drop the field entirely until a price "
            "tracker ships, remove `total_estimated_amount` from "
            "EventShoppingListArchiveData and from FR-009. ALSO amend SC-006 "
            "(threshold currently enumerates 8 payload keys) to require "
            "exactly 7 keys (drop `total_estimated_amount`), and remove the "
            "field from FR-005's enumeration and from the "
            "EventShoppingListArchiveData entry in key_entities. Document "
            "the deferred field in out_of_scope. Both options keep the v1 "
            "implementation simple; this is purely a forward-compat call."
        )

# ---- Fix 3: SC-008 explicit field-shape contract ----
for sc in v1["success_criteria"]:
    if sc["id"] == "SC-008":
        sc["text"] = (
            "GET /api/households/shopping/lists with no query param returns "
            "only rows where archived_at IS NULL, and every returned row "
            "carries archived_at == null AND archived_by == null in the "
            "JSON body. ?archived=true returns only rows where archived_at "
            "IS NOT NULL, and every returned row carries archived_at as a "
            "non-null ISO 8601 timestamp AND archived_by as a non-null "
            "UserSummary. ?archived=all returns the union, and each archived "
            "row populates both fields while each active row sets both to "
            "null. In all three modes, rows from another household never "
            "appear in items[]."
        )
        sc["metric"] = (
            "per-mode set of returned shopping_list ids, per-row JSON shape "
            "of archived_at and archived_by, and cross-household leakage count"
        )
        sc["threshold"] = (
            "default mode set equals active-ids with archived_at == null and "
            "archived_by == null on every row; ?archived=true mode set equals "
            "archived-ids with archived_at non-null and archived_by non-null "
            "on every row; ?archived=all mode set equals their union with the "
            "per-row null/non-null shape matching whether the row is archived; "
            "cross-household leakage equals 0"
        )

# ---- Metadata bump ----
v1["metadata"]["iterations"] = 2

spec = Spec.model_validate(v1)

# Write artifacts: BOTH spec.json (head) AND spec_iterations/spec_v2.*
(WORKSPACE / "spec.json").write_text(
    json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(WORKSPACE / "spec.md").write_text(spec_to_markdown(spec), encoding="utf-8")
(WORKSPACE / "spec_iterations" / "spec_v2.json").write_text(
    json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(WORKSPACE / "spec_iterations" / "spec_v2.md").write_text(
    spec_to_markdown(spec), encoding="utf-8"
)
print(f"Wrote spec.json + spec_iterations/spec_v2.* ({(WORKSPACE / 'spec.json').stat().st_size} bytes)")

# Validators
problems = verify_spec_citations(MEALIE, spec)
print(f"A5 citations: {len(problems)} problems")
for p in problems[:20]:
    print(f"  - {p.fr_id} {p.path} {p.problem}: {p.detail[:200]}")

gaps = find_trace_gaps(spec)
print(f"B3 trace gaps: {len(gaps)} gaps")
for g in gaps[:20]:
    print(f"  - [{g.kind}] {g.actor}: {g.detail[:200]}")

try:
    assert_spec_roundtrip_consistent(spec)
    print("B1 roundtrip: PASS")
except ValueError as exc:
    print(f"B1 roundtrip: FAIL - {exc}")

print(f"A4+F3 schema validation: PASS (FRs={len(spec.functional_requirements)}, SCs={len(spec.success_criteria)}, USs={len(spec.user_stories)}, ECs={len(spec.edge_cases)}, NCs={len(spec.needs_clarification)})")
