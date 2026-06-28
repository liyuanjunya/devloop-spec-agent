# Feature Specification: Recipe Favorites — Self-Service API (new pipeline)

**Feature ID**: `recipe-favorites-self-api`
**Schema version**: 1.0

## Summary

Mealie case-1 (recipe favorites) re-run under the NEW DevLoop pipeline. Goal: add authenticated self favorite routes and `favorited`/`favorite_count` fields on recipe responses while respecting the existing Mealie favorite storage on `UserToRecipe.is_favorite`. Three input-vs-code conflicts are surfaced as `needs_clarification` blocking decisions (storage model, self-favorites response contract, count visibility) so a human reviewer fixes them before coding. Functional requirements pin the concrete decisions: reuse the existing `users_to_recipes` table per NC-001, add a parallel `/api/users/self/favorites/recipes` endpoint per NC-002, count favorites globally bounded by recipe visibility per NC-003, hydrate the recipe response without N+1, add the missing FK cascade migration, mirror the deletion-cleanup path for users, keep all 4xx errors flowing through `self.t(...)` i18n, follow the three-layer routes/services/repos pattern, place new Pydantic schemas at `mealie/schema/user/user_favorites.py`, and meet input §5 test-count minimums (3 unit, 6 integration, 2 multitenant). Every functional FR is linked to a measurable SC and every P1 user story is claimed by a FR per the B3 trace-matrix rule.

## NEEDS_CLARIFICATION (blocking decisions)

### NC-001 — Storage model: new `user_favorite_recipe` table vs reuse `UserToRecipe.is_favorite`

**Conflict**: Input §1 requests a new `user_favorite_recipe` table with composite unique (user_id, recipe_id), single user_id index, and cascade FKs. Mealie code already persists favorites on the existing `users_to_recipes` table via `UserToRecipe.is_favorite` (boolean column), and the 2024-03-18 Alembic migration `d7c6efd2de42` explicitly consolidated favorites into that table and dropped the older `users_to_favorites` table. Implementing both storage models simultaneously would double-write favorite state and break the existing legacy routes plus the rating coexistence on the same row.

**Recommended default**: Reuse `UserToRecipe.is_favorite` as the canonical favorite storage. Rationale: (1) the 2024-03-18 migration already collapsed favorites into this row; (2) the unique constraint `user_id_recipe_id_rating_key` on `UserToRecipe.__table_args__` already enforces the same (user_id, recipe_id) invariant that input §1 asks for; (3) indexes on user_id and recipe_id already exist via `index=True` on the columns; (4) the existing legacy routes at `/api/users/{id}/favorites/{slug}` and the frontend `RecipeFavoriteBadge.vue` already depend on this storage, so a parallel table would require dual-write, backfill, and deprecation work that input §1 does not justify. The composite uniqueness, cascade, and indexing requirements from input §1 are satisfied by adding `ON DELETE CASCADE` to the existing FKs (see FR-015).

**If rejected**: Implement a separate `user_favorite_recipe` table per input §1, plus an Alembic migration that (a) creates the table with FKs ON DELETE CASCADE, (b) backfills rows from `users_to_recipes` where `is_favorite = true`, (c) introduces a dual-write window in `UserRatingsController.set_rating` writing to both tables, (d) cuts over reads, and (e) drops `UserToRecipe.is_favorite` in a follow-up migration. In this branch FR-001 / FR-003 / FR-004 / FR-007 / FR-008 / FR-015 must be re-pointed at the new table.

**Related**: FR-001, FR-003, FR-004, FR-007, FR-008, FR-015

### NC-002 — `GET /api/users/self/favorites` response contract: break the existing rating-summary endpoint or add a parallel path

**Conflict**: Input §2 requests `GET /api/users/self/favorites?page=1&perPage=50` returning a paginated recipe list (response shape `PaginationBase[RecipeSummary]`). Mealie code already has an endpoint at that exact path: `UserController.get_logged_in_user_favorites` at `mealie/routes/users/crud.py:38-40` returns `UserRatings[UserRatingSummary]` (a non-paginated list of rating summaries). Silently overwriting the response model would break OpenAPI clients, generated TypeScript types, and the existing integration test `test_user_recipe_favorites` at `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:43`.

**Recommended default**: Add a new endpoint `GET /api/users/self/favorites/recipes` returning `PaginationBase[RecipeSummary]` per input §2. Leave the existing `GET /api/users/self/favorites` returning `UserRatings[UserRatingSummary]` unchanged so the one integration test caller and any external clients (generated TypeScript, third-party API consumers) continue to work. Document the legacy endpoint as deprecated in its OpenAPI docstring and schedule removal in the next minor release. Rationale: zero breakage, matches input §2 exactly (the path the input specifies still works), and the alias is one extra route handler delegating to `RepositoryUserRatings.get_by_user(self.user.id, favorites_only=True)`.

**If rejected**: Change `UserController.get_logged_in_user_favorites` response_model to `PaginationBase[RecipeSummary]`, update the single test caller in `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:43-95` to expect the new shape, regenerate frontend API types via `task dev:generate`, and add a CHANGELOG entry flagging the breaking response-shape change. Drop FR-006's parallel-route requirement and update SC-003's path.

**Related**: FR-006

### NC-003 — `favorite_count` visibility scope: global vs group-scoped vs public-only

**Conflict**: Input §3 says `favorite_count` is `公开` (publicly returned). The natural reading is a global count across all users who favorited the recipe. But the spec must also avoid leaking cross-tenant data: a household-private recipe should not have its count visible to outsiders, and the existing recipe endpoints scope reads by group/household visibility. The choice changes the SQL aggregate (no WHERE clause vs join through recipe visibility filter) and the tenant isolation guarantee in SC-006.

**Recommended default**: Compute `favorite_count` as the number of `UserToRecipe` rows with `is_favorite = true` AND `recipe_id = <recipe.id>`, with no additional filter on the favoriting user's group or household. Visibility of the count is bounded only by visibility of the recipe itself: the existing recipe endpoint already returns 404 for cross-group recipes (per FR-005), so a caller who can read the recipe is allowed to see how many distinct users favorited it. Rationale: input §3 explicitly says `公开` (public), and the existing `RecipeModel.favorited_by` relationship at `mealie/db/models/recipe/recipe.py:68` has no tenant filter — matching that behavior keeps the count consistent with the relationship and avoids surprising drops when admins move users between households.

**If rejected**: Switch the aggregate to count only `UserToRecipe` rows whose user is in the same group as the recipe (join `UserToRecipe.user_id` to `users.group_id` and filter `users.group_id = recipe.group_id`). Document the choice in FR-008 and add a multitenant test asserting that cross-group favorites do not contribute to the count. SC-005 and SC-006 thresholds must be updated accordingly.

**Related**: FR-007, FR-008

## User Scenarios & Testing

### US-1 — Authenticated user favorites a recipe via self route (Priority: P1)

As a signed-in user, I can favorite a recipe visible to my group without sending my own user id in the URL.

**Why this priority**: Core write path requested by input §2; without it the feature does not exist.

**Independent test**: Log in as user A, POST `/api/users/self/favorites/{visible_recipe_slug}` twice, then GET the new self favorites recipe list and assert the recipe appears exactly once.

**Acceptance Scenarios**:

1. **Given** an authenticated user and a recipe visible to their group, **When** they POST `/api/users/self/favorites/{recipe_slug}`, **Then** the response is 200, a `UserToRecipe` row exists for (user_id, recipe_id) with `is_favorite = true`, and no duplicate row is created on repeat POSTs
2. **Given** an authenticated user POSTing the same favorite twice, **When** the second POST is observed, **Then** the response is 200 (idempotent) and the row count for (user_id, recipe_id) in `users_to_recipes` remains 1
3. **Given** a recipe whose group is not the user's group, **When** the user POSTs the self favorite route for that slug, **Then** the response is 404 and no `UserToRecipe` row is created
4. **Given** an authenticated request to the self favorite POST route, **When** the implementation looks up the user id, **Then** the user id is read from `self.user.id` (the JWT-resolved current user) and never from a URL path parameter

### US-2 — Authenticated user unfavorites a recipe via self route (Priority: P1)

As a signed-in user, I can remove a favorite using a self route, without sending my own user id in the URL.

**Why this priority**: Symmetric counterpart to US-1; required by input §2 idempotency rules.

**Independent test**: Favorite a recipe as user A, DELETE `/api/users/self/favorites/{recipe_slug}` twice, then assert `is_favorite = false` in `users_to_recipes` and 200 status on both DELETEs.

**Acceptance Scenarios**:

1. **Given** an authenticated user with an existing favorite for a recipe, **When** they DELETE `/api/users/self/favorites/{recipe_slug}`, **Then** the `UserToRecipe` row is updated to `is_favorite = false` and the response is 200
2. **Given** an authenticated user with no favorite for a recipe, **When** they DELETE `/api/users/self/favorites/{recipe_slug}`, **Then** the response is 200 (idempotent) and no error is raised
3. **Given** a recipe whose group is not the user's group, **When** the user DELETEs the self favorite route for that slug, **Then** the response is 404 and no row in `users_to_recipes` is modified

### US-3 — User lists their favorited recipes (paginated) (Priority: P1)

As a signed-in user, I can list my favorited recipes with Mealie pagination semantics, getting a paginated recipe list (not a rating summary list).

**Why this priority**: Required by input §2; gives users the 'my collection' surface that motivates the whole favoriting feature.

**Independent test**: Favorite 60 recipes across two pages and GET `/api/users/self/favorites/recipes?page=1&perPage=50` then `?page=2&perPage=50`; assert items length 50 then 10, total=60, and items are `RecipeSummary` shape.

**Acceptance Scenarios**:

1. **Given** an authenticated user with favorited recipes visible in their group, **When** they GET the new self favorites recipe-list endpoint, **Then** the response shape is `PaginationBase[RecipeSummary]` with `page`, `per_page`, `total`, `total_pages`, `items`, `next`, and `previous` fields per `mealie/schema/response/pagination.py:51`
2. **Given** an authenticated user with N favorites and a query `page=2&perPage=10`, **When** the user lists favorites, **Then** exactly the second 10 items are returned and `total = N`
3. **Given** another user B has favorited a recipe that user A has not, **When** user A lists their favorites, **Then** user B's favorite is not included unless user A also favorited it and the recipe is visible to user A's group

### US-4 — Recipe list and detail responses include `favorited` and `favorite_count` (Priority: P1)

As any recipe reader, I see `favorite_count: int` on every recipe response; as an authenticated reader, I additionally see `favorited: bool` indicating whether I favorited the recipe.

**Why this priority**: Required by input §3; UI badge depends on the bool, ranking/sort depends on the count.

**Independent test**: User A favorites recipe R. User A GETs `/api/recipes/{R.slug}` and asserts `favorited = true`, `favorite_count = 1`. User B (different user, same group) GETs the same and asserts `favorited = false`, `favorite_count = 1`.

**Acceptance Scenarios**:

1. **Given** user A favorited recipe R, **When** user A GETs `/api/recipes` or `/api/recipes/{R.slug}`, **Then** the returned recipe has `favorited = true` and `favorite_count >= 1`
2. **Given** user A did NOT favorite recipe R but recipe R has favorites from other users, **When** user A GETs the same recipe, **Then** the returned recipe has `favorited = false` and `favorite_count` equals the total count under the visibility model fixed in NC-003
3. **Given** a list endpoint returning many recipes, **When** favorites are hydrated, **Then** the implementation uses a single bulk query (correlated EXISTS, joined subquery, GROUP BY aggregate, or one batched lookup keyed by page item ids) rather than one extra query per recipe

### US-5 — Anonymous reader sees `favorited=false` and a real `favorite_count` (Priority: P1)

As an unauthenticated reader of public recipe endpoints, I see `favorited = false` (no per-user state) but a non-zero `favorite_count` when the recipe has favorites.

**Why this priority**: Explicitly required by input §3 (`未登录用户：favorited 字段恒为 false`); the public count is the social-proof signal the input asks for.

**Independent test**: User A favorites recipe R. Anonymous client (no Authorization header) GETs the public recipe endpoint for R; assert `favorited = false` and `favorite_count = 1`.

**Acceptance Scenarios**:

1. **Given** an unauthenticated request to a public recipe endpoint, **When** the recipe is returned, **Then** `favorited = false` regardless of whether any user favorited the recipe
2. **Given** an unauthenticated request to a public recipe endpoint and the recipe has favorites, **When** the recipe is returned, **Then** `favorite_count` reflects the real count under the visibility model fixed in NC-003 (not 0)
3. **Given** the `/api/recipes/*` controller currently requires authentication via `UserAPIRouter`, **When** implementing US-5, **Then** either the existing public controller `PublicRecipesController` at `mealie/routes/explore/controller_public_recipes.py:21` is extended to hydrate `favorited`/`favorite_count`, or the authenticated `/api/recipes/*` routes are migrated to `Depends(try_get_current_user)` so anonymous reads are served from the same handler

### US-6 — Cross-group isolation: users cannot favorite or see favorites of other groups' recipes (Priority: P1)

As a tenant-isolated user, I cannot favorite a recipe outside my group, list other users' favorites, or have my favorites leak into another household's responses.

**Why this priority**: Required by input §2 multitenant rules; failure leaks cross-tenant data.

**Independent test**: Create user A in group G1 and user B in group G2. Recipe R belongs to G1. Assert (a) user B POSTing the self favorite route for R returns 404, (b) user B's favorites list does not include R, (c) user A's favorites list does not include any recipe owned by G2.

**Acceptance Scenarios**:

1. **Given** user A in group G1, user B in group G2, recipe R in G1, **When** user B POSTs `/api/users/self/favorites/{R.slug}`, **Then** the response is 404 and no `UserToRecipe` row is created for (B.id, R.id)
2. **Given** user A favorited recipe R (in G1), **When** user B (in G2) lists their own favorites, **Then** R does not appear in user B's response
3. **Given** two households H1 and H2 within group G1, **When** user in H1 favorites a recipe owned by H1, **Then** users in H2 reading their own self favorites list do not see that recipe (favorites are per-user, not per-household)

### US-7 — Cascade cleanup when a recipe or user is deleted (Priority: P2)

As an operator, when I delete a recipe I expect every related favorite row to disappear; when I delete a user I expect every favorite that user owned to disappear; no orphan rows remain to skew `favorite_count`.

**Why this priority**: Required by input §2 (`食谱被删除时：cascade 删除所有相关 favorite`); P2 rather than P1 because it depends on US-4 having shipped the `favorite_count` aggregate before the orphan effect is observable.

**Independent test**: (a) Favorite recipe R, DELETE R via the recipe DELETE endpoint, assert no `UserToRecipe` row with `recipe_id = R.id` remains. (b) Favorite recipe R as user A, DELETE user A via the admin user DELETE endpoint, assert no `UserToRecipe` row with `user_id = A.id` remains and that `favorite_count` on R drops by 1.

**Acceptance Scenarios**:

1. **Given** a favorited recipe is deleted via the recipe DELETE flow, **When** the favorites list and `favorite_count` are queried, **Then** the deleted recipe is absent from every favorites list and contributes 0 to any aggregate
2. **Given** a user with favorite rows is deleted via the user DELETE flow, **When** the favorites and `favorite_count` aggregates are queried for remaining users, **Then** the deleted user's `UserToRecipe` rows are absent and `favorite_count` is decremented for every recipe the user had favorited
3. **Given** FK definitions on `users_to_recipes.user_id` and `users_to_recipes.recipe_id` currently lack `ondelete=CASCADE`, **When** the implementation adds the cascade behavior, **Then** the new Alembic migration (FR-015) modifies the FKs to `ON DELETE CASCADE` AND `RepositoryUsers.delete` is extended (FR-016) so both the database and application layers agree on the cascade outcome

### US-8 — Existing `/api/users/{id}/favorites/{slug}` routes keep working (Priority: P2)

As a client of the legacy user-id favorite routes (single test caller plus any third-party OpenAPI consumer), my requests continue to land on the same storage and return the same shape.

**Why this priority**: Backward compat; failure breaks the existing `test_user_recipe_favorites` test plus any external client.

**Independent test**: Run the existing parametrized `test_user_recipe_favorites[use_self_route=False]` test in `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py` and confirm it still passes after the change.

**Acceptance Scenarios**:

1. **Given** an existing client calling POST/DELETE `/api/users/{id}/favorites/{slug}` for its own user id, **When** the legacy route is invoked, **Then** the behavior, status code, and storage effect are unchanged from the pre-feature baseline
2. **Given** a client calling the legacy route with another user's id, **When** the id mismatch is detected via `assert_user_change_allowed`, **Then** the existing permission check still rejects the request
3. **Given** the new self routes (FR-002) and the legacy routes (FR-011), **When** both mutate the same (user, recipe) pair, **Then** they call the same repository method (`RepositoryUserRatings.create` / `.update`) so storage stays consistent

## Requirements

### Functional Requirements

- **FR-001** [FR]: Under the NC-001 recommended default, favorite persistence MUST use the existing `users_to_recipes` table and `UserToRecipe.is_favorite` boolean column as the canonical storage; no new `user_favorite_recipe` table is introduced. The composite uniqueness input §1 requires is already enforced by the table-level `UniqueConstraint("user_id", "recipe_id", name="user_id_recipe_id_rating_key")` and the existing per-column `index=True` declarations satisfy the user_id index. If NC-001 is rejected, FR-001 is replaced per the NC-001 `if_rejected` block.
  - Code references: `mealie/db/models/users/user_to_recipe.py` L17-30 (UserToRecipe, is_favorite, users_to_recipes, user_id_recipe_id_rating_key, user_id, recipe_id), `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py` L153-195 (users_to_recipes, users_to_favorites, is_favorite, user_id_recipe_id_rating_key)
  - Related: US-1, US-2, US-3, US-6
- **FR-002** [FR]: Add two authenticated self routes that resolve the user id from `self.user.id` (JWT) and never accept a user id from the URL: `POST /api/users/self/favorites/{recipe_slug}` and `DELETE /api/users/self/favorites/{recipe_slug}`. The new routes live on the existing `UserController` in `mealie/routes/users/crud.py` (which extends `BaseUserController`) and are mounted via the existing `user_router` registered in `mealie/routes/users/__init__.py`.
  - Code references: `mealie/routes/users/crud.py` L17-40 (UserController, BaseUserController, user_router, get_logged_in_user_favorites), `mealie/routes/users/ratings.py` L78-86 (add_favorite, remove_favorite, set_rating, is_favorite), `mealie/routes/users/__init__.py` L1-15 (user_prefix, router, include_router, ratings)
  - Related: US-1, US-2
- **FR-003** [FR]: POST `/api/users/self/favorites/{recipe_slug}` MUST be idempotent. When no `UserToRecipe` row exists for (self.user.id, recipe.id), create one with `is_favorite = true`; when one exists, update its `is_favorite` to true. Re-POST MUST return 200 and the row count for (self.user.id, recipe.id) in `users_to_recipes` MUST remain exactly 1. Delegate the row create-or-update to `UserRatingsController.set_rating(self.user.id, slug, UserRatingUpdate(is_favorite=True))` so the existing `assert_user_change_allowed` invariant is preserved.
  - Code references: `mealie/routes/users/ratings.py` L54-86 (set_rating, assert_user_change_allowed, UserRatingUpdate, is_favorite, add_favorite), `mealie/repos/repository_users.py` L78-101 (RepositoryUserRatings, get_by_user_and_recipe, UserToRecipe), `mealie/db/models/users/user_to_recipe.py` L17-30 (UserToRecipe, user_id_recipe_id_rating_key, is_favorite)
  - Related: US-1
- **FR-004** [FR]: DELETE `/api/users/self/favorites/{recipe_slug}` MUST be idempotent. When a `UserToRecipe` row exists, set `is_favorite = false` and return 200; when no row exists, return 200 without raising. Delegate to `UserRatingsController.set_rating(self.user.id, slug, UserRatingUpdate(is_favorite=False))` to keep the storage path identical to FR-003.
  - Code references: `mealie/routes/users/ratings.py` L54-86 (set_rating, remove_favorite, is_favorite, UserRatingUpdate), `mealie/repos/repository_users.py` L78-101 (RepositoryUserRatings, get_by_user_and_recipe, UserToRecipe)
  - Related: US-2
- **FR-005** [FR]: All favorite mutation and list endpoints MUST resolve recipes through `UserRatingsController.group_recipes.get_one(...)` (or the equivalent `BaseRecipeController.group_recipes` repository), which scopes lookups to the current user's group. Recipes outside the user's group MUST return 404 via `get_recipe_or_404`. The new self routes MUST reuse the same `group_recipes` repository pattern as the existing legacy `/api/users/{id}/favorites/{slug}` route — no global recipe lookup is permitted on these handlers.
  - Code references: `mealie/routes/users/ratings.py` L17-42 (UserRatingsController, group_recipes, get_recipe_or_404, HTTPException), `mealie/routes/recipe/_base.py` L37-44 (BaseRecipeController, group_recipes, RepositoryRecipes)
  - Related: US-1, US-2, US-6
- **FR-006** [FR]: Add a new endpoint `GET /api/users/self/favorites/recipes` returning `PaginationBase[RecipeSummary]` per the NC-002 recommended default. The existing `GET /api/users/self/favorites` endpoint at `mealie/routes/users/crud.py:38-40` returning `UserRatings[UserRatingSummary]` MUST stay unchanged in shape and behavior. The new endpoint MUST accept `page` and `per_page` query parameters wired through `PaginationQuery` (`mealie/schema/response/pagination.py:46`) and produce a `PaginationBase`-shaped response. If NC-002 is rejected, the new endpoint is dropped and the existing endpoint's response model is replaced per the NC-002 `if_rejected` block.
  - Code references: `mealie/routes/users/crud.py` L17-40 (UserController, BaseUserController, user_router, get_logged_in_user_favorites, UserRatingSummary), `mealie/schema/response/pagination.py` L32-58 (RequestQuery, PaginationQuery, PaginationBase, page, per_page, items), `mealie/repos/repository_users.py` L78-96 (RepositoryUserRatings, get_by_user, favorites_only, UserToRecipe)
  - Related: US-3
- **FR-007** [FR]: Extend `RecipeSummary` (and therefore `Recipe`, which inherits from it) in `mealie/schema/recipe/recipe.py` with two fields: `favorite_count: int` and `favorited: bool`. Default rules are scoped independently to close the old CONS-H-001 ambiguity: (a) `favorite_count` defaults to `0` only when the recipe has zero favorite rows under the NC-003 visibility model — for unauthenticated callers the count MUST still be computed and returned, not forced to 0; (b) `favorited` defaults to `false` when (i) the request is unauthenticated, OR (ii) no `UserToRecipe` row exists for the current `(user_id, recipe_id)` with `is_favorite = true`.
  - Code references: `mealie/schema/recipe/recipe.py` L116-175 (RecipeSummary, MealieModel, loader_options, recipe_yield_display), `mealie/schema/recipe/recipe.py` L182-190 (Recipe, RecipeSummary, recipe_ingredient)
  - Related: US-4, US-5
- **FR-008** [FR]: Hydrate `favorited` and `favorite_count` via a query mechanism that projects values into the response (NOT via `RepositoryRecipes.column_aliases`, which only feeds ORDER BY and query-filter expressions — see ARCH-H-002). Implementation MUST use one of: (a) a SQLAlchemy `column_property` or `hybrid_property` on `RecipeModel` whose loader option is added to `RecipeSummary.loader_options()`; or (b) a post-query batched lookup keyed by the page's recipe ids, hydrated onto the `RecipeSummary` payloads in the recipe service or route layer. `favorited` MUST be derived from `UserToRecipe.user_id == self.user.id AND UserToRecipe.recipe_id == recipe.id AND UserToRecipe.is_favorite == true`. `favorite_count` MUST be the count of `UserToRecipe` rows for the recipe with `is_favorite = true`, under the visibility model fixed by NC-003.
  - Code references: `mealie/repos/repository_recipes.py` L36-52, 72-93 (RepositoryRecipes, column_aliases, by_user, _get_rating_col_alias, UserToRecipe), `mealie/db/models/recipe/recipe.py` L42-74 (RecipeModel, favorited_by, rating), `mealie/schema/recipe/recipe.py` L168-175 (loader_options, joinedload, RecipeModel)
  - Related: US-4, US-6
- **FR-009** [NFR]: Recipe list queries hydrating `favorited`/`favorite_count` MUST execute a bounded number of database queries that does NOT scale with page size. Concretely: for `GET /api/recipes?per_page=N` the total query count for favorite hydration MUST be at most a constant K (target K ≤ 3) regardless of N. The acceptable implementation shapes are: correlated EXISTS subquery, GROUP BY aggregate in the main SELECT, joined `column_property`, or a single batched lookup keyed by the page's recipe ids.
  - Code references: `mealie/routes/recipe/recipe_crud_routes.py` L85-90, 341-345 (router, UserAPIRouter, RecipeController, BaseRecipeController, get_all), `mealie/repos/repository_recipes.py` L36-52 (RepositoryRecipes, column_aliases, by_user), `mealie/repos/repository_recipes.py` L220-225 (page_all)
  - Related: US-4
- **FR-010** [FR]: `favorited`/`favorite_count` MUST be observable on at least one anonymous-readable recipe endpoint. Two valid implementation paths: (a) extend `PublicRecipesController` at `mealie/routes/explore/controller_public_recipes.py:21-31` to hydrate both fields on the public list and detail routes; or (b) migrate the authenticated `RecipeController` routes from `UserAPIRouter` (which forces `Depends(get_current_user)` and returns 401 to anonymous callers per `mealie/routes/_base/routers.py:20-24`) to `Depends(try_get_current_user)` so the same handler serves both anonymous and authenticated callers. The implementer MUST choose exactly one path and add an integration test asserting an anonymous GET returns 200 with `favorited = false` and the real `favorite_count`.
  - Code references: `mealie/routes/explore/controller_public_recipes.py` L17-31 (router, APIRouter, PublicRecipesController, BasePublicHouseholdExploreController, cross_household_recipes), `mealie/routes/_base/routers.py` L20-25 (UserAPIRouter, APIRouter, get_current_user), `mealie/core/dependencies/dependencies.py` L77-86 (try_get_current_user, oauth2_scheme_soft_fail, get_current_user), `mealie/routes/_base/base_controllers.py` L132-140 (BaseUserController, get_current_user)
  - Related: US-5
- **FR-011** [FR]: The existing legacy routes `POST/DELETE/GET /api/users/{id}/favorites/...` MUST keep their current request and response contracts; both legacy and new self routes MUST delegate to the same `RepositoryUserRatings.create`/`update` call path so the (user_id, recipe_id, is_favorite) row state is identical whichever route is used. The existing parametrized test `test_user_recipe_favorites[use_self_route=False]` MUST continue to pass without modification.
  - Code references: `mealie/routes/users/ratings.py` L49-86 (get_favorites, add_favorite, remove_favorite, set_rating, is_favorite), `mealie/repos/repository_users.py` L78-101 (RepositoryUserRatings, get_by_user, get_by_recipe, get_by_user_and_recipe)
  - Related: US-8
- **FR-012** [FR]: Implementation MUST follow the three-layer pattern input §4 requires: HTTP routes in `mealie/routes/users/` (favorite write/list) and `mealie/routes/recipe/` (recipe response hydration) delegate to a service module under `mealie/services/user_services/` (create the directory if absent) for favorite write/list business logic, which in turn calls the repository layer (`mealie/repos/repository_users.py` `RepositoryUserRatings` or a new `mealie/repos/repository_favorites.py`). The recipe-side hydration MAY route through the existing `mealie/services/recipe/recipe_service.py` `RecipeService`. No favorite SQL or favorite-domain logic is permitted in route handlers.
  - Code references: `mealie/routes/users/ratings.py` L78-86 (add_favorite, remove_favorite, set_rating), `mealie/repos/repository_users.py` L78-101 (RepositoryUserRatings, GroupRepositoryGeneric, UserToRecipe), `mealie/routes/recipe/_base.py` L37-53 (BaseRecipeController, recipes, group_recipes, service, RecipeService)
  - Related: US-1, US-2, US-3
- **FR-013** [FR]: Pydantic request/response models for the new self favorite endpoints (and any new shared favorite types) MUST live at `mealie/schema/user/user_favorites.py` per input §4. The recipe response field additions (`favorited`, `favorite_count`) stay on `RecipeSummary` in `mealie/schema/recipe/recipe.py` per FR-007 because they are recipe-scoped, not user-scoped.
  - Code references: `mealie/schema/recipe/recipe.py` L116-130 (RecipeSummary, MealieModel)
  - Related: US-1, US-2, US-3
- **FR-014** [FR]: All user-facing error messages introduced by this feature MUST be routed through `self.t("<key>")` keys defined in `mealie/lang/messages/en-US.json` (the file is JSON, not YAML as input §4 states). The implementation MUST NOT introduce any new hardcoded English strings in 4xx responses. Existing pattern: `mealie/routes/users/crud.py:47,51` uses `self.t("user.ldap-update-password-unavailable")` etc. Translations for the non-English locale files under `mealie/lang/messages/*.json` are out of scope (see Out of Scope).
  - Code references: `mealie/routes/users/crud.py` L42-60 (self.t, update_password, ErrorResponse), `mealie/lang/messages/en-US.json` L1-10 (generic, server-error, recipe)
  - Related: US-1, US-2, US-6
- **FR-015** [FR]: Add a new Alembic migration that alters the existing `users_to_recipes` foreign keys to `ON DELETE CASCADE` on BOTH `recipe_id` (FK to `recipes.id`) AND `user_id` (FK to `users.id`). The current FK declarations in migration `d7c6efd2de42` at lines 164-171 use bare `sa.ForeignKeyConstraint([...], [...])` with no `ondelete` keyword, so neither database-level cascade fires today. This FR is required by input §1 (`级联删除`) and by US-7. The new migration MUST handle the SQLite path via `op.batch_alter_table("users_to_recipes")` (matching the pattern at lines 190-191 of the cited migration).
  - Code references: `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py` L153-195 (upgrade, users_to_recipes, ForeignKeyConstraint, recipe_id, user_id, batch_alter_table), `mealie/db/models/users/user_to_recipe.py` L17-30 (UserToRecipe, user_id, recipe_id, ForeignKey)
  - Related: US-7
- **FR-016** [FR]: Extend `RepositoryUsers.delete` at `mealie/repos/repository_users.py:55-65` to explicitly `sa.delete(UserToRecipe).where(UserToRecipe.user_id == value)` BEFORE calling `super().delete(...)`, mirroring the existing recipe-side pattern in `RepositoryRecipes._delete_recipe` at `mealie/repos/repository_recipes.py:110-128` which already deletes `UserToRecipe` rows before deleting the recipe. This is the application-layer half of US-7 and runs even on backends where FK ON DELETE CASCADE (FR-015) is not honored at the database level.
  - Code references: `mealie/repos/repository_users.py` L18-65 (RepositoryUsers, delete, PrivateUser, shutil), `mealie/repos/repository_recipes.py` L110-130 (_delete_recipe, UserToRecipe, sa.delete), `mealie/db/models/users/user_to_recipe.py` L17-30 (UserToRecipe, user_id)
  - Related: US-7
- **FR-017** [FR]: The new Alembic migration for FR-015 MUST use the existing filename convention `YYYY-MM-DD-HH.MM.SS_<revision_hash>_<snake_case_description>.py` (example: `2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py`). The revision hash MUST be the new alembic revision id generated by `alembic revision`, the `down_revision` MUST point at the current head, and the file MUST be placed under `mealie/alembic/versions/`.
  - Code references: `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py` L153-195 (upgrade, users_to_recipes)
  - Related: US-7
- **FR-018** [FR]: Every new endpoint (FR-002, FR-006) MUST be defined with a FastAPI `response_model=` argument matching its Pydantic schema and MUST include a docstring describing the operation. The auto-generated OpenAPI spec MUST cover both new endpoints; no manual edits to `frontend/app/lib/api/types/` are permitted (generation runs via `task dev:generate`).
  - Code references: `mealie/routes/users/crud.py` L17-40 (UserController, response_model, user_router, get_logged_in_user), `mealie/routes/users/ratings.py` L44-86 (response_model, UserRatings, UserRatingOut, add_favorite, remove_favorite)
  - Related: US-1, US-2, US-3
- **FR-019** [FR]: Test coverage MUST meet input §5 minimums. Under `tests/unit_tests/` add at least 3 tests covering `RepositoryUserRatings` add/remove/list. Under `tests/integration_tests/user_recipe_tests/` add at least 6 tests covering: (a) self POST then re-POST returns 200 and row count == 1; (b) self DELETE then re-DELETE returns 200; (c) anonymous list-recipes returns `favorited = false` always; (d) cross-group POST returns 404; (e) post-favorite `favorite_count` increments; (f) post-DELETE recipe cascade-removes favorites; (g) pagination returns the right slice. Under `tests/multitenant_tests/` add at least 2 tests covering: (i) household A user cannot see household B user's favorites; (ii) cross-group recipes are not visible to a non-member's favorites attempt.
  - Code references: `tests/fixtures/fixture_users.py` L17-56 (build_unique_user, TestUser), `tests/fixtures/fixture_recipe.py` L32-90 (recipe_ingredient_only, recipes_ingredient_only), `tests/multitenant_tests/test_multitenant_cases.py` L23-60 (test_multitenant_cases_get_all), `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py` L42-96 (test_user_recipe_favorites, use_self_route, users_self_favorites)
  - Related: US-1, US-2, US-3, US-4, US-5, US-6, US-7

## Success Criteria

- **SC-001**: Self favorite POST is idempotent under sequential repeat
  - Metric: row count in users_to_recipes plus HTTP status of the second POST | Threshold: second POST returns HTTP 200 and row count for (user_id, recipe_id) equals 1
- **SC-002**: Self favorite DELETE is idempotent under sequential repeat
  - Metric: is_favorite value and HTTP status of the second DELETE | Threshold: second DELETE returns HTTP 200 and is_favorite equals false (or row absent)
- **SC-003**: Self favorite recipe list at the new path is paginated correctly
  - Metric: response shape and item slicing under page=1/per_page=50 then page=2/per_page=50 with 60 seeded favorites | Threshold: first page items length equals 50, second page items length equals 10, total equals 60, response contains page per_page total total_pages items next previous fields
- **SC-004**: Recipe list hydration of favorited and favorite_count is bounded query count
  - Metric: number of SQL queries issued by GET /api/recipes?per_page=N attributable to favorite hydration, measured with N=10 and N=50 | Threshold: favorite-hydration query count is at most 3 and does not increase between N=10 and N=50
- **SC-005**: favorited and favorite_count are correct for authenticated and anonymous callers
  - Metric: field values returned by GET /api/recipes/{slug} and the anonymous-readable path chosen in FR-010 | Threshold: favoriting user sees favorited equals true and favorite_count greater than or equal to 1; other authenticated users see favorited equals false and the same favorite_count; anonymous caller sees favorited equals false and favorite_count equals the value from the visibility model fixed by NC-003
- **SC-006**: Cross-group and cross-household isolation holds for favorites
  - Metric: HTTP status of POST self favorite against a foreign-group recipe slug, plus presence of foreign-group recipes in self favorites list | Threshold: POST returns HTTP 404 and zero foreign-group recipes appear in any authenticated user self favorites list
- **SC-007**: Legacy /api/users/{id}/favorites/{slug} routes remain backward compatible
  - Metric: pass status of the existing parametrized test_user_recipe_favorites with use_self_route equals False after the change | Threshold: all use_self_route equals False assertions pass without modification
- **SC-008**: All new 4xx error messages flow through the i18n provider
  - Metric: grep across mealie/routes/users and mealie/routes/recipe for new hardcoded English error strings introduced by this feature | Threshold: zero new hardcoded English error strings; every new HTTPException detail uses self.t(<key>) where the key exists in mealie/lang/messages/en-US.json
- **SC-009**: Cascade cleanup works for both recipe-delete and user-delete paths
  - Metric: row count of UserToRecipe entries referencing a deleted parent after DELETE recipe and DELETE user flows complete | Threshold: zero UserToRecipe rows reference a deleted recipe id and zero rows reference a deleted user id
- **SC-010**: Test count minimums from input §5 are met
  - Metric: count of new test functions under tests/unit_tests, tests/integration_tests/user_recipe_tests, and tests/multitenant_tests attributable to this feature | Threshold: unit count greater than or equal to 3, integration count greater than or equal to 6, multitenant count greater than or equal to 2
- **SC-011**: New Alembic migration filename matches the existing convention
  - Metric: regex match of the new migration filename against the convention YYYY-MM-DD-HH.MM.SS_<hash>_<snake>.py | Threshold: filename matches the regex and the file lives under mealie/alembic/versions/
- **SC-012**: OpenAPI spec covers both new endpoints with response_model and docstring
  - Metric: presence of the two new operations in the generated openapi.json with non-empty description and a non-default response schema | Threshold: both POST /api/users/self/favorites/{recipe_slug} and GET /api/users/self/favorites/recipes appear in openapi.json with response_model schemas and descriptions
- **SC-013**: Three-layer pattern is observed for new favorite logic
  - Metric: presence of a mealie/services/user_services/ module with favorite write/list logic AND absence of direct repository or SQL calls in the new route handlers | Threshold: the new service module exists and is imported by the new route handlers; new route handlers contain zero direct SQLAlchemy session calls
- **SC-014**: Pydantic favorite schemas live at the required path
  - Metric: existence and contents of mealie/schema/user/user_favorites.py | Threshold: the file exists and contains at least the request/response models used by the new self favorite endpoints

## Key Entities

- **UserToRecipe (extended)**: Existing association model in `users_to_recipes` (`mealie/db/models/users/user_to_recipe.py:17-30`). Holds `user_id`, `recipe_id`, `is_favorite`, `rating`, `id`, `created_at`, `updated_at`. Canonical favorite storage under the NC-001 default. After FR-015 its FKs gain ON DELETE CASCADE.
  - Fields: user_id (GUID FK users.id), recipe_id (GUID FK recipes.id), is_favorite (bool, indexed), rating (float), id (GUID), created_at (datetime), updated_at (datetime)
  - References: User, RecipeModel
- **Recipe favorite response metadata**: Two new response-only fields on `RecipeSummary` (and `Recipe` via inheritance): `favorited: bool` (current request user's favorite state, false for anonymous) and `favorite_count: int` (count under the visibility model fixed by NC-003).
  - Fields: favorited: bool, favorite_count: int
  - References: RecipeSummary, Recipe
- **Self favorite recipe-list response**: `PaginationBase[RecipeSummary]` returned by the new `GET /api/users/self/favorites/recipes` endpoint (NC-002 default). Items are `RecipeSummary` rows filtered to `UserToRecipe.user_id == current_user.id AND is_favorite = true` and bounded by the current user's group/household visibility.
  - Fields: page: int, per_page: int, total: int, total_pages: int, items: list[RecipeSummary], next: str | None, previous: str | None
  - References: PaginationBase, RecipeSummary
- **UserFavoriteRequest / UserFavoriteOut (new)**: New Pydantic models living at `mealie/schema/user/user_favorites.py` per FR-013. Wraps any favorite-specific request/response payloads (e.g., a typed empty request body for the POST self route, or a thin wrapper around `UserToRecipe` for internal use). Recipe-side fields stay on `RecipeSummary` per FR-007.
  - References: RecipeSummary, UserToRecipe

## Edge Cases

- Idempotent POST of an already-favorited recipe by the same user → return HTTP 200 with the existing favorite state intact; no second `UserToRecipe` row is inserted (FR-003)
- DELETE of a recipe the user never favorited → return HTTP 200 with `is_favorite = false` and no error response (FR-004)
- POST or DELETE self favorite for a recipe outside the user's group → return HTTP 404 via `get_recipe_or_404` (FR-005, US-6)
- Recipe is deleted while it has favorite rows → `RepositoryRecipes._delete_recipe` already deletes UserToRecipe rows; FR-015 additionally adds ON DELETE CASCADE on the FK so raw SQL deletes also clean up (US-7 AC1)
- User is deleted while owning favorite rows → FR-016 extends `RepositoryUsers.delete` to delete UserToRecipe rows for that user first; FR-015 also adds ON DELETE CASCADE on the user_id FK (US-7 AC2)
- Anonymous GET to a public recipe endpoint → `favorited` is returned as false and `favorite_count` is the non-zero real count per FR-007 default (a) and FR-010 (US-5)
- `GET /api/users/self/favorites` already exists returning rating summaries (UserRatings[UserRatingSummary]) → NC-002 default keeps the old route unchanged and adds the recipe-list at the new path `/api/users/self/favorites/recipes`
- Concurrent POSTs to the same self favorite slug from the same user → The existing `set_rating` path reads then writes (no UPSERT), so two concurrent inserts can race against the `user_id_recipe_id_rating_key` UniqueConstraint; the loser raises IntegrityError translated to HTTP 500. This pre-existing behavior is preserved; SC-001 asserts only sequential idempotency
- `favorite_count` for a private recipe under NC-003 default → the count is the global tally of `UserToRecipe` rows for the recipe; the recipe endpoint itself returns 404 to non-members, so unauthorized callers cannot observe the count for hidden recipes
- Existing `UserToRecipe` after_insert/after_update/after_delete event listener at `mealie/db/models/users/user_to_recipe.py:46-49` fires on every favorite toggle → the listener calls `update_recipe_rating` to flag a recipe rating recompute; favorite POST/DELETE pay this SELECT+UPDATE cost. FR-009 bounds total query count but does not eliminate this listener; if FR-009 implementation introduces a denormalized favorite_count column on `recipes`, it MUST hook into the same listener

## Assumptions

- The NC-001 recommended default is accepted (reuse `UserToRecipe.is_favorite`). All FRs are written for that branch; the `if_rejected` block in NC-001 enumerates the FR rewrites for the alternative.
- The NC-002 recommended default is accepted (new endpoint at `/api/users/self/favorites/recipes`; legacy endpoint untouched).
- The NC-003 recommended default is accepted (favorite_count is the global tally, bounded only by recipe visibility).
- The backend API root is `/api`; route decorators may show paths relative to `/users` or `/recipes`.
- Frontend code changes are out of scope for this spec; the existing `RecipeFavoriteBadge.vue`, `RecipeCard.vue`, `RecipeCardMobile.vue`, and `pages/user/[id]/favorites.vue` continue to work because the legacy `/api/users/{id}/favorites/{slug}` and `/api/recipes` routes they call are preserved by FR-011 and FR-010.
- Non-English translation files under `mealie/lang/messages/*.json` are out of scope; only `en-US.json` must gain new keys for the new error messages.
- The integration test runner already exercises both SQLite and Postgres paths; FR-015's batch_alter_table approach is required to make the cascade migration SQLite-safe.

## Out of Scope

- Migrating the frontend client from `/api/users/{id}/favorites/{slug}` to the new self routes (FR-011 preserves the legacy contract for this reason)
- Manual edits to `frontend/app/lib/api/types/` — these are generated by `task dev:generate` per FR-018
- Reworking the rating feature beyond preserving favorite/rating coexistence on the same `UserToRecipe` row
- Translating new error message keys into the non-English locale files under `mealie/lang/messages/*.json`
- Adding household-level or shared favorites — favorites stay per-user per input scope
- Adding a denormalized `favorite_count` column on `recipes` — the hydration mechanism (FR-008) computes it on read
- Upgrading concurrent-POST idempotency to UPSERT — pre-existing behavior preserved per edge-case 8

## Self-Concerns (writer self-reflection)

- **FR-008**: The hydration shape (column_property vs hybrid_property vs post-query batched lookup) is intentionally left as a choice between three valid mechanisms. The implementer's choice affects the exact SQL but every option satisfies SC-004's bounded query-count threshold.
  - Evidence gap: No existing mealie precedent projects a user-specific bool field into RecipeSummary; the closest precedent is `_get_rating_col_alias` at repository_recipes.py:72-93 which is a sort/filter alias, not a projection. The three options were validated by inspecting the mechanism each one would use.
  - Suggested resolution: The implementer picks one of the three options at design time; the FR enumerates the acceptable shapes so the choice is constrained but not pre-committed.
- **FR-010**: Whether to extend the existing PublicRecipesController or migrate RecipeController to try_get_current_user is a controller-architecture choice with downstream implications for test setup and OpenAPI tag organization.
  - Evidence gap: Both controllers exist and both can host the hydration logic. The decision rests on whether the team wants to keep explore-vs-user-router separation or unify.
  - Suggested resolution: The implementer picks one path and writes the integration test specified in FR-010 against that chosen path.
- **Edge case 10 (event listener)**: Existing `update_recipe_rating` event listener on UserToRecipe adds a hidden SELECT+UPDATE cost on every favorite POST/DELETE. SC-004 measures recipe-list latency, not favorite-toggle latency, so this cost is not currently bounded by any SC.
  - Evidence gap: The listener at user_to_recipe.py:46-49 is unchanged by this spec; impact on favorite POST/DELETE latency was not measured.
  - Suggested resolution: If the listener cost becomes observable, add a follow-up SC for favorite-toggle latency; this spec preserves the existing behavior.

---

_Generated by DevLoop spec phase — writer=claude-sonnet-4.5, reviewer=n/a (new-pipeline single-shot, validator-checked), iterations=1_