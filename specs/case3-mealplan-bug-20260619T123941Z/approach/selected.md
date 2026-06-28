# Selected Approach — Case 3 (Meal Plan → Shopping List Consolidation Bug)

## Decision

**Candidate 1 — Conservative: smallest patch inside the broken consolidation function(s).**

## Scope of the fix

Only `mealie/services/household_services/shopping_lists.py`, and only within these two functions:
- `ShoppingListService.can_merge` (lines 45-71): ensure `food_id` equality is the primary merge predicate when `food_id` is present, and `note` is only the fallback when both items have `food_id is None`. Do NOT change the `unit_id` / `standard_unit` branches introduced by PR #7121.
- `ShoppingListService.merge_items` (lines 73-128): ensure the non-unit-converted quantity branch executes `to_item.quantity += from_item.quantity` (line 96). Do NOT change the `merge_quantity_and_unit(...)` branch (lines 86-92), the note concatenation (lines 98-104), the extras update (lines 106-107), or the recipe-reference merge (lines 109-126).

Expected diff size: 1-2 lines per buggy variant (input.md附录 lists two canonical variants). No new files, no new methods, no schema/migration changes, no changes to controllers, repositories, or other services.

## Why this candidate

1. **Strict alignment with input intent.** input.md mandates "只修改导致 bug 的最小代码范围（理想 1-3 个函数, 几十行）" and "不要重构周边代码". Candidate 1 is the only option that fully respects both.
2. **Lowest blast radius.** The two lines under repair are the canonical consolidation invariants. The rest of the service (`bulk_create_items`, `bulk_update_items`, `get_shopping_list_items_from_recipe`, `add_recipe_ingredients_to_list`) already routes through them and will inherit the fix automatically.
3. **Preserves existing green tests.** `test_shopping_lists_add_recipes_with_merge` (`tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739`), `test_shopping_lists_add_recipe_with_merge` (lines 581-660), and `test_shopping_lists_add_nested_recipe_ingredients` (lines 249-361) all exercise the same path and must remain green; restoring the canonical `(food_id, unit_id)` key + `+=` accumulation makes them green by construction.
4. **Avoids re-litigating PR #7121 / #4800 / #5054.** None of the standardized-unit, sub-recipe-flattening, or bulk-add-race behavior is in scope, so we cannot accidentally regress them.
5. **Future-proofed by tests, not by structure.** Candidate 1's modest future-proofing gap is closed by the 4 mandatory regression tests in US-4, which encode the invariants ("same food + same unit accumulates", "different unit does not merge", "different `food_id` does not merge", "single occurrence is unchanged"). These tests are the durable contract — exactly the design the input requires.

## Why NOT the other candidates

- **Candidate 2 (Defensive)**: extracting `_consolidate_create_items` is a small but real refactor of `bulk_create_items` lines 162-176. input.md prohibits this ("不要重构周边代码"). Marginal benefit (one extra unit test) does not justify the breach of intent.
- **Candidate 3 (Comprehensive)**: directly contradicts three explicit input constraints — minimal scope, no broad refactor, and "必须遵循 mealie 既有的 RepositoryShoppingItem / ShoppingListItem schema, 不要新建并行实现". Also conflicts with grounding §8 ("shopping list 与 meal plan 联动逻辑较复杂") — refactoring a known-complex file is exactly the risk to avoid in a focused bug fix.

## Acceptance signal

After applying the fix:
- `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` **PASS** (failed pre-fix).
- All four regression tests (`test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`) **PASS**.
- Full pre-existing suite `uv run pytest tests/integration_tests/user_household_tests/test_group_shopping_lists.py tests/integration_tests/user_household_tests/test_group_shopping_list_items.py tests/integration_tests/user_household_tests/test_group_mealplan.py` **PASS** with no new failures.
- `task py:check` (ruff format + ruff lint + mypy + pytest) clean.

## PR description requirement (US-2)

The PR description must contain a root-cause analysis section that answers, in this order:
1. **Which function holds the bug?** Name the file + function (e.g. `mealie/services/household_services/shopping_lists.py::ShoppingListService.merge_items` or `…::can_merge`).
2. **Is it a wrong merge key, or a quantity overwrite vs. accumulate?** State which of the two canonical variants applies, with the exact line that was changed.
3. **Which boundary cases interact with the fix?** Cover: different `unit_id` (must not merge unless `standard_unit` is convertible), different `food_id` with same `display` (must not merge), `food_id is None` fallback (merges only when `note` matches), and `recipe_scale` accumulation through `merge_items` lines 109-126.
