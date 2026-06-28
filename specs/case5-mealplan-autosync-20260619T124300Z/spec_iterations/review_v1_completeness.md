# Completeness Review v1 — Case 5 Meal Plan Auto-Sync

## Verdict

**FAIL — incomplete against input §1-§5.** The spec is strong overall, but several input requirements are missing or contradicted. Items marked **CRITICAL** must be fixed before coding.

## Summary

- Input sections reviewed: §1 Household configuration, §2 scheduler/aggregation/event, §3 manual trigger, §4 cross-domain support, §5 tests.
- Overall coverage: **mostly covered, with critical gaps**.
- Critical findings: **4**.
- Major findings: **3**.

## CRITICAL findings

### C1 — §1 PATCH route support is missing / changed to PUT

Input requires new field support on `PATCH /api/households/preferences` (`input.md:24-26`). The spec instead repeatedly requires the existing `PUT /api/households/preferences` endpoint (`spec.md:13`, `spec.md:48`). This is not equivalent unless the spec explicitly says Mealie only has PUT and adds/aliases PATCH support.

**Required fix:** Add a requirement for `PATCH /api/households/preferences` accepting the three new user-configurable fields, or explicitly require a PATCH alias with the same validation and tenant checks.

### C2 — §2 scheduled task frequency is not 30 minutes

Input requires the scheduled task to run every 30 minutes using Mealie's existing scheduled abstraction (`input.md:30-37`). The spec registers the task in `register_minutely`, documented as the existing 5-minute bucket, and success criteria assert a 5-minute registered interval (`spec.md:56-58`, `spec.md:97`). The 30-minute window gate does not satisfy the requested trigger frequency.

**Required fix:** Specify actual 30-minute scheduling, or justify and encode an accepted repository constraint that no 30-minute bucket exists while preserving exact once-per-window semantics. Tests should assert the intended interval.

### C3 — §2 `consolidate_ingredients` reuse is not cited as required

Input explicitly requires reusing Mealie's existing `consolidate_ingredients` merge function (`input.md:41-43`). The spec instead says to use “consolidate_ingredients semantics” through `ShoppingListService.add_recipe_ingredients_to_list`, `bulk_create_items`, `can_merge`, and `merge_items` (`spec.md:60-62`, `spec.md:134`). It does not cite or require the named shared function `consolidate_ingredients`.

**Required fix:** Cite the actual shared `consolidate_ingredients` function if it exists, and require reuse. If the repository's current canonical seam is different, explicitly map why that seam is equivalent and include verified references.

### C4 — §5 pantry-staple cross-household isolation is contradicted

Input requires multitenant tests proving cross-household pantry-staple markings do not affect each other (`input.md:72-75`). The spec's clarification defaults `is_pantry_staple` to per-Food scope and states same-group cross-household tests should assert the flag is shared (`spec.md:126-128`). That directly conflicts with the input requirement.

**Required fix:** Change the data model/test design so pantry-staple state is isolated per household, or mark this as a true blocking clarification before coding rather than defaulting to the opposite behavior.

## MAJOR findings

### M1 — §2 recipe reference requirement may not link back to meal plan

Input says synced items must be marked with `recipe_references` linking back to meal plan / recipe (`input.md:43-45`). The spec covers recipe references through `get_shopping_list_items_from_recipe` (`spec.md:62`) but only verifies recipe-level references, not meal-plan-entry references. If Mealie's model cannot store meal-plan references, this should be explicitly stated.

### M2 — §4 Food admin route support is under-specified

Input requires `Food.is_pantry_staple` migration + schema + repo + admin/foods routes allowing admins to mark staples (`input.md:55-58`). The spec covers model/schema/migration and existing `PUT /api/foods/{item_id}` with `can_organize()` (`spec.md:31-32`, `spec.md:40-41`, `spec.md:50`). It does not clearly require an admin-only route or confirm that `can_organize()` is the intended admin permission.

### M3 — §5 scheduler test coverage misses the exact interval requirement

Input requests scheduler tests and the review scope calls out the 30-minute interval. Spec tests cover window gating and idempotency (`spec.md:89-90`) but SC-1 asserts 5-minute registration (`spec.md:97`). Add a test/criterion for the final chosen 30-minute scheduling behavior.

## Covered requirements

- Three user-facing `HouseholdPreferences` fields plus storage/migration are covered (`spec.md:27-30`), with extra infrastructure fields.
- Run-time window, daily idempotency, and CAS-based multi-worker safety are covered (`spec.md:59`, `spec.md:63-64`).
- Per-household timezone handling is covered (`spec.md:40`, `spec.md:59`, `spec.md:138-144`).
- Pantry-staple filtering and `Food.is_pantry_staple` persistence are covered in general (`spec.md:31-32`, `spec.md:60`).
- Append/accumulate strategy is covered (`spec.md:61`).
- Manual trigger route, admin/management gate, bypassing daily limit, and response shape are covered (`spec.md:49`, `spec.md:64`).
- Event bus enum/payload/dispatch are covered (`spec.md:76-77`).
- Three i18n keys are covered (`spec.md:83`).
- Unit, integration, and multitenant test files are covered at a high level (`spec.md:89-91`).
- Tenant isolation for meal plans/shopping lists is covered (`spec.md:19`, `spec.md:91`, `spec.md:101`).

## Recommended spec edits before implementation

1. Replace or supplement PUT with PATCH for household preferences.
2. Resolve 30-minute scheduling vs 5-minute minutely registration.
3. Require/cite the exact `consolidate_ingredients` shared function or document the canonical equivalent seam.
4. Redesign pantry-staple storage/tests for true cross-household isolation, or keep it as a blocking clarification.
5. Clarify whether `recipe_references` must include meal-plan entry identity.
6. Clarify admin permission for marking `Food.is_pantry_staple`.
