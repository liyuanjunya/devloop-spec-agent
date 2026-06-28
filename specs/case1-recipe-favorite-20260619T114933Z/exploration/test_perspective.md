# Test Perspective

## Critical artifacts

- `tests/conftest.py:1-72` — test app/DB bootstrapping (`api_client`, DB init, cleanup)
- `tests/fixtures/fixture_users.py:17-276` — `unique_user`, `h2_user`, `g2_user`, `user_tuple` tenant fixtures
- `tests/fixtures/fixture_recipe.py:16-131` — `random_recipe`, `recipe_ingredient_only`, shared recipe setup
- `tests/fixtures/fixture_multitenant.py:12-24` — `multitenants` fixture for cross-tenant isolation tests
- `tests/multitenant_tests/test_multitenant_cases.py:1-94` — canonical isolation pattern
- `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:16-240` — recipe cross-household isolation behavior
- `tests/integration_tests/user_tests/test_user_crud.py:49-117` — current-user / permissions patterns
- `pyproject.toml:97-105` — pytest discovery + marker/config defaults

## Relevant artifacts

- `tests/unit_tests/repository_tests/test_recipe_repository.py:138-220` — repository pagination/filtering patterns
- `tests/integration_tests/user_tests/test_user_api_token.py:9-39` — self endpoint + token handling
- `tests/integration_tests/user_group_tests/test_group_self_service.py:10-82` — group membership/household access checks
- `tests/integration_tests/user_household_tests/test_group_recipe_actions.py:1-240` — household edit/delete permissions

## Conventions discovered

- `tests/conftest.py` creates one shared FastAPI `TestClient` (`api_client`), runs DB init once via `main()`; cleanup removes `.temp` and SQLite DB path
- Test discovery: `tests/**`, filenames `test_*`, functions `test_*`
- Shared tenant fixtures build real users by registering + logging in, then derive `group_id` / `household_id` and attach repo handles via `get_repositories(...)`
- Multitenant tests use a common base class + seed/get_all/cleanup API; compare visible IDs per tenant
- Cross-tenant recipe tests often toggle `household.preferences.private_household` and `lock_recipe_edits_from_other_households` before asserting 200/403 behavior
- Self/current-user patterns typically fetch `api_routes.users_self` after login and assert on the returned user payload
- Pagination tests commonly use `page=1, perPage=-1` to fetch all items and compare returned IDs
- Repository tests use `PaginationQuery(page=1, per_page=-1)` for "all items" verification

## Recommended test files to create

- `tests/unit_tests/repository_tests/test_favorite_repository.py` — create/delete favorite row; duplicate create idempotency; count queries scoped by group/household
- `tests/integration_tests/user_recipe_tests/test_recipe_favorites.py` — POST/DELETE/GET endpoints; recipe response includes `favorited` and `favorite_count`; self-user behavior via `api_routes.users_self`-style auth
- `tests/multitenant_tests/case_favorites.py` — seed favorites for one/both tenants and verify `GET` only returns tenant-visible favorites; assert same recipe ID in another group/household does not leak counts or favorited state

## Open questions for spec

- Should favorite POST be idempotent (second POST returns 200/201/204) or fail on duplicate? **(Spec says idempotent — confirmed)**
- Is `favorite_count` global per recipe, per group, or per household visibility scope?
- Should `favorited` be computed for the current user only on list/detail responses? **(Spec says yes — confirmed)**
- What exact routes are expected for POST/DELETE/GET favorites, and is GET paginated? **(Spec says paginated — confirmed)**
- Can admins see cross-household favorites, or must isolation still apply exactly as with recipes?

## Tool calls used: 25
