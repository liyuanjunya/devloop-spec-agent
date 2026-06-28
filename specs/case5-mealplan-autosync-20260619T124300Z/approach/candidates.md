# Case 5 — Approach Candidates (Stage 4)

> Three approaches considered for Meal Plan → Shopping List auto-sync. All three deliver the same functional outcome (the 5 HouseholdPreferences columns, the pantry-staple column, the consolidation pipeline reuse, the event dispatch, the manual trigger, the multitenant guarantees). They differ in **how the sync is triggered** and **how idempotency is enforced**.
> Evaluation criteria: alignment with spec input §2 ("每 30 分钟跑一次"), reuse of existing Mealie abstractions, multi-replica safety, complexity of new code, testability, and risk of regression in adjacent subsystems (shopping list, scheduler).

---

## Approach A — Polling-based (scheduler tick + window gate)

### Description
- Register a single new task `auto_sync_meal_plan_to_shopping` in `SchedulerRegistry.register_minutely(...)` at `mealie/app.py:134-136`. The existing `register_minutely` bucket fires every 5 minutes (`scheduler_service.py:16` `MINUTES_5 = 5` + `:77-81` `run_minutely`).
- The task loop iterates `groups → households` (mirroring `delete_old_checked_shopping_list_items.py:54-75`). For each household:
  1. Load `HouseholdPreferences`; if `auto_sync_meal_plan_to_shopping = False`, skip.
  2. Compute `now_in_tz = datetime.now(tz=ZoneInfo(prefs.timezone or "UTC"))`. If `prefs.auto_sync_run_time <= now_in_tz.strftime("%H:%M") < (run_time + 30 min)` is false, skip.
  3. Compute `today_start_utc = today_in_household_tz_at_midnight.astimezone(UTC)`. Issue **CAS UPDATE**: `UPDATE household_preferences SET last_auto_synced_at = :now_utc WHERE id = :pref_id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_start_utc)`. If `rowcount == 0`, another worker won or today already synced — skip.
  4. Fetch today's meal plans via `repos.meals.get_today(tz=ZoneInfo(prefs.timezone or "UTC"))` (existing API at `mealie/repos/repository_meals.py:11-22`).
  5. Resolve target list: `prefs.auto_sync_target_shopping_list_id` or fallback "first active main list".
  6. Build `recipe_items: list[ShoppingListAddRecipeParamsBulk]` (one per recipe entry); pantry filter is applied by passing `recipe_ingredients=[i for i in recipe.recipe_ingredient if not (i.food and i.food.is_pantry_staple)]` into `get_shopping_list_items_from_recipe`.
  7. Call `ShoppingListService.add_recipe_ingredients_to_list(target_list_id, recipe_items)` (`shopping_lists.py:413-455`).
  8. Dispatch `EventTypes.meal_plan_auto_synced_to_shopping` via `EventBusService(session=session).dispatch(...)`.

### Pros
- **Spec compliance** — directly satisfies "每 30 分钟跑一次" (window check makes the effective cadence 30 min for any given household).
- **Reuses existing scheduler abstraction** — exactly what spec §"实现约束" demands ("不要新建并行 scheduler").
- **Multi-replica safe** — single CAS UPDATE works on both SQLite and Postgres without `FOR UPDATE SKIP LOCKED` (which SQLite lacks per history H5). Per spec § implementation constraint.
- **Simple to test** — call `auto_sync_meal_plan_to_shopping()` directly in tests (matches `test_create_timeline_events.py:18` pattern). No clock mock needed; manipulate `last_auto_synced_at` and `auto_sync_run_time` to drive scenarios.
- **No subsystem-level changes** — touches `scheduler/tasks/` (new file) + `tasks/__init__.py` + `app.py` (one positional arg). Scheduler core untouched (avoids the historical fragility of PR #3820/#3914/#3645).
- **Idempotency works under all failure modes** — if a tick crashes mid-run, the next tick within the same household-local day finds `last_auto_synced_at >= today_start_utc` and skips (no double-write). If a tick succeeds partway then crashes, the marker has already been set, so the partial write is final for the day — acceptable per spec §2 "同一 household 每天最多触发 1 次".

### Cons
- **5-minute polling overhead** — the task fires 288 times/day. For each tick, it loads all groups + households and checks gates. For a deployment with 100 households, that's 28,800 row reads/day before any work happens. Mitigation: the per-household work short-circuits early (gate checks are O(1) per household; only one CAS roundtrip per skipped household).
- **Window math edge case at DST boundary** — if a household's tz observes DST and the configured `auto_sync_run_time` falls in the "skipped" hour (e.g., 02:30 when clocks spring forward from 02:00 to 03:00), that day is missed. Spec doesn't define DST behavior; document as a known limitation. (Same hazard exists in current `create_mealplan_timeline_events:36` `tzlocal()` code.)

---

## Approach B — Event-driven (SQLAlchemy listeners on MealPlan / ShoppingList)

### Description
- Register SQLAlchemy `after_insert` / `after_update` listeners on `GroupMealPlan` (`mealie/db/models/household/mealplan.py:55-77`) and `ShoppingList` (`shopping_list.py:147-181`). On any meal-plan write whose `date == today_in_household_tz`, enqueue an async task to re-sync that household's preferences-target list.
- Dedup via a debounce/coalesce keyed on `(household_id, today_date)` plus the same `last_auto_synced_at` CAS guard.
- No scheduler registration at all. Tasks run inside the FastAPI request/response cycle or via `BackgroundTasks`.

### Pros
- **Zero polling** — sync happens on real user actions, eliminating the 288/day idle ticks.
- **Lower latency** — items appear in the shopping list moments after the meal plan is saved, not "sometime in the next 30 minutes". Better UX.
- **No timezone-window math** — the trigger is "user added an entry for today" rather than "today's clock hit X". DST hazard disappears.

### Cons
- **Violates spec mandate** — spec §2 explicitly says "每 30 分钟跑一次", "在 household 时区下的 auto_sync_run_time 时刻所在的 30 分钟窗口内触发" — both presuppose polling. Going event-driven would silently change the contract.
- **Violates spec implementation constraint** — "必须复用 `mealie/services/scheduler/` 既有抽象". Event-driven design uses zero scheduler.
- **Loses the daily-batch semantic** — spec §2 step 6 implies one consolidated run per day; event-driven would fire on each meal-plan write, producing multiple smaller writes per day even with debouncing.
- **Higher complexity** — SQLAlchemy event listeners must be wired in `mealie/db/db_setup.py`; cross-cutting and easy to break in tests. None of the existing tasks use this pattern; would set a brittle precedent.
- **Debounce / coalesce is non-trivial** — needs an extra "pending sync" sidecar table or in-memory state. Per history Risk #4, in-memory state breaks multi-replica.
- **Manual trigger becomes redundant** — if every write auto-syncs, the `run-now` endpoint loses its purpose, conflicting with spec §3.
- **Harder to test** — requires real ORM events; can't be called synchronously like a scheduler function.

---

## Approach C — Hybrid (polling for scheduled run + admin manual trigger only)

### Description
- Same scheduler registration as Approach A.
- The manual trigger endpoint `POST /api/households/preferences/auto-sync-shopping/run-now` shares 100% of its execution logic with the per-household block of the scheduler task (extracted helper `_sync_one_household(...)`).
- The manual trigger bypasses (a) the `auto_sync_meal_plan_to_shopping = True` toggle check (admin override) and (b) the `last_auto_synced_at` CAS guard, but **does** update `last_auto_synced_at` after the sync per spec §3 ("仍更新它").

### Pros
- **Spec compliance** — satisfies both §2 (every-30-min poll) and §3 (admin manual trigger), which the spec author lists as distinct sub-requirements.
- **Shared code path** — the helper extracted in step 2 above means the scheduler and the manual route exercise the exact same consolidation/event dispatch logic. Reduces drift and per-path bug surface.
- **All Approach A pros carry over** — scheduler reuse, multi-replica safe CAS, simple to test.
- **Adds zero new infrastructure beyond Approach A** — same files touched plus the route method already required by spec §3.

### Cons
- **No new cons over Approach A** — Approach C *is* Approach A plus the spec-mandated manual trigger. The "hybrid" framing is mostly nominal: spec §3 already mandates the route, so it's a hybrid by construction, not a design choice.
- Slight refactor risk in the helper signature — must accept overridable flags `(bypass_daily_limit: bool, bypass_enabled_check: bool)` to share between the two callers. Mitigation: a small named-tuple or kwargs.

---

## Evaluation matrix

| Criterion | A: Polling | B: Event-driven | C: Hybrid |
|---|---|---|---|
| Aligns with spec §2 ("每 30 分钟跑一次") | ✅ Direct | ❌ Replaces polling with events | ✅ Direct (extends A) |
| Aligns with spec §3 (admin manual trigger) | ⚠️ Bolted-on as a second route | ❌ Redundant after event-driven | ✅ Shared helper |
| Aligns with spec §"实现约束" ("必须复用既有 scheduler") | ✅ Yes | ❌ Uses no scheduler | ✅ Yes |
| Multi-replica safety | ✅ CAS UPDATE | ⚠️ Needs sidecar / lock | ✅ CAS UPDATE |
| Reuse of existing abstractions | ✅ scheduler + ShoppingListService | ⚠️ Brand-new SQLAlchemy listener wiring | ✅ scheduler + ShoppingListService |
| Lines of new infra code | Lowest (~250) | Highest (~600+ incl. debouncer + listeners) | Lowest+ (~270 — adds shared helper) |
| Testability | ✅ Direct sync call | ❌ Requires ORM event fixtures | ✅ Direct sync call |
| Regression risk (adjacent systems) | Low (task isolated) | High (touches db_setup, ORM listeners) | Low |
| DST / timezone edge cases | ⚠️ Documented limitation | ✅ No tz-window math | ⚠️ Same as A |
| Idle overhead | ⚠️ 288 ticks/day | ✅ None | ⚠️ 288 ticks/day |
| **Compliance with input §2 mandate** | ✅ **Mandatory** | ❌ **Violates** | ✅ **Mandatory** |

---

## Selected: **Approach C (Hybrid)**

See `selected.md`.

Input §2 explicitly mandates polling ("每 30 分钟跑一次"), which rules out Approach B regardless of its UX merits. Between A and C, the only difference is whether the manual trigger (spec §3) shares code with the scheduler block — and since spec §3 mandates the manual trigger, sharing code is strictly better than duplicating. Hence **Hybrid (C) = Polling (A) + spec-mandated route + extracted helper**.
