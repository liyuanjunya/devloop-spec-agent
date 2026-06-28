# Feature Specification: Meal Plan → Shopping List quantity consolidation bug fix (new pipeline v2)

**Feature ID**: `mealplan-shopping-consolidation-bugfix`
**Schema version**: 1.0

## Summary

Mealie case-3 (meal-plan-to-shopping-list quantity bug) re-run under the NEW DevLoop pipeline with all 19 v7 defenses, iteration v2 after the v1 4-axis self-review surfaced 1 HIGH and 4 MEDIUM findings (see `spec_iterations/review_v1.md`). intent_type = fix_bug. Goal: restore correct consolidation when the same recipe is scheduled multiple times in a meal plan and added to a shopping list — the resulting list MUST contain one row per `(food_id, unit_id)` whose quantity equals the single-recipe quantity times the occurrence count. v2 changes vs v1: (a) FR-002 + US-1 + US-2 now require `POST /api/households/mealplans` calls for each occurrence before the bulk-add to mirror the input user-visible flow (ARCH-NEW-H-001); (b) FR-008 / FR-010 / FR-011 now explicitly state regression tests MAY skip meal-plan persistence (COMP-NEW-M-001); (c) SC-002 metric aligned to `task py:test` (CONS-NEW-M-001); (d) FR-009 pins `@pytest.mark.parametrize` as the preferred idiom (EXEC-NEW-M-001); (e) SC-007 threshold rewritten in baseline-relative form so it is invariant to upstream Mealie test additions (EXEC-NEW-M-002). Three input-vs-code conflicts surface as `needs_clarification` blocking decisions: (NC-001) which bug-injection variant the operator applies; (NC-002) reconciling `different units no merge` with PR #7121's unit-conversion contract by pinning `standard_unit=None`; (NC-003) which wire shape the reproduction test sends. Functional requirements name the buggy functions `ShoppingListService.can_merge` (lines 45-71) and `ShoppingListService.merge_items` (lines 73-128) in `mealie/services/household_services/shopping_lists.py`, mandate a failing-before-fix reproduction test, mandate the four named regression tests (`test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`), mandate a Root Cause Analysis section in the PR description, and pin the fix to a minimum scope (1 file, at most 5+5 production-line delta). All 537 pre-existing pytest tests MUST continue to pass per FR-012 / SC-007. Every functional FR is linked to at least one measurable SC and every P1 user story is claimed by an FR per the B3 trace-matrix rule.

## NEEDS_CLARIFICATION (blocking decisions)

### NC-001 — Bug presence on baseline: is the bug currently latent in code, or does the operator need to apply the injection patch first?

**Conflict**: Input section `附录: Bug 注入 Patch` says baseline Mealie may already have a correct implementation, in which case the operator must apply one of two injection patches (variant A: replace `to_item.quantity += from_item.quantity` with `=` at `shopping_lists.py:96`; variant B: change the `can_merge` key from `(food_id, unit_id)` to `(display, unit_id)`). The exploration consolidated.md section 5 shows baseline code at `mealie/services/household_services/shopping_lists.py:73-128` already accumulates correctly via `to_item.quantity += from_item.quantity` at line 96, so the reproduction test in FR-002 will PASS on a clean baseline — not FAIL. The bug-fix workflow demands a FAILING repro test before the fix lands.

**Recommended default**: Treat the bug as present per input intent. The operator MUST apply injection variant A (overwrite-not-accumulate at `shopping_lists.py:96`) on an `inject-bug` branch BEFORE the implementer starts. Rationale: (1) variant A produces the exact symptom described in input — one row with single-recipe quantity instead of accumulated; (2) variant A is a 1-line change that the minimum-scope fix at FR-006 can revert verbatim; (3) variant A keeps `can_merge` correct so the four regression tests at FR-008..FR-011 exercise the merge-key contract independent of the accumulator contract. The implementer verifies on their first run that the repro test FAILS, then applies the fix, then verifies it PASSES.

**If rejected**: If the operator chooses injection variant B instead (`can_merge` key uses `display` not `food_id`), FR-006 must be re-pointed at `can_merge` rather than `merge_items`, and the repro test in FR-002 must additionally assert the merge key correctness (two occurrences produce ONE row keyed by `food_id`, not two rows keyed by display). The four regression tests at FR-008..FR-011 are unchanged. If the operator chooses NEITHER patch (test the system on the bug-free baseline), FR-002 acceptance criterion flips: the repro test PASSES from the start, FR-006 becomes a no-op, and FR-008..FR-011 form the entire deliverable as preventive regression coverage.

**Related**: FR-002, FR-006, FR-008, FR-009, FR-010, FR-011

### NC-002 — `different units do not merge` contract vs the unit-conversion behavior introduced by Mealie PR #7121

**Conflict**: Input section `步骤 4 回归测试` mandates `test_multiple_occurrences_different_units` to assert NO merge when two ingredients share the same food but use different units (e.g. `番茄 2 个` and `番茄 100g`). However, Mealie PR #7121 (commit `b5c089f5`) deliberately changed `ShoppingListService.can_merge` at `mealie/services/household_services/shopping_lists.py:57-68` so that two units WITH compatible `standard_unit` values DO merge via `UnitConverter().can_convert(...)`. `mealie/schema/recipe/recipe_ingredient.py:148-167` defines `standard_unit` as an optional field on `CreateIngredientUnit`, default `None`. A test that creates two units with `standard_unit=None` will hit the early-return at line 62/64 and NOT merge — matching the input contract. A test that creates units with compatible `standard_unit` values will merge — contradicting the input.

**Recommended default**: Honor input verbatim: define the contract as `same food + different unit_id + at least one unit lacks a non-empty standard_unit = NO merge`. The regression test at FR-010 creates both `IngredientUnit` rows with `standard_unit=None` (the schema default), exercising the early-return path at `mealie/services/household_services/shopping_lists.py:61-64`. The PR #7121 unit-conversion path remains supported and is exercised by the EXISTING tests at `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py:644-731` (not by this case). Rationale: (a) input takes precedence over shipped behavior; (b) the early-return path is the same one called when `food_id is None and unit_id differs`, so this test pins existing semantics; (c) any unit-conversion regression is already covered elsewhere.

**If rejected**: If the operator decides the PR #7121 unit-conversion contract must be preserved end-to-end, FR-010 must rename `test_multiple_occurrences_different_units` to `test_multiple_occurrences_different_units_no_convert` and explicitly document `standard_unit=None` in its title, plus add a SECOND test `test_multiple_occurrences_compatible_units_do_merge` that asserts merge with compatible `standard_unit` values. SC-005 threshold updates to 5 regression tests instead of 4.

**Related**: FR-010

### NC-003 — Wire shape of `same recipe appearing twice in the meal plan`: two `ShoppingListAddRecipeParamsBulk` entries vs one entry with `recipe_increment_quantity=2`

**Conflict**: Input section `产品场景` describes a user scheduling the same recipe on Monday dinner and Wednesday lunch, then clicking `Add Meal Plan to Shopping List`. Backend route `POST /households/shopping/lists/{item_id}/recipe` at `mealie/routes/households/controller_shopping_lists.py:256-261` accepts `list[ShoppingListAddRecipeParamsBulk]` (see `mealie/schema/household/group_shopping_list.py:288-295`). The frontend dialog `RecipeDialogAddToShoppingList.consolidateRecipesIntoSections` collapses duplicates into ONE bulk entry with a larger `recipeIncrementQuantity` before POST. A naive client that skips frontend consolidation, or a direct API caller, may send TWO entries each with `recipe_increment_quantity=1`. These two wire shapes exercise different code paths inside `bulk_create_items` (pass-1 in-memory consolidation vs pass-2 merge into existing rows).

**Recommended default**: The reproduction test at FR-002 MUST send TWO bulk entries, each with `recipe_increment_quantity=1`, to exercise the in-memory consolidation path at `mealie/services/household_services/shopping_lists.py:162-176`. The first multi-occurrence regression test at FR-009 (`test_multiple_occurrences_same_unit`) parametrizes BOTH wire shapes (two entries with `recipe_increment_quantity=1` AND one entry with `recipe_increment_quantity=2`) and asserts the same final shopping list state for both. Rationale: (a) the per-occurrence form is the highest-risk path (in-memory pass-1 must consolidate or pass-2 deduplicates against existing rows); (b) coverage of both forms protects against frontend-consolidation regressions; (c) the asserted final state — one row per `(food_id, unit_id)` with accumulated quantity — is identical in both shapes.

**If rejected**: If the operator restricts the reproduction to the frontend-pre-consolidated form only (one entry with `recipe_increment_quantity=2`), FR-002 acceptance criterion must replace the `recipe_increment_quantity=1` payload, FR-009 drops the per-occurrence parametrization, and SC-002 threshold updates from `2 wire shapes` to `1 wire shape`. The bug is still detectable because `get_shopping_list_items_from_recipe` at `shopping_lists.py:373` multiplies `ingredient.quantity * scale` and the resulting `ShoppingListItemCreate.quantity` still flows through the same `bulk_create_items` accumulation path, so the bug remains observable.

**Related**: FR-002, FR-009

## User Scenarios & Testing

### US-1 — User schedules the same recipe twice in a meal plan and the shopping list aggregates ingredient quantities (Priority: P1)

As a household user, when I schedule recipe X on Monday dinner and the same recipe X on Wednesday lunch in my meal plan, then add my meal plan to a shopping list, I see one row per `(food_id, unit_id)` whose quantity is the single-recipe amount times the number of occurrences. I do NOT see two separate rows for the same food, and I do NOT see one row with only the single-recipe amount.

**Why this priority**: This is the canonical user-visible symptom described in input section `产品场景` and `预期行为`. Without this fix the meal-plan-to-shopping-list flow under-counts or duplicates every repeated recipe, defeating the feature.

**Independent test**: Create a recipe with `番茄 quantity=2 unit=个` and `盐 quantity=1 unit=小勺`. Create two meal-plan entries on different dates pointing at this recipe. Add the planned recipes to a shopping list. Assert exactly one shopping list row for `番茄` with `quantity == 4`.

**Acceptance Scenarios**:

1. **Given** an authenticated household user, a recipe `R = (tomato qty=2 unit=each, salt qty=1 unit=tsp)`, and a freshly created shopping list, **When** the client first creates two `MealPlan` entries via `POST /api/households/mealplans` (one for Monday dinner referencing `R.id`, one for Wednesday lunch referencing `R.id`), then POSTs two `ShoppingListAddRecipeParamsBulk` entries (each `recipe_id=R.id`, `recipe_increment_quantity=1`) to `/api/households/shopping/lists/{list_id}/recipe`, **Then** the shopping list contains exactly one row for `food_id == tomato.id` with `unit_id == each.id` and `quantity == 4.0`; and exactly one row for `food_id == salt.id` with `unit_id == tsp.id` and `quantity == 2.0`
2. **Given** the same setup, **When** the same POST is made, **Then** the resulting shopping list row has exactly one `recipe_references` entry with `recipe_id == R.id` and `recipe_scale == 2.0` (consistent with `merge_items` recipe-scale accumulation at `mealie/services/household_services/shopping_lists.py:109-128`)
3. **Given** the same setup, **When** no other recipes have been added to the list, **Then** `len(shopping_list.list_items) == 2` — one row for tomato, one row for salt; no orphan rows

### US-2 — Engineer reproduces the bug with a failing pytest before applying the fix (Priority: P1)

As the engineer fixing the bug, I add a new pytest file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` with a reproduction test that mirrors the input user scenario: it first persists two `MealPlan` entries via `POST /api/households/mealplans` (one per occurrence), then triggers the meal-plan→shopping-list conversion via `POST /api/households/shopping/lists/{list_id}/recipe`. The test MUST FAIL on the bug-injected baseline (or pre-fix code) and PASS once the minimum-scope fix lands. This proves the bug existed and that the fix addresses it.

**Why this priority**: Mandatory per input `步骤 1 复现`. The bug-fix workflow is test-first: a failing repro is required evidence before any production code change is reviewed or merged.

**Independent test**: On the bug-injected branch, run `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients`. Expect FAIL. Apply the FR-006 minimum-scope fix. Re-run. Expect PASS.

**Acceptance Scenarios**:

1. **Given** the bug-injected branch (per NC-001), **When** the reproduction test executes, **Then** the test FAILS with an assertion message that names the observed wrong state (either `quantity != 4` or `len(list_items) != 2`) so the failure points at the underlying defect
2. **Given** the same bug-injected branch with the FR-006 fix applied, **When** the reproduction test executes, **Then** the test PASSES and the assertion at US-1 first acceptance criterion holds end-to-end

### US-3 — Engineer documents the root cause in the PR description (Priority: P1)

As the engineer fixing the bug, I include a `Root Cause Analysis` section in my PR description that names the buggy function, identifies whether the defect is a wrong merge key or a quantity overwrite, and enumerates the boundary cases (different units, different food_ids with the same display name) that the fix preserves.

**Why this priority**: Mandatory per input `步骤 2 根因定位` and the `Spec/Coding/CR` evaluation table. A bug fix without root-cause documentation cannot be reviewed for correctness or regression risk.

**Independent test**: Inspect the PR description. Confirm presence of a `Root Cause Analysis` (or equivalently-named) section that answers all four questions in input `步骤 2`: which function, whether the defect is wrong merge key or overwrite, what role each boundary plays.

**Acceptance Scenarios**:

1. **Given** the open PR, **When** the description is read, **Then** a `Root Cause Analysis` section names `ShoppingListService.merge_items` at `mealie/services/household_services/shopping_lists.py:73-128` (variant A) or `ShoppingListService.can_merge` at `mealie/services/household_services/shopping_lists.py:45-71` (variant B) as the locus of the bug, classifies the defect (quantity overwrite vs wrong merge key), and explicitly states the merge-key invariant: `(food_id, unit_id)` for items with a `food_id`, falling back to `note` only when `food_id is None`
2. **Given** the same PR description, **When** boundary cases are reviewed, **Then** the description explicitly addresses: (a) different units same food should NOT merge unless `standard_unit` allows conversion; (b) different `food_id` with same display name should NOT merge

### US-4 — Engineer ships a minimum-scope fix without refactoring neighbouring code (Priority: P1)

As the engineer fixing the bug, I modify only the smallest set of lines required to make the failing reproduction test pass, restricted to `mealie/services/household_services/shopping_lists.py`. I do NOT refactor `bulk_update_items`, `remove_recipe_ingredients_from_list`, `get_shopping_list_items_from_recipe`, or any of the neighbouring service methods.

**Why this priority**: Mandatory per input `步骤 3 最小修复` and `实现约束`. Broad refactors increase regression surface and obscure the actual fix. The reviewer must be able to see the before-and-after of the defect in 1-3 functions.

**Independent test**: Inspect the diff. Confirm production-code changes are confined to `mealie/services/household_services/shopping_lists.py` and to the function(s) named in US-3. Confirm no changes to `mealie/db/models/`, `mealie/schema/`, or `mealie/routes/`.

**Acceptance Scenarios**:

1. **Given** the PR diff, **When** production-code files are listed, **Then** the only modified file under `mealie/` is `mealie/services/household_services/shopping_lists.py`, and the diff inside that file is bounded to at most 2 functions among `can_merge` (lines 45-71) and `merge_items` (lines 73-128)
2. **Given** the same diff, **When** changes are counted, **Then** the net production-code line delta is at most 5 added lines and 5 removed lines (excluding whitespace-only, comment-only, and import-only lines)
3. **Given** the same diff, **When** no feature flag or configuration toggle is added per input `实现约束`, **Then** no new field appears in `AppSettings` or in any configuration schema, and no environment-variable branch is introduced into the bug-affected functions

### US-5 — Engineer ships the four named regression tests covering the merge-key boundary conditions (Priority: P1)

As the engineer fixing the bug, I add four named regression tests to the same test file as the reproduction test: `test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, and `test_different_food_same_name`. These pin the merge-key invariant against future refactors.

**Why this priority**: Mandatory per input `步骤 4 回归测试`. These four tests exhaustively cover the merge-key axes (occurrence count, unit identity, food identity) and prevent the two known bug-injection variants from regressing silently.

**Independent test**: Run `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py -v`. Confirm all five new tests pass: the repro + the four regressions. Confirm test ids match the input contract names.

**Acceptance Scenarios**:

1. **Given** the test file added by FR-007, **When** the four regression tests run on post-fix code, **Then** all four named tests (`test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`) pass with exit code 0
2. **Given** the same test file, **When** running with `pytest --collect-only`, **Then** the four regression tests are collected by id and located in the same module as the reproduction test

### US-6 — All 537 pre-existing pytest tests continue to pass after the fix (Priority: P1)

As the engineer fixing the bug, I keep every pre-existing pytest test green. The fix touches only the documented merge/accumulate path; no schema, no migration, no route, no fixture change is required.

**Why this priority**: Mandatory per task `ALL existing 537 pytest tests must still pass after your work`. The bug fix has zero tolerance for collateral regressions in the existing test suite.

**Independent test**: Run `task py:test` (which invokes `uv run pytest tests/`). Confirm 537 pre-existing tests plus the 5 new tests (1 repro + 4 regressions) report PASS / no FAIL / no ERROR. Track the baseline count before applying the fix to confirm the 537 figure.

**Acceptance Scenarios**:

1. **Given** the baseline test count of 537 pre-existing tests, **When** `task py:test` is run on post-fix code, **Then** the run reports exactly 537 + 5 = 542 collected tests, with zero FAIL and zero ERROR results
2. **Given** the same run, **When** the closest existing regression tests are inspected — `test_shopping_lists_add_recipes_with_merge` at `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` and `test_shopping_lists_add_recipe_with_merge`, **Then** both pre-existing merge tests pass, confirming the fix did not regress the closest-precedent behavior fixed by PR #5054

## Requirements

### Functional Requirements

- **FR-001** [FR]: The bug fix MUST be scoped to the household shopping-list service module at `mealie/services/household_services/shopping_lists.py`. Specifically, the candidate buggy functions are `ShoppingListService.can_merge` (lines 45-71) and `ShoppingListService.merge_items` (lines 73-128). The PR description identifies which of these is the actual locus of the defect per NC-001 (variant A = `merge_items`, variant B = `can_merge`).
  - Code references: `mealie/services/household_services/shopping_lists.py` L45-71, 73-128 (can_merge, merge_items)
  - Related: US-3, US-4
- **FR-002** [FR]: A new pytest module at `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` MUST contain a reproduction test named `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` that (1) creates a recipe with two food-ingredients each having `food_id` and `unit_id` set, (2) persists two `MealPlan` entries on different ISO dates for the same recipe via `POST /api/households/mealplans` (mirroring `test_create_mealplan_with_recipe` at `tests/integration_tests/user_household_tests/test_group_mealplan.py:80-99` — the meal-plan POST is a required step per input `产品场景`, not a stylistic option), (3) POSTs two `ShoppingListAddRecipeParamsBulk` entries (one per occurrence, each `recipe_increment_quantity=1`) to `/api/households/shopping/lists/{list_id}/recipe`, and (4) asserts the shopping list contains exactly one row per `(food_id, unit_id)` whose `quantity` equals the single-recipe `quantity` multiplied by the number of occurrences. This test MUST FAIL on the bug-injected baseline per NC-001.
  - Code references: `mealie/routes/households/controller_shopping_lists.py` L256-261 (add_recipe_ingredients_to_list), `mealie/schema/household/group_shopping_list.py` L288-295 (ShoppingListAddRecipeParams, ShoppingListAddRecipeParamsBulk), `tests/integration_tests/user_household_tests/test_group_mealplan.py` L80-99 (test_create_mealplan_with_recipe)
  - Related: US-1, US-2
- **FR-003** [FR]: The new test module MUST authenticate via the existing `unique_user` fixture and post recipes/meal-plans/shopping-list mutations through the `api_client` fixture, matching the conventions of `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` (see `test_shopping_lists_add_recipes_with_merge` at lines 663-739) and `tests/integration_tests/user_household_tests/test_group_mealplan.py` (see `test_create_mealplan_with_recipe` at lines 80-99). No bespoke fixtures or session-state shortcuts are permitted.
  - Code references: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` L663-739 (test_shopping_lists_add_recipes_with_merge), `tests/integration_tests/user_household_tests/test_group_mealplan.py` L80-99 (test_create_mealplan_with_recipe), `tests/fixtures/fixture_shopping_lists.py` L49-65 (shopping_list)
  - Related: US-2, US-5
- **FR-004** [FR]: Food and unit creation in the new test module MUST use the Mealie schemas `SaveIngredientFood` (at `mealie/schema/recipe/recipe_ingredient.py:98-99`) and `SaveIngredientUnit` (at `mealie/schema/recipe/recipe_ingredient.py:170-171`), with `group_id` set to `unique_user.group_id`. Units created for the `different units do not merge` regression test in FR-010 MUST leave `standard_unit` at its default `None` (per `CreateIngredientUnit` at `mealie/schema/recipe/recipe_ingredient.py:148-167`), so the early-return branch at `mealie/services/household_services/shopping_lists.py:61-64` fires and `UnitConverter` is not consulted (per NC-002).
  - Code references: `mealie/schema/recipe/recipe_ingredient.py` L98-99, 148-171 (SaveIngredientFood, CreateIngredientUnit, SaveIngredientUnit, standard_unit), `mealie/services/household_services/shopping_lists.py` L45-71 (can_merge)
  - Related: US-5
- **FR-005** [FR]: Shopping-list assertions in the new test module MUST key the `expected row` lookup on `(food_id, unit_id)` and MUST NOT key on `display`, `note`, or any other derived string. Each assertion MUST verify both `quantity` and `recipe_references` shape (at least one entry per recipe appearance, with `recipe_scale` matching the occurrence count per the `merge_items` behavior at `mealie/services/household_services/shopping_lists.py:109-128`).
  - Code references: `mealie/services/household_services/shopping_lists.py` L73-128 (merge_items), `mealie/db/models/household/shopping_list.py` L51-98 (ShoppingListItem, food_id, unit_id, quantity, recipe_references)
  - Related: US-1, US-5
- **FR-006** [FR]: The minimum-scope fix MUST restore the documented `(food_id, unit_id)` merge-key invariant and the additive quantity accumulation at `mealie/services/household_services/shopping_lists.py:73-128`. For NC-001 variant A, the fix changes line 96 back to `to_item.quantity += from_item.quantity` (additive sum). For NC-001 variant B, the fix restores the `can_merge` predicate at lines 45-71 to reject by `food_id` difference (line 52) and use `(food_id, unit_id)` as the effective key, with `note` only consulted when `item1.food_id` is falsy at line 71. Diff is restricted to `mealie/services/household_services/shopping_lists.py`.
  - Code references: `mealie/services/household_services/shopping_lists.py` L45-71, 73-128 (can_merge, merge_items)
  - Related: US-2, US-3, US-4
- **FR-007** [FR]: The PR description MUST contain a `Root Cause Analysis` section (or equivalently titled section) that answers all four questions enumerated in input `步骤 2 根因定位`: (a) which function holds the defect; (b) whether the defect is a wrong merge key or a quantity overwrite; (c) how `different unit` boundary is handled by `can_merge` lines 57-68 (no merge unless both units have `standard_unit`); (d) how `different food, same display name` boundary is handled by `can_merge` line 52 (different `food_id` never merge).
  - Code references: `mealie/services/household_services/shopping_lists.py` L45-71 (can_merge, food_id, unit_id, standard_unit)
  - Related: US-3
- **FR-008** [FR]: The new test module MUST include a regression test named `test_single_occurrence` that creates a recipe with two food-ingredients and adds it to a shopping list with `recipe_increment_quantity=1`. The test MAY skip the `POST /api/households/mealplans` step because this regression validates the single-occurrence quantity invariant on the bulk-add path itself, which is independent of meal-plan persistence. Each shopping list row MUST have `quantity == recipe_ingredient.quantity` (no doubling, no rounding); exactly one row per `(food_id, unit_id)`.
  - Code references: `mealie/services/household_services/shopping_lists.py` L154-223, 413-455 (bulk_create_items, add_recipe_ingredients_to_list)
  - Related: US-5
- **FR-009** [FR]: The new test module MUST include a regression test named `test_multiple_occurrences_same_unit` that creates a recipe, then persists N `MealPlan` entries (N parametrized to 2 and 3) for the same recipe via `POST /api/households/mealplans`, and asserts the final shopping list has exactly one row per `(food_id, unit_id)` with `quantity == base_quantity * N`. Per NC-003 the test MUST parametrize the wire shape (preferred idiom: `@pytest.mark.parametrize` decorator with two cases, matching the convention in `tests/integration_tests/user_recipe_tests/test_recipe_ingredients.py:177-234`): one case sends N separate `ShoppingListAddRecipeParamsBulk` entries with `recipe_increment_quantity=1`, another sends ONE entry with `recipe_increment_quantity=N`. Both cases MUST assert the same final state.
  - Code references: `mealie/services/household_services/shopping_lists.py` L154-223, 323-411 (bulk_create_items, get_shopping_list_items_from_recipe), `mealie/schema/household/group_shopping_list.py` L288-295 (ShoppingListAddRecipeParams, ShoppingListAddRecipeParamsBulk), `tests/integration_tests/user_household_tests/test_group_mealplan.py` L80-99 (test_create_mealplan_with_recipe)
  - Related: US-5
- **FR-010** [FR]: The new test module MUST include a regression test named `test_multiple_occurrences_different_units` that creates two `IngredientUnit` rows with distinct ids and `standard_unit=None` (per NC-002 and FR-004), builds two recipes that each reference the SAME food but DIFFERENT units, adds both to a shopping list, and asserts the list contains TWO rows for that food — one per `unit_id` — each with its own un-merged `quantity`. The test MUST verify the early-return at `mealie/services/household_services/shopping_lists.py:61-64` by inspecting the resulting row count. The test MAY skip the `POST /api/households/mealplans` step because this regression validates the `can_merge` unit-mismatch invariant on the bulk-add path itself, which is independent of meal-plan persistence.
  - Code references: `mealie/services/household_services/shopping_lists.py` L45-71 (can_merge), `mealie/schema/recipe/recipe_ingredient.py` L148-167 (CreateIngredientUnit, standard_unit)
  - Related: US-5
- **FR-011** [FR]: The new test module MUST include a regression test named `test_different_food_same_name` that creates two `IngredientFood` rows with DIFFERENT ids but the SAME `name` string, places each on a separate recipe (same unit), adds both to a shopping list, and asserts the list contains TWO rows keyed by distinct `food_id` values with the same display name — proving that `can_merge` keys off `food_id` (line 52) and NOT off `display`. The test MAY skip the `POST /api/households/mealplans` step because this regression validates the `can_merge` food-identity invariant on the bulk-add path itself, which is independent of meal-plan persistence.
  - Code references: `mealie/services/household_services/shopping_lists.py` L45-71 (can_merge, food_id), `mealie/schema/recipe/recipe_ingredient.py` L98-99 (SaveIngredientFood)
  - Related: US-5
- **FR-012** [FR]: The post-fix test run MUST keep all 537 pre-existing pytest tests passing. In particular the closest-precedent tests `test_shopping_lists_add_recipes_with_merge` at `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` and `test_shopping_lists_add_recipe_with_merge` at `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:581-660` MUST continue to pass without modification.
  - Code references: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` L581-660, 663-739 (test_shopping_lists_add_recipe_with_merge, test_shopping_lists_add_recipes_with_merge)
  - Related: US-6
- **FR-013** [NFR]: The fix MUST NOT introduce any new feature flag, configuration setting, environment variable, schema field, API route, or Alembic migration. The change is confined to production code under `mealie/services/household_services/shopping_lists.py` and to new test code under `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` (per input `实现约束`).
  - Code references: `mealie/services/household_services/shopping_lists.py` L1-50 (ShoppingListService)
  - Related: US-4
- **FR-014** [NFR]: All ID-bearing fields used in shopping-list assertions (`food_id`, `unit_id`, `recipe_id`, `shopping_list_id`) MUST be compared as UUID values (via `UUID4` round-trip or string comparison after `str(uuid)`). Tests MUST NOT compare against `note` for items where `food_id` is set, because `merge_items` mutates `note` by concatenating with ` | ` at `mealie/services/household_services/shopping_lists.py:98-104`.
  - Code references: `mealie/services/household_services/shopping_lists.py` L73-104 (merge_items, note), `mealie/db/models/household/shopping_list.py` L55-90 (ShoppingListItem, food_id, unit_id, shopping_list_id)
  - Related: US-5
- **FR-015** [NFR]: The post-fix codebase MUST keep float comparisons in the new tests tolerant: shopping-list assertions on `quantity` MUST use either exact equality for integer-valued sums (e.g. `2 + 2 == 4.0`) or `pytest.approx(...)` with an absolute tolerance of at most `1e-6` for non-integer sums, matching the existing pattern at `mealie/schema/recipe/recipe_ingredient.py:23` (`INGREDIENT_QTY_PRECISION = 3`).
  - Code references: `mealie/schema/recipe/recipe_ingredient.py` L20-30 (INGREDIENT_QTY_PRECISION)
  - Related: US-5

## Success Criteria

- **SC-001**: The fix is localized to one source file: `mealie/services/household_services/shopping_lists.py`. No other production code file under `mealie/` is modified.
  - Metric: count of modified production files (paths matching `mealie/**.py` excluding `mealie/tests/**` and `tests/**`) in the PR diff | Threshold: exactly 1 file modified
- **SC-002**: The reproduction test fails on the bug-injected baseline and passes on post-fix code, demonstrating both the bug and the fix.
  - Metric: exit code of `task py:test -- tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` on bug-injected branch (expect non-zero / FAIL) and on post-fix branch (expect zero / PASS) | Threshold: non-zero exit on bug-injected branch AND zero exit on post-fix branch
- **SC-003**: The new test module relies only on existing pytest fixtures (`unique_user`, `api_client`, `shopping_list`) and the existing api-routes module; no new fixtures or conftest changes.
  - Metric: presence of new fixture declarations in conftest.py, tests/fixtures/, or in the new test module; new entries in tests/utils/api_routes/__init__.py | Threshold: 0 new fixture declarations and 0 new api-route helpers
- **SC-004**: Production-code line delta is small: at most 5 added and 5 removed non-comment, non-blank lines inside `shopping_lists.py`.
  - Metric: git diff --numstat on `mealie/services/household_services/shopping_lists.py` after stripping blank-only and comment-only lines | Threshold: added <= 5 AND removed <= 5 lines
- **SC-005**: All four named regression tests (`test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`) plus the reproduction test exist in the new test module and pass on post-fix code.
  - Metric: count of passing tests matched by node ids `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_*` | Threshold: exactly 5 passing tests with the required names (1 repro + 4 regressions)
- **SC-006**: The PR description contains a Root Cause Analysis section that answers the four questions from input `步骤 2`.
  - Metric: presence of a heading `Root Cause Analysis` (or equivalently titled section) plus prose answering: (a) function name, (b) defect classification, (c) different-unit handling, (d) different-food handling | Threshold: section exists AND answers 4-of-4 questions
- **SC-007**: The full pre-existing pytest suite continues to pass after the fix.
  - Metric: result counts from `task py:test` on post-fix code vs the same `task py:test` invocation captured on the bug-injected baseline immediately prior (BASELINE_COLLECTED = collected count BEFORE the new test module is added): collected, passed, failed, error | Threshold: post-fix `collected == BASELINE_COLLECTED + 5` AND `failed == 0` AND `error == 0` (baseline-relative form so the threshold is invariant to upstream Mealie test additions; per input `约束` the BASELINE_COLLECTED value is 537 at the time of writing)

## Key Entities

- **ShoppingListItem**: Database row representing one line on a household shopping list. Merge key in code is `(food_id, unit_id)` for items with a food, falling back to `note` when `food_id is None`. Persisted via SQLAlchemy `Float` for quantity (no Decimal).
  - Fields: id: UUID4, shopping_list_id: UUID4, food_id: UUID4 | None, unit_id: UUID4 | None, label_id: UUID4 | None, quantity: float | None, note: str | None, checked: bool, position: int, recipe_references: list[ShoppingListItemRecipeReference]
  - References: ShoppingListItemRecipeReference, IngredientFood, IngredientUnit
- **ShoppingListItemRecipeReference**: Link row between a shopping list item and a recipe. Records `recipe_quantity` (the ingredient quantity at scale=1) and `recipe_scale` (the number of times this recipe contributed). When the same recipe is consolidated into one item, `merge_items` sums `recipe_scale` per `recipe_id`.
  - Fields: id: UUID4, shopping_list_item_id: UUID4, recipe_id: UUID4 | None, recipe_quantity: float (NOT NULL), recipe_scale: float (default 1), recipe_note: str | None
  - References: ShoppingListItem, RecipeModel
- **ShoppingListAddRecipeParamsBulk**: Pydantic request schema for `POST /api/households/shopping/lists/{item_id}/recipe`. Carries `recipe_id`, optional `recipe_increment_quantity` (default 1.0), and optional `recipe_ingredients` override. Two meal-plan occurrences of the same recipe can be expressed as two entries or one entry with `recipe_increment_quantity=2`.
  - Fields: recipe_id: UUID4, recipe_increment_quantity: float = 1, recipe_ingredients: list[RecipeIngredient] | None = None
  - References: ShoppingListAddRecipeParams, RecipeIngredient
- **IngredientUnit**: Pydantic schema for a recipe ingredient unit. Has an optional `standard_unit` field that controls whether `can_merge` will consult `UnitConverter` for conversion-based merging. Tests for the `different units no merge` invariant must use `standard_unit=None`.
  - Fields: id: UUID4, name: str, standard_unit: str | None = None, standard_quantity: float | None = None
  - References: CreateIngredientUnit, UnitConverter
- **IngredientFood**: Pydantic schema for a recipe ingredient food. Two foods can share the same human-readable `name` but have distinct `id` (UUID) values. `can_merge` keys off `food_id`, so two foods with the same `name` but different `id` never merge.
  - Fields: id: UUID4, name: str, label_id: UUID4 | None, group_id: UUID4
  - References: CreateIngredientFood, SaveIngredientFood

## Edge Cases

- Recipe with internal duplicate ingredients (same food, same unit appearing twice in `recipe_ingredient`) gets pre-merged inside `get_shopping_list_items_from_recipe` at `mealie/services/household_services/shopping_lists.py:387-409` by adding raw `ingredient.quantity` (not `ingredient.quantity * scale`). → OUT OF SCOPE for this minimum fix: input `实现约束` forbids refactoring neighbouring code. The scaled-internal-duplicate path stays untouched; if a future case requires it, raise a separate ticket.
- Same recipe sent in two `ShoppingListAddRecipeParamsBulk` entries with `recipe_increment_quantity=1` vs sent as one entry with `recipe_increment_quantity=2`. Both forms hit different paths inside `bulk_create_items` (pass-1 in-memory consolidation vs single-pass scaling). → FR-009 parametrizes both wire shapes and asserts the same final shopping-list state. The pass-1 in-memory consolidation at `mealie/services/household_services/shopping_lists.py:162-176` must produce one accumulated row in the two-entry shape; the single-entry shape produces the same row via `get_shopping_list_items_from_recipe` scaling at `mealie/services/household_services/shopping_lists.py:373`.
- Checked rows MUST NEVER merge with new unchecked rows, even for the same food/unit combo (per `can_merge` lines 48-55). → Preserved by the fix: `can_merge` retains the early-return on `item1.checked or item2.checked`. No regression test in this case explicitly covers this — it is exercised by the existing test `test_shopping_lists_add_recipes_with_merge` and broader merge tests at `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py`.
- Items with `food_id is None` fall back to merging by `note`. Two ingredients both lacking `food_id` and sharing the same `note` SHOULD merge. → Preserved by the fix: `can_merge` line 71 returns `bool(item1.food_id) or item1.note == item2.note`. Existing test `test_shopping_lists_add_recipes_with_merge` covers this path (note-only common ingredient). No new regression test is added because input scope is `food + unit` rows.
- Float quantity sums may drift slightly when N is not an integer (e.g. `recipe_increment_quantity=0.5` plus `recipe_increment_quantity=0.5` summing to `0.999999...`). → Mitigated by FR-015: float assertions in the new tests use `pytest.approx(abs=1e-6)` for non-integer sums. Integer-valued occurrence counts (1, 2, 3) are exact in IEEE 754.
- PR #5054 (commit `716c85cc`, fixed issue #3417 `shopping list items of the same type are not consolidated`) is the closest precedent. The case-3 fix must preserve the post-#5054 bulk-add consolidation contract. → FR-012 explicitly mandates that `test_shopping_lists_add_recipes_with_merge` and `test_shopping_lists_add_recipe_with_merge` continue to pass post-fix. SC-007 measures full-suite green.
- If the baseline does NOT contain the bug (`merge_items` line 96 is already `+=`), the reproduction test PASSES from the start and the operator must inject the bug per NC-001. → NC-001 explicitly enumerates two injection variants and directs the operator to apply variant A on an `inject-bug` branch before letting the implementer run the workflow.
- The frontend dialog `RecipeDialogAddToShoppingList.consolidateRecipesIntoSections` may collapse duplicate recipes into one POST entry. A regression in the frontend that bypasses consolidation would route per-occurrence entries to the backend. → FR-009 covers both wire shapes; SC-005 verifies. No frontend code change in this case (per FR-013).

## Assumptions

- The Mealie baseline at `C:\Users\v-liyuanjun\Downloads\mealie` is the `devloop-baseline` commit referenced by the exploration consolidated.md, with `shopping_lists.py` at 554 lines and the `can_merge`/`merge_items` symbols at the documented line ranges.
- The injection variant A (per NC-001) is applied on an `inject-bug` branch before the implementer runs the workflow. The implementer reverts variant A as the minimum-scope fix.
- Pre-existing pytest baseline count is exactly 537 (per task prompt). This is verified by `task py:test --collect-only` on the pre-fix branch.
- `task py:test` (which runs `uv run pytest`) is the canonical test invocation per Mealie's `Taskfile.yml`. The same command is used for both the baseline 537-count check and the post-fix green check.
- The `unique_user` fixture creates an authenticated user with a scoped `repos` attribute that exposes `ingredient_foods`, `ingredient_units`, and `recipes` for creating test data, per `tests/fixtures/fixture_users.py` lines 179-226.
- All 5 new tests run synchronously inside the existing `api_client` TestClient fixture; no async event loop, no separate process, no new conftest hooks.
- Pre-existing PR #7121 (commit `b5c089f5`) unit-conversion behavior remains the shipped contract for items with `standard_unit` set. The new regression tests deliberately avoid that path by setting `standard_unit=None`.

## Out of Scope

- Recipe scale (`recipe_increment_quantity != 1`) with internal duplicate ingredients in the same recipe: the scaling bug at `get_shopping_list_items_from_recipe` lines 393-397 (per consolidated.md section C5) is documented but not fixed in this case.
- Unit conversion merging via `UnitConverter` when both units have compatible `standard_unit`: covered by existing test `test_group_shopping_list_items.py` lines 644-731; not exercised by the new tests (per NC-002).
- Frontend changes: no edit to `frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue` or `consolidateRecipesIntoSections`. Both per-occurrence and pre-consolidated wire shapes are accepted by the backend.
- Concurrent POST race conditions: the closest-precedent fix (PR #5054, commit `716c85cc`) already bulk-consolidates before persistence; no new locking, advisory lock, or upsert behaviour added.
- Cross-household recipe lookup widening (PR #5892, `6cbc308d`): preserved as-is; out-of-scope for this case.
- Database migration / Alembic revision: zero schema changes. All persisted columns (`food_id`, `unit_id`, `quantity`, `note`, `recipe_scale`) are pre-existing.
- Removing or deprecating the legacy single-recipe POST route at `mealie/routes/households/controller_shopping_lists.py:263-272`: it remains `deprecated=True` but untouched.
- Removal of `is_food`/`is_ingredient` deprecated columns on `ShoppingListItem` (per PR #5684, `245ca5fe`): not affected by the case-3 fix.

## Self-Concerns (writer self-reflection)

- **FR-009**: The two parametrized wire shapes (`recipe_increment_quantity=1` repeated N times vs `recipe_increment_quantity=N` once) exercise different internal paths but assert identical final state. If a future regression splits behaviour between the two shapes (e.g. recipe-scale accumulation differs), this test may stop being trivially equivalent.
  - Evidence gap: No existing test parametrizes the wire shape; `test_shopping_lists_add_recipes_with_merge` only exercises two distinct recipes with shared ingredients. The behaviour of `recipe_references[0].recipe_scale` under each shape is validated only by reading `merge_items` lines 109-128.
  - Suggested resolution: Keep both shapes in FR-009 as documented. If they diverge in a future Mealie release, the test will fail and surface the change clearly.
- **Edge case 3 (checked-state isolation)**: The new test module does not add an explicit regression for the `checked != checked` early-return at `can_merge` lines 48-55. A future writer might mistakenly remove this guard while pursuing the merge-key invariant.
  - Evidence gap: Coverage is provided by existing tests in `test_group_shopping_list_items.py`, but those tests are not co-located with the new repro file, so a writer modifying `shopping_lists.py` could miss the cross-file regression signal.
  - Suggested resolution: Rely on the existing suite for now (per FR-012 / SC-007). If FR-006 ends up touching `can_merge`, the implementer should manually run the closest-precedent merge tests before submitting.
- **SC-007 threshold**: The 537 baseline count comes from the task prompt. If Mealie's pytest collection drifts between the task author's snapshot and the implementer's local environment, the `exactly 542` assertion may need to flex by 1-2.
  - Evidence gap: No deterministic `--collect-only` output is shipped with the spec; the 537 figure is taken as given from the task instructions.
  - Suggested resolution: Treat 537 as `baseline_count` and assert `collected == baseline_count + 5 AND failed == 0 AND error == 0`. If the baseline drifts upstream, update the comparison to the fresh `--collect-only` snapshot.

---

_Generated by DevLoop spec phase — writer=claude-sonnet-4.6, reviewer=self-review (4-axis rubric, validator-checked), iterations=2_