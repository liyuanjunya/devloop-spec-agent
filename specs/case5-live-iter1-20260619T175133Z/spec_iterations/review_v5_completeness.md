# Completeness Review (v5)

## Verdict: APPROVE

Spec v5 resolves the v3 completeness blocker. The no-meal-plan/run-now contract is now consistently specified as HTTP 204 No Content with zero body bytes, with the `auto-sync.no-meal-plan-today` key asserted through server-side logs and no event dispatch. I found 0 critical and 0 high completeness issues.

## Critical issues

None.

## High issues

None.

## Medium issues

### COMP-M-014 — One edge-case paragraph still asserts rollback despite NC-004 deferral

- Location: `spec_v5.md:352`, compared with `spec_v5.md:203`, `spec_v5.md:206`, `spec_v5.md:357`, `spec_v5.md:371`, `spec_v5.md:393-395`.
- Evidence: FR-011/FR-012 and the assumptions correctly defer rollback semantics for step-5/step-6 failures to NC-004, and the force-mode exception edge case is neutral across PATH A vs PATH B/C. However, the sub-recipe cycle edge case still says the exception propagates out of the transaction context and rolls back the CAS update so `last_auto_synced_at` is not touched. That statement is only true under NC-004 PATH A; under PATH B/C, the CAS commits before side effects and the marker remains set.
- Impact: This is not a high completeness blocker because sub-recipe cycle handling is not part of the input's primary acceptance surface and NC-004 already makes the durability choice explicit. Still, it is a residual non-neutral sentence in a spec that otherwise claims neutral transaction wording.
- Suggested fix: Rewrite the sub-recipe-cycle edge case like the force-mode exception edge case: under PATH A the CAS/items/outbox roll back; under PATH B/C the marker may remain set and retry/recovery follows the chosen partial-failure policy.

## v3 issue resolution table

| v3 issue | v3 severity | v5 status | Evidence | Completeness assessment |
|---|---:|---|---|---|
| COMP-H-013: No-meal-plan run-now contract contradicted by US-9 response-body acceptance text | High | ✅ Resolved | `spec_v5.md:155-167`, `spec_v5.md:230`, `spec_v5.md:236`, `spec_v5.md:313-314`, `spec_v5.md:358` | US-9, FR-020, FR-022, SC-026, and the edge case now all require 204 with zero body bytes, logs-only i18n, and zero event dispatch on no-op/precondition-failure paths. |

## Requirement coverage delta

| Input requirement area | v5 completeness verdict |
|---|---|
| Household preference fields, persistence, PATCH/PUT/read schemas | Covered |
| Scheduler window, timezone, target-list fallback | Covered |
| Multi-replica idempotency / once-per-day processing | Covered, with durability semantics explicitly escalated to NC-004 |
| Ingredient aggregation, pantry filtering, append/merge | Covered |
| Manual run-now route, admin auth, success and no-content responses | Covered |
| Event bus and i18n keys | Covered; no-op i18n is logs-only and success event payload has `message_key=None` |
| Unit/integration/multitenant tests | Covered |

## Summary

Approve v5 from a completeness perspective. The v3 high-severity contradiction is resolved, and no new critical/high completeness regressions were found. Address COMP-M-014 opportunistically when NC-004 is resolved.
