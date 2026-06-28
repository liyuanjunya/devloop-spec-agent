# A3 perf_opt Rule Check — v2 (case-4 NEW pipeline)

## Verdict
**PASS** — v2 strictly strengthens each of the three A3 perf_opt rule defenses without weakening any.

## Rule (recap)

For any `intent_type == "perf_opt"` spec, the writer MUST include:
1. Quantified performance target.
2. Behavior-preservation test.
3. Nested-array-order subtle break defense.

## V2 status per check

### Check (1) — Quantified performance target
- **v1 status**: PASS. FR-009 + FR-010 prose.
- **v2 status**: PASS, strengthened. FR-010 now contains a verbatim Python skeleton that explicitly asserts both bounds:
  ```python
  assert count_large <= count_small + 3  # Relative
  assert count_large <= 10               # Absolute (perPage <= 200)
  ```
- Improvement: implementer can copy-paste; less room for off-by-one or wrong-bound mistakes.

### Check (2) — Behavior-preservation test
- **v1 status**: PASS. FR-014 prose.
- **v2 status**: PASS, strengthened. FR-014 now contains:
  - The full `EXPECTED_KEYS` Python list literal (25 keys in declaration order).
  - A verbatim test skeleton with (g) envelope assertion, (c) top-level list-equal, (d) nested set-equal, (e) `householdsWithTool` set-equal.
- Improvement: the "executable assertion seam" is no longer just promised — it's literally written.

### Check (3) — Nested-array-order subtle break defense
- **v1 status**: PASS. SC-E + NC-007 + FR-014(f) chain.
- **v2 status**: PASS, strengthened. NC-007 now contains a 3×2 DBMS × loader-strategy matrix showing that at least one supported DBMS configuration (Postgres + selectinload, no order_by) makes the joinedload-vs-selectinload nested-order non-equivalent. This converts "potentially yes" into "demonstrably yes on Postgres" — strict factual upgrade.
- The mitigation chain is intact: SC-E → NC-007 (matrix) → FR-014(f) "sort both sides before set comparison" → test docstring → `non_actions` "no order_by added".

## Summary

| Rule check | v1 | v2 |
|---|---|---|
| (1) Quantified target | ✅ PASS (prose) | ✅ PASS (skeleton + prose) |
| (2) Behavior-preservation test | ✅ PASS (prose) | ✅ PASS (EXPECTED_KEYS literal + skeleton + prose) |
| (3) Nested-order trap defense | ✅ PASS (prose) | ✅ PASS (DBMS matrix + prose + skeleton sort) |

**A3 perf_opt rule: FULLY SATISFIED in v2, strictly stronger than v1.**
