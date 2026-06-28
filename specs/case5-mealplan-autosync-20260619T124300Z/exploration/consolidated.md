# Case 5 — Consolidated Exploration (Stage 3.5)

> **Purpose**: Dedupe, reconcile, and flag conflicts across the four perspectives (data / api / test / history) for the Meal Plan → Shopping List auto-sync feature on Mealie.
> All line references are **re-verified** against `C:\Users\v-liyuanjun\Downloads\mealie\` (commit ref per `context/grounding.md`).
> Sources: `data_perspective.md`, `api_perspective.md`, `test_perspective.md`, `history_perspective.md`, plus first-hand inspection of the listed Mealie files.

---

## 1. Cross-perspective dedup matrix

Each row below is a fact / concern that surfaced in two or more perspectives. The consolidated view is the canonical statement that the spec must encode.

| # | Topic | Where it appears | Consolidated statement |
|---|---|---|---|
| C1 | Three new `HouseholdPreferences` fields | data §1, api §1, test §6.1, history "preferences" | Add `auto_sync_meal_plan_to_shopping: bool` (default false), `auto_sync_target_shopping_list_id: GUID|None`, `auto_sync_run_time: str "HH:MM"` (default "00:00") to `mealie/db/models/household/preferences.py:16-44` AND propagate through `mealie/schema/household/household_preferences.py:10-40` (UpdateHouseholdPreferences cascades to Create/Save/Read). |
| C2 | Two extra fields the spec **implies** but doesn't enumerate | data §1, data §6 | Add `last_auto_synced_at: NaiveDateTime|None` (idempotency CAS marker) and `timezone: str|None` (per-household tz; default None → fall back to UTC). Both go on `HouseholdPreferencesModel` for single-row CAS. |
| C3 | `Food.is_pantry_staple` is genuinely missing | data §3, api §3, test §6.5, history "Food / IngredientFoodModel" | Add `is_pantry_staple: bool` (default false, non-nullable) to `IngredientFoodModel` at `mealie/db/models/recipe/ingredient.py:153-219` — there is **only** the deprecated `on_hand` column at line 192. Migration mirrors `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py:24-46`. |
| C4 | "consolidate_ingredients" does not exist as a named symbol | data §4, history §H4, api §4 | The de-facto consolidation pipeline is `ShoppingListService.can_merge` (`shopping_lists.py:45-71`) + `merge_items` (`73-128`) + `bulk_create_items` (`154-223`) + `get_shopping_list_items_from_recipe` (`323-411`) + `add_recipe_ingredients_to_list` (`413-455`). **Highest-level reuse seam** = `add_recipe_ingredients_to_list`. Pantry filter must run **before** ingredients enter this pipeline (pass filtered `recipe_ingredients` into `get_shopping_list_items_from_recipe`). |
| C5 | Recipe → shopping list back-link | data §5, api §4, test §6.2 | `recipe_references` are populated automatically by `get_shopping_list_items_from_recipe` (lines 377-384, builds `ShoppingListItemRecipeRefCreate(recipe_id, recipe_quantity, recipe_scale, recipe_note)`). No mealplan-id back-link exists in the model; the event payload (C9) is the only mealplan→list trace. |
| C6 | Scheduler bucket — "every 30 min" has **no native bucket** | api §4, test §2.1, history #6 / #11 | Existing buckets: `MINUTES_DAY=1440`, `MINUTES_HOUR=60`, `MINUTES_5=5` (`scheduler_service.py:15-17`). `register_minutely` actually fires every 5 minutes. **Decision: register on minutely, gate inside the task** with an `auto_sync_run_time` ± 30 min window check. Avoids touching the scheduler core (historically fragile per PR #3820/#3914/#3645). |
| C7 | Per-household timezone column has **never existed** | data §6, test "section 5", history Risk #2 | Add a `timezone: str|None` column on `HouseholdPreferencesModel`. Validate via `zoneinfo.ZoneInfo` in the Pydantic schema; fallback to `"UTC"` when None. Pass into `RepositoryMeals.get_today(tz=ZoneInfo(prefs.timezone or "UTC"))` at `mealie/repos/repository_meals.py:11-22`. |
| C8 | `LastAutoSyncedAt` storage location and concurrency | data §1, test §8 Q7, api §"Scheduler integration seam", history Pattern B | Single column `last_auto_synced_at: NaiveDateTime|None` on `HouseholdPreferencesModel`. Multi-replica safety via **CAS UPDATE** (`UPDATE household_preferences SET last_auto_synced_at = :now WHERE id = :id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_start_utc)` → if `rowcount == 0` skip). Works on SQLite + Postgres; sidesteps `FOR UPDATE SKIP LOCKED` (SQLite-incompatible per history H5). |
| C9 | New `EventTypes` member + payload + **subscriber migration** | api §5, test §4.2, history #10 | Add `meal_plan_auto_synced_to_shopping = auto()` to `EventTypes` (`event_types.py:13-60`). Add new `EventMealPlanAutoSyncedData(EventDocumentDataBase)` with `document_type = EventDocumentType.shopping_list`, `operation = EventOperation.create`, `household_id: UUID4`, `shopping_list_id: UUID4`, `added_item_count: int`, `skipped_pantry_count: int`. **Hidden cost (per docstring at `event_types.py:14-22`)**: a Boolean column `meal_plan_auto_synced_to_shopping` must be added to `GroupEventNotifierOptionsModel` (`mealie/db/models/household/events.py:15-58`) via alembic — pattern mirrors `2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py:19-50`. |
| C10 | "PATCH" wording is naming drift; existing route is **PUT** | api §1, test §6.1 Q1, intent skeptic challenge 6 | The existing endpoint is `@router.put("/preferences")` at `controller_household_self_service.py:58-62`. The spec's "PATCH" is loose phrasing for "update". **Decision: add new fields to `UpdateHouseholdPreferences`; the existing PUT picks them up unchanged.** No new endpoint for preferences. |
| C11 | Manual-trigger endpoint | api §2, test §B, spec §3 | New endpoint `POST /api/households/preferences/auto-sync-shopping/run-now` returning a `200` (not 202) with `AutoSyncRunResult { added_count, skipped_pantry_count, target_list_id, run_at }`. Auth: `self.checks.can_manage_household()` (per `checks.py:23-26`). Runs the sync **synchronously** (response carries result); event dispatch is the only async piece. Bypasses `last_auto_synced_at` daily limit but still updates it. |
| C12 | Test directory drift | test §7 "Note", test §8 Q2, spec §5 | Spec says `tests/unit_tests/services/scheduler/test_auto_sync.py`. **Actual convention**: `tests/unit_tests/services_tests/scheduler/tasks/test_auto_sync.py` (verified via `Get-ChildItem` on existing scheduler tests). Use existing convention. |
| C13 | i18n keys | spec §4, api §5 Q3, intent verification 11 | Add `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today` to `mealie/lang/messages/en-US.json` only (current file: 95 lines, no `auto-sync` namespace). Per `.github/copilot-instructions.md`, **never** edit non-English locales (Crowdin-managed). |
| C14 | Cross-household FK safety for `auto_sync_target_shopping_list_id` | data §"Cross-perspective Q2", api §1 | The FK constraint can't enforce that the list belongs to this household. Validation runs in the PUT route or via a Pydantic `@field_validator`: look up the list, reject (HTTP 403) if `list.household_id != self.household_id`. Pattern at `controller_household_self_service.py:73-77`. Use `ondelete="SET NULL"` so deletions don't break FK integrity. |
| C15 | Pantry-staple permission model + scope | data §3, history #2 (`a062a4be`) & #3 (`e9892aba`), test §C | Spec literally says "Food.is_pantry_staple" → group-shared flag. **Historical risk**: commit `e9892aba` (#4616) explicitly deprecated `on_hand` because per-household scope was needed. Case-5 follows the spec literally (group-level) but flags this as `needs_clarification` so reviewers/spec author can confirm. Permission gate: `can_organize` (existing for foods); reuse the existing PUT `/api/foods/{item_id}` (`mealie/routes/unit_and_foods/foods.py:69-73`) — extend `CreateIngredientFood` (`recipe_ingredient.py:92-95`) with `is_pantry_staple: bool = False`. The "admin" routing the spec mentions in §4 is satisfied by `can_organize`. |
| C16 | Iteration shape for scheduler task | api §"Scheduler integration seam", history Pattern A | Mirror `delete_old_checked_shopping_list_items.py:54-75` exactly: `session_context()` → iterate groups (`groups.page_all`) → iterate households (`households.page_all`) → construct `household_repos = get_repositories(session, group_id, household_id)` → `ShoppingListService(household_repos)`. Top-level function `auto_sync_meal_plan_to_shopping()` takes no args. |
| C17 | Tenant isolation via repo scoping | data §7, data §8, test §3 | `RepositoryMeals` and shopping-list repos are `HouseholdRepositoryGeneric`-scoped at construction (`repository_factory.py:240-345`). As long as the per-household block constructs `repos` with the correct `(group_id, household_id)`, cross-tenant leakage is structurally blocked. Multitenant test must still assert this — see test perspective §C. |
| C18 | Empty-meal-plan response shape | api §"Cross-perspective Q2", test §8 Q3, spec §5 | Return `200` with `{ added_count: 0, skipped_pantry_count: 0, target_list_id, run_at }`. Consistent with `bulk_create_items` returning an empty collection rather than 204. The i18n key `auto-sync.no-meal-plan-today` is logged (not raised) in scheduler context; **not** raised by the run-now endpoint (which simply returns 0 counts). |
| C19 | Default target list resolution | api §"Scheduler integration seam" point 5, spec §1 | When `auto_sync_target_shopping_list_id is None`, pick `repos.group_shopping_lists.page_all(PaginationQuery(page=1, per_page=1, order_by="created_at", order_direction="asc"))`. **Definition of "first active main list"**: oldest-created shopping list belonging to this household. If none exists, log i18n key `auto-sync.no-target-list` and skip the household. |
| C20 | Append strategy = existing `bulk_create_items` semantics | data §4, test §6.2, api §"Scheduler integration seam" | Existing logic (`shopping_lists.py:180-203`): for each new item, find any unchecked existing item in the target list with the same `(food_id, unit_id)` via `can_merge`; if found, `merge_items` accumulates `quantity` and merges `recipe_references` by `recipe_id`; otherwise insert as new row. Case-5 reuses this verbatim — no DIY consolidation. |

---

## 2. Existing-code gap analysis

| Domain | Existing | What's missing (needs to be ADDED in case-5) | Files affected |
|---|---|---|---|
| **HouseholdPreferences model** | 10 columns at `preferences.py:18-40` | 5 new columns: `auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id` (FK), `auto_sync_run_time`, `last_auto_synced_at`, `timezone` | `mealie/db/models/household/preferences.py:16-44` |
| **HouseholdPreferences schema** | `UpdateHouseholdPreferences` 10 fields at `household_preferences.py:10-22` | Same 5 fields (Update cascades to Create/Save/Read). Add `@field_validator` for `auto_sync_run_time` (HH:MM regex) and `timezone` (ZoneInfo validity). Cross-household FK check for `auto_sync_target_shopping_list_id` in route. | `mealie/schema/household/household_preferences.py:10-40` |
| **HouseholdPreferences migration** | none for these fields | NEW alembic migration adding 5 columns + populate defaults (FALSE / "00:00" / NULL). Template = `2024-09-02-21.39.49_be568e39ffdf_added_household_recipe_lock_setting_and_.py:21-75`. Depends on current head `2187537c52b8`. | `mealie/alembic/versions/<new>_add_auto_sync_to_household_preferences.py` |
| **Food model** | Only deprecated `on_hand` at `ingredient.py:192` | NEW non-nullable Boolean `is_pantry_staple` with `default=False`. | `mealie/db/models/recipe/ingredient.py:153-219` |
| **Food schema** | No staple-related field on `CreateIngredientFood` (`recipe_ingredient.py:92-95`) | Add `is_pantry_staple: bool = False` to `CreateIngredientFood`; propagates to `SaveIngredientFood`/`IngredientFood`. | `mealie/schema/recipe/recipe_ingredient.py:92-115` |
| **Food migration** | none | NEW alembic migration mirroring `32d69327997b_add_staple_flag_to_foods.py:24-46` (nullable add → UPDATE rows to FALSE → set non-nullable). | `mealie/alembic/versions/<new>_add_is_pantry_staple_to_ingredient_foods.py` |
| **Food admin route** | `PUT /api/foods/{item_id}` at `foods.py:69-73`, gated by `can_organize` | **No change to route signature** — body type `CreateIngredientFood` already cascades the new field. Verified: spec §4 wording "admin/foods routes (允许管理员标记)" is satisfied by the existing `can_organize` gate. | `mealie/routes/unit_and_foods/foods.py:69-73` (untouched; schema extension carries it) |
| **HouseholdPreferences PATCH/PUT route** | `@router.put("/preferences")` at `controller_household_self_service.py:58-62` | **No change to route signature** — body type `UpdateHouseholdPreferences` already cascades the new fields. Add a small cross-household FK validator block before the `update(...)` call. | `mealie/routes/households/controller_household_self_service.py:58-62` |
| **Manual trigger route** | none | NEW `POST /api/households/preferences/auto-sync-shopping/run-now` on `HouseholdSelfServiceController`. Returns `AutoSyncRunResult`. Gated by `can_manage_household()`. | `mealie/routes/households/controller_household_self_service.py:1-92` (add method); new schema `AutoSyncRunResult` in `mealie/schema/household/auto_sync.py` (or extend `household_preferences.py`) |
| **Scheduler task file** | none | NEW `mealie/services/scheduler/tasks/auto_sync_shopping.py` with `auto_sync_meal_plan_to_shopping()` top-level entrypoint, mirroring `delete_old_checked_shopping_list_items.py:54-75` and `create_timeline_events.py:117-134` shape. | `mealie/services/scheduler/tasks/auto_sync_shopping.py` (new) |
| **Tasks `__init__`** | exports 8 task callables at `tasks/__init__.py:1-19` | Add `from .auto_sync_shopping import auto_sync_meal_plan_to_shopping` + entry in `__all__`. | `mealie/services/scheduler/tasks/__init__.py:1-19` |
| **App startup registration** | `register_minutely(tasks.post_group_webhooks)` at `app.py:134-136` | Add `tasks.auto_sync_meal_plan_to_shopping` to the same `register_minutely(...)` call (extra positional arg). | `mealie/app.py:134-136` |
| **EventTypes enum** | 22 members at `event_types.py:24-60` | New member `meal_plan_auto_synced_to_shopping = auto()`. | `mealie/services/event_bus_service/event_types.py:13-60` |
| **Event payload class** | concrete `Event*Data` at `event_types.py:94-176` | New `EventMealPlanAutoSyncedData(EventDocumentDataBase)` with `document_type = EventDocumentType.shopping_list`, `operation = EventOperation.create`, plus `household_id`, `shopping_list_id`, `added_item_count`, `skipped_pantry_count`. | `mealie/services/event_bus_service/event_types.py:94-176` |
| **Event subscriber column** | 22 Boolean fields at `events.py:23-50` | New column `meal_plan_auto_synced_to_shopping: bool default False non-null` on `GroupEventNotifierOptionsModel` at `mealie/db/models/household/events.py:15-58`. | `mealie/db/models/household/events.py:15-58` + NEW alembic migration mirroring `2026-03-26-20.48.28_cdc93edaf73d_…:19-50` |
| **i18n strings** | no `auto-sync` namespace in `en-US.json:1-95` | 3 new keys: `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today`. en-US only. | `mealie/lang/messages/en-US.json:1-95` |
| **Unit tests** | scheduler tests at `tests/unit_tests/services_tests/scheduler/tasks/test_create_timeline_events.py:1-254` etc. | New `tests/unit_tests/services_tests/scheduler/tasks/test_auto_sync.py` (≥6 tests). | new file |
| **Integration tests** | preference tests at `tests/integration_tests/user_household_tests/test_household_perferences.py:1-63`; shopping list tests at `test_group_shopping_lists.py:1-1353` | New `tests/integration_tests/user_household_tests/test_auto_sync_run_now.py` (≥6 tests). | new file |
| **Multitenant tests** | harness at `tests/multitenant_tests/case_abc.py:1-31` + `test_multitenant_cases.py:1-74` | New `tests/multitenant_tests/test_auto_sync_isolation.py` (≥3 tests covering cross-group + cross-household same-group + pantry-staple isolation). | new file |
| **Fixtures** | `tests/fixtures/fixture_users.py:1-351`, `fixture_shopping_lists.py:1-95` | OPTIONAL fixture in `tests/fixtures/fixture_auto_sync.py` to seed `autosync_household` (preference toggled on, target list, today's meal plan). | new file (optional) |

---

## 3. Critical conflicts (must be resolved before coding)

These items had **active disagreement** between perspectives (not just additive expansions). Resolutions below are this consolidator's reading; the ones still ambiguous become `needs_clarification` entries in `spec.md`.

### CC1 — Verb on the preferences endpoint (PATCH vs PUT)
- **Spec §1**: "`PATCH /api/households/preferences`".
- **Code reality** (`controller_household_self_service.py:58`): `@router.put("/preferences")`.
- **Test reality** (`test_household_perferences.py:43,56`): uses `api_client.put`.
- **Resolution**: **PUT** wins. Spec wording is naming drift, not a behavioral requirement. Add new fields to `UpdateHouseholdPreferences`; existing PUT picks them up. (Echoed by intent skeptic challenge 6.)

### CC2 — `is_pantry_staple` scope: per-Food (global) vs per-Household (M2M)
- **Spec §4** (literal): "Food 模型新增 `is_pantry_staple: bool`". Group-shared.
- **History #3 / `e9892aba`** (#4616, 2025-01-13): explicitly moved `on_hand` *off* `IngredientFoodModel` to a per-household M2M `households_with_ingredient_food` (`ingredient.py:160-162`) because "on hand" was conceptually per-household.
- **Spec §5 test bullet** (literal): "跨 household 的 food pantry-staple 标记不互相影响" — implies per-household behaviour.
- **Resolution**: Follow the spec literally for case-5 (group-shared `is_pantry_staple` on `IngredientFoodModel`) but flag as `needs_clarification`. The §5 multitenant test then becomes "marks set in group A's food don't bleed into group B" (which is satisfied by group-scoping at `ingredient.py:158`), NOT "household A marks don't bleed into household B" (which would require M2M and contradict §4). If spec author wants per-household, redo as M2M before coding.

### CC3 — Scheduler bucket (extend vs reuse)
- **Spec §2**: "每 30 分钟跑一次" + "必须复用既有 scheduler 抽象, 不要新建并行 scheduler".
- **Code reality** (`scheduler_service.py:15-17`): only `MINUTES_5`, `MINUTES_HOUR`, `MINUTES_DAY` exist.
- **History Risk #5**: extending `SchedulerService` with a new bucket has historically caused off-by-an-hour bugs.
- **Resolution**: Register on existing `register_minutely` (5-min cadence). Inside the task, gate execution to households whose `auto_sync_run_time` falls within the current 30-min window. `last_auto_synced_at` CAS guarantees idempotency even if the window is hit by multiple ticks. No scheduler-core surface change.

### CC4 — Manual trigger response shape (200 vs 202 vs 204)
- **Spec §3**: "返回结果: `{ added_count, skipped_pantry_count, target_list_id, run_at }`" → implies 200 with body.
- **Spec §5 integration test**: "当天无 meal plan 时返回 204 / 0 added" → ambiguous.
- **Existing pattern** (`controller_group_recipe_actions.py:70`): `status_code=202` with BackgroundTasks for fire-and-forget.
- **Existing pattern** (`admin_maintenance.py:89-98`): synchronous POST returning `SuccessResponse` (200).
- **Resolution**: **200 with `AutoSyncRunResult`** in **all** cases including empty meal plan (`added_count=0`). Sync work is synchronous; only event dispatch is backgrounded via `EventBusService.as_dependency`. Matches the spec §3 explicit shape; 204 path is dropped (logged warning instead).

### CC5 — Test directory drift
- **Spec §5**: `tests/unit_tests/services/scheduler/test_auto_sync.py`.
- **Codebase reality**: every scheduler test lives at `tests/unit_tests/services_tests/scheduler/tasks/test_*.py` (verified).
- **Resolution**: Use the **existing convention** (`services_tests`, plural, plus `tasks/`). pytest collection relies on `conftest.py` in the existing paths.

### CC6 — Manual trigger and `last_auto_synced_at`
- **Spec §3** (literal): "绕过 `LastAutoSyncedAt` 限制, 但仍更新它" — translated: bypass the daily limit, but still update the marker.
- **No conflict in code** — straightforward semantics.
- **Resolution**: Run-now ignores any existing `last_auto_synced_at` value (does not check the CAS guard), performs the sync, and sets `last_auto_synced_at = NOW(UTC)` on completion. This means a subsequent scheduler tick within the same household-local day will skip (because the marker is now today). Flag as `needs_clarification` only to confirm interpretation (per user instruction).

### CC7 — Event payload contains `household_id` (duplication vs leak prevention)
- **Code reality** (`event_bus_service.py:66-96`): `dispatch(...)` already takes `household_id` as a parameter; the dispatched event is scoped per-household at L92-96.
- **Spec §2 step 7** (literal): payload should contain "household_id, shopping_list_id, added_item_count, skipped_pantry_count".
- **Resolution**: Include `household_id` redundantly in `EventMealPlanAutoSyncedData` for self-contained payloads (matches subscriber-side schema expectations and prevents cross-household payload accidents). The dispatcher's `household_id` argument is the routing key; the payload field is the audit record.

### CC8 — `consolidate_ingredients` symbol name
- **Spec §2 step 3** (literal): "用 mealie 既有 `consolidate_ingredients`(合并函数, 复用 case-3 中可能被修复的逻辑) 按 (food_id, unit_id) 合并".
- **Code reality**: **no top-level function literally called `consolidate_ingredients`** (grep verified). Semantics live inside `ShoppingListService.bulk_create_items` (`shopping_lists.py:154-223`) which inline-calls `can_merge` + `merge_items`.
- **Resolution**: Call `ShoppingListService.add_recipe_ingredients_to_list` (`shopping_lists.py:413-455`) — the highest-level seam that internally invokes the consolidation. Document in `self_concerns` that this is a coupling point with case-3 (if case-3 ships a refactored top-level `consolidate_ingredients`, case-5 should call it; otherwise call the seam). Coding agent must not roll its own consolidation.

---

## 4. Items the perspectives **agree** on (no conflict, no resolution needed)

For completeness — these are facts on which all four perspectives align and which feed directly into the spec without further debate:

1. The task structure mirrors `delete_old_checked_shopping_list_items.py:54-75` (groups → households → per-household work). [api, history, test all cite this.]
2. `RepositoryMeals.get_today(tz=...)` at `repos/repository_meals.py:11-22` is the source of today's meal plans. [data, api, history.]
3. `recipe_references` are auto-populated by `get_shopping_list_items_from_recipe:377-384`. [data, api.]
4. Tests must call the task function **synchronously**, never await `@repeat_every`. [test §5, history Pattern E.]
5. Multi-tenant tests are non-negotiable per spec §5 and per history Risk #1. [test, history, data §8.]
6. `EventTypes` additions require a DB migration on `group_events_notifier_options` per `event_types.py:14-22` docstring. [api, test, history #10.]
7. en-US only for i18n. [api §"Cross-perspective Q3", Mealie `.github/copilot-instructions.md`.]
8. Use `INTERNAL_INTEGRATION_ID = "mealie_generic_user"` (`event_types.py:10`) for scheduler-originated events; use `DEFAULT_INTEGRATION_ID = "generic"` (`schema/user/user.py:24`) for user-triggered. [api §5, history.]

---

## 5. Open questions deferred to spec / coding stages

These become `needs_clarification` entries in `spec.md` (Section "needs_clarification"):

1. **CC2** — Should `is_pantry_staple` be per-household (M2M) or per-Food (group-shared)? (Spec literal says per-Food; history says per-Food was a known mistake.)
2. **CC6** — Should the manual trigger reset `last_auto_synced_at`? (Spec wording "但仍更新它" interpreted as "yes, set to now"; needs confirmation.)
3. **Default target list also archived/deleted** — when `auto_sync_target_shopping_list_id` is NULL and the fallback "first active main list" is also archived/deleted, return graceful error (`auto-sync.no-target-list` i18n) or skip silently? (Overlap with case-2 archived-list semantics.)

---

## 6. Self-concerns flagged for coding

1. **Coupling to case-3 consolidation refactor** — case-5 calls `add_recipe_ingredients_to_list`. If case-3 ships a separate `consolidate_ingredients` symbol, case-5 should be updated to call it. Without case-3 landed, case-5 still works because the consolidation is internal.
2. **Timezone library** — `zoneinfo.ZoneInfo` is stdlib (Python 3.9+). Mealie runs Python 3.12. No new dependency needed. Validate string via `try: ZoneInfo(tz)` in the Pydantic field validator.
3. **`last_auto_synced_at` storage layer** — column on `HouseholdPreferencesModel`. CAS works on SQLite + Postgres without `FOR UPDATE SKIP LOCKED`. The `WHERE last_auto_synced_at < :today_start_utc` clause is the "did we win?" predicate; `rowcount == 0` means skip.
