# Stage 4 — Selected approach

## Selection: **Approach A — Conservative**

Extend `RecipeSummary.loader_options()` at `mealie/schema/recipe/recipe.py:168-175`:

- Convert `joinedload(RecipeModel.recipe_category)` → `selectinload(RecipeModel.recipe_category)`.
- Convert `joinedload(RecipeModel.tags)` → `selectinload(RecipeModel.tags)`.
- Convert `joinedload(RecipeModel.tools)` → `selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)` (chained).
- **Keep** `joinedload(RecipeModel.user).load_only(User.household_id)` (load-bearing for the AssociationProxy at `mealie/db/models/recipe/recipe.py:55-56`).
- Add `Tool` to the imports in `mealie/schema/recipe/recipe.py` (already in `mealie/db/models/recipe/__init__.py`'s public surface).

`RepositoryRecipes.page_all` (`mealie/repos/repository_recipes.py:220-293`) is **not modified** — it already splats `RecipeSummary.loader_options()` at line 277, and the "apply options late" invariant (commit `ba363da2`, history `#1`) is intact.

Add `tests/integration_tests/test_recipe_list_query_count.py` per the test-perspective scaffolding (sync `def`, `event.listens_for(Engine, "before_cursor_execute")`, `unique_user_fn_scoped`, `api_routes.recipes`).

---

## Why Conservative wins over Hybrid and Aggressive

1. **Bug coverage is identical to Hybrid and complete.** All five perspectives agree the dominant N+1 is `Tool.households_with_tool` lazy-load per unique tool, plus secondary joinedload-on-M2M cartesian inflation. Conservative addresses both at the single architectural seam.

2. **The "batched subquery for counted fields" half of Hybrid is dead code in Case 4.** `consolidated.md` K-3 and K-7 confirm there are no counted fields to batch — `rating` is already a correlated subquery (`_get_rating_col_alias` at `repository_recipes.py:72-93`), `comments_count` does not exist in `RecipeSummary` and would violate "响应字段 100% 不变" if added. Choosing Hybrid risks the implementer scaffolding a subquery that does nothing.

3. **Aggressive violates the spec's invariants in spirit.** Bypassing `RecipeSummary.model_validate` and streaming dicts couples the wire shape to a bespoke SQL → dict translator, breaking the existing field-validator pipeline (`clean_numbers`, `clean_strings` at `recipe.py:151-162`). The required JSON snapshot test would also significantly expand the regression surface for marginal wins.

4. **Conservative matches the existing codebase idiom.** `Recipe.loader_options` (`recipe.py:299-320`), `RecipeToolOut.loader_options` (`recipe_tool.py:36-39`), and `IngredientFood.loader_options` (`recipe_ingredient.py:117-123`) all use the same `selectinload + chained selectinload(Tool|IngredientFoodModel.households_with_*)` pattern. The fix is the rest of the app catching up to the convention.

5. **Smallest blast radius.** One source file changed. Zero new dependencies. Zero existing tests modified. Zero migrations. PR diff size is bounded and easy to review.

---

## Evaluation against the four axes

| Axis | Verdict | Evidence |
|------|---------|----------|
| **Bug coverage** | ✅ Full | C-4, C-5, C-6, C-7 in `consolidated.md` |
| **Blast radius** | 🟢 Minimal | 1 source file (`mealie/schema/recipe/recipe.py`) + 1 new test file |
| **Test cost** | 🟢 Low | 1 new sync `def` test; zero diffs to existing suite (`test_perspective.md` §8) |
| **Future-proofing** | 🟢 Aligned with codebase convention | Matches `Recipe.loader_options`, `RecipeToolOut.loader_options`, `IngredientFood.loader_options` patterns |

---

## What this approach explicitly does NOT do

- Does **not** modify `RepositoryRecipes.page_all` body — the seam is the schema's `loader_options`, not the repo method.
- Does **not** touch `_get_rating_col_alias`, `_get_last_made_col_alias`, or the `column_aliases` property — they are already correlated subqueries (C-12).
- Does **not** remove `.scalars().unique().all()` at `repository_recipes.py:280` — becomes a no-op after the refactor but cheap protection against future regressions.
- Does **not** add any new field to `RecipeSummary` — preserves "响应字段 100% 不变" (`input.md:19`).
- Does **not** add an alembic migration — all three M2M secondary tables (`recipes_to_categories`, `recipes_to_tags`, `recipes_to_tools`, `households_to_tools`) already index both columns; `selectinload`'s `WHERE … IN (...)` lookup uses the existing `recipe_id`/`tool_id` indexes (data §"secondary tables — indexing baseline").
- Does **not** patch the two adjacent loader sites (`ReadPlanEntry.loader_options` at `meal_plan/new_meal.py:67-74`, `ShoppingListRecipeRefOut.loader_options` at `group_shopping_list.py:202-208`) — strictly out of `input.md` §1 scope. Captured as `self_concerns` SC-002 in the spec for a PR-description follow-up note.
- Does **not** add an in-memory or Redis cache (`input.md:79`).
- Does **not** use `lazy='dynamic'` or any "hide-the-query" trick (`input.md:82`).
