# Feature Specification: Recipe Favorites — Self-Service API

**Feature ID**: `recipe-favorites-self-api`
**Status**: Draft
**Schema version**: 1.0

## Summary
Add a first-class self-service favorites API and recipe response favorite metadata, but **do not create a new `user_favorite_recipe` table**. Mealie already stores favorites in `users_to_recipes` through `UserToRecipe.is_favorite`; this spec chooses the conservative plan: reuse that storage, add missing self POST/DELETE wrappers, define a paginated self favorite recipe-list contract, and compute `favorited` plus `favorite_count` without N+1 queries.

## Existing-code findings (informs all FRs below)
- Mealie already has favorites at `mealie/db/models/users/user_to_recipe.py:17-30` (`UserToRecipe.is_favorite`).
- Existing favorites endpoint: `mealie/routes/users/ratings.py:78-86` POST/DELETE `/{id}/favorites/{slug}`.
- Existing repository: `mealie/repos/repository_users.py:78-102` `RepositoryUserRatings`.
- Frontend already has `RecipeFavoriteBadge.vue` (`frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue:48-64`) + `pages/user/[id]/favorites.vue` (`frontend/app/pages/user/[id]/favorites.vue:30-32`).
- Migration `2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:153-194` consolidated favorites into `users_to_recipes` and dropped the older `users_to_favorites` table.
**Implication for this spec**: `UserToRecipe.is_favorite` remains canonical. A new `user_favorite_recipe` table is explicitly out of scope unless a reviewer rejects the reuse approach and requests a replacement migration.

## User Stories

### US-1 (P1) — Authenticated user favorites a recipe
**Description**: As a signed-in user, I can favorite a recipe visible to my group without knowing or sending my own user id.
**Independent test**: Log in, POST `/api/users/self/favorites/{recipe_slug}` twice, and verify the recipe is favorited once.
**Acceptance**:
1. Given an authenticated user and a visible recipe, When they POST `/api/users/self/favorites/{recipe_slug}`, Then `UserToRecipe.is_favorite` is `true` for that user and recipe.
2. Given the favorite already exists, When they POST the same route again, Then the response is successful and no duplicate association row is created.
3. Given a recipe outside the user's group visibility, When they POST the self favorite route, Then the API returns 404.

### US-2 (P1) — Authenticated user unfavorites a recipe
**Description**: As a signed-in user, I can remove a favorite using a self route.
**Independent test**: Favorite a recipe, DELETE `/api/users/self/favorites/{recipe_slug}` twice, then verify `is_favorite=false` and no error.
**Acceptance**:
1. Given an authenticated user with a favorite, When they DELETE `/api/users/self/favorites/{recipe_slug}`, Then the existing `UserToRecipe` row is updated to `is_favorite=false`.
2. Given no favorite exists, When they DELETE the same route, Then the response is still successful.
3. Given a recipe outside the user's group visibility, When they DELETE the self favorite route, Then the API returns 404.

### US-3 (P1) — User lists their favorites (paginated)
**Description**: As a signed-in user, I can list my favorited recipes with Mealie pagination semantics.
**Independent test**: Favorite multiple recipes and GET `/api/users/self/favorites?page=1&perPage=50`; verify only visible recipes favorited by the current user are returned.
**Acceptance**:
1. Given an authenticated user with favorites, When they GET `/api/users/self/favorites`, Then the API returns a paginated recipe-summary collection.
2. Given pagination query parameters, When the user requests a page, Then `page`, `perPage`, `total`, and `items` follow existing `PaginationQuery` / `PaginationBase` conventions.
3. Given other users have favorites, When the current user lists favorites, Then those recipes are not included unless also favorited by the current user and visible in the current group.
4. Given the current implementation already has `/api/users/self/favorites` returning rating summaries, When implementing this story, Then compatibility must be explicitly resolved: either retain a rating-summary alias and add a documented recipe-list response path, or coordinate the response-model migration with generated clients.

### US-4 (P1) — Recipe list/detail shows `favorited` and `favorite_count`
**Description**: As any recipe reader, I can see how many users favorited each recipe; as an authenticated user, I can also see whether I favorited it.
**Independent test**: Favorite a recipe as user A, fetch recipe list/detail as user A, user B, and anonymous user; compare `favorited` and `favorite_count`.
**Acceptance**:
1. Given an authenticated user who favorited a recipe, When they GET `/api/recipes` or `/api/recipes/{slug}`, Then the recipe has `favorited=true` and `favorite_count>=1`.
2. Given an authenticated user who did not favorite the recipe, When they fetch the same recipe, Then `favorited=false` and `favorite_count` remains populated.
3. Given an unauthenticated request to supported public recipe reads, When a recipe is returned, Then `favorited=false` and `favorite_count` is populated.
4. Given a recipe list with many items, When favorites are hydrated, Then the implementation uses joins, aggregate subqueries, `EXISTS`, or batched lookups rather than one query per recipe.

### US-5 (P2) — Existing favorite endpoints stay operational
**Description**: As an existing frontend/client user, current user-id favorite routes should continue to work while self routes are introduced.
**Independent test**: Exercise both `/api/users/{id}/favorites/{slug}` and `/api/users/self/favorites/{slug}` for the same user and verify they affect the same `UserToRecipe` row.
**Acceptance**:
1. Given an existing client using `/api/users/{id}/favorites/{slug}`, When it adds or removes a favorite for the current user, Then behavior is unchanged.
2. Given a client attempts to mutate another user's favorites through the user-id route, When the ids differ, Then existing permission checks still reject it.
3. Given self routes are used, When they mutate favorites, Then they call the same repository/storage path as legacy routes.

### US-6 (P2) — Favorite data is cleaned with users/recipes
**Description**: As an operator, I should not have orphan favorite rows after recipe or user deletion.
**Independent test**: Favorite a recipe, delete the recipe or user through existing flows, and assert no visible favorite remains.
**Acceptance**:
1. Given a favorited recipe is deleted, When favorite list and recipe count queries run, Then deleted recipes are absent.
2. Given a user is deleted, When repository queries run for remaining users, Then the deleted user's favorites do not affect `favorite_count`.
3. Given existing FK cascade behavior is insufficient, When implementing, Then add the smallest migration needed to enforce cleanup on `users_to_recipes`, not a new favorites table.

## Functional Requirements

- **FR-001** [functional]: Favorite persistence MUST reuse `users_to_recipes` / `UserToRecipe.is_favorite` as the canonical storage; do not add `user_favorite_recipe` in the default implementation.
  - Code references: `mealie/db/models/users/user_to_recipe.py:17-30` `UserToRecipe`; `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:153-194` migration.
  - Related: US-1, US-2, US-6

- **FR-002** [functional]: Add authenticated self write endpoints `POST /api/users/self/favorites/{recipe_slug}` and `DELETE /api/users/self/favorites/{recipe_slug}` that use `self.user.id` and never accept a user id from the caller.
  - Code references: `mealie/routes/users/crud.py:19-40` existing self routes; `mealie/routes/users/ratings.py:78-86` existing favorite write routes; `mealie/routes/users/__init__.py:10-15` router registration.
  - Related: US-1, US-2, US-5

- **FR-003** [functional]: POST favorite MUST be idempotent: create a `UserToRecipe` link if absent, otherwise update the existing row to `is_favorite=true` without duplicate rows.
  - Code references: `mealie/routes/users/ratings.py:54-76` existing create/update logic; `mealie/db/models/users/user_to_recipe.py:17-29` uniqueness and `is_favorite`; `mealie/repos/repository_users.py:98-101` lookup by user and recipe.
  - Related: US-1

- **FR-004** [functional]: DELETE favorite MUST be idempotent: if the user-recipe row exists, set `is_favorite=false`; if the favorite is already absent, return success without creating an error for the idempotent state.
  - Code references: `mealie/routes/users/ratings.py:70-86` existing update/remove flow; `mealie/repos/repository_users.py:98-101` lookup by user and recipe.
  - Related: US-2

- **FR-005** [functional]: Favorite mutation MUST resolve recipes through group-scoped recipe lookup and return 404 for recipes not visible to the current user's group.
  - Code references: `mealie/routes/users/ratings.py:19-42` `group_recipes` and `get_recipe_or_404`; `mealie/routes/recipe/_base.py:37-56` group recipe scoping (if touched, verify before implementation); `mealie/repos/repository_generic.py:104-179` scoped `get_one` behavior (if touched, verify before implementation).
  - Related: US-1, US-2

- **FR-006** [functional]: Define and implement a paginated self favorite recipe-list contract for `/api/users/self/favorites`; because this path currently returns rating summaries, the implementation MUST include an explicit compatibility decision before changing the response model.
  - Code references: `mealie/routes/users/crud.py:38-40` current `/self/favorites` rating-summary route; `mealie/schema/response/pagination.py:32-49` pagination conventions; `frontend/app/lib/api/user/users.ts:58-75` existing frontend client expectations.
  - Related: US-3, US-5

- **FR-007** [functional]: Add `favorited: bool` and `favorite_count: int` to recipe list/detail schemas, defaulting to `false` and `0` when no authenticated user/favorites exist.
  - Code references: `mealie/schema/recipe/recipe.py:116-149` `RecipeSummary`; `mealie/schema/recipe/recipe.py:182-190` `Recipe` inherits summary fields; `mealie/routes/recipe/recipe_crud_routes.py:340-395` list response; `mealie/routes/recipe/recipe_crud_routes.py:415-424` detail response.
  - Related: US-4

- **FR-008** [functional]: Recipe favorite hydration MUST compute current-user `favorited` from `UserToRecipe.user_id + recipe_id + is_favorite` and `favorite_count` from favorite rows for the recipe, counting only visible/group-appropriate data.
  - Code references: `mealie/repos/repository_recipes.py:36-52` `by_user`; `mealie/repos/repository_recipes.py:72-93` existing user-specific rating alias pattern; `mealie/db/models/recipe/recipe.py:68-74` `favorited_by` relationship; `mealie/repos/repository_users.py:82-96` favorite filtering.
  - Related: US-4

- **FR-009** [non_functional]: Recipe list query MUST avoid N+1 when adding `favorited` and `favorite_count`; use joined/aggregate query, correlated `EXISTS`, grouped subquery, or one batched lookup for all page item ids. This is measurable via SC-004.
  - Code references: `mealie/routes/recipe/recipe_crud_routes.py:367-383` list query path; `mealie/schema/recipe/recipe.py:168-175` loader options; `mealie/repos/repository_recipes.py:40-52` column alias extension point.
  - Related: US-4

- **FR-010** [functional]: Existing `/api/users/{id}/favorites/{slug}` and `/api/users/{id}/favorites` behavior MUST remain operational for backward compatibility unless a separate migration task updates the frontend and generated API clients.
  - Code references: `mealie/routes/users/ratings.py:44-86` legacy ratings/favorites routes; `frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue:53-64` existing UI calls; `frontend/app/pages/user/[id]/favorites.vue:30-32` existing favorites page query.
  - Related: US-5

- **FR-011** [functional]: Tests MUST cover repository add/remove/list, self POST/DELETE/list, recipe response fields, anonymous `favorited=false`, cross-group 404, count changes, deletion cleanup, pagination, and multitenant isolation.
  - Code references: `tests/fixtures/fixture_users.py:17-276` user/tenant fixtures; `tests/fixtures/fixture_recipe.py:16-131` recipe fixtures; `tests/multitenant_tests/test_multitenant_cases.py:1-94` isolation pattern; `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:16-240` cross-household recipe behavior.
  - Related: US-1, US-2, US-3, US-4, US-6

## Success Criteria

- **SC-001**: Self favorite POST is idempotent | metric=duplicate POST result | threshold=second POST returns success and row count for `(user_id, recipe_id)` remains 1.
- **SC-002**: Self favorite DELETE is idempotent | metric=duplicate DELETE result | threshold=second DELETE returns success and recipe is not favorited.
- **SC-003**: Self favorite list is paginated | metric=response contract | threshold=`items`, `page`, `perPage`, and `total` match `PaginationBase` for at least 3 favorites across 2 pages.
- **SC-004**: GET /api/recipes p95 latency does NOT regress vs baseline after adding `favorited`/`favorite_count` (no N+1) | metric=p95 latency or query-count test on a seeded page | threshold=≤10% p95 regression or bounded query count independent of page size.
- **SC-005**: Recipe detail/list metadata is correct | metric=response field assertions | threshold=authenticated favoriting user sees `favorited=true`; other/anonymous users see `favorited=false`; all see correct `favorite_count`.
- **SC-006**: Tenant isolation holds | metric=integration/multitenant tests | threshold=cross-group favorite attempts return 404 and cross-tenant favorites do not leak in list/count state.
- **SC-007**: Backward compatibility holds | metric=legacy route regression tests | threshold=existing `/api/users/{id}/favorites/{slug}` add/remove and `/api/users/{id}/favorites` list still pass.

## Key Entities

- **Extended UserToRecipe**: Existing association model in `users_to_recipes`; fields include `user_id`, `recipe_id`, `rating`, `is_favorite`, `id`, `created_at`, and `updated_at`/`update_at`. This is the canonical favorite entity for this spec.
- **Recipe favorite metadata**: Response-only fields on `RecipeSummary` / `Recipe`: `favorited: bool` for the current request user and `favorite_count: int` for the recipe.
- **Self favorite recipe list**: Paginated `RecipeSummary` collection filtered to `UserToRecipe.user_id == current_user.id` and `is_favorite == true` within visible recipe scope.

## Edge Cases

- Idempotent POST of an already-favorited recipe → 200 + existing favorite state, no duplicate row.
- DELETE of a non-favorited recipe → 200 and `favorited=false`.
- Recipe in another group → 404.
- Recipe cascade-deleted → favorites no longer visible/countable; add FK cascade migration only if current constraints do not clean rows.
- User cascade-deleted → the deleted user's favorites no longer count.
- Unauthenticated GET /api/recipes → `favorited=false`, `favorite_count` populated.
- Existing `/api/users/self/favorites` route contract conflict → resolve compatibility before changing generated clients.
- `favorite_count` for private/hidden recipes → count only within the recipe visibility model used by the recipe endpoint.

## Assumptions

- `UserToRecipe.is_favorite` is the canonical storage because Mealie already migrated old favorites into `users_to_recipes`.
- Existing `/api/users/{id}/favorites/{slug}` endpoints will remain operational for backward compatibility.
- The backend API root includes `/api`; route decorators may show paths relative to `/users`.
- Frontend migration is not required in this spec, but backend changes must avoid breaking existing UI favorite badge/page behavior.
- If exact `GET /api/users/self/favorites` paginated recipe-list semantics conflict with existing rating-summary clients, implementers may use a temporary alias or compatibility response only with explicit reviewer approval.

## Out of Scope

- Creating a new `user_favorite_recipe` table in the default plan.
- Frontend changes to switch UI from `/users/{id}/favorites/{slug}` to `/users/self/favorites/...`.
- Manually editing generated TypeScript API types.
- Reworking the ratings feature beyond preserving favorite/rating coexistence in `UserToRecipe`.
- Changing non-English translation files.
- Adding household-level/shared favorites.

## Self-Concerns (writer's own residual uncertainty)

- Conflict over the self list route: current `/api/users/self/favorites` returns rating summaries, while the input asks for paginated recipes. I chose compatibility-first wording; reviewer should decide whether to break/rename/alias.
- Migration semantics for existing `UserToRecipe` FK cascades are uncertain from inspected snippets; implementation should verify actual `ON DELETE` behavior before adding any migration.
- `favorite_count` visibility semantics are not explicit in current code: this spec assumes counts should follow recipe endpoint visibility/group scoping, not global cross-group counts.
- I did not inspect optional-auth/public recipe route variants; unauthenticated `favorited=false` may require `try_get_current_user` wiring where applicable.
