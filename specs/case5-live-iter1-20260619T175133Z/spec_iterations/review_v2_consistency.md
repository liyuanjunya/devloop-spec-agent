# Consistency Review v2 — Case-5 LIVE RUN

**Reviewer:** Consistency Reviewer  
**Inputs:** `spec_v2.md`, `spec_v2.json`, `review_v1_consistency.md`, `rewrite_v1_to_v2.md`  
**Verdict:** **REVISE** — v2 fixes many v1 contradictions, but the new CAS placement still conflicts with daily idempotency, duplicate-event guarantees, and the exact run-now response contract.

## Summary

The rewrite successfully resolves the v1 field-name, pantry-scope, target-ownership, i18n-key, and writable-marker issues. However, the v2 spec now places the conditional idempotency update after committed shopping-list mutations and event dispatch. That means normal same-day reruns and replica races can still mutate quantities and emit events before discovering the marker was already set, contradicting US-2, SC-007, SC-013, and the summary's one-sync-per-day intent.

## Findings

### C2-001 — Conditional UPDATE after side effects does not enforce daily idempotency
**Severity:** Blocking  
**Scope:** Summary ↔ FR ↔ US ↔ SC contradiction

- The summary says idempotency is enforced by a conditional UPDATE after `bulk_create_items`, recipe-reference updates, and event dispatch commit.
- FR-011 steps 4-6 perform shopping-list writes and event dispatch first, then update `last_auto_synced_at` only after commit.
- FR-012 explicitly says that if the UPDATE affects 0 rows, the duplicate-add side effect has already been applied and is acceptable.
- US-2 AC2 requires a second same-day task fire to add no items, dispatch no event, and not bump the marker.
- SC-007 requires the second invocation to create 0 new item rows and only one marker write across both invocations.

**Issue:** The CAS is no longer a guard; it is only a post-facto marker write. A non-concurrent second invocation on the same day will still run `bulk_create_items` before learning the marker was already set. Even if no duplicate row is inserted, quantity can be merged again, so the shopping list is mutated twice.

**Recommendation:** Keep the v2 precondition ordering, but move the conditional UPDATE before shopping-list mutation/event dispatch and inside the same transaction: resolve target + non-empty meal plan first; attempt CAS; if 0 rows, return before writes/events; if 1 row, write items, dispatch after commit or via an after-commit hook.

### C2-002 — Duplicate event edge case contradicts exactly-once event criteria
**Severity:** Blocking  
**Scope:** FR ↔ SC ↔ Edge cases

- FR-021 says exactly one dispatch per successful sync and zero dispatches on short-circuit.
- SC-013 requires `EventBusService.dispatch` exactly once for a successful run.
- US-2 AC2 requires no event on a second same-day run.
- The two-replica edge case says both replicas execute FR-011 steps 1-5, the loser dispatches a duplicate event, and subscribers must tolerate it.
- Out of scope excludes subscriber-side dedup.

**Issue:** The spec simultaneously promises exactly-once dispatch and at-least-once duplicate dispatch. Because dedup is out of scope, implementation cannot satisfy both.

**Recommendation:** Make CAS decide the single winner before event dispatch. If at-least-once event delivery is truly intended, downgrade SC-013/US-2 wording and define the dedup key in scope.

### C2-003 — Run-now response shape conflicts with localized `detail`
**Severity:** High  
**Scope:** FR ↔ US ↔ SC contradiction

- US-3 and SC-012 require the run-now response keys to be exactly `{'added_count', 'skipped_pantry_count', 'target_list_id', 'run_at'}`.
- FR-020 first repeats that exact shape, but then says precondition failures return HTTP 200 with those fields **and** surface the i18n key in a `detail` field.
- US-9 requires run-now with no active meal plan to return the localized key `auto-sync.no-meal-plan-today`.

**Issue:** A precondition-failure response cannot both have the exact four-key shape and include `detail`.

**Recommendation:** Either add `detail: str | None` to the canonical response schema and update SC-012, or make precondition failures use a different documented error/warning envelope and scope SC-012 to successful syncs only.

### C2-004 — Target-list foreign key behavior is specified but absent from migration requirements
**Severity:** High  
**Scope:** FR ↔ Assumption ↔ SC gap

- FR-001 defines `auto_sync_target_shopping_list_id` as a foreign key to `shopping_lists.id` with `ON DELETE SET NULL`.
- Assumption #6 relies on hard deletes setting the field to null via that FK.
- FR-024's migration adds the GUID column but does not require creating the FK constraint or `ON DELETE SET NULL` action.
- SC-002 checks only column presence/types/defaults, not FK constraints.

**Issue:** The implementation can satisfy FR-024 and SC-002 while violating FR-001 and Assumption #6.

**Recommendation:** Amend FR-024 to create/drop the FK constraint explicitly and add a success criterion that inspects the foreign key and delete action.

### C2-005 — “Meal plan added later same day will trigger” overstates the scheduler window
**Severity:** Medium  
**Scope:** Edge case ↔ FR contradiction

- FR-009 permits scheduled execution only inside `[auto_sync_run_time, auto_sync_run_time + 30 minutes)`.
- The no-meal-plan edge case says leaving the marker untouched means a meal plan added later the same day “will trigger a real sync once the next scheduler tick falls inside the FR-009 window.”

**Issue:** If the meal plan is added after the 30-minute window closes, no later scheduler tick falls inside the window. Only run-now can sync that day.

**Recommendation:** Qualify the edge case: automatic retry occurs only while the current day's window remains open; after the window closes, the admin must use run-now or wait until the next configured window.

### C2-006 — JSON FR↔SC links still have reciprocal mismatches
**Severity:** Low  
**Scope:** spec.json relationship consistency

The following JSON relationship links are one-way only:

- FR-007 → SC-018, but SC-018 does not list FR-007.
- SC-002 → FR-024, but FR-024 does not list SC-002.
- SC-024 → FR-009, but FR-009 does not list SC-024.
- SC-025 → FR-011 and FR-021, but FR-011/FR-021 do not list SC-025.

**Recommendation:** Make `related_success_criteria` and `related_requirements` reciprocal, or document that only one direction is authoritative.

## v1 finding status

| v1 finding | v2 status |
|---|---|
| C-001 daily threshold conflict | Mostly fixed by local-day boundary + window gating; blocked by C2-001 CAS placement. |
| C-002 CAS ordering/no-op marker | No-op marker update fixed; side-effect-before-CAS introduced C2-001. |
| C-003 run-now daily gate | Fixed via `force=True`; response schema conflict remains C2-003. |
| C-004 pantry filter seam | Fixed via explicit filtered `recipe_ingredients=`. |
| C-005 client-writable marker | Fixed; PATCH/PUT exclude marker and SC-018 tests rejection. |
| C-006 target ownership | Fixed at PATCH-time and sync-time. |
| C-007 i18n drift | Mostly fixed to `auto-sync.*`; response-envelope conflict remains C2-003. |
| C-008 pantry scope | Fixed with association table default, still correctly blocked by NC-001. |
| C-009 reciprocal links | Improved but not fully fixed; see C2-006. |

## Self-concerns vs FRs / ACs

- FR-021 self-concern about old database schema aligns with FR-024, but there is no success criterion for startup failure or migration-before-serve behavior. This is acceptable as a self-concern, not a contradiction.
- FR-009 ZoneInfo cost concern does not weaken any hard AC.
- FR-022 locale concern aligns with Assumption #3 and Out of Scope.

## Edge cases vs FRs / ACs

- The two-replica edge case conflicts with exact event and idempotency criteria (C2-001/C2-002).
- The no-meal-plan retry edge case overstates behavior after the 30-minute scheduler window closes (C2-005).
- Deleted target, invalid timezone, recipe cycle, pantry cascade, zero-list, and auth-bypass edge cases are otherwise aligned with the FRs.

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata | `spec.md` has a rendered title/header/footer; `spec.json` has structured `metadata`, counts, and model/tool fields. | Expected representation difference. |
| Needs clarification | Same NC-001..NC-003 titles and semantics. JSON has `related_requirements` arrays. | No material mismatch found. |
| User stories | Same 9 user stories and acceptance content. Markdown headings use `US-1` style; JSON ids match. | No material mismatch found. |
| Functional requirements | Same 27 FRs in order. JSON additionally carries `requirement_type`, `testable`, `related_success_criteria`, and structured code references. | Relationship mismatches exist only in JSON metadata; see C2-006. |
| Success criteria | Same 25 SCs in order and prose. JSON additionally carries metrics, thresholds, and `related_requirements`. | No prose mismatch found; relationship mismatches remain. |
| Key entities / edge cases / assumptions / out of scope / self-concerns | Same semantics, with JSON split into structured objects. | Behavioral issues are shared by both representations. |

## US ↔ FR.related_user_stories check

Every user story is represented in the FR relationship graph, and no dangling user-story IDs were found in `spec.json`. Semantic contradictions remain for US-2/US-5 because FR-011/FR-012 permit side effects and duplicate dispatch before the CAS result is known.

## FR ↔ SC bidirectional check

All FRs have at least one SC and all SCs have at least one FR. Reciprocal-link mismatches remain as listed in C2-006.

## Recommended resolution order

1. Move the CAS guard before shopping-list writes and event dispatch, while preserving v2's precondition/no-op marker behavior.
2. Reconcile event semantics: exactly once per CAS winner, or explicit at-least-once with in-scope dedup.
3. Normalize the run-now response schema including localized warnings.
4. Add the missing FK migration/test requirement.
5. Clean up reciprocal JSON links and qualify the no-meal-plan edge case.
