# Architecture Review — v1

## Verdict
NEEDS_REFINE

The selected seam is architecturally right: `RepositoryRecipes.page_all` already applies `RecipeSummary.loader_options()` after pagination, so changing the summary loaders preserves the repository/controller flow and also covers `/api/explore/groups/.../recipes`. However, the spec over-claims exact wire identity and under-counts selectinload chunking. Because those gaps affect two explicit P1/P2 acceptance criteria, do not approve until resolved.

## Critical issues

(none)

## High issues

### ARCH-H-001 (HIGH)
**Location**: US-1, FR-001, SC-002; selected approach `RecipeSummary.loader_options()` swap

**Issue**: The spec requires byte-identical response contents and order, but the proposed loader swap can change the order of M2M arrays unless this is explicitly tested or stabilized. `RecipeModel.recipe_category`, `RecipeModel.tags`, and `RecipeModel.tools` have no `order_by`; switching from joined eager loading to select-in eager loading changes the SQL shape used to populate those collections. Pydantic field declaration order stays stable, but nested array item order is not guaranteed by the model definitions.

**Evidence**: `RecipeSummary` serializes `recipe_category`, `tags`, and `tools` directly (`mealie/schema/recipe/recipe.py:137-139`) and the route dumps `pagination_response.model_dump(by_alias=True)` directly (`mealie/routes/recipe/recipe_crud_routes.py:392`). The relationships have no `order_by`: `recipe_category` (`mealie/db/models/recipe/recipe.py:98-100`), `tools` (`:101`), and `tags` (`:138`). Existing tests named in SC-002 assert some fields/counts but are not a before/after complete JSON order diff.

**Fix**: Add a required response-equivalence test that seeds multiple categories/tags/tools per recipe and verifies complete `items[*]` field order plus nested array contents/order against the current baseline contract. If exact nested order is truly required, specify a deterministic ordering strategy and verify it does not change the current baseline.

### ARCH-H-002 (HIGH)
**Location**: US-2 acceptance, FR-009, EC-006, SC-C

**Issue**: The query-count budget under-counts SQLAlchemy selectinload chunking for the chained `Tool.households_with_tool` load. The chained selectinload chunks by number of loaded `Tool` rows, not by recipe count. With the spec's own seeding pattern (3 unique tools per recipe), `perPage=1000` can produce about 3000 tool ids, so the households load alone may split into ~6 statements. The stated `<= 10` absolute bound for `perPage <= 1000` is therefore not reliable.

**Evidence**: FR-010 says each recipe is decorated with 3 tools. FR-009 expects 6 statements and allows `<= 10`; EC-006 says three parent M2M selectinloads may split but treats the chained households load as one statement. The target loader is `selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)` and `Tool.households_with_tool` is a separate M2M relationship (`mealie/db/models/recipe/tool.py:54-56`).

**Fix**: Replace the absolute ceiling with a formula or scoped bound: `2 + chunks(recipe_ids for categories) + chunks(recipe_ids for tags) + chunks(recipe_ids for tools) + chunks(tool_ids for households_with_tool)`, plus known auth/random-order overhead if counted. Keep the regression test below the 500-id chunk threshold or assert a relative bound only for larger pages.

## Medium issues

### ARCH-M-001 (MEDIUM)
**Location**: NC-001 / FR-013

**Issue**: The spec says `rating` in the response is user-correlated when `by_user(user_id)` is set. In the current repository, `column_aliases` is consumed for query filtering and ordering, not projection. This does not require changing the refactor, but the wording could mislead implementers into writing incorrect response assertions.

**Evidence**: `RepositoryRecipes.column_aliases` defines aliases (`mealie/repos/repository_recipes.py:39-47`), and generic pagination uses them in `QueryFilterBuilder.filter_query` and `add_order_attr_to_query` (`mealie/repos/repository_generic.py:370,414`). The page query still selects `self.model` and validates ORM objects (`repository_recipes.py:238,286`), so `RecipeSummary.rating` comes from the loaded model attribute.

**Fix**: Reword FR-013/NC-001: rating sorting/filtering uses correlated scalar expressions; the response field remains the existing `RecipeModel.rating` value unless existing code elsewhere mutates it. The refactor should not add comments/rating-count aggregates.

## Low issues

(none)

## Related-route assessment

- `/api/explore/groups/{group_slug}/recipes`: safe and covered because it calls `cross_household_recipes.page_all(...)` and therefore uses `RecipeSummary.loader_options()` (`mealie/routes/explore/controller_public_recipes.py:67-80`).
- `/api/users/self/favorites`: unaffected because it returns `UserRatings[UserRatingSummary]` via `repos.user_ratings`, not recipe pagination (`mealie/routes/users/crud.py:38-40`).

## Self-concerns verdict

- SC-A: valid; PR should explain the concrete `Tool.households_with_tool` lazy-load root cause.
- SC-B: valid follow-up, not blocking for this input scope.
- SC-C: confirmed problem as written; see ARCH-H-002.
- SC-D: valid; no schema field-set change means no frontend type regeneration should be required.

## Summary

- Critical: 0 | High: 2 | Medium: 1 | Low: 0
- Overall: FAIL until the two high issues are addressed.
