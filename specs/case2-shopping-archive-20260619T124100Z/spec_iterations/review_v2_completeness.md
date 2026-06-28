# Completeness Review (v2)

## Verdict: NEEDS_REFINE

v2 resolves most v1 completeness findings: event payload field names now match the input, the multitenant matrix is explicit, the `archived_by_user_id` invariant is coherent with `ON DELETE SET NULL`, recipe/label mutation gaps are closed, and the i18n locale conflict is documented with a repository-policy exception. One critical input-contract issue remains unresolved: the default shopping-list response still includes `archived_at` / `archived_by` as `null`, while input §6 requires default queries not to return those fields.

## v1 resolution table

| v1 issue | v2 disposition | Completeness reviewer status |
|---|---|---|
| COMP-C-001 — Default response must omit `archived_at` / `archived_by`, not emit `null` | Explicitly rejected in `rewrite_v1_to_v2.md` lines 99-107; v2 US-9 lines 121-131 and FR-9 lines 341-352 require null-default fields on default responses | **UNRESOLVED / STILL CRITICAL**. Input §6 line 64 says default query does not return these fields. Row filtering does not satisfy field-shape omission for active rows returned by default GET. |
| COMP-C-002 — Event payload must use `list_id` / `list_name` | Fixed in v2 FR-10 lines 361-384, US-7 lines 96-107, NC-3 lines 627-631 | **RESOLVED**. Payload key set now uses the input's exact names and forbids extra fields. |
| COMP-C-003 — i18n all-language-file requirement weakened to en-US only | v2 documents an explicit repo-policy divergence in FR-13 lines 483-503 and rewrite lines 109-117 | **RESOLVED WITH ACCEPTED EXCEPTION**. This satisfies the v1 requested fix path: document repository-policy exception and require en-US plus Crowdin follow-up. |
| COMP-H-001 — Multitenant tests do not fully enumerate required scenarios | Fixed in SC-6/SC-7/SC-13 lines 541-548 and US-8 lines 109-119 | **RESOLVED**. Same-group GET isolation, cross-group GET isolation, and same/cross-group archive-unarchive 404s are measurable. |
| COMP-H-002 — `archived_by_user_id` invariant conflicts with user deletion | Fixed in FR-1 lines 150-158, EC-8 lines 600-603, SC-15 line 550 | **RESOLVED**. Invariant is now one-way and tested after user deletion. |
| COMP-H-003 — Frozen-scope clarification allows partial mutation on recipe routes | Fixed in US-5 lines 61-81, FR-6 lines 220-242, EC-9 lines 605-608 | **RESOLVED**. v2 requires early pre-flight before label/recipe mutations and row-count/`updated_at` assertions. |

## New issues in v2

### COMP-V2-C-001 — Default response field shape still violates input §6

- **Severity:** Critical
- **Location:** `spec_v2.md` US-9 lines 121-131, FR-9 lines 341-352; `spec_v2.json` US-9 lines 109-116, FR-9 lines 286-295.
- **Evidence:** Input §6 lines 63-64 requires `ShoppingListSummary` / `ShoppingListOut` to add `archived_at` and `archived_by` for archive queries, and states the default query does not return these fields. v2 instead says default `GET /api/households/shopping/lists` returns items with `archived_at: null` and `archived_by: null`, and mandates the fields are always present on the schema.
- **Why this matters:** The requirement is about wire response shape, not only which rows are returned. Default GET still returns active rows; adding two new JSON properties to those rows is observably different from omitting them.
- **Required fix:** Add conditional response shaping or separate active/archive response variants so default `GET /lists` omits `archived_at` and `archived_by`, while `?archived=true` and `?archived=all` include them. If the product owner intentionally accepts the schema break, record it as a formal product decision outside the spec-completeness rubric.

### COMP-V2-M-001 — Markdown spec underspecifies the new precondition exception

- **Severity:** Medium
- **Location:** `spec_v2.md` FR-7 lines 284-286, FR-11 lines 416 and 430-452; `spec_v2.json` FR-7 lines 248-255.
- **Evidence:** The Markdown spec requires raising and handling `ShoppingListArchivePreconditionError`, but only explicitly defines the constructor shape for `ShoppingListIsArchivedError`. The JSON version does list both typed exceptions, so the two v2 artifacts are not equally complete.
- **Suggested fix:** Mirror the JSON requirement in `spec_v2.md`: declare `ShoppingListArchivePreconditionError(list_ids: set[UUID4])` in `mealie/core/exceptions.py` alongside `ShoppingListIsArchivedError`.

## Requirement coverage summary

| Input requirement | v2 completeness |
|---|---|
| Two nullable columns + migration + rollback | Covered |
| Archive / unarchive endpoints | Covered |
| Default, archived-only, all list query behavior | Row filtering covered; default field omission missing (COMP-V2-C-001) |
| Archive requires all items checked + 409 i18n | Covered, including `None` as unchecked |
| Frozen mutations, including `checked` and downstream list-mutating routes | Covered |
| Multitenant isolation | Covered |
| Event types, exact payload, no leak | Covered |
| Schema fields for archive queries | Covered |
| Default schema compatibility via field omission | Missing |
| Repository/service placement | Covered |
| i18n keys | Covered with documented en-US/Crowdin exception |
| Unit/integration/multitenant tests | Covered |

## Summary

Refine once more before coding. The only blocking completeness gap is the unresolved default-response omission requirement. Everything else from v1 completeness is either fixed or has a documented, acceptable exception.
