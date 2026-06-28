# Spec v2 — Case 4: Recipe List N+1 Performance Refactor

> **Intent**: SQL-layer performance refactor of `GET /api/recipes` to eliminate
> the N+1 query growth (currently scales O(unique tools in page)) while keeping
> the response payload, pagination semantics, and multi-tenant filters
> byte-identical for the same persisted rows.
>
> **Approach** (`approach\selected.md`): extend `RecipeSummary.loader_options()`
> at `mealie/schema/recipe/recipe.py:168-175` to convert M2M `joinedload`s to
> `selectinload`s and chain `selectinload(Tool.households_with_tool)` off the
> `tools` loader. Keep `joinedload(RecipeModel.user).load_only(User.household_id)`
> for the `AssociationProxy`. Add a new sync regression test
> `tests/integration_tests/test_recipe_list_query_count.py`.
>
> **Authoritative consolidation**: `exploration\consolidated.md`.
>
> **Iteration**: v2 — resolves all CRITICAL+HIGH issues from `review_v1_architecture.md`,
> `review_v1_completeness.md`, `review_v1_consistency.md`, `review_v1_executability.md`.
> Issue-by-issue resolution table in `spec_iterations\rewrite_v1_to_v2.md`.

---

## User stories

### US-1 (P1) — Backend developer: response payload unchanged
**As** a Mealie backend developer responsible for client compatibility,
**I want** the `GET /api/recipes` JSON response — field set, field declaration
order, camelCase aliases (`orgURL` special-case included), nested item field
order, and pagination envelope (`page`, `perPage`, `total`, `totalPages`,
`items`, `next`, `previous`) — to be **identical to the pre-refactor baseline
when measured against the same persisted rows** (i.e. same database state,
same query parameters), modulo the nested-array element-order normalization
strategy declared in FR-014,
**so that** existing UI consumers (`RecipeCard`, `RecipeCardMobile`,
`RecipeCardSection.vue:119-127, 144-152`), command-K search
(`RecipeDialogSearch.vue:59-63`), and generated TypeScript types
(`frontend/app/lib/api/types/recipe.ts:310-336`) keep working without
regeneration.

**Acceptance**: a deterministic JSON comparison between pre- and post-refactor
responses on the same seeded dataset (per FR-014's seam) returns `[]` (no
diffs) for keys, key order, and values. See FR-001, FR-002, FR-014, SC-002.

### US-2 (P1) — Backend developer: query count constant in recipe count
**As** a Mealie backend developer triaging the "All Recipes" page slowness in
libraries with 100+ recipes,
**I want** the SQL statement count emitted by `GET /api/recipes` to be a
small constant relative to the number of recipes returned (subject only to
the SQLAlchemy IN-list chunking formula in FR-009),
**so that** page latency no longer scales linearly with library size, and
future regressions are caught deterministically.

**Acceptance**: `count(queries for 100 recipes) <= count(queries for 10 recipes) + 3`
AND `count(queries for 100 recipes) <= 8` for the regression-test parameter
window (`perPage <= 200`, 3 tags/3 categories/3 tools per recipe). See
FR-003..FR-006, FR-009, SC-001.

### US-3 (P2) — Backend developer: existing tests still green
**As** a Mealie backend developer running `task py:check` before opening the PR,
**I want** every existing unit, integration, and multi-tenant test that
touches `RepositoryRecipes.page_all` and `RecipeSummary` to pass without
modification,
**so that** the refactor's correctness is verified by the existing regression
surface (response shape, multi-household filtering, organizer filtering, sort
ordering, validator coercion).

**Acceptance**: `task py:test` exits 0 with no new skips, no new xfails, and
no new warnings. The exhaustive must-pass file enumeration is FR-015 (file
appendix). The strict regression list from `exploration\test_perspective.md` §8
all pass. See FR-013, FR-015, SC-003.

### US-4 (P2) — Backend developer: regression-test guard for future N+1
**As** a Mealie backend developer protecting the recipe list path against
future regressions (e.g., adding a new lazy relationship to `RecipeSummary`),
**I want** a new test
`tests/integration_tests/test_recipe_list_query_count.py` (NEW FILE) that arms
a SQLAlchemy `before_cursor_execute` listener on the shared `engine`, runs the
warm-up + measured `GET /api/recipes` flow at two recipe-count scales (10 and
100), and asserts the query count does not grow,
**so that** a careless re-introduction of a `joinedload`-on-M2M with `LIMIT`
or a missing chained `selectinload` fails CI deterministically.

**Acceptance**: `uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v`
passes; the test is a plain sync `def`, uses `unique_user_fn_scoped`, attaches
the listener with `event.listen(engine, "before_cursor_execute", _on_query)`
inside a `try/finally event.remove(...)` block to avoid session-scope
leakage, warms up before measuring, and measures with `perPage=50` then
`perPage=200`. See FR-010, SC-005.

---

## Functional requirements

### FR-001 — Preserve exact `RecipeSummary` response field set, order, and aliases
The set, declaration order, and camelCase aliases of fields on each
`items[*]` element of the `GET /api/recipes` response must be unchanged from
the pre-refactor baseline. The exact post-camelize wire fields are:

```
id, userId, householdId, groupId,
name, slug, image, recipeServings, recipeYieldQuantity, recipeYield,
totalTime, prepTime, cookTime, performTime,
description,
recipeCategory[]  (each: {id, name, slug, groupId}),
tags[]            (each: {id, name, slug, groupId}),
tools[]           (each: {id, name, slug, groupId, householdsWithTool[]}),
rating, orgURL,
dateAdded, dateUpdated, createdAt, updatedAt, lastMade
```

`orgURL` is a special-cased Pydantic alias
(`Field(alias="orgURL")`) — must NOT be re-camelized.
`MealieModel.model_config` (`mealie/schema/_mealie/mealie_model.py:53`)
provides `alias_generator=camelize, populate_by_name=True`.
**Note (resolves NC-004)**: the field `slug_image` enumerated in
`input.md:23` does not exist on `RecipeSummary` and never has — preserving the
current contract means keeping `slug` (line 125) and `image` (line 126) and
**not** adding `slug_image`. No fields are added or removed.

**code_references**: `mealie/schema/recipe/recipe.py:116-149` (`RecipeSummary`
field declarations including `tools: list[RecipeTool] = []` and the explicit
`org_url: str | None = Field(None, alias="orgURL")` on line 141);
`mealie/routes/recipe/recipe_crud_routes.py:392` (serialization via
`orjson.dumps(pagination_response.model_dump(by_alias=True))`);
`frontend/app/lib/api/types/recipe.ts:310-336` (current 26-field TS contract).

### FR-002 — Preserve pagination behavior
The `PaginationBase[RecipeSummary]` envelope keys `page`, `perPage`, `total`,
`totalPages`, `items`, `next`, `previous` must be returned with the same
semantics: `total` = unique recipe count matching filters,
`totalPages = ceil(total / perPage)`, `perPage=-1` → "all rows",
`page=-1` → "last page", and `next` / `previous` URLs built by
`set_pagination_guides`. The "apply options late" invariant must be preserved
(loader options are attached **after** `add_pagination_to_query`).

**code_references**: `mealie/repos/repository_generic.py:357-405`
(`add_pagination_to_query` — COUNT subquery L376-377, perPage=-1 handling
L382-385, total_pages L388, page=-1 L392-394);
`mealie/repos/repository_recipes.py:274,277,280` (the canonical
"add_pagination_to_query → `.options(...)` → `session.execute(...)` sequence");
`mealie/routes/recipe/recipe_crud_routes.py:387-390`
(`set_pagination_guides`); `mealie/schema/response/pagination.py:51-94`
(`PaginationBase`).

### FR-003 — Eager-load `recipe_category` via `selectinload`
Replace `joinedload(RecipeModel.recipe_category)` with
`selectinload(RecipeModel.recipe_category)` in `RecipeSummary.loader_options()`.
Rationale: `recipe_category` is M2M via `recipes_to_categories`; combining
joinedload-on-collection with `LIMIT/OFFSET` causes SQLAlchemy to fall back
to a subquery+OUTER JOIN strategy with cartesian-product row inflation
(observable via the load-bearing `.scalars().unique().all()` at
`repository_recipes.py:280`). `selectinload` issues a follow-up
`SELECT … FROM categories JOIN recipes_to_categories WHERE recipes_to_categories.recipe_id IN (...)`
as one extra statement (subject to FR-009 chunking formula) regardless of
page size.

**code_references**: `mealie/schema/recipe/recipe.py:171` (current line);
`mealie/db/models/recipe/recipe.py:98-100` (`recipe_category` relationship
via `recipes_to_categories`); `mealie/db/models/recipe/category.py:35-41`
(`recipes_to_categories` table — `recipe_id` and `category_id` both indexed;
no migration needed).

### FR-004 — Eager-load `tags` via `selectinload`
Replace `joinedload(RecipeModel.tags)` with `selectinload(RecipeModel.tags)`
in `RecipeSummary.loader_options()`. Same rationale as FR-003.

**code_references**: `mealie/schema/recipe/recipe.py:172` (current line);
`mealie/db/models/recipe/recipe.py:138` (`tags` relationship via
`recipes_to_tags`); `mealie/db/models/recipe/tag.py:19-25`
(`recipes_to_tags` table — `recipe_id` and `tag_id` indexed).

### FR-005 — Eager-load `tools` via `selectinload`
Replace `joinedload(RecipeModel.tools)` with `selectinload(RecipeModel.tools)`
in `RecipeSummary.loader_options()`. Same rationale as FR-003.

**code_references**: `mealie/schema/recipe/recipe.py:173` (current line);
`mealie/db/models/recipe/recipe.py:101` (`tools` relationship via
`recipes_to_tools`); `mealie/db/models/recipe/tool.py:25-31`
(`recipes_to_tools` table).

### FR-006 — Chain `selectinload(Tool.households_with_tool)` off the `tools` loader
Chain `selectinload(Tool.households_with_tool)` off the
`selectinload(RecipeModel.tools)` loader so the loader entry becomes:

```python
selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)
```

Rationale: `RecipeTool.households_with_tool` is `list[str]` populated by a
`@field_validator("households_with_tool", mode="before")` that iterates
`household.slug for household in v`. `Tool.households_with_tool` is a
default-`lazy="select"` M2M relationship. Without the chained `selectinload`,
every unique tool in the page triggers one `SELECT FROM households JOIN
households_to_tools WHERE tool_id = ?` during
`pagination_response.model_dump(by_alias=True)` — **this is the dominant
N+1**. Prior art for the exact pattern lives in `RecipeToolOut.loader_options`
and `IngredientFood.loader_options`.

**code_references**: `mealie/schema/recipe/recipe.py:83-95` (`RecipeTool` +
`convert_households_to_slugs` validator that triggers the lazy load);
`mealie/db/models/recipe/tool.py:54-56` (`Tool.households_with_tool` M2M
relationship — default `lazy="select"`);
`mealie/db/models/recipe/tool.py:17-23` (`households_to_tools` table —
`household_id` and `tool_id` indexed);
`mealie/schema/recipe/recipe_tool.py:36-39` (prior art:
`selectinload(Tool.households_with_tool)`);
`mealie/schema/recipe/recipe_ingredient.py:117-123` (symmetric prior art for
`IngredientFood.households_with_ingredient_food`).

### FR-007 — Preserve `joinedload(RecipeModel.user).load_only(User.household_id)`
The fourth loader entry must remain
`joinedload(RecipeModel.user).load_only(User.household_id)`. Rationale:
`RecipeModel.household_id` is an `AssociationProxy` through `user`
(`association_proxy("user", "household_id")`); the proxy resolution requires
`recipe.user` to be resident on the row. Dropping this loader silently
regresses to a per-row lazy load on `recipe.user.household_id` during
`RecipeSummary.model_validate` — re-introducing the very N+1 the spec is
eliminating, just shifted to a different relationship. A 1:1 `joinedload`
adds no cartesian risk.

**code_references**: `mealie/schema/recipe/recipe.py:174` (current line);
`mealie/db/models/recipe/recipe.py:55-56` (the `AssociationProxy`);
`mealie/db/models/recipe/recipe.py:59` (`user` 1:1 relationship —
`orm.relationship("User", uselist=False, foreign_keys=[user_id])`).

### FR-008 — Preserve the "apply options late" invariant
`RepositoryRecipes.page_all` must continue to call
`q = q.options(*RecipeSummary.loader_options())` **after**
`add_pagination_to_query(q, pagination_result)` and **before**
`self.session.execute(q)` — i.e., the line ordering at
`mealie/repos/repository_recipes.py:274,277,280` is unchanged. The COUNT
subquery at `repository_generic.py:376-377`
(`select(func.count()).select_from(query.order_by(None).distinct().subquery())`)
must NOT see loader options, otherwise `total` regresses (commit `7b325082`).
Implementation note: this requirement is satisfied automatically by editing
only `loader_options()` and leaving `page_all` unchanged.

**code_references**: `mealie/repos/repository_recipes.py:274,277,280`
(load-bearing sequence: `add_pagination_to_query` at 274, then
`q.options(*RecipeSummary.loader_options())` at 277, then
`session.execute(q).scalars().unique().all()` at 280);
`mealie/repos/repository_generic.py:341-342` (mantra "Apply options late, so
they do not get used for counting");
`mealie/repos/repository_generic.py:376-377` (COUNT subquery).

### FR-009 — Query-count bound — formula plus regression-test budget
The number of cursor executes emitted by `engine.execute` during a
`GET /api/recipes?perPage={N}` call (after the per-session warm-up) must be
bounded as follows:

(a) **Formula bound** — the only growth allowed is via SQLAlchemy's IN-list
chunking. With default `selectin_loader.IN_BULK = 500`, the worst-case
statement count is:

```
statements = 2                                  # COUNT subquery + parent SELECT (incl. joinedload(user))
           + chunks_of_recipe_ids(N)            # selectinload(recipe_category)  (≥1)
           + chunks_of_recipe_ids(N)            # selectinload(tags)              (≥1)
           + chunks_of_recipe_ids(N)            # selectinload(tools)             (≥1)
           + chunks_of_tool_ids(T)              # selectinload(Tool.households_with_tool) (1 if any tool loaded, else 0)

where chunks_of_X(M) = ceil(M / 500) when M > 0 else 0
      T = number of distinct Tool rows loaded by the previous step
```

The post-refactor **minimum is 6** (1 COUNT + 1 parent SELECT + 3 single-chunk
M2M selectinloads + 1 chained households selectinload). It rises to **9** the
first time any M2M chunk splits (501-1000 child IDs) and to **10** if the
chained `Tool.households_with_tool` step also splits (501-1000 Tool IDs).

(b) **Regression-test budget** — for the FR-010 test parameters (10 then 100
recipes, each with 3 tags / 3 categories / 3 tools, `perPage=50` then
`perPage=200`):
- `chunks_of_recipe_ids(100) = 1` (100 ≤ 500),
- `chunks_of_tool_ids(≤300) = 1` (300 ≤ 500),
- expected minimum = 6, ceiling asserted = **`<= 8`** (absorbs middleware /
  savepoint noise),
- relative bound asserted = `count_large <= count_small + 3`.

(c) **`perPage > 200` is out of FR-010 scope** — the regression test must
stay under the 500-row chunking threshold so the absolute ceiling stays
predictable. Out-of-scope larger pages are bounded only by the formula in
(a). Spec ceiling `<= 5` from `input.md:67-68` is **infeasible** (provably
≥ 6) — formally relaxed in NC-003.

**code_references**: `mealie/schema/recipe/recipe.py:168-175` (loader options
that produce the 4 child SELECTs);
`mealie/repos/repository_recipes.py:274,277,280` (COUNT + parent SELECT
execution); `mealie/repos/repository_generic.py:376-377` (COUNT subquery);
`exploration/consolidated.md:50-75` (full statement trace, §3).

### FR-010 — New regression test `tests/integration_tests/test_recipe_list_query_count.py` (NEW FILE)
Add a NEW FILE at `tests/integration_tests/test_recipe_list_query_count.py`
containing a sync `def` test that:

1. Imports the global `engine` from `mealie.db.db_setup`.
2. Uses the function-scoped fixture `unique_user_fn_scoped` for a clean per-test slate.
3. Seeds N recipes (10 then +90), each decorated with exactly 3 tags + 3 categories
   + 3 tools, using the bulk pattern `db.recipes.create_many([Recipe(...), ...])`
   modelled on `tests/integration_tests/user_recipe_tests/test_recipe_crud.py:1534-1558`.
4. **Warms up** the test client with one throwaway
   `api_client.get(api_routes.recipes, params={"page": 1, "perPage": 1}, headers=user.token)`
   call before arming the listener (FastAPI dependency injection emits ~5
   auth/user-resolution queries on cold-cache that would otherwise dominate
   `count_small`).
5. Attaches `event.listen(engine, "before_cursor_execute", on_query)` inside a
   `try/finally event.remove(...)` block to avoid leakage across the
   session-scoped `api_client` fixture.
6. **Measures with `params={"page": 1, "perPage": 50}` after 10 rows
   (`count_small`) and `params={"page": 1, "perPage": 200}` after 100 rows
   (`count_large`)** — both stay below the 500-row IN-list chunking threshold
   per FR-009.
7. Asserts (i) `len(body["items"])` matches the seeded count under the
   `perPage` limit; (ii) `body["total"]` equals the persisted recipe count;
   (iii) `count_large <= count_small + 3`; (iv) `count_large <= 8`.
8. Is a plain sync `def` — **not** `async def`. Justification: Mealie's
   `api_client` fixture is `starlette.testclient.TestClient` (sync), the
   shared `engine` is built by `sa.create_engine(...)` (sync), and every
   existing `test_recipe_*.py` integration test in
   `tests/integration_tests/user_recipe_tests/` is sync `def`. Although
   `pytest-asyncio==1.4.0` is in `pyproject.toml:72`, applying `@pytest.mark.asyncio`
   here would force-wrap the sync TestClient in an event loop with no
   benefit. **Do not use `async def` or `@pytest.mark.asyncio`.**

**code_references**: `mealie/db/db_setup.py:38,45` (sync `engine` global from
`sa.create_engine`); `tests/conftest.py:45-49` (session-scoped sync
`api_client` using `TestClient(app)`);
`tests/fixtures/fixture_users.py:219-221` (`unique_user_fn_scoped`);
`tests/utils/api_routes/__init__.py:138` (`recipes = "/api/recipes"`);
`tests/integration_tests/user_recipe_tests/test_recipe_crud.py:1534-1558`
(bulk `create_many` pattern with M2M decoration);
`exploration/test_perspective.md:175-264` (full scaffolding, §7).

### FR-011 — Shared loader benefits adjacent endpoints
Editing `RecipeSummary.loader_options()` transitively fixes every call site
of `RepositoryRecipes.page_all` and any other location that splats
`RecipeSummary.loader_options()`. The two **user-facing list endpoints**
covered are:

- `GET /api/recipes` (`mealie/routes/recipe/recipe_crud_routes.py:340-395`) — primary.
- `GET /api/explore/groups/{group_slug}/recipes` (`mealie/routes/explore/controller_public_recipes.py:30-92`) — public/cross-household. Same `page_all` path with an injected `query_filter` for `household.preferences.privateHousehold = FALSE AND settings.public = TRUE`.

Two non-user-facing/secondary callers also benefit transitively:

- `GET /organizers/categories/slug/{category_slug}` (`mealie/routes/organizers/controller_categories.py:131-134`) — uses `per_page=-1`.
- `cross_household_recipes.page_all` from `controller_mealplan.py:65` — random-pick.

`GET /api/users/{id}/favorites` (and `/ratings`) does **not** share this code
path — it returns `UserRatingOut` records via a different repository
(`mealie/routes/users/ratings.py:44-52`), so it is **explicitly out of scope**.

Regression-test scope is `/api/recipes` only (per `input.md:19`); an
optional sibling assertion for the explore endpoint is captured as
`self_concerns SC-E`.

**code_references**: `mealie/routes/recipe/recipe_crud_routes.py:340-395`
(primary `get_all` controller; `page_all` call at L370);
`mealie/routes/explore/controller_public_recipes.py:30-92` (explore
controller; `page_all` call at L67-80; public filter at L61-65);
`mealie/routes/organizers/controller_categories.py:131-134` (`per_page=-1`
category-page call site);
`mealie/routes/households/controller_mealplan.py:60-73` (random-pick call site);
`mealie/routes/users/ratings.py:44-52` (favorites/ratings — out of scope).

### FR-012 — Multi-tenant safety preserved
The household/group filter chain must remain enforced on the parent SELECT.
Specifically:

- `sa.select(self.model).filter(self.model.household_id.is_not(None))`
  (`repository_recipes.py:238`) — the secondary safety filter introduced in
  commit `d02023e1`.
- `_build_recipe_filter` (`repository_recipes.py:295-337`) — appends
  `RecipeModel.group_id == self.group_id` and (when set)
  `RecipeModel.household_id == self.household_id`, plus the explicit
  `households=[...]` query-param filter via
  `RecipeModel.household_id.in_(households)` at L335-336.

`selectinload` does NOT add JOINs to the parent SELECT (it issues separate
follow-up `SELECT … WHERE recipe_id IN (...)` statements), so these filters
are preserved. The follow-up selectinload statements load child rows **for
already-filtered recipes** — no cross-household or cross-group leakage is
possible. Verified by the existing tests in
`tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102`
and `:313-354`.

**code_references**: `mealie/repos/repository_recipes.py:238`
(`household_id IS NOT NULL`); `mealie/repos/repository_recipes.py:295-337`
(`_build_recipe_filter`);
`tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102`
(strict multi-household tests that must still pass);
`tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:313-354`
(`test_cookbook_recipes_includes_all_households`).

### FR-013 — `rating` and `last_made` remain correlated scalar subqueries (used for filtering/ordering only)
The user-correlated `column_aliases["rating"]` (`_get_rating_col_alias` at
`repository_recipes.py:72-93`) and `column_aliases["last_made"]`
(`_get_last_made_col_alias` at `repository_recipes.py:54-70`) are **not
modified**. They are correlated scalar subqueries used by
`QueryFilterBuilder.filter_query` and `add_order_attr_to_query` for
**query-level filtering and ordering only** — they emit zero extra cursor
executes per row. They are armed by `by_user(user_id)`
(`repository_recipes.py:49-52`) which the controller already calls
(`recipe_crud_routes.py:370`).

**The serialized `RecipeSummary.rating` value comes from the loaded
`RecipeModel.rating` ORM attribute** (`mealie/db/models/recipe/recipe.py:61`,
`sa.Float`) — not from the alias. Implementers must not change the
projection. Replacing the column aliases with JOINs would inflate rows and
break `test_order_by_last_made`
(`tests/unit_tests/repository_tests/test_recipe_repository.py:593-647`) and
`test_order_by_rating` (L691-812). This requirement explicitly forbids
introducing a new aggregate field (e.g., `comments_count`) — `RecipeSummary`'s
field set is locked by FR-001.

**code_references**: `mealie/repos/repository_recipes.py:39-93`
(`column_aliases`, `by_user`, `_get_last_made_col_alias`,
`_get_rating_col_alias`); `mealie/repos/repository_generic.py:370`
(filter consumer of `column_aliases`);
`mealie/repos/repository_generic.py:407-430,432-450` (`add_order_attr_to_query` /
`add_order_by_to_query` consumers);
`mealie/db/models/recipe/recipe.py:61` (scalar `Float` column that the
projection actually reads);
`tests/unit_tests/repository_tests/test_recipe_repository.py:593-812`
(must-still-pass tests).

### FR-014 — Response-equivalence assertion seam (NEW — addresses ARCH-H-001, COMP-H-001)
The new test file `tests/integration_tests/test_recipe_list_query_count.py`
(FR-010) must additionally include a **response-shape equivalence assertion**
on the 100-recipe response body, structured as follows:

1. **Pagination envelope key order**: assert
   `list(body.keys()) == ["page", "perPage", "total", "totalPages", "items", "next", "previous"]`.
2. **Per-item field set**: assert
   `set(body["items"][0].keys()) == EXPECTED_RECIPE_SUMMARY_KEYS`, where
   `EXPECTED_RECIPE_SUMMARY_KEYS` is the literal frozen set of 26 camelized
   names enumerated in FR-001 (`id, userId, householdId, groupId, name,
   slug, image, recipeServings, recipeYieldQuantity, recipeYield, totalTime,
   prepTime, cookTime, performTime, description, recipeCategory, tags,
   tools, rating, orgURL, dateAdded, dateUpdated, createdAt, updatedAt,
   lastMade`).
3. **Per-item field declaration order**: assert
   `list(body["items"][0].keys()) == EXPECTED_RECIPE_SUMMARY_KEYS_IN_ORDER`,
   matching the declaration order in `mealie/schema/recipe/recipe.py:116-149`
   under the camelize alias generator.
4. **Nested-array element field set**: for `recipeCategory[0]`, `tags[0]`,
   `tools[0]`, assert
   `set(...) == {"id", "name", "slug", "groupId"}` for the first two and
   `set(...) == {"id", "name", "slug", "groupId", "householdsWithTool"}` for
   tools.
5. **Nested-array element-order normalization (addresses ARCH-H-001)**: M2M
   relationships `recipe_category`, `tags`, `tools` have no `order_by` on the
   ORM side (`mealie/db/models/recipe/recipe.py:98-101,138`). The refactor
   may therefore legitimately change the order in which child rows are
   returned within each `items[*]` nested array. The assertion seam must
   normalize by **sorting each nested array by the child's `id` field
   pre-comparison** on both pre- and post-refactor responses, then assert
   equality of the sorted sequences. This explicitly accepts that nested
   array order is not part of the public contract and must not be relied
   upon by clients.

The implementer captures the pre-refactor response by running the same test
seed against `main` once, persisting the sorted JSON to a fixture file (or
recomputing in-process from a `from_baseline(...)` helper), and then asserts
the post-refactor sorted JSON matches.

**code_references**: `mealie/schema/recipe/recipe.py:116-149` (canonical
field declaration order);
`mealie/routes/recipe/recipe_crud_routes.py:392`
(`model_dump(by_alias=True)` serialization);
`mealie/db/models/recipe/recipe.py:98-101,138` (M2M relationships without
`order_by`); `mealie/schema/response/pagination.py:51-58` (envelope key
declaration order).

### FR-015 — Exhaustive must-pass test-file appendix (NEW — addresses COMP-H-002)
The complete must-pass test surface required by `input.md:28-33` is **every
file in the appendix below**. The implementer must run `task py:test` (or
equivalently the listed `uv run pytest` commands) and confirm exit code 0 on
the union of these files with zero new failures, skips, xfails, or
warnings, in addition to the new FR-010 file.

**Unit tests (recipe-touching)**:

- `tests/unit_tests/test_recipe_export_types.py`
- `tests/unit_tests/test_recipe_parser.py`
- `tests/unit_tests/schema_tests/test_recipe.py`
- `tests/unit_tests/repository_tests/test_recipe_repository.py`

**Integration tests (recipe-touching) — every file in `tests/integration_tests/user_recipe_tests/`**:

- `tests/integration_tests/user_recipe_tests/test_recipe_bulk_action.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_bulk_import.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_comments.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_create_from_openai.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_create_from_video.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_crud.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_export_as.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_foods.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_image_assets.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_ingredients.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_owner.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_ratings.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_share_tokens.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_steps.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_suggestions.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_timeline_events.py`
- `tests/integration_tests/user_recipe_tests/test_recipe_units.py`

**Integration tests (other recipe-relevant files)**:

- `tests/integration_tests/recipe_migration_tests/test_recipe_migrations.py`
- `tests/integration_tests/public_explorer_tests/test_public_recipes.py` (covers the explore endpoint FR-011 path)
- `tests/integration_tests/user_household_tests/test_group_recipe_actions.py`

**Multitenant tests** — `tests/multitenant_tests/` contains no `test_recipe_*.py` filename, but `tests/multitenant_tests/test_multitenant_cases.py` parametrizes over `case_categories.py`, `case_tags.py`, `case_tools.py`, `case_foods.py` (each imports `RecipeCategory`/`RecipeTag`/`RecipeTool`/`IngredientFood` schemas at L3-4). Required:

- `tests/multitenant_tests/test_multitenant_cases.py` (all parametrizations including `case_categories`, `case_tags`, `case_tools`, `case_foods`)

**Verification commands** (Windows PowerShell):

```powershell
uv run pytest tests/unit_tests/test_recipe_export_types.py tests/unit_tests/test_recipe_parser.py tests/unit_tests/schema_tests/test_recipe.py tests/unit_tests/repository_tests/test_recipe_repository.py -v
uv run pytest tests/integration_tests/user_recipe_tests/ -v
uv run pytest tests/integration_tests/recipe_migration_tests/test_recipe_migrations.py tests/integration_tests/public_explorer_tests/test_public_recipes.py tests/integration_tests/user_household_tests/test_group_recipe_actions.py -v
uv run pytest tests/multitenant_tests/test_multitenant_cases.py -v
uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v
```

All five commands must exit 0.

**code_references**: `tests/unit_tests/test_recipe_export_types.py`,
`tests/unit_tests/test_recipe_parser.py`,
`tests/unit_tests/schema_tests/test_recipe.py`,
`tests/unit_tests/repository_tests/test_recipe_repository.py`,
all 19 files under `tests/integration_tests/user_recipe_tests/`,
`tests/integration_tests/recipe_migration_tests/test_recipe_migrations.py`,
`tests/integration_tests/public_explorer_tests/test_public_recipes.py`,
`tests/integration_tests/user_household_tests/test_group_recipe_actions.py`,
`tests/multitenant_tests/test_multitenant_cases.py`,
`tests/multitenant_tests/case_categories.py:3-4`,
`tests/multitenant_tests/case_tags.py:3-4`,
`tests/multitenant_tests/case_tools.py:3-4`,
`tests/multitenant_tests/case_foods.py:3`.

---

## Success criteria

### SC-001 — Query-count growth is bounded by a constant
`count(queries for 100 recipes) - count(queries for 10 recipes) <= 3`
(asserted in `test_recipe_list_query_count.py` per FR-010 with `perPage=50`
then `perPage=200`). Today, this difference is approximately
`|distinct tools in 100 recipes|` ≈ 70-90; post-refactor it is 0
(selectinload IN-list grows, statement count does not), modulo SQLAlchemy
chunking which is held constant inside the FR-010 parameter window.

**Verification**:
```powershell
uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v
```
Exits 0; the parametrized growth and absolute assertions both pass.

### SC-002 — Response shape diff against pre-refactor baseline = 0 (normalized)
Pre- and post-refactor JSON responses for the same persisted dataset (same
user, same query parameters, same database state) compare equal after the
FR-014 normalization (sort nested arrays by child `id`; preserve top-level
key order and per-item key order verbatim). The 26 wire fields of
`RecipeSummary` and the seven pagination envelope keys are unchanged. The
comparison is **normalized**, not byte-identical: the regression test does
not re-seed between the pre- and post-refactor measurements, and any volatile
timestamp / random-UUID field that does happen to differ does so only when
the test seed itself changes — which is forbidden by the FR-014 protocol.

**Verification**: FR-014's assertion block in
`tests/integration_tests/test_recipe_list_query_count.py` plus existing
tests in `test_recipe_owner.py:42-57`, `test_recipe_crud.py:1530-1657`, and
`test_recipe_cross_household.py:46-354` (which assert on field names,
values, and counts) all pass without modification.

### SC-003 — Existing test count passing unchanged
`task py:test` exit code 0; FR-015's exhaustive must-pass file list all
passes; no test is skipped, xfailed, or modified; no new pytest warnings
emitted.

**Verification**: the five `uv run pytest` commands in FR-015 each exit 0
with zero diff against pre-refactor pass/skip/xfail/warning counts.

### SC-004 — Latency improvement documented (no hard p95 SLA)
PR description includes a before/after table with query count for 100 recipes
(captured by enabling the same `before_cursor_execute` listener manually) and
an EXPLAIN ANALYZE on the parent SELECT for the 100-recipe case. **No
absolute p95 SLA is asserted** because Mealie's test suite has no baseline
benchmark to compare against. The implementer is required only to publish
the numbers, not to hit a specific milliseconds target. This is explicit per
`input.md:73-75` which requires "before/after query count comparison" and
"before/after EXPLAIN ANALYZE" but no p95 SLA.

**Verification**: PR description body contains a fenced-code-block table
with `before: ~92 queries (50 recipes), after: 6 queries` for the 100-recipe
case, plus an EXPLAIN ANALYZE text dump (Postgres preferred per
`task py:postgres`; SQLite acceptable with a note that the test DB is
SQLite by default per `mealie/db/db_setup.py:38`).

### SC-005 — New regression test exists and passes
`tests/integration_tests/test_recipe_list_query_count.py` exists (NEW FILE
per FR-010), is collected by pytest (no collection errors), and passes
locally and in CI.

**Verification**:
```powershell
uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v
```
Exit code 0; at least one test reported as passed.

### SC-006 — No new SQL warnings in logs
Running `task py:test` does not emit any new SQLAlchemy warnings (e.g.
`SAWarning: Loader strategy ... will be overridden`, `Cartesian product
warning`, `Cannot correlate ...`). Compare warning counts before/after.

**Verification**:
```powershell
uv run pytest tests/ 2>&1 | Select-String -Pattern "SAWarning"
```
Returns the same count pre- and post-refactor.

### SC-007 — Explore endpoint shares the fix (no code duplication)
A single `RecipeSummary.loader_options()` definition serves both
`GET /api/recipes` and `GET /api/explore/groups/{group_slug}/recipes`. No
parallel loader graph is added to the explore controller.

**Verification**:
```powershell
Get-ChildItem -Path mealie -Recurse -File -Include *.py | Select-String -Pattern "selectinload\(Tool\.households_with_tool\)"
```
Returns occurrences only in `mealie/schema/recipe/recipe.py` (new, from
FR-006) and `mealie/schema/recipe/recipe_tool.py` (existing prior art).
Specifically must NOT appear in `mealie/routes/explore/`,
`mealie/routes/recipe/`, or `mealie/services/`.

### SC-008 — Nested-array order is explicitly normalized (NEW — addresses ARCH-H-001)
The FR-014 assertion seam sorts nested arrays
(`items[*].recipeCategory`, `items[*].tags`, `items[*].tools`) by child `id`
before comparison. The PR description explicitly documents that nested-array
order within `items[*]` is **not** part of the public contract and may
change under `selectinload`. UI consumers
(`RecipeCard`, `RecipeCardMobile`, `RecipeCardSection.vue:119-127, 144-152`)
do not depend on nested-array order; the command-K search
(`RecipeDialogSearch.vue:59-63`) only reads
`name`/`slug`/`description`/`image`/`rating`.

**Verification**: the FR-014 normalized assertion in
`test_recipe_list_query_count.py` passes against the seeded dataset. PR
description includes a "Wire-contract notes" paragraph naming the
normalization protocol.

---

## Edge cases

### EC-001 — Empty recipe list
`GET /api/recipes` for a user whose household/group has zero recipes returns
`{"items": [], "total": 0, "totalPages": 0, "page": 1, "perPage": 50, "next": null, "previous": null}`.
Query count: 1 COUNT (returns 0) + 1 parent SELECT (returns 0 rows) +
**0** follow-up selectinloads (each IN-list is empty → SQLAlchemy elides the
statement) = **2 statements**. Within FR-009 bound.

### EC-002 — Single recipe with no organizers (`tags=[]`, `recipe_category=[]`, `tools=[]`)
Selectinloads for `recipe_category`, `tags`, `tools` issue with IN-list
`(recipe_id,)` and each returns zero child rows. The chained
`selectinload(Tool.households_with_tool)` is **elided** because the preceding
`tools` selectinload returned no `Tool` rows. The benign 1:1
`joinedload(RecipeModel.user)` is part of the parent SELECT (not a separate
cursor execute). Query count: 1 COUNT + 1 parent SELECT (with joined user) +
1 categories selectinload + 1 tags selectinload + 1 tools selectinload =
**5 statements** (not 6 — corrected from v1). Within FR-009 bound.

### EC-003 — Recipe with non-empty M2M but empty `Tool.households_with_tool`
A tool created without any `households_with_tool` (default `[]` per
`Tool.__init__` at `mealie/db/models/recipe/tool.py:78-80`). The chained
selectinload issues with the tool's ID in the IN-list, returns zero
`households` rows — still **1 statement** (not elided, because a non-empty
parent IN-list still emits the SQL even when result is empty). Validator
`convert_households_to_slugs` returns `[]` (the `if not v: return []`
branch at `schema/recipe/recipe.py:89-90`). Response:
`tools[i].householdsWithTool == []`. Unchanged from current behavior.

### EC-004 — Orphan/deleted FK references
`recipes_to_tools`, `recipes_to_tags`, `recipes_to_categories` have FK
constraints to `tools.id`, `tags.id`, `categories.id` respectively with no
explicit `ON DELETE CASCADE` clause documented in the secondary table
declarations (`mealie/db/models/recipe/{tool,tag,category}.py`). Deletion of
a Tool/Tag/Category cascades via SQLAlchemy session-level cascade
(`back_populates="recipes"`) in the normal application flow. The
`selectinload` IN-list lookup against `recipes_to_*` is FK-protected and
cannot return phantom rows. No new failure modes introduced by the
refactor.

### EC-005 — Multi-tenant: recipes from another household
`unique_user` (household A) and `h2_user` (household B, same group) both
seed recipes. `GET /api/recipes` from `unique_user` MUST include recipes
from both households (cross-household-within-group is the
`group_recipes` semantic at `routes/recipe/_base.py:42-44`,
`household_id=None`). `GET /api/recipes?households=<B.householdId>` MUST
exclude recipes owned by `unique_user`. Both behaviors are guaranteed by
FR-012; `selectinload` cannot leak children of recipes that are filtered out
of the parent SELECT.

**Verification**: existing tests
`tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102`
must pass without modification.

### EC-006 — `perPage=-1` (load all rows; out of FR-010 scope)
The `/organizers/categories/slug/{slug}` controller passes `per_page=-1` to
`page_all` (`mealie/routes/organizers/controller_categories.py:131-134`),
which `add_pagination_to_query` (`repository_generic.py:382-385`) maps to
"no LIMIT". For libraries with > 500 recipes, each per-recipe-id
selectinload may split into ⌈N/500⌉ chunks; if loaded Tool count > 500,
the chained households selectinload also splits. The total statement count
is governed only by the **FR-009 formula bound** (not the FR-009(b)
regression-test ceiling, which applies only to the FR-010 parameter
window). Worst-case bookkeeping for a 1 000-recipe library with 300 distinct
tools: 1 COUNT + 1 parent + 2 categories + 2 tags + 2 tools +
1 chained households = **9 statements**. For 1 500 recipes with 600
distinct tools: 1 COUNT + 1 parent + 3 categories + 3 tags + 3 tools +
2 chained households = **13 statements**. The regression test in FR-010
explicitly stays at `perPage <= 200` to keep all chunk counts at 1; larger
pages are bounded only by the FR-009 formula and are not part of the
SC-001/SC-005 ceilings.

### EC-007 — `orderBy=random` + `paginationSeed`
`add_order_by_to_query` materializes all matching IDs to Python for the
random shuffle (`mealie/repos/repository_generic.py:436-449`). This is part
of the parent-SELECT execution and adds 1 extra cursor execute (a "fetch all
IDs" step). Post-refactor count: **7** (the 6 baseline from FR-009 plus the
random-order ID fetch). The FR-010 regression test does NOT use
`orderBy=random` to avoid this noise.

### EC-008 — `orderBy=lastMade` or `orderBy=rating`
The user-correlated subqueries `_get_last_made_col_alias` /
`_get_rating_col_alias` (FR-013) become part of the parent SELECT — they
emit zero extra cursor executes. The chained selectinload for
`Tool.households_with_tool` is unaffected. Query count remains at the FR-009
baseline. `test_order_by_last_made` and `test_order_by_rating` continue to
pass (US-3).

---

## needs_clarification

### NC-001 — `rating` field source (confirmed: no change required)
**Question**: Is the projected `rating` field a stored column or a computed
aggregate?
**Resolution**: It is a **stored column** for projection purposes. The
serialized value on `items[*].rating` comes from `RecipeModel.rating`
(`mealie/db/models/recipe/recipe.py:61`, scalar `sa.Float`). The
`column_aliases["rating"]` defined in `RepositoryRecipes`
(`repository_recipes.py:72-93`) is a correlated scalar subquery used **only**
for `QueryFilterBuilder.filter_query` (filtering) and
`add_order_attr_to_query` (sorting) when the route passes
`orderBy=rating` or `query_filter` referencing `rating`. The route at
`recipe_crud_routes.py:370` always calls `by_user(user_id)`, but that only
arms the aliases — it does not redirect the projection. **No batching or
aggregate denormalization is required by this spec.** FR-013 codifies this.
The implementer must not introduce a new aggregate field.

### NC-002 — Scope coverage of list endpoints
**Question**: Does the refactor cover ONLY `/api/recipes` (`input.md:19`) or
also `/api/explore/groups/.../recipes` and `/organizers/categories/slug/{slug}`?
**Resolution**: The seam (`RecipeSummary.loader_options()`) is shared by all
callers of `RepositoryRecipes.page_all` and any other site that splats
`RecipeSummary.loader_options()`. Fixing the seam transitively benefits all
of them (FR-011). **The new regression test is scoped to `/api/recipes`** per
`input.md:19`; an additional sibling assertion for the explore endpoint is
an **optional follow-up captured as `self_concerns SC-E`** (corrected from
v1's broken cross-reference to `SC-003`/`SC-C`).
`GET /api/users/{id}/favorites` is NOT a shared consumer (uses
`UserRatingOut`, not `RecipeSummary`) — `api_perspective.md` §8 confirms
exclusion.

### NC-003 — Spec ceiling `<= 5` is infeasible (formally relaxed)
**Question**: `input.md:67-68` asserts `count_large <= 5`. The
post-refactor minimum is provably 6.
**Resolution**: The minimum is **provably 6**: 1 COUNT subquery + 1 parent
SELECT (with the benign 1:1 `joinedload(user)`) + 3 selectinloads
(recipe_category, tags, tools) + 1 chained selectinload
(`Tool.households_with_tool`). Hitting `<= 5` would require either dropping
a field from the response (forbidden by FR-001) or moving the
`user.household_id` proxy to a different mechanism (out of scope, would
change call shape across the codebase). **The spec ceiling is formally
relaxed to `<= 8` for the FR-010 regression-test parameter window
(`perPage <= 200`, no IN-list chunk splits)**, with the formula bound in
FR-009(a) applying for pages outside that window. The relative bound from
`input.md` (`count_large <= count_small + 3`) is preserved.

### NC-004 — `slug_image` field does not exist (drop from scope)
**Question**: `input.md:23` lists `slug_image` as a required-to-preserve
field. `grep -r "slug_image" mealie/` returns zero hits.
**Resolution**: Treat as a typo in the spec input. The actual fields are
`slug` (`schema/recipe/recipe.py:125`) and `image` (line 126) on
`RecipeSummary`. Both are preserved by FR-001 (which explicitly notes this).
**Drop `slug_image` from the required-fields list.** Independently flagged
by `api_perspective.md` §5, `history_perspective.md` §3 TL;DR #4, and
`ui_perspective.md` §2.6.

### NC-005 — `comments_count` / "recent comments count" is not a real N+1 source
**Question**: `input.md:13` lists "recent comment counts" as an N+1 victim.
`RecipeSummary` has no comments-related field.
**Resolution**: `RecipeSummary.loader_options()` (`recipe.py:168-175`) does
NOT include `RecipeModel.comments`, and `model_dump(by_alias=True)` does not
walk a non-existent attribute. **No comments-related query is currently
emitted by `GET /api/recipes`.** Adding a `comments_count` field would
violate FR-001 ("响应字段 100% 不变"). **Treat the input phrase as
illustrative of the historical N+1 class, not as a current symptom to fix.**
Independently flagged by `api_perspective.md` §5,
`history_perspective.md` §3 TL;DR #4, and `ui_perspective.md` §1.5.

### NC-006 — Test must be sync, not async
**Question**: `input.md:42-43` pseudo-code uses `@pytest.mark.asyncio` and
`async def`.
**Resolution**: Write the new regression test as plain sync `def`. Codified
by FR-010. Evidence: (a) `mealie/db/db_setup.py:38` uses
`sa.create_engine(...)` (sync engine); (b) `tests/conftest.py:45-49`
exposes `api_client` as a `starlette.testclient.TestClient` (sync); (c)
every existing `test_recipe_*.py` file in
`tests/integration_tests/user_recipe_tests/` is sync `def` (verified by
inspection — 19 files, all sync). Note: `pyproject.toml:72` does declare
`pytest-asyncio==1.4.0` (it is used by other suites such as
`tests/unit_tests/test_security.py:128`), so the package is present —
applying `@pytest.mark.asyncio` here would still work, but it would
force-wrap the sync TestClient with no measurable benefit. **Do not use
`async def` for this test.**

### NC-007 — Definition of "byte-identical" response (NEW — addresses CONS-C-004)
**Question**: US-1 acceptance demands a JSON diff returning `{}`, while v1
SC-002 wording said "byte-identical modulo `createdAt`, `updatedAt`, random
UUIDs". These are mutually inconsistent.
**Resolution**: Adopt a single, well-defined comparison protocol:

- The comparison is performed on the **same persisted rows** (no
  re-seeding between pre- and post-refactor measurements). Therefore
  `createdAt`, `updatedAt`, and any random UUIDs are stable across the two
  measurements and need no masking.
- The comparison is **structural-equal-after-normalization** (per FR-014),
  not byte-identical at the orjson level: nested M2M arrays are sorted by
  child `id` because the underlying ORM relationships have no `order_by`
  (`mealie/db/models/recipe/recipe.py:98-101,138`). Top-level pagination
  envelope key order and per-`items[*]` key order are asserted verbatim.
- US-1 acceptance and SC-002 wording are aligned in v2 to refer to this
  normalized comparison.

---

## self_concerns

### SC-A — Reviewers may not connect the fix to the literal N+1 framing
The data perspective identified `Tool.households_with_tool` lazy-load as the
**concrete** N+1 root, but `input.md` frames the bug as generic
"tags/categories/tools/comments/image" (`input.md:13`). A reviewer reading
only the input may wonder why the patch adds a chained
`selectinload(Tool.households_with_tool)` instead of (or in addition to) a
new `comments_count` loader. **Mitigation**: the PR description should
explicitly trace the N+1 from the `RecipeTool.convert_households_to_slugs`
validator (`schema/recipe/recipe.py:87-95`) through the default-lazy
`Tool.households_with_tool` relationship (`db/models/recipe/tool.py:54-56`)
to the per-tool SQL fired during `model_dump`. The pre-existing prior art
in `RecipeToolOut.loader_options` should be cited.

### SC-B — Adjacent loader seams retain the anti-pattern
Two adjacent `loader_options` sites carry the same joinedload-on-M2M
anti-pattern AND lack the chained `selectinload(Tool.households_with_tool)`:

- `mealie/schema/meal_plan/new_meal.py:67-74` (`ReadPlanEntry.loader_options`)
- `mealie/schema/household/group_shopping_list.py:202-208` (`ShoppingListRecipeRefOut.loader_options`)

Both hydrate `RecipeSummary` indirectly and exhibit the same N+1 risk on
their respective endpoints. They are **strictly out of `input.md:19` scope**.
**Mitigation**: list them as out-of-scope follow-ups in the PR description
so a future iteration can fix them with the same one-line pattern.

### SC-C — Query-count budget under-counts chained Tool.households_with_tool chunking (REWORKED)
SQLAlchemy 2.x's `selectinload` batches IN-list parameters at a default
chunk size of 500 per the formula in FR-009(a). **The chained
`selectinload(Tool.households_with_tool)` chunks by the number of distinct
loaded `Tool` rows, not by recipe count.** With the FR-010 seeding of
3 unique tools per recipe, a 100-recipe page yields up to ~300 distinct
Tool IDs (still 1 chunk, ≤ 500); a 1 000-recipe page could yield up to
~3 000 distinct Tool IDs (6 chunks). **Mitigation**:

- FR-009(b) regression-test ceiling `<= 8` is scoped to `perPage <= 200` so
  all chunk counts stay at 1.
- FR-009(a) formula bound covers larger pages exactly.
- EC-006 enumerates the worst-case statement counts (9, 13) for 1 000- and
  1 500-recipe libraries.

### SC-D — Frontend types should not be regenerated for this refactor
This refactor changes no Pydantic schema field set. `task dev:generate`
would not produce a TS-types diff for `frontend/app/lib/api/types/recipe.ts`.
**Mitigation**: explicitly note in the PR description that no Pydantic
schema field set is changed and `frontend/app/lib/api/types/recipe.ts` is
expected to be unchanged. This pre-empts reviewer confusion about why a
"schema-touching" PR doesn't ship a TS-types diff.

### SC-E — Explore endpoint query-count assertion is an optional follow-up (NEW — fixes CONS-C-001 broken cross-reference)
`GET /api/explore/groups/{group_slug}/recipes` benefits transitively from
the FR-006 fix (it uses the same `RecipeSummary.loader_options()` via
`cross_household_recipes.page_all`), but the FR-010 regression test is
**scoped to `/api/recipes` only** per `input.md:19`. Adding a sibling
assertion for the explore endpoint would be a small, mechanical extension
(parametrize FR-010's test over `[api_routes.recipes, api_routes.explore_group_recipes]`)
that provides redundant coverage without expanding the input scope.
**Mitigation**: capture as a one-line follow-up in the PR description;
do not block this PR on adding it. Both FR-011 and NC-002 reference this
self-concern.

---

## Notes on v1 → v2 changes

This v2 spec resolves all CRITICAL+HIGH issues from the four v1 reviewer
reports. The complete issue-by-issue resolution table — *Issues addressed |
NOT addressed | New issues introduced* — is in
`spec_iterations\rewrite_v1_to_v2.md`.

Key v2 deltas relative to v1:

1. **New FR-014** — codifies the executable response-equivalence assertion
   seam (resolves COMP-H-001, ARCH-H-001) including the nested-array
   sort-by-id normalization.
2. **New FR-015** — exhaustive must-pass test-file appendix (resolves
   COMP-H-002).
3. **FR-009 reworked** — separates the formula bound (always applicable)
   from the regression-test budget (scoped to `perPage <= 200`); resolves
   ARCH-H-002 chunking under-count and CONS-C-003 perPage=-1 overstatement.
4. **New SC-008** — explicit nested-array normalization criterion
   (resolves ARCH-H-001).
5. **New SC-E** — explore-endpoint optional follow-up; fixes the broken
   cross-references in FR-011/NC-002 (CONS-C-001).
6. **New NC-007** — defines the byte-identical comparison protocol
   (resolves CONS-C-004).
7. **FR-013/NC-001 reworded** — clarifies that `column_aliases` is for
   filtering/ordering only; the projected `rating` value comes from the
   ORM attribute (resolves ARCH-M-001).
8. **EC-002 corrected** — 5 statements (not 6) when tools list is empty;
   chained households selectinload elides (resolves CONS-C-002).
9. **EC-006 reworked** — `perPage=-1` is bounded by the FR-009(a) formula,
   not the regression-test ceiling (resolves CONS-C-003).
10. **FR-010 expanded** — explicit measured `perPage` values
    (`perPage=50` then `perPage=200`), aligned with SC-C parameters
    (resolves CONS-C-005); marked NEW FILE in FR-010 + SC-005 (EXEC-4);
    NC-006 evidence updated to reflect that `pytest-asyncio==1.4.0` IS in
    `pyproject.toml:72` (correcting v1's incorrect citation).
11. **All `code_references` re-verified** against the on-disk source at
    `C:\Users\v-liyuanjun\Downloads\mealie\`; `spec_v2.md` and `spec_v2.json`
    are derived from the same canonical content; FR-011 references are
    aligned across both artifacts (EXEC-1); `consolidated.md` /
    `test_perspective.md` references normalized to `path:line-range`
    (EXEC-2); FR-009 references now include line 280 (parent SELECT
    execution, EXEC-3).
12. **slug_image** note moved inline into FR-001 (COMP-M-001).
13. **`metadata.iterations = 2`** in `spec_v2.json`.

v2 contains no soft-language placeholders (no fallback-style "or alike"
clauses, no unresolved markers, no conditional optionality without an explicit
condition).
