# Meta-Review v2 — Case-5 LIVE RUN

**Judge:** claude-opus-4.7 (meta + rewriter, iter 3)
**Inputs:** `review_v2_{architecture,completeness,executability,consistency}.md`, `spec_v2.md`, `spec_v2.json`, `meta_review_v1.{md,json}`, `rewrite_v1_to_v2.md`, `input.md`, Mealie source at `C:\Users\v-liyuanjun\Downloads\mealie\`.

## Verdict

v2 spec **CONVERGENCE FAILED — REWRITE REQUIRED**. Across four axes there are **6 deduped critical+high actions** that block coding (3 critical / 3 high), plus 4 medium and 1 low polish items. Strong cross-axis convergence: the single most cited root cause (CAS-after-side-effects, raised by ARCH/COMP/CONS/EXEC simultaneously) accounts for 6 of the 7 critical-or-high reviewer findings. All other v1 issues stayed resolved between v1→v2; no regressions detected. With M-CAS reordered, M-EVT-SUB landed, M-PATCH-SAFE applied, and M-RUN-NOW-SHAPE reconciled, v3 should reach 0 critical + 0 high.

## Recommended fix order

1. **META-V2-001** (CAS BEFORE side effects in one transaction) — unblocks META-V2-005 (run-now force semantics) and resolves 6 critical/high findings in one architectural change
2. **META-V2-002** (event subscriber: correct table name + model + schema) — independent, blocks dispatch correctness
3. **META-V2-003** (`extra='forbid'` on `HouseholdPreferencesPartialUpdate` only) — independent
4. **META-V2-004** (PATCH applies diff via column-set UPDATE, never full-model write that includes marker)
5. **META-V2-005** (run-now response: HTTP 204 on no-meal-plan; 4-key shape on success only)
6. **META-V2-006** (target-list FK in migration with `ondelete='SET NULL'`) + add SC verifying FK + delete action
7. **META-V2-007** (FR-002 association table explicitly declares `ondelete='CASCADE'`; deviates from cited L21-27 which omits it)
8. then P3/P4 (cross-group test, enumeration query, locale correction, edge case window, reciprocal links)

## Actions

| ID | Pri | Sev | Axes | Sources | Action |
|---|---|---|---|---|---|
| META-V2-001 | 1 | critical | arch, comp, cons, exec | NEW-ARCH-C-1, COMP-C-010, C2-001, C2-002, EXEC-C-001, EXEC-C-002 | Re-order FR-011/FR-012: (1) resolve preconditions + load target/mealplan; (2) open transaction; (3) issue conditional UPDATE on `last_auto_synced_at` — if 0 rows, COMMIT empty txn and return without side effects or event; (4) if 1 row, build items + call `bulk_create_items` + update `recipe_references` + flush; (5) dispatch event via after-commit hook (or directly inside txn followed by commit); (6) on any exception, rollback (which reverses the CAS too). Force-mode replaces step 3 with an unconditional UPDATE. Update SC-007/SC-013/SC-017/SC-025; update US-2 AC2; rewrite the two-replica edge case; remove out-of-scope item about subscriber dedup tolerance. |
| META-V2-002 | 1 | critical | arch, exec | NEW-ARCH-H-1, EXEC-C-004 | Fix FR-024 table name from `group_event_notifier_options` → `group_events_notifier_options` (real table per `mealie/db/models/household/events.py:16`). Add a NEW FR-028: also add `mealplan_auto_synced_to_shopping: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)` to `GroupEventNotifierOptionsModel` (`events.py:15-53`) AND `mealplan_auto_synced_to_shopping: bool = False` to `GroupEventNotifierOptions` schema (`group_events.py:13-55`). `AppriseEventListener.get_subscribers` resolves the subscription bool via `getattr(notifier.options, event.event_type.name)` (`event_bus_listeners.py:76-83`), so missing schema/model fields silently disable subscribers. |
| META-V2-003 | 1 | critical | arch, exec | NEW-ARCH-M-1, EXEC-C-003 | Update FR-004 + SC-018: `HouseholdPreferencesPartialUpdate` MUST set `model_config = ConfigDict(extra='forbid')` on the schema class itself. `MealieModel.model_config` only sets `alias_generator` + `populate_by_name` (`mealie_model.py:53`); no global forbid exists. SC-018 prose must cite the schema-level forbid, not a non-existent global. |
| META-V2-004 | 2 | high | arch | NEW-ARCH-H-2 | Rewrite FR-006 step 5: replace `self.repos.household_preferences.update(self.household_id, current)` with a column-set UPDATE that only writes `diff` keys via SQLAlchemy `session.execute(update(HouseholdPreferencesModel).where(...).values(**diff))`. This guarantees the server-owned `last_auto_synced_at` is never overwritten by a PATCH, even if the route somehow loaded a stale `ReadHouseholdPreferences` object containing the field. Return value: re-fetch the row via `self.repos.household_preferences.get_one(self.household_id, 'household_id')` and serialize via `ReadHouseholdPreferences.model_validate(...)`. |
| META-V2-005 | 2 | high | arch, comp, cons, exec | NEW-ARCH-M-2, COMP-H-011, C2-003, EXEC-H-002 | Reconcile run-now response: success returns HTTP 200 with EXACTLY `{added_count, skipped_pantry_count, target_list_id, run_at}` per SC-012. Precondition-fail (no meal plan today OR no resolvable target list) returns HTTP 204 No Content with no body (matching input requirement `input.md:67-71`). The i18n key (FR-022) surfaces only in server-side logs and event payloads, NOT in the response body. Update FR-020, SC-012, US-9 AC1, FR-022, and the edge cases that mention `detail` field. Add an integration SC for the HTTP 204 path. |
| META-V2-006 | 2 | high | cons, exec | C2-004, EXEC-H-001 | Update FR-024 step A to also call `batch_op.create_foreign_key('fk_household_preferences_auto_sync_target', 'shopping_lists', ['auto_sync_target_shopping_list_id'], ['id'], ondelete='SET NULL')` (per the `create_foreign_key` pattern at `mealie/alembic/versions/2024-02-23-16.15.07_2298bb460ffd_added_user_to_shopping_list.py:86`). Add a new SC-026: after `alembic upgrade`, `inspect(engine).get_foreign_keys('household_preferences')` includes one FK on `auto_sync_target_shopping_list_id` → `shopping_lists.id` with `ondelete='SET NULL'`. |
| META-V2-007 | 2 | high | exec | EXEC wrong citation #1 (FR-002/edge case) | Update FR-002 to explicitly state `sa.ForeignKey('households.id', ondelete='CASCADE')` and `sa.ForeignKey('ingredient_foods.id', ondelete='CASCADE')` on the new association table. Document that the parallel `households_to_ingredient_foods` (cited at `ingredient.py:21-27`) does NOT use CASCADE and that this new table intentionally deviates to support the deleted-food edge case. No existing Mealie table uses `ondelete='CASCADE'` (verified by grep of `mealie/`), so the deviation must be explicit. Alternatively, the deleted-food edge case must switch to application-level cleanup. |
| META-V2-008 | 3 | medium | comp | COMP-M-012 | Add a multitenant SC + test for cross-group isolation: create household A in group G1 and household B in group G2; configure auto-sync for both; trigger task for both; assert A cannot read or write G2's meal plans, foods, shopping lists, or pantry-staple rows, and vice versa. Add as a new FR-029 [NFR] mirroring FR-027's structure but for cross-group rather than cross-household-same-group. |
| META-V2-009 | 3 | medium | exec | EXEC-M-001 | Pin FR-009 per-household enumeration query: `session.execute(select(HouseholdModel).join(HouseholdPreferencesModel, HouseholdPreferencesModel.household_id == HouseholdModel.id).where(HouseholdPreferencesModel.auto_sync_meal_plan_to_shopping == True)).scalars().all()`. Per household, build `repos = get_repositories(session, group_id=household.group_id, household_id=household.id)` to scope all downstream operations. |
| META-V2-010 | 3 | medium | exec | EXEC-M-002 + EXEC wrong citation #4 | Correct FR-022 + Assumption #3 + Self-Concern #3: Mealie ships MANY locale files (`mealie/lang/messages/*.json` — confirmed: af-ZA, ar-SA, bg-BG, …, en-US, en-GB, fr-FR, zh-CN, etc.). The actionable convention per `.github/copilot-instructions.md` "Translations" section is: ONLY modify `en-US.json`; other locales are Crowdin-managed and MUST NOT be edited. Update the spec text to reflect this convention rather than the false claim that en-US is the only locale. |
| META-V2-011 | 3 | medium | cons | C2-005 | Tighten the no-meal-plan edge case: a meal plan added later in the same household-local day triggers a real sync only if (a) it is added before the current day's `[scheduled_local_instant, scheduled_local_instant + 30min)` window closes, AND (b) the next scheduler tick fires inside that window. If the meal plan arrives after the window closes, only `POST /auto-sync-shopping/run-now` syncs that day; the next automatic sync is the next day's window. |
| META-V2-012 | 4 | low | cons | C2-006 | Make these FR↔SC links reciprocal in `spec_v3.json`: (a) SC-018 must list FR-007 in `related_requirements`; (b) FR-024 must list SC-002 in `related_success_criteria`; (c) FR-009 must list SC-024; (d) FR-011 + FR-021 must each list SC-025. |

## Cross-axis conflicts

| # | Type | Where | Resolution |
|---|---|---|---|
| 1 | Substantive convergence | 4 axes flag CAS-after-side-effects as the single dominant blocker | **Merged in META-V2-001:** the chosen design (CAS BEFORE side effects, within one transaction; force-mode replaces CAS with unconditional UPDATE) is recommended by COMP, CONS, and EXEC reviewers in identical words. ARCH suggests "separate claim/lease/status row" as an alternative; single-transaction CAS is sufficient and simpler. |
| 2 | Latent | ARCH says "use a separate in-progress claim or row-level lock" vs COMP/CONS/EXEC say "single conditional UPDATE inside same txn" | **Resolved in META-V2-001:** single-transaction CAS is sufficient. Postgres + SQLite both support transactional UPDATE that other readers won't see until commit, and the CAS WHERE clause `(last_auto_synced_at IS NULL OR last_auto_synced_at < :today_midnight_utc)` is the lease. Rolled-back transactions automatically rollback the CAS so a failed mid-sync leaves the marker untouched. The "in-progress claim row" approach is over-engineered for a per-household-per-day claim. |
| 3 | Latent | EXEC wrong citation #1 says FR-002 needs `ondelete='CASCADE'` to match the cited model, vs the model L21-27 omits CASCADE | **Resolved in META-V2-007:** the new association table intentionally deviates from `households_to_ingredient_foods`. The cited line range justifies the column shape and uniqueness constraint; the CASCADE addition is a deliberate enhancement documented in FR-002 text, NOT a claim that the existing table uses CASCADE. |
| 4 | Latent | C2-003 says response shape conflicts with localized `detail` field for failures (HIGH) vs COMP-H-011 says input requires HTTP 204 on no-meal-plan (HIGH) | **Merged in META-V2-005:** the input wins. HTTP 204 on no-meal-plan / no-target-list (no body, no `detail` needed). HTTP 200 with the exact 4-key shape on success. Drops the `detail` field entirely from the response contract. |
| 5 | None substantive | — | All four axes converge on the same critical defects. No reviewer-vs-reviewer disagreement on whether to fix anything. |

## Severity rollup vs reviewer claims

| Reviewer | Reviewer-claimed counts | Folded into meta priority |
|---|---|---|
| Architecture | 1 critical + 2 high + 2 medium | All 1 critical → P1 (META-V2-001). Both high → P1+P2 (META-V2-002 + META-V2-004). 1 medium → P1 (META-V2-003: shared with EXEC critical so promoted). 1 medium → P2 (META-V2-005: shared with COMP/CONS/EXEC high so promoted). |
| Completeness | 1 critical + 1 high + 1 medium | Critical → P1 (META-V2-001). High → P2 (META-V2-005). Medium → P3 (META-V2-008). |
| Executability | 4 critical + 3 high + 2 medium | Critical 1+2 → P1 (META-V2-001). Critical 3 → P1 (META-V2-003). Critical 4 → P1 (META-V2-002). 3 high → P2 (META-V2-006, -005, -001-followup). 2 medium → P3 (META-V2-009, -010). Wrong-citation block (#1 cascade, #2 table name, #3 race safety, #4 locale) → distributed across META-V2-007/002/001/010. |
| Consistency | 2 blocking + 2 high + 1 medium + 1 low | Both blocking → P1 (META-V2-001). 2 high → P2 (META-V2-005, -006). 1 medium → P3 (META-V2-011). 1 low → P4 (META-V2-012). |

## V1→V2 regression check (already validated by A1; cross-confirmed here)

| v1 META action | v2 disposition | Regression risk |
|---|---|---|
| META-001 (per-household pantry) | Resolved (FR-002/FR-016/FR-025/FR-027) | None — design held. v3 reinforces with explicit CASCADE in FR-002 (META-V2-007). |
| META-002 (CAS ordering) | Partially resolved (marker after side effects rather than before) | **Yes — this is the v2 critical that triggers META-V2-001.** v3 fully resolves. |
| META-003 (auto_sync_run_time + cadence) | Resolved (FR-001/FR-009) | None. |
| META-004 (target-list ownership) | Resolved (FR-006/FR-014) | None. v3 reinforces with FR migration (META-V2-006). |
| META-005 (unconditional pantry filter) | Resolved (FR-015/FR-016) | None. |
| META-006 (new event type + payload) | Resolved (FR-021) BUT subscriber registration in FR-024 has wrong table name and missing model/schema. | **Partial — see META-V2-002.** |
| META-007 (run-now route + force + shape) | Resolved (FR-020) BUT response shape conflicts with localized `detail` field. | **Partial — see META-V2-005.** |
| META-008 (marker server-only) | Resolved (FR-003/FR-004/FR-005/FR-007/SC-018) BUT FR-006 step 5 may clobber marker via full-model write. | **Partial — see META-V2-004.** |
| META-009 (exact i18n keys) | Resolved (FR-022/SC-019) | None. |
| META-010 (consolidate_ingredients reuse) | Resolved (FR-017/SC-010) | None. |
| META-011 (test matrix) | Resolved (FR-026/FR-027) BUT cross-group bullet missing. | **Partial — see META-V2-008.** |
| META-012/-013/-014/-015/-016/-017/-018 | Resolved | None. |

## Summary

Four axes converge tightly on a single dominant architectural defect — **CAS happens AFTER non-idempotent shopping-list side effects** — that accounts for 6 of 7 critical+high findings. v2 reorganized the CAS to fire after the work transaction commits and added explicit tolerance for duplicate events in the two-replica edge case; this contradicts US-2 AC2, SC-007, SC-013, SC-017, SC-025 simultaneously because `merge_items` sums quantities (`shopping_lists.py:96`), not absorbs duplicates. The fix is to issue the conditional UPDATE BEFORE side effects inside a single transaction so a CAS-loser performs zero writes and dispatches no event.

The other 3 critical+high blockers are independent and each has a one-paragraph fix: (a) correct the event subscriber table name and add the missing ORM/schema fields, (b) move `extra='forbid'` to the partial schema and update SC-018's prose, (c) make PATCH apply a column-set UPDATE so the server-owned marker is structurally protected from full-model writeback, (d) reconcile the run-now response: HTTP 204 with no body for no-meal-plan, HTTP 200 with the exact 4-key shape on success, no `detail` field ever.

Apply META-V2-001 through META-V2-007 to clear all critical+high. Apply META-V2-008 through META-V2-012 in the same pass for polish + traceability. Bump metadata.iterations to 3.
