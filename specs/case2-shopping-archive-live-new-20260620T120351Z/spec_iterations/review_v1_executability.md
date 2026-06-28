# Review v1 — Executability axis

Verified every code reference, line range, symbol presence, and the
absence of soft language. Mechanical validators were re-run and pass:

- A4 (soft-language regex): clean (no `or equivalent`, `TBD`, `if needed`,
  `placeholder`, `to be decided`, no Unicode-confusable bypass).
- A5 (citation verifier on `C:\Users\v-liyuanjun\Downloads\mealie\`): 0
  problems across all 16 FRs.
- B3 (trace matrix): 0 gaps across 9 user stories / 16 FRs / 10 SCs.
- B1 (md↔json roundtrip): PASS.
- F3 (under-escalation regex): clean — no `Concern.evidence_gap` enumerates
  ≥3 implementation options.

## Verdict
APPROVE

## Critical issues
None.

## High issues
None.

## Medium issues

### M1. SC-001 metric is partly subjective ("after upgrade/downgrade cycle")

SC-001 measures `shopping_lists row count` against the pre-upgrade
total, but the threshold reads "equal to pre-upgrade count, with zero
rows lost across upgrade then downgrade then upgrade." The "zero rows
lost" part is testable; the "equal to pre-upgrade count" half is
trivially true unless the migration deletes rows (which it doesn't
because it only adds nullable columns). Recommend tightening to:
"row count and column set after upgrade equal the pre-upgrade row count
and a strict superset of the pre-upgrade column set; downgrade returns
the column set to the pre-upgrade set and row count is preserved."
Severity Medium — the test is still executable as-written, just less
informative.

### M2. SC-010 acceptance is ambiguous about "passes when invoked"

SC-010 says the new `ArchivedShoppingListsTestCase` "passes when invoked
by `test_multitenant_cases_get_all`" but does not specify the assertion
inside the case. Per the template
(`tests/multitenant_tests/case_foods.py:1-50`) the case must implement
`ABCMultiTenantTestCase`'s abstract methods (likely `get_one`,
`get_all`, `create_one`, `update_one`, `delete_one`). Recommend
expanding the SC to enumerate those entrypoints. Severity Medium —
implementers can read the template themselves, but the SC is one
hop removed from a concrete pass/fail.

## Executability strengths

- Every `code_references` entry was verified file-by-file. Sample
  spot-checks:
  - `mealie/db/models/household/shopping_list.py` lines 147-181 contain
    `class ShoppingList` ✓
  - `mealie/services/event_bus_service/event_types.py` lines 130-132
    contain `EventShoppingListData` and `shopping_list_id` ✓
  - `mealie/routes/_base/base_controllers.py` lines 192-214 contain
    `BaseCrudController` and `publish_event` (line 199-214) ✓
  - `mealie/repos/repository_generic.py` lines 94-102 contain
    `_filter_builder` ✓
  - `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py`
    lines 37-75 contain `_trim_list_items` and the
    `delete_old_checked_list_items` body ✓
- Every FR.text reads as a concrete change: which file, which line,
  which symbol. No "or equivalent" / "TBD" / "if needed" leak through.
- SC thresholds are deterministic (row counts, HTTP status codes,
  payload key sets, exception counts) — no "feels fast", "reasonable
  latency", etc.

## Summary

- Critical: 0 | High: 0 | Medium: 2
