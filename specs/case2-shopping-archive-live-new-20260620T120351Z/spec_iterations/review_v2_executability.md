# Review v2 — Executability axis

v2 changes relevant to this axis:

- SC-008 metric and threshold are now strictly checkable per-row
  (every JSON entry has `archived_at == null` xor non-null per mode).
- NC-001 / NC-002 prose changes have no code-reference impact.

All mechanical validators re-run on v2 and pass:

- A4 (soft-language regex): clean.
- A5 (citation verifier): 0 problems across all 16 FRs.
- B3 (trace matrix): 0 gaps.
- B1 (md↔json roundtrip): PASS.
- F3: clean.

## Verdict
APPROVE

## Critical issues
None.

## High issues
None.

## Medium issues

### M1. (From v1, unchanged) SC-001 "row count equals pre-upgrade" half is trivially true

Same as v1 M1: nullable column additions can't lose rows, so the
"equal to pre-upgrade count" half of SC-001 is trivial. Recommend a
follow-up tightening to assert column-set deltas explicitly. Medium.

### M2. (From v1, unchanged) SC-010 doesn't enumerate the abstract methods

Same as v1 M2. Medium.

## Summary

- Critical: 0 | High: 0 | Medium: 2
