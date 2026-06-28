# Completeness Review v1 — Case 5 LIVE RUN v1

## Verdict

**FAIL — incomplete against input §1-§5.** The spec covers some core seams, but multiple required behaviours are missing, renamed, or contradicted. Per the completeness gate, missing §1-§5 requirements are **Critical**.

## Summary

- Input sections reviewed: §1 Household configuration, §2 scheduler/aggregation/event, §3 manual trigger, §4 cross-domain support, §5 tests.
- Overall coverage: **partial, with critical gaps**.
- Critical findings: **9**.
- Major findings: **3**.

## CRITICAL findings

### C1 — §1 required household preference fields are incomplete and renamed

Input requires exactly three user-facing fields: `auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, and `auto_sync_run_time` (`input.md:17-23`). The spec instead defines `auto_sync_meal_plan_to_shopping_list`, target id, `auto_sync_pantry_filter_enabled`, `last_auto_synced_at`, and `timezone` (`spec.md:160-170`, `spec.md:256-257`). `auto_sync_run_time` is absent, so PATCH support and migration coverage are for the wrong shape.

**Required fix:** Add `auto_sync_run_time: str` with HH:MM validation/default `"00:00"`, align the enable field name with input or explicitly alias it, and include these fields in schema, PATCH, GET/PUT compatibility, and migration requirements.

### C2 — §2 scheduler cadence and run-time window do not match the input

Input requires the task to run every 30 minutes and trigger only inside the household-local `auto_sync_run_time` 30-minute window (`input.md:30-38`). The spec registers via `SchedulerRegistry.register_minutely` / `MINUTES_5` and gates around local midnight / `last_auto_synced_at`, not a configurable HH:MM (`spec.md:178-188`, `spec.md:231-232`).

**Required fix:** Require a 30-minute scheduler cadence or a repository-supported equivalent with explicit 30-minute semantics, and compute the eligible window from `auto_sync_run_time` in the household timezone.

### C3 — §2 pantry staple filter is made optional, contradicting the required behaviour

Input says any ingredient whose `food.is_pantry_staple = true` is skipped (`input.md:41-44`). The spec adds an extra `auto_sync_pantry_filter_enabled` preference and filters only when that flag is true (`spec.md:160`, `spec.md:190-195`). That permits pantry staples to be synced by default.

**Required fix:** Remove the extra gating flag or make pantry-staple filtering unconditional for auto-sync.

### C4 — §2 required `consolidate_ingredients` reuse is not cited as the shared function

Input explicitly requires reusing existing `consolidate_ingredients` (`input.md:41-43`). The spec cites `ShoppingListService.add_recipe_ingredients_to_list`, `get_shopping_list_items_from_recipe`, `bulk_create_items`, and `can_merge`, but never requires or cites a shared function named `consolidate_ingredients` (`spec.md:190-198`).

**Required fix:** Cite and require the shared consolidation function, or explicitly document the verified canonical equivalent seam and add a test proving `(food_id, unit_id)` consolidation semantics.

### C5 — §3 manual trigger route and response shape are wrong / incomplete

Input requires `POST /api/households/preferences/auto-sync-shopping/run-now`, admin-only, returning `{ added_count, skipped_pantry_count, target_list_id, run_at }`, bypassing daily idempotency while updating it (`input.md:48-53`). The spec uses `/api/households/preferences/auto-sync/run-now`, returns a vague localized success payload, and does not clearly require bypassing `last_auto_synced_at` (`spec.md:77-82`, `spec.md:199-200`).

**Required fix:** Use the required route path, require household-admin authorization, define the exact count-summary response, and state that run-now bypasses same-day skip but updates `last_auto_synced_at`.

### C6 — §2 event bus event type and safe payload are missing

Input requires dispatching `MealPlanAutoSyncedToShopping` with safe payload fields `household_id`, `shopping_list_id`, `added_item_count`, and `skipped_pantry_count` (`input.md:45-47`). The spec dispatches existing `EventTypes.shopping_list_updated` with `EventShoppingListData` carrying only `shopping_list_id` as document data (`spec.md:96-107`, `spec.md:202-204`, `spec.md:261-264`).

**Required fix:** Add the new event type/payload or explicitly require a safe payload extension containing the four required fields and no recipe/ingredient/user-sensitive data.

### C7 — §4 i18n keys do not match the requested keys

Input requires `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, and `auto-sync.already-synced-today` (`input.md:55-59`). The spec adds `mealplan.auto-sync.success`, `mealplan.auto-sync.no-active-meal-plan`, and `mealplan.auto-sync.target-shopping-list-not-found` (`spec.md:205-207`, `spec.md:249-250`). This misses `already-synced-today` and renames the other two.

**Required fix:** Add the exact three required keys or document an explicit key-namespace mapping while preserving all three required semantic messages.

### C8 — §5 multitenant pantry-staple isolation is contradicted

Input requires tests proving cross-household pantry-staple markings do not affect each other (`input.md:72-75`). The spec defaults `IngredientFoodModel.is_pantry_staple` to a group-scoped Boolean and explicitly says per-household semantics are only an unresolved clarification (`spec.md:13-21`, `spec.md:163-165`, `spec.md:288-289`). That cannot satisfy the required isolation rule.

**Required fix:** Model pantry-staple state per household, or keep NC-001 blocking with no default implementation that violates the input.

### C9 — §5 required test matrix is incomplete

Input requires unit coverage for merge, pantry, timezone window, and idempotency; integration coverage for run-now, disabled scheduled skip, no-meal-plan 204/0, pantry; multitenant coverage for same-household, cross-group, and pantry-staple isolation; plus scheduler-mock coverage (`input.md:60-75`). The spec lists broad tests but omits disabled scheduled skip, 204/0-added no-meal-plan behaviour, cross-group isolation, pantry-staple isolation, and scheduler-mock/30-minute interval assertions (`spec.md:217-222`).

**Required fix:** Add explicit tests for each input bullet, including scheduler registration/mock timing and exact manual-trigger response counts.

## MAJOR findings

### M1 — §2 recipe references may not link back to meal-plan entries

Input asks appended items to mark `recipe_references` linking back to meal plan / recipe (`input.md:43-45`). The spec relies on existing recipe references created from recipe id only (`spec.md:190-191`, `spec.md:436-452` cited by the spec). It does not say whether meal-plan-entry identity is persisted or impossible in the current model.

**Suggested fix:** Clarify whether recipe-only references satisfy the requirement, or add a meal-plan-entry reference/extras strategy.

### M2 — §2 append strategy lacks an explicit unchecked accumulation test

The spec notes checked rows are not merged (`spec.md:196-198`, `spec.md:276-277`), but it does not explicitly require that existing unchecked same `(food_id, unit_id)` rows accumulate quantity rather than creating duplicates.

**Suggested fix:** Add an FR/SC/test for unchecked same-food/unit accumulation and recipe-reference merge preservation.

### M3 — §4 Food admin route/repo support is under-specified

Input requires `Food.is_pantry_staple` migration + schema + repo + admin/foods routes (`input.md:55-58`). The spec covers model/schema/migration and existing food create/update paths, but says no repository method is required and uses `can_organize` rather than an admin route/permission (`spec.md:211-224`).

**Suggested fix:** State the intended permission explicitly and add repository/schema route coverage for create, read, update, and admin/foods access.

## Covered requirements

- PATCH route support is present in principle (`spec.md:172-174`), but for the wrong field set.
- Daily idempotency / multi-replica CAS is covered (`spec.md:187-188`, `spec.md:273-274`).
- Timezone awareness using `ZoneInfo` is covered generally (`spec.md:181-185`, `spec.md:272-275`), but DST-specific tests are only a self-concern (`spec.md:301-303`).
- Target-list fallback is covered with a clarification on ordering (`spec.md:23-31`, `spec.md:214-215`).
- Alembic migration coverage is present for the spec's chosen columns (`spec.md:211-213`).

## Recommended spec edits before implementation

1. Restore the exact §1 fields, especially `auto_sync_run_time`.
2. Define true 30-minute scheduling and run-time window logic.
3. Make pantry-staple filtering unconditional and per-household isolated.
4. Require the exact manual route, response, and idempotency bypass behaviour.
5. Add the required event type/payload and exact i18n keys.
6. Expand tests to cover every §5 bullet, including scheduler mock and cross-group isolation.
