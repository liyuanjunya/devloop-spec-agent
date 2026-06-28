# Consistency Review v4 — Case-5 LIVE RUN ITER 4

**Reviewer:** Consistency Reviewer v4  
**Inputs:** `spec_v4.md`, `spec_v4.json`, `review_v3_consistency.md`, `rewrite_v3_to_v4.md`  
**Verdict:** **REVISE** — v4 resolves the v3 direct transaction/after-commit contradiction, but still has high-severity contradictions around no-op localization events and outbox dispatcher exactly-once delivery. Approval requires 0 critical + 0 high.

## Summary

v4 materially improves the architecture by adding FR-030 commit suppression and FR-031 transactional outbox. The CAS/items/outbox database atomicity contract is now internally coherent for the auto-sync writer transaction.

However, two high issues remain. First, the spec says no-op/error i18n keys are available to downstream subscribers through `EventMealPlanAutoSyncedData.message_key`, while the same no-op paths explicitly insert zero outbox rows and dispatch zero events. Second, the dispatcher claims exactly one normal delivery per outbox row, but its poll/dispatch/update sequence allows duplicate external dispatches when two scheduler replicas poll the same undispatched row.

## Findings

### C4-001 — No-op `message_key` is promised to subscribers, but no no-op event is ever enqueued
**Severity:** High  
**Scope:** US ↔ FR ↔ SC ↔ Edge-case contradiction

- US-9 says i18n keys surface in both server-side logs and downstream event-bus subscribers through `EventMealPlanAutoSyncedData.message_key` (`spec_v4.md:155-167`).
- FR-020 says precondition-failure i18n keys appear in `EventMealPlanAutoSyncedData.message_key` on the eventual outbox-dispatched event (`spec_v4.md:230`).
- FR-021 says `message_key` is set on no-meal-plan / no-target-list / already-synced paths (`spec_v4.md:233`).
- But FR-011 step 2 returns before CAS/outbox insert for no target or empty meal plan, and step 4 returns before outbox insert for CAS losers (`spec_v4.md:203`).
- US-9 AC1, SC-025, and the no-meal/no-target edge case require zero `event_outbox` rows / zero dispatches for those same paths (`spec_v4.md:165`, `spec_v4.json:1982-1991`, `spec_v4.md:373`).

**Issue:** The event payload field exists, but every path that would set a non-`None` i18n key is specified as dispatching no event. Downstream subscribers therefore cannot observe the no-op keys as promised.

**Recommendation:** Choose one contract. Either make no-op/error keys logs-only and revise US-9 / FR-020 / FR-021 / FR-022 / Key Entities accordingly, or enqueue explicit no-op outbox rows for selected no-op paths and revise SC-025 / US-9 AC1 / CAS-loser semantics.

### C4-002 — Outbox dispatcher exactly-once claim is not consistent with its multi-replica algorithm
**Severity:** High  
**Scope:** FR ↔ SC ↔ Edge-case contradiction

- FR-031 polls rows with `dispatched_at IS NULL`, calls `EventBusService.dispatch(...)`, then sets `dispatched_at` and commits (`spec_v4.md:263`).
- FR-021 and SC-013 claim exactly one dispatch per CAS winner under normal operation (`spec_v4.md:233`, `spec_v4.json:1852-1860`).
- The two-replica edge case says subscribers receive exactly one event because the dispatcher marks `dispatched_at` atomically before the row is re-eligible (`spec_v4.md:365`).

**Issue:** The row is not claimed before external dispatch. Two app replicas running `dispatch_event_outbox()` can both select the same `dispatched_at IS NULL` row, both call external dispatch, and only then race to set `dispatched_at`. That violates the normal-operation exactly-once dispatch claim.

**Recommendation:** Add an atomic claim mechanism (`SELECT ... FOR UPDATE SKIP LOCKED`, a `claimed_at/claimed_by` field, or a conditional UPDATE claim before dispatch), or downgrade the contract to at-least-once even during normal dispatcher races and update SC-013 / FR-031 / edge cases.

### C4-003 — Retry idempotency key is unstable/underspecified
**Severity:** Medium  
**Scope:** FR ↔ SC ↔ Assumption contradiction

- SC-013 says subscribers must treat deliveries with the same `Event.event_id` as idempotent (`spec_v4.json:1852-1860`).
- FR-031 says subscribers should dedupe by the same `event_outbox.id`, surfaced via `Event.event_id` (`spec_v4.md:263`).
- EventOutboxModel fields do not include a stored `event_id`, and the FR-031 dispatch call has no parameter that passes the outbox id as an event id (`spec_v4.md:357-358`, `spec_v4.md:263`).

**Issue:** The spec does not define how the stable outbox id becomes the event id on each retry. If `EventBusService.dispatch` creates a fresh event per call, retries will not share `Event.event_id`.

**Recommendation:** Store a stable `event_id` on `event_outbox` and require the dispatcher to pass it through, or expose `event_outbox.id` explicitly in payload/message metadata and change SC-013 / Assumptions to use that key.

### C4-004 — JSON FR↔SC reciprocal links still have one-way edges
**Severity:** Low  
**Scope:** spec.json relationship metadata

Remaining reciprocal-link mismatches found in `spec_v4.json`:

- `FR-024 -> SC-031`, but `SC-031.related_requirements` omits `FR-024`.
- `SC-013 -> FR-031`, but `FR-031.related_success_criteria` omits `SC-013`.
- `SC-025 -> FR-031`, but `FR-031.related_success_criteria` omits `SC-025`.

**Recommendation:** Make the relationship graph reciprocal, or document that one direction is authoritative.

## v3 finding status

| v3 finding | v4 status |
|---|---|
| C3-001 event dispatch rollback contradiction | Mostly fixed by FR-030/FR-031 outbox; new dispatcher race remains C4-002. |
| C3-002 US-9 body vs 204 | HTTP body conflict fixed; residual no-op event/message-key contradiction remains C4-001. |
| C3-003 payload lacks localization field | Field added, but no-op paths that need non-None values enqueue zero events; see C4-001. |
| C3-004 stale locale sentence | Fixed. |
| C3-005 reciprocal JSON links | Improved, but 3 one-way edges remain; see C4-004. |

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata/header/footer | `spec.md` is rendered prose; `spec.json` has structured metadata, model/tool fields, and arrays. | Expected representation difference. |
| User stories / FRs / SCs | Prose content is materially aligned between Markdown and JSON. | C4-001 and C4-002 exist in both representations. |
| Key entities / edge cases / assumptions / out of scope | Same semantics, with JSON split into structured objects. | C4-003 exists in both representations. |
| Relationship metadata | Markdown renders only simple `Related:` lines; JSON carries explicit `related_*` arrays. | JSON-only metadata has the remaining reciprocal-link issue C4-004. |

## Recommended resolution order

1. Resolve no-op localization surface: logs-only or explicit no-op outbox events.
2. Add a dispatcher claim/locking contract or downgrade normal dispatch to at-least-once.
3. Define a stable retry idempotency key and how subscribers receive it.
4. Clean up remaining reciprocal JSON links.
