# Consolidated Exploration — Case 5 (Meal Plan → Shopping List Auto-Sync)

Aggregates the data / api / test / history perspectives into one deduplicated artifact set. All line ranges have been re-verified against `C:\Users\v-liyuanjun\Downloads\mealie\` immediately before publishing.

## Summary

Case-5 introduces an opt-in per-household scheduled job that, once per household-local day, appends today's MealPlan recipe ingredients (with pantry-staple filter) to the household's configured shopping list and dispatches a `MealPlanAutoSyncedToShopping` event. The implementation reuses `repos.meals.get_today` (passing per-household `ZoneInfo`), `ShoppingListService.add_recipe_ingredients_to_list`, `EventBusService.dispatch`, and `SchedulerRegistry.register_minutely` with an internal 30-min window gate. It adds 4 new `HouseholdPreferences` columns + a `Food.is_pantry_staple` flag + a new `EventTypes` member + 3 `en-US` i18n keys, with multi-replica safety via `last_auto_synced_at` CAS.

## Critical consolidated artifacts (deduped across perspectives)

| Path | Symbols | Line ranges | Why critical |
|---|---|---|---|
| `mealie/db/models/household/preferences.py` | `HouseholdPreferencesModel` | 16-44 | Add 5 new columns (`auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, `auto_sync_run_time`, `last_auto_synced_at`, `timezone`); `@auto_init` at line 42 means no constructor edits. |
| `mealie/schema/household/household_preferences.py` | `UpdateHouseholdPreferences`, `ReadHouseholdPreferences` | 10-40 | Propagates new fields to Create/Save/Read via subclassing. `loader_options` at 36-40 already joins `Household.group_id`. |
| `mealie/db/models/recipe/ingredient.py` | `IngredientFoodModel` | 153-192 | Add `is_pantry_staple: bool` column. Deprecated `on_hand` at line 192 is precedent for shape; PR #4616 moved per-household variant to `households_to_ingredient_foods` — see Conflict #1. |
| `mealie/db/models/household/shopping_list.py` | `ShoppingListItem`, `ShoppingList`, `ShoppingListItemRecipeReference` | 26-98, 147-181 | Target tables. `food_id` (78), `unit_id` (75), `checked` (65), `recipe_references` (87-89); household scoping is via `association_proxy` (60, 153). |
| `mealie/db/models/_model_utils/datetime.py` | `NaiveDateTime`, `get_utc_now` | 6-50 | `last_auto_synced_at` MUST use `NaiveDateTime`. Docstring at 22-27 mandates UTC-naive everywhere. |
| `mealie/repos/repository_meals.py` | `RepositoryMeals.get_today` | 11-21 | Reuse as-is with `tz=ZoneInfo(household_tz)`; raises on missing `household_id` (line 14) so repo must be household-scoped. |
| `mealie/routes/households/controller_household_self_service.py` | `update_household_preferences`, `get_household_preferences`, `HouseholdSelfServiceController` | 54-62 | Existing PUT `/preferences` at line 58 uses `can_manage_household()` (line 60); new PATCH route + new run-now route extend this controller. |
| `mealie/services/scheduler/scheduler_service.py` | `SchedulerService`, `run_minutely` | 15-17, 20-81 | `MINUTES_5=5` at line 16: `run_minutely` actually fires every 5 minutes (line 77). No 30-minute bucket — case-5 must reuse `register_minutely` + internal gate. |
| `mealie/services/scheduler/scheduler_registry.py` | `SchedulerRegistry`, `register_minutely` | 8-48 | `_minutely` callable list (15) + `register_minutely` (41-43); wiring happens in `mealie/app.py:134-136`. |
| `mealie/services/scheduler/tasks/__init__.py` | (re-export module) | 1-28 | New `auto_sync_shopping_to_meal_plan` added to imports + `__all__`. Docstring at 21-28 warns scheduler is single-worker → motivates CAS. |
| `mealie/app.py` | `start_scheduler` | 124-144 | Where the task is registered: add `tasks.auto_sync_shopping_to_meal_plan` to `SchedulerRegistry.register_minutely(...)` at lines 134-136. |
| `mealie/services/event_bus_service/event_types.py` | `EventTypes`, `EventDocumentDataBase`, `EventShoppingListData` | 13-60, 88-132 | New `meal_plan_auto_synced_to_shopping` enum value (13-60); paired migration required (warning at 14-22). New `EventMealPlanAutoSyncedToShoppingData(EventDocumentDataBase)` payload (mirror 130-132). |
| `mealie/services/event_bus_service/event_bus_service.py` | `EventBusService.dispatch` | 42-96 | Only public publish entrypoint. Task constructs `EventBusService(session=session)` and dispatches with explicit `household_id`. |
| `mealie/services/household_services/shopping_lists.py` | `ShoppingListService.can_merge`, `merge_items`, `add_recipe_ingredients_to_list` | 34-71, 73-128, 413-455 | The actual reusable merge surface (spec's `consolidate_ingredients` does not exist by that name). `add_recipe_ingredients_to_list` (413-455) is the highest-level entry — case-5 calls per mealplan entry, after pantry-staple filter. |
| `mealie/db/models/household/mealplan.py` | `GroupMealPlan` | 55-77 | Source of today's recipes. `household_id` is association_proxy through user (65); `repos.meals.get_today` already joins correctly. |
| `mealie/routes/_base/checks.py` | `OperationChecks.can_manage_household` | 6-41 | Household-admin gate (23-26) raises 403; both new routes call `self.checks.can_manage_household()`. |
| `mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py` | `upgrade`, `downgrade` | 20-47 | Most recent precedent for adding a boolean to `household_preferences`. Pattern: `op.batch_alter_table('household_preferences')` + `add_column(server_default=...)`. |

## Relevant supporting artifacts

| Path | Why relevant |
|---|---|
| `mealie/services/scheduler/tasks/create_timeline_events.py` (25-134) | Closest template task: group→household walk, household-scoped repos, `repos.meals.get_today`, dispatch events. Case-5 mirrors structure but replaces `tzlocal()` (36) with per-household `ZoneInfo`. |
| `mealie/routes/_base/base_controllers.py` (132-215) | `BaseUserController` (132-172) supplies scoped repos / group_id / household_id. New controllers inherit this. |
| `mealie/repos/repository_factory.py` (105-301) | Repo factory contract. `ingredient_foods` (139-141) is group-scoped only — confirms `is_pantry_staple` is group-scoped when on `IngredientFoodModel`. `household_preferences` (244-253) is the CAS repo for `last_auto_synced_at`. |
| `mealie/db/models/household/household.py` (29-98) | Household has no `timezone` column today (gap); `preferences` cascade (43-49) guarantees a row per Household. |
| `mealie/routes/unit_and_foods/foods.py` (21-78) | Existing food CRUD; `update_one` (69-73) reads `CreateIngredientFood`. Once `is_pantry_staple` is added to the schema, this route accepts it automatically. |
| `mealie/lang/messages/en-US.json` (1-80) | Add new top-level `"auto-sync": {...}` block with the 3 new keys. en-US ONLY (Crowdin-managed otherwise). |

## Cross-perspective conflicts (≤5, prioritized)

### Conflict #1 — `is_pantry_staple` scope (data vs history)
**Disagreement**: data perspective accepts spec-literal column on `IngredientFoodModel` (group-scoped); history flags this as repeating the `on_hand` mistake corrected by PR #4616 (commit `e9892aba`), which moved `on_hand` from a column to `households_to_ingredient_foods` because foods are group-scoped but the flag was per-household. The spec test "cross-household pantry-staple does not interfere" is satisfied trivially by group-scoping iff household-A and household-B in the same group are not expected to differ.
**Resolution**: escalate as **NC-001** (BlockingDecision). Default: spec-literal group-scoped column (matches spec wording, simpler migration). If reviewer rejects, fall back to per-household association table.

### Conflict #2 — Scheduler 30-min cadence (api vs test)
**Disagreement**: api proposes adding a new `MINUTES_30 = 30` bucket + `register_half_hourly`; test prefers `register_minutely` + internal window gating (matches `post_webhooks.py:21-35` `last_ran` precedent).
**Resolution**: adopt `register_minutely` + internal gate. Honors the explicit reuse constraint in the input ("must reuse existing scheduler abstractions"), keeps blast radius small, and matches the existing `post_webhooks` precedent for window-based filtering.

### Conflict #3 — Per-household timezone storage default (data vs test)
**Disagreement**: data says fall back to server-local then UTC; test says default to UTC explicitly to keep behavior deterministic across deployments.
**Resolution**: add `HouseholdPreferencesModel.timezone` as nullable `String` (IANA name). Runtime fallback chain is **`ZoneInfo(prefs.timezone)` if set, else `ZoneInfo("UTC")`** — server-local is intentionally excluded.

### Conflict #4 — PATCH vs PUT for `/api/households/preferences` (api vs history)
**Disagreement**: api notes only PUT exists today and proposes adding a real PATCH; history notes the project actively removes boolean prefs flags (#5684) and would scrutinize new add-only PATCH semantics.
**Resolution**: extend `UpdateHouseholdPreferences` with the new fields (mandatory anyway). **Also** add `PATCH /api/households/preferences` accepting a partial body with `exclude_unset` semantics, so frontend can toggle `auto_sync_meal_plan_to_shopping` without round-tripping the full prefs object. Old PUT remains for backward compat.

### Conflict #5 — `EventTypes` enum migration coupling (api vs history)
**Disagreement**: api flags the docstring requirement (`event_types.py:14-22`) that new enum members need a matching boolean column on the subscriber notifier-options table; history confirms via PR #7015 (`e52a887e` / migration `cdc93edaf73d`) this is the established pattern. Risk: easy to miss, breaks fresh-DB integration tests but passes unit tests.
**Resolution**: ship ONE alembic migration combining (a) `household_preferences` column additions, (b) `ingredient_foods.is_pantry_staple` column, AND (c) `group_events_notifier_options` boolean column for the new event. Single migration keeps upgrade/downgrade deterministic.

## Consolidated conventions

- Mealie uses naive UTC datetimes via `NaiveDateTime` TypeDecorator; never use `sa.DateTime(timezone=True)`.
- Repositories are group/household scoped through `AllRepositories` factory; the auto-sync task constructs household-scoped repos per household via `get_repositories(session, group_id=g, household_id=h)`.
- Schemas under `mealie/schema/` use `UpdateXxx / CreateXxx / SaveXxx / ReadXxx` suffixes; field added on Update propagates via subclassing.
- i18n: modify only `en-US.json`; other locales are managed by Crowdin.
- After schema changes run `task dev:generate` to regenerate TS types + schema exports.
- Use `task py:migrate -- "description"` to scaffold alembic migrations; wrap with `op.batch_alter_table` for SQLite + PostgreSQL compatibility.
- Scheduler is in-process single-worker; tasks must self-gate via DB CAS (`UPDATE WHERE last_auto_synced_at < today_local`) for multi-replica safety.
- Event bus dispatch from a scheduled task uses `EventBusService(session=session)` with `DEFAULT_INTEGRATION_ID` and an explicit `household_id` (no fan-out).
- Adding a new `EventTypes` enum value requires a paired migration adding a boolean column to `group_events_notifier_options`.
- Controllers inherit `BaseUserController` (or `BaseAdminController`); household-admin checks use `self.checks.can_manage_household()`.
