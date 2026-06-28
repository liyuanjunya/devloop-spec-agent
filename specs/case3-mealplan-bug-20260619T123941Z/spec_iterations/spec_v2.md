# Spec — Case 3: Meal Plan → Shopping List Consolidation Bug Fix (v2)

> Generated from `input.md`, `intent/confirmed.json`, `exploration/consolidated.md`, `approach/selected.md`, and 4 v1 reviewer reports. All code references verified line-by-line in `C:\Users\v-liyuanjun\Downloads\mealie\`.

## Metadata

- **Spec ID**: `case3-mealplan-bug-20260619T123941Z/spec-v2`
- **Iterations**: 2
- **Intent type**: `bug_fix`
- **Scope**: `service` (single function in `mealie/services/household_services/shopping_lists.py`) + `test` (new integration test file)
- **Selected approach**: Conservative — smallest patch inside `can_merge` and/or `merge_items` (see `approach/selected.md`).
- **Production target file under repair**: `mealie/services/household_services/shopping_lists.py`
- **New test file**: `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`
- **No schema / migration / controller / repository changes.**

---

## Baseline reality and bug-injection precondition (NEW in v2)

The architecture reviewer (v1, ARCH-C-001 / ARCH-C-002) correctly observed that the **checked-out Mealie baseline at `C:\Users\v-liyuanjun\Downloads\mealie\` does NOT exhibit the bug**: `can_merge` already rejects different `food_id` (line 52), the standard-unit fallback is gated (lines 57-68), the `note`-fallback is conditional on `food_id is None` (line 71), and `merge_items` already uses `to_item.quantity += from_item.quantity` (line 96). On the baseline tree, the v1-required reproduction test would PASS, not FAIL — making SC-1 of v1 unsatisfiable.

To make this DevLoop case deterministic and repeatable, this spec **adopts the bug-injection workflow documented in `input.md:88-138` (附录: Bug 注入 Patch)**. Operator instructions:

1. Cut a branch `inject-bug` from the baseline commit.
2. Apply ONE of the two canonical bug-injection patches (the operator picks; both produce equivalent symptoms):
   - **Variant A — "overwrite instead of accumulate"**: in `mealie/services/household_services/shopping_lists.py:96`, replace `to_item.quantity += from_item.quantity` with `to_item.quantity = from_item.quantity`.
   - **Variant B — "wrong merge key"**: in `mealie/services/household_services/shopping_lists.py:45-71` (`can_merge`), replace the `item1.food_id != item2.food_id` rejection (line 52) and/or the final `bool(item1.food_id) or item1.note == item2.note` return (line 71) with a key derived from `display` (e.g. return `item1.display == item2.display`), so two same-food items end up with different `display` strings and fail to merge, while two different-food same-name items wrongly merge.
3. Cut the case-3 working branch from `inject-bug`. DevLoop fixes the bug by reverting Variant A or Variant B to the canonical implementation.

This precondition is intentionally documented in the spec (not hidden in operator notes) so the reviewer chain understands that "FAIL before fix" means **FAIL on the bug-injected branch**, not on baseline. The fix itself remains a 1-2 line surgical revert — minimum-scope as required by input.md:40-43.

The variant chosen by the operator is unknown to DevLoop ahead of time; it must be inferred from the failing test output and the diff between the working branch and baseline. The root-cause analysis (US-2) explicitly handles either variant. See `needs_clarification` NC-001.

---

## Problem statement

When a Mealie user schedules the same recipe in multiple meal-plan slots within a week (e.g. Monday dinner = recipe A, Wednesday lunch = recipe A) and then triggers the "Add Meal Plan to Shopping List" UI action, the resulting shopping list must contain exactly one row per `(food_id, unit_id)` whose `quantity` equals the recipe's per-ingredient quantity times the number of occurrences. With the injected bug present (Variant A or Variant B), this invariant is violated: either the row appears once with the single-recipe quantity (Variant A — lost accumulation), or it appears multiple times unmerged (Variant B — lost consolidation). Both symptoms localize to `ShoppingListService.can_merge` (`mealie/services/household_services/shopping_lists.py:45-71`) and `ShoppingListService.merge_items` (`mealie/services/household_services/shopping_lists.py:73-128`).

The frontend "Add Meal Plan to Shopping List" action has no dedicated backend route; it gathers the planned recipes and calls `POST /api/households/shopping/lists/{item_id}/recipe` (`mealie/routes/households/controller_shopping_lists.py:256-261`) with a `list[ShoppingListAddRecipeParamsBulk]` payload, which delegates to `ShoppingListService.add_recipe_ingredients_to_list` (`mealie/services/household_services/shopping_lists.py:413-455`) and then to `ShoppingListService.bulk_create_items` (`:154-223`).

### Frontend payload shape (verified, v2 addition for ARCH-H-001)

The real frontend pipeline is:

1. `frontend/app/pages/household/mealplan/planner.vue:243-256` (`weekRecipesWithScales`) maps each meal-plan occurrence to one object with `scale: 1`. Two meal-plan slots → two list elements.
2. `frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue:340-394` (`consolidateRecipesIntoSections`) deduplicates by `recipe.slug` and accumulates duplicates into one section with `recipeScale += recipe.scale` (lines 345-349).
3. `frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue:434-461` (`addRecipesToList`) sends ONE `ShoppingListAddRecipeParamsBulk` per unique recipe, with `recipeIncrementQuantity: section.recipeScale` (line 457).
4. `frontend/app/lib/api/user/group-shopping-lists.ts:32-34` POSTs that payload to `/api/households/shopping/lists/{id}/recipe`.

The merge-consolidation bug surface (Variant A/B inside `bulk_create_items`) is exercised by the **per-occurrence backend form**: two `ShoppingListAddRecipeParamsBulk` entries with `recipe_increment_quantity=1` each. The **consolidated frontend form** (one entry with `recipe_increment_quantity=2`) instead exercises the scaling path at `get_shopping_list_items_from_recipe:373` (`ingredient.quantity * scale`) and the list-level reference accumulator at `add_recipe_ingredients_to_list:443`. Both forms MUST produce identical results: exactly one shopping-list row per `(food_id, unit_id)` with the per-recipe quantity multiplied by 2. Because the backend route accepts both forms and at least one client (the API or a custom integration) may bypass dialog-side consolidation, the spec exercises BOTH forms.

---

## User stories

### US-1 — 复现 (Reproduce, primary backend form)

**As** a Mealie developer fixing this bug, **I want** an integration test that reliably reproduces the meal-plan-to-shopping-list consolidation failure on the bug-injected branch, **so that** the regression cannot recur silently and the fix has a measurable acceptance signal.

**Acceptance criteria**:
- A new test file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` exists.
- The test `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients`:
  1. Creates `food_tomato` and `food_salt` via `unique_user.repos.ingredient_foods.create(SaveIngredientFood(name=..., group_id=unique_user.group_id))` (pattern: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:258-278`). **(v2 fix for EXEC-H-001 / C-001: the second food is `food_salt` — matching `input.md:26` 盐 — across all subsequent steps.)**
  2. Creates two units via `unique_user.repos.ingredient_units.create(SaveIngredientUnit(name="each", group_id=unique_user.group_id))` and `SaveIngredientUnit(name="tsp", group_id=unique_user.group_id)` with `standard_unit=None` (default — confirmed at `mealie/schema/recipe/recipe_ingredient.py:155-156`) to avoid `UnitConverter` interference.
  3. Creates `recipe_a` via `unique_user.repos.recipes.create(Recipe(...))` with `recipe_ingredient=[RecipeIngredient(food=food_tomato, unit=unit_each, quantity=2.0, note=food_tomato.name), RecipeIngredient(food=food_salt, unit=unit_tsp, quantity=1.0, note=food_salt.name)]` (pattern: `tests/fixtures/fixture_recipe.py:31-49`).
  4. Creates two meal-plan entries via `POST /api/households/mealplans` (`tests/utils/api_routes/__init__.py:92`) with `CreatePlanEntry(date=monday, entry_type="dinner", recipe_id=recipe_a.id).model_dump(by_alias=True)` and `CreatePlanEntry(date=wednesday, entry_type="lunch", recipe_id=recipe_a.id).model_dump(by_alias=True)`, with `new_plan["date"] = date.strftime("%Y-%m-%d")` and `new_plan["recipeId"] = str(recipe_a.id)` normalization (pattern: `tests/integration_tests/user_household_tests/test_group_mealplan.py:80-99`).
  5. Acquires the destination shopping list from the `shopping_list` fixture (`tests/fixtures/fixture_shopping_lists.py:49-65`).
  6. POSTs `[ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id), ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id)]` (two per-occurrence entries with default `recipe_increment_quantity=1`, exercising the merge-consolidation bug surface targeted by `input.md:88-128` Variants A/B) to `api_routes.households_shopping_lists_item_id_recipe(shopping_list.id)` (`tests/utils/api_routes/__init__.py:415-417`) using `utils.jsonify([... .model_dump()])`.
  7. GETs the shopping list and asserts exactly one item per food: `tomato` quantity equals `4.0` (within `pytest.approx(abs=1e-6)`), with `unit_id == unit_each.id` and `food_id == food_tomato.id`; `salt` quantity equals `2.0` with `unit_id == unit_tsp.id` and `food_id == food_salt.id`; total `len(listItems) == 2`.
- This test **FAILS on the bug-injected branch** (Variant A: tomato quantity == 2.0 instead of 4.0; Variant B: `len(listItems) == 4` with two unmerged tomato rows and two unmerged salt rows) and **PASSES after the US-3 fix re-applies the canonical implementation**.

### US-2 — 根因 (Root-cause analysis)

**As** a code reviewer, **I want** the PR description to contain a structured root-cause analysis, **so that** the failure mode, fix location, and adjacent contract are documented for future maintainers.

**Acceptance criteria**:
- The PR description contains a `### Root cause` section that answers, verbatim and in order:
  1. **Which function holds the bug?** Names the exact path + symbol, e.g. `mealie/services/household_services/shopping_lists.py::ShoppingListService.merge_items` (line 96) for Variant A OR `…::ShoppingListService.can_merge` (line 52 and/or line 71) for Variant B. Cites the line number(s) actually changed in the fix diff.
  2. **Wrong merge key or quantity overwrite vs. accumulate?** States explicitly whether the observed defect is (Variant A) `merge_items` line 96 using `=` instead of `+=`, or (Variant B) `can_merge` using `display` (or any non-`food_id` derivation) as the primary merge key. References `input.md:88-128` 附录 to label the variant.
  3. **Boundary cases**, covering each of: same `food_id` + same `unit_id` ⇒ merge with sum; same `food_id` + different `unit_id` with both `standard_unit is None` ⇒ no merge; different `food_id` even with same `display`/name ⇒ no merge; `food_id is None` ⇒ merge falls back to `note` equality (`can_merge` line 71); `recipe_scale` accumulation through `merge_items` lines 109-126 yields one `recipe_references` entry with `recipe_scale == N` when the same `recipe_id` is added N times.
- The PR description references the file paths and line numbers above so the reviewer can navigate to the exact code.

### US-3 — 最小修复 (Minimum-scope fix)

**As** a Mealie maintainer, **I want** a 1-2 line surgical patch inside `mealie/services/household_services/shopping_lists.py` that restores the canonical `(food_id, unit_id)` merge key and the `to_item.quantity += from_item.quantity` accumulation, **so that** the reproduction passes and no other behavior is affected.

**Acceptance criteria** (v2 wording fix for C-002 — "production code" qualifier added):
- The ONLY **production-code** file modified is `mealie/services/household_services/shopping_lists.py`. The new test file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` is a required addition under `tests/` and is NOT counted against this constraint.
- Within `mealie/services/household_services/shopping_lists.py`, the diff is confined to `ShoppingListService.can_merge` (lines 45-71) and/or `ShoppingListService.merge_items` (lines 73-128). No new methods, no extracted helpers, no signature changes, no schema changes, no toggles, no config flags, no feature switches.
- The non-unit-converted branch at line 96 contains `to_item.quantity += from_item.quantity` (NOT `=`).
- `can_merge` rejects items with `item1.food_id != item2.food_id` (line 52) and uses `bool(item1.food_id) or item1.note == item2.note` as the final return (line 71); `display` is NOT used as a merge key anywhere.
- `bulk_create_items` (lines 154-223), `bulk_update_items` (lines 225-310), `get_shopping_list_items_from_recipe` (lines 323-411), and `add_recipe_ingredients_to_list` (lines 413-455) are unchanged.
- All pre-existing tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py`, `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py`, and `tests/integration_tests/user_household_tests/test_group_mealplan.py` continue to pass with no modifications (v2 fix for C-004 — `test_group_mealplan.py` added).

### US-4 — 回归测试 (Regression tests)

**As** a Mealie team member, **I want** four additional regression tests in the same new test file that pin the exact merge contract, **so that** any future change to consolidation logic is caught immediately.

**Acceptance criteria** — all four tests live in `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` and use the same helper / fixture conventions as US-1:

1. **`test_single_occurrence`** — Create the recipe, schedule it in exactly one meal-plan slot, add to a fresh shopping list. Assert: each ingredient appears once with `quantity == ingredient.quantity` (within `pytest.approx(abs=1e-6)`), `food_id` and `unit_id` set, exactly one `recipe_references` entry with `recipe_scale == 1.0`. Total `len(listItems) == 2` (tomato + salt).
2. **`test_multiple_occurrences_same_unit`** — Parametrized via two pytest parameter axes:
   - `@pytest.mark.parametrize("occurrences", [2, 3])` — number of meal-plan slots.
   - `@pytest.mark.parametrize("payload_form", ["per_occurrence", "consolidated"])` — backend form (v2 addition for ARCH-H-001):
     - `per_occurrence`: send N `ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id)` entries with default `recipe_increment_quantity=1` (exercises `bulk_create_items` consolidation through `can_merge` / `merge_items`).
     - `consolidated`: send ONE `ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id, recipe_increment_quantity=N)` entry (matches real frontend dialog payload at `RecipeDialogAddToShoppingList.vue:454-461`; exercises `get_shopping_list_items_from_recipe` scaling at `:373` and list-level ref accumulator at `add_recipe_ingredients_to_list:443`).
   - Assert (BOTH forms): each ingredient appears once with `quantity == ingredient.quantity * N` (within `pytest.approx(abs=1e-6)`), exactly one `recipe_references` entry with `recipe_scale == float(N)` (per `merge_items` lines 109-126 for `per_occurrence` form, and per `get_shopping_list_items_from_recipe:381` for `consolidated` form). `len(listItems) == 2`.
3. **`test_multiple_occurrences_different_units`** — Build TWO recipes: `recipe_each` has `RecipeIngredient(food=food_tomato, unit=unit_each, quantity=2)`; `recipe_grams` has `RecipeIngredient(food=food_tomato, unit=unit_gram, quantity=100)`. Both `unit_each` and `unit_gram` are created with `standard_unit=None` so `UnitConverter` does not apply. Schedule one of each, add both to a fresh shopping list. Assert: TWO distinct list items for `food_tomato`, one with `unit_id == unit_each.id, quantity == 2.0`, one with `unit_id == unit_gram.id, quantity == 100.0`. Both items have the same `food_id` but distinct `unit_id`. `len(listItems) == 2`.
4. **`test_different_food_same_name`** — Create two `SaveIngredientFood(name="tomato", group_id=...)` records (distinct UUIDs but identical name). Build two recipes, each using a different food but the same `unit_each` and `quantity=2`. Schedule one of each, add both to a fresh shopping list. Assert: TWO distinct list items, each with `food.name == "tomato"` but DISTINCT `food_id`. Each item has `quantity == 2.0`. `len(listItems) == 2`. This confirms `food_id` (not `display`/`name`) is the merge key.

All four tests PASS after the US-3 fix.

---

## Functional requirements

> Each FR pins a behavior the fix must satisfy, with VERIFIED code references (re-verified in v2 against `C:\Users\v-liyuanjun\Downloads\mealie\`).

### FR-1 (US-1) — Failing reproduction test exists
A new test file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` contains the `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` test described in US-1. The test is runnable via `task py:test -- tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` (per `Taskfile.yml:107-110`) or `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`. It exercises the real HTTP route `POST /api/households/shopping/lists/{item_id}/recipe` and asserts the per-food quantity and row-count invariants on the response of the subsequent `GET /api/households/shopping/lists/{item_id}`.
- **Code references**:
  - `mealie/routes/households/controller_shopping_lists.py:256-261` (route under exercise)
  - `tests/utils/api_routes/__init__.py:415-417` (route helper `households_shopping_lists_item_id_recipe`)
  - `tests/utils/api_routes/__init__.py:405-407` (`households_shopping_lists_item_id`)
  - `tests/utils/api_routes/__init__.py:92` (`households_mealplans`)
  - `tests/fixtures/fixture_users.py:179-226` (`unique_user`)
  - `tests/fixtures/fixture_shopping_lists.py:49-65` (`shopping_list`)
  - `tests/conftest.py:37-54` (`api_client`)

### FR-2 (US-2) — PR description contains a structured root-cause analysis
The PR description has a `### Root cause` markdown section answering the three input questions in order (function, variant, boundary cases) with at least one specific file:line citation per answer. The variant labeling references `input.md:88-128` 附录 (Variant A: overwrite-vs-accumulate at `merge_items` line 96; Variant B: wrong merge key at `can_merge` lines 52 / 71). Boundary case enumeration covers same-food+same-unit merge, same-food+different-unit non-merge (with `standard_unit=None`), different-food same-display non-merge, `food_id is None` note-fallback, and `recipe_scale` accumulation through `merge_items` lines 109-126.
- **Code references**:
  - `mealie/services/household_services/shopping_lists.py:45-71` (`can_merge`)
  - `mealie/services/household_services/shopping_lists.py:73-128` (`merge_items`)
  - `mealie/services/household_services/shopping_lists.py:109-126` (`recipe_scale` accumulation)
  - `input.md:88-138` (附录 — Variant A/B canonical patches and operator workflow)

### FR-3 (US-3) — Fix is confined to `can_merge` and/or `merge_items`
The diff modifies only `mealie/services/household_services/shopping_lists.py` **in production code** (the new test file under `tests/` is additionally required by US-1/US-4 and is NOT counted against this constraint — v2 wording fix for C-002). Within `shopping_lists.py`, only `ShoppingListService.can_merge` (lines 45-71) and/or `ShoppingListService.merge_items` (lines 73-128) are touched. Total changed lines ≤ 5 (idiomatic Conservative patch is 1-2 lines). After the fix: `can_merge` keeps `item1.food_id != item2.food_id` as a rejection (line 52), retains the existing `standard_unit` / `UnitConverter` branch (lines 57-68), and returns `bool(item1.food_id) or item1.note == item2.note` (line 71). `merge_items` keeps `to_item.quantity += from_item.quantity` (line 96), the `merge_quantity_and_unit(...)` branch (lines 86-92), the note concatenation (lines 98-104), the extras update (lines 106-107), and the recipe-reference merge (lines 109-126) unchanged.
- **Code references**:
  - `mealie/services/household_services/shopping_lists.py:45-71`
  - `mealie/services/household_services/shopping_lists.py:73-128`
  - `mealie/services/household_services/shopping_lists.py:154-223` (unchanged consumer)
  - `mealie/services/household_services/shopping_lists.py:413-455` (unchanged caller)

### FR-4 (US-4) — Four regression tests with the named contract
Four tests are appended to `test_meal_plan_to_shopping_bug.py` with the EXACT names and behaviors in the input table: `test_single_occurrence`, `test_multiple_occurrences_same_unit` (parametrized over `occurrences=[2, 3]` × `payload_form=["per_occurrence", "consolidated"]` — v2 addition for ARCH-H-001), `test_multiple_occurrences_different_units`, `test_different_food_same_name`. Each asserts both the per-item quantity AND the `len(listItems)` count; each also asserts the `food_id` and `unit_id` on returned items (not just `note` / `display`) to lock the merge-key semantics.
- **Code references** (v2 widened for EXEC-M-001):
  - `mealie/schema/household/group_shopping_list.py:58-67` (`ShoppingListItemBase` declares `food_id`, `unit_id`, inherited by `ShoppingListItemOut`)
  - `mealie/schema/household/group_shopping_list.py:106-120` (`ShoppingListItemOut` adds `food`, `unit`)
  - `mealie/schema/household/group_shopping_list.py:32-46` (`ShoppingListItemRecipeRefCreate` — `recipe_scale` field)
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` (analogous prior test pattern to mirror: `test_shopping_lists_add_recipes_with_merge`)
  - `mealie/services/household_services/shopping_lists.py:109-126` (`recipe_scale` merge semantics — `per_occurrence` form)
  - `mealie/services/household_services/shopping_lists.py:370-385` (`get_shopping_list_items_from_recipe` scaling — `consolidated` form)
  - `mealie/services/household_services/shopping_lists.py:437-452` (`add_recipe_ingredients_to_list` list-level ref accumulator — `consolidated` form)

### FR-5 (US-3 / non-functional) — Pre-existing tests remain green
After the US-3 fix, all tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py`, `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py`, and `tests/integration_tests/user_household_tests/test_group_mealplan.py` PASS without modification. In particular, the existing merge tests `test_shopping_lists_add_recipe_with_merge` (lines 581-660), `test_shopping_lists_add_recipes_with_merge` (lines 663-739), and `test_shopping_lists_add_nested_recipe_ingredients` (lines 249-361) keep passing — confirming the fix does not regress PRs #5054 (bulk add), #4800 (recipe-as-ingredient), or #7121 (unit standardization).
- **Code references**:
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:581-660`
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739`
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:249-361`
  - `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py:644-731` (standard-unit merge tests)

### FR-6 (non-functional) — Toolchain conformance per Mealie conventions
Tests follow Mealie conventions: use `unique_user` + `api_client` fixtures; assert via `utils.assert_deserialize(response, 200)` (`tests/utils/assertion_helpers.py:23-25`); serialize bulk payloads via `utils.jsonify([... .model_dump()])` (`tests/utils/jsonify.py:1-5`); deserialize the list response via `ShoppingListOut.model_validate(...)` for typed access to `food`, `unit`, `food_id`, `unit_id`, `recipe_references`. The full validation command is `task py:check` (`Taskfile.yml:122-128` — runs ruff format + ruff lint + mypy + pytest). Python entry-points use `uv` (never `python` / `pip`), per `.github/copilot-instructions.md`.
- **Code references** (v2 widened for EXEC-M-001):
  - `tests/utils/assertion_helpers.py:23-25`
  - `tests/utils/jsonify.py:1-5`
  - `Taskfile.yml:107-110` (`py:test`)
  - `Taskfile.yml:122-128` (`py:check`)
  - `mealie/schema/household/group_shopping_list.py:245-254` (`ShoppingListUpdate.list_items` at line 247, `ShoppingListOut` at line 250 — needed by `ShoppingListOut.model_validate(...).list_items`)
  - `mealie/schema/household/group_shopping_list.py:250-285` (`ShoppingListOut` loader options)

### FR-7 (non-functional) — Implementation constraints (NEW in v2, addresses COMP-M-002)
Per `input.md:55-59`, the fix must satisfy three implementation constraints **explicitly enumerated** as acceptance gates (not merely implied by diff limits):

1. **No toggle / config / feature-flag workaround.** The fix MUST be a real behavioral correction inside `can_merge` / `merge_items`. Adding a setting, env var, request parameter, or runtime flag to "opt into" the correct behavior is forbidden.
2. **No broad mechanical edit.** No global `grep + sed` style rewrites; no rename sweeps; no auto-formatting churn that adds noise outside the 1-2 changed lines. The diff against the bug-injected baseline (or against the canonical Mealie baseline after the operator-injected patch is conceptually reverted) must contain only the canonical accumulation / merge-key restoration.
3. **No parallel implementation.** Continue to use the existing `RepositoryShoppingItem` / `ShoppingListItem` schemas (per `input.md:59`). Do NOT introduce a new model, repository, alternative merge path, side-table, cache, or "v2" shopping-item type. All persistence flows through `self.list_items.create_many` / `update_many` in `bulk_create_items` (`mealie/services/household_services/shopping_lists.py:215-216`) unchanged.
- **Code references**:
  - `mealie/services/household_services/shopping_lists.py:154-223` (`bulk_create_items`, unchanged persistence path)
  - `mealie/db/models/household/shopping_list.py:51-98` (`ShoppingListItem` SQLAlchemy model, untouched)
  - `mealie/schema/household/group_shopping_list.py:58-120` (`ShoppingListItemBase` / `…Create` / `…Update` / `…Out`, untouched)
  - `input.md:55-59` (constraint origin)

---

## Success criteria

| ID | Metric | Threshold | How measured |
|---|---|---|---|
| SC-1 | `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` exit status **on the bug-injected branch** (precondition documented in "Baseline reality" section above) | exit non-zero (FAIL) | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients -v` after Variant A or Variant B is applied per `input.md:88-128` |
| SC-2 | Same test exit status after fix | exit zero (PASS) | Re-run after the US-3 patch restores canonical implementation |
| SC-3 | Total pytest cases collected from `test_meal_plan_to_shopping_bug.py` pass (v2 fix for C-003) | **6 pytest cases pass** (1 repro + 1 single + 4 parametrized [2 occurrences × 2 payload_forms] + 1 different-units + 1 same-name = **8 total**); see note below | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py -v` |
| SC-4 | Pre-existing related tests still green (v2 includes `test_group_mealplan.py` per C-004) | 0 new failures in `test_group_shopping_lists.py`, `test_group_shopping_list_items.py`, `test_group_mealplan.py` | `uv run pytest tests/integration_tests/user_household_tests/test_group_shopping_lists.py tests/integration_tests/user_household_tests/test_group_shopping_list_items.py tests/integration_tests/user_household_tests/test_group_mealplan.py` |
| SC-5 | Diff size in `mealie/services/household_services/shopping_lists.py` | ≤ 5 changed lines | `git diff --shortstat -- mealie/services/household_services/shopping_lists.py` (pre-commit-friendly, no `HEAD~` per EXEC-M-002) **and** `git diff --shortstat HEAD~ -- mealie/services/household_services/shopping_lists.py` post-commit |
| SC-6 | Files modified in **production code** | exactly 1 (`mealie/services/household_services/shopping_lists.py`) | `git diff --name-only -- mealie/` (pre-commit) **and** `git diff --name-only HEAD~ -- mealie/` (post-commit). Files under `tests/` are explicitly NOT counted against this metric. |
| SC-7 | `task py:check` exit status | zero | `task py:check` end-to-end (runs ruff format + ruff lint + mypy + pytest, per `Taskfile.yml:122-128`) |
| SC-8 | Implementation-constraint conformance (NEW for FR-7) | All three constraints from `input.md:55-59` hold | Manual audit: (a) no new config keys in `mealie/core/settings/`; (b) `git diff --stat` shows no file outside `mealie/services/household_services/shopping_lists.py` and `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`; (c) no new model class in `mealie/db/models/` or new schema class in `mealie/schema/`. |

**SC-3 collection arithmetic.** Named tests: 5 (`test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients`, `test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`). Pytest case expansion: `test_multiple_occurrences_same_unit` has 2 × 2 = 4 cases (occurrences × payload_form), others are 1 case each → 1 + 1 + 4 + 1 + 1 = **8 collected cases, all must PASS**.

---

## Edge cases

| EC | Scenario | Expected behavior | Source |
|---|---|---|---|
| EC-1 | Same `food_id`, different `unit_id`, neither unit has `standard_unit` | Two distinct rows (no merge) | `can_merge` lines 57-68: both fail the `standard_unit` check, return `False` |
| EC-2 | Different `food_id`, identical `food.name` ("tomato" twice with distinct UUIDs) | Two distinct rows (no merge) | `can_merge` line 52: `item1.food_id != item2.food_id` rejects merge regardless of name |
| EC-3 | Same recipe added N times with `recipe_increment_quantity` mix (e.g. one entry with 2 and one entry with 1) | One row per `(food_id, unit_id)` with quantity = `base * 3`; one `recipe_references` entry with `recipe_scale == 3.0` | `merge_items` lines 109-126 sum `recipe_scale` per `recipe_id` |
| EC-4 | Float-precision accumulation (e.g. `0.1 * 3` produces `0.30000000000000004`) | Assertions use `pytest.approx(..., abs=1e-6)`; quantities are persisted as raw float sums (no rounding after merge) | `mealie/db/models/household/shopping_list.py:67` (Float column); `mealie/schema/recipe/recipe_ingredient.py:23, 345-357` rounds INPUT to `INGREDIENT_QTY_PRECISION=3` but `merge_items` line 96 does NOT round the SUM |
| EC-5 | Recipe deleted between meal-plan creation and add-to-shopping-list | `get_shopping_list_items_from_recipe` raises `UnexpectedNone("Recipe not found")` — caller surfaces this; the new tests do NOT exercise this path (out of fix scope) but the spec documents it as an unchanged contract | `mealie/services/household_services/shopping_lists.py:336-338` |
| EC-6 | `food_id is None` on both items (parsed/unparsed ingredient with no food) | Merges only when `note` matches (`can_merge` line 71 fallback) | `can_merge` lines 70-71: `return bool(item1.food_id) or item1.note == item2.note` |
| EC-7 | Recipe with internal duplicate ingredients AND `recipe_increment_quantity > 1` (sub-recipe scaling) | The same-recipe pre-merge in `get_shopping_list_items_from_recipe` lines 395-397 adds raw `ingredient.quantity` (not scaled); this is a separate latent issue documented in `self_concerns`, NOT fixed here | `mealie/services/household_services/shopping_lists.py:393-397` |
| EC-8 (NEW v2) | Consolidated payload form: one `ShoppingListAddRecipeParamsBulk(recipe_increment_quantity=N)` instead of N per-occurrence entries | Same result as N per-occurrence entries: one row per `(food_id, unit_id)` with `quantity == ingredient.quantity * N`, one `recipe_references` entry with `recipe_scale == N`. Asserted by `test_multiple_occurrences_same_unit[payload_form=consolidated]`. | `get_shopping_list_items_from_recipe:370-385` (scaling at line 373: `ingredient.quantity * scale if ingredient.quantity else 0`), `add_recipe_ingredients_to_list:437-452` (list-level ref `recipe_quantity += recipe.recipe_increment_quantity` at line 443) |

---

## Self-concerns

1. **In-recipe duplicate scaling latent bug.** `get_shopping_list_items_from_recipe` lines 395-397 use `existing_item.quantity += ingredient.quantity` rather than `ingredient.quantity * scale` when consolidating duplicates inside a single recipe. With `recipe_increment_quantity > 1` and internal duplicates, the result undercounts. This is OUT OF SCOPE for the case 3 minimum fix (the reported bug is duplicate occurrences across meal-plan slots, not internal duplicates at scale). Recommended follow-up: a separate PR with its own reproduction test. Confirmed `confirmed_problem` by ARCH-M-002 reviewer.
2. **Float-precision accumulation not rounded.** `merge_items` line 96 produces raw float sums; for ingredients with fractional quantities (e.g. `1/3`), accumulating across many occurrences will produce floats that do not round-trip exactly to `INGREDIENT_QTY_PRECISION=3` decimal places. The Mealie schema rounds INPUT quantities but not consolidated sums. Tests in this spec use `pytest.approx(..., abs=1e-6)` to remain robust. A future enhancement could re-round at the persistence boundary, but this would also be a separate PR.
3. **Future unit-conversion merge dimensions.** PR #7121 introduced `standard_unit` / `UnitConverter` so two items with different `unit_id` but compatible `standard_unit` DO merge (e.g. `gram` + `kilogram`). If a future PR adds more merge dimensions (e.g. fuzzy food matching by alias), the `test_multiple_occurrences_different_units` test must be re-evaluated. The spec uses `standard_unit=None` units explicitly to insulate the regression test from that change.
4. **Bug-injection precondition (NEW v2).** This case relies on the operator applying `input.md:88-128` 附录 Variant A or B against the otherwise-clean baseline. If the operator skips injection, SC-1 will erroneously report "FAIL: pytest expected non-zero exit but the test passed" — i.e. the test PASSES against the canonical baseline, indicating the bug is not present. The architecture review (ARCH-C-002) flagged this explicitly. Resolution path documented at the top of this spec; choice of Variant A vs Variant B documented at NC-001.

---

## Out of scope

- Modifying any frontend code (`frontend/`) — bug is backend-only. (Frontend code is cited only as evidence of the real payload shape exercised by `test_multiple_occurrences_same_unit[payload_form=consolidated]`.)
- Refactoring `bulk_create_items`, `bulk_update_items`, `get_shopping_list_items_from_recipe`, or `add_recipe_ingredients_to_list`.
- Changing any SQLAlchemy model, Alembic migration, repository, or Pydantic schema.
- Adding a dedicated meal-plan-to-shopping-list backend route (UI currently calls the existing bulk route — this is by design).
- Fixing the in-recipe duplicate scaling latent bug (see self-concern 1).
- Re-rounding float sums after merge (see self-concern 2).
- Any locale / translation file change.
- Any change to OpenAPI generation, TypeScript codegen, or test-helper generation. The `task dev:generate` step is NOT required because no Pydantic schema changes.
- Modifying or reverting the operator's bug-injection patch from a code-agent commit (the patch lives on the `inject-bug` branch; case-3 branches are downstream of it).

---

## Verification commands

| Phase | Command | Expected |
|---|---|---|
| Pre-fix (US-1 baseline on bug-injected branch) | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients -v` | 1 failed |
| Post-fix (US-3 acceptance, all collected cases) | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py -v` | **8 passed** (1 repro + 1 single + 4 parametrized + 1 different-units + 1 same-name; see SC-3 collection arithmetic) |
| Regression sweep | `uv run pytest tests/integration_tests/user_household_tests/test_group_shopping_lists.py tests/integration_tests/user_household_tests/test_group_shopping_list_items.py tests/integration_tests/user_household_tests/test_group_mealplan.py` | 0 new failures |
| Full validation | `task py:check` | exit 0 |
| Diff size check (pre-commit) | `git diff --shortstat -- mealie/services/household_services/shopping_lists.py` | ≤ 5 lines changed in 1 file |
| Diff size check (post-commit) | `git diff --shortstat HEAD~ -- mealie/services/household_services/shopping_lists.py` | ≤ 5 lines changed in 1 file |
| Production-file count check (pre-commit) | `git diff --name-only -- mealie/` | exactly 1 file: `mealie/services/household_services/shopping_lists.py` |
| Constraint audit (FR-7 / SC-8) | `git diff --stat` | only `mealie/services/household_services/shopping_lists.py` and `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` appear |

---

## needs_clarification

### NC-001 — Bug-injection variant choice (operator preference)
**Question**: Which canonical bug-injection variant from `input.md:88-128` 附录 is applied on the `inject-bug` branch — Variant A (`merge_items:96` `+=` → `=`, "overwrite-not-accumulate") or Variant B (`can_merge:52` / `:71` key derivation changed to `display`, "wrong merge key")?

**Why it matters**: Both variants fail the US-1 reproduction with distinct symptoms (Variant A → tomato `quantity == 2.0`, total `len == 2`; Variant B → tomato `quantity == 2.0` per row, total `len == 4`). The US-1 assertion list (one row per food with sum quantity) is robust to both, but US-2 root-cause analysis (FR-2 acceptance criterion 2) must name the variant explicitly. The fix patch is also slightly different (revert line 96 vs. revert line 52 / 71).

**Default if unanswered**: Spec proceeds assuming **Variant A** (most common bug pattern per `input.md:101`: "把累加改为覆盖（最常见的此类 bug 表现）"). The US-2 PR description template offers Variant A wording first, with an explicit Variant B fallback if the diff inspection contradicts the Variant A assumption.

**Resolution path**: Operator chooses at injection time; DevLoop infers by inspecting the diff between the case-3 working branch and the upstream baseline before authoring the US-2 root-cause section. No spec changes required regardless of choice.
