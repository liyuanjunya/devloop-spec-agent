# Completeness Review (v2)

## Verdict: NEEDS_REFINE

Spec v2 is much more executable than v1 and resolves the scheduler-cadence, consolidation-seam, recipe-reference, admin-food-route, target-list, and server-only marker ambiguities. However, two original input requirements are still not fully covered: the explicit `PATCH /api/households/preferences` API requirement is rejected rather than supported, and the explicit cross-household pantry-staple isolation test is contradicted by the chosen group-shared `Food.is_pantry_staple` model. One additional pantry-staple edge remains under-scoped for sub-recipes.

## Critical issues

### COMP-C-005 — Cross-household pantry-staple isolation is still contradicted

- Location: `input.md:72-75`; `spec_v2.md:42`, `spec_v2.md:102`, `spec_v2.md:154`; `spec_v2.json` FR-3 / FR-28 / NC-3.
- Evidence: The input requires a multitenant test that “跨 household 的 food pantry-staple 标记不互相影响” (`input.md:75`). Spec v2 instead decides `is_pantry_staple` is per-Food and group-shared (`spec_v2.md:42`, `spec_v2.md:154`) and requires `test_pantry_staple_shared_cross_household_same_group_by_design` to assert that household H2 in the same group observes H1's flag (`spec_v2.md:102`).
- Impact: This is not just a missing test; it asks implementation to prove the opposite of an explicit input requirement.
- Required fix: Either implement household-scoped pantry-staple state (for example via a household association) and assert cross-household independence, or mark NC-3 as a blocking product clarification instead of deciding the opposite behavior.

## High issues

### COMP-H-006 — Required `PATCH /api/households/preferences` support is not covered

- Location: `input.md:24-26`; `spec_v2.md:13-16`, `spec_v2.md:59`; `spec_v2.json` naming_reconciliations / FR-10.
- Evidence: The input explicitly says to add field support to `PATCH /api/households/preferences`. Spec v2 states Mealie currently has `PUT /preferences` and decides “no new PATCH route” (`spec_v2.md:15`), with FR-10 extending only the existing PUT route (`spec_v2.md:59`).
- Impact: Clients following the input contract cannot use PATCH. A code agent would correctly omit the requested route.
- Required fix: Add a PATCH alias with the same body validation, target-list tenant check, permission gate, and server-only `last_auto_synced_at` protection as PUT; or mark this as a blocking product/API clarification.

## Medium issues

### COMP-M-004 — Pantry-staple filtering is explicitly incomplete for sub-recipes

- Location: `input.md:43`, `input.md:71`; `spec_v2.md:146`, `spec_v2.md:155`; `spec_v2.json` EC-8 / NC-4.
- Evidence: The input broadly requires skipping ingredients where `food.is_pantry_staple = true` and integration coverage that pantry staples are not synced. Spec v2 documents that staples inside `referenced_recipe` sub-recipes are not skipped because filtering runs only on top-level `recipe_ingredient` entries.
- Impact: A pantry staple can still be synced through Mealie's existing sub-recipe expansion path, weakening the staple-filter guarantee.
- Suggested fix: Require recursive filtering before item creation, or make NC-4 blocking / product-accepted and add an explicit test documenting the limitation.

## v1 issue resolution table

| v1 issue | v2 status | Evidence | Completeness assessment |
|---|---|---|---|
| C1: PATCH route missing / changed to PUT | Not resolved | `spec_v2.md:15`, `spec_v2.md:59` | v2 documents Mealie reality but still omits the requested PATCH contract. |
| C2: scheduled task frequency not 30 minutes | Resolved with documented repo constraint | `spec_v2.md:17`, `spec_v2.md:67-70`, `spec_v2.md:108-109` | Acceptable from completeness perspective because v2 encodes 5-min registration plus 30-min window/CAS effective behavior. |
| C3: `consolidate_ingredients` reuse not cited | Resolved | `spec_v2.md:16`, `spec_v2.md:71`, `spec_v2.md:161` | v2 verifies the symbol does not exist and pins the canonical existing seam plus case-3 follow-up behavior. |
| C4: pantry-staple cross-household isolation contradicted | Not resolved | `spec_v2.md:102`, `spec_v2.md:154` | v2 still chooses same-group sharing, opposite of input. |
| M1: recipe reference may not link to meal plan | Resolved | `spec_v2.md:73` | v2 explains model limits and preserves recipe-level references; event-only meal-plan linkage is explicit. |
| M2: Food admin route under-specified | Resolved | `spec_v2.md:61` | `can_organize()` mapping is explicit. |
| M3: scheduler test misses final interval behavior | Resolved | `spec_v2.md:100`, `spec_v2.md:108-109` | Tests now cover registration and once-per-day/window behavior. |

## Requirement coverage delta

| Input requirement area | v2 completeness verdict |
|---|---|
| Household preference fields + storage | Covered, except PATCH route support |
| Scheduler task, window, timezone, idempotency, multi-worker CAS | Covered |
| Ingredient consolidation and append/merge semantics | Covered |
| Pantry-staple filtering | Partially covered; cross-household scope and sub-recipes need refinement |
| Manual trigger route, auth, response shape | Covered |
| Event dispatch and i18n keys | Covered |
| Unit/integration/multitenant tests | Mostly covered; pantry isolation test currently asserts the wrong behavior |

## Summary

Refine v2 before coding. The highest-priority fix is pantry-staple scoping: the spec must not require a test that proves the opposite of `input.md`. Add PATCH support or block on an API clarification, and either recursively filter sub-recipe pantry staples or explicitly block/accept that limitation.
