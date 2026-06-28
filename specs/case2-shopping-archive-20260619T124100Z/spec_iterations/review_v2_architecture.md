# Architecture Review v2 — Shopping List Archive

## Verdict: REQUEST_CHANGES

**Decision rule:** APPROVE only with 0 Critical + 0 High. This review finds **1 Critical, 2 High, 1 Medium** new v2 issues.

## v1 issue resolution status

| v1 issue | Status | Evidence |
|---|---|---|
| C1 — Archived-list immutability incomplete; label-settings and recipe routes mutable | PARTIALLY_RESOLVED | v2 now enumerates all 11 routes and adds Group B pre-flight before label/recipe writes (`spec_v2.md:220-242`, `605-608`). However the frozen-route strategy remains incomplete for some item-route requests because Group A relies on repo methods reached after service preprocessing; see NEW-M1. |
| H1 — `archived_by_user_id` FK delete behavior contradictory | RESOLVED | Model and migration both specify `ondelete="SET NULL"`, and invariant is loosened to one-way (`spec_v2.md:151-157`, `164-174`, `600-603`). |
| H2 — Archive/unarchive repository updates are not tenant-scoped | RESOLVED | v2 requires tenant-scoped pre-fetch and tenant-scoped `UPDATE` predicates for archive/unarchive (`spec_v2.md:262-271`, `466-473`). |
| M1 — HTTP/i18n translation placed in service layer | RESOLVED | v2 moves translation to FastAPI exception handling and states service methods remain HTTP-free (`spec_v2.md:403-455`, `649-651`). New handler executability concerns are tracked separately as NEW-H2. |
| M2 — `RepositoryShoppingListItem` dependency underspecified | RESOLVED | v2 chooses single constructor-injection wiring for `parent_repo: RepositoryShoppingList` (`spec_v2.md:299-333`). |

## New v2 findings

### NEW-C1 — Item repository guard preserves a cross-tenant write primitive
- **Severity:** Critical
- **Spec refs:** `spec_v2.md:280-282`, `309-318`, `466-470`, `541`
- **Code refs:** `mealie/repos/repository_generic.py:195-208`, `228-244`, `271-287`; `mealie/db/models/household/shopping_list.py:56-60`
- **Issue:** FR-8 says cross-household parent IDs are silently filtered by `get_archived_ids` and treated as “not archived” because mutations “would 404 elsewhere”. That assumption is false: generic `create_many`, `update_many`, and `delete_many` do not apply `_filter_builder`; they insert/update/delete by supplied IDs. A caller can create an item in another household's list, or update/delete another household's item, after the archive guard returns an empty set.
- **Required fix:** In `RepositoryShoppingListItem`, validate parent-list visibility for create payloads and current-row visibility for update/delete via tenant-scoped joins before any write. Invisible rows must raise `NoEntryFound`/404. Do not delegate to unscoped generic bulk writes unless the visible row set exactly matches the requested row set.

### NEW-H1 — `ArchiveTransitionResult` is owned by the service layer but returned by the repo layer
- **Severity:** High
- **Spec refs:** `spec_v2.md:262-271`, `284-286`, `406-423`
- **Issue:** `RepositoryShoppingList.archive/unarchive` are specified to return `ArchiveTransitionResult`, but the type is declared in `mealie/services/household_services/shopping_lists.py`. That forces repository code to import a service type, creating a reversed layer dependency and likely circular imports because the service already depends on repositories.
- **Required fix:** Move the transition DTO to a repository/domain-neutral module, declare it beside `RepositoryShoppingList`, or have repos return `(ShoppingListOut, transitioned)` and let the service wrap it.

### NEW-H2 — Global exception handler is not executable as specified and returns the wrong envelope
- **Severity:** High
- **Spec refs:** `spec_v2.md:430-453`, `536-538`
- **Code refs:** `mealie/lang/providers.py:43-46`, `mealie/middleware/locale_context.py:13-16`, `mealie/schema/response/responses.py:13-19`
- **Issue:** The handler calls `get_locale_provider(request)`, but `get_locale_provider` expects an `accept_language` string/Header value, not a `Request`. Also, the handler returns `ErrorResponse.respond(...)` as the top-level JSON body, while SC-1/SC-2 assert `response.json()["detail"]["message"]`, the existing `HTTPException` envelope.
- **Required fix:** Obtain the translator from `request.headers.get("accept-language")` or `get_locale_context()`, and either return `{"detail": ErrorResponse.respond(...)}` or update all response contracts/tests to the top-level `ErrorResponse` shape.

### NEW-M1 — Group A frozen-route guard can be bypassed by service no-op preprocessing
- **Severity:** Medium
- **Spec refs:** `spec_v2.md:223-232`, `309-318`, `536-537`
- **Code refs:** `mealie/services/household_services/shopping_lists.py:203-216`; `mealie/schema/household/group_shopping_list.py:61-80`
- **Issue:** FR-6 promises every item-mutating route targeting an archived list returns 409. But `bulk_create_items` can discard a create request before calling `self.list_items.create_many` (e.g., negative quantity with no merge), so the repo-layer guard may never run and the route can return success instead of 409.
- **Required fix:** Add a service/controller pre-flight for all Group A item routes, or make service methods validate target list archived state before any consolidation/no-op filtering.

## Checklist

- 3-layer routes/services/repos: **Partial** — service HTTP concerns fixed, but repo return type depends on service DTO.
- Centralized archive filter in repo layer: **Partial** — archive/unarchive scoped; item bulk writes remain unsafe.
- Frozen-state guard placement: **Partial** — Group B fixed; Group A relies on late repo calls.
- Event bus payload tenant leak: **Pass** for archive/unarchive payload design.
- Migration backward compatibility: **Pass** for nullable fields and FK `SET NULL`.
- Multitenant scoping: **Fail** — item repository bulk operations can cross tenant boundaries.
