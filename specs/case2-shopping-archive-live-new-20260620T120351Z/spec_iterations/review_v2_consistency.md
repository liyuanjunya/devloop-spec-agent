# Review v2 — Consistency axis

v2 changes relevant to this axis:

- **NC-001.related_requirements** now reads
  `["FR-007", "FR-008", "FR-010", "FR-016", "SC-004"]` — closes v1 H2.
- **NC-002.if_rejected** now instructs a rewriter to also amend SC-006
  (drop `total_estimated_amount` from the 8-key threshold) and update
  FR-005 / key_entities if the field is dropped — closes v1 H1.

## Verdict
APPROVE

## Critical issues
None.

## High issues
None.

### Verification that v1 highs are closed

- **v1 H1 (NC-002 if_rejected incomplete)** — v2 if_rejected now reads
  (excerpt): "ALSO amend SC-006 (threshold currently enumerates 8
  payload keys) to require exactly 7 keys ... and remove the field
  from FR-005's enumeration and from the EventShoppingListArchiveData
  entry in key_entities." This makes the if_rejected path mechanically
  complete — every spec field that mentions `total_estimated_amount`
  is named. Closed.
- **v1 H2 (NC-001 related_requirements incomplete)** — v2 now lists
  FR-007, FR-008, FR-010, FR-016, SC-004. The downstream-affected
  fields if NC-001 flips are FR-010 (controller endpoints), FR-016
  (test scope), plus the original FR-007/FR-008/SC-004. Closed.

## Medium issues

### M1. (From v1, unchanged) mixins.py:79-83 is cited only in the edge case prose

Same as v1 M1. Medium.

### M2. (From v1, unchanged) US-5 acceptance scenario conflates create vs. update on items

Same as v1 M2. Medium.

### M3. (From v1, unchanged) SC-006 "exactly 1 event per call" wording

Same as v1 M3. Medium.

## Strengths (unchanged)

- All 4 trace-matrix rules still pass (B3 gaps = 0).
- Edge cases still align with FRs.
- v2 corrections did NOT introduce any new dangling references — the
  new `FR-010` / `FR-016` entries in NC-001.related_requirements both
  resolve to FRs that exist in the same spec; the SC-006 / FR-005 /
  key_entities mention in NC-002.if_rejected is prose (not a
  machine-readable cross-reference) so trace-matrix doesn't complain
  even if `total_estimated_amount` survives in v2 (which it does —
  the if_rejected path only fires if the reviewer rejects the
  default).

## Summary

- Critical: 0 | High: 0 | Medium: 3
