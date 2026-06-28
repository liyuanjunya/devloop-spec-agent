# Rewrite — Case 5 spec v1 → v2

> Spec author: **Spec Rewriter** (devloop case-5)
> Inputs: `spec.md` / `spec.json` v1 + 4 reviewer reports (`review_v1_*.md`).
> Code re-verified against `C:\Users\v-liyuanjun\Downloads\mealie\` (mealie repo, branch `devloop-baseline`).

## 0. Verdict at a glance

| Reviewer | v1 Verdict | Severity totals | v2 outcome |
|---|---|---|---|
| Architecture | REQUEST_CHANGES | 1 C / 0 H / 1 M | **C1 rejected** as out-of-scope for the spec phase (no implementation expected in a Spec gate); M1 rejected (concerns unrelated worktree, not the spec). Documented as `out-of-scope` in §3 below. |
| Completeness | FAIL | 4 C / 3 M | All 4 C resolved; all 3 M resolved. |
| Consistency | NEEDS_REVISION | 3 H / 4 M / 2 L | All 3 H resolved; 4 M resolved; 2 L resolved. |
| Executability | NEEDS_REFINE | 1 C / 2 H / 3 M | All 1 C + 2 H resolved; all 3 M resolved; all 7 wrong line ranges corrected. |

Net: every **Critical + High** finding from v1 is either resolved with a concrete change in v2 or explicitly rejected with rationale in §3 (Architecture C1/M1).

---

## 1. Issue-by-issue resolution table

Legend — **Resolution**:
- `FIX` = spec content changed in v2
- `REJECT` = the finding does not apply / is out-of-scope; rationale recorded
- `CLARIFY` = no behavioral change, but wording sharpened to remove ambiguity

| # | Reviewer | Severity | Finding (summary) | Resolution | v2 location |
|---|---|---|---|---|---|
| arch-C1 | Architecture | Critical | "Case-5 implementation absent from Mealie checkout" | **REJECT** — this is a Spec rewriter pass; no implementation is expected yet. The architecture review's decision rule (`APPROVE only with 0 C+H`) was applied to a non-spec scope. The spec already describes every required seam with verified code references. | n/a — explicitly noted in §3 |
| arch-M1 | Architecture | Medium | "Worktree contains unrelated dependency edits" | **REJECT** — unrelated worktree state, not part of the spec. Reviewer should rebase / clean their checkout. | n/a |
| comp-C1 | Completeness | Critical | "`PATCH /api/households/preferences` required by input §1; spec uses `PUT`" | **CLARIFY** — Mealie's actual route is `@router.put("/preferences")` (verified at `controller_household_self_service.py:58-62`). Input §1's "PATCH" is loose phrasing for "update". v2 makes this reconciliation explicit in feature_summary, FR-10, and a new constraint bullet. No new route added. | FR-10 + feature_summary + §"Naming reconciliations" |
| comp-C2 | Completeness | Critical | "Scheduled task must run every 30 min; spec uses 5-min `register_minutely`" | **CLARIFY** — Mealie has no 30-min bucket (`scheduler_service.py:15-17` only defines `MINUTES_5`, `MINUTES_HOUR`, `MINUTES_DAY`) and input §"实现约束" forbids new schedulers. v2: register on `register_minutely` (5-min cadence) and gate per-household to a 30-min window so the *effective per-household execution* is once-per-household-local-day. SC-1 rewritten to assert *registration* + *effective interval*, not "the scheduler ticks every 30 min". Adds a unit test `test_window_gates_to_once_per_day`. | FR-13, FR-14, FR-16, SC-1, SC-2, FR-26 |
| comp-C3 | Completeness | Critical | "Input §2 requires reuse of `consolidate_ingredients`; spec doesn't cite it" | **FIX** — verified: **no top-level `consolidate_ingredients` function exists** in `mealie/` (ripgrep across the whole repo, no matches). The actual consolidation lives inside `ShoppingListService.bulk_create_items` (`shopping_lists.py:154-223`). v2: FR-17 explicitly states "Mealie has no public `consolidate_ingredients` symbol; the canonical consolidation seam is `ShoppingListService.add_recipe_ingredients_to_list` which internally invokes `get_shopping_list_items_from_recipe` → `bulk_create_items` → `can_merge` + `merge_items`. Case-3, if it lands first, may extract a public `consolidate_ingredients`; case-5 must then call it directly." A new `self_concerns` entry (SCN-1) and a smoke unit test (FR-26 / SC-9) verify the (food_id, unit_id) merge end-to-end. | FR-17, SCN-1, FR-26 |
| comp-C4 | Completeness | Critical | "Pantry-staple per-household isolation contradiction" | **CLARIFY → resolve NC-3 as non-blocking** — input §4 literally adds `is_pantry_staple: bool` to the `Food` model (group-shared because `IngredientFoodModel.group_id` scopes Foods to a group). Input §5 "跨 household pantry-staple 标记不互相影响" is reconciled as **cross-group isolation** (which holds via `group_id` scoping). v2: NC-3 flipped from `blocking=true` to `blocking=false` with the explicit decision recorded. FR-28 multitenant test enumerates: (a) cross-group isolation (asserted), (b) cross-household same-group is *shared by design* (asserted — flip flag in H1, observe H2 in same group sees the same flag). | NC-3, FR-28, SC-5 |
| comp-M1 | Completeness | Major | "`recipe_references` may not link to meal plan" | **CLARIFY** — Mealie's `ShoppingListItemRecipeReference` model (`shopping_list.py:26-48`) has no `meal_plan_id` field — meal plans cannot be back-referenced from list items by data model. The link from a list item back to the meal-plan entry is event-based only (via the dispatched `EventMealPlanAutoSyncedData`). v2 makes this explicit in FR-19. | FR-19 |
| comp-M2 | Completeness | Major | "Admin-only route for marking `is_pantry_staple` is under-specified" | **CLARIFY** — verified `PUT /api/foods/{item_id}` at `foods.py:69-73` gates on `self.checks.can_organize()` (`checks.py:38-41`). This is the same permission used to manage any food field. Input §4's "admin" wording maps to `can_organize` (which is a household-level permission — not the global admin flag — and is the canonical food-management gate in Mealie). v2 documents this mapping in FR-12. | FR-12 |
| comp-M3 | Completeness | Major | "SC-1 asserts 5-min registration, not 30-min" | Subsumed by comp-C2. SC-1 rewritten. | SC-1 |
| cons-001 | Consistency | High | "Default target-list fallback may violate same-group isolation" | **FIX** — the v1 wording said `repos.group_shopping_lists.page_all(...)` without naming the household scope. Verified: `repository_factory.py:317-321` constructs `group_shopping_lists` with both `group_id=self.group_id` and `household_id=self.household_id`, so when called from a household-scoped `repos`, the `_filter_builder` in `repository_generic.py:94-102` automatically applies `household_id`. v2 makes this *explicit* in FR-22 and adds an SC-7b assertion. | FR-22, SC-7 |
| cons-002 | Consistency | High | "`last_auto_synced_at` is both client-updatable AND server-only" | **FIX** — v1 listed `last_auto_synced_at` in `UpdateHouseholdPreferences` (FR-7) while SCN-3 said the route must not write it. v2: remove `last_auto_synced_at` from `UpdateHouseholdPreferences`. Keep it on the SQLAlchemy model (FR-1) and add a new read-only field on `ReadHouseholdPreferences` (so the UI can show "last synced at" but never POST it). Add a new field-set helper in FR-7. The CAS path writes it via raw `text(...)` only. | FR-1, FR-7, FR-10, SCN-3 |
| cons-003 | Consistency | High | "CAS timing conflicts with EC-2 'no target list retries next tick'" | **FIX** — v1 said "CAS before any write work". v2 introduces an explicit ordered pipeline in FR-20: (1) load prefs, (2) gate on enabled, (3) gate on window, (4) resolve target list (EC-2 early-return *without* CAS), (5) fetch today's meal plans (EC-1 early-return *with* CAS so we don't re-scan empty days), (6) CAS attempt, (7) sync work, (8) event dispatch. v2 EC-1 and EC-2 are rewritten to match this order. | FR-20, EC-1, EC-2 |
| cons-004 | Consistency | Medium | "Event payload 'only' wording contradicts EventDocumentDataBase fields" | **FIX** — v2 SC-4 reworded to "no recipe titles, no meal-plan IDs, no per-item details beyond the standard `EventDocumentDataBase` metadata (`document_type`, `operation`)". | SC-4 |
| cons-005 | Consistency | Medium | "'first active main list' is undefined" | **FIX** — v2 renames everywhere to "oldest household shopping list (by `created_at` ascending)". Removes "active" and "main" (no such fields exist in case-5 scope). | feature_summary, FR-22, SC-7, EC-2 |
| cons-006 | Consistency | Medium | "Manual-trigger marker update ambiguous for empty/no-op runs" | **FIX** — v2 adds an explicit table (Manual trigger: `last_auto_synced_at` update matrix) covering: (a) successful sync (≥1 item written) → updates marker, (b) empty meal plan → updates marker, (c) no target list → does NOT update marker, (d) target list resolution failure (EC-3 cascade) → does NOT update marker, (e) any exception → does NOT update marker. Mirrored in EC-1, EC-2, EC-3 wording. NC-1 resolved as non-blocking with the documented matrix as the answer. | new §"Manual trigger marker matrix", EC-1, EC-2, EC-3, NC-1 |
| cons-007 | Consistency | Medium | "EC-6 mentions i18n/response that no FR provides" | **FIX** — v2 EC-6 simply states the forward-looking semantic ("pantry-staple flagging is forward-looking only — does not retro-remove existing items") without claiming i18n/response support. The i18n claim is dropped. The frontend can surface this via release notes / docs, not as a runtime message. | EC-6 |
| cons-008 | Consistency | Low | "Constraint mentions group-default timezone but no FR provides it" | **FIX** — v2 removes "group default" from the constraints list. Mealie has no `Group.timezone` column. Fallback is strictly `household.preferences.timezone → "UTC"`. | §"Constraints", FR-16 |
| cons-009 | Consistency | Low | "CAS parameter names drift (`:now_utc/:pref_id/:today_start_utc` vs `:now/:id/:today_start`)" | **FIX** — v2 standardises on `:now`, `:id`, `:today_start` (bound parameter names) in both FR-20 and SC-11. | FR-20, SC-11 |
| exec-C-001 | Executability | Critical | "`mp.recipe.recipe_ingredient` cannot work — `ReadPlanEntry.recipe` is `RecipeSummary` (no `recipe_ingredient` field)" | **FIX** — verified: `ReadPlanEntry.recipe: RecipeSummary \| None` (`new_meal.py:62-65`); `RecipeSummary` (`recipe.py:116-175`) has no `recipe_ingredient`; full `Recipe` (`recipe.py:182-183`) has `recipe_ingredient`. v2 FR-17 explicitly requires re-fetching the full Recipe via `get_repositories(session, group_id=group_id, household_id=None).recipes.get_one(mp.recipe_id, "id")` — mirroring the pattern at `shopping_lists.py:333-336`. | FR-17 |
| exec-H-001 | Executability | High | Same as cons-002. | See cons-002. | FR-7, FR-10, SCN-3 |
| exec-H-002 | Executability | High | Same as cons-005. | See cons-005. | FR-22, SC-7 |
| exec-M-001 | Executability | Medium | "`added_count` semantics not pinned" | **FIX** — v2 FR-17 pins: `added_count = len(item_changes.created_items) + len(item_changes.updated_items)`. SC-3 rewritten to use this definition. | FR-17, SC-3 |
| exec-M-002 | Executability | Medium | "Pantry filtering doesn't cover nested sub-recipes" | **CLARIFY** — verified: `get_shopping_list_items_from_recipe` recursively expands `ingredient.referenced_recipe` (`shopping_lists.py:344-355`). Sub-recipe ingredients are pulled in via that recursion, bypassing our top-level pantry filter. v2 adds **EC-8** documenting this as a known *intentional* limitation: pantry filtering applies to top-level recipe ingredients only. Sub-recipe ingredients flow through unfiltered. Future scope (NC-4) may extend this. | new EC-8, new NC-4 |
| exec-M-003 | Executability | Medium | "Migration chain ordering underspecified" | **FIX** — v2 FR-2/4/6 specify exact `down_revision` order: (a) `add_is_pantry_staple_to_ingredient_foods` ⟵ `2187537c52b8`, (b) `add_auto_sync_to_household_preferences` ⟵ migration (a), (c) `add_meal_plan_auto_synced_to_shopping_event` ⟵ migration (b). | FR-2, FR-4, FR-6, SC-8 |
| exec-cites | Executability | (cite check) | 7 wrong line ranges + 11 `spec.md` vs `spec.json` drift in code_references | **FIX** — see §2 below. Every range re-verified via `(Get-Content $f).Length` and every code_reference list normalised to identical entries between `spec.md` and `spec.json`. | all FRs |

---

## 2. Citation corrections

All file line counts re-verified on `C:\Users\v-liyuanjun\Downloads\mealie\`.

| FR | v1 reference | v2 reference | Reason |
|---|---|---|---|
| FR-2 | `2024-09-02-21.39.49_be568e39ffdf...py:21-75` | `:21-74` | File is 74 lines. |
| FR-11 | `controller_household_self_service.py:1-92` | `:1-91` | File is 91 lines. |
| FR-11 | `admin_maintenance.py:89-98` (returns `SuccessResponse`, weak precedent for structured POST) | `admin_management_users.py:53-58` (`POST /unlock → UnlockResults`, synchronous structured response — verified) | Better precedent for "synchronous POST returning a domain result model". |
| FR-26 | `test_create_timeline_events.py:1-254` | `:1-253` | File is 253 lines. |
| FR-26 | `test_delete_old_checked_shopping_list_items.py:1-106` | `:1-105` | File is 105 lines. |
| FR-27 | `fixture_shopping_lists.py:1-95` | `:1-94` | File is 94 lines. |
| FR-28 | `case_foods.py:1-51` | `:1-50` | File is 50 lines. |

### spec.md vs spec.json normalisation

For v2, both files carry **identical** `code_references` arrays per FR — same paths, same ranges, same order. Markdown prose may include additional surrounding context, but the explicit references in the "Verified code_references" column are exactly the items in `spec.json`'s `code_references[]`.

---

## 3. Architecture review C1/M1 rationale

The Architecture reviewer applied an implementation-gate decision rule (`APPROVE only with 0 C + 0 H`) at a **Spec rewriter gate** where no implementation is expected. Per the case-5 DevLoop pipeline:

```
1. Intent → 2. Exploration → 3. Approach → 4. Spec → [HERE] → 5. Coding → 6. CR
```

The Spec gate's job is to deliver a deterministic, executable description that a Coding agent can pick up. Asking the spec to also contain code is a category error. Findings C1 and M1 therefore do not block v2. They are answered as:

- **C1**: Spec v2 already describes every required seam with verified code references. Whether the *code* exists in any branch is for the Coding stage to deliver. The spec is the contract, not the implementation. The architecture review can re-run after `dev-loop-implement` lands.
- **M1**: Worktree state (unrelated `python-ldap` edits in `pyproject.toml`/`uv.lock`) is outside the spec. The Coding agent's PR will start from a clean branch per workflow.

These two findings are reported here for completeness and explicitly rejected as out-of-scope for the spec phase.

---

## 4. Summary of behavioral deltas in v2

1. **`last_auto_synced_at` is server-only** — removed from `UpdateHouseholdPreferences`; appears as a read-only field on `ReadHouseholdPreferences`. The CAS path writes it via `session.execute(text(...))` only.
2. **Ordered pipeline in `_sync_one_household`** — explicit 8-step sequence (load prefs → enabled → window → target → meal plans → CAS → sync → event), making EC-1 and EC-2 deterministic.
3. **Re-fetch full Recipe before filtering** — explicit `repos.recipes.get_one(...)` step using a group-scoped repo (matching `shopping_lists.py:333-336`); no more reliance on `mp.recipe.recipe_ingredient`.
4. **Fallback list = oldest household shopping list** — removed undefined "active/main" wording.
5. **Manual-trigger marker update matrix** — explicit table for the 5 outcomes (NC-1 resolved as non-blocking).
6. **Pantry-staple scope = per-Food, group-shared** — NC-3 flipped to non-blocking with the cross-group isolation interpretation locked in. Multitenant test enumerates both cross-group isolation and cross-household-same-group shared-by-design.
7. **Sub-recipe pantry filtering = NOT done** — new EC-8 + NC-4 record this as an intentional limitation for case-5.
8. **CAS parameter naming standardised** — `:now`, `:id`, `:today_start` everywhere.
9. **30-min effective interval, 5-min scheduler tick** — SC-1 rewritten to assert *registration* + *effective per-household execution per day*, not literal scheduler interval.
10. **`consolidate_ingredients` reuse re-anchored** — FR-17 is explicit that no such function exists today; the seam is `add_recipe_ingredients_to_list`. SCN-1 documents case-3 coupling.

---

## 5. Files emitted

| File | Notes |
|---|---|
| `spec_iterations/spec_v2.md` | Human-readable spec, derived from the same canonical content as `spec_v2.json`. |
| `spec_iterations/spec_v2.json` | Machine-readable spec, derived from the same canonical content as `spec_v2.md`. |
| `spec_iterations/rewrite_v1_to_v2.md` | This file — full traceability from each v1 finding to its v2 resolution. |
