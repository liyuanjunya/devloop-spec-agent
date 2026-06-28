# Consistency Review v5 — Case-5 LIVE RUN ITER 5

**Reviewer:** Consistency Reviewer v5  
**Inputs:** `spec_v5.md`, `spec_v5.json`, `review_v3_consistency.md`, `rewrite_v3_v4_to_v5.md`  
**Verdict:** **REVISE** — v5 fixes the v3 high response-body/i18n conflict and most v3 transaction wording, but one high-severity rollback contradiction remains. Approval requires 0 critical + 0 high.

## Summary

v5 is substantially more internally consistent than v3. US-9, FR-020, FR-021, FR-022, SC-026, and the no-op edge cases now agree that run-now precondition failures return HTTP 204 with a zero-byte body, log the i18n key server-side, and dispatch no event. The v3 after-commit/rollback impossibility is mostly moved into NC-004 as a blocking decision instead of being falsely specified in FR-011/FR-012/FR-021.

However, one edge case still makes the old unconditional rollback claim: the sub-recipe cycle path says an exception propagates out of an FR-011 transaction context and rolls back the CAS/update/items. That contradicts NC-004, FR-011, FR-012, FR-020, the force-mode edge case, and Assumption #10, all of which say rollback behavior is path-dependent until NC-004 is resolved. Because that contradiction reintroduces a high-severity transaction/durability inconsistency, v5 cannot be approved.

## Findings

### C5-001 — Sub-recipe cycle edge case still promises rollback despite NC-004 deferral
**Severity:** High  
**Scope:** Edge case ↔ NC ↔ FR contradiction

- NC-004 says the rollback/durability choice is unresolved and offers PATH A (atomic rollback via outbox/refactor) versus PATH B/C (CAS commits first; later failures leave marker set).
- FR-011 says it specifies only ordering and CAS-loser short-circuit until NC-004 is resolved; rollback/retry semantics for steps 5-6 are determined by NC-004.
- FR-012 says rollback of the CAS on step-5/step-6 failure is governed by NC-004; under PATH B/C, later failures leave the marker set.
- FR-020 and the force-mode edge case use path-dependent wording for mid-pipeline exceptions.
- The edge case “Recipe contains a sub-recipe reference cycle” says the exception propagates out of the FR-011 transaction context, which “ROLLS BACK the CAS UPDATE alongside any partial item writes — so last_auto_synced_at reverts and the marker is NOT touched.”

**Issue:** The sub-recipe cycle edge case chooses PATH A rollback semantics while the rest of v5 deliberately defers that decision. Under NC-004 PATH B/C, the CAS may already be committed before recursive expansion/item writes fail, so the marker would not necessarily revert. This is the same class of transaction contradiction v5 was intended to remove.

**Recommendation:** Rewrite the sub-recipe cycle edge case in neutral terms, e.g. “On RecursionError, the task logs the recipe id and continues; whether the CAS marker and partial writes roll back is governed by NC-004. Under PATH A they roll back atomically; under PATH B/C the marker may remain set and recovery follows the selected partial-failure policy.”

### C5-002 — JSON SC-027 still has one non-reciprocal FR link
**Severity:** Low  
**Scope:** spec.json relationship consistency

- `SC-027.related_requirements` lists `FR-021`, `FR-024`, and `FR-028`.
- `FR-021.related_success_criteria` includes `SC-027`.
- `FR-028.related_success_criteria` includes `SC-027`.
- `FR-024.related_success_criteria` lists `SC-020`, `SC-002`, and `SC-028`, but not `SC-027`.
- The rewrite log says reciprocal links were fixed for `SC-027↔FR-021/FR-024/FR-028`, but the JSON still lacks the `FR-024 → SC-027` back-link.

**Issue:** This is metadata-only and does not change behavior, but it means the claimed v3 C3-005 fix is incomplete.

**Recommendation:** Add `SC-027` to `FR-024.related_success_criteria`, or remove `FR-024` from `SC-027.related_requirements` if migration coverage should not be tied to that SC.

### C5-003 — Summary says NC-004 has “two paths” but NC-004 defines three
**Severity:** Low  
**Scope:** Summary ↔ NC wording

The summary says “see NC-004 for the two paths,” while NC-004 defines PATH A, PATH B, and PATH C and later text repeatedly says “three paths.”

**Recommendation:** Change the summary wording from “two paths” to “three paths.”

### C5-004 — Run-now success response type allows impossible null target_list_id
**Severity:** Low  
**Scope:** FR ↔ SC precision

FR-020 and SC-012 allow `target_list_id: UUID4 | null` in the HTTP 200 success body. But FR-013/FR-014/FR-020 say success occurs only after a target list is resolvable; no target list returns HTTP 204. Therefore `target_list_id` should always be a UUID on success.

**Recommendation:** Tighten FR-020 and SC-012 to `target_list_id: UUID4` for HTTP 200 success responses.

## v3 consistency finding status

| v3 finding | v5 status |
|---|---|
| C3-001 event dispatch both after-commit and rollback-protected | Mostly fixed by NC-004 deferral in FR-011/FR-012/FR-021, but the sub-recipe cycle edge case still makes an unconditional rollback claim; see C5-001. |
| C3-002 US-9 response body for 204 path | Fixed. US-9, FR-020, FR-022, SC-026, and edge cases now require HTTP 204 with zero body and logs-only i18n. |
| C3-003 localization surface underspecified | Fixed. No-op keys are logs-only; success event has `message_key=None`; no-op paths dispatch no event. |
| C3-004 stale non-en-US locale sentence | Fixed. Out of Scope now correctly describes 40+ Crowdin-managed locales and en-US-only PR changes. |
| C3-005 one-way JSON FR↔SC links | Mostly fixed, but one mismatch remains: `SC-027 → FR-024` lacks `FR-024 → SC-027`; see C5-002. |

## Self-concerns vs FRs / ACs

- FR-011 self-concern correctly explains the NC-004 escalation and matches FR-011/FR-012/FR-021.
- FR-022 self-concern aligns with US-9/FR-022/Out of Scope.
- The sub-recipe cycle edge case is the outlier because it ignores the same NC-004 uncertainty that the FR-011 self-concern documents.

## Edge cases vs FRs / ACs

- No-meal-plan, no-target-list, already-synced, two-replica, invalid-timezone, deleted-list, deleted-food, zero-list, auth-bypass, and force-mode exception edge cases are aligned with the FRs.
- The sub-recipe cycle edge case is not aligned because it asserts unconditional rollback rather than NC-004-dependent rollback semantics.

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata/header/footer | `spec.md` has rendered title/header/footer; `spec.json` has structured metadata (`iterations=5`, model fields, counts). | Expected representation difference. |
| Needs clarification | Same NC-001..NC-004 semantics. JSON carries structured `related_requirements`. | No material prose mismatch found. |
| User stories | Same 9 user stories and acceptance content. | US-9 204/no-body/logs-only fix is present in both. |
| Functional requirements | Same 29 FRs in order. JSON additionally carries `requirement_type`, `testable`, `related_success_criteria`, and structured code references. | Behavioral prose is aligned; JSON metadata has the `FR-024`/`SC-027` reciprocal-link issue in C5-002. |
| Success criteria | Same 29 SCs in order. JSON additionally carries metrics, thresholds, and `related_requirements`. | No prose mismatch found; SC-027 metadata mismatch is JSON-only. |
| Key entities / edge cases / assumptions / out of scope / self-concerns | Same semantics, with JSON split into structured objects. | The sub-recipe cycle rollback contradiction exists in both representations. |

## US ↔ FR.related_user_stories check

All user-story IDs referenced by FRs exist in `spec.json`; no dangling user-story links were found. US-9 is now semantically aligned with FR-020/FR-021/FR-022/SC-026.

## FR ↔ SC bidirectional check

All FRs and SCs have at least one relationship, and nearly all reciprocal links are now correct. The only remaining one-way edge found is `SC-027 → FR-024` without the reciprocal `FR-024 → SC-027`.

## Recommended resolution order

1. Fix the sub-recipe cycle edge case to defer rollback semantics to NC-004, matching the force-mode edge case wording.
2. Add the missing `FR-024.related_success_criteria += [SC-027]` reciprocal link, or remove the reverse link.
3. Change the summary “two paths” phrase to “three paths.”
4. Tighten run-now HTTP 200 `target_list_id` from nullable UUID to required UUID.

## Final verdict

**REVISE.** Current severity count: **0 critical, 1 high, 3 low**. Do not approve until C5-001 is fixed.
