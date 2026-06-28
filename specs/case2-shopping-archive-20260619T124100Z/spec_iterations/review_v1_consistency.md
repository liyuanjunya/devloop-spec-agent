# Consistency Review v1 — DevLoop Case 2

**Reviewer:** Consistency Reviewer  
**Inputs:** `spec.md`, `spec.json`  
**Verdict:** **REVISE** — several internal contradictions would lead implementers/tests to choose incompatible behavior.

## Findings

### C-001 — `archived_by_user_id` invariant conflicts with `ON DELETE SET NULL`
**Severity:** Blocking  
**Scope:** FR-internal; Edge cases vs FRs; needs_clarification vs FR/defaults; spec.md vs spec.json

- `spec.md` FR-1 requires `archived_at IS NULL ⇔ archived_by_user_id IS NULL` (line 147).
- `spec.md` EC-8/NC-5 then requires `ON DELETE SET NULL` and expects an archived list to retain `archived_at` while `archived_by_user_id` becomes `NULL` (lines 495-527).
- `spec.md` FR-2 initially says the FK is created without `ondelete=` (line 158), while NC-5 says FR-2 declares `ondelete="SET NULL"` (line 527).
- `spec.json` FR-2 already includes `ondelete='SET NULL'` (line 136), diverging from `spec.md` FR-2.

**Recommendation:** Pick one invariant. Suggested: active lists must have `archived_by_user_id IS NULL`; archived lists may have `archived_by_user_id NULL` after user deletion. Update FR-1 and `spec.md` FR-2 accordingly.

### C-002 — Event payload exact field set is inconsistent about `operation`
**Severity:** Blocking  
**Scope:** US ↔ FR ↔ SC contradictions; AC-internal contradictions

- US-7 and SC-3 require exact payload keys including `operation` (spec.md lines 98, 434; spec.json lines 82, 381).
- FR-10's concrete `EventShoppingListArchiveData` class lists `document_type`, `shopping_list_id`, `shopping_list_name`, `household_id`, `archived_by_user_id`, `item_count`, and `total_estimated_amount`, but not `operation` (spec.md lines 310-320; spec.json line 276).
- FR-10 then says payload must not contain any field not listed above (spec.md line 323; spec.json line 278).

**Recommendation:** State explicitly that `operation` is inherited from `EventDocumentDataBase` and is part of the allowed exact field set, or remove it from US/SC expectations.

### C-003 — Unarchive idempotent no-op event behavior conflicts with controller dispatch rule
**Severity:** Blocking  
**Scope:** Edge cases vs FRs/ACs

- EC-3 says `POST /unarchive` on an active list returns `200 OK` and dispatches **no event** (spec.md lines 464-467; spec.json lines 452-456).
- FR-7 says `unarchive(item_id)` is idempotent and returns unchanged row for active lists (spec.md lines 242-245; spec.json line 225).
- FR-4 says archive/unarchive endpoints dispatch `shopping_list_archived` / `shopping_list_unarchived` after success (spec.md line 188; spec.json line 170), with no exception for no-op success.

**Recommendation:** Define a state-change flag or have service return whether a transition occurred. Dispatch `shopping_list_unarchived` only when `archived_at` changed from non-null to null, if EC-3 is intended.

### C-004 — HTTP translation ownership contradicts repository/service layering guidance
**Severity:** Blocking  
**Scope:** self_concerns vs FRs; FR-internal

- FR-11 requires `ShoppingListService.archive_list` and bulk methods to raise/catch `HTTPException` and call `self.t(...)` (spec.md lines 337-358; spec.json lines 292-295).
- The selected approach says repositories raise typed exceptions with no HTTP/i18n concerns, translated by service layer or FastAPI global handler (spec.json line 9).
- SCN-1 recommends a global exception handler because `ShoppingListService` has no translator (spec.md lines 535-539; spec.json lines 533-536).
- The compliance checklist says service methods stay free of HTTP concerns (spec.md line 569; spec.json line 598).

**Recommendation:** Choose one translation boundary. Suggested: service raises domain exceptions; controller/global handler translates to `HTTPException` with i18n. Update FR-11 examples and compliance checklist to match.

### C-005 — Frozen scope says “every mutating operation” but defaults allow mutable/partially mutable routes
**Severity:** Blocking  
**Scope:** US ↔ FR; needs_clarification vs FR/defaults; AC-internal

- Summary and US-5 say archived lists/items are immutable and every mutating operation on the list/items is rejected (spec.md lines 13, 62; spec.json lines 6, 62).
- FR-6 freezes only seven route variants and explicitly excludes label-settings and recipe routes (spec.md lines 209-222; spec.json lines 197-212).
- NC-1 default leaves label-settings mutable and accepts recipe partial-mutation-then-409 behavior (spec.md lines 504-508; spec.json lines 496-500).

**Recommendation:** Either narrow US/summary wording to “the enumerated item/list CRUD routes” or expand FR-6 to freeze all list-mutating routes, including label-settings and recipe operations, with atomic rollback.

### C-006 — SC-2 title/count is misleading
**Severity:** Non-blocking  
**Scope:** SC-internal

- SC-2 title says “All 4 frozen routes” but measurement requires seven route variants (spec.md line 433; spec.json lines 374-376).

**Recommendation:** Rename to “All frozen route variants” or “All 7 frozen route variants”.

### C-007 — `RepositoryShoppingListItem` dependency text contains unresolved implementation alternatives
**Severity:** Non-blocking  
**Scope:** FR-internal; self_concerns vs FRs

- FR-8 says `RepositoryShoppingListItem` should call `self.repos.group_shopping_lists`, then says the repo has no back-reference and offers alternatives (spec.md lines 267-280).
- SCN-3 later recommends constructor-injected `parent_repo` (spec.md lines 545-548; spec.json lines 545-548).

**Recommendation:** Make FR-8 normative: require constructor-injected `parent_repo: RepositoryShoppingList`; move alternatives to rationale only.

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata | `spec.md` has Generated/Repo/Selected approach/Input source/Status header (lines 3-7); `spec.json` has `schema_version`, `case_id`, `feature_name`, `intent_type` (lines 2-5). | Expected format difference; no action unless strict round-trip parity is required. |
| `primary_summary` / Summary | `spec.json` summary narrows immutability to “PUT list / POST item / PUT item / DELETE item” (line 6); `spec.md` summary says “all mutating endpoints on the list and its items” (line 13). | Reinforces C-005. |
| FR-2 FK definition | `spec.md` FR-2 omits `ondelete` (line 158); `spec.json` FR-2 includes `ondelete='SET NULL'` (line 136). | Blocking mismatch; see C-001. |
| EC-8 user deletion | `spec.md` contains a contradictory sentence saying FR-2 declares the FK without `ondelete=` and then says use `ON DELETE SET NULL` (lines 495-496); `spec.json` is internally normalized to `SET NULL` (lines 487-491). | `spec.md` should be corrected to match chosen default. |
| Self-concern SCN-1 | `spec.md` says “Recommendation: Use option (c)” and mentions request translator dependency (lines 535-539); `spec.json` is more prescriptive about `mealie/routes/handlers.py` (lines 533-536). | Same direction; not a semantic diff. |
| Compliance checklist | `spec.md` includes `task ui:check` and a checkbox format (lines 561-572); `spec.json` omits `task ui:check` and stores plain strings (lines 590-601). | Minor omission in JSON; add if field-level parity is required. |
| Code references / prose detail | `spec.md` contains detailed rationale paragraphs and line-specific notes that `spec.json` condenses into arrays. | Expected lossy representation; no blocking issue except where noted above. |

## Overall recommendation

Revise before design/coding. Resolve C-001 through C-005 first; they affect migrations, event tests, endpoint behavior, error layering, and frozen-route acceptance criteria.
