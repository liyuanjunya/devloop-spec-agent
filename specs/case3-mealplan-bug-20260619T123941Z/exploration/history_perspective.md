# History Perspective — Case 3 Meal Plan → Shopping List Quantity Accumulation

Source input: `C:\Users\v-liyuanjun\source\repos\devloop\specs\case3-mealplan-bug-20260619T123941Z\input.md`  
Repo inspected: `C:\Users\v-liyuanjun\Downloads\mealie` (`devloop-baseline`). I unshallowed the local clone before history exploration so `git --no-pager log --follow` covered the full file lineage from `mealie/services/group_services/shopping_lists.py` to `mealie/services/household_services/shopping_lists.py`.

## Commits on shopping_lists.py

Most recent commits touching `mealie/services/household_services/shopping_lists.py` or its followed predecessor:

| Commit | Date | Summary | History signal for this bug |
|---|---:|---|---|
| `b5c089f5` | 2026-03-09 | `feat: Unit standardization / conversion (#7121)` | Changed `can_merge` and `merge_items` so items with compatible but different units can merge via `UnitConverter`; merge key is no longer strictly `(food_id, unit_id)`. |
| `60d92948` | 2025-11-03 | `feat: Add recipe as ingredient (#4800)` | Added recursive recipe-as-ingredient flattening in `get_shopping_list_items_from_recipe`; introduces `scale` propagation for sub-recipes. |
| `6cbc308d` | 2025-08-16 | `fix: Add Recipe From Another Household To Shopping List (#5892)` | Changed recipe lookup to group-scoped (`household_id=None`) so incrementing cross-household recipes from shopping lists works. |
| `245ca5fe` | 2025-07-31 | `feat: Remove "Is Food" and "Disable Amounts" Flags (#5684)` | Removed old food/amount branching; all ingredients are treated as foods and quantity defaults/zero quantities changed. |
| `716c85cc` | 2025-02-27 | `fix: Bulk Add Recipes to Shopping List (#5054)` | Key prior fix for meal planner bulk add: endpoint accepts multiple recipes and consolidates before saving; fixed race-driven non-merging. |
| `eb170cc7` | 2024-08-22 | `feat: Add Households to Mealie (#3970)` | Renamed/moved service from group to household namespace; multi-tenant scoping changed. |
| `432914e3` | 2024-08-12 | `fix: Lint Python code with ruff (#3799)` | Style-only churn in service. |
| `da11204c` | 2024-06-28 | `feat: Auto-label new shopping list items (#3800)` | Added label inference to item creation path. |
| `0bf3aed2` | 2024-02-23 | `updated models/services/tests to include user_id` | Shopping lists gained user ownership; service behavior now depends on list owner context. |
| `b153ddf8` | 2023-10-07 | `feat: more shopping list enhancements (#2587)` | Positioning/order and checked-item cleanup; touched service ordering semantics. |
| `d6e4829e` | 2023-08-21 | `feat: Display Shopping List Item Recipe Refs (#2501)` | Added recipe reference display and `recipe_note`; fixed note merge bug with 3+ notes. |
| `a6c46a74` | 2023-02-21 | `Feature: Shopping List Label Section Improvements (#2090)` | Label settings/schema/service changes; removed unique constraint around label settings. |
| `5562effd` | 2023-02-19 | `feat: select ingredients to add to shopping List (#2136)` | Added recipe ingredient override/filter payloads for add-to-list. |
| `617cc1fd` | 2023-01-28 | `Refactor Shopping List API (#2021)` | Centralized shopping-list item operations, consolidated recipe items before sending, added many merge edge-case tests. |
| `856a009d` | 2023-01-08 | `fix: for several Shopping List bugs (#1912)` | Prevented merging checked and unchecked items; fixed recipe-reference throttling and refresh/reorder issues. |

Top relevant PR descriptions / commit bodies opened:

- `b5c089f5` / PR #7121: introduced unit standardization and automatic merging of compatible units. This directly changes the expected contract for "different unit" cases: exact different unit IDs may still merge if both have compatible standard units.
- `60d92948` / PR #4800: added recipe references as ingredients; shopping-list add now cascades into linked recipes and flattens their ingredients.
- `6cbc308d` / PR #5892: fixed adding/incrementing recipes from another household by widening recipe lookup scope.
- `716c85cc` / PR #5054: fixed meal-planner bulk add race where same-type shopping-list items were not consolidated; kept old endpoint but deprecated it.
- `46cc3898` / PR #1847: introduced recipe scaling support and `recipe_scale` for item recipe references; adding to shopping list respects UI recipe scale.

## Prior bugs / fixes in this area

- `716c85cc` — **closest precedent to this case**. PR #5054 fixed issue #3417, titled "Shopping list items of the same type are not consolidated". The issue explicitly reproduced via meal planner: breakfast/lunch/dinner recipes added to a shopping list produced duplicate eggs/salt rows until manually checking/unchecking caused summing. The fix bulked recipe additions and pre-consolidated items before persistence, reducing race conditions.
- `856a009d` — fixed several shopping-list bugs and specifically added a guard so checked and unchecked items are not merged. Any new consolidation test must keep checked-state behavior intact.
- `617cc1fd` — major API refactor routed operations through central item collection methods, consolidated recipe items before saving, and added edge-case tests for zero quantities, duplicate merges, merged updates creating dupes, and self-removing recipe refs.
- `46cc3898` — recipe scaling refactor changed quantities from raw ingredient quantity to `ingredient.quantity * recipe_increment` and introduced recipe-reference scale merging.
- `6cbc308d` — cross-household add/increment fix. Tests around meal-plan-to-list should avoid assuming household-scoped recipe lookup only, or explicitly cover cross-household lock behavior if relevant.
- `703db293` / PR #7537 — frontend fix for sub-recipe double scaling; issue #7518 showed linked recipe quantities can be under/over-counted when scale is applied in more than one layer. Even though this was frontend dialog code, it is a strong warning for backend scale accumulation.
- `b5c089f5` — unit conversion merge changed `can_merge`: different `unit_id`s can merge when standard units are convertible. This may conflict with a spec expectation of "same food, different unit should not merge" unless the test chooses non-standardized/non-convertible units.

## Schema/contract evolution

- Initial `shopping_list_items` schema included `quantity`, `note`, `unit_id`, `food_id`, `label_id`, `checked`, `position`, plus deprecated `is_food`. Initial `shopping_list_item_recipe_reference` included `recipe_id` and `recipe_quantity`.
- `46cc3898` added nullable `recipe_scale` to `shopping_list_item_recipe_reference`, backfilled existing refs to `1`, and changed add-to-list logic to track both per-recipe ingredient quantity and recipe scale.
- `d6e4829e` added `recipe_note` to item recipe refs and fixed multi-note merging; note strings are part of merge/display contract when `food_id` is absent.
- `245ca5fe` removed the old "is food" / "disable amounts" feature from active behavior; `is_food` remains deprecated on `ShoppingListItem` model.
- `b5c089f5` added unit standardization fields on ingredient units and made shopping-list merging unit-conversion-aware. Contract is now: same food can merge across different units only if both resolve to compatible standard units; merged item may switch `unit_id` to the converter-selected unit.
- `642c826f` changed model annotations to `FilterableColumn` for query-filter allowlisting. This is not a quantity schema change, but it affects repository filtering expectations around `shopping_list_id`, `checked`, `food_id`, `unit_id`, `recipe_scale`, etc.

## Risk hotspots

- `ShoppingListService.can_merge`: currently rejects checked items and different `food_id`, but allows same food with compatible standard units. Tests that expect different units not to merge must use units without compatible `standard_unit`, or explicitly document that standardized units are intentionally merged.
- `ShoppingListService.merge_items`: sums quantity or converts units, then merges notes/extras and combines recipe references by `recipe_id` by adding `recipe_scale`. A bug here can overwrite instead of accumulate or double-count recipe scales.
- `ShoppingListService.bulk_create_items`: first consolidates new create items, then merges with existing unchecked items. The 2025 bulk-add bug was specifically caused by this path not handling multiple meal-plan recipes atomically.
- `ShoppingListService.get_shopping_list_items_from_recipe`: recursively flattens referenced recipes and applies `scale`; internal duplicate ingredients in the same recipe are manually accumulated. The in-function merge currently adds `ingredient.quantity` to an existing item rather than `ingredient.quantity * scale`, so scale-related tests are important.
- `add_recipe_ingredients_to_list`: list-level `recipe_references` are incremented separately from item-level refs. Quantity, item-level `recipe_scale`, and list-level `recipe_quantity` can drift if only one side is fixed.
- Deprecated/legacy endpoints remain for adding a single recipe. Case tests should exercise the endpoint used by meal planner bulk add, not only the older single-recipe route.

## Cross-perspective questions

1. Should the case's "different unit should not merge" assertion be revised for post-#7121 behavior, or should the test create non-standard/non-convertible units to preserve that expectation?
2. Does the meal planner call the bulk endpoint introduced in #5054 in the current frontend, or can some UI path still hit the deprecated single-recipe endpoint?
3. Should regression coverage include recipe scale and sub-recipe scale, given #1847 and #7537 both changed quantity scaling semantics?
4. Should the fix target only `bulk_create_items`/`merge_items`, or also the same-recipe duplicate merge inside `get_shopping_list_items_from_recipe` where scaled duplicates may be undercounted?
5. When two different foods have the same display/name but different `food_id`, should tests assert no merge even if notes/display match? Current `can_merge` says different `food_id` never merge.
6. How should `None` food IDs be handled for parsed/unparsed ingredients after removal of the old food flags? Current fallback merges by note when no food ID exists.
