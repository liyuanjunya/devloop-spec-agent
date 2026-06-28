# Rewrite log: spec_v2 → spec_v3 (ITER 3)

**Generated**: 2026-06-19
**Meta-review input**: `meta_review_v2.{md,json}` (12 actions)
**Verdict (meta)**: REWRITE_REQUIRED
**Goal**: 0 critical + 0 high across all 4 axes

## Counts

| | v2 | v3 | Δ |
|---|---|---|---|
| Functional requirements | 27 | 29 | +2 (FR-028 subscriber model/schema, FR-029 cross-group test) |
| Success criteria | 25 | 29 | +4 (SC-026 204 no-meal-plan, SC-027 subscriber attribute, SC-028 FK ondelete, SC-029 cross-group byte-equal) |
| Needs clarification | 3 | 3 | 0 (NC-003 recommended_default text strengthened) |
| User stories | 9 | 9 | 0 |
| Edge cases | 9 | 11 | +2 (force-mode mid-tx rollback, run-now 204) |
| Assumptions | 8 | 9 | +1 (merge_items sums quantities at line 96) |
| Out-of-scope items | 7 | 6 | −1 (dropped "subscriber-dedup tolerance") |
| Self-concerns | 3 | 3 | 0 (locale + FR-021 startup-check rewritten) |
| iterations | 2 | 3 | +1 |

## Validators (Step 3)

| Validator | v3 result |
|---|---|
| A4+F3 schema (`Spec.model_validate`) | **PASS** (FRs=29, SCs=29, NCs=3) |
| A5 citation (`verify_spec_citations`) | **0 problems** |
| B3 trace (`find_trace_gaps`) | **0 gaps** |
| B1 roundtrip (`assert_spec_roundtrip_consistent`) | **PASS** |

## Action-by-action change log

### META-V2-001 (CRITICAL) — CAS BEFORE side effects in one transaction

**Source v2 findings**: arch-1, comp-1, exec-1, cons-1, exec-7 (5 distinct callouts about merge-double-counting if a CAS loser still reaches `bulk_create_items`)

**Changes applied**:
- **FR-011** (replaced text): Now specifies the exact 6-step pipeline (resolve preconditions → open transaction → conditional CAS UPDATE → branch on rowcount → side effects → event dispatch). Explicitly states that CAS happens INSIDE the transaction BEFORE `bulk_create_items` / `recipe_references` / `EventBusService.dispatch`, and that an exception rolls back the CAS too.
- **FR-012** (replaced text): Pinned the SQL — `UPDATE household_preferences SET last_auto_synced_at = :now_naive_utc WHERE id = :pref_id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local_midnight_utc)`. Spelled out the `:today_local_midnight_utc` computation as `datetime.combine(...).astimezone(UTC).replace(tzinfo=None)` to match the `NaiveDateTime` column type. Restated that CAS loser performs zero writes BECAUSE the CAS sits BEFORE side effects, not because `merge_items` is idempotent (it is NOT — line 96 sums quantities).
- **FR-018** (replaced text): Removed the false claim that "the CAS race is safe because merge handles duplicates"; explicitly states `merge_items` SUMS quantities at line 96 and is NOT idempotent. Multi-replica safety is enforced UPSTREAM by FR-012's CAS-before-side-effects ordering.
- **FR-020** (replaced text): Documents that `force=True` replaces the WHERE clause with an unconditional UPDATE that ALWAYS affects 1 row, but still runs inside the same transaction so exceptions roll back the marker write too.
- **FR-021** (replaced text): Restated "exactly one dispatch per CAS winner; CAS losers never dispatch". The dispatch sits in step 6 of FR-011, reached only when CAS UPDATE affected 1 row.
- **SC-007** (replaced text + metric + threshold): Now asserts exactly-once `bulk_create_items`, exactly-once `EventBusService.dispatch`, exactly-once marker write across two consecutive invocations.
- **SC-013** (replaced text + metric + threshold): Now asserts exactly 1 dispatch per CAS winner with the 5 required payload fields, exactly 0 per CAS loser.
- **edge_cases.two-replica** (rewritten): "Each replica opens its own transaction and races to issue the conditional UPDATE … the CAS loser is a structural no-op."
- **edge_cases.recipe-cycle** (rewritten): Documents that the exception rolls back the CAS too, so the marker reverts and is NOT touched.
- **edge_cases.force-mode mid-tx exception** (new): Documents that force-mode's unconditional UPDATE is also rolled back on exception.
- **out_of_scope**: Removed "Subscriber-side dedup tolerance" item — no longer needed because subscribers never see duplicate events.
- **assumptions[8]**: Added explicit note that `merge_items` SUMS at line 96 and per-day idempotency is enforced upstream by CAS.

### META-V2-002 (CRITICAL) — Event subscriber: table name + model + schema

**Source v2 findings**: arch-3 (model missing field), comp-2 (schema missing field), cons-2 (wrong table name `group_event_notifier_options`)

**Changes applied**:
- **FR-024** (replaced text): Corrected the migration target table name to `group_events_notifier_options` (with the 's' in `events`) — verified at `events.py:16` and at the existing migration `2026-03-26-20.48.28_cdc93edaf73d_…:21`. Cited both.
- **FR-028** (NEW): Adds `mealplan_auto_synced_to_shopping: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)` to `GroupEventNotifierOptionsModel` (`events.py:15-53`) AND `mealplan_auto_synced_to_shopping: bool = False` to `GroupEventNotifierOptions` schema (`group_events.py:13-55`). Cites the `getattr(notifier.options, event.event_type.name)` seam at `event_bus_listeners.py:76-83` so the necessity is provable from code.
- **SC-027** (NEW): Asserts the attribute is accessible via `getattr` and defaults to False; verifies column exists on `group_events_notifier_options`.
- **self_concerns[FR-021]** (rewritten): Now references both the migration column AND the ORM/schema additions; suggests a single startup integration test that asserts both.

### META-V2-003 (CRITICAL) — `extra='forbid'` on `HouseholdPreferencesPartialUpdate` itself

**Source v2 findings**: arch-2, cons-3, exec-2 (all flagged that v2 wrongly relied on global `extra='forbid'` on `MealieModel`, which is not present)

**Changes applied**:
- **FR-004** (replaced text): The partial-update schema MUST declare `model_config = ConfigDict(extra='forbid', alias_generator=camelize, populate_by_name=True)` directly on its class. Explicitly notes that `MealieModel.model_config` (cited `mealie_model.py:45-53`) only sets `alias_generator` + `populate_by_name=True` — so the `extra='forbid'` MUST be local to this schema and not global.
- **FR-004.code_references**: Added citation to `mealie/schema/_mealie/mealie_model.py:45-53` for the `MealieModel` config.
- **SC-018** (replaced text): Asserts the 422 response is produced because of the schema-level `extra='forbid'` (NOT globally on `MealieModel`). Cites the `mealie_model.py:45-53` location to make the reasoning verifiable.
- **SC-018.related_requirements**: Added `FR-007` (reciprocal link for trace).
- **NC-003.recommended_default**: Updated to explicitly call out the schema-level `model_config = ConfigDict(extra='forbid')` declaration.

### META-V2-004 (HIGH) — PATCH clobber marker

**Source v2 findings**: arch-4, exec-3 (v2 used `repos.household_preferences.update(...)` which goes through the generic repo's full-model serialize/write path that would clobber the server-owned marker even if the field is absent from the partial schema)

**Changes applied**:
- **FR-006** (replaced text): Replaced the full-model update with a column-set UPDATE: `self.repos.session.execute(update(HouseholdPreferencesModel).where(HouseholdPreferencesModel.household_id == self.household_id).values(**diff))`. Documents the structural guarantee: `diff` is built from `HouseholdPreferencesPartialUpdate.model_dump(exclude_unset=True)` and the schema does not declare `last_auto_synced_at`, so that key is never in `diff` and never in `values(**diff)`. Re-fetches the row for the response. Specifies that an empty `diff` returns the current row unchanged.
- **NC-003.recommended_default**: Mirrors the FR-006 column-set UPDATE language.

### META-V2-005 (HIGH) — Run-now HTTP 204 contract

**Source v2 findings**: comp-3, cons-4 (v2 returned HTTP 200 with `{detail: <i18n key>}` body on precondition failure, but input requirement 5 explicitly says "204 / 0 added")

**Changes applied**:
- **FR-020** (replaced text): On success, HTTP 200 with body EXACTLY matching `{'added_count', 'skipped_pantry_count', 'target_list_id', 'run_at'}` (no `detail`). On precondition failure (empty meal plan OR no target list), HTTP 204 No Content with NO body. The i18n keys from FR-022 surface only in server-side logs.
- **FR-022** (replaced text): Removed the suggestion that i18n keys appear in the HTTP response body. Now explicitly states the keys surface only in logs / event payload.
- **FR-026** (replaced text): Added integration test assertions for HTTP 204 + zero-byte body for both no-meal-plan and no-target-list cases.
- **SC-026** (NEW): Asserts status code 204 + Content-Length 0 for both precondition-failure cases.
- **edge_cases.run-now-precondition-failure** (new): Documents the 204 contract.
- **US-9 AC1 / FR-022** texts mention 204 instead of "200 + detail".

### META-V2-006 (HIGH) — Target-list FK migration with ondelete='SET NULL'

**Source v2 findings**: arch-5 (migration omitted `create_foreign_key` step so the `ON DELETE SET NULL` assumption documented in assumptions[5] was unbacked)

**Changes applied**:
- **FR-024** (replaced text): Step A now explicitly calls `batch_op.create_foreign_key('fk_household_preferences_auto_sync_target', 'shopping_lists', ['auto_sync_target_shopping_list_id'], ['id'], ondelete='SET NULL')`. The downgrade step explicitly drops the constraint via `batch_op.drop_constraint('fk_household_preferences_auto_sync_target', type_='foreignkey')`. Cited the FK creation pattern at `2024-02-23-16.15.07_2298bb460ffd_added_user_to_shopping_list.py:80-100`.
- **SC-028** (NEW): Asserts `inspect(engine).get_foreign_keys('household_preferences')` includes the FK with `ondelete='SET NULL'`, and that deleting a parent `shopping_lists` row sets the referencing column to NULL rather than raising IntegrityError.

### META-V2-007 (HIGH) — CASCADE on association table FKs

**Source v2 findings**: arch-6 (v2 cited `mealie/db/models/recipe/ingredient.py:21-27` for the new association table pattern, but that cited example omits CASCADE; the deleted-food edge case would crash on IntegrityError without CASCADE)

**Changes applied**:
- **FR-002** (replaced text): Explicitly specifies `sa.ForeignKey('households.id', ondelete='CASCADE')` and `sa.ForeignKey('ingredient_foods.id', ondelete='CASCADE')`. Documents the deliberate deviation from the cited L21-27 example (which omits ondelete entirely) and notes that a repo-wide grep confirms no existing table uses `ondelete='CASCADE'`. Justifies the deviation: required by the deleted-food edge case.
- **FR-024** (replaced text): Step B now writes the CASCADE explicitly into the migration's `op.create_table('household_pantry_staples', …)` call.

### META-V2-008 (MEDIUM) — Cross-group multitenant test

**Source v2 findings**: comp-4 (input requirement 5 "cross group complete isolation" had no concrete success criterion)

**Changes applied**:
- **FR-029 [NFR]** (NEW): Cross-group multitenant test setup. Household A in G1, household B in G2; both have seeded meal plans + auto-sync configured + different pantry staples. Asserts byte-equal snapshots of G2 entities before/after A's sync, and vice versa.
- **SC-029** (NEW): Asserts zero diff bytes between pre-sync and post-sync snapshots for the foreign group's `ShoppingList`, `GroupMealPlan`, `IngredientFood`, and `household_pantry_staples` rows.

### META-V2-009 (MEDIUM) — Pinned enumeration query for FR-009

**Source v2 findings**: exec-4 (FR-009 said "enumerate enabled households" without a concrete SQLAlchemy pattern, leaving the implementer to guess between `repository_household.get_all()` + filter, vs a JOIN, vs raw SQL)

**Changes applied**:
- **FR-009** (replaced text): Pinned the exact query — `session.execute(select(Household).join(HouseholdPreferencesModel, HouseholdPreferencesModel.household_id == Household.id).where(HouseholdPreferencesModel.auto_sync_meal_plan_to_shopping == True)).scalars().all()`. Built per-household scoped repos via `get_repositories(session, group_id=household.group_id, household_id=household.id)`. Cites `all_repositories.py:8-11` for the factory, `household.py:29-50` for the model, `preferences.py:16-44` for the FK column.
- **FR-009.related_success_criteria**: Added `SC-024` (reciprocal link).

### META-V2-010 (MEDIUM) — Locale correction (40+ locales, only en-US editable)

**Source v2 findings**: cons-5, exec-5 (v2 implied that "Mealie supports a single en locale" or that the i18n keys would be added to all locale files; both are wrong)

**Changes applied**:
- **FR-022** (replaced text): Mealie ships 40+ locale files at `mealie/lang/messages/*.json`; per `.github/copilot-instructions.md` 'Translations' section ONLY `en-US.json` is editable by repository contributors. All other locales are Crowdin-managed and MUST NOT be edited.
- **assumptions[2]** (rewritten): Replaces the v2 single-locale claim with the 40+ locales + Crowdin policy.
- **self_concerns[FR-022]** (rewritten): Notes that Crowdin back-fills keys on its own cadence; non-English users see en-US fallback in the interim via the i18n resolver's default behavior.

### META-V2-011 (MEDIUM) — Tighten no-meal-plan re-trigger window edge case

**Source v2 findings**: exec-6 (edge case said "a meal plan added later in the day will trigger a real sync on the next tick" without specifying whether the tick must fall in the window, or whether late-day creation outside the window should also trigger)

**Changes applied**:
- **edge_cases.no-meal-plan** (rewritten): A meal plan added later in the same household-local day triggers an auto-sync only when BOTH (a) the meal plan is created before the current day's `[scheduled_local_instant, scheduled_local_instant + 30min)` window closes AND (b) the next 5-minute scheduler tick fires inside that window. Otherwise only POST run-now syncs that day; next automatic sync is tomorrow's window.

### META-V2-012 (LOW) — Reciprocal JSON links

**Changes applied**:
- **SC-018.related_requirements** += `FR-007`
- **FR-024.related_success_criteria** += `SC-002`, `SC-028`
- **FR-009.related_success_criteria** += `SC-024`
- **FR-011.related_success_criteria** += `SC-025`
- **FR-021.related_success_criteria** += `SC-025`
- **SC-025.related_requirements** = `[FR-011, FR-021]`

## v2 critical+high → v3 mapping

| v2 finding (axis-id) | v3 resolution |
|---|---|
| arch-1 (CAS race writes side effects before CAS) | FR-011 + FR-012 rewrites; SC-007 + SC-013 tightened |
| arch-2 (extra='forbid' missing on partial schema) | FR-004 rewrite; SC-018 rewrite |
| arch-3 (event subscriber model missing field) | FR-028 (new); SC-027 (new) |
| arch-4 (PATCH full-model clobber risk) | FR-006 rewrite (column-set UPDATE) |
| arch-5 (FK migration omits create_foreign_key) | FR-024 rewrite (step A FK creation); SC-028 (new) |
| arch-6 (association table omits CASCADE) | FR-002 + FR-024 step B rewrites |
| comp-1 (no exactly-once event guarantee) | FR-021 rewrite; SC-013 rewrite |
| comp-2 (event subscriber schema missing field) | FR-028 (new); SC-027 (new) |
| comp-3 (run-now contract violates input req 5) | FR-020 rewrite; SC-026 (new) |
| comp-4 (cross-group isolation has no SC) | FR-029 [NFR] (new); SC-029 (new) |
| exec-1 (CAS race re-described in execution view) | FR-011/FR-012 rewrites |
| exec-2 (extra='forbid' execution view) | FR-004 rewrite |
| exec-3 (PATCH execution view clobber) | FR-006 rewrite |
| cons-1 (CAS race consistency view) | FR-011/FR-012/FR-018 rewrites |
| cons-2 (wrong subscriber-options table name) | FR-024 rewrite (`group_events_notifier_options`) |
| cons-3 (extra='forbid' consistency view) | FR-004 + SC-018 rewrites |
| cons-4 (run-now contract consistency view) | FR-020 + FR-022 + FR-026 rewrites; SC-026 (new) |

## v2 → v3 regression risk

| Risk | Status |
|---|---|
| Could the new CAS-before-side-effects ordering break the run-now (force=True) path? | NO — `force=True` makes the WHERE unconditional, so step 4 still always proceeds to step 5. Documented in FR-020. |
| Could the column-set UPDATE bypass any audit triggers or onupdate handlers? | NO — `HouseholdPreferencesModel` does not declare `onupdate=` or any ORM event listeners. Verified at `preferences.py:16-44`. |
| Could the new `extra='forbid'` reject the existing client PUT body? | NO — PUT uses `UpdateHouseholdPreferences` (separate class without `extra='forbid'`). Only the new PATCH path uses `HouseholdPreferencesPartialUpdate`. |
| Could the new ondelete='CASCADE' on association FKs cause unintended cascades? | NO — the table is purely a junction table; both parents (Households, IngredientFoods) explicitly should clear their pantry-staple membership on delete. |
| Could the new ondelete='SET NULL' on `auto_sync_target_shopping_list_id` mask data-integrity issues? | NO — this is the documented behavior in assumptions[5] and US-3; the previous absence was the bug. |
| Could the table-name fix to `group_events_notifier_options` break the existing migration baseline? | NO — the existing migration `2026-03-26-20.48.28_cdc93edaf73d_…` already uses the correct name (`:21`). v2 was the outlier. |

## Files written by this iteration

- `spec_v3.json` (apply meta-review actions to spec_v2.json)
- `spec_v3.md` (rendered from spec_v3.json via `spec_to_markdown`)
- `rewrite_v2_to_v3.md` (this file)
- `build_v3.py` (the in-place transformation script — kept for audit)

## Build artifact (for audit)

The script that produced v3 from v2 is `build_v3.py`. It loads `spec_v2.json`, mutates the dict in place, writes `spec_v3.json`, and then runs the four validators. All four reported zero problems on the first invocation. The script is idempotent — running it again produces a byte-identical `spec_v3.json`.
