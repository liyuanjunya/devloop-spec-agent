# Test Perspective — `GET /api/recipes` N+1 Refactor

> **Repo**: `C:\Users\v-liyuanjun\Downloads\mealie`  
> **Test runner**: `task py:test` (delegates to `uv run pytest`).  
> **Line numbers verified** against on-disk files at exploration time.

---

## 0. Critical correction up-front

The pseudo-code in the input spec uses `@pytest.mark.asyncio` and `async def`, but the Mealie test suite is **fully synchronous**:

- `mealie/db/db_setup.py:38` uses `sa.create_engine(…)` (sync), **not** `create_async_engine`.
- `tests/conftest.py:45–53` exposes `api_client` as a `starlette.testclient.TestClient` (sync) — there is no `httpx.AsyncClient` fixture.
- `pyproject.toml` declares neither `pytest-asyncio` nor `anyio` plugins, and zero existing tests use `async def` (grep across `tests/` returns 0 hits for `@pytest.mark.asyncio`).

⇒ **`tests/integration_tests/test_recipe_list_query_count.py` must be a plain sync `def` test using the `api_client` fixture**, not async. The implementer will get an import / collection error otherwise.

---

## 1. The DB engine and event-listener pattern

| Field | Value |
|-------|-------|
| Path | `mealie/db/db_setup.py` |
| Symbols | `engine` (module-level global), `SessionLocal`, `sql_global_init`, `session_context`, `generate_session` |
| Line range | **1–79** (engine init at **38**, exposed at **45**) |
| Importance | **CRITICAL** for the new query-count test |
| Reason | The new test must import the **same engine** the app and the `TestClient` use, otherwise the listener attaches to a different `Engine` instance and counts zero queries. Correct import: `from mealie.db.db_setup import engine`. The engine is bound to `SessionLocal` at L40 and the app's `Depends(generate_session)` plumbing uses this engine via `tests/conftest.py:37–53`'s `override_get_db`. |

### Existing in-code precedent for `event.listens_for(Engine, …)`

| Path | Symbol | Line range | What it shows |
|------|--------|------------|---------------|
| `mealie/db/db_setup.py` | `set_sqlite_pragma_journal_wal` | **15–30** | Decorator form: `@listens_for(Engine, "connect")`. Import path is `from sqlalchemy.event import listens_for` (L6). This is the **only** existing engine listener in the repo — there is no test-side query-count scaffold to reuse, so the new test will be the first of its kind. |

### Recommended listener wiring (compatible with the existing sync engine)

```python
from sqlalchemy import event
from mealie.db.db_setup import engine

queries: list[str] = []

def _on_query(conn, cursor, statement, parameters, context, executemany):
    queries.append(statement)

event.listen(engine, "before_cursor_execute", _on_query)
try:
    response = api_client.get("/api/recipes", params={"perPage": -1}, headers=user.token)
finally:
    event.remove(engine, "before_cursor_execute", _on_query)
```

`event.remove` is critical — the engine is a session-scoped singleton (because `api_client` is `scope="session"`), so a leaked listener would pollute every subsequent test in the run.

---

## 2. Test client + session plumbing

| Field | Value |
|-------|-------|
| Path | `tests/conftest.py` |
| Symbols | `api_client` fixture, `override_get_db`, `global_cleanup` |
| Line range | **1–71** (`api_client` at **45–53**, `override_get_db` at **37–42**) |
| Importance | HIGH |
| Reason | `api_client` is `scope="session"` (L45) — every test in the run shares one `TestClient(app)` instance. `app.dependency_overrides[generate_session] = override_get_db` replaces FastAPI's session dep with a fresh `SessionLocal()` per request. **This means the engine listener will see every SELECT the route + every internal repo call emits, including auth/middleware queries on the first request of the test.** Therefore the listener must be armed AFTER an initial "warm-up" GET, or the test must subtract the cost of auth/user-loading. Pattern: do an idle `api_client.get(api_routes.recipes, params={"page": 1, "perPage": 1}, headers=user.token)` before `queries.clear()` to flush any first-call lazy-init. |

---

## 3. User / fixture factory

| Field | Value |
|-------|-------|
| Path | `tests/fixtures/fixture_users.py` |
| Symbols | `_unique_user`, `unique_user` (module-scoped), `unique_user_fn_scoped` (function-scoped), `h2_user`, `g2_user`, `build_unique_user` |
| Line range | `build_unique_user` **17–52**, `h2_user` **55–118**, `_unique_user` **179–216**, `unique_user_fn_scoped` **219–221**, `unique_user` **224–226** |
| Importance | **CRITICAL** |
| Reason | The new query-count test should use `unique_user_fn_scoped` (function-scoped — fresh user per parametrize), not the module-scoped `unique_user`, because we are going to seed wildly different recipe counts (10 vs 100) and we want a clean slate per case. `h2_user` (line 55–118, module-scoped) gives us a *second* household in the *same group* — needed for the multitenant isolation assertion (verify `household_id` filtering still works after the refactor). |

| Field | Value |
|-------|-------|
| Path | `tests/utils/fixture_schemas.py` |
| Symbol | `class TestUser` |
| Line range | **9–28** |
| Importance | HIGH |
| Reason | Provides `repos: AllRepositories` (group + household scoped) and the auth `token` dict. `user.repos.recipes.create_many([…])` is the fast bulk-seeding hook (see §4). The `group_id`/`household_id` `@property` accessors return strings, not UUIDs — relevant when crafting `params={"households": [user.household_id]}` query strings. |

---

## 4. Recipe-seeding fixtures and patterns

### Existing fixtures (file-scope)

| Path | Symbol | Line range | Scope | Useful for query-count test? |
|------|--------|------------|-------|---|
| `tests/fixtures/fixture_recipe.py` | `random_recipe` | **108–131** | `function` | Single recipe with 3 ingredients + 3 steps. **Too small** for N+1 measurement. |
| `tests/fixtures/fixture_recipe.py` | `recipe_ingredient_only` | **31–54** | `function` | Single recipe, 6 ingredients. **No tags/categories/tools** — wouldn't exercise the Cartesian path being refactored. |
| `tests/fixtures/fixture_recipe.py` | `recipes_ingredient_only` | **57–85** | `function` | 3 recipes, ingredients only. Same problem — no M:N data. |
| `tests/fixtures/fixture_recipe.py` | `recipe_categories` | **88–104** | `function` | 3 categories, no recipes attached. Useful as a building block to assemble a fully-decorated recipe set. |

**None of the existing fixtures produce a recipe set with non-empty `tags + recipe_category + tools`** — which is exactly the set that triggers the Cartesian product. The new test must build its own seed function.

### The canonical bulk-seed pattern (from existing tests)

| Path | Symbol | Line range | Pattern |
|------|--------|------------|---------|
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` | `test_get_recipes_organizer_filter` | **1530–1588** | **This is the closest blueprint.** Lines 1534–1540 create 3 tags + 3 categories + 3 tools, lines 1542–1557 build a `list[Recipe]` of 40 with assorted M:N decoration, line 1558 calls `database.recipes.create_many(new_recipes_data)`. Reuse this pattern verbatim — it covers the exact shape the refactor must keep fast. |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_recipe_repo_pagination_by_categories` | **138–234** | Per-recipe `database.recipes.create(...)` in a loop (L182–183). Slower than `create_many` but used when you need separately-created `created_at` timestamps. Not needed for the query-count test. |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `search_recipes` fixture | **70–135** | `unique_db.recipes.create_many(recipes)` at L135 — direct repo-level bulk seed. |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` | `test_get_cookbook_recipes` | **1616–1657** | `unique_user.repos.recipes.create_many([Recipe(...) for _ in range(3)])` — the idiomatic spelling for a controller-level (route-driven) test. |

### Recommended seed for the new test

```python
from tests.utils.factories import random_string
from mealie.schema.recipe.recipe import Recipe
from mealie.schema.recipe.recipe_category import CategorySave, TagSave
from mealie.schema.recipe.recipe_tool import RecipeToolSave

def _seed_recipes(user, n: int) -> list[Recipe]:
    db = user.repos
    tags       = db.tags.create_many([TagSave(name=random_string(), group_id=user.group_id)         for _ in range(3)])
    categories = db.categories.create_many([CategorySave(name=random_string(), group_id=user.group_id) for _ in range(3)])
    tools      = db.tools.create_many([RecipeToolSave(name=random_string(), group_id=user.group_id)    for _ in range(3)])
    recipes = [
        Recipe(
            user_id=user.user_id, group_id=user.group_id, name=random_string(),
            tags=tags, recipe_category=categories, tools=tools,
        )
        for _ in range(n)
    ]
    return db.recipes.create_many(recipes)
```

**Each seeded recipe carries 3 tags + 3 categories + 3 tools** ⇒ today's `joinedload` Cartesian = 27 rows fetched per recipe ⇒ at 100 recipes the pre-refactor query returns ~2,700 rows. This is the bound the test should measurably collapse.

---

## 5. Multitenant recipe-visibility tests (regression surface)

| Path | Symbol | Line range | What it asserts |
|------|--------|------------|-----------------|
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` | `test_get_all_recipes_includes_all_households` | **46–70** | `GET /api/recipes` from `unique_user` MUST include recipes owned by `h2_user` (same group, different household). Validates that the `household_id` filter is **NOT** applied implicitly on the list endpoint. |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` | `test_get_all_recipes_with_household_filter` | **73–102** | When `?households=<h2.household_id>` is passed, `unique_user`'s recipes MUST be excluded. Validates the explicit filter path through `_build_recipe_filter` (`repository_recipes.py:335–336`). |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` | `test_cookbook_recipes_includes_all_households` | **313–354** | `?cookbook=<slug>` MUST union recipes across all households in the group. |
| `tests/integration_tests/user_recipe_tests/test_recipe_owner.py` | `test_get_all_only_includes_group_recipes` | **42–57** | Hard contract: response `items[*]` must have `groupId == user.group_id` and `userId == user.user_id`. Catches accidental leakage across **groups** (not households). |

> The dedicated `tests/multitenant_tests/` directory does **not** cover recipes — see `tests/multitenant_tests/test_multitenant_cases.py:13–19`, where `all_cases` lists only `UnitsTestCase, FoodsTestCase, ToolsTestCase, TagsTestCase, CategoryTestCase`. Recipe-specific multi-tenancy lives in `test_recipe_cross_household.py` instead. Don't waste time grepping the multitenant folder for recipe coverage.

---

## 6. Other tests that exercise `RepositoryRecipes.page_all` (full regression list)

| Path | Test(s) | Line range | What they cover |
|------|---------|------------|-----------------|
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_recipe_repo_pagination_by_categories` | **138–234** | category filter, require_all / single, random ordering |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_recipe_repo_pagination_by_tags` | **237–332** | tag filter, require_all / single, random ordering |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_recipe_repo_pagination_by_tools` | **335–429** | tool filter, require_all / single, random ordering |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_recipe_repo_pagination_by_foods` | **432–538** | food/ingredient filter |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_basic_recipe_search` | **540–556** | full-text search against the page_all path |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_fuzzy_recipe_search` | **559–571** | Postgres-only trigram search |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_random_order_recipe_search` | **574–590** | `order_by=random` + `pagination_seed` |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_order_by_last_made` | **593–647** | **`column_aliases["last_made"]` correctness across two households — top risk if a JOIN replaces the scalar subquery.** |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_coalesce_last_made` | **650–688** | coalesce(last_made, 1900-01-01) behavior + filter compatibility |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_order_by_rating` | **691–812** | `column_aliases["rating"]` user-rating vs recipe-rating fallback |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` | `test_get_recipes_organizer_filter` | **1530–1588** | controller-level filter + response shape (parametrized over tags/categories/tools) |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` | `test_get_random_order` | **1591–1613** | controller-level random ordering + seed determinism |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` | `test_get_cookbook_recipes` | **1616–1657** | cookbook query-filter path |
| `tests/unit_tests/schema_tests/test_recipe.py` | `test_recipe_number_sanitation` | **11–40** | `recipe_servings`/`recipe_yield_quantity` validators must keep firing |
| `tests/unit_tests/schema_tests/test_recipe.py` | `test_recipe_string_sanitation` | **43–63** | time-field string coercion must keep firing |

---

## 7. Query-count test scaffolding — concrete recipe for `test_recipe_list_query_count.py`

```python
# tests/integration_tests/test_recipe_list_query_count.py
"""
N+1 regression guard for GET /api/recipes.

Query count must NOT grow with recipe count. With N recipes each carrying
3 tags + 3 categories + 3 tools, the refactored loader_options should emit
exactly:
  * 1 SELECT recipes ... LIMIT N      (the page)
  * 1 SELECT COUNT(*)                  (pagination total)
  * 1 SELECT users ... WHERE id IN (...)         (joinedload(user).load_only(household_id))
  * 1 SELECT categories JOIN recipes_to_categories  (selectinload recipe_category)
  * 1 SELECT tags JOIN recipes_to_tags              (selectinload tags)
  * 1 SELECT tools JOIN recipes_to_tools            (selectinload tools)
= 6 statements regardless of N.  (Plus a few auth/middleware SELECTs on the first request — warm up first.)
"""
import pytest
from sqlalchemy import event
from fastapi.testclient import TestClient

from mealie.db.db_setup import engine
from mealie.schema.recipe.recipe import Recipe
from mealie.schema.recipe.recipe_category import CategorySave, TagSave
from mealie.schema.recipe.recipe_tool import RecipeToolSave
from tests.utils import api_routes
from tests.utils.factories import random_string
from tests.utils.fixture_schemas import TestUser


def _seed_recipes(user: TestUser, n: int) -> None:
    db = user.repos
    tags       = db.tags.create_many([TagSave(name=random_string(), group_id=user.group_id) for _ in range(3)])
    categories = db.categories.create_many([CategorySave(name=random_string(), group_id=user.group_id) for _ in range(3)])
    tools      = db.tools.create_many([RecipeToolSave(name=random_string(), group_id=user.group_id) for _ in range(3)])
    db.recipes.create_many([
        Recipe(
            user_id=user.user_id, group_id=user.group_id, name=random_string(),
            tags=tags, recipe_category=categories, tools=tools,
        )
        for _ in range(n)
    ])


def _count_queries_for(api_client: TestClient, user: TestUser, per_page: int) -> tuple[int, dict]:
    # WARM UP: first call triggers auth / user-lookup queries that we want to exclude.
    api_client.get(api_routes.recipes, params={"page": 1, "perPage": 1}, headers=user.token)

    captured: list[str] = []
    def _on_query(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)
    event.listen(engine, "before_cursor_execute", _on_query)
    try:
        response = api_client.get(
            api_routes.recipes, params={"page": 1, "perPage": per_page}, headers=user.token,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _on_query)

    assert response.status_code == 200
    return len(captured), response.json()


def test_recipe_list_query_count_does_not_grow_with_n(
    api_client: TestClient, unique_user_fn_scoped: TestUser
):
    user = unique_user_fn_scoped

    _seed_recipes(user, 10)
    count_small, body_small = _count_queries_for(api_client, user, per_page=50)
    assert len(body_small["items"]) == 10
    assert body_small["total"] == 10

    _seed_recipes(user, 90)  # now 100 recipes total
    count_large, body_large = _count_queries_for(api_client, user, per_page=200)
    assert len(body_large["items"]) == 100
    assert body_large["total"] == 100

    # Hard contract from spec § 1: query count must not scale with N.
    assert count_large <= count_small + 3, (
        f"N+1 regression: {count_small} queries for 10 recipes, "
        f"{count_large} queries for 100 recipes (full list: {[q[:120] for q in []]})"
    )
    # Upper bound: page (1) + count (1) + user joinedload (1) + 3 selectinloads = 6.
    # Allow a couple of stragglers (settings/pragma) — anything > 10 is definitely O(N).
    assert count_large <= 10, f"Expected ≤ 10 queries for 100 recipes, got {count_large}"
```

### Why this scaffolding (rationale for the writer)

| Choice | Reason | Alternative ruled out |
|--------|--------|------------------------|
| Sync `def`, not `async def` | Engine and `TestClient` are sync (`db_setup.py:38`, `conftest.py:46`). | `async def` + `pytest-asyncio` — plugin not installed, would fail collection. |
| `unique_user_fn_scoped` | Need a clean per-test slate (different recipe counts in same run). | Module-scoped `unique_user` — would inherit state from earlier tests in the same module. |
| `event.listen(engine, "before_cursor_execute", …)` | Mirrors the in-repo pattern in `db_setup.py:15–30` and aligns with SQLAlchemy 2.x event API; the engine is a session-wide singleton, so the listener catches every SQL the route emits. | Per-session `connection.execution_options(…)` — would only see one session's traffic, miss any nested `session_context()` use. |
| `try/finally event.remove(...)` | `api_client` is `scope="session"` (`conftest.py:45`), so a leaked listener would inflate counts for every subsequent test in the run, silently breaking unrelated assertions. | `pytest.fixture(autouse=True)` with teardown — works but adds an extra fixture for a single-use scenario. |
| WARM-UP request before arming | First `api_client.get` triggers `users` / `households` / `settings` lookups via FastAPI deps that have nothing to do with `page_all`. Without warm-up, `count_small` is dominated by 5–10 auth queries. | Subtract a fixed constant — fragile against unrelated middleware changes. |
| `db.recipes.create_many([...])` for seeding | Single INSERT batch, no per-call session refresh, mirrors `test_get_recipes_organizer_filter` at `test_recipe_crud.py:1558`. | Per-recipe `db.recipes.create(...)` loop — adds N additional SELECTs to the seeding phase, doesn't affect the measured count (seeding runs before warm-up) but slower CI. |
| `len(captured) <= count_small + 3` (relative) | Matches the spec's `count_large <= count_small + 3` wording, allowing for one extra `SELECT IN (…)` chunk if `selectinload` batches into 2 chunks at 100 rows. | Exact equality — too brittle against SQLAlchemy's batching heuristics. |
| `count_large <= 10` (absolute) | The spec's `<= 5` is too tight: even the post-refactor path emits page + count + user-joinedload + 3 selectinloads = **6** statements minimum, plus any `SAVEPOINT`/`RELEASE` in transactions. 10 is a safe upper bound that still flags any per-recipe lazy load. | Spec's literal `<= 5` — would fail even the correctly-refactored code. **Flag back to spec author.** |

---

## 8. Tests that MUST still pass unchanged

> "Non-regression scope" for the implementer — every test below must continue to pass without modification. If any one of these breaks, the refactor has changed observable behavior.

### Strict — wire-format / response-shape

| File | Test(s) | Reason it's strict |
|------|---------|--------------------|
| `tests/integration_tests/user_recipe_tests/test_recipe_owner.py` (**42–57**) | `test_get_all_only_includes_group_recipes` | Asserts `groupId`/`userId` keys (camelCase) on `items[*]` |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` (**1530–1588**) | `test_get_recipes_organizer_filter` | Parametrized over tags/categories/tools; asserts `len(items)` and `id` set equality |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` (**1591–1613**) | `test_get_random_order` | Asserts seed determinism + 422 on missing `paginationSeed` |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` (**1616–1657**) | `test_get_cookbook_recipes` | Cookbook `query_filter_string` path |
| `tests/unit_tests/schema_tests/test_recipe.py` (**11–63**) | `test_recipe_number_sanitation`, `test_recipe_string_sanitation` | Field validators must keep firing on `RecipeSummary.model_validate` |

### Strict — multi-tenant isolation (highest blast-radius bugs)

| File | Test(s) | Reason it's strict |
|------|---------|--------------------|
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` (**46–70**) | `test_get_all_recipes_includes_all_households` | Cross-household visibility within same group |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` (**73–102**) | `test_get_all_recipes_with_household_filter` | `?households=` explicit filter |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` (**313–354**) | `test_cookbook_recipes_includes_all_households` | Cookbook union across households |

### Strict — ordering / `column_aliases` correctness

| File | Test(s) | Reason it's strict |
|------|---------|--------------------|
| `tests/unit_tests/repository_tests/test_recipe_repository.py` (**593–647**) | `test_order_by_last_made` | Two-household ordering — if a naive JOIN replaces the scalar subquery, one household's recipes will be invisible or duplicated |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` (**650–688**) | `test_coalesce_last_made` | Coalesce of missing-`last_made` to `1900-01-01` |
| `tests/unit_tests/repository_tests/test_recipe_repository.py` (**691–812**) | `test_order_by_rating` | User-rating fallback to recipe-rating |

### Strict — filter-by-organizer (the M:N tables being refactored)

| File | Test(s) |
|------|---------|
| `tests/unit_tests/repository_tests/test_recipe_repository.py` | `test_recipe_repo_pagination_by_categories` (**138–234**), `test_recipe_repo_pagination_by_tags` (**237–332**), `test_recipe_repo_pagination_by_tools` (**335–429**), `test_recipe_repo_pagination_by_foods` (**432–538**) |

### Run-the-full-suites command

```powershell
# From repo root (mealie/)
uv run pytest tests/unit_tests/repository_tests/test_recipe_repository.py -v
uv run pytest tests/unit_tests/schema_tests/test_recipe.py -v
uv run pytest tests/integration_tests/user_recipe_tests/ -v
# Then the new test
uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v
```

Or use the org convention from `Downloads/mealie/.github/copilot-instructions.md`: `task py:check` for the full lint+format+type+test pipeline.

---

## 9. Cross-perspective questions (for the API perspective)

1. **`RecipeSummary` field order vs. JSON wire order**: Pydantic v2 preserves field-declaration order in `model_dump`. After the refactor, if the writer adds any helper attribute to `RecipeSummary` (e.g. an aggregate-loaded field), it MUST be appended at the bottom or it will reorder the JSON keys and silently break frontend snapshot tests. Confirm there's no clientside dependency on key order in `frontend/`.
2. **`households_id` proxy + `selectinload(user)` interplay**: today's `joinedload(user).load_only(household_id)` is the proxy's data source. If the refactor swaps to `selectinload(user).load_only(household_id)`, that's still 1 query — but is that OK contractually? (i.e. no client expects `userId` and `householdId` to come from a single roundtrip?)
3. **`count_uncategorized`/`count_untagged`** (`mealie/repos/repository_recipes.py:167–181`) and `find_suggested_recipes` (mentioned in API §8) **also instantiate `RecipeSummary`** indirectly. Should the query-count test cover those too, or do we explicitly scope to `GET /api/recipes` only?
4. **`/api/explore/groups/{slug}/recipes`** shares `page_all` (API doc §8). Should there be a sibling query-count test for the explore route, or is the single-test coverage of the shared method enough? Recommend: a 2-line parametrize over `[api_routes.recipes, f"/api/explore/groups/{slug}/recipes"]`.
5. **Spec calls for `<= 5` total queries**; the post-refactor minimum is **6** (page + count + 1 joinedload(user) + 3 selectinloads). Either (a) reduce the joinedload(user) to a column subquery to hit 5, or (b) relax the spec to `<= 10`. The implementer needs the API perspective to confirm whether (a) is contractually acceptable (it affects how `household_id` is materialized).
6. **`EXPLAIN ANALYZE` in PR description**: only meaningful against Postgres; CI runs SQLite. Does the test infrastructure need a Postgres fixture, or will the human PR author run `task py:postgres` locally and paste the output?
7. **`recipe_servings` validator**: the validator (`recipe.py:151–153`) returns `0` for `None`/`""`. If a future optimization streams rows without `model_validate`, this normalization is lost. Confirm the API perspective wants `model_validate` kept in the loop (or wants the validator hoisted into a SQL-level `COALESCE`).
