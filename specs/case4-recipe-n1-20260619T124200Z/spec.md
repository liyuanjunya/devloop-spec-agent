# Spec v1 — Case 4: Recipe List N+1 Performance Refactor

> **Intent**: SQL-layer performance refactor of `GET /api/recipes` to eliminate
> the N+1 query growth (currently scales O(unique tools in page)) while keeping
> the response payload, pagination semantics, and multi-tenant filters
> byte-identical.
>
> **Approach** (`approach\selected.md`): extend `RecipeSummary.loader_options()`
> at `mealie/schema/recipe/recipe.py:168-175` to convert M2M `joinedload`s to
> `selectinload`s and chain `selectinload(Tool.households_with_tool)` off the
> `tools` loader. Keep `joinedload(RecipeModel.user).load_only(User.household_id)`
> for the AssociationProxy. Add `tests/integration_tests/test_recipe_list_query_count.py`.
>
> **Authoritative consolidation**: `exploration\consolidated.md`.

---

## User stories

### US-1 (P1) — Backend developer: response payload unchanged
**As** a Mealie backend developer responsible for client compatibility,
**I want** the `GET /api/recipes` JSON response — field set, field declaration
order, camelCase aliases (`orgURL` special-case included), and pagination
envelope (`page`, `perPage`, `total`, `totalPages`, `items`, `next`, `previous`)
— to be byte-identical to the pre-refactor baseline for identical seed data,
**so that** existing UI consumers (`RecipeCard`, `RecipeCardMobile`,
`RecipeCardSection.vue:119-127, 144-152`), command-K search
(`RecipeDialogSearch.vue:59-63`), and generated TypeScript types
(`frontend/app/lib/api/types/recipe.ts:310-336`) keep working without
regeneration.

**Acceptance**: a JSON diff between pre- and post-refactor responses on the
same seeded dataset returns `{}` (no changes). See FR-001, FR-002, SC-002.

### US-2 (P1) — Backend developer: query count constant in recipe count
**As** a Mealie backend developer triaging the "All Recipes" page slowness in
libraries with 100+ recipes,
**I want** the SQL statement count emitted by `GET /api/recipes` to be a small
constant (independent of how many recipes are returned),
**so that** page latency no longer scales linearly with library size, and
future regressions can be caught quickly.

**Acceptance**: `count(queries for 100 recipes) <= count(queries for 10 recipes) + 3`
AND `count(queries for 100 recipes) <= 8` (typical) / `<= 10` (absolute,
accommodating SQLAlchemy IN-list chunking). See FR-003..FR-006, FR-009,
SC-001.

### US-3 (P2) — Backend developer: existing tests still green
**As** a Mealie backend developer running `task py:check` before opening the PR,
**I want** every existing unit, integration, and multi-tenant test that
touches `RepositoryRecipes.page_all` and `RecipeSummary` to pass without
modification,
**so that** the refactor's correctness is verified by the existing regression
surface (response shape, multi-household filtering, organizer filtering, sort
ordering, validator coercion).

**Acceptance**: `task py:test` exits 0 with no new skips, no new xfails, and
no new warnings. Specifically the tests enumerated in `test_perspective.md` §8
(strict regression list) pass: `test_get_all_only_includes_group_recipes`,
`test_get_recipes_organizer_filter`, `test_get_random_order`,
`test_get_cookbook_recipes`, `test_get_all_recipes_includes_all_households`,
`test_get_all_recipes_with_household_filter`,
`test_cookbook_recipes_includes_all_households`, `test_order_by_last_made`,
`test_coalesce_last_made`, `test_order_by_rating`,
`test_recipe_repo_pagination_by_categories|tags|tools|foods`,
`test_recipe_number_sanitation`, `test_recipe_string_sanitation`. See FR-013,
SC-003.

### US-4 (P2) — Backend developer: regression-test guard for future N+1
**As** a Mealie backend developer protecting the recipe list path against
future regressions (e.g., adding a new lazy relationship to `RecipeSummary`),
**I want** a new test
`tests/integration_tests/test_recipe_list_query_count.py` that arms a
SQLAlchemy `before_cursor_execute` listener on the shared `engine`, runs the
warm-up + measured `GET /api/recipes` flow at two recipe-count scales (10 and
100), and asserts the query count does not grow,
**so that** a careless re-introduction of a `joinedload`-on-M2M with `LIMIT`
or a missing chained selectinload fails CI deterministically.

**Acceptance**: `uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v`
passes; the test is a plain sync `def`, uses `unique_user_fn_scoped`, attaches
the listener with `event.listen(engine, "before_cursor_execute", _on_query)`
inside a `try/finally event.remove(...)` block to avoid session-scope leakage,
and warms up before measuring. See FR-010, SC-005.

---

## Functional requirements

### FR-001 — Preserve exact `RecipeSummary` response fields
The set, declaration order, and camelCase aliases of fields on each
`items[*]` element of the `GET /api/recipes` response must be unchanged from
the pre-refactor baseline:

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
`MealieModel.model_config` (`mealie/schema/_mealie/mealie_model.py:45-53`)
provides `alias_generator=camelize, populate_by_name=True`.
No fields are added or removed.

**code_references**: `mealie/schema/recipe/recipe.py:116-149` (RecipeSummary
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
(loader options are attached AFTER `add_pagination_to_query`).

**code_references**: `mealie/repos/repository_generic.py:357-405`
(`add_pagination_to_query` — COUNT subquery at L376-377, perPage=-1 handling
at L382-385, total_pages at L388, page=-1 at L392-394);
`mealie/repos/repository_recipes.py:274,277` (the canonical
"add_pagination_to_query THEN .options(...)" sequence);
`mealie/routes/recipe/recipe_crud_routes.py:387-390`
(`set_pagination_guides`); `mealie/schema/response/pagination.py:51-94`
(`PaginationBase`).

### FR-003 — Eager-load `recipe_category` via `selectinload`
Replace `joinedload(RecipeModel.recipe_category)` with
`selectinload(RecipeModel.recipe_category)` in `RecipeSummary.loader_options()`.
Rationale: `recipe_category` is M2M via `recipes_to_categories`; combining
joinedload-on-collection with `LIMIT/OFFSET` causes SQLAlchemy to fall back
to a subquery+OUTER JOIN strategy with cartesian-product row inflation
(observable via the load-bearing `.scalars().unique().all()` at L280).
`selectinload` issues a follow-up
`SELECT … FROM categories JOIN recipes_to_categories WHERE recipes_to_categories.recipe_id IN (...)`
as one extra statement regardless of page size.

**code_references**: `mealie/schema/recipe/recipe.py:171` (current line);
`mealie/db/models/recipe/recipe.py:98-100` (`recipe_category` relationship
via `recipes_to_categories`); `mealie/db/models/recipe/category.py:35-41`
(`recipes_to_categories` table — `recipe_id` and `category_id` both indexed,
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
`selectinload(RecipeModel.tools)` loader so the load becomes:

```python
selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)
```

Rationale: `RecipeTool.households_with_tool` is `list[str]` populated by a
`@field_validator("households_with_tool", mode="before")` that iterates
`household.slug for household in v`. `Tool.households_with_tool` is a default
`lazy="select"` M2M relationship. Without the chained selectinload, every
unique tool in the page triggers one `SELECT FROM households JOIN
households_to_tools WHERE tool_id = ?` during
`pagination_response.model_dump(by_alias=True)` — **this is the dominant
N+1**. Prior art for the exact pattern lives in `RecipeToolOut.loader_options`
and `IngredientFood.loader_options`.

**code_references**: `mealie/schema/recipe/recipe.py:83-95` (RecipeTool +
`convert_households_to_slugs` validator that triggers the lazy load);
`mealie/db/models/recipe/tool.py:54-56` (`Tool.households_with_tool` M2M
relationship — default lazy);
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
`mealie/db/models/recipe/recipe.py:55-56` (the AssociationProxy);
`mealie/db/models/recipe/recipe.py:59` (`user` 1:1 relationship —
`orm.relationship("User", uselist=False, foreign_keys=[user_id])`).

### FR-008 — Preserve the "apply options late" invariant
`RepositoryRecipes.page_all` must continue to call
`q = q.options(*RecipeSummary.loader_options())` **AFTER**
`add_pagination_to_query(q, pagination_result)` — i.e., the line ordering at
`mealie/repos/repository_recipes.py:274,277` is unchanged. The COUNT
subquery at `repository_generic.py:376-377`
(`select(func.count()).select_from(query.order_by(None).distinct().subquery())`)
must NOT see loader options, otherwise `total` regresses (commit `7b325082`).
Implementation note: this requirement is satisfied automatically by editing
only `loader_options()` and leaving `page_all` unchanged.

**code_references**: `mealie/repos/repository_recipes.py:274,277` (load-bearing
sequence); `mealie/repos/repository_generic.py:341-342` (mantra
"Apply options late, so they do not get used for counting");
`mealie/repos/repository_generic.py:376-377` (COUNT subquery).

### FR-009 — Query-count bound
The number of cursor executes emitted by `engine.execute` during a
`GET /api/recipes?perPage={N}` call (after the per-session warm-up) must be:

- **Relative bound**: `count(queries for 100 recipes) <= count(queries for 10 recipes) + 3`.
- **Absolute bound**: `<= 8 queries` for `perPage <= 500` (typical),
  `<= 10 queries` for `perPage <= 1000` (absorbs SQLAlchemy IN-list chunking
  at the default 500-row split).

The expected post-refactor minimum is **6**: 1 COUNT subquery + 1 parent
SELECT with the 1:1 `joinedload(user)` + 3 selectinloads (recipe_category,
tags, tools) + 1 chained selectinload (Tool.households_with_tool). Spec
ceiling is relaxed from `input.md`'s literal `<= 5` to `<= 8` because the
post-refactor minimum is provably 6, not 5 (see `needs_clarification` NC-003).

**code_references**: `mealie/schema/recipe/recipe.py:168-175` (loader options
that produce the 4 child SELECTs); `mealie/repos/repository_recipes.py:274,277`
(COUNT + parent SELECT); `mealie/repos/repository_generic.py:376-377`
(COUNT subquery); `exploration\consolidated.md` §3 (full trace).

### FR-010 — New regression test `test_recipe_list_query_count.py`
Add `tests/integration_tests/test_recipe_list_query_count.py` containing a
sync `def` test that:

1. Imports the global `engine` from `mealie.db.db_setup`.
2. Uses the function-scoped fixture `unique_user_fn_scoped` for a clean per-test slate.
3. Seeds N recipes (10 then +90), each decorated with 3 tags + 3 categories
   + 3 tools, using the bulk pattern `db.recipes.create_many([Recipe(...), ...])`
   modelled on `tests/integration_tests/user_recipe_tests/test_recipe_crud.py:1534-1558`.
4. **Warms up** the test client with one throwaway `api_client.get(api_routes.recipes, params={"page": 1, "perPage": 1}, headers=user.token)` call before arming the listener (FastAPI dependency injection emits ~5 auth/user-resolution queries on cold-cache that would otherwise dominate `count_small`).
5. Attaches `event.listen(engine, "before_cursor_execute", on_query)` inside a
   `try/finally event.remove(...)` block to avoid leakage across the session-scoped
   `api_client` fixture.
6. Asserts `len(body["items"])`, `body["total"]`, and the two query-count
   bounds (relative `<= count_small + 3`, absolute `<= 10`).
7. Is a plain sync `def` — **not** `async def` — because Mealie's test suite
   uses `TestClient` (sync) and the engine is `sa.create_engine(...)` (sync);
   `pytest-asyncio` is not in `pyproject.toml`.

**code_references**: `mealie/db/db_setup.py:38,45` (sync `engine` global);
`tests/conftest.py:45-53` (session-scoped sync `api_client`);
`tests/fixtures/fixture_users.py:219-221` (`unique_user_fn_scoped`);
`tests/utils/api_routes/__init__.py:138` (`recipes = "/api/recipes"`);
`tests/integration_tests/user_recipe_tests/test_recipe_crud.py:1534-1558`
(bulk `create_many` pattern with M2M decoration);
`exploration\test_perspective.md` §7 (full scaffolding & rationale).

### FR-011 — Shared loader benefits adjacent endpoints
Editing `RecipeSummary.loader_options()` transitively fixes every call site
of `RepositoryRecipes.page_all` and any other location that splats
`RecipeSummary.loader_options()`. The two **user-facing list endpoints**
covered are:

- `GET /api/recipes` (`mealie/routes/recipe/recipe_crud_routes.py:340-395`) — primary.
- `GET /api/explore/groups/{group_slug}/recipes` (`mealie/routes/explore/controller_public_recipes.py:30-92`) — public/cross-household. Same `page_all` path with an injected `query_filter` for `household.preferences.privateHousehold = FALSE AND settings.public = TRUE`.

`GET /api/users/{id}/favorites` (and `/ratings`) does **not** share this code
path — it returns `UserRatingOut` records via a different repository
(`mealie/routes/users/ratings.py:44-52`), so it is **out of scope** for this
spec (`api_perspective.md` §8). Regression test scope is `/api/recipes` only
(per `input.md` §1); explore-endpoint coverage is captured as `self_concerns`
SC-003.

**code_references**: `mealie/routes/recipe/recipe_crud_routes.py:370`
(primary call site); `mealie/routes/explore/controller_public_recipes.py:67-80`
(explore call site); `mealie/routes/organizers/controller_categories.py:131-134`
(`per_page=-1` category-page call site, also benefits); `mealie/routes/households/controller_mealplan.py:65` (random-pick call site).

### FR-012 — Multi-tenant safety preserved
The household/group filter chain must remain enforced on the parent SELECT.
Specifically:

- `sa.select(self.model).filter(self.model.household_id.is_not(None))`
  (`repository_recipes.py:238`) — the secondary safety filter introduced in
  commit `d02023e1`.
- `_build_recipe_filter` (`repository_recipes.py:295-337`) — appends
  `RecipeModel.group_id == self.group_id` and (when set) `RecipeModel.household_id == self.household_id`, plus the explicit `households=[...]` query-param filter via `RecipeModel.household_id.in_(households)` at L335-336.

`selectinload` does NOT add JOINs to the parent SELECT (it issues separate
follow-up `SELECT … WHERE recipe_id IN (...)` statements), so these filters
are preserved. The follow-up selectinload statements load child rows **for
already-filtered recipes** — no cross-household or cross-group leakage is
possible. Verified by the existing tests in
`tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102`.

**code_references**: `mealie/repos/repository_recipes.py:238`
(`household_id IS NOT NULL`); `mealie/repos/repository_recipes.py:295-337`
(`_build_recipe_filter`);
`tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102`
(strict multi-household tests that must still pass).

### FR-013 — `rating` and `last_made` remain correlated scalar subqueries
The user-correlated `column_aliases["rating"]` (`_get_rating_col_alias` at
`repository_recipes.py:72-93`) and `column_aliases["last_made"]`
(`_get_last_made_col_alias` at `repository_recipes.py:54-70`) are **not
modified**. They are correlated scalar subqueries on the parent SELECT —
they emit zero extra cursor executes per row and are armed by
`by_user(user_id)` (`repository_recipes.py:49-52`) which the controller
already calls (`recipe_crud_routes.py:370`). Replacing them with JOINs
would inflate rows and break `test_order_by_last_made`
(`tests/unit_tests/repository_tests/test_recipe_repository.py:593-647`) and
`test_order_by_rating` (L691-812). This requirement explicitly forbids
introducing a new aggregate field (e.g., `comments_count`) — `RecipeSummary`'s
field set is locked by FR-001.

**code_references**: `mealie/repos/repository_recipes.py:39-93`
(`column_aliases`, `by_user`, `_get_last_made_col_alias`,
`_get_rating_col_alias`);
`tests/unit_tests/repository_tests/test_recipe_repository.py:593-812`
(must-still-pass tests).

---

## Success criteria

### SC-001 — Query-count growth is bounded by a constant
`count(queries for 100 recipes) - count(queries for 10 recipes) <= 3`
(asserted in `test_recipe_list_query_count.py` per FR-010). Today, this
difference is approximately `|distinct tools in 100 recipes|` ≈ 70-90;
post-refactor it is 0 (selectinload IN-list grows, statement count does not),
modulo SQLAlchemy chunking.

**Verification**: `uv run pytest tests/integration_tests/test_recipe_list_query_count.py::test_recipe_list_query_count_does_not_grow_with_n -v` passes.

### SC-002 — Response shape diff against baseline = 0
Pre- and post-refactor JSON responses for the same seeded dataset (same user,
same query parameters) are byte-identical after orjson serialization, modulo
field values that are non-deterministic by design (`createdAt`, `updatedAt`,
random UUIDs from the seeder). The 26 fields of `RecipeSummary` and the
pagination envelope keys are unchanged.

**Verification**: Existing tests in `test_recipe_owner.py:42-57`,
`test_recipe_crud.py:1530-1657`, and `test_recipe_cross_household.py:46-354`
all assert on field names, values, and counts — passing without modification
is the byte-shape equivalence proof.

### SC-003 — Existing test count passing unchanged
`task py:test` exit code 0; the strict-regression list in
`test_perspective.md` §8 all pass; no test is skipped, xfailed, or modified;
no new pytest warnings emitted.

**Verification**:
```powershell
uv run pytest tests/unit_tests/repository_tests/test_recipe_repository.py -v
uv run pytest tests/unit_tests/schema_tests/test_recipe.py -v
uv run pytest tests/integration_tests/user_recipe_tests/ -v
```
All pass with zero diff against pre-refactor counts.

### SC-004 — Latency improvement documented (no hard p95 SLA)
PR description includes a before/after table with query count for 100 recipes
(captured by enabling the same `before_cursor_execute` listener manually) and
an EXPLAIN ANALYZE on the parent SELECT for the 100-recipe case. **No
absolute p95 SLA is asserted** because Mealie's test suite has no baseline
benchmark to compare against (unlike case-1 SC-004, which had a documented
prior latency measurement). The implementer is required only to publish the
numbers, not to hit a specific milliseconds target. This is explicit per the
spec's `input.md` §4 which requires "before/after query count comparison" and
"before/after EXPLAIN ANALYZE" but no p95 SLA.

**Verification**: PR description body contains a fenced-code-block table with
`before: N queries, after: 6 queries (or measured value)` for the 100-recipe
case, plus an EXPLAIN ANALYZE text dump (Postgres preferred; SQLite
acceptable with a note that the test DB is SQLite by default per
`mealie/db/db_setup.py:38` and `task py:postgres` is required for the
Postgres pass).

### SC-005 — New regression test exists and passes
`tests/integration_tests/test_recipe_list_query_count.py` exists, is
collected by pytest (no collection errors), and passes locally and in CI.

**Verification**:
```powershell
uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v
```
Exit code 0; at least one test reported as passed.

### SC-006 — No new SQL warnings in logs
Running `task py:test` does not emit any new SQLAlchemy warnings (e.g.
`SAWarning: Loader strategy ... will be overridden`, `Cartesian product
warning`, `Cannot correlate ...`). Compare warning counts before/after.

**Verification**: `uv run pytest tests/ 2>&1 | Select-String -Pattern "SAWarning"` returns the same count pre- and post-refactor.

### SC-007 — Explore endpoint shares the fix (no code duplication)
A single `RecipeSummary.loader_options()` definition serves both
`GET /api/recipes` and `GET /api/explore/groups/{group_slug}/recipes`. No
parallel loader graph is added to the explore controller.

**Verification**: `grep -rn "selectinload(Tool.households_with_tool)" mealie/` returns occurrences only in `mealie/schema/recipe/recipe.py` (new), `mealie/schema/recipe/recipe_tool.py` (existing prior art), and any out-of-scope adjacent seam — **not** in `mealie/routes/explore/`.

---

## Edge cases

### EC-001 — Empty recipe list
`GET /api/recipes` for a user whose household/group has zero recipes returns
`{"items": [], "total": 0, "totalPages": 0, "page": 1, "perPage": 50, "next": null, "previous": null}`.
Query count: 1 COUNT (returns 0) + 0 follow-up selectinloads (IN-list is
empty → SQLAlchemy elides the statement) + 1 parent SELECT (returns 0 rows)
= **2 statements** typically (selectinload elision when parent returns no
rows is standard SQLAlchemy 2.x behavior).

### EC-002 — Single recipe with no organizers
A recipe with `tags=[]`, `recipe_category=[]`, `tools=[]`. Selectinloads
issue with IN-list `(recipe_id,)` and return zero child rows for each — still
3 statements (categories, tags, tools) plus 1 for users plus parent +
COUNT = 6. The chained `selectinload(Tool.households_with_tool)` is elided
when the `tools` IN-list returns no `Tool` IDs. Bound by FR-009 ceiling.

### EC-003 — Recipe with non-empty M2M but empty `Tool.households_with_tool`
A tool created without any `households_with_tool` (default `[]` per
`Tool.__init__` at `mealie/db/models/recipe/tool.py:78-80`). The chained
selectinload issues with the tool's ID in the IN-list, returns zero
`households` rows — still 1 statement. Validator
`convert_households_to_slugs` returns `[]` (the `if not v: return []`
branch at `schema/recipe/recipe.py:89-90`). Response: `tools[i].householdsWithTool == []`. Unchanged from current behavior.

### EC-004 — Orphan/deleted FK references
`recipes_to_tools`, `recipes_to_tags`, `recipes_to_categories` have FK
constraints to `tools.id`, `tags.id`, `categories.id` respectively with no
explicit `ON DELETE CASCADE` clause documented in the secondary table
declarations (`mealie/db/models/recipe/{tool,tag,category}.py`). Deletion of
a Tool/Tag/Category cascades via SQLAlchemy session-level cascade
(`back_populates="recipes"`) in normal flow. The `selectinload` IN-list
lookup against `recipes_to_*` is FK-protected and cannot return phantom
rows. No new failure modes introduced by the refactor.

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

### EC-006 — `perPage=-1` (load all rows)
The `/organizers/categories/slug/{slug}` controller passes `per_page=-1` to
`page_all` (`mealie/routes/organizers/controller_categories.py:131-134`),
which `add_pagination_to_query` (`repository_generic.py:382-385`) maps to
"no LIMIT". After the refactor, the selectinload IN-list can contain >500
parent IDs → SQLAlchemy splits into 2 chunks (default `selectin_loader.IN_BULK = 500`).
Total statements: COUNT + parent + 3 × {1 or 2 chunks for the M2M} + chained
households_with_tool. Bounded by FR-009 absolute `<= 10` for libraries
within reasonable user limits.

### EC-007 — `orderBy=random` + `paginationSeed`
`add_order_by_to_query` materializes all matching IDs to Python for the
random shuffle (`mealie/repos/repository_generic.py:436-449`). This is part
of the parent-SELECT execution and adds 1 extra cursor execute (a "fetch all
IDs" step). Post-refactor count: 7 (the 6 from FR-009 plus the random-order
ID fetch). The regression test does NOT use `orderBy=random` to avoid this
noise; if the implementer wants to parametrize, the ceiling becomes `<= 10`.

### EC-008 — `orderBy=lastMade` or `orderBy=rating`
The user-correlated subqueries `_get_last_made_col_alias` /
`_get_rating_col_alias` (FR-013) become part of the parent SELECT — they emit
zero extra cursor executes. The chained selectinload for
`Tool.households_with_tool` is unaffected. Query count remains at the FR-009
baseline. `test_order_by_last_made` and `test_order_by_rating` continue to
pass (US-3).

---

## needs_clarification

### NC-001 — `rating` field source (confirmed: no change required)
**Question**: Is `rating` a stored column or computed aggregate?
**Resolution**: Both. `RecipeModel.rating` is a scalar `Float` column
(`mealie/db/models/recipe/recipe.py:61`). When `by_user(user_id)` is set
(which the controller always does at `recipe_crud_routes.py:370`),
`column_aliases["rating"]` returns `_get_rating_col_alias`
(`repository_recipes.py:72-93`) — a `sa.case(...)` expression that prefers
the user's `UserToRecipe.rating` if present and non-zero, else the recipe's
scalar rating. This is a correlated scalar subquery on the parent SELECT —
zero extra cursor executes. **No batching or aggregate denormalization is
required by the spec.** FR-013 codifies this. The implementer should not
introduce a new aggregate.

### NC-002 — Scope coverage of list endpoints
**Question**: Does the refactor cover ONLY `/api/recipes` (`input.md` §1) or
also `/api/explore/groups/.../recipes` and `/organizers/categories/slug/{slug}`?
**Resolution**: The seam (`RecipeSummary.loader_options()`) is shared by all
callers of `RepositoryRecipes.page_all` and any other site that splats
`RecipeSummary.loader_options()`. Fixing the seam transitively benefits all
of them (FR-011). **The regression test is scoped to `/api/recipes` per
`input.md` §1**; an additional sibling assertion for the explore endpoint is
an optional follow-up captured in `self_concerns` SC-003.
`GET /api/users/{id}/favorites` is NOT a shared consumer (uses
`UserRatingOut`, not `RecipeSummary`) — `api_perspective.md` §8 confirms
exclusion.

### NC-003 — Spec ceiling `<= 5` is infeasible (relaxed to `<= 8`)
**Question**: `input.md:67-68` asserts `count_large <= 5`. The
post-refactor minimum is 6.
**Resolution**: The minimum is **provably 6**: 1 COUNT subquery + 1 parent
SELECT (with the benign 1:1 `joinedload(user)`) + 3 selectinloads
(recipe_category, tags, tools) + 1 chained selectinload
(Tool.households_with_tool). Hitting `<= 5` would require either dropping a
field from the response (forbidden by FR-001) or moving the `user.household_id`
proxy to a different mechanism (out of scope, would change call shape across
the codebase). **The spec ceiling is relaxed to `<= 8` typical / `<= 10`
absolute** (FR-009). The relative bound from `input.md` (`count_large <= count_small + 3`) is comfortably preserved.

### NC-004 — `slug_image` field does not exist (drop from scope)
**Question**: `input.md:23` lists `slug_image` as a required-to-preserve
field. `grep -rn "slug_image" mealie/` returns zero hits.
**Resolution**: Treat as a typo in the spec input. The actual fields are
`slug` (line 125) and `image` (line 126) on `RecipeSummary`. Both are
preserved by FR-001. **Drop `slug_image` from the required-fields list.**
This was independently flagged by `api_perspective.md` §5,
`history_perspective.md` §3 TL;DR #4, and `ui_perspective.md` §2.6.

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
`async def`. Mealie's test suite is fully synchronous.
**Resolution**: Write the test as plain sync `def`. Codified by FR-010.
Evidence: `mealie/db/db_setup.py:38` uses `sa.create_engine(...)` (sync
engine), `tests/conftest.py:45-46` exposes `api_client` as a
`starlette.testclient.TestClient` (sync), `pyproject.toml` does not declare
`pytest-asyncio`, and zero existing tests use `async def`
(`test_perspective.md` §0).

---

## self_concerns

### SC-A — Reviewers may not connect the fix to the literal N+1 framing
The data perspective identified `Tool.households_with_tool` lazy-load as the
**concrete** N+1 root, but `input.md` frames the bug as generic
"tags/categories/tools/comments/image" (`input.md:13`). A reviewer reading
only the input may wonder why the patch adds a chained
`selectinload(Tool.households_with_tool)` instead of (or in addition to) a
new comments_count loader. **Mitigation**: the PR description should
explicitly trace the N+1 from the `RecipeTool.convert_households_to_slugs`
validator (`schema/recipe/recipe.py:87-95`) through the default-lazy
`Tool.households_with_tool` relationship (`db/models/recipe/tool.py:54-56`)
to the per-tool SQL fired during `model_dump`. The pre-existing prior art
in `RecipeToolOut.loader_options` should be cited.

### SC-B — Adjacent loader seams retain the anti-pattern
Two adjacent `loader_options` sites carry the same joinedload-on-M2M anti-pattern AND lack the chained `selectinload(Tool.households_with_tool)`:

- `mealie/schema/meal_plan/new_meal.py:67-74` (`ReadPlanEntry.loader_options`)
- `mealie/schema/household/group_shopping_list.py:202-208` (`ShoppingListRecipeRefOut.loader_options`)

Both hydrate `RecipeSummary` indirectly and exhibit the same N+1 risk on
their respective endpoints. They are **strictly out of `input.md` §1 scope**.
**Mitigation**: list them as out-of-scope follow-ups in the PR description
so a future iteration can fix them with the same one-line pattern.

### SC-C — Query-count budget depends on SQLAlchemy IN-list chunking
SQLAlchemy 2.x's `selectinload` batches IN-list parameters at a default
chunk size (currently 500). For `perPage=-1` libraries > 500 recipes, each
selectinload may split into 2 chunks → up to 3 extra statements (3
selectinloads + 1 chained), bringing the maximum to ~9. **Mitigation**:
spec ceiling is `<= 8` typical / `<= 10` absolute (FR-009). The regression
test parameters (`perPage=50`, then `perPage=200`) stay safely below the
chunking threshold.

### SC-D — Frontend types must be regenerated only if a Pydantic schema field
changes; this refactor changes none — but the `task dev:generate` reflex
could trigger an unnecessary regeneration in CI. **Mitigation**: explicitly
note in the PR description that no Pydantic schema field set is changed and
`frontend/app/lib/api/types/recipe.ts` is expected to be unchanged. This
also pre-empts reviewer confusion about why a "schema-touching" PR doesn't
ship a TS-types diff.
