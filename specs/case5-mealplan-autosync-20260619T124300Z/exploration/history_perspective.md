# Case-5 — History Perspective

Mealie repo at `C:\Users\v-liyuanjun\Downloads\mealie\` (HEAD of
default branch). All commits below verified with
`git --no-pager log --all -n N --pretty=format:"%h|%ad|%s" --date=short
-- <path>` and `git --no-pager show --stat <sha>`.

---

## Scope-of-history queries actually run

| # | Query | Hits |
|---|---|---|
| 1 | `git log -n 40 -- mealie/services/scheduler/` | 38 commits — full history |
| 2 | `git log -n 40 -- mealie/services/household_services/shopping_lists.py` | 6 commits (file is young — first appeared in #3970) |
| 3 | `git log -n 40 -- mealie/services/event_bus_service/` | 26 commits |
| 4 | `git log --grep="scheduler|scheduled|cron" -i` | 16 commits |
| 5 | `git log --grep="household preferences|HouseholdPreferences|pantry" -i` | 0 commits — no past PR mentions either phrase in its subject |
| 6 | `git log --grep="auto sync|auto-sync|autosync" -i` | 0 commits — **green field** for the feature |
| 7 | `git log -- mealie/schema/household/` | 18 commits since Households were introduced |
| 8 | `git log -- mealie/db/models/household/` | 14 commits |
| 9 | `git log -- mealie/db/models/recipe/ingredient.py` (Food model) | 30 commits |
| 10 | `git log -- mealie/db/models/household/preferences.py` | 5 commits (preferences are touched rarely) |

> Key takeaway from #5/#6: there is **no prior PR for auto-sync or
> pantry**. The closest semantic match is `on_hand` (PR #3777, see
> commit `a062a4be` below) — which is exactly the precedent the spec's
> `is_pantry_staple` should match.

---

## Top 15 commits and their impact on case-5

| # | sha | date | title | Impact on case-5 |
|---|-----|------|-------|------------------|
| 1 | `eb170cc7` | 2024-08-22 | feat: **Add Households to Mealie** (#3970) | **Foundational.** Created `households` + `household_preferences` tables, the M2M `households_to_ingredient_foods`, and the household-scoping in `RepositoryMeals.get_today` (`repo_meals.py:13`). All case-5 work rides on this schema. Migration `2024-07-12-16.16.29_feecc8ffb956_add_households.py`. |
| 2 | `a062a4be` | 2024-06-29 | feat: **Add the ability to flag a food as "on hand", to exclude from shopping list** (#3777) | **Strongest precedent.** Added `on_hand: bool` column on `IngredientFoodModel` (`db/models/recipe/ingredient.py:192`, now marked `# Deprecated`), the migration template (`32d69327997b_add_staple_flag_to_foods.py`), and admin UI surface (`pages/group/data/foods.vue`). Case-5's `is_pantry_staple` should follow this template — and learn from the *deprecation*. |
| 3 | `e9892aba` | 2025-01-13 | feat: **Move "on hand" and "last made" to household** (#4616) | **Critical refactor that obsoleted commit #2's design.** Replaced the boolean `on_hand` on Food with a per-household M2M (`households_with_ingredient_food` in `ingredient.py:160-162`). Tells us: **a global Food-level flag is the *wrong* abstraction in this codebase** — pantry-staple should likely be per-household too. Otherwise case-5 will be reverted by the next maintainer. |
| 4 | `d5f7a883` | 2024-07-08 | fix: **Make Mealie Timezone-Aware** (#3847) | Established the convention: store naive UTC, convert at the edges (see `db/models/_model_utils/datetime.py:22-38`). Forbids `datetime.now()` without `tz=UTC`. The case-5 spec echoes this rule verbatim. |
| 5 | `5b1e827d` | 2024-07-20 | fix: **Convert Daily Schedule Time to UTC** (#3914) | Built `DAILY_SCHEDULE_TIME_UTC` in `settings.py:187-210` (a property that parses `HH:MM` and converts via `tzlocal()`). This is the **exact same shape** as the per-household `auto_sync_run_time` parser case-5 needs. Reuse the pattern. |
| 6 | `b0cc7c4c` | 2024-06-30 | fix: **Daily task scheduler can be off by an hour** (#3820) | Existing scheduler is fragile around DST and timezone boundaries. Touched only `scheduler_service.py` (+14 / −7). Tells us: the 30-min window check must be exact-comparison-safe, not "close enough". |
| 7 | `e07467df` | 2024-05-26 | fix: **Set the daily schedule to a specific time, rather than 24hr from start up** (#3645) | Same theme — original scheduler used "24h from process start" which broke after container restarts. Reinforces #6's lesson. |
| 8 | `8d325198` | 2024-12-17 | fix: **Use configured server time when calling `RepositoryMeals.get_today()`** (#4734) | Modified `repo/repository_meals.py`, `routes/households/controller_mealplan.py`, and `tasks/create_timeline_events.py` — proves `get_today(tz=...)` is **the** path to "today's meal plans" and the timezone arg is honored. Case-5 must pass the household tz. |
| 9 | `eb170cc7` (reuse) | 2024-08-22 | (same) | Scheduler tasks before #3970 were group-scoped; this PR rewrote them to be household-scoped (see `tasks/delete_old_checked_shopping_list_items.py:62-75` — nested group→household→list loop). Case-5 follows the same nested iteration. |
| 10 | `e52a887e` | 2026-03-26 | fix: **publish all mealplan create, update, and delete events** (#7015) | Most recent event_bus change. Added migration `…edaf73d_add_mealplan_updated_and_deleted_to_.py` for new `EventTypes` values + new columns on `events`. **Confirms the workflow** for adding `EventTypes.mealplan_auto_synced_to_shopping`: enum addition + alembic migration adding subscriber columns. |
| 11 | `b153ddf8` | 2023-10-07 | feat: more shopping list enhancements (#2587) | First scheduler-touching shopping-list cleanup; introduced `delete_old_checked_list_items` task — the template for "scheduled task that mutates shopping lists." |
| 12 | `6cbc308d` | 2025-08-16 | fix: **Add Recipe From Another Household To Shopping List** (#5892) | Recent bug: cross-household add-recipe was broken. Patched `services/household_services/shopping_lists.py` (+6 / −1). **Risk hotspot** for case-5: any cross-household path through `shopping_lists.py` is historically buggy. |
| 13 | `60d92948` | 2025-11-03 | feat: **Add recipe as ingredient** (#4800) | Introduced nested-recipe expansion in `get_shopping_list_items_from_recipe` (`shopping_lists.py:344-355`). Case-5's "consolidate ingredients" must handle this (otherwise nested recipes silently skip pantry-staple filtering). |
| 14 | `b5c089f5` | 2026-03-09 | feat: **Unit standardization / conversion** (#7121) | Most recent change to `shopping_lists.py`. Introduced `UnitConverter.can_convert` + `merge_quantity_and_unit` (used in `can_merge` L57-68 and `merge_items` L86-92). Case-5's consolidation must keep using these (no DIY merge). |
| 15 | `716c85cc` | 2025-02-27 | fix: **Bulk Add Recipes to Shopping List** (#5054) | Latest shopping-list bug fix — broke when the bulk endpoint hit the `bulk_create_items` consolidation path. Same code we're reusing. Triple-check our test coverage there. |

---

## Prior scheduled-task patterns

Pulled from the 38 commits to `mealie/services/scheduler/`. The
convention is remarkably stable since 2022.

### Pattern A — Module function + side-effect, no class

Every task is a top-level function that takes **no arguments** (so it
can be registered via `SchedulerRegistry.register_*`). It opens its own
session via `with session_context()` and walks the
groups→households→resources tree itself.

> Evidence: `tasks/delete_old_checked_shopping_list_items.py:54-75`,
> `tasks/create_timeline_events.py:125-134`, `tasks/post_webhooks.py:24-79`.

**Implication for case-5:** `tasks/auto_sync_shopping.py` must export
one zero-arg function `auto_sync_meal_plan_to_shopping()`. Helper
functions that take args (for testability) are nested below it.

### Pattern B — Idempotency via DB queries, not external state

`create_timeline_events.py:64-67` queries existing events with the
exact subject filter to skip duplicates — no Redis, no in-memory set.
`post_webhooks.py:21,29,35` keeps a module-global `last_ran` datetime
(deliberately process-local — single-worker assumption).

**Implication for case-5:** the `LastAutoSyncedAt` column must be a DB
column on `HouseholdPreferences` (or a sibling table), since the
existing scheduler does **not** assume a single worker for everything
(see #4429 — `reset_locked_users` race) and the case-5 spec explicitly
calls out multi-replica. The CAS approach is correct.

### Pattern C — `dateutil.tz.tzlocal()` for "household time"

`create_timeline_events.py:36` uses `tzlocal()` as a stand-in for any
per-household timezone (there isn't one yet — see Risk #2 below).
`settings.py:204-207` does the same for `DAILY_SCHEDULE_TIME_UTC`.

**Implication for case-5:** until a real `timezone` column lands on
`HouseholdPreferences`, the implementer will either:
(a) add the column (preferred, per spec §"实现约束"), or
(b) fall back to `tzlocal()` (matches existing code but breaks the
spec's "per-household timezone" promise).

### Pattern D — No mock clock in tests; construct data near `now()`

Grep across `tests/` confirms **0 hits** for `freezegun`,
`freeze_time`, `time_machine`. The closest "time-window" test
(`test_post_webhook.py:40-78`) constructs `start - timedelta(min=20)`
to manufacture out-of-window data. Case-5 follows suit.

### Pattern E — `repeat_every` is **never** awaited in tests

Tests import the underlying task function directly
(`from mealie.services.scheduler.tasks.X import Y; Y()`). The
`@repeat_every` wrapper is only exercised by
`SchedulerService.start()` at app boot. Verified in every
`test_*` under `tests/unit_tests/services_tests/scheduler/tasks/`.

### Pattern F — Major commits affecting scheduler shape

The scheduler had two architecture-level changes worth knowing:

1. `045798e9` (2022-04-10) **chore: drop-apscheduler** (#1152) —
   removed `apscheduler` in favor of the tiny in-process
   `repeat_every` decorator. **There is no cron string today**; case-5
   cannot say "0 0,30 * * *".
2. `5b1e827d` / `b0cc7c4c` / `e07467df` (2024 mid-year) — three
   independent fixes to the "daily at X o'clock" logic.
   Implication: anything time-of-day-bound (case-5 included) **must
   ship with end-to-end tests around the window edges** — this has
   regressed three times in one year.

---

## Recent household preference / Food model changes

### `HouseholdPreferences` schema (`mealie/db/models/household/preferences.py`, 5 commits)

| sha | date | what changed |
|---|---|---|
| `eb170cc7` | 2024-08-22 | initial creation in #3970 |
| `fd0257c1` | 2024-09-17 | `feat: Additional Household Permissions` (#4158) — added `lock_recipe_edits_from_other_households` (see model L29). **This is exactly the shape of column we'll add for case-5.** |
| `245ca5fe` | 2025-07-31 | `feat: Remove "Is Food" and "Disable Amounts" Flags` (#5684) — deprecation pattern; field `recipe_disable_amount` left in model (L40) but marked `# Deprecated`. Tells us the **deprecation discipline**. |
| `d2b0681d` | 2026-04-11 | `feat: Announcements` (#7431) — added `show_announcements` (L27). Pure-additive Pydantic + alembic. |
| `642c826f` | 2026-05-21 | security fix (#7629) on query filter — touched repository, not preference shape itself. |

**Migration cadence:** when `HouseholdPreferencesModel` gets a new
column, the PR ships an alembic file under `mealie/alembic/versions/`
(naming convention `YYYY-MM-DD-HH.MM.SS_<hash>_<description>.py`).
PRs #4158 and #7431 are the cleanest templates to copy for case-5.

### `Food` / `IngredientFoodModel` (`mealie/db/models/recipe/ingredient.py`, 30 commits)

| sha | date | what changed (case-5 relevance) |
|---|---|---|
| `a062a4be` | 2024-06-29 | **Added `on_hand` boolean** (#3777). Migration `32d69327997b_add_staple_flag_to_foods.py`. ✱ THIS IS THE TEMPLATE for adding `is_pantry_staple`. |
| `eb170cc7` | 2024-08-22 | Households arrival — added `households_with_ingredient_food` M2M (L160-162). |
| `e9892aba` | 2025-01-13 | **Deprecated `on_hand`** in favor of the M2M (L191 comment `# Deprecated`). ✱ THIS IS THE LESSON: a global Food bool got obsoleted within 6 months. |
| `245ca5fe` | 2025-07-31 | Removed "Is Food" / "Disable Amounts" flags. |
| `60d92948` | 2025-11-03 | Added recipe-as-ingredient — Food now references nested recipes. Case-5's consolidation must traverse this (see `services/household_services/shopping_lists.py:344-355`). |
| `b5c089f5` | 2026-03-09 | Unit standardization (#7121). Touched `recipe_ingredient.py` and `ingredient.py` together. Case-5's `(food_id, unit_id)` grouping should reuse `UnitConverter`. |
| `642c826f` | 2026-05-21 | Security fix on query filter — affects how we expose `is_pantry_staple` in `query_filter` strings. |

---

## Risk hotspots (where case-5 will trip)

1. **Cross-household shopping-list mutations** — `6cbc308d`
   (#5892, 2025-08-16) and `716c85cc` (#5054, 2025-02-27) both fixed
   *recent* bugs in this exact path. The case-5 scheduler walks all
   households and writes to per-household lists; an off-by-one in the
   household scope (e.g., passing `group_id` without `household_id`
   into `get_repositories`) will silently fan out writes — exactly the
   bug class #5892 fixed. **Mitigation:** the multi-tenant test in
   §C of the test perspective is non-negotiable.

2. **Per-household timezone is absent.** `git log -- mealie/schema/household/`
   and `mealie/db/models/household/` confirm: **no `timezone` column
   has ever existed**. The spec assumes one. If case-5 ships *without*
   adding it, the `auto_sync_run_time` will silently use server
   `tzlocal()` (`tasks/create_timeline_events.py:36` precedent), which
   becomes wrong the moment two households in two timezones share a
   server. **Risk:** the same class of bug as #3820 / #3914 / #3645 —
   which regressed three times in one year.

3. **Pantry-staple at Food level repeats a known mistake.** Commit
   `e9892aba` (#4616) explicitly *moved* `on_hand` off Food because
   "on hand" is per-household. If case-5 keeps `is_pantry_staple` on
   `Food` as the spec literally says, expect a follow-up PR to refactor
   it within months. **Mitigation:** at minimum, make it a
   per-household M2M like `households_with_ingredient_food` (see
   `db/models/recipe/ingredient.py:160-162` for the existing pattern).

4. **Single-worker assumption in `post_webhooks.last_ran`.** That
   module-global at `tasks/post_webhooks.py:21` is silently broken for
   multi-replica deploys today. Nobody has noticed because webhooks
   are idempotent-ish. **Don't copy this pattern** for
   `LastAutoSyncedAt` — use a DB column with CAS as the spec demands.

5. **Scheduler buckets are coarse-grained.** Only 5-min
   (`MINUTES_5 = 5` in `scheduler_service.py:16`), hourly, daily. The
   spec says "every 30 min". Either bolt a new bucket onto
   `SchedulerService` (touch surface: app.py, scheduler_service.py,
   scheduler_registry.py — historically fragile per #3820) or register
   under `_minutely` and gate inside the task. The latter is safer.
   **Risk:** adding a `_half_hourly` bucket repeats the
   off-by-an-hour bug class.

6. **EventTypes additions require migration.** Per
   `event_types.py:13-22` docstring: *"Each event type is represented
   by a field on the subscriber repository, therefore any changes made
   here must also be reflected in the database (and likely requires a
   database migration)."* PR #7015 (`e52a887e`, 2026-03-26) is the
   recent precedent showing this is **a real migration with column
   adds**, not just an enum addition. Case-5 ships at least one
   alembic file for the event type + one for the preference columns +
   one for `is_pantry_staple` — three migrations minimum.

7. **Lifespan-based scheduler start.** `app.py:54-69` registers the
   scheduler in the FastAPI lifespan. Mealie has had two regressions
   here: `1af0f426` (2024-03-14, `fix: remove deprecated lifecycle and
   consolidate startup actions` #3311) and `2e9026f9` (2021-10-07,
   `feat(frontend): Fix scheduler …` #725). Tests must **import the
   task function** and never trigger app lifecycle — otherwise the
   scheduler genuinely starts and tests become flaky.

8. **No `freezegun` / time-machine dependency.** Adding one for case-5
   is justifiable for the 30-min window test, but it'll be the first
   such use — flag for design review (do they want to introduce that
   dep, or stick with the existing real-clock construction style?).

---

## Cross-perspective questions (from history's angle)

H1. **Should `is_pantry_staple` be per-household (M2M) instead of a
    global Food bool?** Commit `e9892aba` (#4616) is the canonical
    precedent that moved "on hand" *off* Food for exactly this reason.
    If the spec stays as-is, we knowingly recreate a deprecated
    pattern. Worth flagging to the spec author.

H2. **Is `auto_sync_run_time` parsed at the global settings level or
    per-household?** The only existing time-of-day parser is the
    `DAILY_SCHEDULE_TIME_UTC` property in `settings.py:187-210` — it
    converts a single global string. Per-household requires a similar
    helper that takes a `tz`. Should we lift the existing helper to a
    shared utility, or copy/inline it? History favors copy/inline
    (Mealie tends not to extract until 3+ call sites exist).

H3. **Migration count / ordering.** Case-5 ships three migrations
    (preference columns, Food flag, EventTypes columns). Should they
    be one combined migration or three sequenced ones? PR #4158 used
    a single migration for multiple preference columns; PR #7015 had
    its own dedicated migration. **Recommendation from history:** one
    migration per concern, ordered by dependency. Reviewers tend to
    request splits.

H4. **What does "consolidate_ingredients" mean here?** The spec says
    "复用 mealie 既有 `consolidate_ingredients`". Grep across `mealie/`
    shows no function by that exact name. The closest is
    `ShoppingListService.bulk_create_items` (`shopping_lists.py:154`)
    which calls `can_merge` (L45) and `merge_items` (L73). The
    spec author may be referring to a case-3 deliverable that doesn't
    exist on disk yet. **Flag for spec:** confirm name and signature.

H5. **Worker concurrency: `SELECT … FOR UPDATE SKIP LOCKED` on
    SQLite?** The project supports both SQLite and Postgres
    (`task py:postgres`). SQLite doesn't support `FOR UPDATE SKIP
    LOCKED`. Either: case-5 declares it Postgres-only for the locking
    behavior (degrading SQLite to non-concurrent execution), or it
    uses an application-level CAS via `UPDATE … WHERE LastAutoSyncedAt
    < :today`. History favors the latter (commit `9e77a9f3` — sqlalchemy 2.0
    migration — was careful to keep SQLite working).

H6. **Where does the new task get registered in `app.py`?** Existing
    `register_minutely` (`app.py:134-136`) only has `post_group_webhooks`.
    Adding `auto_sync_meal_plan_to_shopping` here makes the
    `_minutely` bucket more eclectic. Acceptable, but reviewers
    consistently ask for justification — be ready to defend "every
    5 min wakes up to check the 30-min window".
