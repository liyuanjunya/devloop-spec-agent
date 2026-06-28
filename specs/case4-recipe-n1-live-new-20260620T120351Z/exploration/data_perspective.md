# Data Perspective — Case 4 (Recipe List N+1 Performance Refactor)

> Scope: trace every artifact in Mealie that contributes to the query graph executed by `GET /api/recipes`, identify the eager-loading seam, and surface the constraints (multi-tenant filter, pagination, response shape) the refactor must preserve.

---

## Critical artifacts (must read to write the fix)

### Artifact: `RepositoryRecipes.page_all` — the recipe-list method
- **path**: `mealie/repos/repository_recipes.py`
- **key symbols**: `RepositoryRecipes.page_all`, `_build_recipe_filter`, `_uuids_for_items`, `add_pagination_to_query` (inherited), `add_search_to_query` (inherited), `column_aliases`, `by_user`
- **line_ranges**: `220-293` (page_all body), `295-337` (_build_recipe_filter), `36-93` (class header + `by_user` + computed `column_aliases` for `rating` / `last_made`), `183-202` (_uuids_for_items)
- **importance**: critical
- **reason**: This is the list method that `GET /api/recipes` calls. The query is built as `sa.select(self.model).filter(self.model.household_id.is_not(None))` (line 238), then household/group filters from `_build_recipe_filter` (lines 308-311) are appended, then category/tag/tool/food/household filters (lines 313-336), then optional search and ordering. `add_pagination_to_query` issues a separate `SELECT COUNT(...)` (via `repository_generic.py:376-377`) and applies `LIMIT/OFFSET` to the data query. **The critical seam is line 277: `q = q.options(*RecipeSummary.loader_options())`** — applied AFTER pagination intentionally ("Apply options late, so they do not get used for counting", line 276). Any inline `selectinload`/`joinedload` chain added to this `.options(...)` call cascades through every recipe-list caller.

### Artifact: `RecipeSummary.loader_options` — the eager-loading seam (current bug source)
- **path**: `mealie/schema/recipe/recipe.py`
- **key symbols**: `RecipeSummary`, `RecipeSummary.loader_options`, `RecipeTool`, `RecipeTool.convert_households_to_slugs`, `RecipeCategory`, `RecipeTag`, `RecipePagination`
- **line_ranges**: `116-149` (RecipeSummary field set), `168-175` (loader_options), `83-95` (RecipeTool + before-validator that lazy-loads), `61-80` (RecipeTag/RecipeCategory — pure scalar, no validator), `178-180` (RecipePagination wrapper)
- **importance**: critical
- **reason**: `RecipeSummary.loader_options()` currently returns four eager-loads — `joinedload(RecipeModel.recipe_category)`, `joinedload(RecipeModel.tags)`, `joinedload(RecipeModel.tools)`, `joinedload(RecipeModel.user).load_only(User.household_id)` (lines 170-174) — but does NOT chain `selectinload(Tool.households_with_tool)`. Because `RecipeTool.households_with_tool` is declared `list[str]` with a `@field_validator(..., mode="before")` that iterates `household.slug for household in v` (lines 87-95), Pydantic dereferences the unloaded `Tool.households_with_tool` M2M relationship once per `tool` in `recipe.tools` during `RecipeSummary.model_validate`, producing the N+1. Three additional concerns observable here: (a) joinedload on three M2M collections combined with the LIMIT/OFFSET from `add_pagination_to_query` triggers SQLAlchemy's subquery+OUTER-JOIN-of-collections strategy with cartesian-product row inflation per recipe — observable through the explicit `.unique()` deduplication required at `repository_recipes.py:280`; (b) `RecipeTag` and `RecipeCategory` are pure scalar value objects (`id`, `group_id`, `name`, `slug`) with no validator that touches relationships, so they cannot drive a per-row N+1 — only the M2M-on-LIMIT inflation; (c) the `joinedload(RecipeModel.user)...load_only(...)` is needed because `RecipeModel.household_id` is an `association_proxy` through `user`, so `user` must be loaded for the schema's `household_id: UUID4` field to populate.

### Artifact: `RecipeModel` — relationships and lazy-loading defaults
- **path**: `mealie/db/models/recipe/recipe.py`
- **key symbols**: `RecipeModel`, `recipe_category`, `tags`, `tools`, `user`, `household_id` (association_proxy), `household` (association_proxy), `recipes_to_categories`, `recipes_to_tags`, `recipes_to_tools`
- **line_ranges**: `42-101` (class header, IDs, `user` relationship, `recipe_category`/`tools` declarations), `138` (`tags` relationship), `52-59` (`group_id` FK + `user` relationship + `household_id`/`household` association_proxies through `user`), `144-150` (`date_added`, `date_updated`, `last_made` scalar columns plus `made_by` M2M)
- **importance**: critical
- **reason**: `recipe_category`, `tags`, and `tools` are `orm.relationship` collections via secondary tables (`recipes_to_categories`, `recipes_to_tags`, `recipes_to_tools`) and have no `lazy=` override — they default to lazy `"select"`. `household_id`/`household` are `association_proxy("user", ...)` so `recipe.household_id` requires `recipe.user` to be resident, justifying the explicit `joinedload(RecipeModel.user).load_only(User.household_id)`. Scalar fields in `RecipeSummary` (`name`, `slug`, `image`, `description`, `recipe_servings`, `recipe_yield_quantity`, `recipe_yield`, `total_time`, `prep_time`, `cook_time`, `perform_time`, `rating`, `org_url`, `date_added`, `date_updated`, `last_made`, plus `created_at`/`updated_at` from `BaseMixins`) are direct `mapped_column`s on `RecipeModel` (lines 48-49, 80-94, 144-147) — they cannot trigger lazy loads. `last_made` in particular is a scalar `NaiveDateTime` column (line 147), distinct from the user-scoped `column_aliases["last_made"]` subquery that only applies when **ordering** by last_made.

### Artifact: `Tool` and `households_to_tools` — the unloaded M2M behind the N+1
- **path**: `mealie/db/models/recipe/tool.py`
- **key symbols**: `Tool`, `Tool.households_with_tool`, `Tool.recipes`, `recipes_to_tools` (secondary), `households_to_tools` (secondary)
- **line_ranges**: `17-23` (`households_to_tools` secondary table), `25-31` (`recipes_to_tools` secondary table), `42-65` (`Tool` class with both M2M relationships and `model_config` exclude for `households_with_tool`)
- **importance**: critical
- **reason**: `Tool.households_with_tool: Mapped[list["Household"]] = orm.relationship("Household", secondary=households_to_tools, back_populates="tools_on_hand")` (lines 54-56) is the relationship that fires per-tool when `RecipeTool` validates `households_with_tool`. No `lazy=` argument means default lazy `"select"`, i.e., one SQL roundtrip per access. The fix is `selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)`, chained inside `RecipeSummary.loader_options()`. Note `Tool.model_config = ConfigDict(exclude={"households_with_tool"})` (lines 61-65) only affects the SQLAlchemy-base auto-init helper, NOT Pydantic serialization of the `RecipeTool` schema.

### Artifact: `RepositoryGeneric.page_all` — the canonical count+select+options skeleton
- **path**: `mealie/repos/repository_generic.py`
- **key symbols**: `RepositoryGeneric.page_all`, `RepositoryGeneric.add_pagination_to_query`, `RepositoryGeneric._query`, `RepositoryGeneric._filter_builder`, `RepositoryGeneric.add_order_by_to_query`
- **line_ranges**: `33-92` (class header, `_query(with_options=True)`), `94-102` (`_filter_builder` for `group_id`/`household_id`), `315-355` (generic `page_all`), `357-405` (`add_pagination_to_query` — issues one COUNT subquery at 376-377 and one `LIMIT/OFFSET` on the data query at 402-405), `432-482` (`add_order_by_to_query`)
- **importance**: critical
- **reason**: `RepositoryRecipes.page_all` shadows the generic version but mirrors its three-statement skeleton: a parent SELECT (one statement), a separate COUNT subquery via `add_pagination_to_query` (`select(func.count()).select_from(query.order_by(None).distinct().subquery())` at line 376), and loader options applied AFTER pagination so the COUNT subquery is not polluted. This is the source of the "2 base queries" floor; the loader options decide how many additional statements are emitted. The generic version's mantra at lines 341-342 — "Apply options late, so they do not get used for counting" — must be preserved in any refactor.

### Artifact: `GET /api/recipes` controller and JSON serialization path
- **path**: `mealie/routes/recipe/recipe_crud_routes.py`
- **key symbols**: `RecipeController.get_all`, `JSONBytes`, `self.group_recipes`, `pagination_response.model_dump`
- **line_ranges**: `340-395` (the full route handler), `83-101` (router setup + controller exception path)
- **importance**: critical
- **reason**: `RecipeController.get_all` is the controller that calls `self.group_recipes.by_user(self.user.id).page_all(...)` at line 370 with cookbook/categories/tags/tools/foods/households filters from the query string. The response is rendered via `orjson.dumps(pagination_response.model_dump(by_alias=True))` (line 392) — this `model_dump` is what walks every `RecipeSummary` and triggers the per-tool `households_with_tool` lazy load. The comment at line 394, "Response is returned directly, to avoid validation and improve performance", confirms the team has already optimized away one validation pass but the per-tool lazy-load remains. The route registers as `@router.get("", response_model=PaginationBase[RecipeSummary])` (line 340), so the response contract is `PaginationBase[RecipeSummary]` — any refactor must produce byte-identical JSON for that shape.

### Artifact: `BaseRecipeController.group_recipes` — household scope toggle
- **path**: `mealie/routes/recipe/_base.py`
- **key symbols**: `BaseRecipeController.recipes`, `BaseRecipeController.group_recipes`, `JSONBytes`
- **line_ranges**: `37-57` (controller helpers), `20-29` (`JSONBytes` response class)
- **importance**: relevant
- **reason**: `self.group_recipes` uses `household_id=None` (line 44) so the list view spans all households in the user's group; the household filter is then re-imposed via the route-level `households` query parameter through `RepositoryRecipes._build_recipe_filter`. Any refactor that adds JOINs must NOT silently include household secondary tables that broaden the parent SELECT and leak rows across households in the same group — see also the public-explore caller below.

---

## Relevant artifacts (provide context)

### Artifact: prior art — `RecipeToolOut.loader_options`
- **path**: `mealie/schema/recipe/recipe_tool.py`
- **key symbols**: `RecipeToolOut`, `RecipeToolOut.loader_options`, `RecipeToolOut.convert_households_to_slugs`, `RecipeToolResponse.loader_options`
- **line_ranges**: `18-39` (`RecipeToolOut` with selectinload), `42-53` (`RecipeToolResponse` extended loader)
- **importance**: relevant (textbook prior art)
- **reason**: The same `convert_households_to_slugs` validator exists here (lines 25-33), and `RecipeToolOut.loader_options()` returns `[selectinload(Tool.households_with_tool)]` (lines 36-39). This is the exact pattern that must be chained into `RecipeSummary.loader_options()` as `selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)`. `RecipeToolResponse.loader_options` at lines 47-53 is the pattern when the parent already loaded `Tool` via a relationship — chain selectinload on the parent relationship, then chain again on `Tool.households_with_tool`.

### Artifact: prior art — `IngredientFood.loader_options`
- **path**: `mealie/schema/recipe/recipe_ingredient.py`
- **key symbols**: `IngredientFood`, `IngredientFood.loader_options`, `IngredientFood.convert_households_to_slugs`
- **line_ranges**: `102-134` (class with selectinload + symmetric validator)
- **importance**: relevant (textbook prior art)
- **reason**: Symmetric to `RecipeTool`. `IngredientFood.households_with_ingredient_food` has the identical validator (lines 125-133) and the loader uses `selectinload(IngredientFoodModel.households_with_ingredient_food)` (line 120). Confirms that across two separate schemas, Mealie's idiomatic fix is `selectinload`, not `joinedload`, for the household-with-* relationship.

### Artifact: downstream callers of `RecipeSummary.loader_options` that benefit transitively
- **paths** and **line_ranges**:
  - `mealie/schema/meal_plan/new_meal.py:62-74` — `ReadPlanEntry.loader_options` already chains `selectinload(GroupMealPlan.recipe).joinedload(RecipeModel.recipe_category|tags|tools)` and `selectinload(GroupMealPlan.user).load_only(User.household_id)`; same bug surface (no chained `selectinload(Tool.households_with_tool)`).
  - `mealie/schema/household/group_shopping_list.py:192-208` — `ShoppingListRecipeRefOut.loader_options` does the same on `ShoppingListRecipeReference.recipe`.
- **importance**: relevant
- **reason**: Fixing `RecipeSummary.loader_options()` in isolation only repairs paths that explicitly use it. Meal-plan reads and shopping-list reads carry their own loader graphs that ALSO load `RecipeSummary` indirectly. If the refactor only touches `RepositoryRecipes.page_all` (inline `.options(...)`), these adjacent N+1 sites remain. If the refactor touches `RecipeSummary.loader_options()`, all three benefit — but the call sites at `meal_plan/new_meal.py` and `group_shopping_list.py` still embed their own M2M joinedloads that should be updated for consistency.

### Artifact: additional `recipes.page_all` call sites (multi-tenant correctness sweep)
- **paths**:
  - `mealie/routes/recipe/recipe_crud_routes.py:370` — primary `GET /api/recipes`.
  - `mealie/routes/organizers/controller_categories.py:131-134` — `GET /organizers/categories/slug/{category_slug}` reuses `group_recipes.page_all(PaginationQuery(per_page=-1, query_filter=...))` with `per_page=-1` meaning "all rows". This is the largest possible blast radius for the N+1 fix.
  - `mealie/routes/explore/controller_public_recipes.py:67-80` — public unauthenticated explore route uses `cross_household_recipes.page_all(...)` and injects `(household.preferences.privateHousehold = FALSE AND settings.public = TRUE)` as a query_filter (lines 61-65). Multi-tenant correctness must hold here even more strictly.
  - `mealie/routes/households/controller_mealplan.py:65` — `cross_household_recipes.page_all` for meal planning.
- **importance**: relevant
- **reason**: Five call sites. Any inline `.options(...)` change to `RepositoryRecipes.page_all` instantly benefits all five. The `controller_categories.py` site uses `per_page=-1` (all rows in the group), so it is the worst-case N+1 site in the codebase.

### Artifact: `RepositoryFactory.AllRepositories` and `recipes` property
- **path**: `mealie/repos/repository_factory.py`
- **key symbols**: `AllRepositories.recipes`, `AllRepositories.group_recipes`, `get_repositories`
- **line_ranges**: `1-80` (imports including `RecipeModel`, `Tool`, `Tag`, `Category`, `HouseholdToRecipe`, `UserToRecipe`)
- **importance**: relevant
- **reason**: Confirms `RecipeModel` and `Tool` are already importable at the repo/schema layer, so chained loaders do not introduce new cross-module imports. The factory exposes `recipes` (household-scoped) and `group_recipes` (group-only) — both return `RepositoryRecipes`. No new repo class is needed for the refactor.

### Artifact: secondary tables — indexing baseline
- **paths**:
  - `mealie/db/models/recipe/tool.py:17-31` — `households_to_tools` (`household_id`, `tool_id` indexed individually + composite unique) and `recipes_to_tools` (same).
  - `mealie/db/models/recipe/tag.py:19-25` — `recipes_to_tags` (recipe_id, tag_id indexed individually + composite unique).
  - `mealie/db/models/recipe/category.py:35-41` — `recipes_to_categories` (recipe_id, category_id indexed individually + composite unique).
- **importance**: relevant
- **reason**: All three secondary tables already have indexes on both columns and a composite unique constraint. `selectinload`'s child SELECT (`SELECT ... FROM tags JOIN recipes_to_tags WHERE recipes_to_tags.recipe_id IN (...)`) uses the existing `recipe_id` index on the secondary table — no migration is required. The PR description's "indexes added" section can legitimately say "no new indexes required; existing per-column indexes on the secondary tables cover the selectinload IN-list lookups."

---

## Current query trace — `GET /api/recipes?perPage=50` (best inference from code)

Assuming a freshly-logged-in user in a group with 50 recipes returned, where each recipe has ~3 `recipe_category`, ~5 `tags`, ~4 `tools`, and each tool has ~2 `households_with_tool`. Trace through `repository_recipes.py:220-293` → `repository_generic.py:357-405` → `RecipeSummary.model_validate` → JSON serialization:

| # | Query | Source | Per-recipe? |
|---|-------|--------|-------------|
| 1 | `SELECT COUNT(*) FROM (SELECT DISTINCT recipes.* WHERE group_id=? AND household_id IS NOT NULL [...] ORDER BY NULL).sq` | `repository_generic.py:376-377` via `add_pagination_to_query(q, pagination)` called at `repository_recipes.py:274` | no (one per request) |
| 2 | `SELECT recipes.*, users.household_id FROM recipes [LEFT OUTER JOIN users ON ...] LEFT OUTER JOIN recipes_to_categories ... LEFT OUTER JOIN categories ... LEFT OUTER JOIN recipes_to_tags ... LEFT OUTER JOIN tags ... LEFT OUTER JOIN recipes_to_tools ... LEFT OUTER JOIN tools ... WHERE ... ORDER BY recipes.created_at DESC LIMIT 50` — SQLAlchemy detects `joinedload` on multiple collections + LIMIT and switches to "subquery+JOIN" semantics, producing ~50 × 3 × 5 × 4 = 3000 rows that `.unique()` deduplicates to 50 distinct recipe objects | `repository_recipes.py:277-280` applying `RecipeSummary.loader_options()` from `schema/recipe/recipe.py:170-174` | no (one per request, but bloated) |
| 3..N+2 | For **each tool of each recipe**, on first attribute access of `tool.households_with_tool` during `RecipeTool.convert_households_to_slugs` (`schema/recipe/recipe.py:87-95`): `SELECT households.* FROM households JOIN households_to_tools ON ... WHERE households_to_tools.tool_id = ?` | `db/models/recipe/tool.py:54-56` (default lazy="select") triggered by `pagination_response.model_dump(by_alias=True)` in `routes/recipe/recipe_crud_routes.py:392` | **yes — 1 query per unique `tool` instance** |

If 50 recipes share ~30 distinct tools after deduplication, that is **~32 queries** for perPage=50 (1 COUNT + 1 SELECT + 30 lazy loads). For perPage=200 with ~100 unique tools, it becomes **~102 queries**. The exact growth function is "1 + 1 + |distinct tools in page|" rather than strict O(N=recipes), but the user-perceived spec-N (`recipe count`) drives the tool diversity, so the spec's "N+1" framing is correct in observable behavior.

**Target after refactor:**

| # | Query |
|---|-------|
| 1 | COUNT subquery (unchanged) |
| 2 | `SELECT recipes.*, users.household_id FROM recipes JOIN users ON ... WHERE ... LIMIT 50` — single-object joinedload on `user` is benign; no collection JOINs |
| 3 | `SELECT categories.*, recipes_to_categories.recipe_id FROM categories JOIN recipes_to_categories WHERE recipes_to_categories.recipe_id IN (?,?,...)` — selectinload for `recipe_category` |
| 4 | Same shape for `tags` — selectinload |
| 5 | Same shape for `tools` — selectinload |
| 6 | `SELECT households.*, households_to_tools.tool_id FROM households JOIN households_to_tools WHERE households_to_tools.tool_id IN (?,?,...)` — **chained** selectinload for `Tool.households_with_tool` |

Total: **6 queries regardless of N**. The spec test's `<= 5` ceiling is tight: hitting it requires either (a) dropping `households_with_tool` from the response (NOT allowed — must keep response identical), (b) folding `tools` and `households_with_tool` into a single join that pre-aggregates household slugs (e.g., `selectinload(RecipeModel.tools).options(load_only(Tool.id, Tool.name, Tool.slug, Tool.group_id), selectinload(Tool.households_with_tool).load_only(Household.slug))` — still 5 statements: COUNT + recipes + 3 selectinloads + the chained one folds into the tools select via SQLAlchemy's planner only sometimes), or (c) accepting that the test's `<= 5` cap may need to be `<= 6` once the implementer measures actual statement counts. **The robust target is `<= 6` queries with `count_large - count_small <= 1` (only the IN-list grows; statement count is constant).** The spec's primary assertion `count_large <= count_small + 3` is comfortably satisfied; the secondary `count_large <= 5` may require the implementer to consult the spec author.

---

## Eager-loading seams — where `loader_options` should be extended

1. **Primary seam — `RecipeSummary.loader_options()` (`mealie/schema/recipe/recipe.py:168-175`)** — the single highest-leverage fix:
   ```python
   # Proposed shape (illustrative — implementer owns final form)
   return [
       selectinload(RecipeModel.recipe_category),
       selectinload(RecipeModel.tags),
       selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool),
       joinedload(RecipeModel.user).load_only(User.household_id),
   ]
   ```
   - Converts the three M2M joinedloads to selectinload (eliminates LIMIT+joinedload cartesian inflation).
   - Adds the missing `selectinload(Tool.households_with_tool)` chained off `RecipeModel.tools` (eliminates per-tool lazy load).
   - Keeps `joinedload(RecipeModel.user).load_only(User.household_id)` because `user` is uselist=False and `RecipeModel.household_id` is an association_proxy through it.

2. **Secondary seam — inline `.options(...)` at `repository_recipes.py:277`** — only needed if the implementer wants to localize the change without affecting `ReadPlanEntry` / `ShoppingListRecipeRefOut`. The downside is that the bug stays for adjacent callers.

3. **Adjacent seams that should also be updated for consistency** (not strictly required by the spec, but flagged for the CR phase):
   - `mealie/schema/meal_plan/new_meal.py:67-74` (`ReadPlanEntry.loader_options`) — same joinedload-on-M2M pattern, same `households_with_tool` gap.
   - `mealie/schema/household/group_shopping_list.py:202-208` (`ShoppingListRecipeRefOut.loader_options`) — same.

4. **Non-seams (do NOT touch in this refactor):**
   - `Recipe.loader_options()` at `mealie/schema/recipe/recipe.py:299-320` — already uses selectinload for collections; serves only `GET /api/recipes/{slug}` (one row), so per-tool lazy is bounded and acceptable for now.
   - `RepositoryRecipes.find_suggested_recipes` at `mealie/repos/repository_recipes.py:361-532` — separate endpoint, uses its own subqueries for tool/food unmatched counts; not on the spec's hot path.

---

## Cross-perspective questions

- **API perspective:** Does the public `GET /api/recipes` response JSON include `households_with_tool` inside every `tools[]` entry? (Verified: yes, via `RecipeTool.households_with_tool: list[str] = []` at `schema/recipe/recipe.py:85`.) Are any clients depending on the **order** of `tools[]` / `tags[]` / `recipe_category[]` — selectinload preserves parent ordering but does NOT guarantee child order without an explicit `order_by`?
- **API perspective:** The spec lists `slug_image` as a response field (`input.md:23`). `slug_image` does **not** exist on `RecipeSummary` in this checkout (grep returns no matches). Is the spec author asking for it to be added (which would violate "fields 100% unchanged"), or is it a typo for `slug` + `image`?
- **Test perspective:** Does the existing test suite have a `before_cursor_execute` listener fixture? The spec's regression test attaches one inline; if a shared `query_counter` fixture already exists in `tests/conftest.py` or `tests/fixtures/`, the implementer should reuse it.
- **Test perspective:** What `engine` does the spec test target — the test-app session-bound engine, or the global `mealie/db/db_setup.py` engine? The test as written imports a module-level `engine`; in Mealie's setup the engine is created per-test-DB in `tests/conftest.py`, so the listener must attach there to capture the right cursor.
- **Multi-tenant perspective:** With `cross_household_recipes` (household_id=None) at `mealie/routes/explore/controller_public_recipes.py:67`, does selectinload of `Tool.households_with_tool` accidentally return households that belong to OTHER groups? Tools are group-scoped (`Tool.group_id`, `db/models/recipe/tool.py:48`) but the `households_with_tool` secondary table has no `group_id`; the implementer must confirm `households_with_tool` only contains households of the same group via FK chain (likely yes via `Tool.group_id` filter on the parent recipe selectinload chain — but worth verifying).
- **Pagination perspective:** `add_pagination_to_query` at `repository_generic.py:376-377` calls `query.order_by(None).distinct().subquery()` for the COUNT. After switching collection loaders to selectinload, does the `.distinct()` still produce the correct count? (Yes — selectinload doesn't add JOINs to the parent query, so the count subquery is unaffected; this is precisely why selectinload is the correct strategy.)
- **EXPLAIN ANALYZE perspective:** The spec requires before/after EXPLAIN ANALYZE. Postgres and SQLite plan differently for `IN (?, ?, ?)` lists; the implementer should report both backends or at least disclose which they captured.
- **Comments-count perspective:** The spec's business background mentions "recent comments count" as part of the N+1 root cause, but `RecipeSummary` does not include a comments count field today and no comments relationship is touched by its current `loader_options`. Should the implementer treat this as a non-issue (no field → no query → no N+1), or proactively add a `COUNT(comments)` aggregate column? "Fields 100% unchanged" argues for the former.
