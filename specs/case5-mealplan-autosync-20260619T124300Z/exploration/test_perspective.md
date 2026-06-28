# Case-5 — Test Perspective

Scope: Meal Plan auto-sync to Shopping List (Mealie). Map existing test
infrastructure that the new scheduled-task / preference / multitenant tests
will sit on top of.

Mealie repo root for citations: `C:\Users\v-liyuanjun\Downloads\mealie\`.
All `line_ranges` were re-opened in the editor and verified; **no fixture
named `unique_user_group` or `freezegun` was found** — see callouts below.

---

## 1. Existing scheduler-task tests (the closest analog to case-5)

### 1.1 `tests/unit_tests/services_tests/scheduler/tasks/test_create_timeline_events.py`
- **path:** `tests/unit_tests/services_tests/scheduler/tasks/test_create_timeline_events.py`
- **symbols:** `test_no_mealplans`, `test_new_mealplan_event`,
  `test_new_mealplan_event_duplicates`,
  `test_new_mealplan_events_with_multiple_recipes`,
  `test_preserve_future_made_date`
- **line_ranges (verified, file is 254 lines):**
  - `test_no_mealplans` — L16-18 (smoke that task runs with empty DB)
  - `test_new_mealplan_event` — L21-100 (happy path; **uses `api_client`
    + `unique_user` + `h2_user`**; creates recipe → meal plan → calls
    `create_mealplan_timeline_events()` directly → asserts via API)
  - `test_new_mealplan_event_duplicates` — L103-140 (idempotency:
    runs the task **3 times** and expects exactly 1 event)
  - `test_new_mealplan_events_with_multiple_recipes` — L143-205
  - `test_preserve_future_made_date` — L208-253
- **importance:** ⭐⭐⭐⭐⭐ — direct template for `test_auto_sync.py`.
  Same shape applies cleanly: arrange via API → call scheduled function
  directly (no time travel, no scheduler loop), assert via API.
- **reason:** Demonstrates the canonical Mealie pattern of testing
  scheduled tasks by **importing the task function and invoking it
  synchronously**. The repeat/cron wrapping (`@repeat_every` in
  `mealie/services/scheduler/runner.py`) is bypassed entirely in tests.
  Idempotency is asserted by simply calling the function N times — the
  same trick we'll use for `LastAutoSyncedAt`.

### 1.2 `tests/unit_tests/services_tests/scheduler/tasks/test_delete_old_checked_shopping_list_items.py`
- **path:** same dir
- **symbols:** `test_cleanup` (L12-60), `test_no_cleanup` (L63-90)
- **line_ranges (verified, file is 106 lines):** entire file
- **importance:** ⭐⭐⭐⭐ — closest precedent for *a scheduled task that
  mutates shopping lists*. Shows:
  - using `unique_user.repos.group_shopping_lists` /
    `group_shopping_list_item` directly to seed data
  - calling `delete_old_checked_list_items()` synchronously
  - `database.session.commit()` after the task to flush before
    re-reading via repo (L53, L100)
- **reason:** Anything that touches shopping lists from a scheduler task
  needs the post-task `session.commit()` dance — easy to miss; our new
  test will hit the same trap.

### 1.3 `tests/unit_tests/services_tests/scheduler/tasks/test_post_webhook.py`
- **path:** same dir
- **symbols:** `webhook_factory` (L20-37),
  `test_get_scheduled_webhooks_filter_query` (L40-78),
  `test_event_listener_get_meals_by_date_range` (L81-149),
  `test_get_meals_by_date_range*` (L152-end)
- **line_ranges (verified, file is 298 lines):** entire file
- **importance:** ⭐⭐⭐⭐ — only test that exercises the **time-window
  filter** logic of a scheduled task (`scheduled_time > start_dt` …
  `<= end_dt`, in `event_bus_listeners.py` L174-175). The case-5 spec
  has an equivalent 30-minute window: this test shows how Mealie does
  it without any mock clock — it just builds `start - timedelta(min=20)`
  scenarios and runs them at real `datetime.now(UTC)`.
- **reason:** Confirms the convention: window-edge cases are tested by
  *constructing data near* the wall clock rather than by *freezing*
  the clock. We should follow this for the `auto_sync_run_time` window.

### 1.4 `tests/unit_tests/services_tests/scheduler/tasks/test_purge_*`
- **path:** `test_purge_expired_share_tokens.py`, `test_purge_group_exports.py`
- **importance:** ⭐⭐ — additional examples; both follow the same
  "seed → call function → assert" pattern with no time mocking.

---

## 2. Scheduler / scheduled-task plumbing the tests rely on

### 2.1 `mealie/services/scheduler/scheduler_service.py`
- **line_ranges (verified, file is 82 lines):** entire file
- **symbols:** `SchedulerService.start` (L21-27),
  `schedule_daily` (L30-53), `_scheduled_task_wrapper` (L56-60),
  `run_daily` / `run_hourly` / `run_minutely` (L63-81)
- **importance:** ⭐⭐⭐⭐⭐ for understanding what the test bypasses.
- **reason:** `run_*` functions are `@repeat_every` decorated, so they
  install an `asyncio` loop when imported. Tests **must not** import
  them — they import the underlying task function (e.g.
  `from mealie.services.scheduler.tasks.create_timeline_events import
  create_mealplan_timeline_events`).
- **For case-5:** the spec says "30-minute frequency", but the scheduler
  only offers `_minutely` (which actually runs every 5 min — see
  `MINUTES_5 = 5` constant on L16), `_hourly`, `_daily`. So either:
  (a) register on `_minutely` and gate inside the task with the window
  check, or (b) extend the scheduler. Tests will need to cover whichever
  path is chosen — **flag for design**.

### 2.2 `mealie/services/scheduler/scheduler_registry.py`
- **line_ranges (verified):** L1-60 (whole file)
- **importance:** ⭐⭐⭐ — class-level lists (`_daily`, `_hourly`,
  `_minutely`) are **module-global state** that persists across tests.
  Important for test isolation: re-registering the same callback can
  cause duplicate runs. The existing tests do **not** re-register —
  they call the task function directly. We follow suit.

### 2.3 `mealie/services/scheduler/runner.py`
- **line_ranges:** L19-83 (`repeat_every` decorator)
- **importance:** ⭐⭐ — confirms the wrapper does `asyncio.sleep` +
  `ensure_future`. Tests must avoid awaiting it.

### 2.4 `mealie/services/scheduler/tasks/__init__.py`
- **line_ranges:** L1-19
- **importance:** ⭐⭐ — every new scheduled task must be exported here
  to be visible to `mealie/app.py:124-141` (`start_scheduler`).
- **For case-5:** the test must verify the new `auto_sync_shopping`
  symbol is exported (a one-line smoke import test). The existing
  tasks have **no such test today** — see Cross-perspective Q4.

### 2.5 `mealie/app.py` registration block
- **line_ranges (verified):** L124-144
- **symbols:** `start_scheduler` registers tasks with
  `SchedulerRegistry.register_daily(...)` / `register_minutely(...)` /
  `register_hourly(...)`.
- **importance:** ⭐⭐⭐ — wiring point. A unit test that imports
  `from mealie.app import start_scheduler` is fine but will trigger the
  full app import chain; better to assert the new task is present in
  `SchedulerRegistry._minutely` (or whichever bucket).

---

## 3. Multitenant test patterns (critical for the case-5 isolation tests)

### 3.1 `tests/multitenant_tests/test_multitenant_cases.py`
- **line_ranges (verified, file is 74 lines):** entire file
- **symbols:** `all_cases` (L13-19), `test_multitenant_cases_get_all`
  (L23-56), `test_multitenant_cases_same_named_resources` (L60-93)
- **importance:** ⭐⭐⭐⭐⭐ — the canonical multitenant harness.
  Parameterized over per-resource subclasses of
  `ABCMultiTenantTestCase`. **This is the pattern case-5 should plug
  into.**
- **reason:** Two slots — `seed_action(group_id)` (single tenant) and
  `seed_multi(group1, group2)` (same-name conflict) — and the harness
  asserts both `(token, [...expected...])` lookups return only that
  tenant's resources.

### 3.2 `tests/multitenant_tests/case_abc.py`
- **line_ranges (verified):** L1-31 (whole file)
- **symbols:** `ABCMultiTenantTestCase` with `seed_action`, `seed_multi`,
  `get_all`, `cleanup`; context-manager `__enter__/__exit__` runs
  cleanup automatically.
- **importance:** ⭐⭐⭐⭐ — shape contract for the new case.
- **For case-5:** we need (at minimum) a `case_shopping_list_autosync.py`
  with `seed_action(group_id)` creating: household → recipe → meal plan
  for today → preference toggle on → target shopping list. `get_all`
  should drive the sync (POST `run-now`) and return shopping-list
  contents so the harness can assert tenant B's list stayed empty.

### 3.3 `tests/multitenant_tests/case_foods.py`
- **line_ranges (verified):** L1-51 (whole file)
- **importance:** ⭐⭐⭐⭐ — closest sibling because foods are exactly
  the resource we add `is_pantry_staple` to. Shows how same-named
  resources are seeded into two groups (L31-43). For case-5 we need an
  equivalent for "pantry-staple flag on Food in group A does not affect
  group B" — see the **Test scaffolding plan** below.

### 3.4 `tests/fixtures/fixture_multitenant.py`
- **line_ranges (verified):** L1-23 (whole file)
- **symbols:** `MultiTenant` dataclass, `multitenants` module-scoped
  fixture that builds two registered users with **independent groups**
  via `build_unique_user(session, random_string(12), api_client)`.
- **importance:** ⭐⭐⭐⭐ — gives two independent groups. For
  cross-household-within-same-group tests, use `h2_user` instead (see
  3.5).

### 3.5 `tests/fixtures/fixture_users.py`
- **line_ranges (verified, file is 351 lines):**
  - `build_unique_user` — L17-52 (registers a fresh user → fresh group
    → fresh household)
  - `h2_user` — L55-118 (another user in **same group** as
    `unique_user`, but **different household**) ← **critical for
    case-5 "household A vs household B in same group" isolation**
  - `g2_user` — L121-176 (another group entirely)
  - `_unique_user` / `unique_user_fn_scoped` / `unique_user` —
    L179-226 (module-scoped is the default and is what the existing
    scheduler tests use)
  - `user_tuple` — L237-306 (two users in the **same household**)
- **importance:** ⭐⭐⭐⭐⭐ — these four fixtures cover every isolation
  axis case-5 needs (same household, same group / diff household,
  diff group entirely).

---

## 4. Event-bus test patterns

### 4.1 `mealie/services/event_bus_service/event_bus_service.py`
- **line_ranges (verified, file is 106 lines):** entire file;
  `EventBusService.dispatch` L66-96 is the entry point used by every
  scheduled task. Note L82-90: if `household_id is None`, it auto-fans
  out to **all households in the group** — likely **not** what case-5
  wants; the spec calls for a single `MealPlanAutoSyncedToShopping`
  event per affected household.
- **importance:** ⭐⭐⭐⭐ — case-5 must pass an explicit `household_id`.

### 4.2 `mealie/services/event_bus_service/event_types.py`
- **line_ranges (verified, file is 208 lines):**
  - `EventTypes` enum — L13-60. **NEW enum value required**:
    `mealplan_auto_synced_to_shopping = auto()`. Because each enum
    value backs a DB-subscriber column (per the docstring L15-18), this
    **requires an Alembic migration**.
  - `EventDocumentType` — L63-77. Likely reuse
    `shopping_list_item` or add a new `mealplan_auto_sync`.
  - `EventShoppingListItemBulkData` — L141-144 — perfect shape to reuse
    (`shopping_list_id` + `shopping_list_item_ids: list[UUID4]`).
- **importance:** ⭐⭐⭐⭐⭐ — case-5 event payload **must** subclass
  `EventDocumentDataBase` and the new `EventTypes` value must be added
  with a migration. There is currently **no test asserting event
  dispatch from a scheduled task**; the existing pattern is to verify
  *side effects* (rows created) rather than mock the bus.
- **For case-5 tests:** to assert "event was dispatched with N items
  and M skipped", use `monkeypatch` on `EventBusService.dispatch` —
  no precedent in the repo for this but it's the simplest path.

### 4.3 Webhook end-to-end test
- **path:** `tests/unit_tests/services_tests/scheduler/tasks/test_post_webhook.py`
- **line_ranges:** L114-149 (`test_event_listener_get_meals_by_date_range`)
- **importance:** ⭐⭐⭐ — this is the **closest thing** to an
  event-bus assertion in the repo: builds an `Event` + payload and
  calls `event_bus_listener.publish_to_subscribers` directly. We can
  imitate to assert payload shape for `MealPlanAutoSyncedToShopping`.

---

## 5. How async tasks are tested today (manual trigger, no run-loop)

**Convention:** import the bare task function and invoke it
synchronously. The `@repeat_every` decorator is **never** awaited in
tests.

| Pattern | Example |
|---|---|
| Direct synchronous call | `create_mealplan_timeline_events()` in `test_create_timeline_events.py:18` |
| Idempotency by re-call | `for _ in range(3): create_mealplan_timeline_events()` `:128-129` |
| Flush before re-read | `database.session.commit()` in `test_delete_old_checked_shopping_list_items.py:53` |
| Time-window via real wall clock | `start - timedelta(minutes=20)` in `test_post_webhook.py:58` |
| No freezegun / time-machine | grep across `tests/` → **0 matches** for `freezegun`, `freeze_time`, `time_machine` |
| Tasks bypass FastAPI BG | `EventBusService()` instantiated without `bg`, runs inline (see `event_bus_service.py:93-96`) |

**No mock-clock infrastructure exists**, and `dateutil.tz.tzlocal()` is
the de-facto "household timezone" today (see
`mealie/services/scheduler/tasks/create_timeline_events.py:36-37`).
The case-5 spec requires per-household timezone — currently
**no such column exists** in `Household` or `HouseholdPreferences`
(verified by grep: 0 `timezone` hits in
`mealie/schema/household/` and `mealie/db/models/household/`). This
means the test must drive timezone-window logic by **injecting** a
chosen tz into the task (refactor recommendation for the implementer).

---

## 6. Preference/shopping/mealplan integration test entry points

### 6.1 `tests/integration_tests/user_household_tests/test_household_perferences.py`
- **line_ranges (verified, file is 63 lines):** entire file
- **symbols:** `test_get_preferences` L10-17,
  `test_preferences_in_household` L20-31,
  `test_update_preferences_no_permission` L34-44,
  `test_update_preferences` L47-63
- **importance:** ⭐⭐⭐⭐⭐ — template for the new
  `auto_sync_meal_plan_to_shopping` / `auto_sync_target_shopping_list_id`
  / `auto_sync_run_time` PATCH coverage. Note: it uses **PUT** today
  (`api_client.put`), not PATCH — the spec says PATCH; we should
  validate which verb the existing controller actually exposes (it's
  `@router.put("/preferences")` in
  `controller_household_self_service.py:58`). Spec says PATCH —
  **flag for design** (cross-perspective Q1).

### 6.2 `tests/integration_tests/user_household_tests/test_group_shopping_lists.py`
- **line_ranges (verified, file is 1353 lines):**
  - `test_shopping_lists_create_one` L35-46
  - `test_shopping_lists_add_recipe` L115-174 (recipe→list, quantity
    accumulation when added twice — direct precedent for "append vs
    increment" behavior)
  - `test_shopping_lists_add_nested_recipe_ingredients` L249+
  - `test_shopping_lists_add_recipes` L177-246 (bulk)
- **importance:** ⭐⭐⭐⭐⭐ — `test_shopping_lists_add_recipe` is
  literally the same merge-on-duplicate semantics the case-5 task
  needs (`quantity` doubles when same recipe added twice, recipe
  reference quantity goes 1→2). Reuse `recipe_ingredient_only` fixture.

### 6.3 `tests/integration_tests/user_household_tests/test_group_mealplan.py`
- **line_ranges (verified, file is 341 lines):**
  - `create_recipe` helper L23-32
  - `create_rule` helper L35-60
  - `test_create_mealplan_no_recipe` L63-77
  - `test_create_mealplan_with_recipe` L80+
- **importance:** ⭐⭐⭐⭐ — reusable helpers for seeding a meal plan
  dated `datetime.now(UTC).date()`. Same dated-today pattern that case-5
  needs.

### 6.4 `tests/fixtures/fixture_shopping_lists.py`
- **line_ranges (verified, file is 95 lines):** `shopping_lists` L24-46,
  `shopping_list` L49-65, `list_with_items` L68-94, `create_item` L10-21
- **importance:** ⭐⭐⭐⭐ — gives us 3-list / 1-list scaffolding so the
  test can verify "the right list got the items" without rolling its own.

### 6.5 `tests/multitenant_tests/case_foods.py`
- See §3.3 — direct template for the pantry-staple cross-household test.

---

## 7. Test scaffolding plan for case-5

Targets (mirroring spec §5):

### A. Unit — `tests/unit_tests/services/scheduler/test_auto_sync.py`
> **Note:** spec says `tests/unit_tests/services/...` but Mealie's
> existing convention is `tests/unit_tests/services_tests/scheduler/tasks/`.
> Follow existing convention; flag the path discrepancy to design.
> (See Cross-perspective Q2.)

| Test | Pattern from | What it asserts |
|---|---|---|
| `test_no_households_with_autosync` | `test_create_timeline_events.py:test_no_mealplans` | task runs cleanly on empty config |
| `test_consolidate_by_food_and_unit` | new — calls `ShoppingListService.bulk_create_items` directly (the existing merge entry point at `shopping_lists.py:154`) | merged `(food_id, unit_id)` produces single item with summed `quantity` |
| `test_pantry_staple_filter` | new — seeds 2 foods, one with the new flag set; assert only non-staple lands in created items | spec §2 step 4 |
| `test_timezone_window` | `test_post_webhook.py:test_get_scheduled_webhooks_filter_query:40` | constructs `auto_sync_run_time` ±15 min from `datetime.now(<tz>)`; task should fire/skip per window |
| `test_idempotent_same_day` | `test_create_timeline_events.py:test_new_mealplan_event_duplicates:103` | call task 3× → only 1 sync; `LastAutoSyncedAt` advanced |
| `test_idempotent_concurrent_workers` | new — manually invoke the task twice in two threads (or in one thread with a deliberate race injection) | spec implementation constraint: multi-replica safety |

### B. Integration — `tests/integration_tests/user_household_tests/test_auto_sync_run_now.py`
| Test | Pattern from | What it asserts |
|---|---|---|
| `test_run_now_happy_path` | `test_group_shopping_lists.py:test_shopping_lists_add_recipe:115` | POST `…/auto-sync-shopping/run-now` returns `{added_count, skipped_pantry_count, target_list_id, run_at}`; list contains the expected items |
| `test_run_now_requires_admin` | `test_household_perferences.py:test_update_preferences_no_permission:34` | non-admin in household → 403 |
| `test_disabled_pref_skips_scheduler` | `test_create_timeline_events.py:test_no_mealplans:16` | call scheduler task while preference is `false` → no list mutation, no event |
| `test_no_meal_plans_today` | new | run-now → `{ added_count: 0, target_list_id, … }` or 204 (spec is ambiguous — Q3) |
| `test_pantry_staple_excluded` | derived from `case_foods.py` + new pantry flag | item with staple flag never appears in list |
| `test_event_dispatched` | `test_post_webhook.py:test_event_listener_get_meals_by_date_range:81` | `monkeypatch` `EventBusService.dispatch` and assert it was called with `EventTypes.mealplan_auto_synced_to_shopping`, expected counts |

### C. Multi-tenant — `tests/multitenant_tests/case_shopping_list_autosync.py` + entry in `test_multitenant_cases.py:all_cases`
Plus a dedicated `test_multitenant_autosync.py` (the parametrized
harness only covers `get_all`-shaped resources; auto-sync needs custom
flow):
| Test | Pattern from | What it asserts |
|---|---|---|
| `test_autosync_isolation_cross_group` | `multitenants` fixture (§3.4) + run-now | household A in group 1 syncs → household B in group 2 list is empty |
| `test_autosync_isolation_cross_household_same_group` | `h2_user` fixture (`fixture_users.py:55`) | household A and `h2_user`'s household share a group; A's run-now never writes to B's list |
| `test_pantry_staple_per_household` | `case_foods.py:seed_multi:27` + new flag | flag set on food in group A does not propagate to identically-named food in group B (since foods are group-scoped per `recipe_ingredient.py:158`) |

### D. Smoke/wiring
| Test | What it asserts |
|---|---|
| `test_auto_sync_registered` | importing `tasks` exposes the new symbol and `start_scheduler` adds it to the right bucket (mirrors absence of any current "is registered" test — new convention worth seeding) |

### Fixtures to add (in `tests/fixtures/fixture_auto_sync.py`)
- `autosync_household` — `unique_user` with preference toggled on, run
  time set to current 30-min window, target list created.
- `household_with_meal_plan_today` — yields `(user, recipe, list)`.

---

## 8. Cross-perspective questions

1. **PUT vs PATCH on `/api/households/preferences`** — spec §1 says
   "新增 `PATCH /api/households/preferences` 字段支持", but the current
   controller exposes `@router.put("/preferences")`
   (`controller_household_self_service.py:58`) and the existing test
   uses `api_client.put` (`test_household_perferences.py:43,56`).
   Do we add a PATCH alongside, replace PUT, or simply add the new
   fields to the existing PUT payload? **History/Spec call.**

2. **Test directory convention** — spec §5 says
   `tests/unit_tests/services/scheduler/test_auto_sync.py`, but every
   existing scheduler test lives under
   `tests/unit_tests/services_tests/scheduler/tasks/`. Confirm we use
   the **existing** path; otherwise pytest collection conventions
   (and `conftest.py:tests/fixtures/*` import discovery) could break.

3. **"No meal plan today" response shape** — spec §5 mentions "204 / 0
   added". Should the run-now endpoint return 204 No Content, or 200
   with `{added_count: 0, …}`? Tests need to commit to one. Picking
   the latter is more useful (callers can read `target_list_id`).

4. **Scheduler bucket choice** — spec §2 says "每 30 分钟跑一次" but
   `SchedulerService` only ships `_minutely` (actually 5-min cadence —
   `scheduler_service.py:16`), `_hourly`, `_daily`. Extending the
   scheduler is invasive; gating inside the task with the
   `auto_sync_run_time` window seems safer. **Design call** —
   tests must match.

5. **Household timezone source** — there is **no per-household nor
   per-group timezone column** today (grep verified). The spec wants
   "household 配置的时区". Does this case add a `timezone` field to
   `HouseholdPreferences`, or does it fall back to server `tzlocal()`
   (as `create_timeline_events.py:36` does)? Tests for §2 "时区窗口
   判断" depend on the answer.

6. **Pantry-staple scope** — spec §4 puts `is_pantry_staple` on
   `Food`. But Mealie deprecated the global `on_hand: bool` (still
   present at `db/models/recipe/ingredient.py:192` marked `# Deprecated`)
   in favor of a **per-household M2M** `households_with_ingredient_food`
   (`ingredient.py:160-162`). Should the new flag follow the same
   per-household pattern? If so, the multi-tenant test in §C item 3
   becomes "pantry-staple flag is per-household" rather than
   "per-group".

7. **`LastAutoSyncedAt` storage** — spec doesn't say *where* this
   column lives. Tests need to know: column on `HouseholdPreferences`,
   on `Household`, or a separate `household_auto_sync_state` table?
   Concurrent-worker test in §A item 6 depends on which row gets
   the `SELECT … FOR UPDATE SKIP LOCKED`.

8. **Event-dispatch assertion strategy** — no precedent in the repo
   for spying on `EventBusService.dispatch` from a test. Plan is
   `monkeypatch` — is that acceptable? Alternative: subscribe a
   listener and capture (much more setup). Confirm with reviewer.
