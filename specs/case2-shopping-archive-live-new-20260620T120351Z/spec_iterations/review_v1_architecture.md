# Review v1 — Architecture axis

Self-review applied to `spec.json` / `spec.md` against Mealie repository
patterns (Repository–Service–Controller layering, FastAPI dependency
injection, event bus reuse, multi-tenant scoping via
`HouseholdRepositoryGeneric._filter_builder`).

## Verdict
APPROVE

## Critical issues
None.

## High issues
None.

## Medium issues

### M1. (Optional) Document the bypass that NC-001 leaves on the floor

FR-006 centralises the frozen guard at the repository layer
(`RepositoryShoppingList.update` + new `RepositoryShoppingListItem.*`).
That correctly covers the four endpoints input §3 enumerates plus their
bulk siblings. NC-001 documents that three additional list-mutating
routes (`PUT /lists/{id}/label-settings`, `POST /lists/{id}/recipe`,
`POST /lists/{id}/recipe/{recipe_id}/delete`, controller lines 234-283)
do NOT path through the guarded repo methods and therefore remain
mutable while archived. The spec defers this to a reviewer decision via
NC-001 with a defensible recommended default ("freeze only what input
§3 names"). Architecturally this is acceptable for v1 because:

- the guard is centralised exactly where the spec says it should be,
- the bypass is surfaced as a blocking decision rather than swept under
  the rug,
- the alternative (freezing all 7 routes) is documented in `if_rejected`.

This is recorded as Medium (not High) because it is an intentional
documented choice, not an oversight. If the reviewer-decision lands on
"freeze all 7", FR-007 / FR-008 grow but no layering is violated.

### M2. DELETE /lists/{id} is silently not enumerated

Input §3 lists the four frozen routes (`PUT /lists/{id}`,
`POST /items`, `PUT /items/{id}`, `DELETE /items/{id}`). Notably absent
is `DELETE /lists/{id}` (the list-deletion endpoint at controller
line 217). The spec text inherits this silence — FR-007 freezes only
the `update` path. Architecturally this is consistent with the input
("freezing" is about preserving an archived record; deletion is a
different operation), but the spec could be clearer that DELETE
remains intentionally available so users can purge old archives. Worth
adding to assumptions or as an explicit FR. Severity Medium because
no requirement is violated; just a clarity gap a reviewer would ask
about.

## Architectural strengths (verified)

- 3-layer pattern is preserved: controllers delegate to
  `ShoppingListService` (FR-009, FR-010); services orchestrate via the
  repository layer (FR-006, FR-008); repositories raise typed
  exceptions, services translate them to HTTPException with i18n via
  `self.t(...)` (FR-009 mentions this explicitly).
- `BaseCrudController.publish_event` (lines 192-214) is reused via the
  existing `self.event_bus` dependency — no parallel event plumbing is
  introduced (FR-015).
- Multi-tenant scoping continues through
  `HouseholdRepositoryGeneric._filter_builder` (FR-006 explicitly forbids
  bypassing it); the new archived filter composes via `.where(...)`
  AFTER `_filter_builder` runs.
- Event payload class is dedicated (`EventShoppingListArchiveData`,
  FR-005) rather than overloading the existing `EventShoppingListData`,
  which keeps the cross-tenant invariant explicit at the type level.
- Two-migration sequencing (FR-002 columns + FR-004 notifier options) is
  explicit, matching the requirement in
  `mealie/services/event_bus_service/event_types.py` lines 14-22.

## Summary

- Critical: 0 | High: 0 | Medium: 2
