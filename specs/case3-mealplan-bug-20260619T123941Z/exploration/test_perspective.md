# Test perspective exploration — DevLoop case 3

Input reviewed: `C:\Users\v-liyuanjun\source\repos\devloop\specs\case3-mealplan-bug-20260619T123941Z\input.md`. Required tests are one bug repro plus four regressions: single occurrence, multiple same-unit occurrences, same food/different units not merged, different food IDs/same name not merged.

## Existing fixture/test files found

### `tests\conftest.py` — test app/session bootstrap
- Symbols / ranges:
  - `override_get_db`: lines 37-42
  - `api_client`: lines 45-54
  - `global_cleanup`: lines 66-71
- Importance: critical
- Notes: `api_client` overrides FastAPI `generate_session` with `SessionLocal` and yields `TestClient(app)`. Cleanup removes the SQLite DB path at session end and purges `tests\.temp`; no per-test transaction rollback fixture is visible here.

### `tests\fixtures\__init__.py` — fixture export surface
- Symbols / ranges:
  - wildcard exports for fixture modules: lines 1-6
- Importance: relevant
- Notes: `tests\conftest.py` imports these fixtures via `from tests.fixtures import *`, so integration tests can directly use `unique_user`, `shopping_list(s)`, and recipe fixtures.

### `tests\fixtures\fixture_database.py` — repository/session fixtures
- Symbols / ranges:
  - `session`: lines 10-17
  - `unfiltered_database`: lines 19-21
- Importance: critical
- Notes: `session` is module-scoped and backed by `SessionLocal`; tests commonly create scoped repositories through `unique_user.repos` rather than explicit rollback wrappers.

### `tests\fixtures\fixture_users.py` — user/group/household fixtures
- Symbols / ranges:
  - `build_unique_user`: lines 17-52
  - `_unique_user`: lines 179-216
  - `unique_user_fn_scoped`: lines 219-221
  - `unique_user`: lines 224-226
  - `h2_user`: lines 55-118
- Importance: critical
- Notes: these fixtures create registered users, authenticate, and attach `get_repositories(session, group_id, household_id)`. Use `unique_user_fn_scoped` if isolation from module-scoped state is important; otherwise existing household tests use `unique_user`.

### `tests\fixtures\fixture_recipe.py` — recipe/ingredient fixtures
- Symbols / ranges:
  - `recipe_ingredient_only`: lines 31-55
  - `recipes_ingredient_only`: lines 57-85
  - `random_recipe`: lines 107-131
- Importance: critical
- Notes: creates recipes through `unique_user.repos.recipes.create(Recipe(... recipe_ingredient=[RecipeIngredient(...)])`. Existing fixture ingredients are note-based and quantity-based; they do not set food+unit together.

### `tests\fixtures\fixture_shopping_lists.py` — shopping list fixtures
- Symbols / ranges:
  - `create_item`: lines 10-21
  - `shopping_lists`: lines 24-47
  - `shopping_list`: lines 49-65
  - `list_with_items`: lines 68-94
- Importance: critical
- Notes: creates shopping lists with `ShoppingListSave`, and items with `ShoppingListItemCreate`. `create_item` shows item field names including `unit_id`, `food_id`, `recipe_id`, `quantity`, and `note`.

### `tests\utils\api_routes\__init__.py` — route constants/helpers
- Symbols / ranges:
  - meal plan/shopping constants: lines 92-115
  - shopping recipe route helpers: lines 405-427
- Importance: critical
- Notes: existing test routes include `households_mealplans`, `households_shopping_lists`, `households_shopping_lists_item_id`, `households_shopping_lists_item_id_recipe`, and `households_shopping_lists_item_id_recipe_recipe_id`. No generated route helper for a direct meal-plan-to-shopping-list endpoint was found.

### `tests\utils\assertion_helpers.py` / `tests\utils\jsonify.py` — assertion/encoding helpers
- Symbols / ranges:
  - `assert_deserialize`: `tests\utils\assertion_helpers.py` lines 23-25
  - `jsonify`: `tests\utils\jsonify.py` lines 1-5
- Importance: relevant
- Notes: shopping tests use `utils.assert_deserialize(response, status)` and `utils.jsonify([...model_dump()...])` before posting Pydantic payloads.

### `tests\integration_tests\user_household_tests\test_group_mealplan.py` — meal plan tests
- Symbols / ranges:
  - `create_recipe`: lines 23-32
  - `test_create_mealplan_no_recipe`: lines 63-78
  - `test_create_mealplan_with_recipe`: lines 80-99
  - slice/today patterns: lines 160-215
- Importance: critical
- Notes: meal plans are created with `CreatePlanEntry(...).model_dump(by_alias=True)`, then date is converted to `YYYY-MM-DD` and `recipeId` is stringified before `POST api_routes.households_mealplans`.

### `tests\integration_tests\user_household_tests\test_group_shopping_lists.py` — shopping list recipe/consolidation tests
- Symbols / ranges:
  - `test_shopping_lists_add_recipe`: lines 115-175
  - `test_shopping_lists_add_recipes`: lines 177-247
  - `test_shopping_lists_add_nested_recipe_ingredients`: lines 249-361
  - `test_shopping_lists_add_cross_household_recipe`: lines 364-422
  - `test_shopping_lists_add_one_with_zero_quantity`: lines 425-484
  - `test_shopping_lists_add_custom_recipe_items`: lines 487-537
  - `test_shopping_lists_add_recipe_with_merge`: lines 581-660
  - `test_shopping_lists_add_recipes_with_merge`: lines 663-739
  - `test_shopping_list_add_recipe_scale`: lines 742-806
  - remove/decrement coverage: lines 808-1070
  - zero-quantity manipulation: lines 1073-1187
- Importance: critical
- Notes: this is the closest existing coverage. It tests adding one recipe, adding bulk recipes, recipe quantity scaling, nested recipes, duplicate-note consolidation within one recipe and across recipes, recipe references, and quantity increments. It does **not** create meal plan entries first, and merge tests are primarily note-based rather than food_id+unit_id based.

### `tests\integration_tests\user_household_tests\test_group_shopping_list_items.py` — item CRUD/merge assertions
- Symbols / ranges:
  - `create_item`: lines 17-23
  - create-one assertions: lines 39-70
  - create-many assertions: lines 72-105
  - label-by-food examples: lines 108-170
  - update-one/list-size assertions: lines 205-237
  - standard-unit merge tests: lines 644-731
- Importance: relevant
- Notes: useful patterns for asserting `createdItems`, `updatedItems`, `deletedItems`, `listItems`, `quantity`, `unitId`, nested `unit.id`, and list length. Standard-unit tests show compatible units merge, different foods/notes do not merge, and incompatible standard units do not merge.

### `tests\unit_tests\schema_tests\test_shopping_list_ingredient.py` — shopping item display schema
- Symbols / ranges:
  - `test_shopping_list_ingredient_validation`: lines 6-40
- Importance: adjacent
- Notes: validates `ShoppingListItemOut` with `foodId`, `unitId`, `quantity`, `recipeReferences`, and `display == "8 bell peppers"`.

### `tests\integration_tests\user_recipe_tests\test_recipe_ingredients.py` — ingredient display unit test file under integration tree
- Symbols / ranges:
  - parametrized ingredient display inputs: lines 15-176
  - `test_ingredient_display`: lines 177-234
- Importance: adjacent
- Notes: demonstrates constructing `RecipeIngredient(quantity=quantity, unit=unit, food=food, note=note)` with `IngredientUnit` and `IngredientFood`, but it is schema/display oriented and not persisted through a recipe/shopping-list flow.

### `tests\unit_tests\repository_tests\test_food_repository.py` and `test_unit_repository.py` — persisted food/unit recipe associations
- Symbols / ranges:
  - `test_food_merger`: `test_food_repository.py` lines 9-52
  - `test_unit_merger`: `test_unit_repository.py` lines 24-69
- Importance: relevant
- Notes: show repository creation of `SaveIngredientFood`/`SaveIngredientUnit`, then `database.recipes.create(Recipe(... RecipeIngredient(food=...) / RecipeIngredient(unit=...)))`. They provide partial persisted patterns for food and unit references.

### `tests\integration_tests\user_recipe_tests\test_recipe_crud.py` — nested recipe/food patterns
- Symbols / ranges:
  - linear nested recipe setup: lines 634-690
  - referenced recipe deletion setup: lines 936-980
- Importance: adjacent
- Notes: demonstrates `database.ingredient_foods.create(SaveIngredientFood(...))` and creating recipes with `RecipeIngredient(food=food)` and `RecipeIngredient(referenced_recipe=recipe)`.

### `pyproject.toml` and `Taskfile.yml` — test runner conventions
- Symbols / ranges:
  - pytest config: `pyproject.toml` lines 97-105
  - dev deps include pytest/pytest-asyncio: `pyproject.toml` lines 64-82
  - task runner: `Taskfile.yml` lines 107-110 and 122-128
- Importance: critical
- Notes: tests are named `test_*`; default pytest addopts are `-ra -q`; asyncio fixture loop scope is function. Run with `task py:test -- <pytest args>` or directly as `uv run pytest <args>` per project convention.

## Existing patterns to reuse

- Recipe with ingredients: use `unique_user.repos.recipes.create(Recipe(user_id=..., group_id=..., name=..., recipe_ingredient=[RecipeIngredient(...)]))` from `fixture_recipe.py` lines 31-49 and shopping-list nested examples lines 280-316.
- Food creation: `database.ingredient_foods.create(SaveIngredientFood(name=..., group_id=unique_user.group_id))` from `test_group_shopping_lists.py` lines 258-278 and `test_food_repository.py` lines 14-26.
- Unit creation: either `database.ingredient_units.create(SaveIngredientUnit(...))` from `test_unit_repository.py` lines 29-41, or API `POST api_routes.units` from `test_group_shopping_list_items.py` lines 647-653.
- Meal plan creation: `CreatePlanEntry(date=..., entry_type="dinner", recipe_id=recipe_id).model_dump(by_alias=True)` with `date` and `recipeId` normalized before `POST api_routes.households_mealplans`, from `test_group_mealplan.py` lines 89-95.
- Shopping list creation: fixture `shopping_list` / `shopping_lists` from `fixture_shopping_lists.py` lines 24-65, or direct `POST api_routes.households_shopping_lists` from `test_group_shopping_lists.py` lines 35-46.
- Add recipes to list: `POST api_routes.households_shopping_lists_item_id_recipe(list_id)` with `utils.jsonify([ShoppingListAddRecipeParamsBulk(recipe_id=...).model_dump()])`, from `test_group_shopping_lists.py` lines 187-195 and 699-703.
- Assert shopping list items: `GET api_routes.households_shopping_lists_item_id(list_id)`, deserialize to dict or `ShoppingListOut`, inspect `listItems`/`list_items`, `quantity`, `note`, `recipeReferences`, from `test_group_shopping_lists.py` lines 197-210, 629-660, 705-739.

## Is "add meal plan to shopping list" already covered?

No direct backend/integration/unit test was found that creates meal plan entries and then invokes an "add meal plan to shopping list" flow. Existing coverage tests adding recipes or bulk recipes directly to a shopping list (`test_group_shopping_lists.py` lines 115-247, 581-739), and separate meal-plan CRUD tests (`test_group_mealplan.py` lines 80-99, 160-215). Code search in `tests\` found no `mealplans.*shopping` / `shopping.*mealplans` test, and `api_routes` exposes no direct meal-plan-to-shopping-list helper.

## Recommended test scaffolding

Place the new tests under `tests\integration_tests\`, likely `tests\integration_tests\user_household_tests\test_meal_plan_to_shopping_bug.py`, because it needs API + DB fixtures and existing household shopping/meal-plan route patterns.

Suggested shared helpers inside the new test file:

1. `create_food_unit_recipe(unique_user, ingredients)`
   - Create foods via `unique_user.repos.ingredient_foods.create(SaveIngredientFood(...))`.
   - Create units via `unique_user.repos.ingredient_units.create(SaveIngredientUnit(...))` or `POST api_routes.units`.
   - Persist `Recipe(... recipe_ingredient=[RecipeIngredient(food=food, unit=unit, quantity=qty, note=food.name), ...])`.
2. `create_plan(api_client, unique_user, date, entry_type, recipe)`
   - Follow `CreatePlanEntry(...).model_dump(by_alias=True)` plus string `date`/`recipeId` normalization.
3. `add_planned_recipes_to_list(...)`
   - If implementation has no dedicated backend meal-plan route, mimic the frontend/product action by querying the meal-plan date slice, extracting recipe IDs (including duplicates), and posting bulk `ShoppingListAddRecipeParamsBulk` entries to `households_shopping_lists_item_id_recipe`.
   - If the fix adds or identifies a direct route, use that route instead and add a matching `api_routes` helper only if route generation does not already provide one.
4. `items_for_food(list_out, food)` / `assert_single_item_quantity(list_out, food, unit, qty)`
   - Prefer matching on `foodId` and `unitId` when present, not just `note`, to satisfy the bug's merge-key requirements.

Five required tests:

- `test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients` (bug repro): create tomato qty=2 unit="each" and salt qty=1 unit="tsp" recipe; create Monday dinner and Wednesday lunch meal plans for same recipe; add the planned recipes to one shopping list; assert exactly one tomato item with quantity 4, not quantity 2 and not two tomato rows.
- `test_single_occurrence`: one meal plan entry for the recipe; add to list; assert each ingredient quantity equals the recipe quantity and list has one row per food+unit.
- `test_multiple_occurrences_same_unit`: parametrize occurrence count (e.g. 2 or 3); same food_id+unit_id across occurrences; assert one row with quantity `base_qty * occurrences`.
- `test_multiple_occurrences_different_units`: one recipe (or two planned recipes) produces same food with unit "each" and "gram"; assert two rows for the same food_id with distinct `unitId` values and original quantities preserved per unit.
- `test_different_food_same_name`: create two `SaveIngredientFood` records with identical `name` but different IDs, same unit; add through planned recipes; assert two rows keyed by distinct `foodId`, not a merged display-name row.

## Cross-perspective questions

- Does the product action call a backend endpoint dedicated to meal-plan-to-shopping-list, or does the frontend gather planned recipes and call the existing bulk add-recipes shopping-list endpoint?
- Should duplicate meal-plan entries for the same recipe be represented as repeated bulk recipe params, or a single param with `recipe_increment_quantity=N`?
- Does the service's canonical merge key use `food_id + unit_id`, and how does it behave for null `food_id`, null `unit_id`, or standardized compatible units?
- Should recipe scale factors from meal plans be covered now, or deferred as a separate regression given existing scale coverage in `test_shopping_list_add_recipe_scale`?
- For assertions, should tests require exact `recipeReferences` counts/scales in addition to shopping-list item quantities?
