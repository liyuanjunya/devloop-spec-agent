# Review v2 — Architecture axis

Same axis as v1 review. v2 changed: SC-008 (field-shape contract),
NC-001 (related_requirements), NC-002 (if_rejected). No structural
changes to the FR / repository layering / event-bus reuse, so the
architectural picture is unchanged.

## Verdict
APPROVE

## Critical issues
None.

## High issues
None.

## Medium issues

### M1. (From v1, unchanged) NC-001 leaves three list-mutating routes intentionally unfrozen

The architectural picture is identical to v1: the centralised guard
lives at the repository layer, three routes (label-settings, recipe-add,
recipe-remove) bypass it by design, and the bypass is surfaced as
NC-001. v2 strengthened NC-001's `related_requirements` to include
FR-010 and FR-016, which makes the downstream impact crisp for any
follow-up rewrite — same intentional-choice verdict as v1 (Medium, not
High).

### M2. (From v1, unchanged) `DELETE /lists/{id}` not enumerated

Still silent on whether DELETE on an archived list is allowed. Not
worth a v2 rewrite — Medium.

## Summary

- Critical: 0 | High: 0 | Medium: 2
