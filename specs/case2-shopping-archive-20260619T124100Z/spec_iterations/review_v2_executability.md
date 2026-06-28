# Executability Review v2 — Case-2 Shopping List Archive

## Verdict

**Needs revision before implementation.** v2 fixes the v1 filename/path problems and resolves several prior ambiguities, but it still contains executable blockers around item-route tenancy, exception response shape, translator usage, repository/service type ownership, and concurrency semantics.

## Checks performed

- Opened `spec_v2.md`, `spec_v2.json`, `review_v1_executability.md`, and `rewrite_v1_to_v2.md`.
- Extracted and existence-checked concrete Mealie references against `C:\Users\v-liyuanjun\Downloads\mealie`.
- Opened key cited line ranges directly in Mealie source.
- Compared FR `code_references` in markdown vs JSON.
- Searched for residual `TBD`, `or equivalent`, `if needed`, `may need`, and related ambiguity markers.

## v1 executability fixes verified

- FR-2 now cites the real truncated migration filename `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_.py:183`, and line 183 contains the `NaiveDateTime` `last_made` column.
- FR-3 now cites the real truncated migration filename `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py:1-51`; the file exists and contains the notifier-option add/drop template.
- FR-10 now includes `mealie/services/event_bus_service/event_bus_service.py:54-64`, which is the listener/subscriber construction path, plus `66-96` for dispatch fan-out.
- FR-8 removed the normative “or equivalent reference” and now chooses constructor injection.
- SC-2 title now says 11 frozen route variants.

## Blocking executability findings

### 1. Item mutation tenancy is still not executable for SC-6 / FR-12

FR-8 guards `create_many` by checking `shopping_list_id` from the request payload (`spec_v2.md:309-313`) and FR-7 says cross-household IDs are “silently filtered out and treated as not archived” in `get_archived_ids` (`spec_v2.md:280-282`). That does **not** produce the SC-6 required `POST /shopping/items` cross-household 404 (`spec_v2.md:541`). Existing `RepositoryGeneric.create_many` simply inserts supplied rows (`repository_generic.py:195-208`) and does not tenant-check parent `shopping_list_id`. Existing `update_many` fetches only by item ids (`repository_generic.py:228-244`) and does not apply `_filter_builder`.

**Required revision:** `RepositoryShoppingListItem` must first verify target parent/target rows are visible in the current household and return/raise 404 for invisible list/item ids. For update/delete, derive parent list ids from scoped DB rows, not trusted request bodies.

### 2. 409 response envelope contradicts success criteria

FR-11’s global handler returns `JSONResponse(content=ErrorResponse.respond(...))` (`spec_v2.md:436-451`), which produces a top-level `{"message": ..., "error": ...}` because `ErrorResponse.respond` returns a dict (`responses.py:13-19`). SC-1 and SC-2 assert `response.json()["detail"]["message"]` (`spec_v2.md:536-537`), which matches existing `HTTPException(detail=ErrorResponse.respond(...))` behavior (`mixins.py:56-64`), not the proposed global handler.

**Required revision:** choose one envelope. Either make the handler return `content={"detail": ErrorResponse.respond(...)}` or change SC-1/SC-2 to assert top-level `message`.

### 3. Global handler translator sample passes the wrong object

The sample handler calls `get_locale_provider(request)` (`spec_v2.md:439,447`). The real signature is `get_locale_provider(accept_language: str | None = Header(None))` (`providers.py:43-46`); middleware passes `request.headers.get("accept-language")` (`locale_context.py:13-16`). Passing a `Request` object is not an executable translation lookup.

**Required revision:** use `request.headers.get("accept-language")`, or use the request locale context explicitly.

### 4. `ArchiveTransitionResult` location creates a circular ownership problem

FR-7 requires repository methods to return/construct `ArchiveTransitionResult` (`spec_v2.md:262-271`), but FR-11 declares that type in `shopping_lists.py` (`spec_v2.md:406-411`). `shopping_lists.py` imports `AllRepositories` from `repository_factory.py` (`shopping_lists.py:6-7`), and `repository_factory.py` imports `RepositoryShoppingList` (`repository_factory.py:82`). If `repository_shopping_list.py` imports `ArchiveTransitionResult` from the service to instantiate it, a circular import is likely.

**Required revision:** define `ArchiveTransitionResult` in a neutral module (schema/repo helper) or in `repository_shopping_list.py` and import it into the service, not the reverse.

### 5. EC-7 concurrency guarantee is not enforced by FR-7 SQL

EC-7 expects one concurrent archive request to succeed and the other to return 409 (`spec_v2.md:595-598`). FR-7’s UPDATE predicate does not include `archived_at IS NULL` and does not require checking `rowcount` (`spec_v2.md:263-266`). Two transactions can both pre-fetch an active row, both update, and the later one can overwrite `archived_by_user_id`.

**Required revision:** make the UPDATE conditional on `ShoppingList.archived_at.is_(None)` and translate `rowcount == 0` after a re-check into `ShoppingListIsArchivedError`.

### 6. SC-8 test construction uses a Protocol as if it were concrete

SC-8 says a unit test asserts `Translator(locale="en-US").t(...)` (`spec_v2.md:543`). `Translator` is a `Protocol` with abstract `t` (`providers.py:16-19`), not a concrete class. The executable construction is `get_locale_provider("en-US")` (`providers.py:43-46`).

## Wrong/imprecise citations

1. **FR-13 repository-policy citation is not synchronized and lacks a real line range.** Markdown cites `Downloads/mealie/.github/copilot-instructions.md` (`spec_v2.md:503`); JSON cites `.github/copilot-instructions.md:n/a (root)`. The strict verified citation should be `.github/copilot-instructions.md:144-146` (line 146 contains the en-US-only locale policy).
2. **FR-11 app-registration citation is imprecise.** `spec_v2.md:453` says the registration site is “wherever `register_debug_handler` is currently invoked — verified at `handlers.py:18`”. `handlers.py:18` is the function definition; the invocation is `mealie/app.py:121`.
3. **FR-8 still contains an `if needed` implementation gap.** The delete-many parent-list discovery says “scoped to current tenant via JOIN on `shopping_lists` if needed” (`spec_v2.md:316`). For executability and SC-6, the join is needed and should be mandatory with exact 404 behavior.
4. **FR-13 markdown vs JSON `code_references` differ.** All other FR code-reference arrays match, but FR-13 differs on the policy file path/range.

## Planned-new vs existing paths

The following are expected new files/tests and are not current path failures: `mealie/repos/repository_shopping_list_item.py`, `tests/multitenant_tests/case_shopping_list_archive.py`, and `tests/multitenant_tests/test_shopping_list_archive_household.py`.

The EC-4 mention of missing `mealie/services/household_services/cookbook_service.py` is intentional negative evidence, not a required existing source file.

## Recommendation

Revise v2 before handing it to a coding agent. The most important fix is to make `RepositoryShoppingListItem` enforce parent-list visibility for create/update/delete; otherwise the stated multitenant acceptance tests cannot be made true by following the spec as written.
