# Case-5 — History Perspective (Stage 3)

> Source repo: `C:\Users\v-liyuanjun\Downloads\mealie` (branch `devloop-baseline`, HEAD `4a099c16 2026-06-17 fix: Various lint issues (#7766)`)
> Method: `git --no-pager log/show` over the four target paths plus topical greps (`scheduler|scheduled|cron|auto sync|pantry|household preference|timezone|on hand|consolidate|revert`).

---

## 1. Top 15 recent commits on the four target paths

Ranked by recency, restricted to commits that touch any of
`mealie/services/scheduler/`, `mealie/services/event_bus_service/`,
`mealie/services/household_services/shopping_lists.py`,
`mealie/db/models/household/preferences.py`,
plus `mealie/db/models/recipe/ingredient.py` (Food model — case-5 needs it).

| # | Hash | Date | Subject | Why it matters to case-5 |
|---|------|------|---------|--------------------------|
| 1 | `642c826f` | 2026-05-21 | fix: Protect sensitive data in query filter API (GHSA-8m57-7cv5-rjp8) (#7629) | Touched `preferences.py`. Reminds us that adding a `auto_sync_target_shopping_list_id: UUID` (filterable column) needs to be reviewed against the query-filter sanitization rules introduced here. |
| 2 | `d2b0681d` | 2026-04-11 | feat: Announcements (#7431) | Most recent precedent for **adding new columns to `HouseholdPreferencesModel`** (added `show_announcements` etc.). Use this PR as the template for our preferences migration shape. |
| 3 | `e52a887e` | 2026-03-26 | fix: publish all mealplan create, update, and delete events (#7015) | Live precedent for **adding new `EventTypes` enum values + matching `group_events_notifier_options` migration** (`cdc93edaf73d_add_mealplan_updated_and_deleted_to_…`). Our `mealplan_auto_synced_to_shopping` event must follow the same dual-write pattern. |
| 4 | `b5c089f5` | 2026-03-09 | feat: Unit standardization / conversion (#7121) | Modified `shopping_lists.py` and `ingredient.py`; introduces `UnitConverter` / `standard_unit` semantics that `can_merge` now relies on. **Merging by `(food_id, unit_id)` is no longer naïve** — the auto-sync task must accept that two distinct units may merge after conversion. |
| 5 | `60d92948` | 2025-11-03 | feat: Add recipe as ingredient (#4800) | Recent ingredient/`IngredientFoodModel` change. Recipe-as-ingredient introduces non-food ingredients — auto-sync must handle ingredients where `food_id is None` (skip them or fall back to note matching, like the existing dialog does). |
| 6 | `6cbc308d` | 2025-08-16 | fix: Add Recipe From Another Household To Shopping List (#5892) | Cross-household bug fix in `shopping_lists.py`. Proves **cross-household recipe→shopping list pathing is historically fragile**; our task copies meal-plan→shopping-list inside one household, but reviewers will look hard at the boundary. |
| 7 | `d3436a5c` | 2025-08-10 | feat: Add label notifier (#5879) | Touched `event_bus_service/`. Adds a notifier opt-in column per event type — sets the precedent that **new `EventTypes` SHOULD expose a per-household subscription toggle** (or be marked internal). |
| 8 | `245ca5fe` | 2025-07-31 | feat: Remove "Is Food" and "Disable Amounts" Flags (#5684) | Touched `preferences.py` + `shopping_lists.py` + `ingredient.py`. Shows the project actively *removes* boolean flags rather than letting them accumulate — `is_pantry_staple` will be scrutinised under this lens. |
| 9 | `675ac9c3` | 2025-07-28 | fix: Make Sure Test Webhook Always Fires (#5816) | Touched `scheduler/` and `event_bus_service/`. Reminds us that scheduler tasks must dispatch through the central event bus, never call webhooks directly. |
| 10 | `716c85cc` | 2025-02-27 | fix: Bulk Add Recipes to Shopping List (#5054) | Refactored `add_recipe_ingredients_to_list` and added `ShoppingListAddRecipeParamsBulk`. **This is the function we must reuse** to enforce "复用既有合并/添加 item 函数". |
| 11 | `df8dd3fe` | 2025-02-25 | fix: Invalidate Expired Shared Links (#5065) | Touched `scheduler/`. Shows the "purge / expire" task pattern (per-row updates, idempotent, daily). |
| 12 | `e9892aba` | 2025-01-13 | feat: Move "on hand" and "last made" to household (#4616) | **CRITICAL PRECEDENT for `is_pantry_staple`.** The project previously had `IngredientFoodModel.on_hand: bool` (group-scoped) and *deliberately moved it* to a `households_to_ingredient_foods` association table because foods are group-scoped but the flag is per-household. Putting `is_pantry_staple` as a column on `ingredient_foods` would **repeat exactly the mistake this PR fixed**. |
| 13 | `8d325198` | 2024-12-17 | fix: Use configured server time when calling `RepositoryMeals.get_today()` (#4734) | Defines how `repos.meals.get_today(tz=…)` must be called from scheduler tasks. Case-5 spec says we must use the *household* tz, so we must pass `tz=household_tz` here, not the server `tzlocal()` that `create_timeline_events.py` uses today. |
| 14 | `87504fbb` | 2024-12-04 | feat: Upgrade to Python 3.12 (#4675) | Established `datetime.UTC` usage in scheduler tasks. Stay on `from datetime import UTC` (not `pytz.UTC`, not `timezone.utc`). |
| 15 | `b0ed242f` | 2024-10-06 | fix: Strip Timezone from Timestamps in DB (#4310) | Introduces `NaiveDateTime` column type (`mealie/db/models/_model_utils/datetime.py`). **`last_auto_synced_at` MUST use `NaiveDateTime`**, not `sa.DateTime(timezone=True)`. Comment in that file: *"Mealie uses naive date times since the app handles timezones explicitly. All timezones are generated, stored, and retrieved as UTC."* |

Additional honourable mentions outside the strict top-15 but historically relevant:

- `fd0257c1 2024-09-17 feat: Additional Household Permissions (#4158)` — last time a single field was added to `HouseholdPreferencesModel` *and* a paired permission was added. Useful migration template (`75b0a0bafdf_added_household_recipe_lock_setting_and_…`).
- `eb170cc7 2024-08-22 feat: Add Households to Mealie (#3970)` — the household concept itself. `HouseholdPreferencesModel` is FK to `households.id`, `group_id` only via `association_proxy`.
- `d5f7a883 2024-07-08 fix: Make Mealie Timezone-Aware (#3847)` — the whole TZ story starts here.

---

## 2. Prior scheduled-task patterns — precedent for the case-5 task

`mealie/services/scheduler/` is **homegrown, single-worker** (apscheduler was dropped in `045798e9 2022-04-10 chore: drop-apscheduler (#1152)`). The current architecture:

```
SchedulerService.start()  (app.py line 124)
   ├── run_minutely  (actually every 5 min — MINUTES_5 = 5)
   ├── run_hourly
   └── schedule_daily → asyncio.sleep until DAILY_SCHEDULE_TIME_UTC, then run_daily

SchedulerRegistry (class-level lists)
   ├── _minutely  ← register_minutely(...)
   ├── _hourly
   └── _daily
```

Registration happens once in `app.py`:

```python
SchedulerRegistry.register_daily(
    tasks.purge_expired_tokens,
    tasks.purge_group_registration,
    tasks.purge_password_reset_tokens,
    tasks.purge_group_data_exports,
    tasks.create_mealplan_timeline_events,     # ← the gold-standard precedent
    tasks.delete_old_checked_list_items,
)
SchedulerRegistry.register_minutely(tasks.post_group_webhooks)
SchedulerRegistry.register_hourly(tasks.locked_user_reset)
```

### Key precedent — `create_timeline_events.py`

`mealie/services/scheduler/tasks/create_timeline_events.py` is the closest existing analogue to case-5's new task: it walks every group → every household, calls `repos.meals.get_today()`, materialises results, and dispatches via `EventBusService`. The case-5 task **must mirror this structure** rather than invent a new orchestration:

```python
def create_mealplan_timeline_events() -> None:
    event_time = datetime.now(UTC)
    with session_context() as session:
        repos = get_repositories(session)
        groups = repos.groups.page_all(PaginationQuery(page=1, per_page=-1))
        for group in groups.items:
            _create_mealplan_timeline_events_for_group(event_time, session, group.id)

def _..._for_group(event_time, session, group_id):
    repos = get_repositories(session, group_id=group_id)
    households = repos.households.page_all(...)
    for household in households.items:
        _..._for_household(event_time, session, group_id, household.id)

def _..._for_household(event_time, session, group_id, household_id):
    repos = get_repositories(session, group_id=group_id, household_id=household_id)
    mealplans = repos.meals.get_today(tz=local_tz)   # ← case-5 changes tz source
    ...
    event_bus_service.dispatch(... group_id=..., household_id=..., event_type=...)
```

Deltas the case-5 task must introduce vs this precedent:

1. **Per-household `auto_sync_meal_plan_to_shopping=true` filter** — skip households with the flag off.
2. **Per-household tz** — `tzlocal()` (server tz) is wrong for case-5; must read household tz from preferences (a field that does not yet exist — see §3 risk).
3. **30-min time-window gate + once-per-day idempotency** — `create_timeline_events` is `register_daily` (fires once a day). Case-5 needs the **`register_minutely` (every 5 min) or a new register** path with internal gating, because no 30-min bucket exists. Reusing `register_minutely` and short-circuiting based on `(now_in_household_tz - run_time) within (0, 30min]` + `last_auto_synced_at < today_in_household_tz` is the cheapest fit.
4. **Reuse `ShoppingListService.add_recipe_ingredients_to_list`** (see §4) — do not re-implement merging.
5. **Dispatch `EventTypes.mealplan_auto_synced_to_shopping`** with `EventDocumentDataBase` payload containing `shopping_list_id`, `added_item_count`, `skipped_pantry_count` — must add to enum AND `group_events_notifier_options` migration AND `group_events.py` model (see `e52a887e` for the exact template).

### Other scheduler task patterns to copy verbatim

| Task | Pattern lesson |
|------|----------------|
| `purge_group_exports.py` | Uses `NaiveDateTime` + `datetime.now(UTC)`; per-group loop. |
| `delete_old_checked_shopping_list_items.py` | Uses `_create_publish_event` helper to centralise dispatch and *publishes events even from a scheduled context*. Reuse this helper shape. |
| `post_webhooks.py` | Only minutely task that touches multi-household state; demonstrates how to safely open a fresh `session_context()` per tick. |

### Frequency limitation (RISK)

Only three frequency buckets exist: daily, hourly, "minutely" (=5 min). **There is no 30-minute trigger**. The spec says "每 30 分钟跑一次" — implementing that *literally* requires either:

- **(Recommended) Reuse `register_minutely` and gate inside the task** — fires every 5 min, but the body short-circuits unless `(now_in_household_tz - run_time) ∈ [0, 30min)` for that household. This matches the spec's "30 分钟窗口" wording without changing the scheduler shape.
- (Avoid) Adding a new `register_half_hourly` bucket + a new `MINUTES_30 = 30` constant in `scheduler_service.py`. Larger blast radius, more PR scope.

---

## 3. Recent `HouseholdPreferences` / `Food` schema changes

### `HouseholdPreferencesModel` history (`mealie/db/models/household/preferences.py`)

| Hash | Date | Subject | Schema delta |
|------|------|---------|--------------|
| `642c826f` | 2026-05-21 | fix: Protect sensitive data in query filter API (#7629) | Tightened `FilterableColumn` rules — case-5 columns marked `FilterableColumn` will be validated against this. |
| `d2b0681d` | 2026-04-11 | feat: Announcements (#7431) | `+show_announcements: bool default True` |
| `245ca5fe` | 2025-07-31 | feat: Remove "Is Food" and "Disable Amounts" Flags (#5684) | Marked `recipe_disable_amount` as `# Deprecated`; data-fix migration `d7b3ce6fa31a_empty_migration_to_fix_food_flag_data.py` rewrites stale rows in a backfill step. |
| `fd0257c1` | 2024-09-17 | feat: Additional Household Permissions (#4158) | `+lock_recipe_edits_from_other_households` + paired permission. |
| `eb170cc7` | 2024-08-22 | feat: Add Households to Mealie (#3970) | Initial model. |

**Current full column set** (verbatim from `preferences.py`):

```python
id, household_id (FK→households.id), household, group_id (assoc proxy),
private_household, show_announcements,
lock_recipe_edits_from_other_households, first_day_of_week,
recipe_public, recipe_show_nutrition, recipe_show_assets,
recipe_landscape_view, recipe_disable_comments,
recipe_disable_amount,  # Deprecated
```

**Notably absent (relevant to case-5):**

- ❌ No `timezone` column anywhere on household, preferences, group, or group preferences. The only timezone source today is `dateutil.tz.tzlocal()` (server tz) and the env var `TZ` consumed by `DAILY_SCHEDULE_TIME_UTC`. **Adding `timezone: str` to `HouseholdPreferencesModel` is unavoidable** if the spec's "household 时区" requirement is to be met literally.
- ❌ No `time` columns. Existing time-of-day values are stored at the app-settings level (`DAILY_SCHEDULE_TIME: str = "23:45"` in `settings.py:176`, also `HH:MM` string). Precedent for `auto_sync_run_time` is therefore: store as `sa.String` `"HH:MM"`, not `sa.Time`.
- ❌ No `UUID` FK on `HouseholdPreferencesModel`. `auto_sync_target_shopping_list_id` would be the first — needs `sa.ForeignKey("shopping_lists.id", ondelete="SET NULL")` and a thoughtful migration when the target list is deleted.
- ❌ No `NaiveDateTime` last-touched column. `last_auto_synced_at` would be the first; pattern is in `_model_utils/datetime.py`.

### `IngredientFoodModel` history (`mealie/db/models/recipe/ingredient.py`)

Key commits that shape the `is_pantry_staple` decision:

| Hash | Date | Subject | Lesson for case-5 |
|------|------|---------|-------------------|
| `b5c089f5` | 2026-03-09 | feat: Unit standardization / conversion (#7121) | Added `standard_unit` fields to units → affects `(food_id, unit_id)` merge key. |
| `245ca5fe` | 2025-07-31 | Remove "Is Food" and "Disable Amounts" Flags (#5684) | Project actively removes per-food boolean flags. |
| `60d92948` | 2025-11-03 | Add recipe as ingredient (#4800) | A recipe-ingredient row can have no `food_id` — auto-sync must skip / handle. |
| `e9892aba` | 2025-01-13 | **Move "on hand" and "last made" to household (#4616)** | **THE precedent.** Took the previous `on_hand: bool` column on `ingredient_foods` and migrated it to a `households_to_ingredient_foods` many-to-many association (because `ingredient_foods` is **group**-scoped, not household-scoped). `on_hand` is *still present* in the model but marked `# Deprecated`. |
| `a062a4be` | 2024-06-29 | Add the ability to flag a food as "on hand" (#3777) | Original mistake the above PR corrected. Added the deprecated `on_hand: bool` column. |

**Implication for `is_pantry_staple`**:

The spec proposes `Food.is_pantry_staple: bool default false` and the test says "**跨 household 的 food pantry-staple 标记不互相影响**". Those two statements are contradictory in this codebase because `ingredient_foods.group_id` is the only scope on the table — a bool column there is group-wide, not household-wide. Two viable designs:

- **(Spec-literal, wrong by precedent)** Add `is_pantry_staple: bool` as a column on `IngredientFoodModel`. Tests will fail the multi-tenant requirement, *and* this will be flagged in CR as a repeat of the `on_hand` mistake.
- **(Precedent-correct)** Add `households_to_pantry_staple_foods` association table mirroring `households_to_ingredient_foods` from PR #4616. Same shape, same migration style (template: `b9e516e2d3b3_add_household_to_recipe_last_made_…`).

The history strongly recommends the second design, and reviewers (especially michael-genson who authored both #3777 and #4616) will almost certainly request the second.

---

## 4. `ShoppingListService` reuse — the "consolidate" function the spec mentions does not exist

The spec says: *"用 mealie 既有 `consolidate_ingredients`（合并函数，复用 case-3 中可能被修复的逻辑）"*.

**There is no function named `consolidate_ingredients` anywhere in the codebase.** `Get-ChildItem mealie\ -Recurse | Select-String 'consolidate_ingredients|def consolidate'` returns zero results. The merging logic that actually exists:

| Symbol | File | What it does |
|--------|------|--------------|
| `ShoppingListService.can_merge` | `mealie/services/household_services/shopping_lists.py:45` | Returns True iff two items share `food_id` AND (matching `unit_id` OR unit-convertible). Skips checked items. |
| `ShoppingListService.merge_items` | `shopping_lists.py:73` | Combines two items into one `ShoppingListItemUpdate`. |
| `ShoppingListService.get_shopping_list_items_from_recipe` | `shopping_lists.py` (~340) | Converts recipe ingredients → list items, calling `can_merge`/`merge_items` to combine duplicates within a single recipe. |
| `ShoppingListService.add_recipe_ingredients_to_list` | `shopping_lists.py:413` | Entry point: `(list_id, list[ShoppingListAddRecipeParamsBulk]) → (ShoppingListOut, ShoppingListItemsCollectionOut)`. **Already handles deduplication against existing unchecked items in the target list.** This is the function case-5 should call. |
| `merge_quantity_and_unit` | `mealie/services/parser_services/parser_utils/unit_utils.py` | Lower-level helper; called inside `merge_items`. |

**Recommendation**: case-5 task should construct `list[ShoppingListAddRecipeParamsBulk]` from `get_today()` mealplans (one entry per `recipe_id`, with `recipe_increment_quantity` defaulting to the mealplan's serving scale) and call `ShoppingListService(repos).add_recipe_ingredients_to_list(target_list_id, params)`. **Do not re-implement consolidation.** The spec's wording is misleading — flag this to design phase.

---

## 5. Risk hotspots

| # | Risk | Source of evidence | Likely failure mode |
|---|------|-------------------|---------------------|
| R1 | **No per-household timezone storage exists** in the model layer. | `Select-String timezone mealie/db/models/**/*.py` returns only the `_model_utils/datetime.py` doc comment; `households/household.py` has no `timezone` column. | Implementer either (a) silently uses `tzlocal()` like `create_timeline_events`, violating spec, or (b) adds a 4th column to `HouseholdPreferencesModel` that nobody planned for. Either way the design must surface this. |
| R2 | **`is_pantry_staple` as a Food column would repeat the `on_hand` mistake corrected by PR #4616.** | `e9892aba` commit message and current `# Deprecated` marker on `on_hand`. | Spec's "跨 household 不互相影响" test will fail; CR will request a `households_to_pantry_staple_foods` association table. |
| R3 | **Scheduler is documented as single-worker** ("the Scheduler object is only available to a single worker" — `tasks/__init__.py` lines 22-28), but the spec mandates multi-replica safety (`SELECT … FOR UPDATE SKIP LOCKED`). | `tasks/__init__.py` docstring; `app.py:124` `start_scheduler()` is called once in lifespan. | Two outcomes: (a) implementer adds row-level locks and overengineers, or (b) implementer ignores spec. Either should be flagged in spec phase. The `last_auto_synced_at` CAS pattern *is* enough for single-worker idempotency across restarts and is the lower-risk choice. |
| R4 | **No 30-minute scheduler bucket exists.** | `scheduler_service.py:15-17` defines only `MINUTES_DAY`, `MINUTES_5`, `MINUTES_HOUR`. `register_minutely` runs every 5 min. | Naïve implementation calls `register_daily` (fires once) or invents a new bucket. Correct fit is `register_minutely` + internal time-window gating. |
| R5 | **`EventTypes` enum requires a paired migration.** | `event_types.py:17-21`: *"Each event type is represented by a field on the subscriber repository, therefore any changes made here must also be reflected in the database (and likely requires a database migration)."* Reference: `cdc93edaf73d_add_mealplan_updated_and_deleted_to_…`. | Forgetting the migration on `group_events_notifier_options` will pass unit tests but break in fresh-DB integration tests. |
| R6 | **Recipe ingredients can have `food_id=None`.** | PR `60d92948` Add recipe as ingredient (#4800) + the existing dialog code (`RecipeDialogAddToShoppingList.vue`). | If the task merges strictly by `(food_id, unit_id)` it will collapse all foodless ingredients into a single garbage row. `add_recipe_ingredients_to_list` already handles this correctly — another reason to reuse it. |
| R7 | **Unit standardization changed merge semantics in 2026-03.** | PR `b5c089f5` Unit standardization (#7121). `can_merge` now does unit conversion via `UnitConverter`. | Tests asserting "two items with different `unit_id` stay distinct" may now incorrectly merge if both units have a `standard_unit`. Test fixtures must explicitly use units without `standard_unit` to test the negative case. |
| R8 | **`HouseholdPreferencesModel` currently has NO `NaiveDateTime` columns and NO FK columns to non-household tables.** | Visual scan of the model. | First-of-its-kind on this table — easy to forget `nullable=True`, `index=True`, or `ondelete="SET NULL"` (which we need for `auto_sync_target_shopping_list_id` so a deleted shopping list doesn't break preferences). |
| R9 | **Multi-tenant test infrastructure is GROUP-scoped, not household-scoped.** | `tests/multitenant_tests/case_foods.py` and `test_multitenant_cases.py` parameterize by group only. | Case-5 spec requires "household A 的 meal plan **绝不**写入 household B 的 shopping list" — there is no `case_household_meal_plan.py` template; implementer must build new fixtures (or extend `MultiTenant` fixture) for **within-group, cross-household** isolation tests. |
| R10 | **`repos.meals.get_today(tz=…)` exists and uses host-tz default.** | `mealie/repos/repository_meals.py` after PR `8d325198`. | Must pass `tz=household_tz` explicitly; calling `get_today()` with the default `UTC` will silently violate the spec's tz requirement, and **no test will catch it without a non-UTC fixture**. |
| R11 | **Naive datetime storage convention.** | `mealie/db/models/_model_utils/datetime.py` docstring; PR `b0ed242f`. | If `last_auto_synced_at` is declared as `sa.DateTime(timezone=True)` it will pass mypy but fail consistency review. Use `NaiveDateTime`. |
| R12 | **Cross-household shopping-list bug was fixed only in 2025-08 (PR #5892).** | `6cbc308d` touched `shopping_lists.py` for cross-household correctness. | Strong signal that the test matrix for case-5 should explicitly include "household admin can target their own household's list" and "cannot accidentally write to another household's list". |

---

## 6. Prior abandoned auto-sync attempts

Searched: `git log --all --grep="auto-sync" --grep="auto_sync" --grep="autosync" -i` → **zero hits**.
Searched: `git log --all --grep="revert" -i --oneline` → 30 results, none related to meal-plan → shopping-list sync.

**Conclusion**: this feature has *never been attempted before*. The closest existing capability is the **manual** "Add Meal Plan to Shopping List" introduced by:

- `0775072f 2023-11-21 feat: add meal plan to shopping list (#2653)` — purely frontend (`GroupMealPlanDayContextMenu.vue` + `RecipeDialogAddToShoppingList.vue`). It loops over the day's mealplans, opens the bulk-add dialog, and calls `add_recipe_ingredients_to_list` server-side.

So case-5 is essentially **server-side automation of the existing manual flow**. The backend wiring already exists; what's new is (a) the scheduler trigger, (b) per-household preferences, (c) the pantry-staple skip, (d) the event, and (e) the `last_auto_synced_at` idempotency latch.

---

## 7. Cross-perspective questions (for STRUCTURE / DATA / REVIEW perspectives)

1. **For STRUCTURE perspective**: Does the design place the new task under `mealie/services/scheduler/tasks/auto_sync_shopping.py` (spec wording) or somewhere closer to `household_services/`? `create_timeline_events.py` is the closest analogue and lives in `scheduler/tasks/` — consistency suggests sticking with the spec path.
2. **For DATA perspective**: Where should `timezone` live — on `HouseholdPreferencesModel` (new) or on `HouseholdModel` itself? Project convention so far is to put user-visible toggles on preferences and identity/auth fields on the household. `timezone` is debatable; the spec implicitly puts it on preferences ("per-household 可配置"). Need a DATA-perspective ruling so the migration is clean.
3. **For DATA perspective**: Should `is_pantry_staple` be (a) a column on `ingredient_foods` (spec-literal, group-wide, easy) or (b) a `households_to_pantry_staple_foods` association (precedent-correct, per-household, harder)? PR #4616 is decisive evidence for (b); please confirm.
4. **For STRUCTURE perspective**: Should the manual `POST /api/households/preferences/auto-sync-shopping/run-now` route live in `mealie/routes/households/controller_household_self_service.py` (preferences live there) or under a new `controller_auto_sync.py`? Most household-scoped one-off actions are added to existing controllers — verify.
5. **For REVIEW perspective**: Should we add the event-type `mealplan_auto_synced_to_shopping` *with* a default-true subscriber column, or default-false (consistent with `mealplan_entry_updated` from PR `e52a887e`)?
6. **For REVIEW perspective**: The spec calls out `SELECT … FOR UPDATE SKIP LOCKED` for multi-replica safety, but the scheduler is documented as single-worker. Is the spec's expectation that we (a) implement DB row locking anyway as future-proofing, (b) document that mealie's scheduler is single-worker and rely on `last_auto_synced_at` CAS, or (c) escalate the multi-replica scheduler story as a separate workstream?
7. **For REVIEW perspective**: What's the desired behaviour when `auto_sync_target_shopping_list_id` references a shopping list that has since been deleted? `ON DELETE SET NULL` + fall through to "first active list" matches the spec wording but means a deletion can silently change the auto-sync target.
8. **For STRUCTURE perspective**: `ShoppingListService.add_recipe_ingredients_to_list` returns `(ShoppingListOut, ShoppingListItemsCollectionOut)`. The pantry-staple filter has to happen **before** this call (filter the incoming `ShoppingListAddRecipeParamsBulk` list) or **inside** `get_shopping_list_items_from_recipe`. Pre-filter is less invasive; inside is more reusable for case-3. Which scope is in play?
9. **For DATA perspective**: For the "**within-group, cross-household** isolation" test requirement, do we extend `tests/fixtures/fixture_multitenant.py` (`MultiTenant`) to provision two households inside the same group, or add a new `MultiHousehold` fixture? Current fixture is single-household-per-group.
10. **For REVIEW perspective**: The `consolidate_ingredients` symbol the spec names does not exist. Should the spec be amended to reference `ShoppingListService.add_recipe_ingredients_to_list` + `can_merge`/`merge_items`, or do we keep the spec wording and accept the implementer will have to discover the actual API?

---

*End of history perspective. All git commands rerunnable from `C:\Users\v-liyuanjun\Downloads\mealie` with `--no-pager`.*
