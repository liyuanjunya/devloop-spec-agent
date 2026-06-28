# Consistency Review v2 — DevLoop Case 2

**Reviewer:** Consistency Reviewer  
**Inputs:** `spec_v2.md`, `spec_v2.json`, `review_v1_consistency.md`, `rewrite_v1_to_v2.md`  
**Verdict:** **REVISE** — v2 resolves the v1 consistency blockers, but introduces/retains a small number of new contradictions that should be normalized before coding.

## Findings

### C2-001 — Concurrent archive expectation is not guaranteed by the specified repository algorithm
**Severity:** Blocking  
**Scope:** Edge cases vs FRs

- `spec_v2.md` EC-7 expects two concurrent `POST /archive` calls to produce exactly one success and one 409 because the loser observes `archived_at IS NOT NULL` during `RepositoryShoppingList.archive` pre-fetch (lines 595-598).
- `spec_v2.md` FR-7 specifies a pre-fetch, then an UPDATE whose tenant-scoped WHERE clause includes list id, group id, and household ownership, but **does not include `archived_at IS NULL`** nor require checking `rowcount` (lines 262-266).
- If both requests pre-fetch while the row is active, both can execute the specified UPDATE and both can return success, contradicting EC-7.

**Recommendation:** Make the transition atomic: include `ShoppingList.archived_at.is_(None)` in the UPDATE WHERE clause and convert `rowcount == 0` after a visible active pre-fetch into `ShoppingListIsArchivedError`, or explicitly state concurrent double-success/last-writer-wins is acceptable and revise EC-7.

### C2-002 — `ArchiveTransitionResult` ownership contradicts repository/service layering
**Severity:** Blocking  
**Scope:** FR-internal; FR-7 vs FR-11; layering consistency

- `spec_v2.md` FR-7 requires repository methods `archive()` / `unarchive()` to return `ArchiveTransitionResult` (lines 262-271).
- The same FR says `ArchiveTransitionResult` is declared in `mealie/services/household_services/shopping_lists.py`, not in the repository or schema layer (line 286), and FR-11 repeats that declaration (lines 406-410).
- That makes the repository layer depend on a service-layer type while the service calls the repository, undermining the repository-service-controller separation v2 otherwise tries to preserve.

**Recommendation:** Define `ArchiveTransitionResult` in a neutral lower-level module (for example `mealie/schema/household/group_shopping_list.py` or a small repository DTO module), or have the repository return `(ShoppingListOut, transitioned)` / a local dataclass and let the service wrap it.

### C2-003 — Global exception handler response wording is inconsistent in `spec_v2.json`
**Severity:** Non-blocking  
**Scope:** spec.md vs spec.json; selected approach vs FR-11

- `spec_v2.md` consistently says domain exceptions are translated to HTTP 409 by a global FastAPI handler and FR-11's code sketch returns `JSONResponse` (lines 430-455).
- `spec_v2.json` `selected_approach.rationale` says the handler translates to `HTTPException(409, ErrorResponse.respond(...))` (line 24), while JSON FR-11 says the handler returns `JSONResponse` (line 334).

**Recommendation:** Replace the selected-approach wording with “returns a 409 JSONResponse” / “HTTP 409 response” to avoid reintroducing the service/HTTPException ambiguity fixed from v1 C-004.

### C2-004 — Stale v1/v2 scope language remains in v2 edge cases
**Severity:** Non-blocking  
**Scope:** EC-internal; self-concerns

- `spec_v2.md` EC-6 says “Expected (v1)”, “no admin-specific archive/unarchive endpoint is added in v1”, and “Tracked under self_concerns for v2 consideration” (lines 590-593), despite this being Spec v2.
- `spec_v2.json` carries the same stale wording in EC-6 (lines 533-537).

**Recommendation:** Rename those references to “current scope” / “this iteration” and, if still relevant, “future consideration” rather than “v1” or “v2 consideration”.

### C2-005 — `archived_by` loader mitigation contradicts FR-9
**Severity:** Non-blocking  
**Scope:** self_concerns vs FRs

- FR-9 requires `ShoppingListSummary.loader_options()` and `ShoppingListOut.loader_options()` to gain `selectinload(ShoppingList.archived_by)` (spec_v2.md lines 345-349).
- SCN-4 mitigates the performance concern by saying `archived_by` is “Only loaded eagerly when needed” (lines 660-663), but the FR-9 loader-options change is unconditional for those schemas.

**Recommendation:** Either state the eager load is unconditional but accepted, or specify conditional loader behavior tied to `archived=true|all` if that is intended.

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata | `spec_v2.md` has rendered header/status fields (lines 3-8); `spec_v2.json` has structured `metadata` and `resolves` arrays (lines 6-20). | Expected format difference. |
| Selected approach exception translation | `spec_v2.md` says global handler translates domain exceptions to HTTP 409 (line 14); `spec_v2.json` says `HTTPException(409, ...)` in selected-approach rationale (line 24). | Semantic mismatch; see C2-003. |
| Edge case count | `spec_v2.md` heading says “covers 9” (line 554) while it lists EC-1, EC-2, EC-2b, EC-3…EC-9 (10 entries); `spec_v2.json` has 10 `edge_cases`. | Minor count mismatch; update heading to 10 or do not count EC-2b separately. |
| `ShoppingListArchivePreconditionError` declaration | `spec_v2.json` FR-7 explicitly lists both `ShoppingListIsArchivedError` and `ShoppingListArchivePreconditionError` in `mealie/core/exceptions.py` (line 254); `spec_v2.md` FR-7 only declares `ShoppingListIsArchivedError` there (lines 284-286), while FR-11 later imports/uses `ShoppingListArchivePreconditionError` (lines 416, 432). | Low risk but normalize md FR-7 so implementers know both exceptions belong in `mealie/core/exceptions.py`. |
| Compliance checklist | `spec_v2.md` includes `task ui:check` when UI-adjacent files change (line 679); `spec_v2.json` checklist omits this item (lines 673-685). | Minor parity gap; add to JSON if checklist round-trip parity matters. |
| v1 scope language | Both files contain stale “v1 scope” wording in EC-6, but locations differ (`spec_v2.md` lines 590-593; `spec_v2.json` lines 533-537). | Same issue in both representations; see C2-004. |
| Prose density | `spec_v2.md` includes code blocks and expanded rationale; `spec_v2.json` condenses these into arrays/strings. | Expected lossy representation; no action beyond semantic diffs above. |

## Overall recommendation

Revise before design/coding. v2 successfully fixes v1 consistency findings C-001 through C-007, but C2-001 and C2-002 affect implementable behavior and module ownership. The remaining findings are low-cost wording/parity cleanups.
