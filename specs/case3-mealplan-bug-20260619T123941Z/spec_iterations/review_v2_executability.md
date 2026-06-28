# Executability Review (v2)

## Verdict: NEEDS_REFINE

v2 fixes the v1 `food_salt` inconsistency and the two inherited-field schema citations. Most FR-level source ranges are now executable. However, v2 introduces two blocking executability problems: the spec still permits Variant B even though the stated primary reproduction/SC-1 is not guaranteed to fail for the display-key Variant B described in `input.md`, and `spec_v2.md` contradicts itself on SC-3 by saying **6 pytest cases pass** while the arithmetic, verification command, and JSON say **8**.

---

## Code reference verification

All existing source paths were opened from `C:\Users\v-liyuanjun\Downloads\mealie\`; `input.md` was opened from the case directory.

| FR / location | path | claim | verified? |
|---|---|---|---|
| FR-1 | `mealie/routes/households/controller_shopping_lists.py:256-261` | bulk add-recipe route | ✅ route and service delegation are in range |
| FR-1 | `tests/utils/api_routes/__init__.py:415-417` | recipe route helper | ✅ exact helper in range |
| FR-1 | `tests/utils/api_routes/__init__.py:405-407` | list GET helper | ✅ exact helper in range |
| FR-1 | `tests/utils/api_routes/__init__.py:92` | mealplans route constant | ✅ exact constant in range |
| FR-1 | `tests/fixtures/fixture_users.py:179-226` | `unique_user` fixture path | ✅ `_unique_user` and `unique_user` are in range |
| FR-1 | `tests/fixtures/fixture_shopping_lists.py:49-65` | `shopping_list` fixture | ✅ exact fixture in range |
| FR-1 | `tests/conftest.py:37-54` | DB override / `api_client` | ✅ exact fixture and override in range |
| FR-2 / FR-3 | `mealie/services/household_services/shopping_lists.py:45-71` | `can_merge` | ✅ exact function in range |
| FR-2 / FR-3 | `mealie/services/household_services/shopping_lists.py:73-128` | `merge_items` | ✅ exact function in range |
| FR-2 / FR-4 | `mealie/services/household_services/shopping_lists.py:109-126` | recipe-scale accumulation | ✅ exact block in range |
| FR-2 | `input.md:88-138` | bug-injection appendix and workflow | ✅ range exists, but see wrong-citation note about Variant B symptoms |
| FR-3 / FR-7 | `mealie/services/household_services/shopping_lists.py:154-223` | `bulk_create_items` | ✅ exact function in range |
| FR-3 | `mealie/services/household_services/shopping_lists.py:413-455` | `add_recipe_ingredients_to_list` | ✅ exact function in range |
| FR-4 | `mealie/schema/household/group_shopping_list.py:58-67` | inherited `food_id`, `unit_id` | ✅ v1 issue fixed; fields at L65/L67 |
| FR-4 | `mealie/schema/household/group_shopping_list.py:106-120` | `ShoppingListItemOut.food`, `.unit` | ✅ fields at L111/L113 |
| FR-4 | `mealie/schema/household/group_shopping_list.py:32-46` | recipe ref create / scale | ✅ class and `recipe_scale` in range |
| FR-4 / FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:663-739` | analogous merge test | ✅ exact test in range |
| FR-4 | `mealie/services/household_services/shopping_lists.py:370-385` | scale applied to ingredient quantity | ✅ line 373 has `ingredient.quantity * scale` |
| FR-4 | `mealie/services/household_services/shopping_lists.py:437-452` | list-level recipe ref accumulator | ✅ line 443 accumulates `recipe_quantity` |
| FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:581-660` | single recipe merge test | ✅ exact test in range |
| FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:249-361` | nested recipe test | ✅ exact test in range |
| FR-5 | `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py:644-731` | standard-unit tests | ✅ three tests in range |
| FR-6 | `tests/utils/assertion_helpers.py:23-25` | `assert_deserialize` | ✅ exact helper in range |
| FR-6 | `tests/utils/jsonify.py:1-5` | `jsonify` | ✅ exact helper in range |
| FR-6 | `Taskfile.yml:107-110` | `py:test` | ✅ exact task in range |
| FR-6 | `Taskfile.yml:122-128` | `py:check` deps | ✅ task deps in range |
| FR-6 | `mealie/schema/household/group_shopping_list.py:245-254` | `list_items` inherited by `ShoppingListOut` | ✅ v1 issue fixed; `list_items` at L247 |
| FR-6 | `mealie/schema/household/group_shopping_list.py:250-285` | loader options | ✅ class and loader options in range |
| FR-7 | `mealie/services/household_services/shopping_lists.py:215-216` | create/update persistence | ✅ exact calls in range |
| FR-7 | `mealie/db/models/household/shopping_list.py:51-98` | `ShoppingListItem` model | ✅ model range in range |
| FR-7 | `mealie/schema/household/group_shopping_list.py:58-120` | item schemas | ✅ base/create/update/out in range |
| FR-7 | `input.md:55-59` | implementation constraints | ✅ exact constraint bullets in range |

Additional in-text citations checked and found present: frontend `planner.vue:243-256`, `RecipeDialogAddToShoppingList.vue:340-394`, `:434-461`, `group-shopping-lists.ts:32-34`, recipe ingredient schema `:23`, `:155-156`, `:345-357`, fixture/test pattern ranges, and shopping-list service subranges.

---

## Wrong / imprecise citations in v2

- **`input.md:88-128` / `input.md:88-138` when used to justify Variant B failing US-1 / SC-1** — semantically wrong. The range contains the display-key illustrative Variant B, but that variant does not imply the primary duplicate-same-recipe test fails: two per-occurrence entries from the same recipe have the same `food_id`, `unit_id`, quantity, and generated `display`, so a display-key merge can still accumulate them. The cited appendix supports “different food same display can merge wrongly,” not “US-1 fails with `len(listItems) == 4`.”
- **`frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue:340-394`** — imprecise for the named function `consolidateRecipesIntoSections`; the function starts at L307 and the map is initialized at L308. The dedupe loop is in L340-L394, so use `307-394` if the citation purpose includes the function itself.
- **`frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue:434-461`** — imprecise for “sends ONE payload”; L434-L461 builds `recipeData`, but the actual `api.shopping.lists.addRecipes(...)` call is L463. Suggested range: `434-463` or split `454-461` payload construction plus `463` send.
- **`Taskfile.yml:122-128`** — mildly imprecise for “runs ruff format + ruff lint + mypy + pytest.” L122-L128 shows the `py:check` task and dependency names only; the actual commands are at `102-110` and `112-120`. Not blocking if dependency names are sufficient.
- **`tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`** — still does not exist in the checkout. This is expected for the new target test file, but it is not an existing-path citation.

---

## Critical issues

(none)

## High issues

- **EXEC2-H-001 — Variant B is not executable under SC-1 as written.**
  v2 says either Variant A or Variant B produces equivalent symptoms and that US-1 fails for Variant B with `len(listItems) == 4`. That does not follow from the cited Variant B. A display-key merge bug is primarily caught by `test_different_food_same_name`, not necessarily by the primary duplicate-same-recipe reproduction. Fix by either restricting the deterministic precondition to Variant A, or splitting SC-1 into variant-specific pre-fix failures with a Variant B primary test that actually fails.

- **EXEC2-H-002 — `spec_v2.md` SC-3 has a contradictory pass threshold.**
  The SC-3 row says **“6 pytest cases pass”** but immediately computes `1 + 1 + 4 + 1 + 1 = 8 total`; the verification table says **8 passed**, and `spec_v2.json` also says 8. A literal agent could report the wrong acceptance count. Fix the markdown threshold to **8 collected pytest cases pass**.

## Medium issues

- **EXEC2-M-001 — Some frontend and Taskfile line ranges are too narrow for their stated purpose.**
  See wrong/imprecise citations. These do not block backend implementation, but they violate the “verified line range” standard and should be tightened before handing the spec to an autonomous agent.

## Low issues

- **EXEC2-L-001 — The `needs_clarification` item should not say “No spec changes required regardless of choice.”**
  Because Variant B needs a different pre-fix failure signal, the variant choice can change which test proves SC-1. This is low only if the spec is changed to default exclusively to Variant A.

---

## spec.md vs spec.json

- ✅ `spec_id` and `iterations` match (`spec-v2`, iterations `2`).
- ✅ FR-level `code_references` in the explicit FR reference lists match the JSON for FR-1 through FR-7.
- ⚠ SC-3 differs: `spec_v2.md` threshold says **6** while `spec_v2.json` says **8**. The JSON, markdown arithmetic note, and verification table agree on 8.

---

## Success criteria measurability

SC-2, SC-4, SC-5, SC-6, SC-7, and SC-8 are measurable. SC-3 is measurable after fixing the 6/8 typo. SC-1 is measurable only for Variant A as written; Variant B needs a variant-specific failing test or must be removed from the allowed injection choices.

---

## TBD / placeholder phrase scan

✅ No matches in `spec_v2.md` or `spec_v2.json` for: `TBD`, `placeholder`, `or equivalent`, `if needed`, `TODO`, or `FIXME`.

---

## Named regression tests

The five named tests and the 8 collected pytest cases are concrete enough to implement after the SC-3 typo is fixed. The Variant B pre-fix expectation should be moved to `test_different_food_same_name` or equivalent if Variant B remains an allowed injection.

---

## Summary

v2 is much closer than v1 and resolves all v1 executability findings. Before implementation, fix the Variant B precondition/SC-1 mismatch and the SC-3 6-vs-8 contradiction, then widen the few narrow line citations above.
