# Selected Approach — Case 5

**Selected: Candidate B — Defensive**

## Selection summary
- **Selected candidate**: B (Defensive)
- **Eliminated**: A (Conservative) — does not satisfy multi-replica safety nor per-household timezone, both of which are hard requirements per the input.
- **Eliminated**: C (Comprehensive) — overreaches by (a) modifying `SchedulerService` with a new `MINUTES_30` bucket, increasing blast radius across unrelated scheduled tasks; (b) moving `is_pantry_staple` to a per-household association table, contradicting the spec's literal wording "global on foods table"; (c) exceeding the spec's estimated file count (~12-18) without commensurate user-stated value.

## Why Defensive over Conservative
The input file (`input.md`) explicitly enumerates two hard non-functional requirements:

1. **"幂等 + 多副本安全"** — idempotency + multi-replica safety. Conservative's read-check-write on `last_auto_synced_at` is racy under multi-worker / multi-replica deployments. Defensive's conditional UPDATE (`WHERE last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local`) provides DB-level atomicity that works on both SQLite and PostgreSQL without dialect-specific code.
2. **"按 household 的时区计算 today"** — compute "today" in the household's timezone, not the server's. Conservative falls back to `tzlocal()` (current `create_timeline_events.py` behavior); Defensive adds `HouseholdPreferencesModel.timezone: str | None` with `ZoneInfo` resolution and explicit UTC fallback.

## Why Defensive over Comprehensive
- **Spec wording fidelity**: input.md describes `Food.is_pantry_staple` as a `Boolean` column on the `foods` table. Comprehensive's per-household association table is a more correct design (mirrors PR #4616's `households_to_ingredient_foods` correction) but breaks the spec's literal wording. Defensive surfaces this as a `BlockingDecision` (NC-001) so a reviewer can flip to per-household without re-implementing.
- **Scheduler blast radius**: Comprehensive's new `MINUTES_30` bucket would touch `SchedulerService.run_minutely / run_hourly / run_daily` siblings and require regression-testing every existing scheduled task. Defensive registers on the existing `register_minutely` bucket and gates inside the task with a 30-minute window — zero blast radius on the scheduler core.
- **Estimated file count**: input.md projects "~12-18 files". Defensive lands at ~14-16; Comprehensive at ~18-22. Staying within the projected range reduces review friction.
- **CI coverage**: Comprehensive's `SELECT ... FOR UPDATE SKIP LOCKED` only fires on PostgreSQL, but `task py:test` uses SQLite by default — the new code path would ship un-exercised in default CI.

## Defensive design — concrete commitments
The selected approach commits to the following concrete decisions (every one of these is reflected in `spec.json` either as a functional requirement or as a `BlockingDecision` for reviewer escalation):

| # | Decision | Rationale |
|---|---|---|
| D1 | `HouseholdPreferencesModel` gains 5 columns: `auto_sync_meal_plan_to_shopping_list: bool`, `auto_sync_target_shopping_list_id: UUID \| None`, `auto_sync_pantry_filter_enabled: bool`, `last_auto_synced_at: NaiveDateTime \| None`, `timezone: str \| None` | Single migration; preserves prefs cascade on Household. |
| D2 | `IngredientFoodModel` gains 1 column: `is_pantry_staple: bool` (server_default `false`) | Spec-literal; surfaced via NC-001 if per-household needed. |
| D3 | Scheduler: `register_minutely(sync_meal_plan_to_shopping_lists)` + internal 30-minute window check | Reuses existing bucket; zero blast radius. |
| D4 | Per-household timezone resolution: `ZoneInfo(prefs.timezone) if prefs.timezone else ZoneInfo("UTC")` — explicitly NOT `tzlocal()` | Deterministic across replicas; UTC fallback is documented in spec. |
| D5 | Idempotency: conditional UPDATE — `UPDATE household_preferences SET last_auto_synced_at = :now WHERE id = :id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local_midnight)` returning row count | DB-level CAS; works on SQLite + PostgreSQL; no dialect branching. |
| D6 | Both PATCH and PUT on `/api/households/preferences` | PATCH for partial updates; PUT preserved for backward compat. |
| D7 | Run-now endpoint: `POST /api/households/preferences/auto-sync/run-now` on `HouseholdSelfServiceController`, gated by `can_manage_household` | Reuses existing controller + check. |
| D8 | Pantry filter: `if prefs.auto_sync_pantry_filter_enabled and food.is_pantry_staple: skip` evaluated per-ingredient inside the recipe walk | Pure read; no new DB write path. |
| D9 | Reuse `add_recipe_ingredients_to_list` (shopping_lists.py:413-455) so existing `consolidate_ingredients` + label/checked merge semantics are inherited | Avoids duplicating merge logic. |
| D10 | New `EventTypes.shopping_list_updated` enum value + new `EventShoppingListAutoSyncData` subclass + dispatch via `EventBusService.dispatch` | Reuses existing notification pipeline. |
| D11 | 3 new i18n keys in `en-US.json` under `mealplan.auto_sync.*`: `success`, `no_active_meal_plan`, `target_shopping_list_not_found` | Matches the en-US-only convention from `copilot-instructions.md`. |
| D12 | Multitenant scoping: every query joins on `household_id` (preferences) or `group_id` (foods) — no cross-household writes possible because `RepositoryMeals.get_today` requires `household_id` (raises ValueError at preferences.py:14 today) | Inherits existing scoping; tests assert no leakage. |

## Reason this matches the input
- **Multi-replica safety** ✅ via D5 (DB-level conditional UPDATE).
- **Household-tz awareness** ✅ via D1 (timezone column) + D4 (ZoneInfo resolution).
- **Idempotency** ✅ via D5 + the 30-min window window check (D3 inner gate).
- **PATCH semantics** ✅ via D6 (exclude_unset on partial body).
- **Pantry filter optional** ✅ via D8 (gated by `auto_sync_pantry_filter_enabled`).
- **Event dispatch** ✅ via D10.
- **i18n** ✅ via D11.
- **Multitenant** ✅ via D12.
- **Spec wording fidelity** ✅ via D2 (group-scoped) + NC-001 (per-household alternative escalated, not silently chosen).

## What the spec.json will encode
- **8 user stories** covering: household-admin enables auto-sync, scheduler runs task, on-demand run-now, pantry filter, event subscriber notification, multitenant isolation, admin marks food as pantry-staple, household timezone configuration.
- **18+ functional requirements** mapped 1:1 to D1-D12 plus error-handling and tests.
- **10+ success criteria** with bidirectional FR↔SC `related_*` links.
- **7+ edge cases**: no plan today, no target list configured, midnight tz boundary, recipe with `food_id=None`, deleted target list, checked existing item, multi-replica concurrent invocation.
- **3 needs_clarification BlockingDecisions**:
  - NC-001 pantry-staple scope (group column vs per-household association)
  - NC-002 default target list resolution when null (first active main list — ordered how?)
  - NC-003 PATCH semantics (partial via `exclude_unset` is chosen — but should PUT remain as full-replace?)
- **3+ self_concerns** about: scheduler accuracy ±5 min under load, `freezegun` integration test reliability around DST transitions, conditional UPDATE behaviour on SQLite in WAL mode under high concurrency.
