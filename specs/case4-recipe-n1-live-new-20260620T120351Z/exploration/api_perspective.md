# API Perspective — `GET /api/recipes` N+1 Refactor

> **Repo**: `C:\Users\v-liyuanjun\Downloads\mealie`  
> **Branch state**: HEAD of local working copy (line numbers verified against on-disk files at exploration time).

---

## 1. The route under refactor — `GET /api/recipes`

| Field | Value |
|-------|-------|
| Path | `mealie/routes/recipe/recipe_crud_routes.py` |
| Symbol | `RecipeController.get_all` |
| Line range | **340–395** |
| Importance | **CRITICAL** — this is the endpoint the spec targets |
| Reason | Decorator `@router.get("", response_model=PaginationBase[RecipeSummary])` at L340; the controller delegates to `self.group_recipes.by_user(self.user.id).page_all(...)` at L370–383. Response is short-circuited to `JSONBytes` (L395) so FastAPI does **not** re-validate `model_dump(by_alias=True)` — the wire bytes are produced directly from `RecipePagination.model_dump(by_alias=True)` (L386–395). Any change to fields, ordering, or pagination keys flows straight to clients without a validation guardrail. |

Mounted router prefix: `UserAPIRouter(prefix="/recipes", route_class=MealieCrudRoute)` at L85 ⇒ final path `/api/recipes` (the `/api` segment is added by app-level prefix in `mealie/app.py`).

### Controller plumbing

| Field | Value |
|-------|-------|
| Path | `mealie/routes/recipe/_base.py` |
| Symbol | `BaseRecipeController.group_recipes` (and `recipes`, `service`, `mixins`) |
| Line range | **37–56** |
| Importance | HIGH |
| Reason | `group_recipes` is a `@cached_property` (L42–44) that creates a `RepositoryRecipes` scoped to `group_id` with `household_id=None`. This is what enables cross-household listing inside the same group (necessary for the multitenant guarantee in spec §5). The `.by_user(self.user.id)` call before `.page_all` returns `Self` (see repo §3 below) and arms the user-specific `column_aliases` for `last_made`/`rating`. |

---

## 2. The method to rewrite — `RepositoryRecipes.page_all`

| Field | Value |
|-------|-------|
| Path | `mealie/repos/repository_recipes.py` |
| Symbol | `RepositoryRecipes.page_all` |
| Line range | **220–293** |
| Importance | **CRITICAL** — this is the actual N+1 site |
| Reason | Builds the query at L238–268, applies pagination via the generic helper at L274, then **applies eager-loader options AFTER counting/limiting** (L277): `q = q.options(*RecipeSummary.loader_options())`. The `.unique()` on L280 is the smoking-gun that the loaders currently produce duplicated rows from JOINs — i.e. today the implementation pays a Cartesian product cost just to dedupe in Python. Refactor must keep the `.scalars().unique().all()` semantics correct OR switch all M:N relationships to `selectinload` so dedupe becomes a no-op. |

### Class declaration & `__init__`

| Field | Value |
|-------|-------|
| Path | `mealie/repos/repository_recipes.py` |
| Symbol | `class RepositoryRecipes(HouseholdRepositoryGeneric[Recipe, RecipeModel])` |
| Line range | **36–52** |
| Importance | HIGH |
| Reason | Parent is `HouseholdRepositoryGeneric` (defined at `mealie/repos/repository_generic.py:505–523`), constructor requires both `group_id` and `household_id` kwargs (`KEYWORD_ONLY`). `by_user(user_id)` (L49–52) mutates `self.user_id` in place and returns `Self`, which is what activates the per-user `column_aliases`. |

---

## 3. User-correlated `column_aliases` — the order-by trap

| Field | Value |
|-------|-------|
| Path | `mealie/repos/repository_recipes.py` |
| Symbol | `RepositoryRecipes.column_aliases`, `_get_last_made_col_alias`, `_get_rating_col_alias` |
| Line range | **39–93** |
| Importance | **CRITICAL for correctness during refactor** |
| Reason | These are **correlated scalar subqueries** that are injected into `ORDER BY` via `add_order_attr_to_query` (`repository_generic.py:407–430`, esp. L414: `order_attr = self.column_aliases.get(order_attr.key, order_attr)`). When `orderBy=lastMade` or `orderBy=rating` is requested, every row of the outer recipe query carries a correlated `SELECT … FROM household_to_recipe WHERE recipe_id = recipes.id AND household_id = (SELECT user.household_id FROM users WHERE user.id = :user_id)` subquery. This is _not_ N+1 — it's a single SQL statement that the database planner handles — but **a naive rewrite using `JOIN household_to_recipe ON …` + `LIMIT` would silently inflate the result set** (multi-row join with other M:N JOINs) and break the existing ordering tests at `tests/unit_tests/repository_tests/test_recipe_repository.py:593-688`. Keep `column_aliases` as scalar subqueries — refactor only the **payload eager-load**, not the order-by machinery. |

---

## 4. The eager-loader hot path — `RecipeSummary.loader_options`

| Field | Value |
|-------|-------|
| Path | `mealie/schema/recipe/recipe.py` |
| Symbol | `RecipeSummary.loader_options` (classmethod) |
| Line range | **168–175** |
| Importance | **CRITICAL — the source of the Cartesian product** |
| Reason | Today returns 4 `joinedload(...)` entries for `recipe_category` (M:N), `tags` (M:N), `tools` (M:N), and `user` (1:1 with `.load_only(User.household_id)`). Combining three M:N `joinedload`s with a paginated outer query is the textbook N×M×K Cartesian explosion: with 100 recipes × avg 3 tags × 3 categories × 2 tools you get a single SQL statement returning ~1800 rows that Python deduplicates via `.scalars().unique()` (L280 of `repository_recipes.py`). The literal symptom matching the input spec's "N+1" framing happens slightly differently in practice: in production with `joinedload` + `LIMIT`, **SQLAlchemy emits a subquery rewrite that triggers per-recipe lazy loads when the subquery loses ordering** (see the comment at `recipe.py:318`: _"for whatever reason, joinedload can mess up the order here, so use selectinload just this once"_). Either way, the fix is the same: convert the three M:N `joinedload`s to `selectinload` (1 extra SELECT per relationship, total ≤ 4 queries regardless of N). |

### Adjacent reference — `Recipe.loader_options` (full schema, NOT the list endpoint)

| Field | Value |
|-------|-------|
| Path | `mealie/schema/recipe/recipe.py` |
| Symbol | `Recipe.loader_options` |
| Line range | **299–320** |
| Importance | MEDIUM (informational) |
| Reason | Already uses `selectinload` for `tags`, `tools`, ingredients, instructions, etc., with a self-documenting comment at L318 about joinedload-ordering misbehavior. **Use this as the model pattern** for the `RecipeSummary` rewrite — the rest of the codebase has already converged on `selectinload` for M:N collections. |

---

## 5. The response schema — `RecipeSummary` (the API contract)

| Field | Value |
|-------|-------|
| Path | `mealie/schema/recipe/recipe.py` |
| Symbol | `class RecipeSummary(MealieModel)` |
| Line range | **116–175** |
| Importance | **CRITICAL — this is the contract** |
| Reason | Drives both the wire JSON and the eager-loader set. All fields below MUST appear in the output, in this order, with these aliases. |

### Field-level wire contract

`MealieModel` (`mealie/schema/_mealie/mealie_model.py:45–53`) sets `model_config = ConfigDict(alias_generator=camelize, populate_by_name=True)`, and the route serializes with `model_dump(by_alias=True)` (`recipe_crud_routes.py:392`). Therefore the **on-the-wire keys are camelCase**:

| Python attribute (L#) | Wire key | Source |
|---|---|---|
| `id` (117) | `id` | column |
| `user_id` (120) | `userId` | column |
| `household_id` (121) | `householdId` | `AssociationProxy` from `user.household_id` |
| `group_id` (122) | `groupId` | column |
| `name` (124) | `name` | column |
| `slug` (125) | `slug` | column |
| `image` (126) | `image` | column (integer cache-buster) |
| `recipe_servings` (127) | `recipeServings` | column |
| `recipe_yield_quantity` (128) | `recipeYieldQuantity` | column |
| `recipe_yield` (129) | `recipeYield` | column |
| `total_time` (131) | `totalTime` | column |
| `prep_time` (132) | `prepTime` | column |
| `cook_time` (133) | `cookTime` | column |
| `perform_time` (134) | `performTime` | column |
| `description` (136) | `description` | column |
| `recipe_category` (137) | `recipeCategory` | **M:N via `recipes_to_categories`** |
| `tags` (138) | `tags` | **M:N via `recipes_to_tags`** |
| `tools` (139) | `tools` | **M:N via `recipes_to_tools`** |
| `rating` (140) | `rating` | column **OR** user-aware alias (see §3) |
| `org_url` (141) | **`orgURL`** | explicit `Field(alias="orgURL")` — special-cased, NOT camelize |
| `date_added` (143) | `dateAdded` | column |
| `date_updated` (144) | `dateUpdated` | column |
| `created_at` (146) | `createdAt` | inherited mixin |
| `updated_at` (147) | `updatedAt` | inherited mixin (`UpdatedAtField`) |
| `last_made` (148) | `lastMade` | column **OR** user-aware alias (see §3) |

**There is no `slug_image` field** on `RecipeSummary`. The input spec lists `slug_image` as a required field, but `grep -r "slug_image" mealie/` returns zero hits — clients reconstruct the image URL from `id` + `image` (cache-buster). This is a **spec inaccuracy to flag back, not a field to preserve**.

**Comments are NOT in the list response.** `comments`/`comments_count` exist only on the full `Recipe` schema (L193) and are not in `RecipeSummary`. The input spec's mention of "最近评论数" (recent comment counts) as an N+1 source is **incorrect for `GET /api/recipes`** — the actual N+1 trigger is the joined-load Cartesian product on the three M:N collections, not comments. Flag in cross-perspective Q's.

### Field validators that MUST keep firing

| Symbol | Line range | What it normalizes |
|--------|------------|--------------------|
| `clean_numbers` | 151–153 | `recipe_servings`/`recipe_yield_quantity`: None / "" / 0 → `0` |
| `clean_strings` | 155–162 | time fields + `recipe_yield`: numeric → string |

These run on every `RecipeSummary.model_validate(item)` (currently at `repository_recipes.py:286`). Any refactor that bypasses `model_validate` (e.g. emitting tuples and `JSONBytes` directly) **must reproduce the same normalization** or `tests/unit_tests/schema_tests/test_recipe.py:11–60` will fail.

---

## 6. Pagination machinery

| Field | Value |
|-------|-------|
| Path | `mealie/schema/response/pagination.py` |
| Symbols | `PaginationQuery`, `PaginationBase`, `RequestQuery`, `RecipeSearchQuery` |
| Line ranges | `RequestQuery` 32–43; `PaginationQuery` 46–48; `PaginationBase` 51–94; `RecipeSearchQuery` 22–29 |
| Importance | HIGH |
| Reason | Default `per_page=50` (L48), `page=1` (L47). `PaginationBase` exposes `page`, `per_page`, `total`, `total_pages`, `items`, `next`, `previous` (L52–58). `set_pagination_guides` (L78–84) computes the `next`/`previous` HATEOAS URLs from camelized query params — refactor must keep returning the same `RecipePagination` shape with all of `total`/`total_pages` intact (spec §5). |

### Where the actual `total` count is produced

| Field | Value |
|-------|-------|
| Path | `mealie/repos/repository_generic.py` |
| Symbol | `RepositoryGeneric.add_pagination_to_query` |
| Line range | **357–405** |
| Importance | HIGH |
| Reason | `count_query = select(func.count()).select_from(query.order_by(None).distinct().subquery())` at **L376** — already a `SELECT COUNT(*) FROM (SELECT DISTINCT … FROM recipes WHERE …)`. The `DISTINCT` is necessary today because of the joined-load duplication. **After switching M:N loaders to `selectinload`, the outer count query no longer needs `DISTINCT`**, but leaving the existing `add_pagination_to_query` alone is safe — `DISTINCT` over a primary-key result is a no-op. The refactor in `RepositoryRecipes.page_all` should pass `q` (without loader options) into `add_pagination_to_query` so the count cost stays bounded; it already does this at L274. |

### Order-by application

| Field | Value |
|-------|-------|
| Path | `mealie/repos/repository_generic.py` |
| Symbol | `add_order_by_to_query`, `add_order_attr_to_query` |
| Line range | **407–482** |
| Importance | HIGH |
| Reason | `add_order_attr_to_query` (L407–430) is where `column_aliases` is consulted (L414). Critically, **lowercase normalization** happens at L417–418 for string columns. The refactor must not bypass `add_order_by_to_query`, or string ordering will become case-sensitive and break determinism. |

---

## 7. Underlying ORM model

| Field | Value |
|-------|-------|
| Path | `mealie/db/models/recipe/recipe.py` |
| Symbol | `class RecipeModel(SqlAlchemyBase, BaseMixins)` |
| Line range | **42–183** |
| Importance | HIGH |
| Reason | Names the relationships the refactor will touch: `recipe_category` via `recipes_to_categories` (L98–100), `tags` via `recipes_to_tags` (L138), `tools` via `recipes_to_tools` (L101), `user` 1:1 (L59) for `household_id` AssociationProxy (L55–56). The `__table_args__` at L44–46 enforces `UniqueConstraint("slug", "group_id")` — important for the seeding test fixture to avoid collisions. **No partial index exists today on `(group_id, household_id, created_at)`** — relevant if reviewers ask about adding a multi-column index for the list endpoint. |

### household_id is an AssociationProxy, not a column

| Path | Symbol | Line range | Note |
|---|---|---|---|
| `mealie/db/models/recipe/recipe.py` | `household_id: AssociationProxy[GUID] = association_proxy("user", "household_id")` | **55** | The filter `RecipeModel.household_id.is_not(None)` at `repository_recipes.py:238` and `RecipeModel.household_id == self.household_id` at `repository_recipes.py:311` work because of this proxy — they implicitly require the `user` JOIN. Today's `joinedload(RecipeModel.user).load_only(User.household_id)` (`recipe.py:174`) is **load-bearing** for the proxy. A refactor that drops this loader silently triggers a per-row lazy load on `recipe.user.household_id` during Pydantic validation → **regress to true N+1**. Keep `joinedload(user).load_only(...)` (single-row, no Cartesian risk). |

---

## 8. Other consumers of the same code path

The same `RepositoryRecipes.page_all` method (and `RecipeSummary.loader_options`) is reached by **four other routes**. The refactor MUST not regress any of them:

| Route | Path | Symbol | Line range | Notes |
|-------|------|--------|------------|-------|
| `GET /api/explore/groups/{group_slug}/recipes` | `mealie/routes/explore/controller_public_recipes.py` | `PublicRecipesController.get_all` | **30–92** | Public/cross-household. Calls `self.cross_household_recipes.page_all(...)` at L67–80 with an injected `query_filter` for `household.preferences.privateHousehold = FALSE AND settings.public = TRUE` (L61–65). Same `JSONBytes` short-circuit at L92. |
| `GET /api/organizers/categories/slug/{category_slug}` | `mealie/routes/organizers/controller_categories.py` | `controller_categories.get_one_by_slug` | **126–141** | Calls `group_recipes.page_all(PaginationQuery(per_page=-1, query_filter=…))` at L132–134. Returns `RecipeCategoryResponse` wrapping `recipe_data.items` (L136–141). |
| `GET /api/households/mealplans/random` (helper) | `mealie/routes/households/controller_mealplan.py` | `get_random_recipes_for_mealplan` (private) | **48–74** | Calls `cross_household_recipes.page_all(... order_by="random" ...)` at L65–73. **Exercises the `order_by="random"` path** (`add_order_by_to_query:436–449`) which materializes all matching IDs to Python — refactor must not regress this. |
| `GET /api/recipes/suggestions` | `mealie/routes/recipe/recipe_crud_routes.py` | `RecipeController.suggest_recipes` | **397–413** | Calls `recipes.find_suggested_recipes(...)` (NOT `page_all`). Out of scope — but uses the same `RecipeSummary` shape, so any loader-option change still affects what gets eagerly-loaded here. |

### Endpoints that DO NOT share the code path (don't worry about)

| Endpoint | Why not shared |
|----------|----------------|
| `GET /api/users/{id}/favorites` | `mealie/routes/users/ratings.py:49–52` returns `UserRatings(ratings=self.repos.user_ratings.get_by_user(id, favorites_only=True))`. The response is a list of **rating records** (`UserRatingOut`), not paginated `RecipeSummary`. Different repository, different schema, different loader set. The input spec mentions this URL as a "shared consumer" — it isn't. |
| `GET /api/users/{id}/ratings` | Same as above (L44–47). |
| `GET /api/households/self/recipes/{recipe_slug}` | `mealie/routes/households/controller_household_self_service.py:30` returns `HouseholdRecipeSummary`, single-row by slug — uses `get_one`, not `page_all`. |
| `GET /api/recipes/{slug}` | `mealie/routes/recipe/recipe_crud_routes.py:415–424` returns the **full** `Recipe` (not `RecipeSummary`). Uses `Recipe.loader_options` (`recipe.py:299–320`) which is already `selectinload`-based. No regression risk. |
| `GET /api/recipes/shared/{token_id}` | `mealie/routes/recipe/shared_routes.py:22` — single recipe by share token, same as above. |

---

## 9. OpenAPI / response_model bindings (declared contracts)

| Path | Decorator | Line | Effective contract |
|------|-----------|------|--------------------|
| `mealie/routes/recipe/recipe_crud_routes.py` | `@router.get("", response_model=PaginationBase[RecipeSummary])` | **340** | OpenAPI schema for `GET /api/recipes` is generated from `PaginationBase[RecipeSummary]`. **HOWEVER** the route returns `JSONBytes(content=orjson.dumps(...))` (L395) — FastAPI sees the response as `application/json` bytes and skips response validation. The OpenAPI doc and the runtime payload can therefore drift; the source of truth at runtime is `pagination_response.model_dump(by_alias=True)` on L386–392. |
| `mealie/routes/explore/controller_public_recipes.py` | `@router.get("", response_model=PaginationBase[RecipeSummary])` | **30** | Same pattern, same `JSONBytes` short-circuit at L92. |

Implication for the refactor: **do not change `response_model`** (or generated TypeScript clients in `frontend/app/lib/api/types/` regenerated via `task dev:generate` will diff). Don't change `RecipeSummary`'s `Field(alias="orgURL")` either — that alias is special-cased and the camelize generator would otherwise rewrite it to `orgUrl`.

---

## 10. Contract-preserving boundary

**Fields that must appear in the response, in this serialization order**, with these exact wire keys (camelCase produced by `MealieModel`'s `alias_generator=camelize` at `mealie/schema/_mealie/mealie_model.py:53`, plus the one explicit `orgURL` override at `recipe.py:141`):

```
id, userId, householdId, groupId,
name, slug, image, recipeServings, recipeYieldQuantity, recipeYield,
totalTime, prepTime, cookTime, performTime,
description,
recipeCategory[],   # each item: {id, name, slug}    (RecipeTag base, recipe.py:61–69)
tags[],             # each item: {id, name, slug}    (RecipeTag,      recipe.py:61–69)
tools[],            # each item: {id, name, slug, householdsWithTool[]}  (RecipeTool, recipe.py:83–95)
rating, orgURL,
dateAdded, dateUpdated, createdAt, updatedAt, lastMade
```

(Field-declaration order in `RecipeSummary` L116–148 = serialization order in Pydantic v2 = wire order.)

**Pagination envelope** must continue to return exactly these keys, populated as today (`PaginationBase` at `pagination.py:51–58`):

```
page, perPage, total, totalPages, items, next, previous
```

**Invariants the refactor must NOT break**:

1. `total` is correct against the filter set (today computed via `SELECT COUNT(*) FROM (SELECT DISTINCT … subquery)` at `repository_generic.py:376`). After switching M:N loaders to `selectinload`, the outer query no longer JOINs the M:N tables → `DISTINCT` becomes a no-op but stays correct.
2. `total_pages = ceil(count / per_page)` (`repository_generic.py:388`).
3. `per_page=-1` maps to "all" (`repository_generic.py:382–385`).
4. `page=-1` maps to "last page" (`repository_generic.py:392–394`).
5. Random ordering (`order_by=random` + `pagination_seed`) is deterministic per seed — see `add_order_by_to_query:436–449`. Materializes all matching IDs to Python; **must not** be combined with M:N JOINs (which would inflate the ID set).
6. `column_aliases["last_made"]` and `column_aliases["rating"]` keep working when `orderBy=lastMade` / `orderBy=rating` is requested — these are **per-row correlated subqueries**, not JOINs, and must remain so to preserve the multi-household isolation tested at `test_order_by_last_made` (`tests/unit_tests/repository_tests/test_recipe_repository.py:593–647`).
7. Multitenant: `RecipeModel.household_id` is an `AssociationProxy` (`recipe.py:55–56`) — the existing `joinedload(RecipeModel.user).load_only(User.household_id)` must be **kept** (`recipe.py:174`), or the `RecipeSummary.household_id` validator will trigger a per-row lazy load on `recipe.user` → reintroduces N+1.
8. `JSONBytes` short-circuit (`_base.py:20–29`, `recipe_crud_routes.py:395`) must be kept — clients depend on the camelCase serialization that `model_dump(by_alias=True)` produces, NOT on FastAPI's default jsonable_encoder pass.

---

## 11. Cross-perspective questions (for the Test perspective)

1. **Spec field mismatch — `slug_image`**: input lists it as required, but it does not exist in `RecipeSummary`. Does the test plan need to assert its presence (and therefore fail) or skip it? Recommendation: drop from spec.
2. **Spec field mismatch — `comments`/`comments_count`**: input attributes N+1 partly to "recent comment counts", but the list endpoint does not return them and the loader-set never touches `RecipeModel.comments`. The actual N+1 source is the three M:N `joinedload`s + Cartesian product on pagination. Do query-count tests need to assert anything about a comments table query?
3. **`/api/users/{id}/favorites` is NOT a recipe-list consumer** — it returns rating records, not `RecipeSummary`. Should the query-count test still cover it as a "related consumer" or scope strictly to `/api/recipes`?
4. **Should the query-count test also assert the `/api/explore/groups/{slug}/recipes` route?** It shares the exact `page_all` method and same Cartesian-product risk.
5. **`orderBy=random` materializes all IDs** (`add_order_by_to_query:440`). Should the query-count test exclude `orderBy=random` to avoid noise from that materialization, or explicitly include it as a separate scenario?
6. **`orderBy=lastMade` and `orderBy=rating` use correlated scalar subqueries** that the test will see as part of the main SELECT (no extra query). Confirm the test threshold of "≤ 5 queries" still holds when these are requested (it should — they're embedded subqueries, not separate statements).
7. **Cookbook path** (`cookbook=<slug>`) adds a separate `cookbooks` lookup at `recipe_crud_routes.py:362`. Should the count include that extra `SELECT cookbooks WHERE …`? It's O(1) but bumps the baseline by one statement.
8. **Test DB is SQLite by default** (`mealie/db/db_setup.py:38`) — `EXPLAIN ANALYZE` output requested by spec §4 is Postgres-specific. CI uses SQLite; will the human reviewer run the Postgres comparison manually, or does the task spec need to require `task py:postgres` for the perf artifacts?
