# Stage 3.5 — Consolidated Findings (deduped across 5 perspectives)

> Inputs: `exploration\data_perspective.md`, `exploration\api_perspective.md`,
> `exploration\test_perspective.md`, `exploration\history_perspective.md`,
> `exploration\ui_perspective.md`. Mealie source: `C:\Users\v-liyuanjun\Downloads\mealie\`.
> All line ranges in this document have been re-opened in the on-disk source.

---

## 1. Five-perspective consensus (verified facts)

Items marked ✅ are independently asserted by ≥ 2 perspectives **and** verified against the on-disk source at the cited line ranges.

| # | Verified fact | Citation | Asserted by |
|---|---------------|----------|-------------|
| C-1 | `GET /api/recipes` is `RecipeController.get_all`, decorated `@router.get("", response_model=PaginationBase[RecipeSummary])`. Calls `self.group_recipes.by_user(self.user.id).page_all(...)` and renders via `JSONBytes(content=orjson.dumps(pagination_response.model_dump(by_alias=True)))`. | `mealie/routes/recipe/recipe_crud_routes.py:340-395` | api, data, test, history |
| C-2 | The list-method seam is `RepositoryRecipes.page_all` — single override of the generic `page_all`. Pagination is applied at L274 via `add_pagination_to_query`, then loader options are attached at L277: `q = q.options(*RecipeSummary.loader_options())`. The "apply options late, so they do not get used for counting" invariant comes from `repository_generic.py:341-342`. | `mealie/repos/repository_recipes.py:220-293`, `mealie/repos/repository_generic.py:315-355` | data, api, history |
| C-3 | The eager-loading seam is `RecipeSummary.loader_options()`. **Today it returns four `joinedload(...)` entries** for `recipe_category`, `tags`, `tools`, and `user.load_only(household_id)`. No chained `selectinload(Tool.households_with_tool)`. | `mealie/schema/recipe/recipe.py:168-175` | data, api, history |
| C-4 | `RecipeTool.households_with_tool: list[str] = []` has a `@field_validator(..., mode="before")` that iterates `household.slug for household in v`. Because `Tool.households_with_tool` is a default-lazy M2M (`orm.relationship("Household", secondary=households_to_tools, ...)`), every `RecipeSummary.model_validate(item)` → per-tool serialization triggers one `SELECT FROM households JOIN households_to_tools WHERE tool_id = ?` per unique tool in the page. **This is the dominant N+1 root cause.** | `mealie/schema/recipe/recipe.py:83-95`, `mealie/db/models/recipe/tool.py:17-23,42-56` | data, api, history, ui |
| C-5 | A secondary inflation source: combining three M2M `joinedload`s with `LIMIT/OFFSET` produces SQLAlchemy's subquery+OUTER JOIN strategy with cartesian-product row blow-up, hence the load-bearing `.scalars().unique().all()` at `repository_recipes.py:280`. Switching M2M loaders to `selectinload` eliminates the cartesian (selectinload runs as a follow-up `SELECT … WHERE recipe_id IN (...)` rather than a JOIN). | `mealie/repos/repository_recipes.py:280` | data, api |
| C-6 | `RecipeModel.household_id` is an **AssociationProxy** through `user` (`association_proxy("user", "household_id")` at `mealie/db/models/recipe/recipe.py:55-56`). Therefore `joinedload(RecipeModel.user).load_only(User.household_id)` is **load-bearing**: dropping it silently regresses to a per-row lazy load on `recipe.user.household_id`. **Keep this loader.** | `mealie/db/models/recipe/recipe.py:55-56`, `mealie/schema/recipe/recipe.py:174` | data, api |
| C-7 | Prior art for the chained `selectinload(Tool.households_with_tool)` pattern is already in the codebase: `RecipeToolOut.loader_options()` returns `[selectinload(Tool.households_with_tool)]`. The symmetric `IngredientFood.loader_options()` uses `selectinload(IngredientFoodModel.households_with_ingredient_food)` for the same anti-pattern. | `mealie/schema/recipe/recipe_tool.py:36-39`, `mealie/schema/recipe/recipe_ingredient.py:117-123` | data, api, history |
| C-8 | The COUNT subquery is `select(func.count()).select_from(query.order_by(None).distinct().subquery())` at `repository_generic.py:376-377`. The `.distinct()` is a load-bearing protection against pre-refactor cartesian inflation (`fix: pagination count correctness #6505`, history-perspective entry #4 `7b325082`). After switching M2M loaders to `selectinload`, the parent SELECT no longer has the M2M JOINs, so the COUNT is a clean `SELECT COUNT(*) FROM (SELECT DISTINCT recipes.id …)`. | `mealie/repos/repository_generic.py:357-405`, history `7b325082` | data, api, history |
| C-9 | **Five existing call sites of `RepositoryRecipes.page_all`** (the loader-options seam transitively affects all of them, but only `/api/recipes` and `/api/explore/groups/{slug}/recipes` are user-facing list endpoints): (a) `mealie/routes/recipe/recipe_crud_routes.py:370` — `GET /api/recipes` (primary), (b) `mealie/routes/explore/controller_public_recipes.py:67-80` — `GET /api/explore/groups/{group_slug}/recipes` (public/cross-household, same shape), (c) `mealie/routes/organizers/controller_categories.py:131-134` — `GET /organizers/categories/slug/{category_slug}` with `per_page=-1` (worst-case fan-out), (d) `mealie/routes/households/controller_mealplan.py:65` — `cross_household_recipes.page_all` for meal-plan random pick. | five files, line ranges above | data, api |
| C-10 | Two adjacent loader seams **also** hydrate `RecipeSummary` indirectly and carry the same joinedload-on-M2M anti-pattern: `ReadPlanEntry.loader_options` (`mealie/schema/meal_plan/new_meal.py:67-74`) and `ShoppingListRecipeRefOut.loader_options` (`mealie/schema/household/group_shopping_list.py:202-208`). They do NOT chain `selectinload(Tool.households_with_tool)` either. Out of strict scope (spec §1 names only `/api/recipes`), but in scope as identified follow-ups. | `mealie/schema/meal_plan/new_meal.py:67-74`, `mealie/schema/household/group_shopping_list.py:202-208` | data, history |
| C-11 | Multi-tenant invariant: `q = sa.select(self.model).filter(self.model.household_id.is_not(None))` at `repository_recipes.py:238` is part of the security filter (commit `d02023e1`, history `#5`). `_build_recipe_filter` enforces `group_id` and (optionally) `household_id` on the parent SELECT at `repository_recipes.py:295-337`. **`selectinload` does NOT add JOINs to the parent SELECT, so these filters are preserved.** | `mealie/repos/repository_recipes.py:238,295-337` | data, api, history, test |
| C-12 | User-correlated `column_aliases["last_made"]` (`_get_last_made_col_alias` at `repository_recipes.py:54-70`) and `column_aliases["rating"]` (`_get_rating_col_alias` at `repository_recipes.py:72-93`) are **correlated scalar subqueries on the parent SELECT** — they emit zero extra cursor executes. Replacing them with JOINs would inflate rows and break `test_order_by_last_made` / `test_order_by_rating`. **Do not touch.** | `mealie/repos/repository_recipes.py:54-93`, `tests/unit_tests/repository_tests/test_recipe_repository.py:593-812` | api, history, test |
| C-13 | `add_pagination_to_query` handles `perPage=-1` → "all" (`repository_generic.py:382-385`) and `page=-1` → "last page" (L392-394). `total_pages = ceil(count / per_page)` (L388). All must be preserved. | `mealie/repos/repository_generic.py:382-394` | api, history |
| C-14 | The route renders via `orjson.dumps(pagination_response.model_dump(by_alias=True))` (L392). **Adding any new field to `RecipeSummary` ships it immediately**, by camelCase alias, with no FastAPI validation guardrail. `task dev:generate` then regenerates `frontend/app/lib/api/types/recipe.ts` — but the wire change is already live. | `mealie/routes/recipe/recipe_crud_routes.py:392`, `frontend/app/lib/api/types/recipe.ts:310-336` | api, ui, history |
| C-15 | The frontend cards (`RecipeCard.vue`, `RecipeCardMobile.vue`, `RecipeCardSection.vue:119-127`) bind exactly 7 fields per item: `name`, `description`, `slug`, `rating`, `image`, `tags`, `id`. The full `RecipeSummary` (26 fields) still ships, including `tools[].households_with_tool` — the validator that drives the N+1. **No UI consumer reads `comments_count` or `slug_image`.** | `frontend/app/components/Domain/Recipe/RecipeCardSection.vue:119-127`, ui §3 | ui, history, api |

---

## 2. Critical conflicts (perspectives disagree → must resolve in `needs_clarification`)

| # | Conflict | Source A | Source B | Resolution |
|---|----------|----------|----------|------------|
| K-1 | **Query-count ceiling.** Input pseudo-code asserts `count_large <= 5` (input.md:67). Data, api, test perspectives all compute the post-refactor minimum as **6 statements** (1 COUNT + 1 parent SELECT including `joinedload(user)` + 3 selectinloads for M2M collections + 1 chained selectinload for `Tool.households_with_tool`). Test perspective recommends a `<= 10` absolute cap. | input.md:67-68 (`<= 5`) | data §"Current query trace" (`<= 6 robust`), api §11 Q5, test §7 (`<= 10`) | Flag as `NC-003`. Recommend the spec ceiling be relaxed to **`<= 8` queries** (6 baseline + small headroom for SQLAlchemy IN-list batching); reaffirm relative bound `count_large <= count_small + 3`. |
| K-2 | **`slug_image` field.** Input lists it as a required-to-preserve response field (input.md:23). `grep -r "slug_image" mealie/` returns **zero hits**. Generated TS `RecipeSummary` (26 fields) does not include it. | input.md:23 | api §5 ("no such field"), ui §2.6, history §3 (TL;DR #4) | Flag as `NC-004`. Drop from scope — treat as typo for `slug` + `image` (which both exist and must remain). |
| K-3 | **`comments_count` / "recent comment counts" framing.** Input business background (input.md:13) lists comments-count as an N+1 victim. Reality: `RecipeSummary` has no comments field, `comments` relationship is **not** in `RecipeSummary.loader_options()`, and `grep` for `comment_count|commentsCount` in `frontend/app/` returns zero hits. | input.md:13 | api §5 ("comments are NOT in the list response"), ui §1.5, history TL;DR #4 | Flag as `NC-005`. Treat as a non-issue — no field, no query, no N+1. Adding the field would violate "fields 100% unchanged". |
| K-4 | **N+1 root cause framing.** Input frames the problem as "per-recipe additional queries for tags/categories/tools/recent comments/image metadata" (input.md:13). Reality: tags/categories/tools are already `joinedload`-ed (so they're already eager); image is a scalar column; comments aren't in the response. The **actual** N+1 is per-tool `Tool.households_with_tool` lazy-load, plus secondary joinedload-on-M2M cartesian inflation. | input.md:13-15 | data §"Critical artifacts" (Tool §), api §10, history TL;DR #1, ui §5 Q7 | Address in spec FR-006 (chained `selectinload(Tool.households_with_tool)`) and self_concerns SC-001 (warn reviewers that the fix targets a specific seam, not the literal symptom names). |
| K-5 | **Async vs sync test framing.** Input pseudo-code uses `@pytest.mark.asyncio` and `async def` (input.md:42-43). Mealie test suite is fully synchronous; `pytest-asyncio` is not in `pyproject.toml`; zero existing tests use `async def`. | input.md:42-43 | test §0 (critical correction), `mealie/db/db_setup.py:38` (`sa.create_engine`, sync), `tests/conftest.py:45-46` (`TestClient`, sync) | Flag as `NC-006`. Write the regression test as plain sync `def` using the existing `api_client` + `unique_user_fn_scoped` fixtures and `event.listens_for(Engine, "before_cursor_execute")`. |
| K-6 | **Scope: list endpoints covered.** Input §1 names only `/api/recipes`. Data perspective notes the loader seam transitively benefits 5 callers. UI perspective + history both flag `/api/explore/groups/{slug}/recipes` as the second user-facing list endpoint. | input.md:19 (only `/api/recipes`) | data §"Eager-loading seams", api §8 (explore route shares `page_all`) | Flag as `NC-002`. **Recommend fixing the seam (covers both endpoints)** but scope the regression test only to `/api/recipes` per input. Adjacent loader seams (`ReadPlanEntry`, `ShoppingListRecipeRefOut`) deferred — captured in `self_concerns` SC-002. |
| K-7 | **`rating` source.** Input lists `rating` as a response field to preserve (input.md:25). It is **both** a scalar column on `RecipeModel` (line 61) **and** a per-user correlated subquery via `column_aliases["rating"]` when `by_user(user_id)` is set (which `/api/recipes` always does at `recipe_crud_routes.py:370`). | input.md:25 | data, api §3, history §2.3 (correlated subquery pattern) | Flag as `NC-001`. **No aggregation required** — already a correlated subquery on the parent SELECT (zero extra cursor executes). Do not denormalize / batch / add new aggregate. |

No other material conflicts. All five perspectives agree on the architectural seam (`RecipeSummary.loader_options`), the load-bearing invariants (`apply options late`, `household_id IS NOT NULL`, `column_aliases` as correlated subqueries, `joinedload(user).load_only(...)`), and the non-seams to avoid (`Recipe.loader_options` and `find_suggested_recipes`).

---

## 3. Current-state query trace summary (`GET /api/recipes?perPage=50`)

Synthesized from data §"Current query trace", api §6, history §2.2. All line ranges re-verified.

**Today (joinedload baseline):**

| # | Statement | Source | Per-recipe? |
|---|-----------|--------|-------------|
| 1 | `SELECT COUNT(*) FROM (SELECT DISTINCT recipes.* … WHERE group_id=? AND household_id IS NOT NULL [+ filters] ORDER BY NULL).sq` | `repository_generic.py:376-377` invoked from `repository_recipes.py:274` | no (one per request) |
| 2 | `SELECT recipes.*, users.household_id FROM recipes LEFT OUTER JOIN users LEFT OUTER JOIN recipes_to_categories … LEFT OUTER JOIN recipes_to_tags … LEFT OUTER JOIN recipes_to_tools … WHERE … LIMIT 50` — single statement, but `joinedload`-on-three-M2Ms + `LIMIT` triggers SQLAlchemy's subquery+OUTER-JOIN strategy → ~50 × 3 × 5 × 4 = **3 000 rows** that `.unique()` deduplicates to 50 distinct recipes (`repository_recipes.py:280`) | `repository_recipes.py:277-280` applying `schema/recipe/recipe.py:170-174` | no (one per request, but bloated) |
| 3 … N+2 | For **each unique `Tool` in the page**, on first attribute access of `tool.households_with_tool` during `RecipeTool.convert_households_to_slugs`: `SELECT households.* FROM households JOIN households_to_tools ON households_to_tools.household_id = households.id WHERE households_to_tools.tool_id = ?` | `db/models/recipe/tool.py:54-56` (default `lazy="select"`) triggered by `pagination_response.model_dump(by_alias=True)` at `routes/recipe/recipe_crud_routes.py:392` | **yes — 1 query per unique `tool` instance** |

Observed growth function: `statement_count = 2 + |unique tools in page|`. For perPage=50 with ~30 unique tools → ~32 statements. For perPage=200 with ~100 unique tools → ~102 statements. The user-perceived `O(N=recipes)` framing is a faithful approximation because tool diversity grows monotonically with recipe count.

**Target after refactor (Conservative `RecipeSummary.loader_options()` extension):**

| # | Statement | Per-recipe? |
|---|-----------|-------------|
| 1 | `SELECT COUNT(*) FROM (SELECT DISTINCT recipes.id … FROM recipes [filters]).sq` (unchanged, but no JOIN inflation) | no |
| 2 | `SELECT recipes.*, users.household_id FROM recipes JOIN users ON recipes.user_id = users.id WHERE … LIMIT 50` — parent SELECT with the benign 1:1 `joinedload(user)` (preserves the AssociationProxy data source). No M2M JOINs. | no |
| 3 | `SELECT categories.*, recipes_to_categories.recipe_id FROM categories JOIN recipes_to_categories ON … WHERE recipes_to_categories.recipe_id IN (?, ?, …)` — `selectinload(RecipeModel.recipe_category)` | no |
| 4 | Same shape for `tags` — `selectinload(RecipeModel.tags)` | no |
| 5 | Same shape for `tools` — `selectinload(RecipeModel.tools)` | no |
| 6 | `SELECT households.*, households_to_tools.tool_id FROM households JOIN households_to_tools ON … WHERE households_to_tools.tool_id IN (?, ?, …)` — **chained** `selectinload(Tool.households_with_tool)` | no |

Total: **6 statements regardless of N**. With SQLAlchemy's default IN-list chunk size of 500, perPage=-1 with > 500 recipes would split each selectinload into 2 chunks → up to **9 statements** worst case. → spec ceiling **`<= 8`** is robust for the common case; per-perspective recommendation widens to **`<= 10`** to absorb middleware/savepoint noise.

---

## 4. Seam map (where to change code)

| Seam | Path:Lines | Action | Why |
|------|------------|--------|-----|
| **Primary** | `mealie/schema/recipe/recipe.py:168-175` | Replace 3× `joinedload` for M2M with `selectinload`; chain `.selectinload(Tool.households_with_tool)` off `selectinload(RecipeModel.tools)`; keep `joinedload(RecipeModel.user).load_only(User.household_id)` | One-edit fix; transitively benefits all 5 `page_all` callers + the explore route. C-3, C-4, C-6, C-7 |
| **Adjacent (in scope as identified follow-up, NOT primary)** | `mealie/schema/meal_plan/new_meal.py:67-74`, `mealie/schema/household/group_shopping_list.py:202-208` | Same swap (joinedload→selectinload + chained selectinload(Tool.households_with_tool)) | Same anti-pattern; flagged in self_concerns SC-002 |
| **Non-seam (do NOT touch)** | `mealie/schema/recipe/recipe.py:299-320` (`Recipe.loader_options`) | none | Already selectinload-based; serves single-recipe `GET /api/recipes/{slug}` only; no list scaling concern |
| **Non-seam (do NOT touch)** | `mealie/repos/repository_recipes.py:54-93` (`column_aliases`) | none | Already correlated scalar subqueries — zero extra cursor executes. Replacing with JOINs would break `test_order_by_last_made`/`test_order_by_rating` (C-12). |
| **Non-seam (do NOT touch)** | `mealie/repos/repository_recipes.py:238` (`filter(self.model.household_id.is_not(None))`) | none | Multi-tenant safety filter (C-11, history `d02023e1`). |
| **Non-seam (do NOT touch)** | `mealie/repos/repository_generic.py:357-405` (`add_pagination_to_query`) | none | Count subquery, perPage=-1/page=-1 semantics, order-by handling (C-8, C-13). |
| **New test** | `tests/integration_tests/test_recipe_list_query_count.py` | Create sync `def` test using `engine` from `mealie/db/db_setup.py:45`, `event.listens_for(Engine, "before_cursor_execute")`, `unique_user_fn_scoped` fixture, `api_routes.recipes`. | Spec §3, K-5, test §7 |

---

## 5. Risks register (consolidated from data + api + history)

| Risk | Mitigation |
|------|------------|
| Dropping `joinedload(user).load_only(household_id)` → AssociationProxy lazy-load per row | **Keep** that loader (C-6). Add a comment explaining why. |
| Applying loader options BEFORE `add_pagination_to_query` → COUNT subquery sees M2M JOINs → `total` regression (history `7b325082`) | Keep the L277 ordering (`q.options(...)` AFTER L274 `add_pagination_to_query`). Test asserts `total` equals seeded count. |
| `selectinload` IN-list batching at 500 default chunk size → 2 chunks per relationship for perPage > 500 | Set the spec ceiling at `<= 8` (typical) and `<= 10` (absolute, accommodating chunking). |
| `selectinload(Tool.households_with_tool)` leaking cross-group households | `Tool.group_id` is enforced at parent SELECT via `Category.group_id`/`Tag.group_id`/`Tool.group_id` filters. `households_with_tool` is loaded for **tools already filtered to the user's group** — no leakage. Verified by `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102`. |
| Removing `.unique()` at L280 → potential row duplication | **Do NOT remove `.unique()`**. It becomes a no-op once joinedload-on-M2M is gone (selectinload doesn't add JOINs), but leaving it costs nothing and protects against future regressions. |
| Spec mentions adding indexes — implementer might add unnecessary migration | All three secondary tables (`recipes_to_categories`, `recipes_to_tags`, `recipes_to_tools`, `households_to_tools`) already index both columns + composite unique constraint. **No migration required.** Document this in PR description. |
| Sort by `random` (`pagination_seed`) materializes IDs to Python (`repository_generic.py:436-449`) | Out of N+1 scope but the query-count test should NOT use `orderBy=random` to avoid noise. Optional sibling parametrize for the explore route is fine. |
| Adjacent `ReadPlanEntry` / `ShoppingListRecipeRefOut` loader seams retain the anti-pattern | Out of strict spec scope; capture as `self_concerns` SC-002 and propose as PR follow-up. |
