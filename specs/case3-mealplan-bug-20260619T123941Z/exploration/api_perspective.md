# API Perspective — Case 3 Meal Plan to Shopping List Consolidation

## Route: meal plan entries are read for the planner
- **Path:** `GET /households/mealplans?start_date=...&end_date=...`
- **Symbols:** `GroupMealplanController.get_all`, `MealPlanAPI.getAll`/`BaseCRUDAPI.getAll`, `useMealplans.actions.getAll`
- **Line ranges:**
  - `mealie/routes/households/controller_mealplan.py:26-30`, `76-100`
  - `frontend/app/lib/api/user/group-mealplan.ts:7-14`
  - `frontend/app/composables/use-group-mealplan.ts:39-57`, `59-72`
- **Reason:** This route loads the dated meal plan entries used by the planner page. It does not mutate shopping lists, but it supplies the repeated recipe entries that later become the Add-to-List request.
- **Importance:** relevant

## UI/API trigger: "Add Meal Plan/Day to Shopping List"
- **Path:** no dedicated backend route; UI opens the shopping-list dialog, fetches lists via `GET /households/shopping/lists`, then submits to `POST /households/shopping/lists/{item_id}/recipe`.
- **Symbols:** `GroupMealPlanDayContextMenu`, `RecipeDialogAddToShoppingList.consolidateRecipesIntoSections`, `RecipeDialogAddToShoppingList.addRecipesToList`, `ShoppingListsApi.addRecipes`
- **Line ranges:**
  - `frontend/app/pages/household/mealplan/planner/view.vue:23-25`, `84-98`, `100-126`
  - `frontend/app/components/Domain/Household/GroupMealPlanDayContextMenu.vue:3-8`, `89-100`, `117-129`
  - `frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue:307-397`, `409-418`, `434-463`
  - `frontend/app/lib/api/user/group-shopping-lists.ts:16-20`, `28-34`
- **Reason:** The visible meal-plan action is implemented client-side: it passes the day's recipes into the generic recipe-to-shopping-list dialog. Duplicate recipes are converted to a larger `recipeIncrementQuantity` before the HTTP POST.
- **Importance:** critical

## Route: list existing shopping lists for the add dialog
- **Path:** `GET /households/shopping/lists`
- **Symbols:** `ShoppingListController.get_all`, `ShoppingListSummary`, `ShoppingListPagination`
- **Line ranges:**
  - `mealie/routes/households/controller_shopping_lists.py:156-160`, `176-184`
  - `mealie/schema/household/group_shopping_list.py:216-242`
- **Reason:** The meal-plan action first needs a target shopping list. The response is paginated `ShoppingListSummary` records, including recipe references and label settings.
- **Importance:** relevant

## Route: create an empty shopping list
- **Path:** `POST /households/shopping/lists`
- **Request schema:** `ShoppingListCreate` (`name`, `extras`, timestamps)
- **Response schema:** `ShoppingListOut`
- **Symbols:** `ShoppingListController.create_one`, `ShoppingListService.create_one_list`
- **Line ranges:**
  - `mealie/routes/households/controller_shopping_lists.py:186-198`
  - `mealie/schema/household/group_shopping_list.py:177-189`, `211-254`
  - `mealie/services/household_services/shopping_lists.py:541-554`
- **Reason:** This creates the destination list, but it is not the meal-plan conversion endpoint. The meal-plan conversion adds recipe ingredients to an already-selected list.
- **Importance:** adjacent

## Route: add multiple recipes' ingredients to an existing shopping list
- **Path:** `POST /households/shopping/lists/{item_id}/recipe`
- **Request schema:** `list[ShoppingListAddRecipeParamsBulk]`, each item has `recipe_id`, optional `recipe_increment_quantity`, and optional `recipe_ingredients` override.
- **Response schema:** `ShoppingListOut`
- **Symbols:** `ShoppingListController.add_recipe_ingredients_to_list`, `ShoppingListService.add_recipe_ingredients_to_list`
- **Line ranges:**
  - `mealie/routes/households/controller_shopping_lists.py:256-261`
  - `mealie/schema/household/group_shopping_list.py:288-296`, `250-285`
  - `mealie/services/household_services/shopping_lists.py:413-455`
- **Reason:** This is the primary HTTP route that the meal-plan dialog calls. It is the critical API surface for the bug because repeated meal-plan recipes arrive as repeated/bulk recipe add data or as a scaled recipe entry.
- **Importance:** critical

## Route: add a single recipe's ingredients to an existing shopping list (deprecated)
- **Path:** `POST /households/shopping/lists/{item_id}/recipe/{recipe_id}`
- **Request schema:** optional `ShoppingListAddRecipeParams` (`recipe_increment_quantity`, optional `recipe_ingredients`)
- **Response schema:** `ShoppingListOut`
- **Symbols:** `ShoppingListController.add_single_recipe_ingredients_to_list`
- **Line ranges:**
  - `mealie/routes/households/controller_shopping_lists.py:263-272`
  - `mealie/schema/household/group_shopping_list.py:288-296`
- **Reason:** This compatibility endpoint delegates to the bulk route after adding `recipe_id` to the body. It is relevant for regression coverage because it reaches the same service/consolidation path.
- **Importance:** relevant

## Controller decorators and permission gates
- **FastAPI decorators:** `@router.get`, `@router.post`, `@router.put`, `@router.delete` define OpenAPI paths and response models; `@controller(router)` converts class methods to FastAPI CBV endpoints.
- **Permission gate:** `ShoppingListController` and `GroupMealplanController` inherit `BaseCrudController -> BaseUserController`, which injects `get_current_user`, `get_integration_id`, group/household IDs, and group/household-scoped repositories. No route-specific `OperationChecks` gate is used on the recipe-add endpoint.
- **Line ranges:**
  - `mealie/routes/_base/controller.py:20-34`, `120-165`, `195-209`
  - `mealie/routes/_base/base_controllers.py:132-158`, `168-172`, `192-198`
  - `mealie/routes/households/controller_shopping_lists.py:98-103`, `159-163`, `256-261`
- **Reason:** Access control is inherited rather than declared on each route. This matters for tests because authenticated user context and repository scoping determine which lists and recipes are visible.
- **Importance:** critical

## Consolidation service methods
- **Path/symbols:** `ShoppingListService.get_shopping_list_items_from_recipe`, `bulk_create_items`, `can_merge`, `merge_items`, `add_recipe_ingredients_to_list`
- **Line ranges:**
  - `mealie/services/household_services/shopping_lists.py:45-72` (`can_merge`)
  - `mealie/services/household_services/shopping_lists.py:73-128` (`merge_items`)
  - `mealie/services/household_services/shopping_lists.py:154-223` (`bulk_create_items`)
  - `mealie/services/household_services/shopping_lists.py:323-411` (`get_shopping_list_items_from_recipe`)
  - `mealie/services/household_services/shopping_lists.py:413-455` (`add_recipe_ingredients_to_list`)
- **Reason:** `get_shopping_list_items_from_recipe` creates ingredient items with scaled quantities; `bulk_create_items` consolidates same-request items and merges into existing list items; `can_merge` and `merge_items` define the food/unit/checked/note merge behavior. These are the direct consolidation points for the quantity accumulation bug.
- **Importance:** critical

## Call-graph trace
1. Meal planner page loads entries: `useMealplans.actions.getAll` → `GET /households/mealplans` → `GroupMealplanController.get_all`.
2. User clicks the day context menu: `GroupMealPlanDayContextMenu` → `GET /households/shopping/lists` → `ShoppingListController.get_all` to choose a destination list.
3. Dialog builds request: `RecipeDialogAddToShoppingList.consolidateRecipesIntoSections` combines duplicate recipe sections and assigns `recipeScale`; `addRecipesToList` sends `ShoppingListAddRecipeParamsBulk[]`.
4. API client: `ShoppingListsApi.addRecipes` → `POST /api/households/shopping/lists/{id}/recipe`.
5. Controller: `ShoppingListController.add_recipe_ingredients_to_list` → `ShoppingListService.add_recipe_ingredients_to_list`.
6. Service: `get_shopping_list_items_from_recipe` creates scaled `ShoppingListItemCreate` records → `bulk_create_items` consolidates new items and merges into existing items via `can_merge` + `merge_items` → list-level recipe references are updated.

## Cross-perspective questions
- Does frontend consolidation by `recipe.slug` handle the same recipe appearing with different slug/id forms, or should API tests submit duplicate `recipe_id` rows directly to isolate backend behavior?
- Should regression tests cover both forms: duplicate bulk entries with `recipe_increment_quantity=1` and a single entry with `recipe_increment_quantity=2`?
- `can_merge` can merge compatible standard units, while the case spec says different units should not merge; is the desired behavior exact unit match for this bug, or existing unit-conversion behavior?
- `get_shopping_list_items_from_recipe` combines repeated ingredients inside one recipe by adding raw `ingredient.quantity` rather than scaled quantity at lines 393-397; should sub-recipe/scale tests verify this path?
