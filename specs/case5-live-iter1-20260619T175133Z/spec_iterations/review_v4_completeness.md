# Completeness Review (v4)

## Verdict: NEEDS_REFINE

Spec v4 resolves the v3 response-body contradiction for run-now no-meal-plan: the HTTP contract is now consistently 204 No Content with zero body bytes. However, the rewrite introduced a new normative contradiction about whether no-op/error i18n keys are delivered to event-bus subscribers. Several requirements say `message_key` is set on no-meal-plan / no-target-list / already-synced paths and subscribers can read it from the outbox-dispatched event, while the same spec also requires those same paths to insert zero `event_outbox` rows and dispatch zero events. Because a code agent cannot satisfy both, v4 still has a high-severity completeness issue.

## Critical issues

None.

## High issues

### COMP-H-014 — No-op/error `message_key` event delivery contradicts zero-outbox no-op semantics

- Location: `input.md:57-58`, `input.md:70`; `spec_v4.md:155-167`, `spec_v4.md:203`, `spec_v4.md:230`, `spec_v4.md:233`, `spec_v4.md:236`, `spec_v4.md:317-320`, `spec_v4.md:363-373`.
- Evidence: US-9 and FR-022 say localized i18n keys surface in both server logs and `EventMealPlanAutoSyncedData.message_key` for downstream subscribers. FR-020 says precondition-failure 204 clients read the key from event subscription or logs. FR-021 says `message_key` is set on no-meal-plan / no-target-list / already-synced paths. But FR-011 step 2 returns before CAS/outbox on empty meal plan or no target; US-9 AC1/AC2, SC-025, SC-026, and edge cases require zero `event_outbox` rows and zero dispatches for these paths; US-9 AC3 and SC-013 require CAS losers / already-synced paths to insert zero outbox rows.
- Impact: Implementers must choose between emitting no-op/error events (violating zero-outbox success criteria and idempotency semantics) or not emitting them (violating FR-021/FR-022/US-9 subscriber-facing `message_key` promises). This leaves the i18n/event-bus contract under-specified and contradictory.
- Required fix: Choose one contract. Recommended: keep zero-outbox no-op semantics and revise US-9/FR-020/FR-021/FR-022 to say no-meal-plan, no-target-list, and already-synced keys are log-only; `message_key` is reserved for future emitted warning events or remains `None` on the single success event. Alternatively, explicitly emit dedicated no-op outbox events and update FR-011, SC-013, SC-025, US-9 ACs, and edge cases to allow those rows/dispatches without breaking idempotency.

## Medium issues

None beyond the high issue above.

## v3 issue resolution table

| v3 issue | v3 severity | v4 status | Evidence | Completeness assessment |
|---|---:|---|---|---|
| COMP-H-013: No-meal-plan run-now contract contradicted by US-9 response-body text | High | ⚠️ Partially resolved | `spec_v4.md:157-165`, `spec_v4.md:230`, `spec_v4.md:319-320` | The stale response-body requirement is fixed: 204 + zero bytes is now consistent. But the replacement subscriber/message_key wording introduces COMP-H-014. |

## Requirement coverage delta

| Input requirement area | v4 completeness verdict |
|---|---|
| Household preference fields, storage, PATCH/PUT/read schemas | Covered |
| Scheduler window, timezone, target-list fallback | Covered |
| Multi-replica idempotency / once-per-day processing | Covered |
| Ingredient aggregation, pantry filtering, append/merge | Covered |
| Manual run-now route, auth, success response | Covered for HTTP shape; no-op i18n event/log contract conflicts |
| Event bus and i18n keys | Not fully covered due contradictory no-op/error `message_key` delivery semantics |
| Unit/integration/multitenant tests | Covered, except tests encode both zero-outbox and subscriber-visible keys for no-op paths |

## Summary

Refine v4 before coding. The v3 HTTP 204/no-body issue is fixed, but the spec still has 0 critical and 1 high issue: no-op/error i18n keys cannot be both subscriber-visible via `event_outbox` and accompanied by zero outbox rows / zero dispatches.
