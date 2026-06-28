# Completeness Review (v2)

## Verdict: NEEDS_REFINE

Spec v2 resolves most v1 completeness gaps: the required preference fields and PATCH route are restored, pantry filtering is unconditional and household-scoped, the run-now route is corrected, a new event type/payload is specified, exact i18n keys are present, and merge/reference/admin-route coverage is much stronger. However, the multi-replica idempotency ordering is now internally contradictory and can duplicate quantities/events before the CAS marker is written. The test matrix also still misses explicit cross-group isolation and the input's no-meal-plan integration status/shape.

## Critical issues

### COMP-C-010 — CAS marker is written after side effects, so multi-replica runs can double-add items and dispatch duplicate events

- Location: `input.md:36-37`, `input.md:81-83`; `spec_v2.md:8`, `spec_v2.md:192-196`, `spec_v2.md:222`, `spec_v2.md:258-259`, `spec_v2.md:323-326`, `spec_v2.md:351-352`.
- Evidence: The input requires the same household to sync at most once per day and explicitly calls for DB locking or `LastAutoSyncedAt` CAS so only one worker processes a household per day. Spec v2 says the event is dispatched once per successful sync (`spec_v2.md:222`) and SC-007 expects zero new item rows on the second invocation (`spec_v2.md:258-259`). But FR-011/FR-012 put `bulk_create_items` and event dispatch before the conditional marker UPDATE (`spec_v2.md:192-196`). The edge case admits two replicas execute steps 1-5 and the loser can merge into the row written by the winner and emit a duplicate event (`spec_v2.md:323-326`, `spec_v2.md:351-352`). Merging duplicate `(food_id, unit_id)` rows by summing quantity is not idempotency; it doubles the requested quantity.
- Impact: A code agent following v2 can violate a hard input requirement under multi-replica deployment, while the success criteria still claim once-per-day behavior.
- Required fix: Move the CAS/claim before shopping-list mutation and event dispatch, within the same transaction or by a claim marker/lock that prevents losers from executing side effects. If the marker must be written only after success, use a separate in-progress claim or row-level lock (`SELECT ... FOR UPDATE SKIP LOCKED`) before side effects. Event dispatch must occur only for the winning worker after the transaction succeeds.

## High issues

### COMP-H-011 — Required no-meal-plan integration behavior is not specified with the input status/shape

- Location: `input.md:67-71`; `spec_v2.md:151-156`, `spec_v2.md:219`, `spec_v2.md:237-240`, `spec_v2.md:278-279`, `spec_v2.md:294-295`.
- Evidence: The input requires an integration case where no meal plan today returns `204 / 0 added`. Spec v2's run-now behavior instead returns HTTP 200 with the four count fields plus an extra `detail` field when no meal plan exists (`spec_v2.md:219`), while SC-012's exact four-key response check covers only success (`spec_v2.md:268-269`). FR-026 lists unit empty-meal-plan behavior but does not require an integration assertion for the no-meal-plan endpoint status/body (`spec_v2.md:237-240`).
- Impact: Implementers may produce an API response that fails the requested integration contract and may not test the no-meal-plan endpoint path at integration level.
- Required fix: Decide and specify the no-meal-plan endpoint contract as either HTTP 204 or HTTP 200 with the exact `{added_count, skipped_pantry_count, target_list_id, run_at}` result shape. If localized detail is required, add it in a way that does not contradict the exact response-shape tests, and add an explicit integration success criterion.

## Medium issues

### COMP-M-012 — Cross-group isolation test from the input is still not explicit

- Location: `input.md:72-75`; `spec_v2.md:108-119`, `spec_v2.md:228-230`, `spec_v2.md:237-242`, `spec_v2.md:256-257`, `spec_v2.md:272-277`.
- Evidence: Spec v2 covers same-group cross-household target rejection and pantry-staple isolation. It also says repositories are household-scoped. But the input separately requires “cross group complete isolation,” and FR-026/FR-027/SC-006/SC-015/SC-016 only assert two households in the same group or sibling household cases.
- Impact: A required multitenant test bullet can be omitted, leaving group-boundary regressions uncovered.
- Suggested fix: Add an explicit multitenant test with households in different groups proving auto-sync cannot read, target, or write the other group's shopping list/meal plan/pantry rows.

## v1 issue resolution table

| v1 issue | v1 severity | v2 status | Evidence | Completeness assessment |
|---|---:|---|---|---|
| C1: required household preference fields incomplete/renamed | Critical | ✅ Resolved | `spec_v2.md:162-180`, `spec_v2.md:246-249` | Correct field name, `auto_sync_run_time`, PATCH/PUT/read schemas, defaults, validation, and migration are now specified. |
| C2: scheduler cadence/window mismatch | Critical | ✅ Resolved with repo-supported equivalent | `spec_v2.md:183-188`, `spec_v2.md:250-253`, `spec_v2.md:292-293` | 5-minute bucket plus explicit 30-minute household-local window is complete enough, though idempotency ordering is a new blocker under COMP-C-010. |
| C3: pantry filter optional | Critical | ✅ Resolved | `spec_v2.md:162`, `spec_v2.md:207-209` | Pantry filtering is unconditional and has no extra preference flag. |
| C4: `consolidate_ingredients` reuse not addressed | Critical | ✅ Resolved | `spec_v2.md:204-218`, `spec_v2.md:342` | v2 documents the missing symbol and pins the verified `bulk_create_items` seam with merge tests. |
| C5: run-now route/response/bypass wrong | Critical | ⚠️ Mostly resolved | `spec_v2.md:76-81`, `spec_v2.md:219-220`, `spec_v2.md:268-291` | Correct route, auth, force bypass, marker update, and success response are specified; no-meal-plan status/body remains ambiguous in COMP-H-011. |
| C6: new event type/payload missing | Critical | ⚠️ Partially resolved | `spec_v2.md:221-224`, `spec_v2.md:270-271`, `spec_v2.md:323-326` | Event type and safe payload are present, but the CAS-after-side-effects race can dispatch duplicates. |
| C7: i18n keys mismatch | Critical | ✅ Resolved | `spec_v2.md:225-227`, `spec_v2.md:282-283` | Exact requested keys and namespace are specified. |
| C8: pantry-staple multitenant isolation contradicted | Critical | ✅ Resolved | `spec_v2.md:12-20`, `spec_v2.md:165-167`, `spec_v2.md:240-242` | v2 uses `household_pantry_staples` and tests same-group household independence. |
| C9: required test matrix incomplete | Critical | ⚠️ Partially resolved | `spec_v2.md:237-242`, `spec_v2.md:246-295` | Most bullets are now present, but explicit cross-group isolation and no-meal-plan integration status/body remain missing. |
| M1: recipe references may not link meal-plan entries | Major | ✅ Resolved by documented scope | `spec_v2.md:216-218`, `spec_v2.md:351` | v2 documents current recipe-only refs and makes meal-plan-entry ids out of scope. |
| M2: unchecked accumulation test missing | Major | ✅ Resolved | `spec_v2.md:210-215`, `spec_v2.md:264-265` | Merge into existing unchecked `(food_id, unit_id)` rows is explicit and testable. |
| M3: Food admin route/repo support under-specified | Major | ✅ Resolved by per-household route model | `spec_v2.md:165-167`, `spec_v2.md:231-235`, `spec_v2.md:286-287` | v2 intentionally replaces group-scoped Food field mutation with admin pantry-staple association routes and tests permission. |

## Requirement coverage delta

| Input requirement area | v2 completeness verdict |
|---|---|
| Household preference fields, storage, PATCH/PUT/read schemas | Covered |
| Scheduler window, timezone, target-list fallback | Covered |
| Multi-replica idempotency / once-per-day processing | Not covered; CAS order permits duplicate side effects |
| Ingredient aggregation, pantry filtering, append/merge | Covered, subject to CAS race fix |
| Manual run-now route, auth, success response | Mostly covered; no-meal-plan contract needs refinement |
| Event bus and i18n keys | Covered in schema, but event exactly-once conflicts with CAS race |
| Unit/integration/multitenant tests | Mostly covered; add cross-group and no-meal-plan integration assertions |

## Summary

Refine v2 before coding. The most important fix is to make the idempotency claim happen before shopping-list mutation and event dispatch so a losing replica cannot double quantities or emit duplicate events. Then tighten the no-meal-plan endpoint contract and add an explicit cross-group isolation test.
