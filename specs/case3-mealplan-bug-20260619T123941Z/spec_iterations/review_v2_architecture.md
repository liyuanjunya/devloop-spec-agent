## Verdict
NEEDS_REFINE

v2 fixes the critical unsatisfiability by making the injected-bug branch an explicit precondition, and it adds coverage for the real frontend consolidated payload. However, the original high-severity architecture concern is only partially resolved: the spec still presents the UI meal-plan flow as failing because of `can_merge` / `merge_items`, while the verified frontend sends one consolidated recipe entry that bypasses the duplicate-occurrence merge surface for the normal two-ingredient recipe.

## V1 issue resolution table
| v1 ID | Status | Evidence |
|---|---|---|
| ARCH-C-001 | RESOLVED | v2 explicitly states the checked-out baseline is already correct and moves the work onto an injected-bug branch (`spec_v2.md:18-32`). Verified source matches: `can_merge` rejects different `food_id` at `mealie/services/household_services/shopping_lists.py:52`, returns `bool(item1.food_id) or item1.note == item2.note` at `:71`, and `merge_items` accumulates with `+=` at `:96`. |
| ARCH-C-002 | RESOLVED | SC-1 now measures failure on the bug-injected branch, not canonical baseline (`spec_v2.md:192-195`; JSON agrees at `spec_v2.json:166`). Verified backend canonical baseline would pass the duplicate-entry path because `add_recipe_ingredients_to_list` creates items then calls `bulk_create_items` (`shopping_lists.py:426-433`), which consolidates create items (`:162-177`) using `merge_items` accumulation (`:94-96`). |
| ARCH-H-001 | PARTIALLY_RESOLVED | v2 correctly documents the frontend pipeline and adds a consolidated payload parameter (`spec_v2.md:42-51`, `:103-108`). Verified frontend code: `planner.vue:243-256` emits one item per occurrence with `scale: 1`; `RecipeDialogAddToShoppingList.vue:345-349` accumulates duplicate recipe sections; `:454-458` sends one `recipeIncrementQuantity`; `group-shopping-lists.ts:32-34` posts that payload. But US-1 remains the per-occurrence backend form (`spec_v2.md:69-71`), and the problem statement still says the UI action fails through `can_merge` / `merge_items` (`spec_v2.md:36-51`). For the verified consolidated UI form, a normal recipe with tomato+salt creates one already-scaled item per ingredient (`shopping_lists.py:370-385`) and does not need duplicate-occurrence merge consolidation. |
| ARCH-M-001 | RESOLVED | v2 requires `test_multiple_occurrences_same_unit` to cover both `per_occurrence` and `consolidated` payload forms and assert `recipe_scale == N` (`spec_v2.md:103-108`; JSON `spec_v2.json:70`). Verified scale path exists at `shopping_lists.py:370-385`, and list-level recipe quantity accumulates at `:437-452`. |
| ARCH-M-002 | PARTIALLY_RESOLVED | v2 documents the latent internal-duplicate scaling bug in EC-7 and self-concerns (`spec_v2.md:217`, `:224-227`). Verified source still undercounts internal duplicates with scale because `new_item.quantity` uses `ingredient.quantity * scale` at `shopping_lists.py:373`, but the in-recipe duplicate merge adds raw `ingredient.quantity` at `:395-397`. v2 does not add the requested required non-regression/xfail test documenting this known failure, so the mitigation is documentation-only. |

## NEW issues found in v2

### ARCH-V2-H-001
**Severity**: HIGH

**Issue**: v2 still claims the user-facing meal-plan UI action fails because of the injected `can_merge` / `merge_items` bug, but the verified frontend sends a single consolidated payload per unique recipe. With the normal US-1 recipe (tomato + salt, no internal duplicate same-food rows), that consolidated payload is already scaled before `bulk_create_items`, so Variant A (`merge_items` overwrite) and Variant B (wrong merge key for duplicate items) are not exercised by the actual UI payload.

**Evidence**: `spec_v2.md:36-51` frames the UI flow as the failing behavior while admitting the per-occurrence backend form is the merge-consolidation bug surface. Verified code shows duplicate recipe occurrences are consolidated in the dialog (`RecipeDialogAddToShoppingList.vue:345-349`) and posted once with `recipeIncrementQuantity` (`:454-458`). Backend scaling occurs in `get_shopping_list_items_from_recipe` (`shopping_lists.py:370-385`), and duplicate-entry consolidation only occurs later in `bulk_create_items` (`:162-177`).

**Recommendation**: Reword the problem as an API/backend robustness regression unless the failing reproduction is changed to a payload the real UI can produce. If the case must remain a UI bug, choose an injected bug that affects the consolidated path, or make the primary pre-fix failure use the real frontend payload and prove it fails.

### ARCH-V2-M-001
**Severity**: MEDIUM

**Issue**: `spec_v2.md` has an internal SC-3 contradiction: the Threshold cell says "6 pytest cases pass" while the same cell, its note, the verification command, and `spec_v2.json` all say 8 collected cases.

**Evidence**: `spec_v2.md:196` says `6 pytest cases pass` and then calculates `8 total`; `spec_v2.md:203` and `:250` say 8 collected / 8 passed. JSON is correct at `spec_v2.json:168` and `:256`.

**Recommendation**: Change the markdown SC-3 threshold to "8 collected pytest cases pass" to match JSON and the verification command.

### ARCH-V2-M-002
**Severity**: MEDIUM

**Issue**: The out-of-scope list can be read as forbidding the exact downstream revert/fix that US-3 requires.

**Evidence**: US-3 requires restoring the canonical implementation in `can_merge` / `merge_items` (`spec_v2.md:84-94`), but out-of-scope says "Modifying or reverting the operator's bug-injection patch from a code-agent commit" (`spec_v2.md:241`). Because the case branch is downstream of `inject-bug`, the implementation commit necessarily changes the injected line(s) back to canonical behavior.

**Recommendation**: Reword the out-of-scope bullet to "Do not modify the separate `inject-bug` branch or operator setup commit; the case-3 fix branch must revert the injected line(s) in its own repair commit."

## Summary
- Resolved: 3/5 v1 issues
- New critical: 0 | New high: 1 | New medium: 2
- Overall: improved
