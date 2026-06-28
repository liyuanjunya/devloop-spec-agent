# API Perspective

## Critical artifacts

- `mealie/routes/users/__init__.py:10-15` — current `/users` router includes `crud.user_router`; **no `self/` sub-router exists**
- **★ `mealie/routes/users/crud.py:14-40` — existing `/self/ratings` and `/self/favorites` routes (some self/ routing already in place!)**
- `mealie/routes/_base/base_controllers.py:132-189` — `BaseUserController` injects `user: PrivateUser = Depends(get_current_user)`; `BaseAdminController` swaps to `get_admin_user`; repo scoping comes from `group_id` / `household_id`
- `mealie/routes/recipe/recipe_crud_routes.py:340-395` — GET `/recipes` list endpoint; uses `self.group_recipes.by_user(self.user.id).page_all(...)` and returns raw `PaginationBase[RecipeSummary]`
- `mealie/routes/recipe/recipe_crud_routes.py:415-424` — GET `/recipes/{slug}` returns `Recipe` via `self.service.get_one(slug)`
- `mealie/schema/recipe/recipe.py:116-140` — `RecipeSummary` fields are defined here; this is where list-response `favorited` / `favorite_count` would be added
- `mealie/schema/recipe/recipe.py:167-179` — `RecipeModel` excludes some relations; model/schema shaping happens here
- `mealie/schema/response/pagination.py:32-49` — `PaginationQuery` definition (`page`, `per_page`, ordering/filter)
- `mealie/repos/repository_generic.py:104-179` — `page_all()` / `get_one()` / query filtering and repo scoping pattern
- `mealie/repos/repository_recipes.py:36-94` — recipe repo has `by_user(user_id)` and user-aware rating aliasing; good place to derive favorite state
- **★ `mealie/repos/repository_users.py:78-102` — `RepositoryUserRatings` ALREADY stores favorites via `UserToRecipe.is_favorite`**
- `mealie/core/dependencies/dependencies.py:77-138` — `get_current_user`, `try_get_current_user`, `get_admin_user`; unauthenticated optional auth exists
- **★ `mealie/routes/users/ratings.py:23-40,44-86` — existing per-user favorite CRUD; path shape is `/{id}/favorites/{slug}` via `UserRatingUpdate`** (conflict with new `/self/favorites/...`)
- `mealie/db/models/recipe/recipe.py:61-74` — `RecipeModel.favorited_by` relationship already exists
- `mealie/db/models/users/user_to_recipe.py:17-30` — join table has `is_favorite` and uniqueness on `(user_id, recipe_id)`

## Relevant artifacts

- `mealie/routes/recipe/_base.py:37-56` — `BaseRecipeController.group_recipes = get_repositories(... household_id=None).recipes`; how cross-household recipes are listed while preserving group isolation
- `mealie/repos/repository_generic.py:94-103` — `_filter_builder()` auto-applies `group_id` and `household_id` to repo queries
- `mealie/repos/repository_generic.py:156-179` — `get_one()` returns `None` when missing; controller-level 404 handling expected
- `mealie/lang/messages/en-US.json:1` — i18n bundle has `errors.no-entry-found` ("The requested resource was not found")

## Conventions discovered

- User-scoped routes live under `UserAPIRouter(prefix="/users")` and are mounted through `routes/users/__init__.py`
- Controller DI is class-based: `BaseUserController.user = Depends(get_current_user)`, `BaseAdminController.user = Depends(get_admin_user)`
- Cross-group isolation enforced by repo scoping (`group_id` from current user); cross-household visibility widened only with `household_id=None` and explicit filtering
- 404s usually `HTTPException(404, "… not found")` or `ErrorResponse.respond("Not found.")`; i18n 404 text exists as `errors.no-entry-found`
- Pagination uses `PaginationQuery` via `Depends(make_dependable(PaginationQuery))`; results wrapped in `PaginationBase`

## Open questions for spec

- Should `/api/users/self/favorites` list return only favorite recipes, or include rating metadata too (since favorites currently live on UserRating)?
- For unauthenticated GET `/api/recipes`, should `favorited` always be `false` and `favorite_count` still populated? (Spec says yes — confirmed)
- Should `GET /api/recipes/{slug}` 404 if recipe exists in another group? (Current pattern: yes via repo scoping)
- For idempotent POST/DELETE favorites, should missing recipe visibility return 404 vs 204?

## Tool calls used: 38
