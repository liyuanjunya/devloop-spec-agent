# Consolidated Exploration — Case 3 (Meal Plan → Shopping List Consolidation Bug)

> Synthesis of 4 perspectives: data, api, test, history. UI perspective intentionally omitted (backend-only bug).
> All line ranges verified against `C:\Users\v-liyuanjun\Downloads\mealie\` (baseline commit referenced in grounding).

---

## 1. Critical Artifacts (deduped across perspectives)

### A. `ShoppingListService.can_merge` — merge-key predicate
- **Path / lines**: `mealie/services/household_services/shopping_lists.py:45-71`
- **Importance**: critical
- **What it does**: Decides if two `ShoppingListItemBase` rows can be merged. Rejects when either is `checked` or when `food_id` differs. If `unit_id` differs, both units must have a `standard_unit` and `UnitConverter().can_convert(...)` must return true. Final return: `bool(item1.food_id) or item1.note == item2.note` — i.e. when food_id is present, merge regardless of note; when absent, merge only when notes match.
- **Verified merge-key fields**: `checked`, `food_id`, `unit_id` (with standard-unit fallback), `note` (only if `food_id` is `None`). `recipe_id`, `display`, and `label_id` are NOT part of the merge key.

### B. `ShoppingListService.merge_items` — quantity accumulator
- **Path / lines**: `mealie/services/household_services/shopping_lists.py:73-128`
- **Importance**: critical
- **What it does**: Merges `from_item` into `to_item`. If both units have `standard_unit`, calls `merge_quantity_and_unit(...)` and reassigns `to_item.quantity / unit_id / unit`. Otherwise executes `to_item.quantity += from_item.quantity` (line 96). Notes are concatenated with " | ". Recipe references are merged by `recipe_id`, with `recipe_scale` summed (lines 109-126).
- **Failure modes**: This is the single accumulation point for non-unit-converted merges. Replacing `+=` with `=` (input.md附录 patch variant 1) drops accumulation. The function returns a `ShoppingListItemUpdate` via `to_item.cast(...)`.

### C. `ShoppingListService.bulk_create_items` — consolidation orchestrator
- **Path / lines**: `mealie/services/household_services/shopping_lists.py:154-223`
- **Importance**: critical
- **What it does**: Two-pass merge. Pass 1 (lines 162-176): consolidate the new `create_items` list against itself in-memory. Pass 2 (lines 180-213): for each surviving create-item, fetch unchecked existing rows for the same `shopping_list_id` (`PaginationQuery` with `checked=false`, lines 185-189) and merge into the first compatible row via `can_merge` + `merge_items`. Items that didn't merge are appended to `filtered_create_items`. Final persistence: `create_many` + `update_many` (lines 215-216).
- **Bug surface**: This is the primary location for duplicate-recipe meal plan rows. The `can_merge` key (input.md附录 patch variant 2) and the `+=` accumulation (variant 1) both flow through here.

### D. `ShoppingListService.get_shopping_list_items_from_recipe` — recipe → ShoppingListItemCreate
- **Path / lines**: `mealie/services/household_services/shopping_lists.py:323-411`
- **Importance**: critical
- **What it does**: Converts each `RecipeIngredient` into a `ShoppingListItemCreate`. Sub-recipe ingredients are recursively flattened with `sub_scale = (ingredient.quantity or 1) * scale` (lines 344-355). For non-sub-recipe ingredients, builds `ShoppingListItemCreate(quantity=ingredient.quantity * scale if ingredient.quantity else 0, food_id=…, unit_id=…, recipe_references=[…])` (lines 370-385). Within a single recipe, duplicate ingredients are pre-merged in-place via `can_merge`, adding raw `ingredient.quantity` (not `ingredient.quantity * scale`) at lines 395-397.
- **Secondary bug risk**: At lines 395-397 the same-recipe duplicate merge adds `ingredient.quantity` rather than `ingredient.quantity * scale`. This undercounts scaled recipes with internal duplicates (history #1847 / #7537).

### E. `ShoppingListService.add_recipe_ingredients_to_list` — service entry point
- **Path / lines**: `mealie/services/household_services/shopping_lists.py:413-455`
- **Importance**: critical
- **What it does**: Iterates `recipe_items: list[ShoppingListAddRecipeParamsBulk]`, calls `get_shopping_list_items_from_recipe(list_id, r.recipe_id, r.recipe_increment_quantity, r.recipe_ingredients)` for each, flattens into `items_to_create`, then calls `bulk_create_items(items_to_create)`. Lastly updates list-level `ShoppingList.recipe_references` quantities (lines 437-452). Returns `(ShoppingListOut, ShoppingListItemsCollectionOut)`.
- **Critical detail**: Same recipe appearing twice in the meal plan produces two distinct `ShoppingListAddRecipeParamsBulk` entries, which generate TWO sets of `ShoppingListItemCreate` rows, which must consolidate inside `bulk_create_items`.

### F. `ShoppingListController.add_recipe_ingredients_to_list` — HTTP route
- **Path / lines**: `mealie/routes/households/controller_shopping_lists.py:256-261`
- **Importance**: critical
- **What it does**: `POST /households/shopping/lists/{item_id}/recipe`, accepts `list[ShoppingListAddRecipeParamsBulk]`, calls the service, publishes events, returns `ShoppingListOut`. There is no dedicated meal-plan-to-shopping endpoint; the frontend gathers meal-plan recipes and calls this route directly.

### G. Deprecated single-recipe route
- **Path / lines**: `mealie/routes/households/controller_shopping_lists.py:263-272`
- **Importance**: relevant
- **What it does**: `POST /households/shopping/lists/{item_id}/recipe/{recipe_id}`, casts to bulk format, delegates to F. Decorated `deprecated=True`.

### H. `ShoppingListItem` SQLAlchemy model
- **Path / lines**: `mealie/db/models/household/shopping_list.py:51-98`
- **Importance**: critical
- **Persisted columns**: `quantity: Float | None` (line 67), `unit_id: GUID | None` (line 75), `food_id: GUID | None` (line 78), `label_id` (line 81), `checked` (line 65), `note: String | None` (line 68), `recipe_references` relationship (lines 87-89). `is_food` is deprecated (line 93). No `Decimal`; all quantity math is float.

### I. `ShoppingListItemRecipeReference` SQLAlchemy model
- **Path / lines**: `mealie/db/models/household/shopping_list.py:26-48`
- **Importance**: critical
- **Persisted columns**: `recipe_id`, `recipe_quantity: Float NOT NULL` (line 39), `recipe_scale: Float default=1` (line 40), `recipe_note` (line 41). One row per (item, recipe) link.

### J. `ShoppingListItemBase` / `…Create` / `…Update` / `…Out` schemas
- **Path / lines**: `mealie/schema/household/group_shopping_list.py:58-120`
- **Importance**: critical
- **Key types**: `quantity: float = 1` (line 63), `food_id / unit_id / label_id: UUID4 | None = None` (lines 65-67), `recipe_references: list[ShoppingListItemRecipeRefCreate] = []` (line 82). `ShoppingListItemRecipeRefCreate.recipe_scale: NoneFloat = 1` (line 37), `recipe_quantity: float = 0` (line 34, with `default_none_to_zero` validator lines 43-46).

### K. `ShoppingListAddRecipeParams` / `…ParamsBulk` request schemas
- **Path / lines**: `mealie/schema/household/group_shopping_list.py:288-295`
- **Importance**: critical
- **Fields**: `recipe_increment_quantity: float = 1`, `recipe_ingredients: list[RecipeIngredient] | None = None`, `recipe_id: UUID4` (bulk only).
- **Consequence**: Two meal-plan occurrences can be encoded as either two bulk entries with `recipe_increment_quantity=1` each, OR one entry with `recipe_increment_quantity=2`. Both forms must produce the same consolidated result.

### L. `RecipeIngredientBase` / `RecipeIngredient` Pydantic schemas
- **Path / lines**: `mealie/schema/recipe/recipe_ingredient.py:191-198` (base), `345-357` (validate_quantity), `23` (`INGREDIENT_QTY_PRECISION = 3`)
- **Importance**: relevant
- **Type behavior**: `quantity: NoneFloat = 0`; incoming float values are rounded to 3 decimals via `validate_quantity` (lines 353-354). Shopping-list merges do NOT round after summing — raw float sums are persisted.

### M. `SaveIngredientFood` / `SaveIngredientUnit` (test fixture inputs)
- **Path / lines**: `mealie/schema/recipe/recipe_ingredient.py:98-99` (`SaveIngredientFood`), `170-171` (`SaveIngredientUnit`), `155-156` (`standard_unit` field)
- **Importance**: relevant
- **Why it matters**: Tests create foods and units through these schemas before assembling `RecipeIngredient(food=…, unit=…, quantity=…)`. Setting `standard_unit=None` on a test unit guarantees `can_merge` will fall through to the unit-equality branch and NOT use `UnitConverter` — required for "different units do not merge" assertions to remain stable post-PR #7121.

### N. `RecipeIngredientModel` SQLAlchemy model
- **Path / lines**: `mealie/db/models/recipe/ingredient.py:344-360`
- **Importance**: relevant
- **Key columns**: `unit_id`, `food_id`, `quantity: Float | None` (line 359), `note: String | None` (line 351). Persistence is float.

### O. `NoneFloat` alias
- **Path / lines**: `mealie/schema/_mealie/types.py:1`
- **Importance**: adjacent
- **Value**: `NoneFloat = float | None`. Confirms no `Decimal` layer anywhere.

### P. `UnitConverter` / `merge_quantity_and_unit`
- **Path / lines**: `mealie/services/parser_services/parser_utils/unit_utils.py:20` (class), `:66` (`can_convert`), `:107` (`merge_quantity_and_unit`)
- **Importance**: relevant
- **Why it matters**: After PR #7121 the `(food_id, unit_id)` merge key was loosened — items with different `unit_id` but compatible `standard_unit` will merge through `UnitConverter`. To keep the "different unit ⇒ no merge" regression test stable, test units must be created WITHOUT `standard_unit` (default `None`).

### Q. `AllRepositories.group_shopping_list_item` / `ingredient_foods` / `ingredient_units`
- **Path / lines**: `mealie/repos/repository_factory.py:139-145` (foods/units), `:317-345` (shopping list / item / item refs)
- **Importance**: relevant
- **Why it matters**: Tests use `unique_user.repos.ingredient_foods.create(SaveIngredientFood(...))`, `unique_user.repos.ingredient_units.create(SaveIngredientUnit(...))`, and `unique_user.repos.recipes.create(Recipe(...))`. No bespoke `RepositoryShoppingItem` class exists — items go through `HouseholdRepositoryGeneric`.

### R. Existing similar test: bulk add with shared ingredients
- **Path / lines**: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` (`test_shopping_lists_add_recipes_with_merge`)
- **Importance**: critical
- **What it does**: Builds two recipes that share a common note. Posts both via `POST .../recipe`. Asserts the shared ingredient produces ONE list item with `quantity = 2` and `len(recipe_references) == 2`. Each non-shared ingredient is one row with quantity 1.
- **Gap vs. case 3**: Uses notes only, no `food_id` / `unit_id`, and adds two DIFFERENT recipes. Case 3 requires the SAME recipe added twice through meal-plan entries, with explicit `food_id + unit_id`.

### S. Existing similar test: same-recipe internal duplicates
- **Path / lines**: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:581-660` (`test_shopping_lists_add_recipe_with_merge`)
- **Importance**: relevant
- **What it does**: Recipe with 4 ingredients (2 share a note); asserts 3 list items, quantity sum for the duplicate note. Exercises the in-recipe pre-merge in `get_shopping_list_items_from_recipe` (lines 387-409).

### T. Existing meal-plan creation test (pattern reuse)
- **Path / lines**: `tests/integration_tests/user_household_tests/test_group_mealplan.py:80-99` (`test_create_mealplan_with_recipe`)
- **Importance**: relevant
- **What it does**: Demonstrates `CreatePlanEntry(date=..., entry_type="dinner", recipe_id=recipe_id).model_dump(by_alias=True)` + `new_plan["date"] = date.strftime("%Y-%m-%d")` + `new_plan["recipeId"] = str(recipe_id)` + `POST api_routes.households_mealplans`.

### U. Test fixtures (recipe / shopping list / user)
- **Path / lines**:
  - `tests/fixtures/fixture_users.py:179-226` (`_unique_user`, `unique_user`)
  - `tests/fixtures/fixture_recipe.py:31-49` (`recipe_ingredient_only`)
  - `tests/fixtures/fixture_shopping_lists.py:49-65` (`shopping_list`)
  - `tests/conftest.py:37-54` (`override_get_db`, `api_client`)
- **Importance**: critical
- **Why it matters**: New repro tests use `unique_user` for auth + repos, `shopping_list` for a clean destination, and `api_client` for HTTP calls. Existing patterns rely on session-scoped DB with no per-test rollback — tests must clean up or use random ids to avoid cross-contamination.

### V. Test route helpers
- **Path / lines**: `tests/utils/api_routes/__init__.py:92` (`households_mealplans`), `:114-115` (`households_shopping_lists`), `:405-407` (`households_shopping_lists_item_id`), `:415-417` (`households_shopping_lists_item_id_recipe`), `:420-422` (`households_shopping_lists_item_id_recipe_recipe_id`)
- **Importance**: relevant
- **Why it matters**: All required routes have generated helpers. No new route helper is needed.

### W. History: most relevant prior PRs
- **PR #5054 (`716c85cc`, 2025-02-27)**: closest precedent. Fixed issue #3417 "shopping list items of the same type are not consolidated" via bulk recipe add. Spec must NOT regress this.
- **PR #7121 (`b5c089f5`, 2026-03-09)**: introduced `standard_unit` / `UnitConverter` in `can_merge`. The "different units do not merge" assertion in case 3 must explicitly use non-standardized units.
- **PR #4800 (`60d92948`, 2025-11-03)**: added recipe-as-ingredient flattening; spec edge case for recipe deletion mid-flow stems from this.
- **PR #1847 (recipe scale)**: introduced `recipe_scale` semantics — must be preserved when summing.

---

## 2. Cross-perspective agreements

1. **The HTTP route under test is `POST /api/households/shopping/lists/{item_id}/recipe`** (api + test + data all converge). No dedicated mealplan→shopping endpoint exists.
2. **The merge key is `(food_id, unit_id)` with `note` as fallback only when `food_id is None`** (data + api + history confirm by reading `can_merge` lines 45-71). Different `food_id` never merge; `display` name is NOT a key.
3. **`merge_items` accumulates with `to_item.quantity += from_item.quantity` (line 96)** when no unit conversion is needed. This is the single accumulation site; replacing `+=` with `=` is the canonical "covers instead of accumulates" bug.
4. **The bug surface is `bulk_create_items` (+ `can_merge` + `merge_items`)**, all in `mealie/services/household_services/shopping_lists.py`. All four perspectives agree on this scope.
5. **Quantities are `float` everywhere** (db + schema + service); there is no `Decimal` layer. Float precision is a real concern for assertions.
6. **Recipe ingredient quantities are rounded to `INGREDIENT_QTY_PRECISION = 3`** at the ingredient-schema layer (line 23 + lines 353-354), but shopping-list sums are NOT rounded after addition.
7. **All four required regression tests are unsupported by existing test coverage**: no test creates meal-plan entries and then exercises the add-recipes flow; no test exercises the "different food_id, same display name" path; "different units do not merge" is only partially covered for non-standardized units.

## 3. Cross-perspective conflicts (max 5)

### C1. Did the bug actually exist on baseline?
- **History/data**: `bulk_create_items` lines 162-176 + `merge_items` line 96 look correct on baseline; PR #5054 already fixed the closest known precedent. `test_shopping_lists_add_recipes_with_merge` (lines 663-739) already asserts a similar (different-recipe shared ingredient) merge passes.
- **Input**: input.md附录 explicitly provides a "bug injection patch" specifying that if baseline has no bug, inject one (overwrite-vs-accumulate, or display-vs-food_id key).
- **Resolution for spec**: The spec MUST treat the bug as present (per input intent). The reproduction test must FAIL on the bug-injected branch. If on a clean baseline the test PASSES, the operator is instructed to apply the injection patch first.

### C2. Should "different unit ⇒ no merge" override `UnitConverter`?
- **API/history**: PR #7121 made `can_merge` merge convertible units (e.g. `gram` vs `kilogram`). A test asserting "different unit no merge" with standardized units would contradict shipped behavior.
- **Test perspective**: recommends creating units with `standard_unit=None` to avoid the conversion path.
- **Resolution for spec**: Use units with `standard_unit=None` (the default for `SaveIngredientUnit`) in the "different units" regression test. The spec documents this explicitly so the contract is "different `unit_id` with no convertibility ⇒ no merge".

### C3. Should the test send two bulk entries or one with `recipe_increment_quantity=2`?
- **API**: frontend `consolidateRecipesIntoSections` collapses duplicates into a single entry with larger `recipeScale`/`recipeIncrementQuantity` before POSTing.
- **Data/test**: backend MUST support BOTH forms: two entries (per-occurrence) and one entry with quantity 2. Either must produce the same consolidated row.
- **Resolution for spec**: Repro (`US-1`) uses the per-occurrence form (two bulk entries, each with `recipe_increment_quantity=1`) to mirror what a naive client (or one bypassing frontend consolidation) would send and to exercise `bulk_create_items` pass-1 consolidation directly. `test_multiple_occurrences_same_unit` (`US-4`) parametrizes both forms.

### C4. Should `recipe_scale` accumulation be in scope?
- **History**: PR #1847 / #7537 showed scale accumulation bugs. `merge_items` lines 109-126 sum `recipe_scale` per `recipe_id`.
- **Input**: 评估表 explicitly flags "回归测试是否需要覆盖 recipe scale factor 场景" as a CR-stage concern.
- **Resolution for spec**: Include `recipe_scale` accumulation as an edge case + assertion in `test_multiple_occurrences_same_unit` (recipe_references should contain ONE ref with `recipe_scale == N` OR N refs, depending on which `recipe_id` is repeated). The spec pins the exact expectation: ONE `recipe_references` entry with `recipe_scale == N` when the same recipe is added N times (per `merge_items` lines 109-126).

### C5. Is `get_shopping_list_items_from_recipe` lines 395-397 a separate bug?
- **Data/history**: When a single recipe has duplicate ingredients AND `scale != 1`, the in-recipe pre-merge adds raw `ingredient.quantity`, not `ingredient.quantity * scale`. This undercounts.
- **Input scope**: input.md says "minimum-scope fix" and "do not refactor surrounding code". The reported bug is about multiple meal-plan occurrences of the same recipe, not internal duplicates with scaling.
- **Resolution for spec**: Out of scope for the minimum fix. Documented as a `self_concern` for future follow-up; spec does NOT add a regression test for this path.

## 4. Critical conflicts (the 5 above — already filtered to spec-relevant)

The 5 conflicts in section 3 are exactly the spec-critical ones. Nothing else materially changes the spec contract.

## 5. Likely root cause

The bug is in `ShoppingListService.bulk_create_items` (`mealie/services/household_services/shopping_lists.py:154-223`) and/or its callee `merge_items` (`:73-128`). The reported symptoms map cleanly to the two canonical bug variants documented in input.md附录:

- **Variant A — "quantity covered, not accumulated"**: `merge_items` line 96 changed from `to_item.quantity += from_item.quantity` to `to_item.quantity = from_item.quantity`. Two meal-plan occurrences merge into ONE row but the quantity equals the single-recipe amount instead of 2×.
- **Variant B — "wrong merge key (display instead of food_id)"**: `can_merge` builds the key from `display` (or `note`) instead of `food_id`. Two occurrences of the same recipe end up with different generated `display` strings (or different notes due to formatting), so they do NOT merge — two separate rows appear instead of one accumulated row.

Both variants are detected by the same invariant the repro test asserts: after adding the same recipe N times through meal-plan-style bulk add, the shopping list must contain EXACTLY ONE row per `(food_id, unit_id)` whose `quantity == base_quantity × N`. The minimum fix restores the `(food_id, unit_id)` merge key and the `+=` accumulation in `merge_items`.

The fix is localized to 1-2 lines inside these two functions; surrounding methods (`bulk_update_items`, `remove_recipe_ingredients_from_list`, `get_shopping_list_items_from_recipe`) are not in scope for the minimum repair.
