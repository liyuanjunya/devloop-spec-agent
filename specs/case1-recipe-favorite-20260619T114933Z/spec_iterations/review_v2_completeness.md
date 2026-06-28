# Completeness Review (v2)

## Verdict: NEEDS_REFINE

Score: **0 critical, 1 high, 3 medium, 2 low**. Do **not** approve yet because v2 still contains a blocking data-model gate for the explicit `user_favorite_recipe` table requirement. Most v1 completeness gaps are fixed: service layer, schema path, i18n, test minimums, cascade cleanup, migration naming, OpenAPI `response_model`/docstrings, and codegen are now represented.

## V1 resolution table

| v1 issue | Status in v2 | Evidence |
|---|---:|---|
| COMP-C-001 i18n absent | ✅ Resolved | FR-006 requires i18n-backed 404s and forbids hardcoded English 4xx messages. |
| COMP-C-002 3-layer pattern absent | ✅ Resolved | FR-002 requires `mealie/services/user_services/` between routes and repos. |
| COMP-C-003 new table vs reuse unresolved | ⚠ Partially resolved | NC-001 makes it a blocking decision, but the recommended/default spec still says not to add the explicitly requested table. |
| COMP-H-001 FK cascade too soft | ✅ Resolved | FR-009 hard-requires FK cascade migration plus user-delete cleanup. |
| COMP-H-002 test counts missing | ✅ Resolved | FR-011 and SC-008 require >=3 unit, >=6 integration, >=2 multitenant tests. |
| COMP-H-003 schema file path missing | ✅ Resolved | FR-003 pins `mealie/schema/user/user_favorites.py`. |
| COMP-H-004 `/self/favorites` response collision undecided | ✅ Resolved | NC-002/FR-004 choose paginated recipes on `/self/favorites` and move old rating summaries. |
| COMP-H-005 migration filename/OpenAPI/codegen missing | ✅ Resolved | FR-012 covers migration naming, docstrings, `response_model`, and codegen. |
| COMP-M-001 cascade P2 | ✅ Resolved | US-6 is P1; FR-009 is hard functional. |
| COMP-M-002 anonymous auth wiring not FR | ✅ Resolved with architecture adjustment | FR-007 covers authenticated `/api/recipes` and anonymous public explore recipe reads. |
| COMP-M-003 `favorite_count` visibility undecided | ⚠ Mostly resolved, still ambiguous | Assumption chooses count for returned recipe; SC-006 says cross-tenant counts must not leak, which can conflict with “public total count.” |
| COMP-M-004 N+1 metric contradictory | ✅ Resolved | SC-004 makes bounded query count required; latency threshold applies only if a benchmark baseline exists. |
| COMP-M-005 multitenant tests undercounted | ✅ Resolved | FR-011 names cross-household favorite visibility and different-group recipe invisibility. |

## Section-by-section coverage against `input.md`

| Input section | Coverage | Notes |
|---|---:|---|
| §1 goal: user-level recipe favorites | ✅ | Summary, US-1..US-3, FR-004. |
| §2 data model | ⚠ | Fields/indexes/cascade are described only behind NC-001 fallback; default remains `users_to_recipes` reuse. |
| §2 API endpoints | ✅ | Requested POST/DELETE/GET self endpoints appear in FR-004; legacy user-id routes are preserved in FR-010. |
| §2 behavior details | ⚠ | Idempotency, visibility 404, and cascade are covered; exact `200 + existing record` response is not pinned. |
| §3 recipe response fields | ✅ | FR-007 adds `favorited` and `favorite_count` to `RecipeSummary`/`Recipe`. |
| §4 implementation constraints | ✅ | 3-layer, migration convention, i18n, schema path, no N+1 all appear. |
| §5 tests | ✅ | FR-011/SC-008 enforce minimum counts and named scenarios. |
| §6 docs | ✅ | FR-012 requires docstrings, `response_model`, OpenAPI/codegen. |

## Endpoint coverage check

The input file explicitly names 5 endpoint shapes: `POST /api/users/self/favorites/{recipe_slug}`, `DELETE /api/users/self/favorites/{recipe_slug}`, `GET /api/users/self/favorites?page=...`, `GET /api/recipes`, and `GET /api/recipes/{slug}`. v2 covers all 5. v2 also covers related Mealie surfaces: public explore recipe list/detail, 3 legacy user-id favorites endpoints, and the moved self rating-summary route. I do not see 12 endpoints in the provided `input.md`; if an external §4 endpoint inventory exists, it should be pasted into the spec or review prompt.

## New / remaining issues

### High

- **COMP-H-006 — Explicit new-table requirement is still not implementation-ready.**  
  Input §1 says “新增 `user_favorite_recipe` 表” with concrete columns and indexes. v2 correctly surfaces the architectural conflict, but NC-001/FR-001 still recommend reusing `users_to_recipes` and put the requested table out of scope unless rejected. That is acceptable as a review gate, but not approvable as a final implementation spec until the gate is resolved in the document. Either record reviewer/product approval for reuse, or rewrite FR-001 to require the new table, migration, backfill, and compatibility plan.

### Medium

- **COMP-M-006 — Idempotent mutation responses do not pin the input’s exact `200 + existing record` behavior.**  
  Input §2 says duplicate POST returns `200 + 已存在记录` and missing DELETE returns `200`. v2 says “successful” and “same successful status,” but does not require status code 200 or define the POST response body/model for the already-existing favorite. Add this to FR-004/FR-005 and the integration tests.

- **COMP-M-007 — Anonymous behavior for the exact `/api/recipes` paths is explained architecturally but not stated as a product deviation.**  
  Input §3 names `GET /api/recipes` and `GET /api/recipes/{slug}` and then says unauthenticated users get `favorited=false`. v2 moves anonymous coverage to `/api/explore/groups/{group_slug}/recipes...`, which is likely correct for Mealie, but the spec should explicitly say `/api/recipes` remains authenticated and public anonymous semantics are satisfied by explore routes.

- **COMP-M-008 — `favorite_count` tenant/public semantics remain slightly inconsistent.**  
  Input says `favorite_count` is public total count. v2 says real count for returned recipes, but SC-006 says cross-tenant favorites must not leak in “list/count state.” Clarify whether count is global for a visible recipe, group-scoped, or household-scoped; then make FR-007, SC-005, and SC-006 use the same rule.

### Low

- **COMP-L-001 — Error format is implied, not mandatory.**  
  FR-006 references `ErrorResponse` examples, but only mandates i18n text. Add “use Mealie’s existing `ErrorResponse`/exception response shape” to prevent ad hoc 404 payloads.

- **COMP-L-002 — i18n file extension differs from input.**  
  Input says `lang/messages/*.yaml`; v2 correctly uses verified `en-US.json`. This is fine, but add a note that Mealie’s actual locale files are JSON so implementers do not search for YAML files.

## Summary

v2 is a strong refinement and resolves nearly all v1 completeness defects. The remaining blocker is not coverage breadth; it is that the explicit new-table requirement is still represented as an unresolved gate with a reuse default. Resolve NC-001 in-spec, pin exact idempotent response semantics, and clarify anonymous-route/count semantics, then the completeness perspective can approve.
