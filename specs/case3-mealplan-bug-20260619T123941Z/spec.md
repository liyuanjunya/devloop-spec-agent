# Spec — Case 3: Meal Plan → Shopping List Consolidation Bug Fix

> Generated from `input.md`, `intent/confirmed.json`, `exploration/consolidated.md`, `approach/selected.md`. All code references verified in `C:\Users\v-liyuanjun\Downloads\mealie\`.

## Metadata

- **Spec ID**: `case3-mealplan-bug-20260619T123941Z/spec-v1`
- **Intent type**: `bug_fix`
- **Scope**: `service` (single function in `mealie/services/household_services/shopping_lists.py`) + `test` (new integration test file)
- **Selected approach**: Conservative — smallest patch inside `can_merge` and/or `merge_items` (see `approach/selected.md`).
- **Target file under repair**: `mealie/services/household_services/shopping_lists.py`
- **New test file**: `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`
- **No schema / migration / controller / repository changes.**

---

## Problem statement

When a Mealie user schedules the same recipe in multiple meal-plan slots within a week (e.g. Monday dinner = recipe A, Wednesday lunch = recipe A) and then triggers the "Add Meal Plan to Shopping List" UI action, the resulting shopping list must contain exactly one row per `(food_id, unit_id)` whose `quantity` equals the recipe's per-ingredient quantity times the number of occurrences. Today, this invariant is violated in one of two equivalent ways: either the row appears once with the single-recipe quantity (lost accumulation), or it appears multiple times unmerged (lost consolidation). Both symptoms indicate a defect in `ShoppingListService.can_merge` (`mealie/services/household_services/shopping_lists.py:45-71`) or `ShoppingListService.merge_items` (`mealie/services/household_services/shopping_lists.py:73-128`).

The frontend "Add Meal Plan to Shopping List" action has no dedicated backend route; it gathers the planned recipes and calls `POST /api/households/shopping/lists/{item_id}/recipe` (`mealie/routes/households/controller_shopping_lists.py:256-261`) with a `list[ShoppingListAddRecipeParamsBulk]` payload, which delegates to `ShoppingListService.add_recipe_ingredients_to_list` (`mealie/services/household_services/shopping_lists.py:413-455`) and then to `ShoppingListService.bulk_create_items` (`:154-223`).

---

## User stories

### US-1 — 复现 (Reproduce)

**As** a Mealie developer fixing this bug, **I want** an integration test that reliably reproduces the meal-plan-to-shopping-list consolidation failure, **so that** the regression cannot recur silently and the fix has a measurable acceptance signal.

**Acceptance criteria**:
- A new test file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` exists.
- The test `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients`:
  1. Creates `food_tomato` and `food_egg` via `unique_user.repos.ingredient_foods.create(SaveIngredientFood(name=..., group_id=unique_user.group_id))` (pattern: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:258-278`).
  2. Creates two units via `unique_user.repos.ingredient_units.create(SaveIngredientUnit(name="each", group_id=unique_user.group_id))` and `SaveIngredientUnit(name="tsp", group_id=unique_user.group_id)` with `standard_unit=None` (default — confirmed at `mealie/schema/recipe/recipe_ingredient.py:155-156`) to avoid `UnitConverter` interference.
  3. Creates `recipe_a` via `unique_user.repos.recipes.create(Recipe(...))` with `recipe_ingredient=[RecipeIngredient(food=food_tomato, unit=unit_each, quantity=2.0, note=food_tomato.name), RecipeIngredient(food=food_salt, unit=unit_tsp, quantity=1.0, note=food_salt.name)]` (pattern: `tests/fixtures/fixture_recipe.py:31-49`).
  4. Creates two meal-plan entries via `POST /api/households/mealplans` (`tests/utils/api_routes/__init__.py:92`) with `CreatePlanEntry(date=monday, entry_type="dinner", recipe_id=recipe_a.id).model_dump(by_alias=True)` and `CreatePlanEntry(date=wednesday, entry_type="lunch", recipe_id=recipe_a.id).model_dump(by_alias=True)` (pattern: `tests/integration_tests/user_household_tests/test_group_mealplan.py:80-99`).
  5. Acquires the destination shopping list from the `shopping_list` fixture (`tests/fixtures/fixture_shopping_lists.py:49-65`).
  6. POSTs `[ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id), ShoppingListAddRecipeParamsBulk(recipe_id=recipe_a.id)]` (two entries, mirroring per-occurrence frontend serialization) to `api_routes.households_shopping_lists_item_id_recipe(shopping_list.id)` (`tests/utils/api_routes/__init__.py:415-417`) using `utils.jsonify([... .model_dump()])`.
  7. GETs the shopping list and asserts exactly one item per food: `tomato` quantity equals `4.0` (within `1e-6`), with `unit_id == unit_each.id` and `food_id == food_tomato.id`; `salt` quantity equals `2.0` with `unit_id == unit_tsp.id` and `food_id == food_salt.id`; total `len(listItems) == 2`.
- This test FAILS on the buggy revision and PASSES after the US-3 fix.

### US-2 — 根因 (Root-cause analysis)

**As** a code reviewer, **I want** the PR description to contain a structured root-cause analysis, **so that** the failure mode, fix location, and adjacent contract are documented for future maintainers.

**Acceptance criteria**:
- The PR description contains a `### Root cause` section that answers, verbatim and in order:
  1. **Which function holds the bug?** Names the exact path + symbol, e.g. `mealie/services/household_services/shopping_lists.py::ShoppingListService.merge_items` (line 96) OR `…::ShoppingListService.can_merge` (lines 45-71). Cites the line number(s) actually changed.
  2. **Wrong merge key or quantity overwrite vs. accumulate?** States explicitly whether the defect is (a) `merge_items` line 96 using `=` instead of `+=`, or (b) `can_merge` using `display` / `note` as the primary key instead of `food_id`. References input.md附录 to label the variant (A vs B).
  3. **Boundary cases**, covering each of: same `food_id` + same `unit_id` ⇒ merge with sum; same `food_id` + different `unit_id` with both `standard_unit is None` ⇒ no merge; different `food_id` even with same display ⇒ no merge; `food_id is None` ⇒ merge falls back to `note` equality (`can_merge` line 71); `recipe_scale` accumulation through `merge_items` lines 109-126 yields one `recipe_references` entry with `recipe_scale == N` when the same `recipe_id` is added N times.
- The PR description references the file paths and line numbers above so the reviewer can navigate to the exact code.

### US-3 — 最小修复 (Minimum-scope fix)

**As** a Mealie maintainer, **I want** a 1-2 line surgical patch inside `mealie/services/household_services/shopping_lists.py` that restores the canonical `(food_id, unit_id)` merge key and the `to_item.quantity += from_item.quantity` accumulation, **so that** the reproduction passes and no other behavior is affected.

**Acceptance criteria**:
- Only `mealie/services/household_services/shopping_lists.py` is modified. No other production file changes.
- Diff is confined to `ShoppingListService.can_merge` (lines 45-71) and/or `ShoppingListService.merge_items` (lines 73-128). No new methods, no extracted helpers, no signature changes, no schema changes.
- The non-unit-converted branch at line 96 contains `to_item.quantity += from_item.quantity` (NOT `=`).
- `can_merge` rejects items with `item1.food_id != item2.food_id` (line 52) and uses `bool(item1.food_id) or item1.note == item2.note` as the final return (line 71); `display` is NOT used as a merge key anywhere.
- `bulk_create_items` (lines 154-223), `bulk_update_items` (lines 225-310), `get_shopping_list_items_from_recipe` (lines 323-411), and `add_recipe_ingredients_to_list` (lines 413-455) are unchanged.
- All pre-existing tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` and `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py` continue to pass with no modifications.

### US-4 — 回归测试 (Regression tests)

**As** a Mealie team member, **I want** four additional regression tests in the same new test file that pin the exact merge contract, **so that** any future change to consolidation logic is caught immediately.

**Acceptance criteria** — all four tests live in `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` and use the same helper / fixture conventions as US-1:

1. **`test_single_occurrence`** — Create the recipe, schedule it in exactly one meal-plan slot, add to a fresh shopping list. Assert: each ingredient appears once with `quantity == ingredient.quantity` (within `1e-6`), `food_id` and `unit_id` set, exactly one `recipe_references` entry with `recipe_scale == 1.0`. Total `len(listItems) == 2` (tomato + salt).
2. **`test_multiple_occurrences_same_unit`** — Parametrized via `@pytest.mark.parametrize("occurrences", [2, 3])`. Schedule the recipe `N` times in distinct meal-plan slots. Add via N bulk entries (per-occurrence form). Assert: each ingredient appears once with `quantity == ingredient.quantity * N`, exactly one `recipe_references` entry with `recipe_scale == float(N)` (per `merge_items` lines 109-126). `len(listItems) == 2`.
3. **`test_multiple_occurrences_different_units`** — Build TWO recipes: `recipe_each` has `RecipeIngredient(food=food_tomato, unit=unit_each, quantity=2)`; `recipe_grams` has `RecipeIngredient(food=food_tomato, unit=unit_gram, quantity=100)`. Both `unit_each` and `unit_gram` are created with `standard_unit=None` so `UnitConverter` does not apply. Schedule one of each, add both to a fresh shopping list. Assert: TWO distinct list items for `food_tomato`, one with `unit_id == unit_each.id, quantity == 2.0`, one with `unit_id == unit_gram.id, quantity == 100.0`. Both items have the same `food_id` but distinct `unit_id`. `len(listItems) == 2`.
4. **`test_different_food_same_name`** — Create two `SaveIngredientFood(name="tomato", group_id=...)` records (distinct UUIDs but identical name). Build two recipes, each using a different food but the same `unit_each` and `quantity=2`. Schedule one of each, add both to a fresh shopping list. Assert: TWO distinct list items, each with `food.name == "tomato"` but DISTINCT `food_id`. Each item has `quantity == 2.0`. `len(listItems) == 2`. This confirms `food_id` (not `display`/`name`) is the merge key.

All four tests PASS after the US-3 fix.

---

## Functional requirements

> Each FR pins a behavior the fix must satisfy, with VERIFIED code references.

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
The PR description has a `### Root cause` markdown section answering the three input questions in order (function, variant, boundary cases) with at least one specific file:line citation per answer. The variant labeling references input.md附录 (Variant A: overwrite-vs-accumulate; Variant B: wrong merge key). Boundary case enumeration covers same-food+same-unit merge, same-food+different-unit non-merge (with `standard_unit=None`), different-food same-display non-merge, `food_id is None` note-fallback, and recipe_scale accumulation through `merge_items` lines 109-126.
- **Code references**:
  - `mealie/services/household_services/shopping_lists.py:45-71` (`can_merge`)
  - `mealie/services/household_services/shopping_lists.py:73-128` (`merge_items`)
  - `mealie/services/household_services/shopping_lists.py:109-126` (`recipe_scale` accumulation)
  - `input.md:103-128` (Variant A/B patch text)

### FR-3 (US-3) — Fix is confined to `can_merge` and/or `merge_items`
The diff modifies only `mealie/services/household_services/shopping_lists.py`. Within that file, only `ShoppingListService.can_merge` (lines 45-71) and/or `ShoppingListService.merge_items` (lines 73-128) are touched. Total changed lines ≤ 5 (idiomatic Conservative patch is 1-2 lines). After the fix: `can_merge` keeps `item1.food_id != item2.food_id` as a rejection (line 52), retains the existing `standard_unit` / `UnitConverter` branch (lines 57-68), and returns `bool(item1.food_id) or item1.note == item2.note` (line 71). `merge_items` keeps `to_item.quantity += from_item.quantity` (line 96), the `merge_quantity_and_unit(...)` branch (lines 86-92), the note concatenation, the extras update, and the recipe-reference merge (lines 109-126) unchanged.
- **Code references**:
  - `mealie/services/household_services/shopping_lists.py:45-71`
  - `mealie/services/household_services/shopping_lists.py:73-128`
  - `mealie/services/household_services/shopping_lists.py:154-223` (unchanged consumer)
  - `mealie/services/household_services/shopping_lists.py:413-455` (unchanged caller)

### FR-4 (US-4) — Four regression tests with the named contract
Four tests are appended to `test_meal_plan_to_shopping_bug.py` with the EXACT names and behaviors in the input table: `test_single_occurrence`, `test_multiple_occurrences_same_unit` (parametrized over `[2, 3]`), `test_multiple_occurrences_different_units`, `test_different_food_same_name`. Each asserts both the per-item quantity AND the `len(listItems)` count; each also asserts the `food_id` and `unit_id` on returned items (not just `note` / `display`) to lock the merge-key semantics.
- **Code references**:
  - `mealie/schema/household/group_shopping_list.py:106-120` (`ShoppingListItemOut` exposes `food_id`, `unit_id`, `food`, `unit`)
  - `mealie/schema/household/group_shopping_list.py:32-46` (`ShoppingListItemRecipeRefCreate` — `recipe_scale` field)
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` (analogous prior test pattern to mirror)
  - `mealie/services/household_services/shopping_lists.py:109-126` (`recipe_scale` merge semantics)

### FR-5 (US-3 / non-functional) — Pre-existing tests remain green
After the US-3 fix, all tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py`, `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py`, and `tests/integration_tests/user_household_tests/test_group_mealplan.py` PASS without modification. In particular, the existing merge tests `test_shopping_lists_add_recipe_with_merge` (lines 581-660), `test_shopping_lists_add_recipes_with_merge` (lines 663-739), and `test_shopping_lists_add_nested_recipe_ingredients` (lines 249-361) keep passing — confirming the fix does not regress PRs #5054 (bulk add), #4800 (recipe-as-ingredient), or #7121 (unit standardization).
- **Code references**:
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:581-660`
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739`
  - `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:249-361`
  - `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py:644-731` (standard-unit merge tests)

### FR-6 (non-functional) — Toolchain conformance per Mealie conventions
Tests follow Mealie conventions: use `unique_user` + `api_client` fixtures; assert via `utils.assert_deserialize(response, 200)` (`tests/utils/assertion_helpers.py:23-25`); serialize bulk payloads via `utils.jsonify([... .model_dump()])` (`tests/utils/jsonify.py:1-5`); deserialize the list response via `ShoppingListOut.model_validate(...)` for typed access to `food`, `unit`, `food_id`, `unit_id`, `recipe_references`. The full validation command is `task py:check` (`Taskfile.yml:122-128` — runs ruff format + ruff lint + mypy + pytest). Python entry-points use `uv` (never `python` / `pip`), per `.github/copilot-instructions.md`.
- **Code references**:
  - `tests/utils/assertion_helpers.py:23-25`
  - `tests/utils/jsonify.py:1-5`
  - `Taskfile.yml:107-110` (`py:test`)
  - `Taskfile.yml:122-128` (`py:check`)
  - `mealie/schema/household/group_shopping_list.py:250-285` (`ShoppingListOut` shape)

---

## Success criteria

| ID | Metric | Threshold | How measured |
|---|---|---|---|
| SC-1 | `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` exit status before fix | exit non-zero (FAIL) | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` on the buggy HEAD |
| SC-2 | Same test exit status after fix | exit zero (PASS) | Re-run after the US-3 patch |
| SC-3 | All 5 tests in `test_meal_plan_to_shopping_bug.py` (1 repro + 4 regressions) | 5 / 5 PASS | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py -v` |
| SC-4 | Pre-existing related tests still green | 0 new failures in `test_group_shopping_lists.py`, `test_group_shopping_list_items.py`, `test_group_mealplan.py` | `uv run pytest tests/integration_tests/user_household_tests/test_group_shopping_lists.py tests/integration_tests/user_household_tests/test_group_shopping_list_items.py tests/integration_tests/user_household_tests/test_group_mealplan.py` |
| SC-5 | Diff size in `mealie/services/household_services/shopping_lists.py` | ≤ 5 changed lines | `git diff --shortstat HEAD~ -- mealie/services/household_services/shopping_lists.py` |
| SC-6 | Files modified in production code | exactly 1 (`mealie/services/household_services/shopping_lists.py`) | `git diff --name-only HEAD~ -- mealie/` |
| SC-7 | `task py:check` exit status | zero | `task py:check` end-to-end |

---

## Edge cases

| EC | Scenario | Expected behavior | Source |
|---|---|---|---|
| EC-1 | Same `food_id`, different `unit_id`, neither unit has `standard_unit` | Two distinct rows (no merge) | `can_merge` lines 57-68: both fail the `standard_unit` check, return `False` |
| EC-2 | Different `food_id`, identical `food.name` ("tomato" twice with distinct UUIDs) | Two distinct rows (no merge) | `can_merge` line 52: `item1.food_id != item2.food_id` rejects merge regardless of name |
| EC-3 | Same recipe added N times with `recipe_increment_quantity` mix (e.g. one entry with 2 and one entry with 1) | One row per `(food_id, unit_id)` with quantity = `base * 3`; one `recipe_references` entry with `recipe_scale == 3.0` | `merge_items` lines 109-126 sum `recipe_scale` per `recipe_id` |
| EC-4 | Float-precision accumulation (e.g. `0.1 * 3` produces `0.30000000000000004`) | Assertions use `pytest.approx(..., abs=1e-6)` or `pytest.approx(..., rel=1e-6)`; quantities are persisted as raw float sums (no rounding after merge) | `mealie/db/models/household/shopping_list.py:67` (Float column); `mealie/schema/recipe/recipe_ingredient.py:23, 345-357` rounds INPUT to `INGREDIENT_QTY_PRECISION=3` but `merge_items` line 96 does NOT round the SUM |
| EC-5 | Recipe deleted between meal-plan creation and add-to-shopping-list | `get_shopping_list_items_from_recipe` raises `UnexpectedNone("Recipe not found")` — caller surfaces this; the new tests do NOT exercise this path (out of fix scope) but the spec documents it as an unchanged contract | `mealie/services/household_services/shopping_lists.py:336-338` |
| EC-6 | `food_id is None` on both items (parsed/unparsed ingredient with no food) | Merges only when `note` matches (`can_merge` line 71 fallback) | `can_merge` line 71: `return bool(item1.food_id) or item1.note == item2.note` |
| EC-7 | Recipe with internal duplicate ingredients AND `recipe_increment_quantity > 1` (sub-recipe scaling) | The same-recipe pre-merge in `get_shopping_list_items_from_recipe` lines 395-397 adds raw `ingredient.quantity` (not scaled); this is a separate latent issue documented in `self_concerns`, NOT fixed here | `mealie/services/household_services/shopping_lists.py:393-397` |

---

## Self-concerns

1. **In-recipe duplicate scaling latent bug.** `get_shopping_list_items_from_recipe` lines 395-397 use `existing_item.quantity += ingredient.quantity` rather than `ingredient.quantity * scale` when consolidating duplicates inside a single recipe. With `recipe_increment_quantity > 1` and internal duplicates, the result undercounts. This is OUT OF SCOPE for the case 3 minimum fix (the reported bug is duplicate occurrences across meal-plan slots, not internal duplicates at scale). Recommended follow-up: a separate PR with its own reproduction test.
2. **Float-precision accumulation not rounded.** `merge_items` line 96 produces raw float sums; for ingredients with fractional quantities (e.g. `1/3`), accumulating across many occurrences will produce floats that do not round-trip exactly to `INGREDIENT_QTY_PRECISION=3` decimal places. The Mealie schema rounds INPUT quantities but not consolidated sums. Tests in this spec use `pytest.approx(..., abs=1e-6)` to remain robust. A future enhancement could re-round at the persistence boundary, but this would also be a separate PR.
3. **Future unit-conversion merge dimensions.** PR #7121 introduced `standard_unit` / `UnitConverter` so two items with different `unit_id` but compatible `standard_unit` DO merge (e.g. `gram` + `kilogram`). If a future PR adds more merge dimensions (e.g. fuzzy food matching by alias), the `test_multiple_occurrences_different_units` test must be re-evaluated. The spec uses `standard_unit=None` units explicitly to insulate the regression test from that change.

---

## Out of scope

- Modifying any frontend code (`frontend/`) — bug is backend-only.
- Refactoring `bulk_create_items`, `bulk_update_items`, `get_shopping_list_items_from_recipe`, or `add_recipe_ingredients_to_list`.
- Changing any SQLAlchemy model, Alembic migration, repository, or Pydantic schema.
- Adding a dedicated meal-plan-to-shopping-list backend route (UI currently calls the existing bulk route — this is by design).
- Fixing the in-recipe duplicate scaling latent bug (see self-concern 1).
- Re-rounding float sums after merge (see self-concern 2).
- Any locale / translation file change.
- Any change to OpenAPI generation, TypeScript codegen, or test-helper generation. The `task dev:generate` step is NOT required because no Pydantic schema changes.

---

## Verification commands

| Phase | Command | Expected |
|---|---|---|
| Pre-fix (US-1 baseline) | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients -v` | 1 failed |
| Post-fix (US-3 acceptance) | `uv run pytest tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py -v` | 5 passed (or more with parametrization expansion) |
| Regression sweep | `uv run pytest tests/integration_tests/user_household_tests/test_group_shopping_lists.py tests/integration_tests/user_household_tests/test_group_shopping_list_items.py tests/integration_tests/user_household_tests/test_group_mealplan.py` | 0 new failures |
| Full validation | `task py:check` | exit 0 |
| Diff size check | `git diff --shortstat HEAD~ -- mealie/services/household_services/shopping_lists.py` | ≤ 5 lines changed in 1 file |

---

## needs_clarification

None. The input is unambiguous on workflow, file scope, regression tests, and constraints. All cross-perspective conflicts (C1-C5 in `consolidated.md`) are resolved within the spec without requiring user input.
