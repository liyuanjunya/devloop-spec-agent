# Approach Candidates — Case 5

Three candidates evaluated for the case-5 auto-sync vertical (meal plan → shopping list). Each is a complete, shippable design. The selected primary is documented in `selected.md`.

## Candidate A — Conservative (spec-literal, single-worker pragmatic)

### Description
Implement the spec verbatim with the smallest possible deviation from existing patterns. Treat the documented single-worker scheduler caveat as an accepted limitation; use a per-household `last_auto_synced_at` column with a simple read-check-write pattern (not full CAS). Pantry-staple lives as a column on `IngredientFoodModel` (group-scoped). Defer the per-household timezone field to a follow-up — fall back to `tzlocal()` like `create_timeline_events.py` does today.

### Code references reused
- `mealie/services/scheduler/scheduler_registry.py:41-43` — `register_minutely`
- `mealie/services/scheduler/tasks/create_timeline_events.py:25-134` — group/household walk template
- `mealie/repos/repository_meals.py:11-21` — `get_today`
- `mealie/services/household_services/shopping_lists.py:413-455` — `add_recipe_ingredients_to_list`
- `mealie/services/event_bus_service/event_bus_service.py:66-96` — `dispatch`
- `mealie/db/models/_model_utils/datetime.py:20-50` — `NaiveDateTime`

### New code added
- `mealie/services/scheduler/tasks/auto_sync_shopping.py` — new file, ~150 LOC
- 4 columns added to `HouseholdPreferencesModel` (no `timezone` field)
- 1 column added to `IngredientFoodModel` (group-scoped `is_pantry_staple`)
- 1 new `EventTypes` enum value + 1 new `EventDocumentDataBase` subclass
- 1 alembic migration (preferences + foods + group_events_notifier_options)
- 2 new routes on `HouseholdSelfServiceController` (PATCH + run-now)
- 3 i18n keys in `en-US.json`
- ~7 unit tests + 4 integration tests + 2 multitenant tests

### Risks
- **R1**: relies on `tzlocal()` (server tz) for "today" boundary — fails the spec's "must use household-configured timezone" requirement.
- **R2**: `is_pantry_staple` as a group-scoped column may collide with the spec's "cross-household pantry-staple marks do not interfere" multitenant test if implementers expect per-household semantics.
- **R3**: read-check-write last_auto_synced_at is racy under multi-replica deployments (two workers can both observe `last_auto_synced_at < today` and both proceed).
- **R4**: no PATCH endpoint — clients must PUT the full preferences body to toggle one flag.

### Test cost
- ~13 tests (unit/integration/multitenant combined)
- No `freezegun`-based timezone test (because no timezone field)
- Skip `FOR UPDATE SKIP LOCKED` coverage

### Effort qualitative estimate
Smallest scope. ~10-12 files, fits the spec's "~12-18 个文件" lower bound.

---

## Candidate B — Defensive (spec-literal + multi-replica + per-household tz)

### Description
Implement spec literally, but harden the multi-replica safety and timezone story. Add `HouseholdPreferencesModel.timezone` (nullable IANA string, fallback UTC). `last_auto_synced_at` is updated via a conditional UPDATE (`UPDATE ... WHERE last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local`) — atomic at the DB level, works on both SQLite and PostgreSQL, no need for `FOR UPDATE SKIP LOCKED`. Pantry-staple stays group-scoped per the spec wording (with a top-of-spec `BlockingDecision` recording the per-household alternative for reviewer rejection). PATCH endpoint added alongside PUT.

### Code references reused
All from Candidate A, plus:
- `mealie/db/models/household/preferences.py:16-44` — `HouseholdPreferencesModel` (add 5 columns, not 4)
- `mealie/db/models/household/household.py:43-49` — `preferences` cascade relationship guarantees exactly one prefs row per household
- `mealie/routes/_base/checks.py:23-26` — `can_manage_household` for both new routes
- `mealie/routes/_base/base_controllers.py:132-172` — `BaseUserController` for the new run-now controller

### New code added
- All of Candidate A, plus:
- `HouseholdPreferencesModel.timezone: str | None` (IANA name)
- CAS update on `last_auto_synced_at` (conditional UPDATE; deterministic across SQLite + PostgreSQL)
- New PATCH `/api/households/preferences` accepting partial body (`exclude_unset` semantics) — old PUT preserved for backward compat
- 1 BlockingDecision (NC) about pantry-staple scope (so reviewer can flip to per-household if needed)
- ZoneInfo-based timezone resolution helper (`get_household_tz(prefs) -> ZoneInfo`)
- ~3 additional tests (freezegun timezone boundary, idempotency CAS under concurrent calls, PATCH partial body)

### Risks
- **R1 (mitigated)**: per-household timezone field included; spec requirement satisfied.
- **R2 (escalated)**: pantry-staple scope decision surfaced as NC-001; default is group-scoped; reviewer can flip to per-household.
- **R3 (mitigated)**: conditional UPDATE provides DB-level atomicity even without row-level locking.
- **R4 (mitigated)**: PATCH alongside PUT.
- **R5 (new)**: more files touched (~14-16) so PR review cost increases moderately.

### Test cost
- ~16 tests (13 from Candidate A + 3 new)
- Adds `freezegun`-based timezone boundary tests (uses already-installed `freezegun==1.5.5`)
- Adds an idempotency-under-concurrent-call test (calls task 2× consecutively, asserts second call is a no-op)

### Effort qualitative estimate
Medium. ~14-16 files, within the spec's "~12-18 个文件" mid-range.

---

## Candidate C — Comprehensive (multi-replica row lock + per-household pantry-staple + new scheduler bucket)

### Description
Address every cross-perspective concern in one pass. Add a true 30-minute scheduler bucket (`MINUTES_30 = 30`, `register_half_hourly`). Move `is_pantry_staple` to a per-household `households_to_pantry_staple_foods` association table (mirroring the PR #4616 `households_to_ingredient_foods` correction). Use `SELECT ... FOR UPDATE SKIP LOCKED` for multi-replica row locking on PostgreSQL, fall back to conditional UPDATE on SQLite. Add a new `controller_auto_sync_shopping.py` to keep concerns separated. Surface every architectural choice (scheduler bucket, pantry-staple scope, multi-replica strategy) as either NC or self-concern.

### Code references reused
All from Candidate B, plus:
- `mealie/db/models/recipe/ingredient.py:20-27` — `households_to_ingredient_foods` association table pattern
- `mealie/services/scheduler/runner.py:19-83` — `repeat_every` decorator (for the new MINUTES_30 wrapper)

### New code added
- All of Candidate B, plus:
- `MINUTES_30 = 30` constant + `run_half_hourly` async wrapper + `SchedulerRegistry._half_hourly` list + `register_half_hourly` method
- `households_to_pantry_staple_foods` association table + `IngredientFoodModel.households_with_pantry_staple` relationship + repository methods
- Dialect-aware locking: `select(HouseholdPreferencesModel).filter(...).with_for_update(skip_locked=True)` on PostgreSQL; conditional UPDATE fallback on SQLite
- New `controller_auto_sync_shopping.py` under `mealie/routes/households/` for the run-now endpoint
- ~5 additional tests (per-household pantry-staple scope, 30-min bucket invocation, SKIP LOCKED concurrency on PostgreSQL via `task py:postgres`)

### Risks
- **R1**: changing `SchedulerService` adds blast radius — every existing scheduled task is at risk of regression.
- **R2**: PostgreSQL-only locking path needs a CI configuration that doesn't exist (`task py:test` runs SQLite by default).
- **R3**: per-household pantry-staple breaks the spec wording ("global on foods table") — requires reviewer / user buy-in.
- **R4**: ~18-22 files touched, exceeds the spec's "~12-18 个文件" upper bound; PR review cost is highest.
- **R5**: re-running `task dev:generate` is mandatory to regenerate TypeScript types for the new association table.

### Test cost
- ~21 tests (16 from Candidate B + 5 new)
- Adds PostgreSQL-only concurrency test (gated by `MEALIE_TEST_DB=postgres` env var)
- Adds an end-to-end test for the new 30-min scheduler bucket
- Adds a multitenant test verifying per-household pantry-staple isolation

### Effort qualitative estimate
Largest. ~18-22 files, exceeds the spec's expected range. Highest correctness ceiling, highest review cost.

---

## Comparison summary

| Dimension | A (Conservative) | B (Defensive) | C (Comprehensive) |
|---|---|---|---|
| Multi-replica safety | ❌ racy | ✅ conditional UPDATE | ✅ SKIP LOCKED + fallback |
| Household timezone | ❌ host-tz | ✅ field + UTC fallback | ✅ field + UTC fallback |
| Pantry-staple scope | group | group (with NC) | per-household |
| PATCH endpoint | ❌ | ✅ | ✅ |
| 30-min scheduler bucket | gated on minutely | gated on minutely | new MINUTES_30 |
| Files touched | ~10-12 | ~14-16 | ~18-22 |
| Test count | ~13 | ~16 | ~21 |
| Spec alignment | exact | exact + hardening | exceeds (per-hh pantry) |
| Reviewer ergonomics | low | high (NC surfaces decision) | low (overreach risk) |

---

## Selection rationale (preview)

See `selected.md` for the final pick. The chosen candidate must satisfy two hard input requirements that A cannot meet: **multi-replica safety** (R3 in A) and **household-timezone awareness** (R1 in A). Both B and C satisfy these. C overreaches by changing the scheduler and the pantry-staple scope, exceeding the spec's file-count bound and breaking the spec's "global on foods table" wording without explicit user buy-in. **B (Defensive) is selected**.
