# Review v2 — Completeness axis

v2 edits relevant to this axis:

- **SC-008** now explicitly pins the JSON shape of `archived_at` /
  `archived_by` per mode (resolves v1 High H1). The threshold lists
  every per-row contract: default mode → both fields == null; ?archived=true
  → both non-null; ?archived=all → null/non-null based on the row's
  archive state.

## Verdict
APPROVE

## Critical issues
None.

## High issues
None.

### Verification that v1 H1 is closed

v1 H1 was: "`?archived=all` field-projection contract is implicit, not
explicit". v2 SC-008 now reads (excerpt):

> ?archived=all returns the union, and each archived row populates
> both fields while each active row sets both to null

with a corresponding threshold

> ?archived=all mode set equals their union with the per-row
> null/non-null shape matching whether the row is archived

This pins the contract. v1 H1 is closed.

## Medium issues

### M1. (From v1, unchanged) SC-004 still doesn't enumerate bulk-item endpoints

Same as v1 M1: SC-004 enumerates the singular `POST /items` /
`PUT /items/{id}` / `DELETE /items/{id}` endpoints but not the bulk
forms (`POST /items/create-bulk`, `PUT /items`, `DELETE /items`).
FR-008's code path covers them via `create_many`/`update_many`/
`delete_many`, so the implementation is correct; only the SC text could
include them. Medium.

### M2. (From v1, unchanged) Rubric "downstream consumer" coverage is partial

Same as v1 M2: the spec inventories the scheduler consumer (FR-014),
defers cookbook/backups/UI to out_of_scope or assumptions, but doesn't
add a dedicated FR for `backups_v2`. Medium.

### M3. (From v1, unchanged) DELETE /lists/{id} not stated

Same as v1 M3. Medium.

## Coverage matrix unchanged from v1 (see review_v1_completeness.md).

## Summary

- Critical: 0 | High: 0 | Medium: 3
