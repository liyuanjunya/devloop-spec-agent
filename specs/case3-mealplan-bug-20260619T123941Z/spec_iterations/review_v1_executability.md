# Executability Review (v1)

## Verdict: NEEDS_REFINE

A code agent can probably infer the intended implementation, but the spec is not fully executable as written. The main issue is an inconsistent fixture variable in the core reproduction (`food_egg` is created but `food_salt` is used/asserted), and two schema citations omit inherited fields that their purpose claims are in range. All existing cited Mealie/source files I checked exist, FR-level `code_references` match exactly between `spec.md` and `spec.json`, success criteria are measurable, and the four named regression tests are concrete enough to write.

---

## Code reference verification

All existing source paths were opened from `C:\Users\v-liyuanjun\Downloads\mealie\`; `input.md` was opened from the spec directory.

| FR / location | path | claim | verified? |
|---|---|---|---|
| FR-1 | `mealie/routes/households/controller_shopping_lists.py:256-261` | bulk add-recipe route | ✅ `@router.post("/{item_id}/recipe")` and `add_recipe_ingredients_to_list` are in range |
| FR-1 | `tests/utils/api_routes/__init__.py:415-417` | `households_shopping_lists_item_id_recipe` helper | ✅ exact helper in range |
| FR-1 | `tests/utils/api_routes/__init__.py:405-407` | `households_shopping_lists_item_id` helper | ✅ exact helper in range |
| FR-1 | `tests/utils/api_routes/__init__.py:92` | `households_mealplans` route constant | ✅ exact constant in range |
| FR-1 | `tests/fixtures/fixture_users.py:179-226` | `unique_user` fixture path | ✅ `_unique_user` and `unique_user` fixture are in range |
| FR-1 | `tests/fixtures/fixture_shopping_lists.py:49-65` | `shopping_list` fixture | ✅ exact fixture in range |
| FR-1 | `tests/conftest.py:37-54` | `api_client` fixture / DB override | ✅ exact fixture and override in range |
| FR-2 / FR-3 | `mealie/services/household_services/shopping_lists.py:45-71` | `can_merge` | ✅ exact function in range; final return is L71 |
| FR-2 / FR-3 | `mealie/services/household_services/shopping_lists.py:73-128` | `merge_items` | ✅ exact function in range; non-converted sum is L96; recipe-scale merge is L109-L126 |
| FR-2 | `mealie/services/household_services/shopping_lists.py:109-126` | recipe-scale accumulation | ✅ exact block in range |
| FR-2 | `input.md:103-128` | Variant A/B patch text | ✅ both illustrative patch variants are in range |
| FR-3 | `mealie/services/household_services/shopping_lists.py:154-223` | `bulk_create_items` unchanged consumer | ✅ exact function in range |
| FR-3 | `mealie/services/household_services/shopping_lists.py:413-455` | `add_recipe_ingredients_to_list` unchanged caller | ✅ exact function in range |
| FR-4 | `mealie/schema/household/group_shopping_list.py:106-120` | `ShoppingListItemOut` exposes `food_id`, `unit_id`, `food`, `unit` | ⚠ `ShoppingListItemOut`, `food`, and `unit` are in range, but `food_id`/`unit_id` are inherited from `ShoppingListItemBase` at L65-L67, outside the cited range |
| FR-4 | `mealie/schema/household/group_shopping_list.py:32-46` | `ShoppingListItemRecipeRefCreate.recipe_scale` | ✅ class and `recipe_scale` field are in range |
| FR-4 / FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` | `test_shopping_lists_add_recipes_with_merge` | ✅ exact test in range |
| FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:581-660` | `test_shopping_lists_add_recipe_with_merge` | ✅ exact test in range |
| FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:249-361` | `test_shopping_lists_add_nested_recipe_ingredients` | ✅ exact test in range |
| FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py:644-731` | standard-unit merge tests | ✅ three relevant tests are in range |
| FR-6 | `tests/utils/assertion_helpers.py:23-25` | `assert_deserialize` helper | ✅ exact helper in range |
| FR-6 | `tests/utils/jsonify.py:1-5` | `jsonify` helper | ✅ exact helper in range |
| FR-6 | `Taskfile.yml:107-110` | `py:test` command | ✅ exact task in range |
| FR-6 | `Taskfile.yml:122-128` | `py:check` command | ✅ task and deps are in range |
| FR-6 | `mealie/schema/household/group_shopping_list.py:250-285` | `ShoppingListOut` shape | ⚠ `ShoppingListOut` is in range, but inherited `list_items` is at L247, just outside the range |

Additional in-text citations checked: `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:258-278`, `mealie/schema/recipe/recipe_ingredient.py:155-156`, `tests/fixtures/fixture_recipe.py:31-49`, `tests/integration_tests/user_household_tests/test_group_mealplan.py:80-99`, `mealie/db/models/household/shopping_list.py:67`, `mealie/schema/recipe/recipe_ingredient.py:23` and `:345-357`, `mealie/services/household_services/shopping_lists.py:225-310`, `:323-411`, `:336-338`, and `:393-397` all exist and contain the cited concepts.

---

## Wrong/imprecise citations

- **`mealie/schema/household/group_shopping_list.py:106-120` (FR-4)** — imprecise. The cited range contains `ShoppingListItemOut.food` and `ShoppingListItemOut.unit`, but not `food_id` or `unit_id`; those fields are inherited from `ShoppingListItemBase` at L65-L67. Suggested range: `mealie/schema/household/group_shopping_list.py:60-120` or split as `65-67` plus `106-120`.
- **`mealie/schema/household/group_shopping_list.py:250-285` (FR-6)** — imprecise for “ShoppingListOut shape” if the agent needs `list_items`; `list_items` is declared on `ShoppingListUpdate` at L245-L247 and inherited by `ShoppingListOut`. Suggested range: `mealie/schema/household/group_shopping_list.py:245-285`.
- **`tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`** — does not exist yet in the Mealie checkout. This is expected for a “new test file” target, but it is not a real existing path if strict path verification includes target files.

---

## Critical issues

(none)

## High issues

- **EXEC-H-001 — US-1 / `spec.json` US-1 creates `food_egg` but later uses and asserts `food_salt`.**
  The reproduction setup says to create `food_tomato` and `food_egg`, but the recipe ingredient list and final assertions use `food_salt` with `unit_tsp`. A literal code agent can produce an undefined variable or create the wrong fixture data. Suggested fix: replace `food_egg` with `food_salt` in `spec.md` US-1 AC step 1 and `spec.json` US-1 acceptance criterion 2.

## Medium issues

- **EXEC-M-001 — Two schema citations omit inherited fields needed by the stated purpose.**
  See “Wrong/imprecise citations.” These are not likely to block a human, but a code agent that reads only the cited slices will not see `ShoppingListItemBase.food_id`, `ShoppingListItemBase.unit_id`, or `ShoppingListUpdate.list_items`.

- **EXEC-M-002 — `HEAD~`-based diff success criteria assume a committed implementation shape.**
  SC-5 and SC-6 are measurable after a commit, but many code agents validate before committing. Consider adding equivalent pre-commit measurements, e.g. `git diff --shortstat -- mealie/services/household_services/shopping_lists.py` and `git diff --name-only -- mealie/`.

## Low issues

- **EXEC-L-001 — FR-3 uses `can_merge` and/or `merge_items`, which is acceptable but mildly conditional.**
  The variant is intentionally selected by root cause, so this is not a blocker. If desired, say “modify only the function(s) required by the observed Variant A/B root cause.”

---

## spec.md vs spec.json `code_references`

✅ Identical for every FR (FR-1 through FR-6). Paths, order, and line ranges match between `spec.md` and `spec.json`.

---

## Success criteria measurability

✅ SC-1 through SC-7 are measurable: each has a command or concrete git-diff check and a numeric/exit-code threshold. The only refinement recommended is adding pre-commit alternatives to the `HEAD~` diff checks.

---

## TBD / placeholder phrase scan

✅ No matches found in `spec.md` or `spec.json` for: `TBD`, `placeholder`, `or equivalent`, `if needed`, `TODO`, or `FIXME`.

---

## Four named regression tests

✅ The assertions are concrete enough to write:

- `test_single_occurrence`: exact quantities, row count, `food_id`, `unit_id`, and `recipe_scale == 1.0` are specified.
- `test_multiple_occurrences_same_unit`: exact parametrization `[2, 3]`, quantity multiplier, row count, and `recipe_scale == float(N)` are specified.
- `test_multiple_occurrences_different_units`: exact two-recipe setup and distinct returned row assertions are specified.
- `test_different_food_same_name`: exact same-name/different-UUID setup and non-merge assertions are specified.

---

## Summary

The spec is close to executable and does not require product clarification. Before handing it to an implementation agent, fix the `food_egg`/`food_salt` inconsistency and widen the two schema citations above. After those edits, the FRs, code references, success criteria, and regression-test assertions should be concrete enough for autonomous implementation.
