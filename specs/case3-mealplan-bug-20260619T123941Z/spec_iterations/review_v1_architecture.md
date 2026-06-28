# Architecture Review — v1

## Verdict
REJECT
The spec preserves Mealie's route → service → repository layering and avoids schema/repository changes, but it misattributes the bug to consolidation code that is already correct in the checked-out Mealie source. Because the required reproduction is unlikely to fail on the real baseline, the implementation plan is not actionable as a real bug fix without an explicit injected-bug branch or a corrected root cause.

## Critical issues
### ARCH-C-001 (CRITICAL)
**Location**: spec.md Problem statement, US-2, US-3 / FR-2, FR-3  
**Issue**: The spec incorrectly says the real defect lives in `ShoppingListService.can_merge` or `ShoppingListService.merge_items`. The actual consolidation function already uses the correct food/unit merge predicate and quantity accumulation, so a "1-2 line" fix there would be a no-op or would risk changing correct behavior.  
**Evidence**: `mealie/services/household_services/shopping_lists.py:52` rejects different `food_id`; `:57-68` only merges different units when compatible via `standard_unit`/`UnitConverter`; `:71` falls back to `note` only when no food id exists; `:96` uses `to_item.quantity += from_item.quantity`.  
**Fix**: Re-run/require the pre-fix reproduction against the actual checkout before naming the bug. If this case depends on the injected variants from `input.md`, the spec must state that explicitly and target the injected branch; otherwise remove the `can_merge`/`merge_items` patch requirement and identify the actual failing function from a failing test.

### ARCH-C-002 (CRITICAL)
**Location**: spec.md FR-1 / Success criteria SC-1  
**Issue**: The required reproduction is expected to fail before the fix, but the real backend path appears to already accumulate duplicate recipe additions. Therefore SC-1 is not a valid acceptance gate for the real source tree.  
**Evidence**: `add_recipe_ingredients_to_list` builds all recipe items then calls `bulk_create_items` (`mealie/services/household_services/shopping_lists.py:426-433`); `bulk_create_items` consolidates create items before persistence (`:162-177`); `merge_items` accumulates quantities (`:94-96`) and recipe scales (`:109-126`).  
**Fix**: Either prove a failing baseline with the exact test and cite the failing function, or change the spec to say "apply the injected bug first, then verify the reproduction fails."

## High issues
### ARCH-H-001 (HIGH)
**Location**: spec.md US-1 AC step 6 / US-4 `test_multiple_occurrences_same_unit`  
**Issue**: The spec says posting duplicate bulk entries mirrors frontend meal-plan serialization, but the current frontend consolidates duplicate recipes into one section and sends one `recipeIncrementQuantity` scale. Tests that only post two separate `ShoppingListAddRecipeParamsBulk` entries do not cover the actual "Add Meal Plan to Shopping List" payload shape.  
**Evidence**: `planner.vue:243-255` passes each meal-plan recipe with `scale: 1`; `RecipeDialogAddToShoppingList.vue:345-349` merges duplicate recipe sections by increasing `recipeScale`; `:454-459` sends one item with `recipeIncrementQuantity: section.recipeScale`; `group-shopping-lists.ts:32-33` posts that payload to the backend.  
**Fix**: Change the primary reproduction to post a single `ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id, recipe_increment_quantity=2)` or drive the dialog-equivalent payload. Keep duplicate bulk entries only as an additional backend robustness test.

## Medium issues
### ARCH-M-001 (MEDIUM)
**Location**: spec.md FR-4 / Edge cases EC-3  
**Issue**: Scale-factor handling is documented but not required as a regression test, even though scale is the actual frontend representation for duplicate meal-plan recipes. This leaves a subtle architecture gap around `recipe_increment_quantity`.  
**Evidence**: Backend item quantity is scaled in `get_shopping_list_items_from_recipe` at `mealie/services/household_services/shopping_lists.py:370-381`; frontend sends `recipeIncrementQuantity` at `RecipeDialogAddToShoppingList.vue:454-459`. FR-4 only requires duplicate bulk-entry tests.  
**Fix**: Add a required test for one bulk item with `recipe_increment_quantity=2` asserting quantity `base * 2` and `recipe_references[0].recipe_scale == 2`.

### ARCH-M-002 (MEDIUM)
**Location**: spec.md Self-concerns SCN-1 / Out of scope  
**Issue**: The spec correctly detects an in-recipe duplicate scaling bug but excludes it without tying that exclusion to the actual frontend scale path. If a scheduled recipe has duplicate same-food/same-unit ingredient rows and is added with `recipe_increment_quantity > 1`, the current code undercounts during the in-recipe pre-merge.  
**Evidence**: New items are initially scaled (`mealie/services/household_services/shopping_lists.py:373`), but duplicate in-recipe merge adds raw `ingredient.quantity` (`:393-397`) instead of `ingredient.quantity * scale`.  
**Fix**: At minimum, add a required non-regression test documenting the current known failure as out of scope, or promote this to the actual fix if the baseline reproduction points there.

## Self-concerns verdict
- **SCN-1 — In-recipe duplicate scaling latent bug**: `confirmed_problem`. Evidence: `get_shopping_list_items_from_recipe` scales `new_item.quantity` at `shopping_lists.py:373`, but duplicate in-recipe merge adds unscaled `ingredient.quantity` at `:395-397`.
- **SCN-2 — Float-precision accumulation not rounded**: `valid_concern`. Evidence: shopping-list `quantity` is a SQLAlchemy `Float` at `mealie/db/models/household/shopping_list.py:67`; input recipe quantities are rounded by `RecipeIngredient.validate_quantity` at `mealie/schema/recipe/recipe_ingredient.py:345-357`; merge sums are raw at `shopping_lists.py:96`.
- **SCN-3 — Future unit-conversion merge dimensions**: `valid_concern`. Evidence: current `can_merge` permits different units only when both have `standard_unit` and `UnitConverter.can_convert(...)` succeeds (`shopping_lists.py:57-68`), so tests using `standard_unit=None` are intentionally scoped.

## Summary
- Critical: 2 | High: 1 | Medium: 2 | Low: 0
- Overall: FAIL
