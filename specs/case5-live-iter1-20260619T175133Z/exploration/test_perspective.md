# Case-5 — Test Perspective Exploration (Stage 3)

Exploration of the Mealie test infrastructure to identify reusable patterns
for case-5 (Meal Plan → Shopping List auto-sync, scheduler-driven, multitenant).

All line ranges have been VERIFIED against the on-disk source under
`C:\Users\v-liyuanjun\Downloads\mealie\` at the time of exploration.

---

## 1. Test infrastructure & global setup

### 1.1 Root conftest.py
- **Path**: `tests/conftest.py`
- **Symbols**: `_clean_temp_dir`, `mp = MonkeyPatch()` (env injection), `override_get_db`, `api_client`, `global_cleanup`
- **Line ranges (VERIFIED)**:
  - Environment patch + DB bootstrap: lines **19–34** (sets `PRODUCTION=True`, `TESTING=True`, `ALLOW_SIGNUP=True`, then calls `main()` from `mealie.db.init_db`)
  - `override_get_db`: lines **37–42**
  - `api_client` (session-scoped, overrides `generate_session` dep): lines **45–53**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Every test for case-5 will need the `api_client` fixture and the
  `TESTING=True` env so `ALLOW_SIGNUP` is True for `_unique_user` and so the
  scheduler isn't started during tests. The `main()` call at module import
  time runs migrations — any new migration we add for `auto_sync_*` /
  `is_pantry_staple` will run automatically before fixtures execute.

### 1.2 Fixture aggregator
- **Path**: `tests/fixtures/__init__.py`
- **Line ranges (VERIFIED)**: lines **1–6** (`from .fixture_admin import *`, etc.)
- **Importance**: ⭐⭐⭐
- **Reason**: All new fixtures we add for case-5 (e.g. a `mealplan_for_today`
  fixture, a `pantry_staple_food` fixture) must be re-exported here to be
  auto-discoverable from `tests.fixtures import *` in `conftest.py`.

---

## 2. Existing shopping list + meal plan integration tests

### 2.1 Shopping list ↔ recipe integration
- **Path**: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` (1113 lines)
- **Key symbols + line ranges (VERIFIED)**:
  - `test_shopping_lists_get_all`: lines **22–32**
  - `test_shopping_lists_create_one`: lines **35–46**
  - `test_shopping_lists_add_recipe` (single recipe, add-twice, merge into existing item): lines **115–174**
  - `test_shopping_lists_add_recipes` (bulk via `ShoppingListAddRecipeParamsBulk`): lines **177–246**
  - `test_shopping_lists_add_cross_household_recipe` (parametrized over `is_private_household` + `lock_recipe_edits_from_other_households`): lines **364–422**
  - `test_shopping_lists_add_one_with_zero_quantity`: lines **425–460+**
  - `test_shopping_lists_add_recipe_with_merge` (single recipe, ingredients dedupe via `consolidate_create_items`): lines **581–660**
  - `test_shopping_lists_add_recipes_with_merge` (cross-recipe shared ingredient merge): lines **663–739**
  - `test_shopping_list_add_recipe_scale` (`recipe_increment_quantity` / `recipe_scale`): lines **742–805**
  - `test_shopping_lists_remove_recipe`: lines **808–850+**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: This file is the canonical reference for how shopping list +
  recipe integration tests are structured. Case-5's "manual trigger /
  happy path" integration test should follow the **exact** pattern at lines
  115–174 (POST → GET → assert items + recipe references), and the merge
  semantics at lines 581–660 / 663–739 demonstrate the assertion patterns
  for `(food_id, unit_id)` aggregation we'll need when verifying
  `consolidate_ingredients` for case-5.

### 2.2 Cross-household recipe → shopping list pattern (closest precedent)
- **Path**: same file, lines **364–422**
- **Symbol**: `test_shopping_lists_add_cross_household_recipe`
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: This is the closest existing precedent for case-5's multitenant
  assertions. It shows the exact pattern of:
  1. mutating a foreign household's `private_household` /
     `lock_recipe_edits_from_other_households` flag via
     `h2_user.repos.household_preferences.update(...)`
  2. creating a recipe via the foreign user's repo with explicit
     `household_id` scoping
  3. POSTing to the route under `unique_user.token` and asserting that
     items are added to *unique_user*'s list (not h2's).
  Case-5's multitenant tests will invert this for the *negative* case:
  trigger auto-sync as `h2_user`, then assert `unique_user`'s shopping list
  is **untouched**.

### 2.3 Meal plan creation + scheduler integration
- **Path**: `tests/integration_tests/user_household_tests/test_group_mealplan.py`
- **Line ranges (VERIFIED)**:
  - Helper `create_recipe`: lines **23–32**
  - Helper `create_rule`: lines **35–60**
  - `test_create_mealplan_no_recipe`: lines **63–77**
  - `test_create_mealplan_with_recipe`: line **80+**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: Demonstrates the canonical `CreatePlanEntry(date=..., entry_type=..., recipe_id=...).model_dump(by_alias=True)` payload shape and the `households_mealplans` POST route that case-5 will need to seed today's meal plan in integration tests.

### 2.4 Household preferences integration tests
- **Path**: `tests/integration_tests/user_household_tests/test_household_perferences.py`
- **Line ranges (VERIFIED)**:
  - `test_get_preferences`: lines **10–17**
  - `test_preferences_in_household`: lines **20–31**
  - `test_update_preferences_no_permission` (uses `user_tuple`, demos the
    `can_manage_household` permission flip): lines **34–44**
  - `test_update_preferences` (happy path with PUT + `UpdateHouseholdPreferences`): lines **47–63**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Case-5 adds three new fields to `UpdateHouseholdPreferences`
  (`auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`,
  `auto_sync_run_time`). Tests for those fields must mirror this file's
  PUT-then-GET pattern exactly (lines 47–63) and reuse the
  `can_manage_household` permission test from lines 34–44 to cover the
  403 path for the `PATCH /api/households/preferences/auto-sync-shopping/run-now`
  admin-gated endpoint.

---

## 3. Existing scheduler / scheduled-task test patterns

### 3.1 Scheduler infrastructure under test
- **Path**: `mealie/services/scheduler/scheduler_service.py`
- **Line ranges (VERIFIED)**:
  - `MINUTES_DAY / MINUTES_5 / MINUTES_HOUR` constants: lines **15–17** (NB: `MINUTES_5 = 5`, so the "minutely" loop is actually a **5-minute** loop)
  - `SchedulerService.start`: lines **20–27**
  - `schedule_daily`: lines **30–53**
  - `_scheduled_task_wrapper` (swallows exceptions, logs them): lines **56–60**
  - `run_daily / run_hourly / run_minutely`: lines **63–81**
- **Path**: `mealie/services/scheduler/scheduler_registry.py`
- **Line ranges (VERIFIED)**:
  - `SchedulerRegistry` class with `_daily / _hourly / _minutely` lists: lines **8–15**
  - `register_minutely`: lines **42–43**
- **Path**: `mealie/services/scheduler/runner.py`
- **Line ranges (VERIFIED)**:
  - `repeat_every` decorator: lines **19–83**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Case-5 specifies "每 30 分钟跑一次" but the existing scheduler
  only has `_minutely` (5 min), `_hourly` (60 min), and `_daily` (1440 min).
  **Important finding**: there is no native "every 30 minutes" hook. The
  task perspective must call this out: either (a) register on `_minutely`
  and let the task itself gate on the 30-minute window via a `last_ran`
  module-global (precedent: `post_webhooks.last_ran` at
  `mealie/services/scheduler/tasks/post_webhooks.py:21`), or (b) the spec
  text "@scheduled" decorator doesn't exist as-is.

### 3.2 Test pattern: invoke task function directly (no time mocking)
The dominant pattern in `tests/unit_tests/services_tests/scheduler/tasks/`
is to **call the task function directly** (no scheduler loop, no time mock):

#### test_delete_old_checked_shopping_list_items.py
- **Path**: `tests/unit_tests/services_tests/scheduler/tasks/test_delete_old_checked_shopping_list_items.py`
- **Line ranges (VERIFIED)**:
  - `test_cleanup`: lines **12–60** — seeds via repo, calls `delete_old_checked_list_items()` directly (line 52), commits, re-queries to verify
  - `test_no_cleanup` (boundary at `MAX_CHECKED_ITEMS`): lines **63–106**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Best single example of "scheduler task unit test" — exactly
  the structure case-5's `tests/unit_tests/services/scheduler/test_auto_sync.py`
  should follow: seed pre-conditions through repo, call the task callable
  directly, commit, assert state. Note line 53's `database.session.commit()`
  call — required after calling the task because the task uses its own
  `session_context()`.

#### test_purge_expired_share_tokens.py
- **Path**: `tests/unit_tests/services_tests/scheduler/tasks/test_purge_expired_share_tokens.py`
- **Line ranges (VERIFIED)**:
  - `test_no_expired_tokens` (no-op smoke test): lines **10–12**
  - `test_delete_expired_tokens` (positive + negative pruning in one test): lines **15–38**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: Demonstrates the "smoke test that the task runs cleanly with
  no data" idiom (lines 10–12) — case-5 should add an analogous
  `test_no_eligible_households` test.

#### test_create_timeline_events.py
- **Path**: `tests/unit_tests/services_tests/scheduler/tasks/test_create_timeline_events.py`
- **Line ranges (VERIFIED)**:
  - `test_no_mealplans`: lines **16–18**
  - `test_new_mealplan_event` (full E2E: API client to create recipe + meal plan, then call task): lines **21–100**
  - `test_new_mealplan_event_duplicates` (**idempotency: 3 invocations create 1 event**): lines **103–140**
  - `test_new_mealplan_events_with_multiple_recipes` (run task once, then 3 more times, assert counts stable): lines **143–205**
  - `test_preserve_future_made_date`: lines **208–253**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: `test_new_mealplan_event_duplicates` at lines 103–140 is the
  canonical pattern for testing daily idempotency that case-5 should
  copy verbatim — see §6 below.

#### test_post_webhook.py
- **Path**: `tests/unit_tests/services_tests/scheduler/tasks/test_post_webhook.py`
- **Line ranges (VERIFIED)**:
  - `webhook_factory`: lines **20–37**
  - `test_get_scheduled_webhooks_filter_query` (window-based filtering: tests "in window" vs `start - 20min` out-of-window): lines **40–78**
  - `test_event_listener_get_meals_by_date_range` (mealplan retrieval + event payload): lines **81–149**
  - `test_get_meals_by_date_range_*` (single day, no overlap, invalid range): lines **152–298**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: `test_get_scheduled_webhooks_filter_query` (lines 40–78) is
  the closest existing precedent for testing a **time-window-based
  schedule filter**. Case-5's auto-sync task has identical semantics
  ("only fire in the 30-min window containing `auto_sync_run_time`"),
  and this test shows the proven pattern: create one "in window" item
  + one "20 minutes before" item, then assert only the in-window one
  fires. Reuse this structure verbatim.

### 3.3 Time-window filtering precedent in production code
- **Path**: `mealie/services/scheduler/tasks/post_webhooks.py`
- **Line ranges (VERIFIED)**:
  - Module-global `last_ran = datetime.now(UTC)`: line **21**
  - `post_group_webhooks(start_dt, group_id, household_id)`: lines **24–79** — uses `last_ran` as the implicit `start_dt`, updates `last_ran = datetime.now(UTC)` at line 35 for the next run
- **Importance**: ⭐⭐⭐⭐
- **Reason**: The current scheduler **does not pass time arguments** to
  tasks; tasks self-manage their windows via module-global `last_ran`
  state. Case-5's `LastAutoSyncedAt` per-household idempotency is a
  natural extension of this pattern (just persisted to DB instead of
  module-global). The test pattern at `tests/.../test_post_webhook.py:40–78`
  shows how to inject a custom `start_dt` for testing.

---

## 4. Existing multitenant test patterns

### 4.1 Repository-level multitenant case framework (recommended for case-5)
- **Path**: `tests/multitenant_tests/`
- **Files**:
  - `case_abc.py` (lines **1–32**): `ABCMultiTenantTestCase` with `seed_action`, `seed_multi`, `get_all`, `cleanup`, plus `__enter__`/`__exit__` context manager
  - `case_foods.py` (lines **1–51**): `FoodsTestCase` — best template since case-5 also modifies the `Food` model. Note `seed_multi` at lines 27–43 creates same-named foods in 2 groups to verify compound unique constraint isolation
  - `case_categories.py`, `case_tags.py`, `case_tools.py`, `case_units.py`: same pattern, different domains
  - `test_multitenant_cases.py` (lines **1–94**): driver with `@pytest.mark.parametrize("test_case_type", all_cases)`
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: The case-5 spec asks for `tests/multitenant_tests/`. The
  cleanest implementation is a new `case_shopping_list_auto_sync.py`
  that subclasses `ABCMultiTenantTestCase` and is added to `all_cases`
  in `test_multitenant_cases.py:13–19`. **However**, the existing
  multitenant cases test only **group-level** `get_all` filtering with
  same-named resources — they do **not** test household-level isolation
  within a group. For case-5's "household A's meal plan must never
  write to household B's shopping list" requirement (the spec's
  KEY assertion), this framework is **insufficient on its own** and
  needs to be combined with the `unique_user + h2_user` fixture pair
  for intra-group household isolation.

### 4.2 Multitenant fixtures
- **Path**: `tests/fixtures/fixture_multitenant.py`
- **Line ranges (VERIFIED)**:
  - `MultiTenant` dataclass: lines **12–15**
  - `multitenants` fixture (module-scoped, two cross-group users): lines **18–23**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: Module-scoped pair of users in **different groups**, built via
  `build_unique_user(session, random_string(12), api_client)`. This is
  the right fixture for case-5's "cross-group isolation" assertions.

### 4.3 Cross-household within same group (the KEY assertion for case-5)
- **Path**: `tests/fixtures/fixture_users.py`
- **Line ranges (VERIFIED)**:
  - `build_unique_user`: lines **17–52** — public helper, returns `TestUser`
  - `h2_user` (same group as `unique_user`, different household): lines **55–118**
  - `g2_user` (different group entirely): lines **121–176**
  - `_unique_user` / `unique_user_fn_scoped` / `unique_user`: lines **179–226**
  - `unique_admin`: lines **229–233**
  - `user_tuple` (two users in same household): lines **236–306**
  - `user_token`: lines **309–328**
  - `ldap_user`: lines **331–350**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: `h2_user` (lines 55–118) is **THE critical fixture** for case-5's
  "household A meal plan must never write to household B's shopping list"
  assertion. It's a second user in the same group as `unique_user` but in
  a different household (created via `POST /api/admin/households`). Pattern:
  1. `unique_user` seeds meal plan → auto-sync triggers
  2. assert `unique_user.repos.group_shopping_lists.get_one(list_id)` has items
  3. assert `h2_user.repos.group_shopping_lists.<h2's list>` is unchanged
  4. Inverse: `h2_user` enables auto-sync, seeds meal plan, runs task,
     assert `unique_user`'s list unchanged.

### 4.4 Multitenant integration example (closest pattern for case-5)
- **Path**: `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py`
- **Line ranges (VERIFIED)**:
  - `test_duplicate_recipe_changes_household` (parametrized on `is_private_household`): lines **16–42**
  - `test_get_all_recipes_includes_all_households`: lines **45–70**
  - `test_get_all_recipes_with_household_filter`: lines **73–100+**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Demonstrates the **parametrize-over-preference + flip-foreign-household-prefs** idiom (lines 16–22) that case-5's tests should reuse: parametrize over `auto_sync_meal_plan_to_shopping = True/False` for h2, then assert h2's shopping list is/isn't touched.

### 4.5 Group-scoped second user (for cross-group tests)
- **Path**: `tests/fixtures/fixture_users.py:121–176` (`g2_user`)
- **Importance**: ⭐⭐⭐⭐
- **Reason**: Case-5's "跨 group 完全隔离" assertion uses this — `g2_user` is
  in a totally separate group, so triggering auto-sync as `unique_user` must
  not even *consider* `g2_user`'s households (which would only happen if
  the task-level repo got `group_id=None`).

---

## 5. Event bus dispatcher mocking pattern

### 5.1 Production event bus dispatch path
- **Path**: `mealie/services/event_bus_service/event_bus_service.py`
- **Line ranges (VERIFIED)**:
  - `EventBusService.__init__(bg, session)`: lines **46–52**
  - `_get_listeners`: lines **54–58**
  - `_publish_event` (the actual hop into listeners): lines **60–64**
  - `EventBusService.dispatch(integration_id, group_id, household_id, event_type, document_data, message)`: lines **66–96**
    - If `household_id is None`, fans out across all households in `group_id` (lines 82–90)
    - If `self.bg` is set, runs `_publish_event` as a background task; otherwise inline (lines 92–96)
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Case-5's `MealPlanAutoSyncedToShopping` event will go through
  exactly this dispatch path with `event_type=<new>`, an explicit
  `household_id`, and the synchronous (no-bg) inline path since the
  scheduler doesn't have `BackgroundTasks`.

### 5.2 No "mock EventBusService" precedent — `requests.post` patching is the idiom
- **Path**: `tests/integration_tests/user_household_tests/test_group_webhooks.py`
- **Line ranges (VERIFIED)**:
  - Local `MockResponse` + `mock_post` capture-list pattern: lines **91–104** — captures `(args, kwargs)` tuples in a closure
  - Monkeypatches the **publisher**, not the bus: `monkeypatch.setattr("mealie.services.event_bus_service.publisher.requests.post", mock_post)` at line 104
  - Asserts dispatch with `mock_calls[0]` kwargs at lines 128–133
- **Path**: `tests/integration_tests/user_household_tests/test_group_recipe_actions.py`
- **Line ranges (VERIFIED)**:
  - Autouse `mock_requests_post` (no-op stub for all tests in module): lines **19–21**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: The codebase has **no precedent for mocking
  `EventBusService.dispatch` directly**. The idiom is to let
  dispatch run end-to-end and patch `requests.post` at the publisher
  level (lines 91–104). For case-5's `MealPlanAutoSyncedToShopping`
  event assertion, the simplest pattern is:
  1. `monkeypatch.setattr("mealie.services.event_bus_service.event_bus_service.EventBusService.dispatch", mock_dispatch)` with a capture-list closure, OR
  2. Patch the publisher (line 104 idiom) and assert via captured `requests.post` payloads.
  Pattern (1) is cleaner for unit tests; pattern (2) matches existing
  integration tests.

### 5.3 Direct listener invocation (purest unit test)
- **Path**: `tests/unit_tests/services_tests/scheduler/tasks/test_post_webhook.py:114–137`
- **Importance**: ⭐⭐⭐⭐
- **Reason**: Demonstrates how to construct an `Event` + `EventWebhookData` payload manually and invoke `listener.publish_to_subscribers(event, subscribers)` directly. Useful if case-5 needs to test event-payload formatting without going through `EventBusService.dispatch`.

---

## 6. How daily idempotency is tested today

### 6.1 Canonical idempotency assertion
- **Path**: `tests/unit_tests/services_tests/scheduler/tasks/test_create_timeline_events.py`
- **Line ranges (VERIFIED)**:
  - `test_new_mealplan_event_duplicates`: lines **103–140** — creates 1 meal plan, then `for _ in range(3): create_mealplan_timeline_events()` (lines **127–129**), then asserts `len(items) == initial_event_count + 1` (line **140**)
  - `test_new_mealplan_events_with_multiple_recipes`: lines **143–205** — runs task once (line 175), asserts counts (lines 176–188), then `for _ in range(3): create_mealplan_timeline_events()` (lines 191–192), re-asserts counts unchanged (lines 194–205)
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: This is **the** idempotency pattern in Mealie's scheduler
  tests. It does **not** use freezegun, does **not** mock `datetime.now()`,
  and does **not** rely on a `LastRunAt` column. Idempotency is enforced
  in the production code by an *application-level "do we already have an
  event for this (recipe, day, subject) tuple?"* query
  (`mealie/services/scheduler/tasks/create_timeline_events.py:53–67`).
  Case-5's `LastAutoSyncedAt` column gives us a cleaner mechanism, but
  the **test pattern stays the same**: run the task 3× and assert the
  shopping list item count + recipe_references stay at the post-first-run
  state.

### 6.2 Repeated-call cleanup test
- `tests/unit_tests/services_tests/scheduler/tasks/test_delete_old_checked_shopping_list_items.py:52` (`delete_old_checked_list_items()` called once) and re-calling within the same test would have no effect → de-facto idempotent — but the file does not explicitly assert multi-invocation idempotency. Case-5 should improve on this and explicitly add a `for _ in range(3): run_auto_sync()` assertion.

---

## 7. Per-household timezone test patterns

**Finding (verified)**: Mealie currently has **no per-household timezone
support**. Searches across `mealie/` and `tests/` for `ZoneInfo`, `pytz`,
`timezone` produced these results:

- `mealie/services/scheduler/tasks/create_timeline_events.py:36–37` uses
  `tzlocal()` (server's local TZ) — `local_tz = tzlocal(); mealplans = repos.meals.get_today(tz=local_tz)`
- `mealie/repos/repository_meals.py:12–21` (`get_today(tz=UTC)`) accepts a
  TZ argument but defaults to UTC
- `mealie/core/settings/settings.py:176–205` (`DAILY_SCHEDULE_TIME` /
  `DAILY_SCHEDULE_TIME_UTC`) — **server-wide** schedule time, not per-household
- `tests/integration_tests/user_household_tests/test_group_webhooks.py:46`
  uses `.astimezone(UTC).time()` for webhook scheduled-time assertions
- **No tests anywhere in the codebase set per-household timezone preferences**

- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Case-5's spec says "must use the household's configured
  timezone (if not configured, group default or server default UTC)" — but
  there is **no household.timezone field or test precedent**. Case-5
  implementation must add this field (in `HouseholdPreferences` or
  `Household`), and tests must be authored from scratch. Suggested test
  approach: parametrize over a small set of `("UTC", "America/New_York",
  "Asia/Tokyo")` and an `auto_sync_run_time` value such that the
  per-timezone "today" date differs from UTC's "today" → assert the right
  meal plan entries are picked up. Use `freezegun.freeze_time(...)` to pin
  "now" to a known UTC instant.

---

## 8. Freezegun / time-travel availability

- **Path**: `pyproject.toml`
- **Line range (VERIFIED)**: line **81** — `"freezegun==1.5.5"` declared as dev dep
- **Existing usage**:
  - `tests/unit_tests/repository_tests/test_pagination.py:12` — `from freezegun import freeze_time`
  - Usage examples: lines **1594, 1606, 1635, 1659** — `@freeze_time("2024-01-15 12:00:00")` decorator on functions
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: `freezegun` is available but **only used for a single utility
  function's tests** (`PlaceholderKeyword._parse_now`). It is **not** used
  anywhere in the scheduler tests yet. Case-5 should be the first to apply
  `@freeze_time` to scheduler task tests for deterministic window-edge
  and timezone-boundary assertions.

---

## 9. Other fixtures & helpers cataloged

### 9.1 TestUser dataclass (the unit of multitenant scoping)
- **Path**: `tests/utils/fixture_schemas.py`
- **Line ranges (VERIFIED)**:
  - `TestUser`: lines **9–28** — has `_group_id`, `_household_id`, `repos: AllRepositories` (already filtered to that user's group+household!)
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: `TestUser.repos` is the magic — repos are pre-scoped to the user's group and household, so calling `unique_user.repos.group_shopping_lists.get_all()` only returns *unique_user's household's* lists. For case-5 multitenant tests, this gives a clean assertion: "after running auto_sync, h2_user.repos.group_shopping_lists.get_one(h2_list_id).list_items should be empty".

### 9.2 Database / session fixtures
- **Path**: `tests/fixtures/fixture_database.py`
- **Line ranges (VERIFIED)**:
  - `session` (module-scoped raw `SessionLocal()`): lines **10–16**
  - `unfiltered_database` (= `get_repositories(session, group_id=None, household_id=None)`): lines **19–21**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: `unfiltered_database` is the right fixture for case-5's task-internal repo (which must walk *all* households, not just one). It's also used by the multitenant case framework (`test_multitenant_cases.py:25–28`).

### 9.3 Admin / admin_token fixtures
- **Path**: `tests/fixtures/fixture_admin.py`
- **Line ranges (VERIFIED)**:
  - `admin_token` (session-scoped): lines **13–18**
  - `admin_user` (module-scoped): lines **21–58**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: The case-5 `is_pantry_staple` admin route on `Food` needs
  admin authentication; `admin_token` is the standard fixture for those
  tests. Also required for the `h2_user` fixture which calls
  `POST /api/admin/households` with `admin_token`.

### 9.4 Shopping list fixtures
- **Path**: `tests/fixtures/fixture_shopping_lists.py`
- **Line ranges (VERIFIED)**:
  - `create_item` helper: lines **10–21**
  - `shopping_lists` (function-scoped, 3 lists per `unique_user`): lines **24–46**
  - `shopping_list` (function-scoped, single list per `unique_user`): lines **49–65**
  - `list_with_items` (single list + 10 items): lines **68–94**
- **Importance**: ⭐⭐⭐⭐⭐
- **Reason**: Case-5 needs an "auto-sync target list" fixture. Reuse the
  `shopping_list` pattern (lines 49–65), assign its ID to the household
  preferences `auto_sync_target_shopping_list_id`, then verify items land
  there. **Note**: the case-5 spec says "if `auto_sync_target_shopping_list_id`
  is null, use the household's first active list" — so case-5 also needs
  a no-target-set test that relies on whichever list `shopping_list`
  fixture creates being the first/default.

### 9.5 Recipe fixtures
- **Path**: `tests/fixtures/fixture_recipe.py`
- **Line ranges (VERIFIED)**:
  - `recipe_ingredient_only` (single recipe, 6 ingredients): lines **31–54**
  - `recipes_ingredient_only` (3 recipes, 6 ingredients each): lines **57–85**
  - `recipe_categories`: lines **88–104**
  - `random_recipe` (with instructions): lines **107–131**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: `recipe_ingredient_only` (lines 31–54) is the right fixture
  for case-5 unit tests — it gives a recipe with ingredients but no
  IngredientFood/Unit objects, which means `consolidate_ingredients`
  collapses on `note`. For testing `(food_id, unit_id)` aggregation
  properly, case-5 must explicitly construct ingredients with
  `IngredientFood` and `IngredientUnit` (see
  `mealie/schema/recipe/recipe_ingredient.py:60–135` for the schema).

### 9.6 Test factory helpers
- **Path**: `tests/utils/factories.py`
- **Line ranges (VERIFIED)**:
  - `random_string`, `random_email`, `random_bool`, `random_int`: lines **7–20**
  - `user_registration_factory`: lines **23–34**
- **Importance**: ⭐⭐⭐⭐
- **Reason**: Standard helpers used everywhere — case-5 tests use them
  identically.

### 9.7 API route registry
- **Path**: `tests/utils/api_routes/__init__.py`
- **Line ranges (VERIFIED)**:
  - `households_preferences = "/api/households/preferences"`: line **104**
  - `households_mealplans = "/api/households/mealplans"`: line **92**
  - `households_shopping_lists = "/api/households/shopping/lists"`: line **114**
  - `households_shopping_lists_item_id_recipe(item_id)`: line **415**
  - `households_shopping_lists_item_id_recipe_recipe_id(item_id, recipe_id)`: line **420**
  - `admin_households = "/api/admin/households"`: line **18**
  - `admin_users = "/api/admin/users"`: line **30**
- **Importance**: ⭐⭐⭐
- **Reason**: This file is **auto-generated by `task dev:generate`**. Case-5
  adds `POST /api/households/preferences/auto-sync-shopping/run-now`, so
  after registering the new route, regenerating this file is **mandatory**
  before tests can use the constant.

---

## 10. Test scaffolding plan for case-5

### 10.1 New test files to create

#### A. Unit tests
**File**: `tests/unit_tests/services_tests/scheduler/tasks/test_auto_sync_shopping.py`

Tests (mirroring `test_create_timeline_events.py` structure verbatim):
1. `test_no_eligible_households` — smoke test, no households opted in; task runs cleanly (mirrors `test_no_mealplans` at `test_create_timeline_events.py:16–18`)
2. `test_opt_out_household_skipped` — `auto_sync_meal_plan_to_shopping=False`, verify no items added
3. `test_consolidate_by_food_and_unit` — two meal plan entries with overlapping `(food_id, unit_id)` → 1 list item w/ summed quantity (mirror `test_shopping_lists_add_recipes_with_merge` at `test_group_shopping_lists.py:663–739`)
4. `test_pantry_staple_filter` — recipe with one `is_pantry_staple=True` food → that food skipped; `skipped_pantry_count` in event payload
5. `test_no_meal_plan_today` — opt-in household with empty plan; 0 added; event still dispatched or not (TBD by spec interpretation)
6. `test_idempotency_same_day` — run task 3× via `for _ in range(3): auto_sync_shopping_lists()`; assert items added once, `recipe_references` not duplicated (mirror `test_create_timeline_events.py:103–140`)
7. `test_window_filter_in_range` — `auto_sync_run_time="10:00"` + `freeze_time("...T10:15:00Z")` → triggers
8. `test_window_filter_out_of_range` — `auto_sync_run_time="10:00"` + `freeze_time("...T11:00:00Z")` → does NOT trigger (mirror `test_get_scheduled_webhooks_filter_query` at `test_post_webhook.py:40–78`)
9. `test_timezone_boundary` — household TZ = `America/New_York`, `auto_sync_run_time="00:00"`, `freeze_time` set so UTC date differs from NY date; verify NY's "today" mealplans are picked up, not UTC's
10. `test_target_list_default_resolution` — `auto_sync_target_shopping_list_id=None` → uses first active list
11. `test_target_list_explicit` — `auto_sync_target_shopping_list_id=<list>` → items go to that list
12. `test_event_dispatched_with_payload` — patch `EventBusService.dispatch` with capture-list closure (or `monkeypatch.setattr` on the publisher per `test_group_webhooks.py:104`), assert `MealPlanAutoSyncedToShopping` event with `(household_id, shopping_list_id, added_item_count, skipped_pantry_count)` payload
13. `test_append_strategy_unchecked_merge` — list already has unchecked item matching `(food_id, unit_id)` → quantity accumulated, not duplicated
14. `test_append_strategy_checked_new_item` — list has checked item with same `(food_id, unit_id)` → new item created (spec rule: only merge into unchecked) — derived from `shopping_lists.py:48–55` `can_merge` check

#### B. Integration tests
**File**: `tests/integration_tests/user_household_tests/test_household_auto_sync_shopping.py`

1. `test_run_now_happy_path` — admin POSTs to `/api/households/preferences/auto-sync-shopping/run-now`; returns `{added_count, skipped_pantry_count, target_list_id, run_at}`
2. `test_run_now_non_admin_403` — uses `user_tuple` per `test_household_perferences.py:34–44`; non-admin gets 403
3. `test_run_now_bypasses_idempotency` — call run-now twice in a row; second call adds items again (bypasses `LastAutoSyncedAt` per spec §3) but updates `LastAutoSyncedAt`
4. `test_run_now_no_meal_plan_today` — no plan; 204 / 0 added (spec mentions i18n key `auto-sync.no-meal-plan-today`)
5. `test_run_now_no_target_list_configured` — opt-in with no list configured and no active lists in household → expected error from i18n key `auto-sync.no-target-list`
6. `test_preferences_patch_new_fields` — PATCH `/api/households/preferences` with `auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, `auto_sync_run_time`; GET back; assert (mirror `test_household_perferences.py:47–63`)
7. `test_pantry_staple_filter_e2e` — admin marks food `is_pantry_staple=true`, run sync, assert that food skipped end-to-end

#### C. Multitenant tests
**File**: `tests/multitenant_tests/test_auto_sync_shopping_isolation.py`

These do NOT fit cleanly into the `ABCMultiTenantTestCase` framework
(which is built around `get_all` REST assertions). Instead, use the
`unique_user + h2_user + g2_user` fixture triplet pattern from
`test_recipe_cross_household.py:16–42`:

1. `test_cross_household_isolation_within_group` (THE KEY TEST):
   - `unique_user` opts in, seeds today's meal plan
   - `h2_user` (same group, different household) opts in, seeds different meal plan
   - run `auto_sync_shopping_lists()` directly
   - assert `unique_user.repos.group_shopping_lists.get_one(...)` has only `unique_user`'s recipe ingredients
   - assert `h2_user.repos.group_shopping_lists.get_one(...)` has only `h2_user`'s recipe ingredients
   - assert NO cross-contamination
2. `test_cross_group_isolation` — `unique_user` and `g2_user` both opt in; run task; assert lists isolated
3. `test_pantry_staple_per_household_scope` — h2 marks food X as `is_pantry_staple=true`; if `Food` is group-scoped, this affects unique_user too (case-5 spec ambiguity to flag). Concretely: spec says "跨 household 的 food pantry-staple 标记不互相影响" so test should ASSERT scoping is per-household OR per-group; CR question to surface.

#### D. Multitenant case (optional, additive)
**File**: `tests/multitenant_tests/case_pantry_staple_foods.py`

If case-5 implements `is_pantry_staple` at group scope, add a subclass of
`ABCMultiTenantTestCase` similar to `case_foods.py:9–51` and append to
`all_cases` in `test_multitenant_cases.py:13–19` to get free coverage of
the new field's `get_all` filtering.

### 10.2 New fixtures to add to `tests/fixtures/`

**File**: `tests/fixtures/fixture_auto_sync.py` (must also be added to
`tests/fixtures/__init__.py:1–6`)

```python
# pseudocode-level summary
@pytest.fixture(scope="function")
def auto_sync_enabled_household(unique_user: TestUser, shopping_list: ShoppingListOut):
    """Sets opt-in preferences and returns the configured target list."""
    prefs = unique_user.repos.household_preferences.get_one(unique_user.household_id, key="household_id")
    prefs.auto_sync_meal_plan_to_shopping = True
    prefs.auto_sync_target_shopping_list_id = shopping_list.id
    prefs.auto_sync_run_time = "00:00"
    unique_user.repos.household_preferences.update(prefs.id, prefs)
    yield shopping_list

@pytest.fixture(scope="function")
def mealplan_today(unique_user: TestUser, recipe_ingredient_only: Recipe):
    """Seeds today's mealplan with one recipe."""
    plan = unique_user.repos.meals.create({
        "date": datetime.now(UTC).date(),
        "entry_type": "dinner",
        "recipe_id": recipe_ingredient_only.id,
        "group_id": unique_user.group_id,
        "household_id": unique_user.household_id,
        "user_id": unique_user.user_id,
    })
    yield plan
    unique_user.repos.meals.delete(plan.id)

@pytest.fixture(scope="function")
def pantry_staple_food(unique_user: TestUser):
    """Creates a Food with is_pantry_staple=True."""
    food = unique_user.repos.ingredient_foods.create(
        SaveIngredientFood(group_id=unique_user.group_id, name=random_string(10), is_pantry_staple=True),
    )
    yield food
    unique_user.repos.ingredient_foods.delete(food.id)
```

---

## 11. Recommended scheduler mock strategy

**Recommendation**: Do **not** mock the scheduler loop (`run_minutely` / `_minutely`).
Do **not** mock `EventBusService.dispatch` for integration tests.
Do mock `datetime.now()` via `freezegun` for window/timezone tests.

### Rationale (backed by codebase precedent)

1. **No loop mocking**: Every existing scheduler task test
   (`test_delete_old_checked_shopping_list_items.py:52`,
   `test_purge_expired_share_tokens.py:35`,
   `test_create_timeline_events.py:48`) calls the task function directly
   (e.g. `delete_old_checked_list_items()`, `purge_expired_tokens()`,
   `create_mealplan_timeline_events()`). The scheduler loop itself
   (`@repeat_every` decorated) is **never** invoked in tests. Case-5
   should call `auto_sync_shopping_lists()` directly the same way.

2. **`freeze_time` for window/timezone tests**: Available in `pyproject.toml:81`,
   used in `test_pagination.py:12, 1594, 1606, 1635, 1659`. Use it for:
   - Pinning "now" to a specific UTC instant during the auto_sync_run_time
     window
   - Asserting per-household timezone resolution (e.g. freeze at
     `2026-06-19T04:30:00Z` and assert NY household's "today" = 2026-06-19
     but Tokyo household's "today" = 2026-06-20)
   - Asserting `LastAutoSyncedAt` cross-day reset (call task at
     `2026-06-19T10:00:00Z` → succeeds; call at `2026-06-19T10:30:00Z`
     → skipped; advance frozen time to `2026-06-20T10:00:00Z` →
     succeeds again)

3. **Capture-list event mock for unit tests**:
   ```python
   def test_event_dispatched(monkeypatch, ...):
       captured = []
       def mock_dispatch(self, **kwargs):
           captured.append(kwargs)
       monkeypatch.setattr(
           "mealie.services.event_bus_service.event_bus_service.EventBusService.dispatch",
           mock_dispatch,
       )
       auto_sync_shopping_lists()
       assert any(c["event_type"].name == "mealplan_auto_synced_to_shopping" for c in captured)
   ```
   This matches the closure-capture idiom used at `test_group_webhooks.py:96–104`
   but applied one level higher (at the bus, not the publisher) because the new
   event has no built-in publisher to intercept.

4. **For integration tests with the run-now endpoint**: Let dispatch run
   end-to-end. Apply the autouse `mock_requests_post` pattern from
   `test_group_recipe_actions.py:19–21` so that no actual HTTP calls go
   out via webhook/Apprise listeners.

5. **For multitenant tests**: Do NOT mock anything. Call
   `auto_sync_shopping_lists()` directly with two pre-seeded households,
   then use `unique_user.repos` and `h2_user.repos` (both pre-scoped via
   `tests/fixtures/fixture_users.py:51 / 114`) to read back isolated
   per-household state. This gives the strongest assurance that
   real-world group/household repository filtering holds.

### Concrete starter template for case-5 unit test
```python
# tests/unit_tests/services_tests/scheduler/tasks/test_auto_sync_shopping.py
from datetime import UTC, datetime
from freezegun import freeze_time
from mealie.services.scheduler.tasks.auto_sync_shopping import auto_sync_shopping_lists
from tests.utils.factories import random_string
from tests.utils.fixture_schemas import TestUser

def test_no_eligible_households():
    # smoke: no households opted in, must run cleanly
    auto_sync_shopping_lists()

@freeze_time("2026-06-19 10:15:00")
def test_within_window_triggers(
    unique_user: TestUser,
    auto_sync_enabled_household,   # new fixture
    mealplan_today,                # new fixture
):
    # auto_sync_run_time defaults to "00:00" in the fixture; flip to 10:00 here
    prefs = unique_user.repos.household_preferences.get_one(
        unique_user.household_id, key="household_id"
    )
    prefs.auto_sync_run_time = "10:00"
    unique_user.repos.household_preferences.update(prefs.id, prefs)

    auto_sync_shopping_lists()
    unique_user.repos.session.commit()  # see test_delete_old_checked_shopping_list_items.py:53

    shopping_list = unique_user.repos.group_shopping_lists.get_one(
        auto_sync_enabled_household.id
    )
    assert len(shopping_list.list_items) > 0
    # idempotency: 2nd run no-op
    auto_sync_shopping_lists()
    unique_user.repos.session.commit()
    shopping_list_v2 = unique_user.repos.group_shopping_lists.get_one(
        auto_sync_enabled_household.id
    )
    assert len(shopping_list_v2.list_items) == len(shopping_list.list_items)
```

---

## 12. Cross-perspective questions

For the coordinator / design / impl perspectives to resolve:

1. **Scheduler frequency mismatch**: spec says "每 30 分钟跑一次" via
   `@scheduled` decorator, but Mealie's scheduler only has `_minutely`
   (which is **actually 5-minute** — see `scheduler_service.py:16,77`),
   `_hourly`, and `_daily`. There is **no `_thirty_minute` hook and no
   `@scheduled` decorator**. Choices:
   - (a) Add a new `_thirty_minute` registry list + decorated runner (architectural change)
   - (b) Register on `_minutely` and gate inside the task on a 30-min window (uses `post_webhooks.py:21–35` `last_ran` pattern)
   - (c) Register on `_hourly` and run twice via internal scheduling
   - Question: which does the design perspective prefer? This shapes whether the test seeds 1 invocation or N.

2. **Per-household timezone storage**: case-5 spec assumes per-household
   timezone but **Mealie has no household.timezone field today**. Where
   does the new field live — `HouseholdPreferences`, `Household`, or `Group`?
   How does the test discover the "household timezone" repo path? This
   needs an explicit decision before any timezone test can be written.

3. **`is_pantry_staple` scope**: spec §4 says `Food.is_pantry_staple`
   added to `foods` table, but `Food` is currently **group-scoped** (see
   `case_foods.py:12-25` `seed_action(group_id)`). If a food is shared
   across households-in-a-group, then `is_pantry_staple` is also shared,
   contradicting test §5 "跨 household 的 food pantry-staple 标记不互相影响".
   Two possible interpretations:
   - (a) the assertion really means "cross-*group* doesn't leak" (which is
     trivially true given group-scoping)
   - (b) `is_pantry_staple` needs to move to a per-household join table.
   The test perspective cannot answer this without spec/design clarification.

4. **Daily idempotency: "LastAutoSyncedAt" location**: spec mentions
   "用 `LastAutoSyncedAt` 记录" — column on what table? Plausible options:
   `household_preferences`, a new `household_auto_sync_state` table, or a
   `meta_kv` row. The test pattern depends on this — repo fixture access
   for the state value must be defined.

5. **`MealPlanAutoSyncedToShopping` event type**: does `EventTypes` enum
   (see `mealie/services/event_bus_service/event_types.py`) get a new
   variant? The unit test asserting `event_type == EventTypes.<new>` needs
   the exact enum name from the impl perspective.

6. **i18n keys**: spec mentions `auto-sync.no-meal-plan-today`,
   `auto-sync.no-target-list`, `auto-sync.already-synced-today` — these
   would surface as `mealie/lang/messages/en-US/messages.json` entries
   (only English per `.github/copilot-instructions.md` "Translations"
   rule). Integration tests asserting the run-now endpoint's error
   responses need to know the HTTP status codes (400? 409? 204?) for
   each — spec is ambiguous.

7. **Postgres FOR UPDATE SKIP LOCKED**: spec §"实现约束" requires
   `SELECT ... FOR UPDATE SKIP LOCKED` for multi-worker safety. Mealie's
   test infrastructure uses SQLite by default (see
   `tests/conftest.py:53` — `settings.DB_PROVIDER.db_path.unlink()`
   handles SQLite cleanup). SQLite **does not support `FOR UPDATE SKIP
   LOCKED`**. Options:
   - (a) `SELECT ... FOR UPDATE SKIP LOCKED` only kicks in for Postgres
     and falls back to advisory-lock-free path for SQLite (gated by
     `settings.DB_PROVIDER.name`)
   - (b) CAS via `LastAutoSyncedAt` is the only cross-DB mechanism and
     `FOR UPDATE` is dropped from the implementation
   - The test perspective needs to know which, because (a) means a
     separate Postgres-only test (which doesn't exist in this codebase
     today — `task py:postgres` is for dev, not CI), and (b) means CAS
     testing only.

8. **Manual-trigger endpoint method**: spec §3 says `POST /api/households/preferences/auto-sync-shopping/run-now` but spec §1 also adds `PATCH /api/households/preferences` — the existing endpoint is `PUT /api/households/preferences` (see `test_household_perferences.py:43,56`). Confirm new endpoints use POST/PATCH per spec or align with existing PUT convention.

9. **Bulk add via existing service**: spec §"实现约束" requires reuse of
   `mealie/services/household_services/shopping_lists.py`. The natural
   reuse target is `ShoppingListService.add_recipe_ingredients_to_list`
   (lines 413–455). However, that method ties items to a single recipe
   reference at a time. For case-5's "merge today's meal plan entries
   across multiple recipes", the test pattern from
   `test_shopping_lists_add_recipes_with_merge` (`test_group_shopping_lists.py:663–739`)
   applies — but does the impl pass `recipe_items` as one bulk list or
   loop one recipe at a time? This affects whether the test asserts a
   single `recipe_references` array with N refs or N separate add
   operations.
