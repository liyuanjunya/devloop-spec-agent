# Case 5 — Data Perspective

> Source-of-truth audit for every data-layer symbol case-5 will touch, with
> verified file paths, symbol names, and line ranges. All ranges have been
> opened in the source and validated against `mealie` at the same checkout
> referenced by `context/grounding.md`.

## 1. HouseholdPreferences (model + migration seam)

| Field | Value |
|---|---|
| Path | `mealie/db/models/household/preferences.py` |
| Symbols | `HouseholdPreferencesModel` |
| Line range | `1–44` (full file) |
| Class declaration | line `16` |
| Existing columns | `id` (18), `household_id` (20–22), `household` (23), `group_id` association_proxy (24), `private_household` (26), `show_announcements` (27), `lock_recipe_edits_from_other_households` (29), `first_day_of_week` (30), `recipe_public` (33), `recipe_show_nutrition` (34), `recipe_show_assets` (35), `recipe_landscape_view` (36), `recipe_disable_comments` (37), `recipe_disable_amount` (40, Deprecated) |
| Importance | **Critical**. All three case-5 config fields (`auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, `auto_sync_run_time`) plus `last_auto_synced_at` + `timezone` need to be added here. Uses the `@auto_init()` pattern at line 42; any new fields are automatically picked up. |
| Reason | This is the SQL-backed table that drives the entire opt-in mechanism. The model uses `BaseMixins` (line 16) which already provides `created_at`/`updated_at` via `NaiveDateTime`, so adding `last_auto_synced_at: FilterableColumn[datetime \| None] = mapped_column(NaiveDateTime)` follows existing convention. |

### Existing schema layer (mirrors the model)
| Path | `mealie/schema/household/household_preferences.py` |
|---|---|
| Symbols | `UpdateHouseholdPreferences` (10–22), `CreateHouseholdPreferences` (25), `SaveHouseholdPreferences` (28–29, adds `household_id`), `ReadHouseholdPreferences` (32–40, adds `id`) |
| Line range | `1–40` (full file) |
| Importance | **Critical**. Single inheritance chain — adding fields to `UpdateHouseholdPreferences` propagates through Create/Save/Read automatically. `ReadHouseholdPreferences.loader_options()` at line 37 joinedloads the household; case-5 may need to extend if it adds a `timezone` field. |
| Reason | Adding three (or five, counting `last_auto_synced_at` + `timezone`) new fields here is mechanical and is the cleanest way to expose them through the existing `PUT /households/preferences` route at `mealie/routes/households/controller_household_self_service.py:58`. |

### Migration template (verified pattern)
| Path | `mealie/alembic/versions/2024-09-02-21.39.49_be568e39ffdf_added_household_recipe_lock_setting_and_.py` |
|---|---|
| Symbols | `upgrade()` (58–67), `downgrade()` (70–74), `populate_defaults()` (21–55) |
| Line range | `1–75` (full file) |
| Importance | **High**. Verbatim template for adding boolean + nullable columns to `household_preferences` with Postgres/SQLite-aware defaults. Uses `op.add_column("household_preferences", sa.Column(..., nullable=True))` then `populate_defaults()` SQL UPDATE with `TRUE`/`FALSE` vs `1`/`0` branching at lines 22–27. |
| Reason | Case-5 migration must add three booleans/strings/UUIDs to this table; the existing precedent shows exactly how to do it backward-compatibly. The `downgrade()` mirror is required by Mealie's alembic conventions. |

---

## 2. MealPlan model + entry (the `recipe_id` carrier)

| Field | Value |
|---|---|
| Path | `mealie/db/models/household/mealplan.py` |
| Symbols | `GroupMealPlan` (55–77), `GroupMealPlanRules` (30–52), `plan_rules_to_households` association table (21–27) |
| Line range | `1–78` (full file) |
| Key columns of `GroupMealPlan` | `date: Date, indexed` (58), `entry_type: str` (59), `title: str` (60), `text: str` (61), `group_id` FK (63–64), `household_id: AssociationProxy` via user (65), `user_id` FK (67–68), `recipe_id: GUID \| None` FK (70), `recipe: RecipeModel` relationship (71–73) |
| Importance | **Critical**. The auto-sync task iterates entries of this table for `date == today` AND `household_id == h.id` AND `recipe_id IS NOT NULL`. Note: `household_id` is an `AssociationProxy("user", "household_id")` at line 65 — same tenant-scoping pattern as `ShoppingList.household_id` (model L153 in shopping_list.py). |
| Reason | This is the source dataset for case-5's "today's recipes" query. The repo helper `RepositoryMeals.get_today` (see §6) wraps the filter; auto-sync calls that directly. The `selectinload(GroupMealPlan.recipe).joinedload(RecipeModel.recipe_category/tags/tools)` chain at `mealie/schema/meal_plan/new_meal.py:67–74` (`ReadPlanEntry.loader_options`) eagerly loads recipe data — no N+1 risk. |

### Schema layer
| Path | `mealie/schema/meal_plan/new_meal.py` |
|---|---|
| Symbols | `ReadPlanEntry` (62–74), `CreatePlanEntry` (34–47), `UpdatePlanEntry` (50–53), `PlanEntryType` enum (19–26) |
| Line range | `1–79` |
| Importance | **High**. `ReadPlanEntry.recipe: RecipeSummary \| None` (64) is what the auto-sync task consumes. `recipe_id: UUID \| None` (39, validated on `CreatePlanEntry`) is the filter target. |
| Reason | Lets the auto-sync task treat meal plan entries as Pydantic objects with attached `recipe` (already eager-loaded). |

---

## 3. Food model — does `is_pantry_staple` exist?

**Verdict: NO.** It must be added by case-5.

| Field | Value |
|---|---|
| Path | `mealie/db/models/recipe/ingredient.py` |
| Symbols | `IngredientFoodModel` (153–219), `IngredientFoodAliasModel` (referenced at 171–175), `households_to_ingredient_foods` association table (21–27) |
| Class declaration | line `153` |
| Existing columns of `IngredientFoodModel` | `id` (155), `group_id` FK (158), `group` (159), `households_with_ingredient_food` many-to-many via `households_to_ingredient_foods` (160–162), `name` (164), `plural_name` (165), `description` (166), `ingredients` reverse rel (168–170), `aliases` (171–175), `extras` (176), `label_id` (178), `label` (179), `name_normalized` (182), `plural_name_normalized` (183), `on_hand: Mapped[bool] = mapped_column(Boolean, default=False)` (192, marked Deprecated by comment at line 191) |
| Importance | **Critical**. `is_pantry_staple` is genuinely missing — only the deprecated `on_hand` exists. Case-5 must (a) add `is_pantry_staple: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)` here, (b) extend `mealie/schema/recipe/recipe_ingredient.py` `CreateIngredientFood` (92–95) / `SaveIngredientFood` (98–99) / `IngredientFood` (102–133) to expose it, (c) add an alembic migration mirroring the `on_hand` migration at `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py:24–46`. |
| Reason | The auto-sync task's pantry filter (spec §2 step 4) loads the food via `recipe_ingredient.food` and skips items where `food.is_pantry_staple is True`. Without this column on `IngredientFoodModel` (and visible on `IngredientFood` Pydantic schema), the filter cannot run. |

### Filename trap (`add_staple_flag_to_foods` does NOT add `staple_flag`)
| Path | `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py` |
|---|---|
| Symbols | `upgrade()` (24–41), `downgrade()` (44–46), `is_postgres()` (20–21) |
| Line range | `1–46` (full file) |
| Importance | **Cautionary**. Filename suggests "staple_flag" but body adds `on_hand` (line 26). Future readers (and case-5 reviewers) may be misled. Reuse the file's batch_alter_table + populate-then-set-non-nullable pattern verbatim for `is_pantry_staple`. |
| Reason | This is the closest structural precedent for the case-5 `is_pantry_staple` migration. The pattern is: add column nullable=True → UPDATE rows to FALSE → alter to nullable=False. |

### Pydantic schema (currently does NOT expose any staple/on_hand)
| Path | `mealie/schema/recipe/recipe_ingredient.py` |
|---|---|
| Symbols | `UnitFoodBase` (60–81), `CreateIngredientFood` (92–95), `SaveIngredientFood` (98–99), `IngredientFood` (102–133), `IngredientFoodPagination` (136–137) |
| Line range | `60–140` (relevant block) |
| Importance | **High**. Even though the DB has `on_hand`, none of the schemas expose it. Case-5's `is_pantry_staple` must be added to `CreateIngredientFood` (or one of its parents) so the existing `PUT /api/foods/{item_id}` route at `mealie/routes/unit_and_foods/foods.py:69–73` accepts it. Alternatively, expose only through a new admin-only PATCH route (see API perspective). |
| Reason | Without exposing in the schema, the column would be DB-only and unreachable from the API. |

---

## 4. Existing consolidation pipeline (the spec calls this `consolidate_ingredients` but it does NOT exist by that name)

**Verdict on naming:** there is no top-level function literally called `consolidate_ingredients`. Grep across `mealie/` returns only inline variables (`consolidated_create_items` at L163–177) and unrelated `_consolidate_group` in `services/query_filter/builder.py`. The de-facto consolidation is split across three methods of `ShoppingListService`.

| Field | Value |
|---|---|
| Path | `mealie/services/household_services/shopping_lists.py` |
| File size | 554 lines (verified via PowerShell `Get-Content … .Count`) |
| Symbols and ranges | `ShoppingListService` class (34–onwards), `can_merge(item1, item2)` (45–71), `merge_items(from_item, to_item)` (73–128), `remove_unused_recipe_references(shopping_list_id)` (130–143), `find_matching_label(item)` (145–152), `bulk_create_items(create_items, auto_find_labels=True)` (154–223), `bulk_update_items(update_items)` (225–310), `bulk_delete_items(delete_items)` (312–321), `get_shopping_list_items_from_recipe(list_id, recipe_id, scale, recipe_ingredients)` (323–411), `add_recipe_ingredients_to_list(list_id, recipe_items)` (413–455), `remove_recipe_ingredients_from_list(list_id, recipe_id, recipe_decrement)` (457–~) |
| Importance | **Critical**. Auto-sync MUST reuse these — spec §实现约束 forbids re-implementing consolidation. The highest-level seam is `add_recipe_ingredients_to_list(list_id, recipe_items)` (413–455), which: (1) calls `get_shopping_list_items_from_recipe` per recipe with the requested scale, (2) calls `bulk_create_items` to merge into existing unchecked items by `(food_id, unit_id)` via `can_merge`, (3) returns `(ShoppingListOut, ShoppingListItemsCollectionOut)` so the caller can publish events. |
| Reason | `can_merge` (45–71) verifies food_id equality + unit compatibility (with UnitConverter fallback). `merge_items` (73–128) accumulates `quantity`, merges `unit`, dedupes `note`, and merges `recipe_references` by `recipe_id`. `bulk_create_items` (154–223) first consolidates the incoming batch among itself (162–177), then merges into existing unchecked items in the list (180–203). This is the entire "consolidate then append" semantics case-5 spec §2 steps 5–6 require. |

### Reuse pattern for auto-sync
The cleanest call shape for auto-sync (verified by reading existing controller usage at `mealie/routes/households/controller_shopping_lists.py:256–261`):

```python
shopping_list_service = ShoppingListService(household_repos)
recipe_items = [
    ShoppingListAddRecipeParamsBulk(recipe_id=mp.recipe_id, recipe_increment_quantity=1.0)
    for mp in todays_meal_plans
    if mp.recipe_id is not None
]
updated_list, items_collection = shopping_list_service.add_recipe_ingredients_to_list(
    list_id=target_list_id,
    recipe_items=recipe_items,
)
```

The pantry-staple filter must run before this call (filter the `recipe.recipe_ingredient` list before passing it in via the `recipe_ingredients` param of `get_shopping_list_items_from_recipe`, OR build `ShoppingListItemCreate` objects directly and skip `add_recipe_ingredients_to_list` in favour of `bulk_create_items`).

---

## 5. `recipe_references` linking (back-link from shopping_list_item → mealplan/recipe)

| Field | Value |
|---|---|
| Path | `mealie/db/models/household/shopping_list.py` |
| Symbols | `ShoppingListItemRecipeReference` (26–48), `ShoppingListRecipeReference` (101–120) |
| Line range | `26–48` (item-level ref), `101–120` (list-level ref) |
| `ShoppingListItemRecipeReference` columns | `id` (28), `shopping_list_item` rel (30–32), `shopping_list_item_id` PK FK (33–35), `recipe_id` FK (37), `recipe` rel (38), `recipe_quantity: float` (39), `recipe_scale: float` (40), `recipe_note: str \| None` (41), `group_id` association_proxy (43), `household_id` association_proxy (44) |
| `ShoppingListRecipeReference` columns | `id` (103), `shopping_list` rel (105), `shopping_list_id` PK FK (106), `group_id`/`household_id` association_proxy (107–108), `recipe_id` FK (110), `recipe` rel (111–113), `recipe_quantity: float` (115) |
| Importance | **Critical**. Spec §2 step 5 requires `recipe_references` to be populated on each added item. The schema layer creates these via `ShoppingListItemRecipeRefCreate` at `mealie/schema/household/group_shopping_list.py:32–46`, which is what `get_shopping_list_items_from_recipe` already does at `mealie/services/household_services/shopping_lists.py:377–384`. |
| Reason | Reusing `add_recipe_ingredients_to_list` automatically populates these. Each created `ShoppingListItem` carries a `recipe_references=[ShoppingListItemRecipeRefCreate(recipe_id=..., recipe_quantity=..., recipe_scale=..., recipe_note=...)]`. Spec §2 step 5 says "link back to meal plan / recipe" — `recipe_id` covers recipe; mealplan linkage is implicit because the event payload carries `household_id` + `shopping_list_id` and the meal plan can be looked up by date+household. If a direct mealplan_id back-link is desired, that would require a NEW column on `ShoppingListItemRecipeReference` (not in spec). |

### Schema layer
| Path | `mealie/schema/household/group_shopping_list.py` |
|---|---|
| Symbols | `ShoppingListItemRecipeRefCreate` (32–46), `ShoppingListItemRecipeRefUpdate` (49–51), `ShoppingListItemRecipeRefOut` (54–55), `ShoppingListItemBase` (58–76), `ShoppingListItemCreate` (79–on), `ShoppingListAddRecipeParamsBulk` (referenced in service signature) |
| Line range | `32–80` (relevant) |
| Importance | **High**. These are the DTOs the auto-sync task constructs. `ShoppingListItemRecipeRefCreate` carries `recipe_id` (33), `recipe_quantity` (34), `recipe_scale` (37), `recipe_note` (40). |
| Reason | The merge_items logic at `services/household_services/shopping_lists.py:109–126` consolidates `recipe_references` by `recipe_id`, accumulating `recipe_scale` — so adding the same recipe twice in one batch (or across days within the same scheduler tick) merges correctly. |

---

## 6. Per-household timezone field

**Verdict: NO such field exists anywhere in the model layer.** Verified by grepping `timezone|tz_` across `mealie/db/models/group/` and `mealie/db/models/household/` (zero matches). Also verified the `users` model has no timezone column.

| Field | Value |
|---|---|
| Path (proposed location) | `mealie/db/models/household/preferences.py` (add new column to `HouseholdPreferencesModel`) |
| Existing "today" fallback | `mealie/services/scheduler/tasks/create_timeline_events.py:36` uses `tzlocal()` (process/server TZ); `mealie/routes/households/controller_mealplan.py:124–127` (`get_todays_meals`) uses the same |
| `RepositoryMeals.get_today(tz=UTC)` | `mealie/repos/repository_meals.py:11–21` — accepts a tz parameter and computes `datetime.now(tz=tz).date()` to filter `GroupMealPlan.date == today`. **This is the seam.** |
| Importance | **Critical**. Spec §实现约束 explicitly forbids `datetime.now()` without timezone and mandates household-configured TZ with fallback to group/server default UTC. Without a `timezone` field somewhere, the task can only fall back to server TZ — which violates the spec. |
| Reason | The cleanest add: `timezone: FilterableColumn[str \| None] = mapped_column(sa.String, nullable=True)` on `HouseholdPreferencesModel` (default `None` → fall back). Pass into `RepositoryMeals.get_today(tz=ZoneInfo(prefs.timezone or "UTC"))`. The schema field on `UpdateHouseholdPreferences` would be `timezone: str \| None = None`. This is a NEW column with a separate alembic migration. Edge case: DST and invalid TZ strings — validate via `zoneinfo.ZoneInfo` or `pytz`. |

### Datetime conventions
| Path | `mealie/db/models/_model_utils/datetime.py` |
|---|---|
| Symbols | `NaiveDateTime` (22–48) |
| Line range | `1–50` |
| Importance | **High**. The TypeDecorator at L22–48 strips tzinfo on store (L37–39) and re-adds UTC on load (L46). Docstring at L22–26 says "Mealie uses naive datetimes since the app handles timezones explicitly. All timezones are generated, stored, and retrieved as UTC." |
| Reason | Confirms that `last_auto_synced_at` must be stored as UTC (NaiveDateTime auto-converts), and any comparison against the household's "today" must explicitly construct a TZ-aware datetime before computing the date. |

---

## 7. Repository factory wiring

| Field | Value |
|---|---|
| Path | `mealie/repos/repository_factory.py` |
| Symbols | `AllRepositories` (105–onwards), `household_preferences` (244–253), `meals` (297–301), `group_shopping_lists` (317–321), `group_shopping_list_item` (323–332), `group_shopping_list_item_references` (334–345), `households` (240–242), `ingredient_foods` (139–141) |
| Importance | **High**. The auto-sync task constructs `repos = get_repositories(session, group_id=..., household_id=...)` (the household-scoped variant), then uses `repos.households` for iteration (group-scoped), `repos.meals.get_today(tz=...)`, `repos.group_shopping_lists` to pick/look up the target list, `repos.household_preferences` to read/CAS-update `last_auto_synced_at`, and `repos.ingredient_foods` if it needs to load food details outside the `RecipeIngredient.food` eager-loaded chain. |
| Reason | All repos here are `HouseholdRepositoryGeneric`-scoped (auto-filter by `group_id` AND `household_id`), which means cross-tenant leakage is structurally blocked. The auto-sync task does NOT need to add filters manually for the inner-loop work as long as the `repos` instance is constructed with the right `(group_id, household_id)`. |

---

## 8. Tenant-scoping invariant for the new write

| Field | Value |
|---|---|
| Path | `mealie/db/models/household/shopping_list.py` |
| Key invariant | `ShoppingList.household_id` is `AssociationProxy("user", "household_id")` (153) — derived via the user FK. To write to a shopping list belonging to household H, the user_id on the list must already belong to H. |
| Importance | **Critical for multitenant safety**. The auto-sync task uses a system identity, but the list it writes to was created by a household member, so its `household_id` is already correct. The task only needs to verify `shopping_list.household_id == h.id` (or just trust the household-scoped repo) before writing. |
| Reason | Spec §5 mandates "household A's meal plan never writes to household B's shopping list." The repo scoping (§7) plus this invariant give a layered guarantee. The integration test must explicitly assert that a misconfigured `auto_sync_target_shopping_list_id` pointing to another household's list is rejected (404 or no-op). |

---

## Data model gaps vs case-5 requirements

| Requirement (spec §) | Existing | Gap |
|---|---|---|
| §1 `auto_sync_meal_plan_to_shopping: bool` on HouseholdPreferences | None | **NEW column** on `household_preferences`. |
| §1 `auto_sync_target_shopping_list_id: UUID \| null` on HouseholdPreferences | None | **NEW column** with `ForeignKey("shopping_lists.id", ondelete="SET NULL")` to safely handle deletions. |
| §1 `auto_sync_run_time: str "HH:MM"` on HouseholdPreferences | None | **NEW column**, `String(5)`, default `"00:00"`. Could also be split into `auto_sync_run_hour: int` + `auto_sync_run_minute: int` for index/comparison efficiency. |
| §1 backwards compatibility (`default false`) | n/a | Migration must `populate_defaults()` to FALSE/`"00:00"`/NULL after add — pattern at `mealie/alembic/versions/2024-09-02-21.39.49_be568e39ffdf_...:21–55`. |
| §2 `LastAutoSyncedAt` idempotency marker | None | **NEW column** `last_auto_synced_at: NaiveDateTime \| None` on HouseholdPreferences (or a sidecar table). UTC per `NaiveDateTime` convention. |
| §2 per-household timezone for "today" | `RepositoryMeals.get_today(tz=UTC)` accepts a tz; no per-household source | **NEW column** `timezone: str \| None` on HouseholdPreferences (or fall back to server TZ if spec § implementation-constraint "household default" path is taken — but spec says "household 时区下"). |
| §2 step 4 `Food.is_pantry_staple` | Only deprecated `on_hand` | **NEW column** `is_pantry_staple: bool` on `ingredient_foods` (migration mirrors `add_staple_flag_to_foods`); **NEW schema field** on `CreateIngredientFood`/`SaveIngredientFood`/`IngredientFood`. |
| §2 step 5 `recipe_references` linkage | `ShoppingListItemRecipeReference` already present | **No gap** — `ShoppingListItemRecipeRefCreate` already constructed by `get_shopping_list_items_from_recipe` at `services/household_services/shopping_lists.py:377–384`. |
| §2 step 6 merge into existing unchecked item by `(food_id, unit_id)` | `can_merge` (45–71) + `merge_items` (73–128) + `bulk_create_items` (154–223) | **No gap** in semantics. **Cosmetic gap**: there is NO function literally called `consolidate_ingredients`; the consolidation is split across these three methods. If case-3 refactors and extracts a `consolidate_ingredients` symbol, case-5 should call that; otherwise call `add_recipe_ingredients_to_list` (413–455) as the highest-level seam. |
| §4 multitenant pantry-staple isolation | Foods are `group_id`-scoped (`IngredientFoodModel.group_id` at line 158) — already per-group | **No gap** at the data model level — pantry-staple flag is per-group by inheritance. The cross-household test in §5 is about within-group household isolation (mark in household A's POV does not bleed into household B's foods because the foods themselves are group-shared, but the auto-sync task in household A's run uses A's preferences/timezone — not B's). |

---

## Cross-perspective questions

These need the API perspective and the design/coding phase to resolve.

1. **Where does `last_auto_synced_at` live?** Same row as the other preferences (one extra column on `household_preferences`) keeps the CAS update atomic with the preference read. A sidecar table (`household_auto_sync_state`) would be more normalised but doubles the table count. Recommend same row.
2. **`auto_sync_target_shopping_list_id` cross-household reference safety.** The FK constraint to `shopping_lists.id` does not enforce the list's household equals the row's household. Need either (a) a CHECK constraint (SQLite doesn't support cross-table CHECK) or (b) a validation in `UpdateHouseholdPreferences` schema (PUT route) that looks up the list and rejects if `list.household_id != self.household_id`. Recommend (b).
3. **`auto_sync_run_time` format / timezone semantics.** Store as `"HH:MM"` string with regex validator `^([01]\d|2[0-3]):[0-5]\d$` in the Pydantic schema, OR store as two integers. The "today" definition starts at this local time → the date used for `RepositoryMeals.get_today` could be ambiguous near midnight in the household's TZ. Spec calls it "household 时区下的'今天开始时间'" — clarifies that the date boundary is the run time, not midnight. The repo currently uses `.date()` of `datetime.now(tz=tz)` — needs adapting if the spec literally wants run_time to define the "today" boundary.
4. **`is_pantry_staple` permission model.** Foods are group-shared, so a household-admin (`can_organize`) marking a food as pantry-staple affects every household in the group. Spec §5 says "跨 household 的 food pantry-staple 标记不互相影响" — this is contradictory unless the spec means "tested at integration level, the marks set by one household's tests don't leak via test fixtures to another household's test case". Recommend implementing per-group with `can_organize` permission AND surfacing this as a CR-phase question.
5. **Will `add_recipe_ingredients_to_list` correctly populate `recipe_references` when called with the same recipe ID twice across separate calls (e.g., breakfast + lunch on the same day, both using the same recipe)?** Verified: `merge_items` at L109–126 merges `recipe_references` by `recipe_id` and accumulates `recipe_scale` — so calling twice with the same recipe will end up with one ref whose `recipe_scale` = 2. This matches spec §2 step 6.
6. **Loader options for `ReadPlanEntry.recipe` include `recipe_category/tags/tools` but NOT `recipe_ingredient`.** Verified at `mealie/schema/meal_plan/new_meal.py:67–74`. The auto-sync task needs `recipe.recipe_ingredient` to feed the consolidation pipeline. Either (a) call `get_shopping_list_items_from_recipe(list_id, recipe_id)` which fetches the recipe internally (`services/household_services/shopping_lists.py:336–340`), or (b) extend `ReadPlanEntry.loader_options` to also `selectinload(GroupMealPlan.recipe).selectinload(RecipeModel.recipe_ingredient).selectinload(RecipeIngredientModel.food)` for fewer round-trips. Option (a) is less invasive; option (b) is a future N+1 optimization. Recommend (a) for case-5.
7. **Cross-coupling with case-3:** if case-3 refactors `ShoppingListService` and extracts a top-level `consolidate_ingredients` function, case-5 should call that. Until then case-5 calls `add_recipe_ingredients_to_list` and trusts the inline consolidation. Document this coupling in the design phase.
