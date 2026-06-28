# Case 5 — API Perspective (Stage 3)

> Scope: API surface area (routes, routers, controllers, dispatch seams) needed
> to deliver Case 5 "Meal Plan 自动联动 Shopping List". Every file path and line
> range below has been opened and verified in `C:\Users\v-liyuanjun\Downloads\mealie\`.

---

## 1. Existing `PATCH /api/households/preferences` route ⚠️ DISCREPANCY

### 1.1 Actual existing route is **PUT**, not PATCH

| Field | Value |
|---|---|
| Path | `mealie/routes/households/controller_household_self_service.py` |
| Symbols | `HouseholdSelfServiceController.update_household_preferences`, `get_household_preferences` |
| Line ranges (VERIFIED) | `54–62` (both endpoints); router decl at `16` |
| Importance | **Critical** — entry point for new preference fields |
| Reason | Spec asks for `PATCH /api/households/preferences`. The codebase only has `PUT /preferences` taking a *full* `UpdateHouseholdPreferences` body. Adding a PATCH variant is a **new pattern** for this domain (PATCH currently only used on recipe routes — see §6). |

```python
# controller_household_self_service.py, verified L54–62
@router.get("/preferences", response_model=ReadHouseholdPreferences)
def get_household_preferences(self):
    return self.household.preferences

@router.put("/preferences", response_model=ReadHouseholdPreferences)
def update_household_preferences(self, new_pref: UpdateHouseholdPreferences):
    self.checks.can_manage_household()
    return self.repos.household_preferences.update(self.household_id, new_pref)
```

Router prefix is `/households` (L16), aggregated under `/api` in `mealie/routes/__init__.py` L20 → final URL `PUT /api/households/preferences`.

### 1.2 Preference schema seam (where new fields go)

| Field | Value |
|---|---|
| Path | `mealie/schema/household/household_preferences.py` |
| Symbols | `UpdateHouseholdPreferences`, `CreateHouseholdPreferences`, `SaveHouseholdPreferences`, `ReadHouseholdPreferences` |
| Line ranges (VERIFIED) | `10–22` (Update — add fields here), `25` (Create extends Update), `28–29` (Save), `32–40` (Read) |
| Importance | **Critical** — Pydantic schema for the three new fields. |
| Reason | Adding fields here automatically propagates to Create/Save/Read via subclassing. Per `.github/copilot-instructions.md`, after this change `task dev:generate` must be run to regenerate TS types. |

### 1.3 Preference SQLAlchemy model seam

| Field | Value |
|---|---|
| Path | `mealie/db/models/household/preferences.py` |
| Symbols | `HouseholdPreferencesModel` |
| Line ranges (VERIFIED) | `16–44` whole class; bool columns at `26–37`; `__init__` with `@auto_init()` at `42–44` |
| Importance | **Critical** — DB column seam for new fields, target of alembic migration. |
| Reason | All three new fields (`auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, `auto_sync_run_time`) need columns added here. `@auto_init` means just adding `mapped_column` is sufficient — no constructor change needed. |

### 1.4 Admin-side preferences PUT (cross-household admin path)

| Field | Value |
|---|---|
| Path | `mealie/routes/admin/admin_management_households.py` |
| Symbols | `AdminHouseholdManagementRoutes.update_one` |
| Line ranges (VERIFIED) | `63–77`; `UpdateHouseholdAdmin` import at `8–13` |
| Importance | **Medium** — system-admin can also update preferences via `PUT /api/admin/households/{item_id}`. Validate new fields flow through correctly. |
| Reason | Uses `UpdateHouseholdAdmin` (mealie/schema/household/household.py:60–62), which embeds `UpdateHouseholdPreferences` as `preferences`. Adding fields in §1.2 propagates here automatically. |

---

## 2. Existing scheduler pattern — `mealie/services/scheduler/`

### 2.1 `@repeat_every` decorator + scheduler runner

| Field | Value |
|---|---|
| Path | `mealie/services/scheduler/runner.py` |
| Symbols | `repeat_every` |
| Line ranges (VERIFIED) | `19–83` (whole module); decorator signature `19–48`; inner `loop()` `60–77` |
| Importance | **Critical** — the only periodic-task primitive Mealie has. |
| Reason | Spec mandates "用 mealie 既有的 `@scheduled` 装饰器". Note: actual decorator is `@repeat_every(minutes=...)`, not `@scheduled`. Takes only `minutes: float` (no cron syntax). |

### 2.2 SchedulerService — bucketed runners

| Field | Value |
|---|---|
| Path | `mealie/services/scheduler/scheduler_service.py` |
| Symbols | `SchedulerService.start`, `run_daily`, `run_hourly`, `run_minutely`, `schedule_daily` |
| Line ranges (VERIFIED) | `20–27` (`SchedulerService`), `30–53` (`schedule_daily`), `63–67` (`run_daily`), `70–74` (`run_hourly`), `77–81` (`run_minutely`); constants `MINUTES_DAY=1440`, `MINUTES_HOUR=60`, `MINUTES_5=5` at `15–17` |
| Importance | **Critical** — only three buckets exist; no native 30-min bucket. |
| Reason | ⚠️ **`run_minutely` actually fires every 5 minutes** (constant `MINUTES_5`), not every minute. There is **no 30-minute bucket**. To meet the spec's "每 30 分钟跑一次" we must either (a) register on `run_minutely` (5-min) and gate inside the task with a "last_run_at >= 30min ago" check, or (b) add a new `MINUTES_30` constant + `run_half_hourly` (cleaner; mirrors existing pattern). |

### 2.3 SchedulerRegistry — registration API

| Field | Value |
|---|---|
| Path | `mealie/services/scheduler/scheduler_registry.py` |
| Symbols | `SchedulerRegistry.register_daily`, `register_hourly`, `register_minutely`, `_daily`, `_hourly`, `_minutely` |
| Line ranges (VERIFIED) | `8–59`; lists at `13–15`; register methods at `23–48` |
| Importance | **Critical** — where the new task gets wired. |
| Reason | If we add `MINUTES_30`/`run_half_hourly`, we also need `_half_hourly: list[Callable]` and `register_half_hourly(*callbacks)`. Otherwise just call `register_minutely(auto_sync_shopping_task)`. |

### 2.4 Task module pattern — existing tasks

| Field | Value |
|---|---|
| Path | `mealie/services/scheduler/tasks/` (directory) |
| Symbols | `tasks/__init__.py`, `tasks/post_webhooks.py`, `tasks/delete_old_checked_shopping_list_items.py`, `tasks/create_timeline_events.py` |
| Line ranges (VERIFIED) | `tasks/__init__.py` L1–28 (imports + `__all__`); `tasks/create_timeline_events.py` L25–134 (full pattern of group→household iteration); `tasks/post_webhooks.py` L24–79 |
| Importance | **Critical** — the new `auto_sync_shopping.py` must follow this shape. |
| Reason | Template: open `session_context()`, iterate groups (`repos.groups.page_all(...)`), then households (`get_repositories(session, group_id=group.id).households.page_all(...)`), then per-household get scoped repos via `get_repositories(session, group_id=g, household_id=h)`. `create_timeline_events.py:25–134` is the closest analog — it also reads today's meal plan and dispatches events. |

### 2.5 Scheduler registration in `app.py`

| Field | Value |
|---|---|
| Path | `mealie/app.py` |
| Symbols | `start_scheduler`, `lifespan_fn` |
| Line ranges (VERIFIED) | `124–144` (`start_scheduler`); `54–93` (`lifespan_fn`); registration calls at `125–140` |
| Importance | **Critical** — where the new task must be wired up. |
| Reason | The new task must be added to `SchedulerRegistry.register_minutely(...)` (or new `register_half_hourly` bucket). Without this, the task is dead code. |

### 2.6 ⚠️ Single-worker scheduler caveat

| Field | Value |
|---|---|
| Path | `mealie/services/scheduler/tasks/__init__.py` |
| Symbols | docstring |
| Line ranges (VERIFIED) | `21–28` (docstring) |
| Importance | **High** — directly contradicts spec requirement for multi-replica safety. |
| Reason | Docstring at L21–28 reads: *"the Scheduler object is only available to a single worker"*. Mealie's scheduler is **in-process, not cross-process**. The spec demands `SELECT ... FOR UPDATE SKIP LOCKED` or `LastAutoSyncedAt` CAS for multi-replica safety — this is a *new* concern not handled by the existing scheduler. Cross-perspective question for data layer. |

---

## 3. Existing event bus dispatch pattern — `mealie/services/event_bus_service/`

### 3.1 `EventBusService.dispatch` — public API

| Field | Value |
|---|---|
| Path | `mealie/services/event_bus_service/event_bus_service.py` |
| Symbols | `EventBusService`, `EventBusService.dispatch`, `EventBusService.as_dependency` |
| Line ranges (VERIFIED) | `42–105` (whole class); `dispatch` at `66–96`; `as_dependency` at `98–105` |
| Importance | **Critical** — the only public dispatch entrypoint. |
| Reason | Signature: `dispatch(integration_id, group_id, household_id, event_type: EventTypes, document_data: EventDocumentDataBase, message: str = "")`. From a scheduled task instantiate as `EventBusService(session=session)` (per `tasks/post_webhooks.py:72`). From a route controller use the inherited `self.publish_event(...)` via `BaseCrudController` (mealie/routes/_base/base_controllers.py:192–214). |

### 3.2 `EventTypes` enum — add new event type here

| Field | Value |
|---|---|
| Path | `mealie/services/event_bus_service/event_types.py` |
| Symbols | `EventTypes`, `EventDocumentDataBase`, `EventDocumentType`, `EventOperation`, `Event`, `EventBusMessage` |
| Line ranges (VERIFIED) | `EventTypes` enum at `13–60`; `EventDocumentType` at `63–77`; `EventOperation` at `80–85`; `EventDocumentDataBase` at `88–91`; existing data classes at `94–176`; `Event` at `194–207` |
| Importance | **Critical** — spec requires new event `MealPlanAutoSyncedToShopping`. |
| Reason | ⚠️ Per the docstring at L14–22: *"Each event type is represented by a field on the subscriber repository, therefore any changes made here must also be reflected in the database (and likely requires a database migration)."* — adding a new `EventTypes.meal_plan_auto_synced_to_shopping = auto()` requires a corresponding migration to add a boolean column to the `group_events_notifier_options`-style table (cross-perspective question for data layer to verify). |

### 3.3 New `EventDocumentDataBase` subclass needed

| Field | Value |
|---|---|
| Path | `mealie/services/event_bus_service/event_types.py` |
| Symbols | new `EventMealPlanAutoSyncedToShoppingData` (proposed) |
| Line ranges (VERIFIED) | model after `EventShoppingListItemBulkData` at `141–144` |
| Importance | **High** — required for typed event payload. |
| Reason | Spec payload: `{household_id, shopping_list_id, added_item_count, skipped_pantry_count}`. household_id is already at the dispatch level — payload class should carry `shopping_list_id: UUID4`, `added_item_count: int`, `skipped_pantry_count: int`. Inherit from `EventDocumentDataBase` with `document_type = EventDocumentType.shopping_list` and `operation = EventOperation.update`. |

### 3.4 In-task dispatch pattern (reference impl)

| Field | Value |
|---|---|
| Path | `mealie/services/scheduler/tasks/create_timeline_events.py` |
| Symbols | `_create_mealplan_timeline_events_for_household` |
| Line ranges (VERIFIED) | `25–114`; dispatch call at `93–114`; bus init at `30` |
| Importance | **High** — closest existing analog (also a scheduled task that reads today's meal plan + dispatches). |
| Reason | Shows exact pattern: `event_bus_service = EventBusService(session=session)` then `.dispatch(integration_id=DEFAULT_INTEGRATION_ID, group_id=..., household_id=..., event_type=..., document_data=...)`. Use `DEFAULT_INTEGRATION_ID` (mealie/schema/user/user.py) since this is a system-initiated event. |

---

## 4. Existing "admin-only" routes (for the `Food.is_pantry_staple` admin update)

### 4.1 ⚠️ Two distinct "admin" concepts in Mealie

| Concept | Auth | How |
|---|---|---|
| **System admin** | `Depends(get_admin_user)` checks `user.admin` flag | `AdminAPIRouter` + `BaseAdminController` |
| **Household admin** | `OperationChecks.can_manage_household()` checks `user.can_manage_household` | `UserAPIRouter` + `BaseUserController` + manual `self.checks.can_manage_household()` |

### 4.2 `AdminAPIRouter` (system-admin gating)

| Field | Value |
|---|---|
| Path | `mealie/routes/_base/routers.py` |
| Symbols | `AdminAPIRouter`, `UserAPIRouter`, `MealieCrudRoute` |
| Line ranges (VERIFIED) | `AdminAPIRouter` `13–17`, `UserAPIRouter` `20–24`, `MealieCrudRoute` `27–52` |
| Importance | **Critical** — *the only two router subclasses*. There is **no `HouseholdAPIRouter` or `GroupAPIRouter`** despite the task brief asking for them (see §7). |
| Reason | `AdminAPIRouter` injects `Depends(get_admin_user)` at router level; `UserAPIRouter` injects `Depends(get_current_user)`. Household/group scoping is *not* enforced at the router layer — it's enforced via the `BaseUserController.group_id`/`household_id` properties that auto-filter `self.repos`. |

### 4.3 `get_admin_user` dependency

| Field | Value |
|---|---|
| Path | `mealie/core/dependencies/dependencies.py` |
| Symbols | `get_admin_user`, `get_current_user` |
| Line ranges (VERIFIED) | `get_admin_user` `135–138`; `get_current_user` `88–129` |
| Importance | **Critical** — implementation of the admin gate. |
| Reason | Simple `if not current_user.admin: raise HTTPException(403)`. Adding `is_pantry_staple` write capability scoped to "system admin" means using `AdminAPIRouter` or inheriting `BaseAdminController`. |

### 4.4 `BaseAdminController` — auto-broadens repo scope

| Field | Value |
|---|---|
| Path | `mealie/routes/_base/base_controllers.py` |
| Symbols | `BaseAdminController` |
| Line ranges (VERIFIED) | `175–189`; `repos` override at `184–189` |
| Importance | **High** — ⚠️ admin controllers see **all groups/households** unscoped. |
| Reason | At L186–189: `_repos = AllRepositories(self.session, group_id=None, household_id=None)`. This means an admin update endpoint for `Food.is_pantry_staple` would let one admin flip the flag for any group's food — which connects to the cross-perspective question of "is `is_pantry_staple` a per-group attribute (matches current `IngredientFoodModel` schema, group-scoped) or per-household (would need a new join table)?" |

### 4.5 Existing food routes (target of new admin write)

| Field | Value |
|---|---|
| Path | `mealie/routes/unit_and_foods/foods.py` |
| Symbols | `IngredientFoodsController`, `update_one`, `create_one`, `merge_one`, `delete_one` |
| Line ranges (VERIFIED) | `21` (router decl); `25–78` (class); `update_one` at `69–73` (PUT `/foods/{item_id}`) |
| Importance | **Critical** — existing CRUD surface for foods. New `is_pantry_staple` flag could either piggy-back on `update_one` (any `can_organize` user) or get its own admin-only `PATCH /admin/foods/{item_id}/pantry-staple` route. |
| Reason | Current `update_one` is gated by `self.checks.can_organize()` (L71) — *not* admin. If spec wants "admin only", we must either (a) add a new admin route under `mealie/routes/admin/admin_foods.py` (doesn't exist; would need new file + wiring in `mealie/routes/admin/__init__.py`), or (b) widen the gate to a separate admin route. |

### 4.6 Admin sub-router wiring

| Field | Value |
|---|---|
| Path | `mealie/routes/admin/__init__.py` |
| Symbols | top-level `router = AdminAPIRouter(prefix="/admin")` |
| Line ranges (VERIFIED) | `1–26` (whole file); router decl `15`; sub-router includes `17–25` |
| Importance | **High** — any new admin module file must be `include_router`ed here. |
| Reason | Pattern is clear: `from . import admin_<name>` then `router.include_router(admin_<name>.router, tags=["Admin: <Name>"])`. A proposed `admin_foods.py` for `is_pantry_staple` would slot in identically. |

---

## 5. Existing routes with "run-now" / "trigger-now" admin pattern

> ⚠️ There are **zero** existing routes containing `run-now`, `trigger-now`, `run_now`, or `trigger_now` in the codebase (verified via ripgrep). The closest analogs are:

### 5.1 `POST /households/recipe-actions/{item_id}/trigger/{recipe_slug}`

| Field | Value |
|---|---|
| Path | `mealie/routes/households/controller_group_recipe_actions.py` |
| Symbols | `GroupRecipeActionController.trigger_action` |
| Line ranges (VERIFIED) | `70–104`; router decl `24`; class `27–104` |
| Importance | **High** — closest "fire-an-action-now" pattern. |
| Reason | Pattern: HTTP `POST`, returns `202 Accepted`, takes `BackgroundTasks` to offload heavy work, returns no body. For the spec's `POST /api/households/preferences/auto-sync-shopping/run-now`, we can mirror this — but spec says return a JSON body `{added_count, skipped_pantry_count, target_list_id, run_at}`, so **synchronous return is required**, not 202+background. |

### 5.2 `POST /households/events/notifications/{item_id}/test`

| Field | Value |
|---|---|
| Path | `mealie/routes/households/controller_group_notifications.py` |
| Symbols | `GroupEventsNotifierController.test_notification` |
| Line ranges (VERIFIED) | `91–104`; class `36–104`; router decl `31–33` |
| Importance | **Medium** — "test/run this thing right now" pattern. |
| Reason | Shows `POST /{item_id}/test` with `status_code=204` — fire-and-forget, runs synchronously inline. No admin gate (user-router level only). Useful structural reference for the trigger endpoint. |

### 5.3 `POST /admin/maintenance/clean/*`

| Field | Value |
|---|---|
| Path | `mealie/routes/admin/admin_maintenance.py` |
| Symbols | `AdminMaintenanceController.clean_images`, `clean_temp`, `clean_recipe_folders` |
| Line ranges (VERIFIED) | `89–98` (clean_images), `100–110` (clean_temp), `112–121` (clean_recipe_folders); router `13`; controller `66–121` |
| Importance | **Medium** — admin-gated "do work now" pattern. |
| Reason | All three are `POST`, return `SuccessResponse`, run synchronously, use `BaseAdminController`. Good template for an *admin-scoped* run-now endpoint. ⚠️ But spec's `run-now` lives under `/households/preferences/...` and is **household-admin** gated (`self.checks.can_manage_household()`), not system-admin — so we should use `BaseUserController` + `self.checks.can_manage_household()` pattern from §1.1, *not* `BaseAdminController`. |

### 5.4 `POST /admin/email`

| Field | Value |
|---|---|
| Path | `mealie/routes/admin/admin_email.py` |
| Symbols | `AdminEmailController.send_test_email` |
| Line ranges (VERIFIED) | `19–35`; controller `12–35` |
| Importance | **Low** — yet another admin "run-now" variant, returns body. |
| Reason | `POST` returning `EmailSuccess` (a Pydantic body model). Closest to what spec requires for the `run-now` return value `{added_count, ...}`. |

---

## 6. `HouseholdAPIRouter` / `GroupAPIRouter` auth gating

### 6.1 ⚠️ These routers **do not exist**

| Field | Value |
|---|---|
| Path | `mealie/routes/_base/routers.py` |
| Symbols | only `AdminAPIRouter`, `UserAPIRouter`, `MealieCrudRoute` exist |
| Line ranges (VERIFIED) | `13–24` (only two router subclasses defined); whole file is 53 lines |
| Importance | **Critical** — clears up a misconception in the task brief. |
| Reason | The task asked for "HouseholdAPIRouter / GroupAPIRouter auth gating" but they don't exist. Auth gating is two-layered: (1) router-level via `UserAPIRouter`/`AdminAPIRouter`, (2) controller-level via `BaseUserController` properties + `OperationChecks`. |

### 6.2 Household/group scoping — how it actually works

| Field | Value |
|---|---|
| Path | `mealie/routes/_base/base_controllers.py` |
| Symbols | `_BaseController.repos`, `BaseUserController.group_id`, `BaseUserController.household_id`, `BaseAdminController.repos` (override) |
| Line ranges (VERIFIED) | `_BaseController` `32–78` (repos at `46–50`, group_id/household_id at `70–76`); `BaseUserController` `132–172` (group_id at `152–154`, household_id at `156–158`); `BaseAdminController.repos` override at `184–189` |
| Importance | **Critical** — how multi-tenancy is enforced for routes. |
| Reason | Scoping is *property-driven*: `BaseUserController.group_id` returns `self.user.group_id`, `household_id` returns `self.user.household_id`, and `_BaseController.repos` lazily builds `AllRepositories(session, group_id=self.group_id, household_id=self.household_id)`. The repo factory does the filtering. **Every new route must inherit `BaseUserController` (or subclass) to get this for free.** |

### 6.3 Permission checks at controller level

| Field | Value |
|---|---|
| Path | `mealie/routes/_base/checks.py` |
| Symbols | `OperationChecks`, `OperationChecks.can_manage_household`, `can_manage`, `can_invite`, `can_organize` |
| Line ranges (VERIFIED) | `1–41` (whole file); `can_manage_household` `23–26`; raise pattern via `ForbiddenException` at `14` |
| Importance | **Critical** — the only granular permission check inside a household. |
| Reason | The `run-now` endpoint requires household admin (spec: "鉴权：household 内 admin 角色"). Pattern is `self.checks.can_manage_household()` (raises 403 if not). Already used in `controller_household_self_service.py:60`. |

---

## 7. Adjacent seams needed for the implementation

### 7.1 `repos.meals.get_today(tz=...)` — already timezone-aware

| Field | Value |
|---|---|
| Path | `mealie/repos/repository_meals.py` |
| Symbols | `RepositoryMeals.get_today`, `RepositoryMeals.get_meals_by_date_range` |
| Line ranges (VERIFIED) | `get_today` `12–21`; whole file `1–33` |
| Importance | **Critical** — the data fetch for "today's meal plan". |
| Reason | Already accepts a `tz` parameter (default UTC) and computes `today = datetime.now(tz=tz).date()`. **Reuse exactly as the spec requires**. Already filters by `household_id` (L18), so multi-tenant-safe when called from a household-scoped repo. ⚠️ However, the Household DB model has **no `timezone` column** (see `mealie/db/models/household/household.py` L29–98) — so currently the only sources of tz are: server-local, server settings (`DAILY_SCHEDULE_TIME_UTC` only), or a new `Household.timezone` column. Cross-perspective question for data layer. |

### 7.2 Shopping list "add recipe to list" service seam (reuse for §2 step 5–6)

| Field | Value |
|---|---|
| Path | `mealie/services/household_services/shopping_lists.py` |
| Symbols | `ShoppingListService.add_recipe_ingredients_to_list`, `get_shopping_list_items_from_recipe`, `bulk_create_items`, `merge_items`, `can_merge` |
| Line ranges (VERIFIED) | `add_recipe_ingredients_to_list` `413–455`; `bulk_create_items` `154–223`; `merge_items` `73–128`; `can_merge` `45–71` |
| Importance | **Critical** — spec mandates reuse of these. |
| Reason | `add_recipe_ingredients_to_list(list_id, recipe_items)` already does the merge-by-(food_id, unit_id) behavior with `can_merge` checking `food_id`/`unit_id` equality + unit-conversion. It also already preserves `recipe_references`. ⚠️ However, **it does NOT filter out pantry_staple foods** — that filter must happen *before* calling this (in the new task), iterating each recipe's ingredients and dropping those where `ingredient.food.is_pantry_staple == True`. |

### 7.3 ⚠️ No `consolidate_ingredients` function exists

| Field | Value |
|---|---|
| Path | (negative result — ripgrep) |
| Symbols | none found in `mealie/` |
| Line ranges | n/a |
| Importance | **High** — spec misnames it. |
| Reason | Spec references *"复用 mealie 既有 `consolidate_ingredients`"*. No such function exists in `mealie/`. The actual de-facto consolidation primitives are `ShoppingListService.can_merge` + `merge_items` + `bulk_create_items` (§7.2). The "Case 3 fix" referenced in the spec presumably lands in one of these — coordinate with the spec author / data perspective. |

### 7.4 `IngredientFoodModel` — where `is_pantry_staple` lives

| Field | Value |
|---|---|
| Path | `mealie/db/models/recipe/ingredient.py` |
| Symbols | `IngredientFoodModel` |
| Line ranges (VERIFIED) | `153–219` (class), `on_hand` (deprecated bool template) at `192` |
| Importance | **Critical** — model where the new column lives. |
| Reason | ⚠️ `IngredientFoodModel` is **group-scoped** (`group_id` at L158). Adding `is_pantry_staple` here means the flag is **per-group, not per-household** — household A and B in the same group share the flag. That contradicts the spec's "跨 household 的 food pantry-staple 标记不互相影响" requirement. **Cross-perspective question (Q3 below).** Existing precedent: `on_hand: Mapped[bool]` at L192 (since marked deprecated, but the migration pattern is in `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py`). |

### 7.5 Alembic migration template

| Field | Value |
|---|---|
| Path | `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py` |
| Symbols | `upgrade`, `downgrade`, `is_postgres` |
| Line ranges (VERIFIED) | `20–46`; upgrade `24–41`; downgrade `44–46` |
| Importance | **High** — exact precedent for adding a bool to `ingredient_foods`. |
| Reason | Reuse this pattern for the new `is_pantry_staple` column: `batch_alter_table` + `add_column(sa.Column(..., Boolean, nullable=True, default=False))` + UPDATE-all-existing-rows + `alter_column(nullable=False)`. Generate via `task py:migrate -- "add auto sync prefs and pantry staple"`. |

### 7.6 i18n target file

| Field | Value |
|---|---|
| Path | `mealie/lang/messages/en-US.json` |
| Symbols | top-level objects `mealplan`, `notifications`, `exceptions` |
| Line ranges (VERIFIED) | `mealplan` at `34–36`; `notifications` `54–62`; `exceptions` `46–53` |
| Importance | **High** — spec adds 3 new error codes. |
| Reason | New keys `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today` should go under a new top-level `"auto-sync": { ... }` object. Per `.github/copilot-instructions.md`: **only modify `en-US.json`**; all other locales are managed by Crowdin and must not be touched. |

---

## 8. New routes proposed

> All three live under `mealie/routes/households/controller_household_self_service.py` (extending the existing controller), OR a new `controller_auto_sync_shopping.py` colocated under `mealie/routes/households/`. Recommend the latter to keep `controller_household_self_service.py` focused.

| # | Method + Path | Auth | Handler signature | Returns | Status |
|---|---|---|---|---|---|
| 1 | `PATCH /api/households/preferences` (or extend existing `PUT`) | user, household-admin via `self.checks.can_manage_household()` | `def update_household_preferences_partial(self, new_pref: UpdateHouseholdPreferences)` | `ReadHouseholdPreferences` (200) | New — adds the 3 fields. ⚠️ Spec says PATCH, codebase only does PUT here; either (a) add a real PATCH alongside existing PUT, or (b) keep PUT (since fields fit cleanly into the existing schema). Recommend **(a) PATCH with a partial-update schema** that uses `model_dump(exclude_unset=True)` for forward-compat. |
| 2 | `POST /api/households/preferences/auto-sync-shopping/run-now` | user, household-admin | `def trigger_auto_sync_now(self) -> AutoSyncRunResult` | `AutoSyncRunResult` body `{added_count: int, skipped_pantry_count: int, target_list_id: UUID4 \| None, run_at: datetime}` (200; 204 if no work to do per spec §5 test "返回 204 / 0 added") | New — fires the sync inline, **bypasses** but still updates `LastAutoSyncedAt`. |
| 3 | `PATCH /api/admin/foods/{item_id}/pantry-staple` (or extend `PUT /api/foods/{item_id}`) | choose: system-admin (`BaseAdminController`) or household-admin (`self.checks.can_manage_household()`); spec is ambiguous | `def set_pantry_staple(self, item_id: UUID4, data: IngredientFoodPantryStapleUpdate) -> IngredientFood` | `IngredientFood` (200) | New — see Q3 below. |

### 8.1 New Pydantic schemas needed

- `UpdateHouseholdPreferences` (extend existing) — add 3 fields with defaults.
- `AutoSyncRunResult(MealieModel)` — response body for §8 row 2.
- `IngredientFoodPantryStapleUpdate(MealieModel)` — minimal `{is_pantry_staple: bool}` body for §8 row 3 (or just reuse `CreateIngredientFood` and let it carry the new field).

---

## 9. Scheduler integration seam

**Wiring:**

1. New module `mealie/services/scheduler/tasks/auto_sync_shopping.py` — exports `auto_sync_shopping_to_meal_plan()` callable. Structure mirrors `mealie/services/scheduler/tasks/create_timeline_events.py` (verified L25–134):
   - Open `with session_context() as session:`
   - Iterate `repos.groups.page_all(...)` (unscoped repos)
   - For each group iterate `get_repositories(session, group_id=g).households.page_all(...)`
   - For each household: get household-scoped repos, read preferences, check `auto_sync_meal_plan_to_shopping`, check time-window vs `auto_sync_run_time`, check `LastAutoSyncedAt`, call `repos.meals.get_today(tz=tz)`, run pantry-staple filter, call `ShoppingListService.add_recipe_ingredients_to_list(...)`, dispatch event.

2. Add to `mealie/services/scheduler/tasks/__init__.py` (verified L1–28):
   ```python
   from .auto_sync_shopping import auto_sync_shopping_to_meal_plan
   __all__ = [..., "auto_sync_shopping_to_meal_plan"]
   ```

3. Register in `mealie/app.py` `start_scheduler` (verified L124–144):
   - **Option A (recommended, no scheduler changes):** `SchedulerRegistry.register_minutely(tasks.auto_sync_shopping_to_meal_plan)` — runs every 5 min, task internally checks "is it within the 30-min window after `auto_sync_run_time`?" using last-run-at.
   - **Option B (cleaner cadence, scheduler change):** Add `MINUTES_30 = 30` constant + `run_half_hourly` + `register_half_hourly` to `scheduler_service.py` and `scheduler_registry.py` (verified seams in §2.2, §2.3), then register on that.

**⚠️ Concurrency seam:** scheduler is single-worker per the docstring at `mealie/services/scheduler/tasks/__init__.py:21–28`. Multi-replica deployments will run the task once per replica unless **database-level locking** is added (spec mandates `SELECT ... FOR UPDATE SKIP LOCKED` or `LastAutoSyncedAt` CAS). This is *not* an existing seam — it must be designed in. See Q1 below.

---

## 10. Event bus integration seam

**Wiring:**

1. Add new enum value in `mealie/services/event_bus_service/event_types.py` `EventTypes` (verified L13–60):
   ```python
   meal_plan_auto_synced_to_shopping = auto()
   ```
   ⚠️ Per the in-file docstring at L14–22, this requires a **database migration** adding a corresponding boolean column to the subscriber/notifier options table (cross-perspective question for data layer to confirm exact table and seam).

2. Add new payload class in the same file after L141–144:
   ```python
   class EventMealPlanAutoSyncedToShoppingData(EventDocumentDataBase):
       document_type: EventDocumentType = EventDocumentType.shopping_list
       operation: EventOperation = EventOperation.update
       shopping_list_id: UUID4
       added_item_count: int
       skipped_pantry_count: int
   ```

3. From inside the task (or the `run-now` route), dispatch:
   - **In task:** `EventBusService(session=session).dispatch(integration_id=DEFAULT_INTEGRATION_ID, group_id=..., household_id=..., event_type=EventTypes.meal_plan_auto_synced_to_shopping, document_data=EventMealPlanAutoSyncedToShoppingData(...))` — mirror `tasks/create_timeline_events.py:93–103`.
   - **In route controller:** inherit `BaseCrudController` (verified `mealie/routes/_base/base_controllers.py:192–214`) and call `self.publish_event(event_type=..., document_data=..., group_id=..., household_id=...)`.

---

## 11. Cross-perspective questions

**Q1 (→ data + infra):** **Multi-replica safety.** Mealie's scheduler is in-process per `mealie/services/scheduler/tasks/__init__.py:21–28` ("only available to a single worker"). Spec mandates `SELECT ... FOR UPDATE SKIP LOCKED` or `LastAutoSyncedAt` CAS for multi-replica deployments. What is the data-layer design for `LastAutoSyncedAt` (column on `household_preferences`? Separate `household_auto_sync_state` table?) and how is the row-lock acquired in SQLAlchemy? Does Mealie support PostgreSQL-only locking or must this also work for SQLite?

**Q2 (→ data):** **Household timezone source.** `repository_meals.RepositoryMeals.get_today(tz=...)` (L12–21) accepts a `tz` parameter, but `mealie/db/models/household/household.py:29–98` has **no `timezone` column**. The spec assumes per-household timezone (`auto_sync_run_time` is "household 时区下"). Data layer: should we add `Household.timezone` (or `HouseholdPreferences.timezone`)? Or read from `auto_sync_run_time` as a naive-time-plus-server-tz fallback?

**Q3 (→ data):** **`is_pantry_staple` scope mismatch.** `IngredientFoodModel` is **group-scoped** (`mealie/db/models/recipe/ingredient.py:158`), but the spec test requires "跨 household 的 food pantry-staple 标记不互相影响". A simple boolean column on `IngredientFoodModel` will be group-wide, violating that test. Options: (a) add an `households_to_pantry_staples` association table similar to the existing `households_to_ingredient_foods` at `ingredient.py:160–162`, (b) reinterpret the spec as "per-group is acceptable, the test is about scope leakage *across groups*", (c) move the flag to a per-household join table. Please confirm intended semantics.

**Q4 (→ spec author):** **PATCH vs PUT.** Spec says `PATCH /api/households/preferences` but the only existing endpoint is `PUT` (controller_household_self_service.py:58–62). PATCH semantics in Mealie are only used on recipe routes (`recipe_crud_routes.py:520, 543, 568`) and accept a full schema. Do we (a) add a new PATCH endpoint with `exclude_unset` partial-update semantics, (b) keep PUT and just add fields, or (c) replace PUT with PATCH? Backward compat impact on frontend client — see `frontend/app/lib/api/` types regen via `task dev:generate`.

**Q5 (→ spec author):** **"Admin" scope for pantry-staple update.** Spec §4 says "admin/foods routes (允许管理员标记)" — does "admin" mean:
  - **system admin** (`user.admin == true`, `BaseAdminController`, cross-group write power), or
  - **household admin** (`user.can_manage_household == true`, `self.checks.can_manage_household()`, scoped to own group only)?

  Existing foods CRUD uses `self.checks.can_organize()` at `mealie/routes/unit_and_foods/foods.py:71` — a third option that's even more permissive.

**Q6 (→ data):** **Adding new `EventTypes` enum value requires DB migration** per the in-file warning at `event_types.py:14–22`. What table needs the new boolean column for the `meal_plan_auto_synced_to_shopping` event-type subscription flag? Likely `group_events_notifier_options` (please confirm with `mealie/db/models/household/events.py`).

**Q7 (→ data):** **`auto_sync_target_shopping_list_id` foreign-key & cascade.** Spec defines this as `UUID | null`. If we add a real FK to `group_shopping_lists.id`, what's the desired behavior on shopping-list deletion: SET NULL (auto-sync silently picks the household's first active list per the fallback), CASCADE (disable auto-sync), or RESTRICT (block deletion)? Affects migration shape.
