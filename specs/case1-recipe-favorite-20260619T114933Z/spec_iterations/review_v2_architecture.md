# Architecture Review — v2

## Verdict
APPROVE
v2 resolves the three v1 high-severity architecture blockers: it now targets the public explore controller for anonymous reads, rejects `column_aliases` as response projection, and specifies both user-delete cleanup plus FK cascade migration work. Remaining architecture concerns are medium severity implementation traps, not blockers, provided the recorded NC defaults are accepted before coding.

## V1 issue resolution check
| v1 ID | Status | Evidence (file/line or FR id) |
|---|---|---|
| ARCH-H-001 | RESOLVED | FR-007 explicitly includes authenticated `/api/recipes` and anonymous `/api/explore/groups/{group_slug}/recipes` routes (`spec_v2.md:124-131`). Verified authenticated routes are on `UserAPIRouter(prefix="/recipes")` (`mealie/routes/recipe/recipe_crud_routes.py:85`) and public anonymous routes are `PublicRecipesController` under `APIRouter(prefix="/recipes")` with list/detail handlers (`mealie/routes/explore/controller_public_recipes.py:17,20-21,30-41,67-92,114-125`), mounted under `/explore/groups/{group_slug}` (`mealie/routes/explore/__init__.py:11,22`). |
| ARCH-H-002 | RESOLVED | FR-008 now says hydration "MUST NOT use `RepositoryRecipes.column_aliases` as a response projection mechanism" and requires SELECT/loader-compatible or batched hydration (`spec_v2.md:134-141`). Verified `page_all` serializes model rows via `eff_schema.loader_options()` and `model_validate` (`mealie/repos/repository_generic.py:341-354`), while `column_aliases` is only used in queryFilter/orderBy (`mealie/repos/repository_generic.py:367-370,407-415`; `mealie/repos/repository_recipes.py:39-47,72-93`). |
| ARCH-H-003 | RESOLVED | US-6 now separates recipe-delete cleanup, user-delete cleanup, and FK cleanup (`spec_v2.md:71-77`); FR-009 mandates FK cascade migration plus `RepositoryUsers.delete` cleanup while preserving recipe cleanup (`spec_v2.md:144-151`). Verified current asymmetry remains in code: recipe cleanup exists (`mealie/repos/repository_recipes.py:110-128`), user cleanup is absent (`mealie/repos/repository_users.py:55-65`), and current FKs lack `ondelete` (`mealie/db/models/users/user_to_recipe.py:22-24`; migration `2024-03-18...py:164-171`). |
| ARCH-M-001 | STILL_OPEN | Rewrite summary explicitly leaves favorite write latency/event-listener performance unaddressed (`rewrite_v1_to_v2.md:18-20`). SC-004 still measures only recipe read N+1/query count (`spec_v2.md:183`), while `UserToRecipe` still recomputes recipe rating on insert/update/delete (`mealie/db/models/users/user_to_recipe.py:46-53`). |
| ARCH-M-002 | RESOLVED | v2 narrows idempotency to sequential duplicates: US-1 says "sequentially" (`spec_v2.md:34`), FR-005 says "sequential duplicate-safe" (`spec_v2.md:109`), and SC-001 metric is "sequential duplicate POST result" (`spec_v2.md:180`). This no longer promises concurrent UPSERT behavior beyond the current unique constraint (`mealie/db/models/users/user_to_recipe.py:19`). |
| ARCH-M-003 | RESOLVED | NC-002 and FR-004 now state the actual blast radius: move old rating-summary behavior to a ratings-namespaced route and update the single backend parametrized test caller plus route constants (`spec_v2.md:15-17,100-106`). Verified current self favorites route is the old ratings summary (`mealie/routes/users/crud.py:38-40`), the test caller uses `users_self_favorites` (`tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:63-70`; `tests/utils/api_routes/__init__.py:190-194`), and frontend `getSelfFavorites()` actually calls `/self/ratings` (`frontend/app/lib/api/user/users.ts:62-64`). |

## NEW issues found in v2
### ARCH-V2-M-001 (MEDIUM)
**Location**: spec_v2.md FR-004
**Issue**: The suggested replacement route `/api/users/self/ratings/favorites` can be shadowed by the existing parameter route `/api/users/self/ratings/{recipe_id}` unless the static route is declared before the parameterized route, or a non-conflicting path is chosen.
**Evidence**: FR-004 suggests `/api/users/self/ratings/favorites` (`spec_v2.md:100`). Current `UserController` already declares `/self/ratings` at `mealie/routes/users/crud.py:23-25` and `/self/ratings/{recipe_id}` at `mealie/routes/users/crud.py:27-36`; FastAPI route order means a later `/self/ratings/favorites` route can be matched by `{recipe_id}` and fail UUID validation before reaching the intended handler.
**Fix**: Amend FR-004 to require declaring `/self/ratings/favorites` before `/self/ratings/{recipe_id}`, or choose a safer path such as `/api/users/self/favorite-ratings` and update route constants/tests accordingly.

### ARCH-V2-M-002 (MEDIUM)
**Location**: spec_v2.md FR-009
**Issue**: FR-009 requires a cascade migration but does not explicitly require updating SQLAlchemy model metadata, leaving an implementation path where database constraints and ORM metadata drift.
**Evidence**: FR-009 says to add an Alembic migration enforcing `ON DELETE CASCADE` and to extend `RepositoryUsers.delete` (`spec_v2.md:144-149`). The actual model FKs remain `ForeignKey("users.id")` and `ForeignKey("recipes.id")` with no `ondelete` (`mealie/db/models/users/user_to_recipe.py:22-24`), and the existing migration also created FKs without `ondelete` (`mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:164-171`).
**Fix**: Amend FR-009 to require updating `UserToRecipe.user_id` and `UserToRecipe.recipe_id` model FKs to `ondelete="CASCADE"` (and relationship/passive-delete settings if needed) in addition to the migration and application-level cleanup.

## Code reference verification
- FR-001 verified `UserToRecipe`, `is_favorite`, unique/indexed association, and 2024 migration: `mealie/db/models/users/user_to_recipe.py:17-30`; `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:153-194`.
- FR-002 verified existing service and route-direct/repository factory patterns: `mealie/services/user_services/user_service.py:8-14`; `mealie/routes/users/ratings.py:17-23,54-86`; `mealie/repos/repository_factory.py:182-188`.
- FR-003 verified pagination and recipe schema/loader references: `mealie/schema/response/pagination.py:46-58`; `mealie/schema/recipe/recipe.py:116-149,168-175,182-190`.
- FR-004 verified current self routes, legacy favorite routes, test caller, route constants, and frontend blast radius: `mealie/routes/users/crud.py:23-40`; `mealie/routes/users/ratings.py:78-86`; `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:55-70`; `tests/utils/api_routes/__init__.py:190-194`; `frontend/app/lib/api/user/users.ts:25-40,58-75`.
- FR-005 verified current idempotent write pattern and rating lookup helpers: `mealie/routes/users/ratings.py:54-86`; `mealie/repos/repository_users.py:78-101`; `mealie/db/models/users/user_to_recipe.py:17-30`.
- FR-006 verified i18n key and hardcoded 404 sites/examples: `mealie/lang/messages/en-US.json:45-52`; `mealie/routes/users/ratings.py:23-42`; `mealie/routes/users/crud.py:27-36,42-63`; `mealie/services/recipe/recipe_service.py:63-68`.
- FR-007 verified recipe schemas, authenticated controller/list/detail, public controller/list/detail, explore mount, and auth dependencies: `mealie/schema/recipe/recipe.py:116-149,182-190`; `mealie/routes/recipe/recipe_crud_routes.py:85-89,340-395,415-424`; `mealie/routes/explore/controller_public_recipes.py:20-41,67-92,114-125`; `mealie/routes/explore/__init__.py:11-22`; `mealie/routes/_base/routers.py:20-24`; `mealie/routes/_base/base_controllers.py:139-142`.
- FR-008 verified generic projection/filter/order paths, recipe aliases, serialization paths, favorite relationship, and rating helpers: `mealie/repos/repository_generic.py:330-355,367-370,407-415`; `mealie/repos/repository_recipes.py:36-52,72-93`; `mealie/routes/recipe/recipe_crud_routes.py:367-395,415-424`; `mealie/routes/explore/controller_public_recipes.py:67-92,114-125`; `mealie/db/models/recipe/recipe.py:68-74`; `mealie/repos/repository_users.py:82-96`.
- FR-009 verified FK/model/migration cleanup references: `mealie/db/models/users/user_to_recipe.py:22-24`; `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:164-179`; `mealie/repos/repository_recipes.py:110-128`; `mealie/repos/repository_users.py:55-65`; `mealie/db/models/users/users.py:84-115`; `mealie/db/models/recipe/recipe.py:68-74`.
- FR-010 verified legacy routes and frontend callers: `mealie/routes/users/ratings.py:44-86`; `frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue:48-65`; `frontend/app/pages/user/[id]/favorites.vue:30-32`; `frontend/app/lib/api/user/users.ts:50-64`.
- FR-011 verified fixture/test pattern references: `tests/fixtures/fixture_users.py:17-106`; `tests/fixtures/fixture_recipe.py:31-85`; `tests/multitenant_tests/test_multitenant_cases.py:22-74`; `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:45-70`; `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:55-70`.
- FR-012 verified migration naming/header, endpoint docs/response models, and locale file references: `mealie/alembic/versions/2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py:1-23`; `mealie/routes/users/ratings.py:44-86`; `mealie/routes/explore/controller_public_recipes.py:30-41,114-115`; `mealie/lang/messages/en-US.json:1-3,45-52`.

## Summary
- Resolved: 5/6 v1 issues
- New critical: 0
- New high: 0
- New medium: 2
- Overall: improved
