# Feature Specification: Recipe Favorites — Self-Service API

**Feature ID**: `recipe-favorites-self-api`  
**Status**: Draft v2 — needs blocking decisions recorded  
**Schema version**: 1.0  
**Iterations**: 2

## Summary
Add self-service favorite APIs and recipe favorite metadata while resolving v1 review blockers. Recommended defaults reuse Mealie's existing `users_to_recipes` / `UserToRecipe.is_favorite` storage, make `GET /api/users/self/favorites` a paginated recipe-summary list, move the old self favorites rating-summary contract to a ratings-namespaced route, add a user-services layer, enforce i18n 404s, hydrate authenticated and public recipe reads without N+1, and harden `users_to_recipes` cleanup with both user-delete code and FK cascade migration work.

## NEEDS_CLARIFICATION (blocking decisions)
- **NC-001 — Data model: new `user_favorite_recipe` table vs reuse `users_to_recipes` / `UserToRecipe.is_favorite`**
  - Recommended default: reuse `UserToRecipe.is_favorite` because current code and the 2024 migration already consolidated favorites there; do not add `user_favorite_recipe` unless a reviewer explicitly rejects reuse before coding.
  - If rejected: implement a new table with `user_id`/`recipe_id` FKs, `created_at`, unique `(user_id, recipe_id)`, `user_id` index, backfill from existing `is_favorite` rows, and compatibility reads/writes.
- **NC-002 — Route compatibility: keep old `GET /api/users/self/favorites` rating summaries vs migrate it to a ratings-namespaced route**
  - Recommended default: make `/api/users/self/favorites` the requested paginated recipe-summary list and move old rating-summary behavior to `/api/users/self/ratings/favorites` (or equivalent). The verified blast radius is the backend parametrized ratings test plus route constants, not a frontend UI path.
  - If rejected: use a new recipe-list path and update US-3/FR-004/SC-003 consistently before coding; do not leave dual meanings on the same route.

## Existing-code findings (informs all FRs below)
- Mealie already stores favorites in `users_to_recipes` via `UserToRecipe.is_favorite`.
- Existing favorite write routes are `/api/users/{id}/favorites/{slug}`; requested self write routes should share the same storage/service path.
- Current `/api/users/self/favorites` returns `UserRatings[UserRatingSummary]`, but the confirmed live caller is a backend test path; v2 recommends repurposing this path for paginated recipes and moving the old contract under `/self/ratings`.
- Authenticated `/api/recipes` is gated by `UserAPIRouter` / `BaseUserController`; anonymous public recipe reads live under `PublicRecipesController` at `/api/explore/groups/{group_slug}/recipes`.
- `RepositoryRecipes.column_aliases` is used for queryFilter/orderBy, not SELECT projection; favorite response fields need real model/schema hydration or batched assignment.
- Recipe deletion already removes `UserToRecipe` rows; user deletion does not, and existing `users_to_recipes` FKs have no `ondelete` cascade.

## User Stories

### US-1 (P1) — Authenticated user favorites a recipe
**Description**: As a signed-in user, I can favorite a recipe visible to my group without knowing or sending my own user id.  
**Independent test**: Log in, POST `/api/users/self/favorites/{recipe_slug}` twice, and verify exactly one canonical favorite row/state exists.  
**Acceptance**:
1. Given an authenticated user and a visible recipe, When they POST `/api/users/self/favorites/{recipe_slug}`, Then the service sets canonical favorite state to true for that user and recipe.
2. Given the favorite already exists, When they POST the same route again sequentially, Then the response is successful and no duplicate association row is created.
3. Given a recipe outside the user's group visibility, When they POST the self favorite route, Then the API returns an i18n-backed 404.

### US-2 (P1) — Authenticated user unfavorites a recipe
**Description**: As a signed-in user, I can remove a favorite using a self route.  
**Independent test**: Favorite a recipe, DELETE `/api/users/self/favorites/{recipe_slug}` twice, then verify the canonical favorite state is false and no error is returned.  
**Acceptance**:
1. Given an authenticated user with a favorite, When they DELETE `/api/users/self/favorites/{recipe_slug}`, Then the service sets `is_favorite=false` without deleting or corrupting an existing rating.
2. Given no favorite exists, When they DELETE the same route, Then the response is still successful.
3. Given a recipe outside the user's group visibility, When they DELETE the self favorite route, Then the API returns an i18n-backed 404.

### US-3 (P1) — User lists their favorites as recipes (paginated)
**Description**: As a signed-in user, I can list my favorited recipes with Mealie pagination semantics.  
**Independent test**: Favorite multiple recipes and GET `/api/users/self/favorites?page=1&perPage=50`; verify a `PaginationBase[RecipeSummary]` body containing only current-user visible favorites.  
**Acceptance**:
1. Given an authenticated user with favorites, When they GET `/api/users/self/favorites`, Then the API returns a paginated recipe-summary collection, not rating summaries.
2. Given pagination query parameters, When the user requests a page, Then `page`, `perPage`, `total`, `totalPages`, `next`, `previous`, and `items` follow `PaginationQuery` / `PaginationBase` conventions.
3. Given other users have favorites, When the current user lists favorites, Then those recipes are not included unless also favorited by the current user and visible in the current group.
4. Given the old `/api/users/self/favorites` rating-summary route exists, When this feature is implemented, Then that old rating-summary contract is renamed to a ratings-namespaced route and the backend test caller is updated.

### US-4 (P1) — Recipe list/detail shows `favorited` and `favorite_count`
**Description**: As any recipe reader, I can see how many users favorited each returned recipe; authenticated users also see whether they favorited it.  
**Independent test**: Favorite a recipe as user A, fetch authenticated recipe list/detail as user A and user B, then fetch public explore list/detail anonymously; compare `favorited` and `favorite_count`.  
**Acceptance**:
1. Given an authenticated user who favorited a recipe, When they GET `/api/recipes` or `/api/recipes/{slug}`, Then the recipe has `favorited=true` and `favorite_count>=1`.
2. Given an authenticated user who did not favorite the recipe, When they fetch the same recipe, Then `favorited=false` and `favorite_count` remains the real count.
3. Given an unauthenticated request to `/api/explore/groups/{group_slug}/recipes` or `/api/explore/groups/{group_slug}/recipes/{recipe_slug}`, When a public recipe is returned, Then `favorited=false` and `favorite_count` is the real count, not forced to 0.
4. Given a recipe list with many items, When favorites are hydrated, Then the implementation uses a SELECT/loader-compatible or batched aggregate strategy rather than one query per recipe.

### US-5 (P2) — Existing favorite endpoints stay operational
**Description**: Existing user-id favorite routes continue to work while self routes are introduced.  
**Independent test**: Exercise both `/api/users/{id}/favorites/{slug}` and `/api/users/self/favorites/{recipe_slug}` for the same user and verify they affect the same canonical favorite state.  
**Acceptance**:
1. Given an existing client using `/api/users/{id}/favorites/{slug}`, When it adds or removes a favorite for the current user, Then behavior is unchanged.
2. Given a client attempts to mutate another user's favorites through the user-id route, When the ids differ, Then existing permission checks still reject it.
3. Given self routes are used, When they mutate favorites, Then they call the same service/repository/storage path as legacy routes.

### US-6 (P1) — Favorite data is cleaned with users and recipes
**Description**: As an operator, I should not have orphan favorite rows after recipe or user deletion.  
**Independent test**: Favorite a recipe, delete the recipe, assert rows/counts are clean; repeat by deleting a user with favorites.  
**Acceptance**:
1. Given a favorited recipe is deleted, When `RepositoryRecipes._delete_recipe` runs, Then `UserToRecipe` rows for that recipe are removed and counts/lists ignore the deleted recipe.
2. Given a user with favorites is deleted, When `RepositoryUsers.delete` runs, Then `UserToRecipe` rows for that user are removed before deleting the user.
3. Given database FK constraints are updated, When a parent user or recipe row is deleted by supported DB paths, Then `users_to_recipes` rows are removed by `ON DELETE CASCADE` or an equivalent migration-supported constraint.

## Functional Requirements

- **FR-001** [functional]: Stage-0 data-model decision MUST be recorded before coding. Recommended default: reuse existing `users_to_recipes` / `UserToRecipe.is_favorite` as canonical favorite storage and do not add `user_favorite_recipe`. If reviewers reject reuse, create the requested table and include backfill/dual-read compatibility from `UserToRecipe.is_favorite`.
  - Code references:
    - `mealie/db/models/users/user_to_recipe.py:17-30` — `UserToRecipe`, `is_favorite`, `UniqueConstraint`, `user_id` index, `recipe_id` index
    - `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:153-194` — migration creates `users_to_recipes`, drops `users_to_favorites`
  - Related: US-1, US-2, US-6

- **FR-002** [functional]: Favorite business logic MUST live behind a service in `mealie/services/user_services/` (for example `user_favorites_service.py`) instead of adding new cross-cutting logic directly in route handlers. The service MUST coordinate group-scoped recipe lookup, idempotent favorite writes, favorite list pagination, and cleanup calls through repositories. A deliberately thin pass-through service is acceptable only if explicitly named and tested.
  - Code references:
    - `mealie/services/user_services/user_service.py:8-14` — existing `UserService` pattern
    - `mealie/routes/users/ratings.py:17-23,54-86` — current route-direct favorite pattern to wrap/delegate
    - `mealie/repos/repository_factory.py:183-188` — `users` and `user_ratings` repositories
  - Related: US-1, US-2, US-3

- **FR-003** [functional]: Add Pydantic schemas for the self favorites API in `mealie/schema/user/user_favorites.py`. The GET recipe-list contract MUST be a paginated `RecipeSummary` response using existing `PaginationQuery` / `PaginationBase` field names; generated schema exports and TypeScript types MUST be regenerated rather than manually edited.
  - Code references:
    - `mealie/schema/response/pagination.py:46-58` — `PaginationQuery`, `PaginationBase`
    - `mealie/schema/recipe/recipe.py:116-149,168-175,182-190` — `RecipeSummary`, loader options, `Recipe`
  - Related: US-3

- **FR-004** [functional]: Implement authenticated self endpoints: `POST /api/users/self/favorites/{recipe_slug}`, `DELETE /api/users/self/favorites/{recipe_slug}`, and `GET /api/users/self/favorites?page=...` returning `PaginationBase[RecipeSummary]`. Resolve the existing rating-summary collision by moving old `GET /api/users/self/favorites` rating summaries to `/api/users/self/ratings/favorites` (or equivalent ratings-namespaced path) and updating the single backend parametrized test caller; do not keep `/self/favorites` as a rating-summary alias.
  - Code references:
    - `mealie/routes/users/crud.py:23-40` — current self ratings/favorites routes
    - `mealie/routes/users/ratings.py:78-86` — legacy add/remove favorites
    - `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:55-70` — self route test caller
    - `tests/utils/api_routes/__init__.py:190-193` — self route constants
    - `frontend/app/lib/api/user/users.ts:25-40,58-75` — frontend route/client blast-radius evidence
  - Related: US-1, US-2, US-3, US-5

- **FR-005** [functional]: POST favorite MUST be idempotent and sequential duplicate-safe: create `UserToRecipe` if absent, otherwise update `is_favorite=true` without changing an existing rating. DELETE favorite MUST be idempotent: if a row exists, set `is_favorite=false`; if already absent or false, return the same successful status as the legacy route. New self write routes SHOULD delegate to the same service/repository path as legacy favorites so `assert_user_change_allowed`, rating preservation, and visibility rules remain consistent.
  - Code references:
    - `mealie/routes/users/ratings.py:54-86` — `set_rating`, `add_favorite`, `remove_favorite`
    - `mealie/repos/repository_users.py:78-101` — `RepositoryUserRatings` lookups
    - `mealie/db/models/users/user_to_recipe.py:17-30` — unique favorite/rating association
  - Related: US-1, US-2

- **FR-006** [functional]: Favorite mutation and recipe detail/list 404s MUST use Mealie i18n, not hardcoded English. The required semantic no-entry key is `errors.no-entry-found`: implementation MUST either add that alias to `en-US` and call `self.t("errors.no-entry-found")`, or obtain reviewer approval to use the verified existing key `self.t("exceptions.no-entry-found")`. Do not introduce new hardcoded English 4xx response messages in this feature.
  - Code references:
    - `mealie/lang/messages/en-US.json:45-52` — verified `exceptions.no-entry-found`
    - `mealie/routes/users/ratings.py:23-42` — current hardcoded `"Not found."` 404 to replace
    - `mealie/routes/users/crud.py:27-36,42-63` — existing `ErrorResponse.respond` / `self.t` examples
    - `mealie/services/recipe/recipe_service.py:63-68` — service raises no-entry-found style exception
  - Related: US-1, US-2, US-4

- **FR-007** [functional]: Add `favorited: bool` and `favorite_count: int` to `RecipeSummary` and therefore `Recipe`. For authenticated recipe reads, `favorited` reflects the current user's `is_favorite` row and `favorite_count` is the real count of `is_favorite=true` rows for each returned recipe. For anonymous public explore reads, `favorited` MUST be false but `favorite_count` MUST still be the real count; `favorite_count` defaults to 0 only when no favorite rows exist. Implement both authenticated `/api/recipes` routes and anonymous `/api/explore/groups/{group_slug}/recipes` routes.
  - Code references:
    - `mealie/schema/recipe/recipe.py:116-149,182-190` — `RecipeSummary`, `Recipe`
    - `mealie/routes/recipe/recipe_crud_routes.py:85-89,340-395,415-424` — authenticated recipe controller/list/detail
    - `mealie/routes/explore/controller_public_recipes.py:20-41,67-92,114-125` — public anonymous recipe controller/list/detail
    - `mealie/routes/explore/__init__.py:11-22` — explore route mount
    - `mealie/routes/_base/routers.py:20-24` — `UserAPIRouter` auth dependency
    - `mealie/routes/_base/base_controllers.py:139-142` — `BaseUserController` current user dependency
  - Related: US-4

- **FR-008** [non_functional]: Recipe favorite hydration MUST avoid N+1 and MUST NOT use `RepositoryRecipes.column_aliases` as a response projection mechanism. Use an actual SELECT/loader-compatible strategy: either add SQLAlchemy `column_property` / `hybrid_property` fields that Pydantic can read, or perform one batched lookup/aggregate keyed by current page/detail recipe ids and assign `favorited` / `favorite_count` before serialization. `column_aliases` may remain only for queryFilter/orderBy support.
  - Code references:
    - `mealie/repos/repository_generic.py:330-355,367-370,407-415` — `page_all` projection, queryFilter, orderBy use of `column_aliases`
    - `mealie/repos/repository_recipes.py:36-52,72-93` — `column_aliases`, `by_user`, rating alias precedent
    - `mealie/routes/recipe/recipe_crud_routes.py:367-395,415-424` — authenticated list/detail serialization paths
    - `mealie/routes/explore/controller_public_recipes.py:67-92,114-125` — public list/detail serialization paths
    - `mealie/db/models/recipe/recipe.py:68-74` — `favorited_by` relationship
    - `mealie/repos/repository_users.py:82-96` — existing favorite/rating lookup helpers
  - Related: US-4

- **FR-009** [functional]: Add a hard cleanup remedy for `users_to_recipes`. First, add an Alembic migration that enforces `ON DELETE CASCADE` (or DB-equivalent recreated constraints for supported databases) on both `users_to_recipes.user_id` and `users_to_recipes.recipe_id`. Second, extend `RepositoryUsers.delete` to remove `UserToRecipe` rows for the deleted user before `super().delete()`, mirroring the existing recipe-delete cleanup path. Preserve existing `RepositoryRecipes._delete_recipe` cleanup and add regression tests for both user deletion and recipe deletion.
  - Code references:
    - `mealie/db/models/users/user_to_recipe.py:22-24` — FKs have no `ondelete`
    - `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:164-179` — existing constraints/indexes
    - `mealie/repos/repository_recipes.py:110-128` — recipe-delete cleanup
    - `mealie/repos/repository_users.py:55-65` — user delete lacks cleanup
    - `mealie/db/models/users/users.py:84-115` — cascade relationship not applied to favorites
    - `mealie/db/models/recipe/recipe.py:68-74` — favorite relationship lacks cascade
  - Related: US-6

- **FR-010** [functional]: Legacy user-id favorite routes MUST remain operational and backed by the same storage/service path: `GET /api/users/{id}/favorites`, `POST /api/users/{id}/favorites/{slug}`, and `DELETE /api/users/{id}/favorites/{slug}`. Existing frontend favorite badge and user favorites page behavior MUST not be broken; backend-only scope may update tests/routes but MUST NOT manually edit generated frontend types.
  - Code references:
    - `mealie/routes/users/ratings.py:44-86` — legacy ratings/favorites routes
    - `frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue:48-65` — favorite UI calls
    - `frontend/app/pages/user/[id]/favorites.vue:30-32` — favorites page query
    - `frontend/app/lib/api/user/users.ts:50-64` — existing client favorite methods
  - Related: US-5

- **FR-011** [functional]: Tests MUST meet input minimums: at least 3 unit tests for repository/service add, remove, and list behavior; at least 6 integration tests covering favorite/unfavorite/refavorite idempotency, anonymous public reads with `favorited=false` and real `favorite_count`, cross-group 404, count increments, user and recipe deletion cleanup, and pagination; and at least 2 multitenant tests covering cross-household favorite visibility and different-group recipe invisibility.
  - Code references:
    - `tests/fixtures/fixture_users.py:17-106` — user/household fixtures
    - `tests/fixtures/fixture_recipe.py:31-85` — recipe fixtures
    - `tests/multitenant_tests/test_multitenant_cases.py:22-74` — multitenant test pattern
    - `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:45-70` — cross-household recipe test pattern
    - `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:55-70` — existing favorites test pattern
  - Related: US-1, US-2, US-3, US-4, US-6

- **FR-012** [non_functional]: Migration and API documentation work MUST follow Mealie conventions: create migrations with the `YYYY-MM-DD-HH.MM.SS_<revision>_<snake_case_desc>.py` naming pattern, include complete FastAPI docstrings and `response_model` annotations for all new/changed endpoints, and run code generation after Pydantic schema changes. Only `en-US` translation files may be changed for new strings.
  - Code references:
    - `mealie/alembic/versions/2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py:1-23` — migration naming/header convention
    - `mealie/routes/users/ratings.py:44-86` — endpoint docstring / response_model examples
    - `mealie/routes/explore/controller_public_recipes.py:30-41,114-115` — response_model examples
    - `mealie/lang/messages/en-US.json:1-3,45-52` — locale file to update if adding strings
  - Related: US-3, US-4, US-6

## Success Criteria
- **SC-001**: Self favorite POST is idempotent | metric=sequential duplicate POST result | threshold=second POST returns success and canonical row/state remains unique for `(user_id, recipe_id)`.
- **SC-002**: Self favorite DELETE is idempotent | metric=sequential duplicate DELETE result | threshold=second DELETE returns success and recipe is not favorited.
- **SC-003**: Self favorite list is paginated recipes | metric=response contract at `/api/users/self/favorites` | threshold=`PaginationBase[RecipeSummary]` fields match for at least 3 favorites across 2 pages.
- **SC-004**: Recipe list hydration has no N+1 | metric=query count on seeded pages | threshold=bounded query count independent of page size; p95 latency must not regress by more than 10% if a benchmark baseline exists.
- **SC-005**: Recipe favorite metadata is correct | metric=response field assertions | threshold=favoriting user sees `favorited=true`; other/anonymous users see `favorited=false`; all see correct `favorite_count`.
- **SC-006**: Tenant isolation holds | metric=integration/multitenant tests | threshold=cross-group attempts return i18n-backed 404 and cross-tenant favorites do not leak in list/count state.
- **SC-007**: Cleanup is enforced | metric=user-delete and recipe-delete regression tests plus migration inspection | threshold=`users_to_recipes` rows are cleaned for both user and recipe deletion.
- **SC-008**: Input test minimums met | metric=test count by category | threshold=>=3 unit, >=6 integration, >=2 multitenant tests.

## Key Entities
- **Canonical favorite state**: Recommended default uses existing `users_to_recipes` / `UserToRecipe.is_favorite`; if NC-001 is rejected, a replacement `user_favorite_recipe` table must be specified before coding. Fields: `user_id`, `recipe_id`, `is_favorite`, `rating`, `created_at`, `updated_at/update_at`.
- **Self favorite recipe list**: `GET /api/users/self/favorites` returns `PaginationBase[RecipeSummary]` for the current user's visible favorited recipes. Fields: `items`, `page`, `perPage`, `total`, `totalPages`, `next`, `previous`.
- **Recipe favorite metadata**: Response-only fields added to `RecipeSummary` and `Recipe` for current-user favorite state and aggregate favorite count. Fields: `favorited`, `favorite_count`.
- **User favorites service**: Service in `mealie/services/user_services/` that owns favorite write/list business logic and coordinates repositories. Methods: `favorite_recipe`, `unfavorite_recipe`, `list_favorite_recipes`, `cleanup_user_favorites`.

## Edge Cases
- Idempotent POST of an already-favorited recipe → Return success and keep exactly one canonical favorite state for the user/recipe.
- DELETE of a non-favorited recipe → Return success and leave/ensure `favorited=false` without deleting an unrelated rating.
- Recipe in another group → Return an i18n-backed 404 using group-scoped recipe lookup.
- Anonymous public recipe read → Return `favorited=false` and the real `favorite_count` for the returned public recipe.
- Favorite count for private/hidden recipes → Only count for recipes returned by the endpoint's visibility model; anonymous callers only see public explore recipes.
- Recipe deletion → Preserve `RepositoryRecipes._delete_recipe` cleanup and verify counts/lists are clean.
- User deletion → Delete `UserToRecipe` rows in `RepositoryUsers.delete` and add FK cascade migration coverage.
- Data-model decision rejected → Do not code until the spec is revised with the new table/backfill/compatibility plan.

## Assumptions
- Recommended default is to reuse `UserToRecipe.is_favorite` because current code and migration history already make it canonical.
- Backend API root includes `/api`; route decorators may show paths relative to `/users` or `/explore/groups/{group_slug}`.
- The recipe-list contract for `GET /api/users/self/favorites` is intentional in v2; the old rating-summary contract should be moved, not aliased on the same path.
- `favorite_count` is aggregate state for the returned recipe; anonymous public reads receive the real count for public recipes, not a user-specific or forced-zero value.
- Frontend implementation changes are out of scope, but generated types/routes may need regeneration after backend schema changes; generated files must not be edited manually.

## Out of Scope
- Implementing a new `user_favorite_recipe` table unless NC-001 is rejected before coding.
- Frontend UI migration beyond preserving existing backend behavior and regenerating generated types if schemas change.
- Manually editing generated TypeScript types.
- Reworking ratings beyond moving the old self favorites rating-summary route out of the `/self/favorites` path.
- Changing non-English translation files.
- Adding household-level/shared favorites.

## Self-Concerns (writer's own residual uncertainty)
- **NC-001/FR-001**: Original input explicitly requested a new `user_favorite_recipe` table; v2 recommends reuse but makes that a blocking reviewer gate. Evidence gap: product/reviewer must accept storage reuse before implementation skips the requested new table.
- **FR-006**: Review text requested `t('errors.no-entry-found')`, but verified `en-US.json` contains `exceptions.no-entry-found`. Evidence gap: if reviewers require the exact `errors.*` namespace, add that key explicitly before coding; otherwise use existing `exceptions.no-entry-found`.
- **FR-008**: The exact hydration implementation (`column_property` vs batched assignment) is left to implementer design. Evidence gap: both satisfy the no-N+1/projection requirement; coding should pick the smallest change that keeps JSON serialization correct.

