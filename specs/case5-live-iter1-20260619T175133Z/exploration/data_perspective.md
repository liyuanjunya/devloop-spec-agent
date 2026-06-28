# Data Perspective — Case 5 Live

Scope: data-model artifacts (DB models, Pydantic schemas, repositories, migrations,
event-payload types) that case-5 must read, extend, or reuse. All line ranges were
verified by reading the cited files directly.

---

## Critical artifacts

### `mealie/db/models/household/preferences.py` — `HouseholdPreferencesModel`
- **Path**: `mealie/db/models/household/preferences.py`
- **Symbols**: `HouseholdPreferencesModel` (class), `household_id` FK, `private_household`, `show_announcements`, `lock_recipe_edits_from_other_households`, `first_day_of_week`, `recipe_*` defaults
- **Line ranges**: full file 1–45; class body 16–44; FK 20–22; existing bool columns 26–40
- **Importance**: critical
- **Reason**: This is exactly the table case-5 must extend with `auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, `auto_sync_run_time`, plus the **new** `last_auto_synced_at` column for cross-process idempotency. There is no `timezone` here today — that gap drives sub-feature #1.

### `mealie/schema/household/household_preferences.py` — Pydantic preference DTOs
- **Path**: `mealie/schema/household/household_preferences.py`
- **Symbols**: `UpdateHouseholdPreferences` (10–22), `CreateHouseholdPreferences` (25), `SaveHouseholdPreferences` (28–29), `ReadHouseholdPreferences` (32–40)
- **Line ranges**: full file 1–41
- **Importance**: critical
- **Reason**: All four schema variants must gain the new `auto_sync_*` fields (and `last_auto_synced_at` on Read) with the same defaults as the model. The `loader_options` (lines 36–40) already joins `Household.group_id`; adding a JSON column for timezone/run-time does not need additional loaders.

### `mealie/db/models/household/mealplan.py` — `GroupMealPlan`
- **Path**: `mealie/db/models/household/mealplan.py`
- **Symbols**: `GroupMealPlan` (55–77), `date` (58), `entry_type` (59), `recipe_id` FK (70), `recipe` relationship (71–73), `household_id` AssociationProxy via `user` (65–66), `group_id` (63)
- **Line ranges**: full file 1–77; `GroupMealPlanRules` 30–52
- **Importance**: critical
- **Reason**: The "today's meal plan entries" query the scheduler must run. **Note**: `household_id` is an **association proxy through `user`** — NOT a direct column. Filtering by household therefore requires joining `User`, which `RepositoryMeals.get_today` already encapsulates.

### `mealie/repos/repository_meals.py` — `RepositoryMeals.get_today`
- **Path**: `mealie/repos/repository_meals.py`
- **Symbols**: `RepositoryMeals` (11), `get_today(tz=UTC)` (12–21), `get_meals_by_date_range` (23–33)
- **Line ranges**: full file 1–33
- **Importance**: critical
- **Reason**: Already implements household-scoped "today" with timezone-aware `datetime.now(tz=tz).date()` (line 16). The case-5 scheduler should call `repos.meals.get_today(tz=ZoneInfo(household.preferences.timezone or "UTC"))` rather than reinvent the date filter. Note line 13–14 raises if `household_id` is not set — repo MUST be constructed with `household_id`.

### `mealie/db/models/household/shopping_list.py` — `ShoppingList*` models
- **Path**: `mealie/db/models/household/shopping_list.py`
- **Symbols**: `ShoppingListItemRecipeReference` (26–48; `shopping_list_item_id`, `recipe_id`, `recipe_quantity`, `recipe_scale`, `recipe_note`), `ShoppingListItem` (51–98; `food_id` 78, `unit_id` 75, `quantity` 67, `checked` 65, `recipe_references` 87–89, `household_id` AssocProxy 60), `ShoppingListRecipeReference` (101–120), `ShoppingList` (147–181; `recipe_references` 166–168, `group_id` 151, `household_id` AssocProxy 153–154)
- **Line ranges**: full file 1–238 (event listeners 204–238)
- **Importance**: critical
- **Reason**: Defines the target table for sync output and the `recipe_references` linking pattern case-5 requires. `(food_id, unit_id)` are the dedup keys used by `can_merge`. **Household scoping on items/lists is via association_proxy through `user`** (lines 60, 153–154), so a list's tenancy follows its owning user — this is the multi-tenant boundary tests must validate.

### `mealie/services/household_services/shopping_lists.py` — `ShoppingListService` (the de-facto "consolidate_ingredients")
- **Path**: `mealie/services/household_services/shopping_lists.py`
- **Symbols**:
  - `ShoppingListService` (34)
  - `can_merge(item1, item2)` (45–71) — `(food_id, unit_id)` + unit-conversion compatibility
  - `merge_items(from_item, to_item)` (73–128) — quantity/unit merge, notes, recipe-refs
  - `bulk_create_items(create_items, auto_find_labels=True)` (154–223) — **this is the "consolidate + append" entry point**
  - `get_shopping_list_items_from_recipe(list_id, recipe_id, scale, recipe_ingredients)` (323–411)
  - `add_recipe_ingredients_to_list(list_id, recipe_items)` (413–455) — **the highest-level reuse point for case-5**
- **Line ranges**: full file 1–~548
- **Importance**: critical
- **Reason**: The spec mentions `consolidate_ingredients` by name, but no such function exists. The closest reusable surface is `bulk_create_items` (consolidates within batch + merges into existing un-checked items by `(food_id, unit_id)`) and `add_recipe_ingredients_to_list` (full "add a recipe's ingredients into a list, updating list-level recipe refs"). Case-5 sub-feature #2 step 6 ("if same `(food_id, unit_id)` and not checked, accumulate quantity, else create") is **exactly** what `bulk_create_items` already does (lines 162–223). The auto-sync task should iterate today's mealplan entries and call `add_recipe_ingredients_to_list` once per entry — the only new logic is **pantry-staple filtering** before the call.

### `mealie/db/models/recipe/ingredient.py` — `IngredientFoodModel`
- **Path**: `mealie/db/models/recipe/ingredient.py`
- **Symbols**: `IngredientFoodModel` (153–260), columns `name` (164), `plural_name` (165), `label_id` (178), `name_normalized` (182), **deprecated `on_hand` Bool** (192), `households_to_ingredient_foods` M2M table (21–27)
- **Line ranges**: file 1–~490; food class 153–260
- **Importance**: critical
- **Reason**: Case-5 #1/#4 require adding `is_pantry_staple: bool` here (group-scoped via `group_id` 158). **Important precedent**: `on_hand` (line 192) is marked `# Deprecated` because per-household on-hand tracking moved to the `households_to_ingredient_foods` join table (21–27). The same architectural question applies to `is_pantry_staple` — but the spec explicitly says "global on foods table, default false", so a new boolean column on `ingredient_foods` is consistent with the migration `32d69327997b` that originally added `on_hand`.

### `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py`
- **Path**: `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py`
- **Symbols**: `is_postgres()` (20–21), `upgrade()` (24–41), `downgrade()` (44–46)
- **Line ranges**: full file 1–46
- **Importance**: critical
- **Reason**: Direct template for the case-5 `is_pantry_staple` migration: `batch_alter_table("ingredient_foods")` → `add_column(nullable=True)` → backfill via dialect-aware SQL (`FALSE` vs `0`) → `alter_column(nullable=False)`. Despite its filename literally being "add_staple_flag_to_foods", the migration adds **`on_hand`**, not a pantry flag — so the case-5 column name `is_pantry_staple` does not collide.

### `mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py`
- **Path**: `mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py`
- **Symbols**: `upgrade` (20–32) adds `show_announcements` to `household_preferences` (25–26)
- **Line ranges**: full file 1–48
- **Importance**: critical
- **Reason**: The most recent migration that adds a boolean column to `household_preferences` using `op.batch_alter_table` + `server_default=sa.true()` (line 26). This is the exact pattern for adding `auto_sync_meal_plan_to_shopping` (server_default `false`), `auto_sync_target_shopping_list_id` (nullable GUID FK), `auto_sync_run_time` (String, server_default `"00:00"`), and `last_auto_synced_at` (NaiveDateTime, nullable).

### `mealie/services/scheduler/scheduler_service.py` + `scheduler_registry.py`
- **Path A**: `mealie/services/scheduler/scheduler_service.py`
- **Symbols**: `SchedulerService.start` (21–27), `schedule_daily` (30–53), `run_daily` (63–67), `run_hourly` (70–74), `run_minutely` (77–81), constants `MINUTES_DAY=1440`, `MINUTES_5=5`, `MINUTES_HOUR=60` (15–17)
- **Path B**: `mealie/services/scheduler/scheduler_registry.py`
- **Symbols**: `SchedulerRegistry._daily/_hourly/_minutely` (13–15), `register_daily/hourly/minutely` (23–48)
- **Line ranges**: scheduler_service 1–82; scheduler_registry 1–60
- **Importance**: critical
- **Reason**: **There is no 30-minute bucket.** `run_minutely` actually fires every 5 minutes (line 16: `MINUTES_5=5`, line 77 decorator). The case-5 task must either (a) register as `register_minutely` and gate itself via a `last_auto_synced_at`-style timestamp + an "is current 30-min window aligned with run_time" check, or (b) add a new `MINUTES_30` bucket. Option (a) reuses the existing abstraction (per spec constraint "must reuse `mealie/services/scheduler/` abstractions"). Tasks are registered in `mealie/app.py` line 125–142.

### `mealie/services/scheduler/tasks/create_timeline_events.py` — reference scheduled task
- **Path**: `mealie/services/scheduler/tasks/create_timeline_events.py`
- **Symbols**: `_create_mealplan_timeline_events_for_household` (25–114), `_create_mealplan_timeline_events_for_group` (117–122), `create_mealplan_timeline_events` (125–134), uses `repos.meals.get_today(tz=local_tz)` (37)
- **Line ranges**: full file 1–135
- **Importance**: critical
- **Reason**: Closest existing precedent for the case-5 auto-sync task. Already iterates groups → households (lines 128–134, 117–122), constructs household-scoped repos (28), uses `repos.meals.get_today` (37), and dispatches `EventBusService` events (108–114). Case-5's `auto_sync_shopping.py` should mirror this structure. **Note**: it uses `tzlocal()` (server-local, line 36) — case-5 must replace this with each household's own timezone (which does not exist as a field yet — see "gaps").

### `mealie/services/event_bus_service/event_types.py` — `EventTypes` enum + payload types
- **Path**: `mealie/services/event_bus_service/event_types.py`
- **Symbols**: `EventTypes` enum (13–60), `EventDocumentType` enum (63–77), `EventOperation` (80–85), `EventDocumentDataBase` (88–91), `EventShoppingListData` (130–132), `EventMealplanData` (94–100), `EventBusMessage` (179–191), `Event` (194+)
- **Line ranges**: full file 1–~210
- **Importance**: critical
- **Reason**: Case-5 step #7 requires a new event `MealPlanAutoSyncedToShopping`. The enum docstring (14–22) explicitly warns: **"any changes made here must also be reflected in the database (and likely requires a database migration)"** because each event type is a subscriber-config column. This is a non-obvious migration the case-5 design must include. The new payload type would subclass `EventDocumentDataBase` with `household_id`, `shopping_list_id`, `added_item_count`, `skipped_pantry_count`.

---

## Relevant artifacts

### `mealie/db/models/household/household.py` — `Household`
- **Path**: `mealie/db/models/household/household.py`
- **Symbols**: `Household` (29–97), `preferences` relationship (43–49), `group_id` FK (51)
- **Line ranges**: full file 1–98
- **Importance**: relevant
- **Reason**: Confirms `preferences` is `back_populates="household", uselist=False, cascade="all, delete-orphan"` (45–48), so a Household always has exactly one HouseholdPreferences row — the scheduler can safely load `household.preferences.auto_sync_meal_plan_to_shopping` without nullability concern. There is NO `timezone` column here either — gap noted below.

### `mealie/schema/meal_plan/new_meal.py` — `ReadPlanEntry`
- **Path**: `mealie/schema/meal_plan/new_meal.py`
- **Symbols**: `PlanEntryType` (19–26), `CreatePlanEntry` (34–47), `ReadPlanEntry` (62–74; includes `recipe: RecipeSummary | None` and `household_id: UUID`), `loader_options` (67–74) eagerly loads recipe.recipe_category/tags/tools
- **Line ranges**: full file 1–78
- **Importance**: relevant
- **Reason**: The DTO `RepositoryMeals.get_today` returns. The `recipe` field (64) is the only entry point to the recipe's ingredients — `recipe_id` only is insufficient unless the task re-fetches via `repos.recipes`. Note that `RecipeSummary` may not include the full `recipe_ingredient` list, so the scheduler likely needs to call `repos.recipes.get_one(plan_entry.recipe_id)` for full ingredients (mirroring `ShoppingListService.get_shopping_list_items_from_recipe` line 336).

### `mealie/schema/recipe/recipe_ingredient.py` — `IngredientFood` DTOs
- **Path**: `mealie/schema/recipe/recipe_ingredient.py`
- **Symbols**: `UnitFoodBase` (60–81), `CreateIngredientFood` (92–95), `SaveIngredientFood` (98–99), `IngredientFood` (102–133), `loader_options` (117–123)
- **Line ranges**: file 1–~410; food-related 60–138
- **Importance**: relevant
- **Reason**: All four must gain `is_pantry_staple: bool = False` (Create/Save/Read) to allow admin routes to set it and clients to read it. The deprecated `on_hand` is NOT exposed here, confirming case-5 needs a fresh field.

### `mealie/services/household_services/shopping_lists.py` — `add_recipe_ingredients_to_list`
- (already cited in critical) Specifically lines 413–455: returns `(ShoppingListOut, ShoppingListItemsCollectionOut)`. Case-5 event payload `added_item_count` comes from `len(item_changes.created_items) + len(item_changes.updated_items)`.

### `mealie/repos/repository_factory.py` — `AllRepositories` factory
- **Path**: `mealie/repos/repository_factory.py`
- **Symbols**: `AllRepositories.__init__` (113–122; `group_id`, `household_id` parameters with `NOT_SET` sentinel), `recipes` (133–137), `ingredient_foods` (139–141; group-scoped only), `household_preferences` (244–253), `meals` (297–301), `groups` (203–205), `households` (240–242), `group_shopping_lists` (further down — confirmed referenced from `ShoppingListService.__init__`)
- **Line ranges**: imports 1–95; factory 105–310+
- **Importance**: relevant
- **Reason**: Establishes the dependency-injection contract case-5 must follow. The auto-sync task instantiates `get_repositories(session, group_id=g, household_id=h)` (per `create_timeline_events.py:28` precedent). **Caveat**: `ingredient_foods` (139–141) is group-scoped, NOT household-scoped — confirming the spec's "global on foods table" decision is architecturally consistent.

### `mealie/routes/households/controller_household_self_service.py` — preferences endpoints
- **Path**: `mealie/routes/households/controller_household_self_service.py`
- **Symbols**: `get_household_preferences` GET (54–56), `update_household_preferences` PUT (58–62)
- **Line ranges**: full file 1–92
- **Importance**: relevant
- **Reason**: Today only PUT is exposed. **The spec's `PATCH /api/households/preferences`** is a new verb pattern — the codebase has no PATCH precedent on preferences. Implementer must decide whether to (a) add PATCH alongside PUT, or (b) re-interpret the spec as extending PUT (the existing pattern). Also: `self.checks.can_manage_household()` (60) is the auth gate to reuse for the new `run-now` route's "household admin" requirement.

### `mealie/routes/unit_and_foods/foods.py` — food CRUD
- **Path**: `mealie/routes/unit_and_foods/foods.py`
- **Symbols**: `IngredientFoodsController` (24), `create_one` POST (49–53; gates on `can_organize`), `update_one` PUT (69–73)
- **Line ranges**: full file 1–79
- **Importance**: relevant
- **Reason**: This is where the new `is_pantry_staple` field is read/written. The auth gate is `can_organize()` (line 51, 57, 71, 77), not `can_manage`. Spec says "allow admin to mark"; case-5 should decide whether `can_organize` suffices or if `can_manage_household` is required.

### `mealie/db/models/_model_utils/datetime.py` — `NaiveDateTime` + `get_utc_now`
- **Path**: `mealie/db/models/_model_utils/datetime.py`
- **Symbols**: `get_utc_now()` (6–10), `get_utc_today()` (13–17), `NaiveDateTime` TypeDecorator (20–50)
- **Line ranges**: full file 1–51
- **Importance**: relevant
- **Reason**: All persisted datetimes use `NaiveDateTime` (stores UTC without tzinfo, re-attaches UTC on read). The new `last_auto_synced_at` column MUST use this type for consistency. The class docstring (22–27) explicitly states **"Mealie uses naive datetimes since the app handles timezones explicitly"** — confirming that per-household timezone is purely an app-layer concept (timezone strings stored as `String`, conversion handled in scheduler code).

### `mealie/services/scheduler/tasks/post_webhooks.py` — group/household iteration pattern
- **Path**: `mealie/services/scheduler/tasks/post_webhooks.py`
- **Symbols**: module-level `last_ran = datetime.now(UTC)` (21), `post_group_webhooks` (24–79; iterates groups → households)
- **Line ranges**: full file 1–101
- **Importance**: relevant
- **Reason**: Demonstrates the existing "module-level timestamp guard" pattern (line 21, 32–35) for scheduled tasks. **This pattern is process-local and would NOT survive multi-worker deployments** — exactly what case-5 spec calls out as needing a DB-backed `last_auto_synced_at` instead. Good cautionary precedent.

### `mealie/schema/household/group_shopping_list.py` — shopping-list DTOs
- **Path**: `mealie/schema/household/group_shopping_list.py`
- **Symbols**: `ShoppingListItemRecipeRefCreate` (32–46), `ShoppingListItemBase` (58–76), `ShoppingListItemCreate` (79–94), `ShoppingListItemsCollectionOut` (146–152), `ShoppingListOut` (250–284), `ShoppingListAddRecipeParams` (288–292), `ShoppingListAddRecipeParamsBulk` (294–295), `ShoppingListSummary` (216–238)
- **Line ranges**: full file 1–~300
- **Importance**: relevant
- **Reason**: `ShoppingListAddRecipeParamsBulk` is the input type for `ShoppingListService.add_recipe_ingredients_to_list`. `ShoppingListItemsCollectionOut` (146–152) returns `created_items / updated_items / deleted_items` lists — case-5 derives `added_item_count` from this.

---

## Peripheral artifacts

### `mealie/db/models/household/__init__.py`
- **Path**: `mealie/db/models/household/__init__.py`
- **Line ranges**: full file 1–37
- **Importance**: peripheral
- **Reason**: Re-export module; no edits needed unless case-5 introduces a new model.

### `mealie/schema/household/__init__.py`
- **Path**: `mealie/schema/household/__init__.py`
- **Line ranges**: full file 1–140; `household_preferences` block 62–67 + 73–76
- **Importance**: peripheral
- **Reason**: **Auto-generated by `gen_schema_exports.py`** (header comment line 1). After adding/extending schema classes, `task dev:generate` must be run; do not hand-edit. Listed here so reviewers verify CI ran.

### `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py`
- **Path**: `.../2026-03-26-20.48.28_cdc93edaf73d_*.py`
- **Line ranges**: full file 1–51
- **Importance**: peripheral
- **Reason**: Recent migration adding new `EventTypes` enum values; useful precedent if case-5 must add `mealplan_auto_synced_to_shopping` as a subscribable event type with its own boolean column on `group_events_notifier_options`.

### `mealie/alembic/versions/2025-07-11-20.17.10_d7b3ce6fa31a_empty_migration_to_fix_food_flag_data.py`
- **Path**: `.../2025-07-11_*_empty_migration_to_fix_food_flag_data.py`
- **Line ranges**: full file 1–46
- **Importance**: peripheral
- **Reason**: Shows precedent for shipping a pure data-fix migration alongside a schema migration. Likely not needed for case-5 (the new pantry flag defaults to false, so no backfill required), but cited for completeness.

### `mealie/routes/explore/controller_public_foods.py`
- **Path**: `mealie/routes/explore/controller_public_foods.py`
- **Line ranges**: 1–~40
- **Importance**: peripheral
- **Reason**: Public read-only foods endpoint; will surface `is_pantry_staple` automatically once the DTO carries it. No code change required, but verify response shape changes don't break consumers.

### `mealie/db/models/_all_models.py`
- **Path**: `mealie/db/models/_all_models.py`
- **Importance**: peripheral
- **Reason**: Aggregate import that Alembic uses to discover models. Existing models are already imported; no edit required unless a brand-new table is added (case-5 only adds columns).

### `mealie/schema/group/group_preferences.py`
- **Path**: `mealie/schema/group/group_preferences.py`
- **Line ranges**: full file 1–20
- **Importance**: peripheral
- **Reason**: Group preferences (parent of household) currently has only `private_group` + `show_announcements` — also no timezone field. Confirms timezone is missing system-wide, not just on household.

---

## Data model gaps vs case-5 requirements

| Required by case-5 | Status today | Gap |
|---|---|---|
| `HouseholdPreferences.auto_sync_meal_plan_to_shopping: bool` | absent | new column + migration; default `false`, `server_default=sa.false()` |
| `HouseholdPreferences.auto_sync_target_shopping_list_id: UUID4 | None` | absent | new nullable `GUID` column + FK to `shopping_lists.id`; resolver in scheduler picks first active list when null |
| `HouseholdPreferences.auto_sync_run_time: str` (HH:MM) | absent | new `String` column, server_default `"00:00"`; validator on Pydantic side (regex `^([01]?\d|2[0-3]):[0-5]\d$`) |
| `HouseholdPreferences.last_auto_synced_at: datetime | None` | absent | new `NaiveDateTime` nullable column; CAS update guards multi-worker re-runs |
| **Per-household timezone field** | **absent everywhere** | Neither `HouseholdPreferencesModel` nor `GroupPreferencesModel` nor `Household` carries a timezone. Spec assumes it exists ("如未配置取 group default 或 server default UTC"). **Must add `timezone: str | None`** (IANA name, e.g. `"America/New_York"`) on `HouseholdPreferencesModel` and fall back to server local / UTC. Use `zoneinfo.ZoneInfo` at runtime. |
| `Food.is_pantry_staple: bool` (default false) | absent | new `Boolean` column on `ingredient_foods` (group-scoped) + Pydantic field on Create/Save/Read; migration mirrors `32d69327997b`. Note legacy deprecated `on_hand` column already exists at line 192 — do NOT reuse it. |
| `consolidate_ingredients` function | **does not exist by that name** | Spec references "case-3 中可能被修复的逻辑". The reusable equivalents are `ShoppingListService.bulk_create_items` (consolidates a batch + merges into existing un-checked items by `(food_id, unit_id)`) and `add_recipe_ingredients_to_list` (full add-from-recipe with list-level refs). Case-5 should **call `add_recipe_ingredients_to_list` per mealplan entry** rather than write new merge logic. |
| `recipe_references` linkage on auto-synced items | already implemented | `ShoppingListItem.recipe_references` + `ShoppingListRecipeReference` exist (shopping_list.py:26–48, 101–120, 87–89). `add_recipe_ingredients_to_list` populates both automatically. Case-5 does NOT need a separate "link back to meal plan" model — the recipe linkage is enough (a meal plan entry references a single recipe). |
| Mealplan → ingredients traversal | possible but two-step | `RepositoryMeals.get_today` returns `ReadPlanEntry` whose `recipe: RecipeSummary | None` may not include full `recipe_ingredient`. Scheduler must re-fetch via `repos.recipes.get_one(recipe_id)` to get the full ingredient list (see precedent in `ShoppingListService.get_shopping_list_items_from_recipe:332–340`). |
| `EventTypes.mealplan_auto_synced_to_shopping` | absent | New enum entry in `event_types.py:13` + matching boolean column on `group_events_notifier_options` (migration `cdc93edaf73d` is the pattern). New `EventMealplanAutoSyncData(EventDocumentDataBase)` payload class with `household_id`, `shopping_list_id`, `added_item_count`, `skipped_pantry_count`. |
| 30-minute scheduler bucket | absent | `SchedulerService` exposes minutely (=every 5 min)/hourly/daily only. Reuse `register_minutely` and gate inside the callback via `last_auto_synced_at` + 30-min window alignment with `auto_sync_run_time` in each household's timezone. |
| `PATCH /api/households/preferences` | absent | Today only PUT exists (controller_household_self_service.py:58). New PATCH endpoint must accept partial body. No PATCH precedent in this controller — implementer chooses verb semantics. |
| Multi-worker idempotency | absent for scheduled tasks | `post_webhooks.py` uses an in-process `last_ran` (line 21) — broken under multi-worker. Case-5 must use a `SELECT … FOR UPDATE SKIP LOCKED` on `household_preferences.id` or a conditional `UPDATE … WHERE last_auto_synced_at < <today>` CAS to ensure exactly-once per day. |

---

## Cross-perspective questions

1. **(→ API/route perspective)** Should `PATCH /api/households/preferences` accept the standard `UpdateHouseholdPreferences` body or a smaller `AutoSyncPreferencesPatch` partial? Today only PUT (full body) is supported — confirm convention.
2. **(→ API/route perspective)** Auth gate for the new admin food `is_pantry_staple` write: `can_organize()` (current foods PUT auth) vs `can_manage_household()` (preferences auth)? Spec says "admin only" — needs disambiguation.
3. **(→ scheduler/service perspective)** Should we add a new `MINUTES_30` bucket to `SchedulerService` or stay inside `register_minutely` with internal window guards? Spec says "must reuse existing scheduler abstractions" — option B preferred, but explicit confirmation prevents drift.
4. **(→ scheduler/service perspective)** When `auto_sync_target_shopping_list_id` is null, what defines "first active main list"? Spec lacks a `is_active` or `is_primary` flag on `ShoppingList` — proposed proxy: `ORDER BY created_at ASC LIMIT 1` within `(group_id, household_id)`. Confirm.
5. **(→ scheduler/service perspective)** Where should `ZoneInfo`/timezone resolution live? Proposed helper: `get_household_tz(household_preferences) -> ZoneInfo` returning `ZoneInfo(prefs.timezone or settings.TZ or "UTC")`. Need agreement on fallback chain.
6. **(→ test perspective)** The `household_id` on `ShoppingList`/`ShoppingListItem`/`GroupMealPlan` is an `AssociationProxy` through `user`, not a column. Multi-tenant isolation tests must construct lists/mealplans with users from the correct household — fixture audit needed to ensure tests don't accidentally cross households via shared user IDs.
7. **(→ event-bus perspective)** Does adding `mealplan_auto_synced_to_shopping` to `EventTypes` require a migration to `group_events_notifier_options` (as the enum docstring at event_types.py:14–22 warns)? If yes, that doubles the alembic-revision count.
8. **(→ event-bus perspective)** Is the new event payload subscribable from existing webhook listeners (`event_bus_listeners.py` only handles `webhook_task → EventDocumentType.mealplan` today), or does case-5 just dispatch and expect downstream subscribers later?
9. **(→ design/coding perspective)** Should `is_pantry_staple` be group-scoped (a column on `ingredient_foods` — current proposal) or per-household (a column on the existing `households_to_ingredient_foods` join table)? Spec says "global on foods", but the deprecated-`on_hand`→`households_to_ingredient_foods` precedent (ingredient.py:21–27, 192) suggests per-household tracking was preferred for similar booleans. CR-level call.
