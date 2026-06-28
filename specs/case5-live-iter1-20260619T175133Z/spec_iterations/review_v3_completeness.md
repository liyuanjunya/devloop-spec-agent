# Completeness Review (v3)

## Verdict: NEEDS_REFINE

Spec v3 fixes the main v2 completeness regression around CAS ordering and adds the missing cross-group and subscriber coverage. However, the no-meal-plan/run-now contract is still internally contradictory in a normative user story: US-9 continues to require a localized response body for the same path that FR-020/SC-026 now require to be HTTP 204 with an empty body. Because that was the v2 high-severity completeness regression, v3 should not be approved until the stale US-9 text is aligned with the chosen 204/no-body contract.

## Critical issues

None.

## High issues

### COMP-H-013 — No-meal-plan run-now contract is still contradicted by US-9 response-body acceptance text

- Location: `input.md:67-71`, `input.md:57-58`; `spec_v3.md:145-155`, `spec_v3.md:219-225`, `spec_v3.md:347`, `spec_v3.md:366`, `spec_v3.md:375-378`.
- Evidence: The input requires the no-meal-plan integration path to return `204 / 0 added` and separately requires exact i18n keys. V3's FR-020 and SC-026 choose a clear endpoint contract: precondition failure returns HTTP 204 No Content with no body, and i18n keys are logged rather than returned in the run-now response. But US-9 still says the operator reads localized strings in the API response or webhook payload, its independent test says to assert the response body's localized message key, and AC1 says the response contains `auto-sync.no-meal-plan-today`. That is impossible for a 204 zero-byte response and contradicts the normative success criterion.
- Impact: A code agent can reasonably follow US-9 and return a body/detail field, failing SC-026 and the v2 high-severity fix; or follow SC-026 and fail US-9's acceptance scenario. The no-meal-plan contract is therefore not fully specified without contradiction.
- Required fix: Rewrite US-9's description, independent test, and AC1 to match the chosen v3 contract: run-now no-meal-plan returns HTTP 204 with an empty body, while `auto-sync.no-meal-plan-today` is asserted through logs/telemetry (or choose a 200 body contract and update FR-020/SC-026 accordingly). Also fix the stale out-of-scope locale sentence so it does not say Mealie ships only `en-US.json` while FR-022 says 40+ locales exist.

## Medium issues

None beyond the high issue above.

## v2 issue resolution table

| v2 issue | v2 severity | v3 status | Evidence | Completeness assessment |
|---|---:|---|---|---|
| COMP-C-010: CAS marker written after side effects | Critical | ✅ Resolved | `spec_v3.md:8`, `spec_v3.md:192-196`, `spec_v3.md:337-346` | CAS is now before `bulk_create_items`/event dispatch in the same transaction, and loser behavior is a structural no-op. |
| COMP-H-011: no-meal-plan integration status/shape | High | ⚠️ Partially resolved | `spec_v3.md:219`, `spec_v3.md:347`, but contradicted by `spec_v3.md:145-155` | FR/SC now specify 204 empty body, but US-9 still requires a localized response body. |
| COMP-M-012: cross-group isolation test missing | Medium | ✅ Resolved | `spec_v3.md:246-248`, `spec_v3.md:293-295` | FR-029 and SC-029 add explicit cross-group byte-equality assertions. |

## Requirement coverage delta

| Input requirement area | v3 completeness verdict |
|---|---|
| Household preference fields, storage, PATCH/PUT/read schemas | Covered |
| Scheduler window, timezone, target-list fallback | Covered |
| Multi-replica idempotency / once-per-day processing | Covered |
| Ingredient aggregation, pantry filtering, append/merge | Covered |
| Manual run-now route, auth, success response | Mostly covered; no-meal-plan 204 contract still conflicts with US-9 |
| Event bus and i18n keys | Covered, except stale US-9 response/webhook wording |
| Unit/integration/multitenant tests | Covered |

## Summary

Refine v3 before coding. The v2 CAS and cross-group gaps are fixed, but the v2 high-severity no-meal-plan contract regression is only partially fixed because US-9 still demands a response body for a 204 path.
