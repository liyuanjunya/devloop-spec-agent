# Consistency Review v3 — Case-5 LIVE RUN ITER 3

**Reviewer:** Consistency Reviewer  
**Inputs:** `spec_v3.md`, `spec_v3.json`, `review_v2_consistency.md`, `rewrite_v2_to_v3.md`  
**Verdict:** **REVISE** — v3 fixes the v2 CAS-before-side-effects, subscriber-table/model/schema, PATCH, FK, and 204 contracts in most FR/SC text, but it still contains one blocking transaction/event contradiction and one high-severity US-9 response contradiction. Approval requires 0 critical + 0 high.

## Summary

The rewrite resolves the main v2 structural contradictions around daily idempotency: FR-011/FR-012 now put the CAS before shopping-list mutation, CAS losers do not dispatch events, run-now precondition failures are mostly normalized to HTTP 204, the target-list FK is explicit, and the event subscriber field is added to migration + ORM + schema.

Two material inconsistencies remain. First, the event dispatch is specified both as after-commit and as rollback-protected by the same transaction; those cannot both be true. Second, US-9 still requires a localized string in the run-now no-meal-plan response body even though FR-020/FR-022/SC-026 now require HTTP 204 with no body. Because these include high/blocking findings, v3 cannot be approved.

## Findings

### C3-001 — Event dispatch is both after-commit and transaction-rollback protected
**Severity:** Blocking  
**Scope:** Summary ↔ FR ↔ SC contradiction

- The summary says the CAS, shopping-list mutation, recipe-reference update, and event dispatch are inside the same DB transaction, and any exception rolls back the CAS.
- FR-011 step 6 allows dispatch via `session.commit()` followed by `EventBusService.dispatch(...)`, OR via an SQLAlchemy `after_commit` hook.
- FR-011 then says any exception during steps 4-6 raises out of the transaction context and rolls back the CAS and item writes.
- FR-012 repeats that if `bulk_create_items` or event dispatch raises, rollback reverts the CAS update.
- FR-021 says failures during steps 5-6 roll back the transaction and marker, and no event is dispatched.

**Issue:** A dispatch that occurs after `session.commit()` (including an `after_commit` hook) is not protected by the just-committed transaction. If dispatch fails after commit, the marker and shopping-list writes are already durable, so the next scheduler tick will see the marker and will not retry, contradicting FR-012/FR-021 and US-5 reliability expectations.

**Recommendation:** Choose one explicit contract. Preferred: commit DB side effects first, then dispatch after commit, and document that event dispatch failure is handled by the event bus/outbox/retry mechanism rather than DB rollback. Alternative: dispatch before commit and accept the risk of external side effects before DB durability. Do not claim after-commit dispatch can roll back the CAS.

### C3-002 — US-9 still requires a response body for the 204 no-meal-plan run-now path
**Severity:** High  
**Scope:** US ↔ FR ↔ SC contradiction

- US-9 independent test says to trigger run-now with no active meal plan and assert the response body's localized message key equals `auto-sync.no-meal-plan-today`.
- US-9 AC1 says the run-now response contains the localized string registered under `auto-sync.no-meal-plan-today`.
- FR-020 says precondition failures, including empty meal plan, return HTTP 204 No Content with no body.
- FR-022 says those i18n keys are NOT included in the HTTP response body for run-now.
- SC-026 asserts HTTP 204 and zero-byte body for no-meal-plan and no-target-list cases.

**Issue:** The same path cannot both return HTTP 204 with a zero-byte body and contain a localized response string. This is the v2 run-now response conflict partially left behind in the user-story acceptance text.

**Recommendation:** Update US-9 independent test and AC1 to assert HTTP 204 with no body plus a server-side log/event-key assertion, or change FR-020/SC-026 if a body is truly required. Given input requirement 5, the safer fix is to align US-9 with 204/no-body.

### C3-003 — US-9/event-payload localization surface is underspecified
**Severity:** Medium  
**Scope:** US ↔ FR contradiction

- US-9 describes localized strings in the API response or webhook payload.
- FR-022 says the i18n keys surface in server-side logs and in the event payload dispatched by FR-021 when applicable.
- FR-021 defines `EventMealPlanAutoSyncedData` with only `operation`, `household_id`, `shopping_list_id`, `added_item_count`, and `skipped_pantry_count`; it has no `message_key`, `message`, or localization field.

**Issue:** The spec says webhook/event consumers can see the localization key, but the event payload schema has no place to carry it. This is not as severe as C3-002 because the core sync can still be implemented, but US-9 cannot be fully tested as written.

**Recommendation:** Either add an explicit `message_key`/`message` field to `EventMealPlanAutoSyncedData`, or revise US-9/FR-022 so localization is limited to logs and en-US resource presence.

### C3-004 — Out-of-scope locale text regressed to the old single-locale claim
**Severity:** Medium  
**Scope:** Assumption ↔ Out-of-scope contradiction

- FR-022 and Assumption #3 correctly say Mealie ships 40+ locale files and only `en-US.json` is editable because other locales are Crowdin-managed.
- Out of Scope still says: “Internationalization for non-en-US locales. Mealie currently ships only en-US.json.”

**Issue:** The first sentence is acceptable scope control, but the second sentence is factually inconsistent with FR-022 and Assumption #3. This is the same locale misconception v2 intended to remove.

**Recommendation:** Change the out-of-scope item to: “Internationalization changes for non-en-US locales; Mealie ships 40+ Crowdin-managed locale files, but this PR edits only `en-US.json`.”

### C3-005 — JSON FR↔SC reciprocal links still have one-way edges
**Severity:** Low  
**Scope:** spec.json relationship consistency

The following JSON relationship links are one-way only:

- SC-026 → FR-020 and FR-022, but FR-020/FR-022 do not list SC-026.
- SC-027 → FR-021 and FR-024, but FR-021/FR-024 do not list SC-027.
- SC-028 → FR-001, but FR-001 does not list SC-028.
- SC-029 → FR-023, but FR-023 does not list SC-029.

**Recommendation:** Make `related_success_criteria` and `related_requirements` reciprocal, or document that only the SC→FR direction is authoritative.

## v2 finding status

| v2 finding | v3 status |
|---|---|
| C2-001 CAS after side effects | Fixed by FR-011/FR-012 CAS-before-side-effects ordering. New event rollback wording creates C3-001. |
| C2-002 duplicate event edge case | Fixed for CAS losers; FR-011/FR-021 now say zero dispatch on losers. New dispatch failure semantics remain C3-001. |
| C2-003 run-now response shape vs localized detail | Mostly fixed in FR-020/FR-022/SC-026, but US-9 independent test and AC1 still require a response body; see C3-002. |
| C2-004 target-list FK missing from migration | Fixed by FR-024 step A and SC-028. |
| C2-005 no-meal-plan retry overstates window | Fixed in edge case text. |
| C2-006 reciprocal JSON links | Improved but not fully fixed; see C3-005. |

## Self-concerns vs FRs / ACs

- FR-021 self-concern correctly recognizes a migration/ORM/schema startup gap, but it does not address C3-001: the main FRs still make impossible rollback claims for after-commit dispatch.
- FR-022 self-concern aligns with FR-022 and Assumption #3, but conflicts with the stale Out-of-scope sentence in C3-004.
- FR-009 ZoneInfo cost concern does not weaken any hard AC.

## Edge cases vs FRs / ACs

- The two-replica edge case is now aligned with CAS-winner/CAS-loser idempotency and exactly-once-per-winner dispatch.
- The force-mode mid-transaction exception edge case inherits C3-001 if the exception is an after-commit dispatch failure: the DB marker cannot be rolled back after commit.
- The no-meal-plan / no-target-list run-now edge case aligns with FR-020/SC-026, but conflicts with US-9 AC1 as described in C3-002.
- Deleted target, invalid timezone, recipe cycle, pantry cascade, zero-list, auth-bypass, and no-meal-plan scheduler retry edge cases are otherwise aligned with the FRs.

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata/header/footer | `spec.md` has rendered title/header/footer; `spec.json` has structured `metadata`, schema version, model/tool fields, and counts. | Expected representation difference. |
| Needs clarification | Same NC-001..NC-003 semantics. JSON carries structured `related_requirements`. | No material mismatch found. |
| User stories | Same 9 user stories and acceptance content. The US-9 no-meal-plan response-body contradiction exists in both JSON and Markdown. | Material behavioral issue shared by both; see C3-002. |
| Functional requirements | Same 29 FRs in order. JSON additionally carries `requirement_type`, `testable`, `related_success_criteria`, and structured code references. | FR prose issues are shared by both; relationship mismatches are JSON metadata only (C3-005). |
| Success criteria | Same 29 SCs in order and prose. JSON additionally carries metrics, thresholds, and `related_requirements`. | No prose mismatch found; relationship mismatches remain. |
| Key entities / edge cases / assumptions / out of scope / self-concerns | Same semantics, with JSON split into structured objects. | The locale out-of-scope contradiction exists in both representations; see C3-004. |

## US ↔ FR.related_user_stories check

Every user story is represented in the FR relationship graph, and no dangling user-story IDs were found in `spec.json`. Semantic contradiction remains for US-9 because the user story requires localized response content on a route whose FR/SC contract is 204/no-body.

## FR ↔ SC bidirectional check

All FRs have at least one SC and all SCs have at least one FR. Reciprocal-link mismatches remain as listed in C3-005.

## Recommended resolution order

1. Resolve the event transaction contract: after-commit dispatch with outbox/retry, or pre-commit dispatch without rollback claims.
2. Rewrite US-9 independent test and AC1 to match FR-020/SC-026 204/no-body behavior.
3. Decide whether event payloads carry a localization key; update FR-021/FR-022/US-9 consistently.
4. Fix the stale non-en-US out-of-scope sentence.
5. Clean up reciprocal JSON links.
