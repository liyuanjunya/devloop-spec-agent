# Executability Review (v1)

## Verdict: NEEDS_REFINE

The spec is not fully executable as written. All cited existing paths under `C:\Users\v-liyuanjun\Downloads\mealie\` exist, but several line ranges are off by one, multiple markdown/JSON `code_references` differ, and the central scheduler/pantry implementation seam refers to `mp.recipe.recipe_ingredient` even though `RepositoryMeals.get_today()` returns `ReadPlanEntry.recipe: RecipeSummary | None`, which does not expose `recipe_ingredient`. A coding agent would need to infer an uncited re-fetch/full-recipe loading strategy.

---

## Scope checks

| Check | Result |
|---|---|
| All cited paths real? | ✅ Pass. Every cited existing Mealie path exists. |
| All line ranges accurate and cited symbol in range? | ❌ Fail. See wrong/imprecise citations. |
| `spec.md` / `spec.json` `code_references` identical for each FR? | ❌ Fail for FR-3, FR-5, FR-10, FR-11, FR-14, FR-16, FR-17, FR-18, FR-20, FR-23, FR-25. |
| TBD / `or equivalent` / `if needed` phrases? | ❌ One `or equivalent` in SC-12 (`frontend/app/lib/api/types/household.ts (or equivalent)`). No `TBD` or `if needed` matches. |
| Scheduler-task implementation seam concrete enough? | ⚠️ Partially. File/function/helper/register seam is concrete, but recipe ingredient loading and result-count semantics need refinement. |
| Pantry filter implementation pin-pointed? | ⚠️ Partially. FR-17 names the filter and service seam, but targets a schema object that lacks `recipe_ingredient` and does not address nested/sub-recipe pantry filtering. |
| `last_auto_synced_at` storage layer concrete? | ⚠️ Storage/CAS location is concrete, but schema/route requirements expose it through `UpdateHouseholdPreferences`, conflicting with SCN-3’s server-owned marker warning. |

---

## Wrong/imprecise citations

1. **FR-2** — `mealie/alembic/versions/2024-09-02-21.39.49_be568e39ffdf_added_household_recipe_lock_setting_and_.py:21-75` is out of range; file ends at line 74. Suggested range: `21-74`.
2. **FR-11** — `mealie/routes/households/controller_household_self_service.py:1-92` is out of range; file ends at line 91. Suggested range: `1-91`.
3. **FR-11** — `mealie/routes/admin/admin_maintenance.py:89-98` is imprecise/wrong for “sync POST returning structured result, 200 not 202”; lines 89-98 are `POST /clean/images` returning `SuccessResponse`, not a structured domain result precedent.
4. **FR-26** — `tests/unit_tests/services_tests/scheduler/tasks/test_create_timeline_events.py:1-254` is out of range; file ends at line 253. Suggested range: `1-253`.
5. **FR-26** — `tests/unit_tests/services_tests/scheduler/tasks/test_delete_old_checked_shopping_list_items.py:1-106` is out of range; file ends at line 105. Suggested range: `1-105`.
6. **FR-27** — `tests/fixtures/fixture_shopping_lists.py:1-95` is out of range; file ends at line 94. Suggested range: `1-94`.
7. **FR-28** — `tests/multitenant_tests/case_foods.py:1-51` is out of range; file ends at line 50. Suggested range: `1-50`.
8. **FR-17 / scheduler seam** — the cited shopping-list service ranges are accurate, but the requirement’s source object is not: `RepositoryMeals.get_today()` (`repository_meals.py:11-22`) returns `ReadPlanEntry`, whose `recipe` field is `RecipeSummary | None` (`new_meal.py:62-65`); `RecipeSummary` does not include `recipe_ingredient` (`recipe.py:116-175`). The spec must cite and require a full-recipe load path before filtering.
9. **FR-19** — `shopping_lists.py:377-384` accurately contains `recipe_references`, but only after `get_shopping_list_items_from_recipe` is reached. Because FR-17’s filtered ingredient source is under-specified, this dependency is fragile.

---

## `spec.md` vs `spec.json` `code_references`

Not identical. Differences include:

- FR-3/FR-5: JSON adds explicit single-line refs (`ingredient.py:192`, `events.py:32`) while markdown embeds only prose identifiers (`on_hand`, `mealplan_entry_updated`).
- FR-10: JSON includes `controller_household_self_service.py:73-77`; markdown has it only as prose `L73-77` outside the backticked reference list.
- FR-14/FR-17/FR-18/FR-23: markdown collapses multiple ranges into prose or backticked identifiers; JSON has split path:range entries.
- FR-25: markdown uses absolute `C:\Users\...\.github\copilot-instructions.md`; JSON uses relative `.github/copilot-instructions.md`.

Normalize every FR to the same ordered path/range list in both files.

---

## Executability concerns

### Critical

- **EXEC-C-001 — Auto-sync cannot literally filter `mp.recipe.recipe_ingredient`.** `ReadPlanEntry.recipe` is `RecipeSummary`, not full `Recipe`. Add an explicit implementation step: collect `recipe_id`s from meal plans, fetch full recipes through the group/household-scoped recipe repository (or change/cite loader/schema accordingly), then filter `Recipe.recipe_ingredient`.

### High

- **EXEC-H-001 — `last_auto_synced_at` is both client-updateable and server-owned.** FR-7/FR-10 say the PUT preferences body accepts `last_auto_synced_at`; SCN-3 says the route should not write it. Make it server-only: omit it from `UpdateHouseholdPreferences` or explicitly exclude it before `repos.household_preferences.update()`.
- **EXEC-H-002 — Default target says “first active main list” but cites only `page_all(... order_by="created_at")`.** Current cited repo range has no active/main filter. Either remove “active main” or define/cite the exact active/main predicate.

### Medium

- **EXEC-M-001 — Added count semantics are not pinned.** Specify whether `added_count` counts only `created_items`, both created and updated/merged items, or ingredient rows submitted to the service.
- **EXEC-M-002 — Pantry filtering does not cover nested/sub-recipes.** `get_shopping_list_items_from_recipe()` recursively expands referenced recipes. If pantry staples inside sub-recipes must be skipped, specify a recursive filter or post-expansion filtering strategy.
- **EXEC-M-003 — Migration chain is underspecified for three new migrations.** SC-8 says subsequent migrations chain, but FR-2/4/6 individually describe independent migrations. Add exact new down-revision order.

---

## Verified key citations

- `app.py:134-136`, `scheduler_service.py:15-17,77-81`, and `scheduler_registry.py:41-48` verify the existing 5-minute scheduler bucket and registration seam.
- `shopping_lists.py:45-71,73-128,154-223,323-455` verifies the existing merge/add-recipe seam.
- `event_bus_service.py:66-96` verifies why explicit `household_id` avoids fan-out.
- `preferences.py:16-44` and `_model_utils/datetime.py:20-50` verify the intended storage table and naive-UTC convention.
