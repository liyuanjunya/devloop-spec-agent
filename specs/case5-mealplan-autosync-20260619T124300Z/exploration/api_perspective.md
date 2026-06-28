# Case 5 — API Perspective

> Source-of-truth audit for every route, scheduler hook, event-bus dispatch
> path, and auth seam case-5 will touch, with verified file paths, symbol
> names, and line ranges. All ranges have been opened in the source and
> validated against `mealie` at the same checkout referenced by
> `context/grounding.md`.

## 1. Existing household-preferences route (PATCH/PUT seam)

| Field | Value |
|---|---|
| Path | `mealie/routes/households/controller_household_self_service.py` |
| Symbols | `HouseholdSelfServiceController` (20–91), `get_household_preferences` GET `/households/preferences` (54–56), `update_household_preferences` **PUT** `/households/preferences` (58–62), router definition (16) |
| Line range | `1–92` (full file) |
| Auth seam | Router is `UserAPIRouter(prefix="/households", tags=["Households: Self Service"])` (16) → `Depends(get_current_user)`. `update_household_preferences` additionally calls `self.checks.can_manage_household()` (60). |
| Importance | **Critical**. This is the existing endpoint that the case-5 spec calls `PATCH /api/households/preferences`. Mealie's actual verb is **PUT**. The body type is `UpdateHouseholdPreferences` (imported from `mealie/schema/household/household_preferences.py`), and the response type is `ReadHouseholdPreferences`. |
| Reason | Adding the three (or five) new fields to `UpdateHouseholdPreferences` propagates automatically through this PUT — no route changes required. Spec's "PATCH" wording is naming drift, not a behavior gap. Documented in `intent/trace.md` open question #11. |

### How new fields get picked up (verified)
The chain is:
1. New columns added to `HouseholdPreferencesModel` (`mealie/db/models/household/preferences.py:16–44`).
2. New fields added to `UpdateHouseholdPreferences` (`mealie/schema/household/household_preferences.py:10–22`); inherited by `CreateHouseholdPreferences` (25), `SaveHouseholdPreferences` (28–29), `ReadHouseholdPreferences` (32–40).
3. Existing PUT route at L58–62 accepts the augmented body unchanged — `self.repos.household_preferences.update(self.household_id, new_pref)` flows through `HouseholdRepositoryGeneric.update` which auto-maps Pydantic → ORM via `@auto_init()` on the model (line 42 of `preferences.py`).
4. Frontend type generation (`task dev:generate`) regenerates `frontend/app/lib/api/types/`.

### Cross-household reference validation gap
The spec's `auto_sync_target_shopping_list_id` carries a `UUID4 | None` referencing `shopping_lists.id`. Nothing in `UpdateHouseholdPreferences` today validates cross-household FK semantics. Recommended addition: a `@field_validator("auto_sync_target_shopping_list_id")` in the schema OR a pre-update check in `update_household_preferences` controller that looks up the list and asserts `list.household_id == self.household_id`. Pattern verified against `mealie/routes/households/controller_household_self_service.py:73–77` which already does this style of check (`if target_user.household_id != self.household_id: raise HTTPException(403)`).

---

## 2. "Run-now" / "trigger-now" — existing admin one-shot pattern

**Verdict: only one analogue exists** — there is no general-purpose "run scheduled task now" admin pattern; the closest is the per-action trigger.

| Field | Value |
|---|---|
| Path | `mealie/routes/households/controller_group_recipe_actions.py` |
| Symbols | `GroupRecipeActionController` (28–104), `trigger_action` POST `/households/recipe-actions/{item_id}/trigger/{recipe_slug}` (70–104) |
| Line range | `70–104` (relevant block); `1–105` (full file) |
| Auth | `BaseUserController` (28) → `get_current_user`. No `can_manage` check. |
| Status code | `status_code=202` (70) — fire-and-forget semantics via `BackgroundTasks` (72, 99). |
| Importance | **High**. This is the canonical "imperative trigger that bypasses the scheduler" pattern in Mealie. Uses `BackgroundTasks` (72) so the HTTP response is decoupled from the long-running work. |
| Reason | Case-5's `POST /api/households/preferences/auto-sync-shopping/run-now` should follow this pattern but with a difference: spec §3 says return `{ added_count, skipped_pantry_count, target_list_id, run_at }` — i.e., the response *carries* the result, so it must run synchronously, NOT via `BackgroundTasks`. The status code should therefore be `200` not `202`, and the call should `await` (or synchronously run) the sync work. Use `EventBusService.as_dependency` for the event dispatch fan-out only. |

### Other "/clean/*" admin POST examples (one-shot maintenance)
| Path | `mealie/routes/admin/admin_maintenance.py` |
|---|---|
| Symbols | `AdminMaintenanceController` (66–122), `clean_images` POST `/admin/maintenance/clean/images` (89–98), `clean_temp` POST `/admin/maintenance/clean/temp` (100–110), `clean_recipe_folders` POST `/admin/maintenance/clean/recipe-folders` (112–121) |
| Auth | `BaseAdminController` (66) → `get_admin_user` via `AdminAPIRouter` |
| Importance | **High**. These are synchronous one-shot admin actions returning `SuccessResponse`. They confirm Mealie's convention: synchronous POST for "run this maintenance task now" pattern, returning a structured response. |
| Reason | The case-5 run-now endpoint mirrors this shape but at the household-admin level (not server-admin). |

---

## 3. Admin-only routes pattern (for `Food.is_pantry_staple` exposure)

### Option A — extend existing per-household `PUT /api/foods/{item_id}` with `can_organize`
| Path | `mealie/routes/unit_and_foods/foods.py` |
|---|---|
| Symbols | `IngredientFoodsController` (24–78), `update_one` PUT `/foods/{item_id}` (69–73), `create_one` POST `/foods` (49–53), `merge_one` PUT `/foods/merge` (55–63), `delete_one` DELETE `/foods/{item_id}` (75–78) |
| Auth | `BaseUserController` (25); all mutations gated by `self.checks.can_organize()` (`mealie/routes/_base/checks.py:38–41`). |
| Body | `CreateIngredientFood` (`mealie/schema/recipe/recipe_ingredient.py:92–95`) → cast to `SaveIngredientFood` with `group_id` injection (72) → `self.mixins.update_one(data, item_id)`. |
| Importance | **High**. Simplest path: add `is_pantry_staple: bool = False` to `CreateIngredientFood` and the existing PUT picks it up under the existing `can_organize` permission. |
| Reason | Foods are group-scoped (verified at `mealie/db/models/recipe/ingredient.py:158` `group_id` FK), and `can_organize` is the standard food/category/tag mutation permission. This is the path of least resistance. |

### Option B — add a separate server-admin route under `/admin/foods`
| Path | `mealie/routes/admin/admin_management_households.py` (template, NOT the actual target file) |
|---|---|
| Symbols | `AdminHouseholdManagementRoutes` (26–91), `update_one` PUT `/admin/households/{item_id}` (63–77) |
| Auth | `BaseAdminController` (26) → `get_admin_user` via `AdminAPIRouter(prefix="/admin")` at `mealie/routes/admin/__init__.py:15`. |
| Importance | **Medium**. Pattern reusable verbatim. New file `mealie/routes/admin/admin_management_foods.py` defining `@controller(router)` `class AdminFoodsController(BaseAdminController)` with PATCH `/foods/{item_id}/pantry-staple`. |
| Reason | Spec §4 wording "admin/foods routes (允许管理员标记)" leans toward the admin route variant. But the per-group nature of foods makes a household-level `can_organize` (option A) more idiomatic. **Recommend option A** for case-5 unless the spec author explicitly meant server-admin. |

### Router class reference
| Path | `mealie/routes/_base/routers.py` |
|---|---|
| Symbols | `AdminAPIRouter` (13–17), `UserAPIRouter` (20–24), `MealieCrudRoute` (27–52) |
| Importance | **Reference**. `AdminAPIRouter` auto-injects `Depends(get_admin_user)` (17); `UserAPIRouter` auto-injects `Depends(get_current_user)` (24). |
| Reason | Picking the right router base for the run-now endpoint and the (optional) admin pantry-staple endpoint. The run-now endpoint should use `UserAPIRouter` + explicit `self.checks.can_manage_household()` (matches the existing `update_household_preferences` pattern). |

---

## 4. Existing scheduled-task pattern

### Registry + service entry points
| Path | `mealie/services/scheduler/scheduler_registry.py` |
|---|---|
| Symbols | `SchedulerRegistry` (8–59) with `_daily: list[Callable]` (13), `_hourly: list[Callable]` (14), `_minutely: list[Callable]` (15); `register_daily` (23–25), `register_hourly` (32–34), `register_minutely` (41–43); `remove_*` and `print_jobs` |
| Line range | `1–59` (full file) |
| Importance | **Critical**. Only three time buckets exist. **No 30-minute bucket.** Case-5 must reuse one of the existing buckets and self-gate. |
| Reason | The spec's "every 30 minutes" cadence has no direct match. Either (a) register on minutely and check `current_time matches household's run_time window`, OR (b) extend the registry/service with a new `_thirty_minutely` bucket. Option (a) is less invasive and explicitly satisfied by spec §实现约束 ("必须复用既有 scheduler 抽象, 不要新建并行 scheduler"). |

### Periodicity (verified the "minutely" misnomer)
| Path | `mealie/services/scheduler/scheduler_service.py` |
|---|---|
| Symbols | `SchedulerService.start` (21–28), `schedule_daily()` (30–53), `_scheduled_task_wrapper(callable)` (56–60), `run_daily` decorator `@repeat_every(minutes=MINUTES_DAY, wait_first=False, ...)` (63–67), `run_hourly` (`@repeat_every(minutes=MINUTES_HOUR, wait_first=True, ...)`) (70–74), `run_minutely` (`@repeat_every(minutes=MINUTES_5, wait_first=True, ...)`) (77–81). Constants: `MINUTES_DAY=1440` (15), `MINUTES_5=5` (16), `MINUTES_HOUR=60` (17). |
| Line range | `1–82` (full file) |
| Importance | **Critical**. `register_minutely` actually fires every **5 minutes** (not every minute). The auto-sync task can register here and verify the current time is within the household's `run_time + [0, 30min)` window. Idempotency via `last_auto_synced_at` prevents duplicate runs. |
| Reason | The spec says "每 30 分钟跑一次" but tolerates "30 分钟窗口内触发". Running every 5 minutes + window check is functionally equivalent and follows the existing pattern. |

### `@scheduled` decorator (technically `@repeat_every`)
| Path | `mealie/services/scheduler/runner.py` |
|---|---|
| Symbols | `repeat_every(*, minutes, wait_first=False, logger=None, raise_exceptions=False, max_repetitions=None)` (19–83) |
| Line range | `1–83` (full file) |
| Importance | **Reference**. Adapted from fastapi-utils. Wraps a sync/coroutine func into an asyncio loop that fires every `minutes * 60` seconds. Exception handling: logs by default (lines 71–74), can re-raise via `raise_exceptions=True`. |
| Reason | Spec mentions "既有的 `@scheduled` 装饰器" — that exact name does not exist; the actual decorator is `@repeat_every`. Used internally by `SchedulerService.run_daily/run_hourly/run_minutely`. Case-5's task function is registered via `SchedulerRegistry.register_minutely(auto_sync_meal_plan_to_shopping)`; the decorator wrapping is done by `SchedulerService`, not the task itself. **The task itself is a plain function**, not a decorated one. |

### Task data class
| Path | `mealie/services/scheduler/scheduled_func.py` |
|---|---|
| Symbols | `ScheduledFunc(BaseModel)` (8–18) — fields: `id: tuple[str, int]`, `name: str`, `hour: int`, `minutes: int`, `callback: Callable`, `max_instances: int = 1`, `replace_existing: bool = True`, `args: list = []` |
| Line range | `1–18` (full file) |
| Importance | **Low**. The dataclass is defined but **not used** by the current registry — `SchedulerRegistry` stores raw `Callable`s in lists (lines 13–15 of registry). Case-5 does not need to instantiate `ScheduledFunc`. |
| Reason | Inferred dead code or future-proofing; the actual registration path is `_minutely.append(callback)` at L21 of `scheduler_registry.py`. |

### Registration point — app startup
| Path | `mealie/app.py` |
|---|---|
| Symbols | `lifespan_fn` (54–95), `start_scheduler()` (124–144) — calls `SchedulerRegistry.register_daily(...)` (125–132), `register_minutely(...)` (134–136), `register_hourly(...)` (138–140), then `await SchedulerService.start()` (144). |
| Line range | `54–145` (relevant block) |
| Importance | **Critical**. Case-5 must add `auto_sync_meal_plan_to_shopping` to `register_minutely` at line 134–136. |
| Reason | This is the **only** scheduler registration site in the codebase; everything else flows through it. The task callable comes from `mealie/services/scheduler/tasks/auto_sync_shopping.py` (new file) and is re-exported through `mealie/services/scheduler/tasks/__init__.py:1–19`. |

### Prior-art task files (templates for the new file)
| Path | `mealie/services/scheduler/tasks/create_timeline_events.py` |
|---|---|
| Symbols | `_create_mealplan_timeline_events_for_household(event_time, session, group_id, household_id)` (25–114), `_create_mealplan_timeline_events_for_group(event_time, session, group_id)` (117–122), `create_mealplan_timeline_events()` (125–134) |
| Line range | `1–135` (full file) |
| Importance | **Critical template**. The auto-sync task should mirror this exact shape:<br>1. Top-level `auto_sync_meal_plan_to_shopping()` (no args) opens a `session_context()` and iterates groups (L128–131).<br>2. Per-group helper opens scoped repos and iterates households (L117–122).<br>3. Per-household helper does the actual work: read prefs, check time window, check `last_auto_synced_at`, fetch today's meal plans via `repos.meals.get_today(tz=...)` (L37), call `ShoppingListService.add_recipe_ingredients_to_list`, dispatch event via `EventBusService(session=session).dispatch(...)` (L30, L93–103). |
| Reason | This file is the closest structural analog — both fan out per-household, both call `repos.meals.get_today`, both dispatch events. The TZ usage at L36 (`tzlocal()`) is what case-5 must replace with `ZoneInfo(prefs.timezone or "UTC")`. |

| Path | `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` |
|---|---|
| Symbols | `delete_old_checked_list_items()` (54–75), `_trim_list_items(shopping_list_service, shopping_list_id, event_publisher)` (37–51), `_create_publish_event(event_bus_service)` (17–34), constant `MAX_CHECKED_ITEMS = 100` (14) |
| Line range | `1–76` (full file) |
| Importance | **Critical template**. Closest analog for the shopping-list write path: per group → per household → per shopping list → calls `ShoppingListService` methods → publishes events through a small closure factory (`_create_publish_event`). |
| Reason | Auto-sync should reuse the `_create_publish_event(event_bus_service)` closure pattern (L17–34) to wrap `event_bus_service.dispatch` with the integration_id baked in. Also: this file shows the correct way to construct `household_repos = get_repositories(session, group_id=group.id, household_id=household.id)` (L66) and pass it to `ShoppingListService(household_repos)` (L68). |

| Path | `mealie/services/scheduler/tasks/post_webhooks.py` |
|---|---|
| Symbols | `post_group_webhooks(start_dt=None, group_id=None, household_id=None)` (24–79) — note default args are supported, useful for testability; `last_ran` module-level `datetime` cache (21) |
| Line range | `1–101` (full file) |
| Importance | **Reference**. Demonstrates module-level caching of `last_ran` for "time window since previous tick" semantics. Case-5's `last_auto_synced_at` is a per-household DB column instead of a module global (necessary for multi-replica safety per spec). |
| Reason | Confirms that scheduler tasks support default args, which is helpful for testability. |

| Path | `mealie/services/scheduler/tasks/purge_password_reset.py` |
|---|---|
| Symbols | `purge_password_reset_tokens()` (14–24), constant `MAX_DAYS_OLD = 2` (11) |
| Line range | `1–25` (full file) |
| Importance | **Reference (minimal template)**. The simplest possible scheduled task: open `session_context()`, do work, commit, log. Good shape for the top-level `auto_sync_meal_plan_to_shopping()` entry function. |
| Reason | Showcases the `session_context()` + commit + log idiom. |

### Tasks `__init__` registration
| Path | `mealie/services/scheduler/tasks/__init__.py` |
|---|---|
| Symbols | `__all__` (10–19) — exports all registered task callables |
| Line range | `1–28` (full file) |
| Importance | **High**. Case-5 must add `from .auto_sync_shopping import auto_sync_meal_plan_to_shopping` (or similar) at the top and add the symbol to `__all__`. |
| Reason | `mealie/app.py:27` imports `tasks` from this module; the `__all__` list is what `start_scheduler` references via `tasks.<name>`. |

---

## 5. Event bus dispatch pattern

### EventBusService — top-level API
| Path | `mealie/services/event_bus_service/event_bus_service.py` |
|---|---|
| Symbols | `EventBusService` class (42–105), `__init__(bg=None, session=None)` (46–52), `_get_listeners(group_id, household_id)` (54–58), `_publish_event(event, group_id, household_id)` (60–64), `dispatch(integration_id, group_id, household_id, event_type, document_data, message="")` (66–96), `as_dependency(bg, session)` classmethod (98–105). Also: `EventSource` helper (21–39) and module-level `INTERNAL_INTEGRATION_ID = "mealie_generic_user"` imported from `event_types`. |
| Line range | `1–106` (full file) |
| Importance | **Critical**. This is the dispatch entry point. Two-mode operation:<br>• In a route context: use `event_bus: EventBusService = Depends(EventBusService.as_dependency)` (98–105) — wires up `BackgroundTasks`.<br>• In a scheduler task context: instantiate directly `EventBusService(session=session)` (matches `create_timeline_events.py:30`) — synchronous publish (no BackgroundTasks). |
| Reason | The auto-sync task is in scheduler context, so it uses the direct instantiation. The manual run-now route is in HTTP context, so it uses `Depends(EventBusService.as_dependency)`. Both ultimately call `dispatch(...)`. |

### dispatch signature (verified)
- `integration_id: str` — use `INTERNAL_INTEGRATION_ID = "mealie_generic_user"` (`event_types.py:10`) for scheduler-originated events, or `DEFAULT_INTEGRATION_ID = "generic"` (`mealie/schema/user/user.py:24`) for user-triggered events. Existing tasks use `INTERNAL_INTEGRATION_ID` (`post_webhooks.py:74`) and `DEFAULT_INTEGRATION_ID` (`create_timeline_events.py:94`).
- `group_id: UUID4` — required.
- `household_id: UUID4 | None` — if None, the dispatcher fans out per household (82–96). Case-5 should pass the explicit household_id.
- `event_type: EventTypes` — must be a member of the enum.
- `document_data: EventDocumentDataBase | None` — typed payload.
- `message: str = ""` — title/body for webhooks (defaults via `EventBusMessage.from_type`).

### EventTypes + payload schemas (NEW additions required)
| Path | `mealie/services/event_bus_service/event_types.py` |
|---|---|
| Symbols | `INTERNAL_INTEGRATION_ID` (10), `EventTypes` enum (13–60), `EventDocumentType` enum (63–77), `EventOperation` enum (80–85), `EventDocumentDataBase` (88–91), all concrete `Event*Data` classes (94–176), `EventBusMessage` (179–191), `Event` (194–208) |
| Line range | `1–208` (full file) |
| Existing `EventTypes` members | 22 enums at L24–60, including `shopping_list_created/updated/deleted` (42–44) and `mealplan_entry_created/updated/deleted` (38–40). **No `meal_plan_auto_synced_to_shopping`.** |
| Importance | **Critical**. Case-5 must add:<br>(a) `meal_plan_auto_synced_to_shopping = auto()` to `EventTypes` (~L45).<br>(b) New `EventMealPlanAutoSyncedData(EventDocumentDataBase)` class with `document_type: EventDocumentType = EventDocumentType.shopping_list`, `operation: EventOperation = EventOperation.create`, `shopping_list_id: UUID4`, `added_item_count: int`, `skipped_pantry_count: int`. (household_id is already in the `Event.dispatch` args, no need to duplicate in payload — but spec asks for it; defensive choice: include explicitly in payload too.)<br>(c) **Hidden cost**: the enum docstring at L17–22 mandates a DB migration adding a corresponding subscriber column on `GroupEventNotifierOptionsModel` (`mealie/db/models/household/events.py`) — verified by reading the docstring and grepping the alembic versions directory for prior event-type-add migrations (e.g. `2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py` in the version list). |
| Reason | Without (a) + (b), `dispatch(...)` cannot type-check the event. Without (c), the event has no subscriber wiring and webhooks/apprise notifiers cannot opt in. |

### Listeners (read-only reference)
| Path | `mealie/services/event_bus_service/event_bus_listeners.py` |
|---|---|
| Symbols | `EventListenerBase`, `AppriseEventListener`, `WebhookEventListener` (referenced from `event_bus_service.py:9–13`) |
| Importance | **Low**. No case-5 changes needed here. Listeners read the new event type from subscribers, which gets the new event automatically once (a)+(b)+(c) above are done. |
| Reason | Confirms the event-bus is a pub-sub: dispatching a new event type with proper subscriber wiring automatically fans out to all configured webhooks/notifiers. |

### Helper: `BaseCrudController.publish_event` (route-context wrapper)
| Path | `mealie/routes/_base/base_controllers.py` |
|---|---|
| Symbols | `BaseCrudController` (192–214), `publish_event(event_type, document_data, group_id, household_id, message="")` (199–214); injected `event_bus: EventBusService = Depends(EventBusService.as_dependency)` (197) |
| Line range | `192–214` |
| Importance | **High**. The case-5 run-now route should subclass `BaseCrudController` (instead of `BaseUserController` used by the existing `HouseholdSelfServiceController`) OR explicitly take an `EventBusService` dependency to dispatch the `meal_plan_auto_synced_to_shopping` event. Cleaner: refactor `HouseholdSelfServiceController` to extend `BaseCrudController` (one-line change), then call `self.publish_event(...)`. |
| Reason | Provides a thin wrapper that injects `integration_id` from the request context, ensuring user-triggered runs are properly attributed. |

---

## New routes proposed (mapped to existing patterns)

| New route | Verb | Path | Auth | Body | Response | Maps to existing pattern |
|---|---|---|---|---|---|---|
| Update auto-sync preferences | PUT (NOT PATCH) | `/api/households/preferences` | `can_manage_household` | `UpdateHouseholdPreferences` (extended with 3+2 new fields) | `ReadHouseholdPreferences` | **Reuses** existing `controller_household_self_service.py:58–62`. No new endpoint; just extend body schema. Add a cross-household FK validator for `auto_sync_target_shopping_list_id`. |
| Manual auto-sync trigger | POST | `/api/households/preferences/auto-sync-shopping/run-now` | `can_manage_household` | (none) | `AutoSyncRunResult { added_count, skipped_pantry_count, target_list_id, run_at }` (NEW schema) | **New endpoint** in `controller_household_self_service.py`. Pattern from `controller_group_recipe_actions.py:70–104` for the imperative trigger; pattern from `admin_maintenance.py:89–98` for synchronous "run-now-with-result" shape (NOT async/202). Status code **200**, not 202, because the response carries the result. |
| Admin pantry-staple toggle (Option A — preferred) | PUT | `/api/foods/{item_id}` (existing) | `can_organize` | `CreateIngredientFood` (extended with `is_pantry_staple: bool = False`) | `IngredientFood` (with `is_pantry_staple` field) | **Reuses** existing `unit_and_foods/foods.py:69–73`. No new endpoint; just extend schema. |
| Admin pantry-staple toggle (Option B — only if Option A is rejected by spec author) | PATCH | `/api/admin/foods/{item_id}/pantry-staple` | `get_admin_user` (server admin) | `{ is_pantry_staple: bool }` (NEW schema) | `IngredientFood` | **New file** `mealie/routes/admin/admin_management_foods.py`, registered in `mealie/routes/admin/__init__.py`. Pattern from `admin_management_households.py:22–91`. |

### Recommended response schema (new)
```python
# mealie/schema/household/household_preferences.py (or new auto_sync.py)
class AutoSyncRunResult(MealieModel):
    added_count: int
    skipped_pantry_count: int
    target_list_id: UUID4 | None
    run_at: datetime
```

---

## Scheduler integration seam

### Concrete plan (all line refs verified)
1. **New file**: `mealie/services/scheduler/tasks/auto_sync_shopping.py`
   - Top-level entrypoint `def auto_sync_meal_plan_to_shopping() -> None:` (no args; matches existing task signature convention).
   - Mirrors `create_mealplan_timeline_events.py:117–134` structural pattern: iterate groups → per group → iterate households → per household, do work.
   - Per-household work:
     - Read `household.preferences` (already eager-loaded by `mealie/repos/repository_household.py` via `ReadHouseholdPreferences.loader_options()`).
     - **Multi-replica safety / idempotency**: execute a CAS-style UPDATE on `household_preferences` setting `last_auto_synced_at = NOW()` only when `auto_sync_meal_plan_to_shopping = TRUE AND (last_auto_synced_at IS NULL OR last_auto_synced_at < today_start_in_household_tz)`; if 0 rows affected, skip this household (another worker won or it already ran today).
     - **Time-window check**: compute `now_in_household_tz = datetime.now(tz=ZoneInfo(prefs.timezone or "UTC"))`; check `prefs.auto_sync_run_time <= now_in_household_tz.strftime("%H:%M") < prefs.auto_sync_run_time_plus_30min` (or equivalently a 30-min-bucket equality check). Skip if outside window.
     - Fetch today's meal plans via `repos.meals.get_today(tz=ZoneInfo(prefs.timezone or "UTC"))` (existing API at `mealie/repos/repository_meals.py:11–21`).
     - Filter: only entries with `recipe_id IS NOT NULL`.
     - Resolve target list: `target_list_id = prefs.auto_sync_target_shopping_list_id or first_active_main_list_for(household_id)`.
     - For each recipe, build `ShoppingListAddRecipeParamsBulk(recipe_id=..., recipe_increment_quantity=1.0)`. **Pantry filter**: load each recipe's ingredients (or call `get_shopping_list_items_from_recipe(list_id, recipe_id)` which fetches the recipe internally at `services/household_services/shopping_lists.py:336–340`), and skip ingredients where `food.is_pantry_staple is True`. Count skipped.
     - Call `ShoppingListService.add_recipe_ingredients_to_list(target_list_id, recipe_items)` (`services/household_services/shopping_lists.py:413–455`). Count added items from the returned `ShoppingListItemsCollectionOut`.
     - Dispatch the new event via `EventBusService(session=session).dispatch(integration_id=INTERNAL_INTEGRATION_ID, group_id=..., household_id=..., event_type=EventTypes.meal_plan_auto_synced_to_shopping, document_data=EventMealPlanAutoSyncedData(...))`.
2. **Register**: in `mealie/services/scheduler/tasks/__init__.py:10–19` add to `__all__` and import; in `mealie/app.py:134–136` add `tasks.auto_sync_meal_plan_to_shopping` to `SchedulerRegistry.register_minutely(...)` (executes every 5 min — internal window check ensures only the right 30-min slot triggers actual work).
3. **Multi-replica acceptance**: the CAS UPDATE at the top of the per-household block is the lock. No separate `SELECT … FOR UPDATE SKIP LOCKED` needed because the UPDATE itself takes a row lock and the WHERE clause does the "did we win?" test. If spec demands `FOR UPDATE SKIP LOCKED` explicitly, use `repos.session.execute(text("UPDATE household_preferences SET last_auto_synced_at = :now WHERE id = :id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_start)"), {...}).rowcount` and skip if `rowcount == 0`.

### Why NOT use `register_hourly`?
Hourly is `MINUTES_HOUR = 60` minutes. If a household's `run_time = 03:15`, an hourly tick at 03:00 misses it and the next tick is 04:00 — outside the 30-min window. Minutely (5 min) covers all 30-min windows correctly.

### Why NOT extend `SchedulerRegistry` with `register_thirty_minutely`?
The spec forbids "建新并行 scheduler"; extending the registry would touch `scheduler_registry.py:8–59` + `scheduler_service.py:21–82` to add a new bucket constant and a new `@repeat_every`-decorated runner. Reusing minutely + window check has zero scheduler-core surface change. **Strongly prefer reuse**.

---

## Cross-perspective questions

1. **Method override on `HouseholdSelfServiceController`**: spec wants `POST .../auto-sync-shopping/run-now` but the controller currently extends `BaseUserController` (`controller_household_self_service.py:20`). The class needs `event_bus: EventBusService = Depends(EventBusService.as_dependency)` (or convert to `BaseCrudController` at `mealie/routes/_base/base_controllers.py:192–214`). Which approach does case-5 prefer?
2. **Empty-meal-plan response**: spec §5 says "当天无 meal plan 时返回 204 / 0 added". The proposed `AutoSyncRunResult` returns 200 with `added_count=0` — should it instead return 204 with empty body? Pattern in Mealie: most empty-result POSTs return the structured response (e.g., `bulk_create_items` returns an empty collection, not 204). Recommend 200 + `added_count=0` for consistency, and surface to spec author.
3. **i18n keys**: spec §4 requires `auto-sync.no-meal-plan-today / no-target-list / already-synced-today`. These would be raised in the run-now route's `raise HTTPException(status=..., detail=ErrorResponse.respond(message=self.t("auto-sync.no-target-list")))`. Add to `mealie/lang/messages/en-US.json` only (per `.github/copilot-instructions.md` Crowdin policy). The scheduled task should log these (not raise) since it has no HTTP response.
4. **Event subscriber migration**: confirmed via `event_types.py:17–22` docstring that adding `meal_plan_auto_synced_to_shopping` to the enum requires a DB migration on `GroupEventNotifierOptionsModel`. The alembic version list shows the pattern (`2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py`). Need to open that file in coding phase to mirror the exact column-add + populate-default pattern. This is a **hidden cost** not in the original spec.
5. **`tests/` path drift**: spec says `tests/unit_tests/services/scheduler/test_auto_sync.py` but actual convention (verified via `Get-ChildItem`) is `tests/unit_tests/services_tests/scheduler/tasks/test_auto_sync.py`. Use the actual convention to keep CI's test collection happy.
6. **Run-now and event_bus + BackgroundTasks**: when run synchronously to populate the response, the event dispatch should still go through `BackgroundTasks` (via `EventBusService.as_dependency`) so the HTTP response is not blocked on webhook delivery. The sync work (consolidation + write) IS synchronous in the request; only the event dispatch is backgrounded.
7. **What happens if `auto_sync_target_shopping_list_id` points to a deleted list?** Recommend `ondelete="SET NULL"` on the FK (per Data perspective §1) plus a graceful fallback in the task to "first active list" with a log warning. The i18n key `auto-sync.no-target-list` is then raised only when there are no shopping lists at all.
