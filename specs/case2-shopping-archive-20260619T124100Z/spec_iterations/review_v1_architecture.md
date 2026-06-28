# Architecture Review v1 — Shopping List Archive

## Verdict: REQUEST_CHANGES

**Decision rule:** APPROVE only with 0 Critical + 0 High. This review has **1 Critical, 2 High, 2 Medium**.

## Findings

### C1 — Archived-list immutability is incomplete and accepts partial mutations
- **Severity:** Critical
- **Spec refs:** `spec.md:208-222`, `spec.md:504-508`, `spec.md:540-543`
- **Code refs:** `mealie/routes/households/controller_shopping_lists.py:234-283`, `mealie/services/household_services/shopping_lists.py:430-539`
- **Issue:** The spec explicitly leaves `PUT /lists/{id}/label-settings` mutable and accepts recipe add/remove partial-failure paths. These routes still mutate archived-list state through `shopping_list_multi_purpose_labels`, `list_refs`, or item/list updates, contradicting the feature's frozen historical-record invariant.
- **Required fix:** Freeze every shopping-list mutator that can alter archived list state, including label settings and recipe add/remove routes. Add repo/service guards before any write and test these routes return 409 with no partial writes.

### H1 — `archived_by_user_id` FK delete behavior is contradictory
- **Severity:** High
- **Spec refs:** `spec.md:154-162`, `spec.md:493-497`, `spec.md:525-528`
- **Issue:** FR-2 shows `create_foreign_key(...)` without `ondelete="SET NULL"`, while EC-8/NC-5 says `ON DELETE SET NULL` is required. This ambiguity risks breaking user deletion or producing a migration/model mismatch.
- **Required fix:** Make FR-1/FR-2 unambiguous: both SQLAlchemy model and Alembic migration should specify `ForeignKey("users.id", ondelete="SET NULL")` / `create_foreign_key(..., ondelete="SET NULL")`, with a test deleting the archiving user.

### H2 — Archive/unarchive repository updates are not tenant-scoped
- **Severity:** High
- **Spec refs:** `spec.md:237-245`, `spec.md:368-375`
- **Code refs:** `mealie/repos/repository_generic.py:145-154`, `mealie/repos/repository_generic.py:166-179`
- **Issue:** FR-7 prescribes raw `update(ShoppingList).where(id=item_id)` for archive/unarchive. That bypasses `HouseholdRepositoryGeneric._filter_builder`; service pre-fetch mitigates current controllers, but the central repo method itself remains an unscoped write primitive.
- **Required fix:** Scope archive/unarchive updates through `_filter_builder`/`get_one`-scoped row lookup, or update only rows matched by group + household-owned user. Return 404/no-op for invisible rows, never mutate cross-household rows.

### M1 — HTTP/i18n translation is placed in the service layer
- **Severity:** Medium
- **Spec refs:** `spec.md:334-360`, `spec.md:557-570`
- **Issue:** FR-11 asks `ShoppingListService` to raise `HTTPException` with translated `ErrorResponse`, but the compliance checklist says service methods stay free of HTTP concerns. This weakens the controller/service/repo separation.
- **Recommended fix:** Keep repos raising typed domain exceptions; translate to HTTP/i18n in a controller or global FastAPI exception handler.

### M2 — `RepositoryShoppingListItem` dependency is underspecified
- **Severity:** Medium
- **Spec refs:** `spec.md:267-280`, `spec.md:545-548`
- **Issue:** FR-8 presents multiple implementation options for accessing the parent shopping-list repo, leaving a core architecture seam undecided.
- **Recommended fix:** Specify one approach, preferably constructor injection of `parent_repo: RepositoryShoppingList` from `repository_factory.py`.

## Checklist

- 3-layer routes/services/repos: **Partial** — mostly respected, but HTTP concerns leak into service.
- Centralized archive filter in repo layer: **Partial** — list filter centralized; some mutators bypass guards.
- Frozen-state guard placement: **Fail** — incomplete coverage and partial-write risks.
- Event bus payload tenant leak: **Pass** — payload is constrained and dispatch uses owning group/household.
- Migration backward compatibility: **Partial** — nullable columns ok; FK delete behavior must be fixed.
- Multitenant scoping: **Partial** — read path ok; archive/unarchive raw updates must be scoped.
- `archived_by_user_id` FK/cascade: **Fail until ondelete is made explicit everywhere**.
