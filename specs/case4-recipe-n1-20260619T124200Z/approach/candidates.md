# Stage 4 — Approach candidates

> Three approaches to eliminate the `GET /api/recipes` N+1 (Case 4), evaluated
> against four axes: **bug coverage**, **blast radius**, **test cost**,
> **future-proofing**. Source-of-truth seams are listed in
> `exploration\consolidated.md` §4.

---

## Approach A — Conservative (extend `RecipeSummary.loader_options()`)

### Shape

Edit `mealie/schema/recipe/recipe.py:168-175` only:

```python
@classmethod
def loader_options(cls) -> list[LoaderOption]:
    return [
        selectinload(RecipeModel.recipe_category),
        selectinload(RecipeModel.tags),
        selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool),
        joinedload(RecipeModel.user).load_only(User.household_id),
    ]
```

Add `Tool` to the imports (already imported in `mealie/db/models/recipe/__init__.py`; the schema file already imports `RecipeModel` and `User`). Add the new regression test
`tests/integration_tests/test_recipe_list_query_count.py` (sync `def`, per
`consolidated.md` K-5). Touches **2 files**: 1 source + 1 test.

### Bug coverage
- ✅ Eliminates per-tool `Tool.households_with_tool` lazy load (the dominant N+1, `consolidated.md` C-4).
- ✅ Eliminates joinedload-on-M2M cartesian inflation for all three M2M collections (`consolidated.md` C-5).
- ✅ Preserves `joinedload(user).load_only(household_id)` → AssociationProxy still resolves in one statement (`consolidated.md` C-6).
- ✅ Transitively fixes `GET /api/explore/groups/{slug}/recipes` (same loader), `GET /organizers/categories/slug/{slug}` (same loader, `per_page=-1`), and the `cross_household_recipes` meal-plan-random path (`consolidated.md` C-9).

### Blast radius
- One source edit. No new module, no new SQL helper, no migration. Existing `RepositoryRecipes.page_all` body is unchanged. The "apply options late" invariant at `repository_recipes.py:277` is automatically preserved because we're only changing the function whose return value is splatted there.
- Adjacent loader sites (`ReadPlanEntry.loader_options`, `ShoppingListRecipeRefOut.loader_options`) remain on the joinedload anti-pattern — strictly out of spec scope, captured as `self_concerns` SC-002.

### Test cost
- New file: ~80-line sync test (per the scaffolding in `test_perspective.md` §7). Reuses `api_client`, `unique_user_fn_scoped`, `engine`, `api_routes.recipes` — no new fixtures.
- Zero modifications required to the existing test suite. Validated by reading the strict regression list in `test_perspective.md` §8: all of `test_get_recipes_organizer_filter`, `test_get_random_order`, `test_get_cookbook_recipes`, `test_get_all_recipes_includes_all_households`, `test_get_all_recipes_with_household_filter`, `test_cookbook_recipes_includes_all_households`, `test_order_by_last_made`, `test_order_by_rating`, `test_recipe_number_sanitation`, `test_recipe_string_sanitation` assert on JSON shape or repository-level row contents — none depend on loader strategy.

### Future-proofing
- Follows Mealie's idiomatic `selectinload` pattern that is already used in `Recipe.loader_options` (`recipe.py:299-320`), `RecipeToolOut.loader_options` (`recipe_tool.py:36-39`), and `IngredientFood.loader_options` (`recipe_ingredient.py:117-123`) — there is **no new convention to learn or maintain**.
- If a future field on `RecipeSummary` introduces another lazy relationship (e.g., adding `comments_count`), the new loader can be added in the same list with no architectural change.
- Aligns with the SA 2.0 `selectinload` defaults adopted in commit `9e77a9f3` and the eager-loading playbook adopted in commits `4b426ddf` / `ba363da2` (`history_perspective.md` §1).

### Risks specific to this approach
- The relative bound is strong (`count_large == count_small`), but the absolute bound depends on SQLAlchemy's IN-list chunking (default 500). For `perPage=-1` libraries > 500 recipes, each selectinload could split into 2 chunks → up to 9 statements. Spec ceiling **`<= 8` typical / `<= 10` absolute** absorbs this.

---

## Approach B — Aggressive (rewrite `RepositoryRecipes.page_all` with custom SELECT + aggregated subqueries)

### Shape

Rewrite `mealie/repos/repository_recipes.py:220-293`:
1. Replace `sa.select(self.model)` with an explicit `sa.select(RecipeModel.id, RecipeModel.slug, RecipeModel.name, … , RecipeModel.last_made, ...)` column list — load only the columns `RecipeSummary` consumes.
2. Build aggregated subqueries (`json_agg` / `string_agg` / `group_concat` depending on backend) for `tags`, `recipe_category`, `tools`, and `tools[].households_with_tool`. Materialize as JSON arrays on the parent SELECT.
3. Skip `RecipeSummary.loader_options()` entirely; bypass `RecipeSummary.model_validate` and stream rows into a `dict` that matches the wire shape, then `orjson.dumps` directly.
4. Keep `add_pagination_to_query` for COUNT + LIMIT/OFFSET.

### Bug coverage
- ✅ Eliminates **every** extra query — true 2-statement minimum (COUNT + parent SELECT with all aggregates inline).
- ❌ Forces the implementer to re-derive Pydantic field-validator behavior (`clean_numbers`, `clean_strings` at `schema/recipe/recipe.py:151-162`) in SQL or on the dict — easy to drift silently and break `tests/unit_tests/schema_tests/test_recipe.py:11-63`.
- ❌ Forces the implementer to re-derive the user-scoped `rating` / `last_made` aliases in the new SELECT and confirm they still null-floor correctly (history `216ae857`, `2a541f08`).

### Blast radius
- **Large.** Touches `RepositoryRecipes.page_all` body, all 5 callers' assumptions, and the response serialization path (no longer goes through `RecipeSummary.model_validate`).
- Backend portability: SQLite vs Postgres aggregate functions differ (`group_concat` vs `string_agg` / `json_agg`). Either branch on `self.session.bind.dialect.name` or use a SQLAlchemy compiler extension. Either way, doubles the surface of the maintenance burden.
- Sibling adjacent loaders (`ReadPlanEntry`, `ShoppingListRecipeRefOut`) **still need a separate fix** — this approach doesn't transitively help them.

### Test cost
- **High.** The "no model_validate in the hot path" decision means a JSON snapshot test against the pre-refactor wire bytes must be added (otherwise validator drift is undetectable). The strict-regression list grows by every test that asserts on field shape, type coercion, or default values — `test_recipe_number_sanitation` and `test_recipe_string_sanitation` become coupled to the new dict-construction path.
- The query-count test still applies but loses interpretability — what counts as "a query" when aggregates are inlined is harder to reason about per perspective.

### Future-proofing
- ❌ **Negative.** Diverges from Mealie's `loader_options()` convention; future contributors adding a field must update both the schema and the bespoke SELECT. The cookbook commit `7d4a379f` already established index conventions that the rest of the app reads through SQLAlchemy ORM — bypassing ORM here strands the new code from future ORM refactors (e.g., commit `987c7209` `QueryFilterBuilder` migration).
- Couples to dialect-specific aggregate syntax → fragile under PostgreSQL upgrades and re-tests against SQLite.

### Risks specific to this approach
- The `column_aliases` (`_get_last_made_col_alias`, `_get_rating_col_alias`) are correlated subqueries on `self.model.id`. If the rewrite changes the parent SELECT from `sa.select(self.model)` to a column-list select, the `.correlate(self.model)` in those subqueries must stay valid — easy to break.
- `pagination_response.set_pagination_guides` (`recipe_crud_routes.py:387-390`) currently consumes a `RecipePagination` object with `items: list[RecipeSummary]`. Streaming dicts requires either constructing a `RecipePagination` shim or duplicating the pagination wrapper.
- **Violates the spec's "禁止引入应用层缓存" intent in spirit**: rolling our own dict serialization bypasses Mealie's standard data path and is morally equivalent to a denormalization tier.

---

## Approach C — Hybrid (selectinload for relations + a single batched subquery for any counted fields)

### Shape

Apply Approach A's `RecipeSummary.loader_options()` edit. **Additionally**, if any new aggregate (e.g., `comments_count`) needed to ship inside `RecipeSummary`, attach it as a correlated scalar subquery via `column_aliases` (mirroring the existing `_get_rating_col_alias` / `_get_last_made_col_alias` pattern in `repository_recipes.py:54-93`) and select it as a labeled column on the parent SELECT — exactly the pattern `2a541f08` and `e9892aba` established.

### Bug coverage
- ✅ Same as Approach A for the **actual** N+1 (tags/categories/tools/households_with_tool).
- ⚠️ The "batched subquery for counted fields" half is **not exercised by this spec** because:
  - `consolidated.md` K-3 confirms `comments_count` is not in the current `RecipeSummary` and adding it would violate "fields 100% unchanged" (`input.md:19, 24`).
  - `consolidated.md` K-7 confirms `rating` is already a correlated subquery (`_get_rating_col_alias`) and needs no further batching.
  - No other counted/aggregated field appears in the spec's preserved field list (`input.md:23-26`).
- ✅ Future-ready: if a counted field IS introduced later, the `column_aliases` pattern is documented and ready.

### Blast radius
- Same as Approach A (one source file). The "batched subquery" half is **dormant** — it only activates if a counted field is added in a later iteration.

### Test cost
- Same as Approach A.

### Future-proofing
- ✅ **Best** of the three. Explicitly documents the correlated-subquery pattern in the spec, even though it is not exercised by Case 4 itself, so a future agent that adds (e.g.) `comments_count` knows the precedent rather than reaching for joinedload or selectinload on `RecipeModel.comments`.

### Risks specific to this approach
- The "Hybrid" framing implies that we *do* batch a counted field today. We don't — there is no such field in scope (`consolidated.md` K-3). Selecting this approach risks the implementer over-engineering by adding an unused subquery scaffold.

---

## Evaluation matrix

| Axis | Approach A (Conservative) | Approach B (Aggressive) | Approach C (Hybrid) |
|------|---------------------------|-------------------------|---------------------|
| **Bug coverage** | ✅ Full (N+1 root cause = `Tool.households_with_tool` lazy + M2M cartesian) | ✅ Full + over-coverage of phantom counted fields | ✅ Full for in-scope; future-ready for unscoped counted fields |
| **Blast radius** | 🟢 Minimal — 1 source file, 1 test file | 🔴 Large — `page_all` body, response path, dialect branching | 🟢 Minimal (same as A); dormant batched-subquery scaffold |
| **Test cost** | 🟢 1 new test file, zero existing-test diffs | 🔴 New JSON snapshot test required; validators must be re-derived | 🟢 Same as A |
| **Future-proofing** | 🟢 Aligns with `Recipe.loader_options` / `RecipeToolOut.loader_options` / `IngredientFood.loader_options` precedent | 🔴 Diverges from idiomatic ORM path; couples to dialect aggregates | 🟢 Same as A, plus a documented note for the next counted-field refactor |
| **Spec-fit** ("响应字段 100% 不变") | ✅ No new fields, no shape changes | ⚠️ Implementer must hand-build identical wire bytes — drift risk | ✅ Same as A |
| **Spec-fit** ("禁止引入应用层缓存") | ✅ SQL-layer fix via SA loader strategy | ⚠️ Dict-streaming bypass is morally adjacent to a denormalization tier | ✅ Same as A |

**Selected: Approach A (Conservative).** Reasoning recorded in `approach\selected.md`.

> Approach C is functionally equivalent to A for the *in-scope* work but invites
> over-engineering by suggesting a counted-field subquery that the spec does not
> need. Since the spec explicitly forbids new fields and `rating` is already a
> correlated subquery, the "batched subquery" half of Hybrid is dead code. We
> prefer the leaner Conservative shape and capture the future-readiness note in
> `self_concerns` instead.
