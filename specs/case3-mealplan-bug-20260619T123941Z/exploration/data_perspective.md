# Data Perspective — Case 3 (Shopping List Consolidation Bug)

## Artifact: shopping-list merge predicates and merge operation
- path: `mealie/services/household_services/shopping_lists.py`
- key symbols: `ShoppingListService.can_merge`, `ShoppingListService.merge_items`
- line_ranges: `45-71`, `73-128`
- importance: critical
- reason: `can_merge` defines the merge key semantics: unchecked items only, same `food_id`, and same/convertible `unit_id`; if `food_id` is absent it falls back to equal `note`. `merge_items` performs the quantity accumulation (`to_item.quantity += from_item.quantity` or unit-converted sum) and merges recipe references by `recipe_id` while adding `recipe_scale`.

## Artifact: bulk shopping item consolidation and persistence path
- path: `mealie/services/household_services/shopping_lists.py`
- key symbols: `ShoppingListService.bulk_create_items`, `self.list_items.page_all`, `self.list_items.create_many`, `self.list_items.update_many`
- line_ranges: `154-223`
- importance: critical
- reason: This method first consolidates newly generated recipe items with each other, then merges them into existing unchecked list items. It is the main data path where repeated meal-plan recipe ingredients either become one accumulated row or remain separate rows.

## Artifact: recipe-to-shopping-list item generation
- path: `mealie/services/household_services/shopping_lists.py`
- key symbols: `ShoppingListService.get_shopping_list_items_from_recipe`
- line_ranges: `323-411`
- importance: critical
- reason: Converts each `RecipeIngredient` into `ShoppingListItemCreate`, copying `food_id`, `unit_id`, `note`, `label_id`, and computing `quantity=ingredient.quantity * scale`. It also pre-merges duplicate ingredients within one recipe before the bulk create path runs.

## Artifact: add recipe ingredients entry point
- path: `mealie/services/household_services/shopping_lists.py`
- key symbols: `ShoppingListService.add_recipe_ingredients_to_list`
- line_ranges: `413-455`
- importance: critical
- reason: This is the service entry point for adding one or more recipes to a shopping list. It flattens all recipe additions into `items_to_create`, calls `bulk_create_items`, and separately updates list-level recipe reference quantities.

## Artifact: shopping list SQLAlchemy models
- path: `mealie/db/models/household/shopping_list.py`
- key symbols: `ShoppingListItemRecipeReference`, `ShoppingListItem`, `ShoppingList`, `ShoppingListRecipeReference`
- line_ranges: `26-40`, `51-98`, `101-116`, `147-180`
- importance: critical
- reason: These models define persisted shopping-list data. `ShoppingListItem.quantity` is a SQLAlchemy `Float` (`float | None`), and merge-relevant foreign keys are `food_id` and `unit_id`; recipe lineage is stored separately in recipe-reference tables with `recipe_id`, `recipe_quantity`, and `recipe_scale` as floats.

## Artifact: recipe ingredient SQLAlchemy model
- path: `mealie/db/models/recipe/ingredient.py`
- key symbols: `RecipeIngredientModel`
- line_ranges: `344-360`
- importance: critical
- reason: Recipe ingredients persist `recipe_id`, `unit_id`, `food_id`, and `quantity`. The quantity column is also SQLAlchemy `Float`, so precision behavior is floating-point rather than `Decimal`.

## Artifact: shopping list item Pydantic schema
- path: `mealie/schema/household/group_shopping_list.py`
- key symbols: `ShoppingListItemRecipeRefCreate`, `ShoppingListItemBase`, `ShoppingListItemCreate`, `ShoppingListItemUpdate`, `ShoppingListItemUpdateBulk`, `ShoppingListItemOut`
- line_ranges: `32-47`, `58-83`, `96-115`
- importance: relevant
- reason: These schemas show the service-layer quantity and reference types: shopping item `quantity` is `float`, `food_id`/`unit_id` are nullable UUIDs, and recipe references carry `recipe_id`, `recipe_quantity`, and nullable-float `recipe_scale`. The schema confirms there is no Decimal precision layer in shopping-list consolidation.

## Artifact: recipe ingredient Pydantic schema and precision constants
- path: `mealie/schema/recipe/recipe_ingredient.py`
- key symbols: `INGREDIENT_QTY_PRECISION`, `RecipeIngredientBase`, `RecipeIngredient.validate_quantity`
- line_ranges: `23-24`, `191-198`, `344-357`
- importance: relevant
- reason: Recipe ingredient quantities are `NoneFloat` (`float | None`) and incoming float quantities are rounded to `INGREDIENT_QTY_PRECISION = 3`. This is relevant to assertions around cumulative quantities and floating-point precision.

## Artifact: NoneFloat type alias
- path: `mealie/schema/_mealie/types.py`
- key symbols: `NoneFloat`
- line_ranges: `1-1`
- importance: adjacent
- reason: Confirms Mealie's nullable quantity alias is `float | None`, not `Decimal`. This supports the data-type finding for both recipe quantities and recipe scales.

## Artifact: repository factory shopping item repositories
- path: `mealie/repos/repository_factory.py`
- key symbols: `AllRepositories.group_shopping_list_item`, `AllRepositories.group_shopping_list_item_references`, `AllRepositories.group_shopping_list_recipe_refs`
- line_ranges: `317-345`, `347-358`
- importance: relevant
- reason: There is no bespoke `RepositoryShoppingItem` class in this checkout; shopping-list items use `HouseholdRepositoryGeneric[ShoppingListItemOut, ShoppingListItem]`. The service accesses it as `repos.group_shopping_list_item` and uses the adjacent generic repositories for item and list recipe references.

## Artifact: generic repository methods used by shopping item service
- path: `mealie/repos/repository_generic.py`
- key symbols: `RepositoryGeneric.create_many`, `RepositoryGeneric.update_many`, `RepositoryGeneric.delete_many`, `RepositoryGeneric.page_all`
- line_ranges: `195-208`, `228-244`, `271-287`, `315-355`
- importance: relevant
- reason: `bulk_create_items` depends on these generic methods to fetch unchecked existing rows, create non-merged rows, and persist merged rows. `page_all` applies normal repository filtering/scoping before returning `ShoppingListItemOut` models.

## Merge-key fields observed
- `checked`: checked items never merge (`can_merge`, lines `48-55`).
- `food_id`: must be equal; if present, matching foods can merge regardless of note (`can_merge`, lines `48-55`, `70-71`). Different `food_id` values do not merge even if display names match.
- `unit_id`: must be equal or both units must have convertible `standard_unit` values (`can_merge`, lines `57-68`). Same food with incompatible/different units does not merge.
- `note`: only part of the merge key when `food_id` is missing (`can_merge`, lines `70-71`); otherwise notes are combined during merge.
- `recipe_id`: not part of the shopping-item merge key. It is used only to merge recipe-reference metadata and add `recipe_scale` for repeated references (`merge_items`, lines `109-127`).
- `quantity`: not a key; it is accumulated by `merge_items` or by same-recipe duplicate handling (`merge_items`, lines `84-97`; `get_shopping_list_items_from_recipe`, lines `393-397`).

## Quantity type / precision
- Persisted shopping-list item quantity: SQLAlchemy `Float` / Python `float | None` (`mealie/db/models/household/shopping_list.py`, line `67`).
- Persisted recipe ingredient quantity: SQLAlchemy `Float` / Python `float | None` (`mealie/db/models/recipe/ingredient.py`, line `359`).
- Schema quantity type: `float` or `NoneFloat = float | None` (`group_shopping_list.py`, line `63`; `recipe_ingredient.py`, line `192`; `types.py`, line `1`).
- Recipe-ingredient schema rounds incoming float values to 3 decimals (`recipe_ingredient.py`, lines `23`, `353-357`); shopping-list merges themselves do not appear to round after addition.

## Likely bug location
The most likely bug surface for the reported meal-plan consolidation issue is `ShoppingListService.bulk_create_items` plus `merge_items` (`shopping_lists.py`, lines `154-223` and `73-128`), because duplicate recipe occurrences are flattened into multiple `ShoppingListItemCreate` rows and are expected to consolidate there. Evidence: `add_recipe_ingredients_to_list` generates all occurrence-derived rows first (`426-433`), `bulk_create_items` decides whether two rows merge via `can_merge` (`166-170`, `191-199`), and `merge_items` is where quantities are accumulated (`84-97`).

A second concrete data-risk location is `get_shopping_list_items_from_recipe` lines `393-397`: when duplicate ingredients inside the same recipe are pre-merged, it adds raw `ingredient.quantity` instead of `ingredient.quantity * scale`. That would undercount scaled recipe additions/sub-recipes, although the exact two-occurrence same-recipe meal-plan case should normally be handled by `bulk_create_items` if two create rows are produced.

## Cross-perspective questions
- API/controller perspective: which route is invoked by "Add Meal Plan to Shopping List", and does it send duplicate `ShoppingListAddRecipeParamsBulk` entries or pre-aggregate them into one entry with `recipe_increment_quantity = 2`?
- Test perspective: do existing integration tests cover adding the same recipe twice in one request versus adding it once in two separate requests?
- Domain perspective: should unit-convertible items (e.g., grams and kilograms) merge, or should the requested regression expectation "different units do not merge" override current `standard_unit` conversion behavior?
- Precision perspective: should shopping-list quantities be rounded after merge to `INGREDIENT_QTY_PRECISION`, or are raw float sums acceptable?
- Recipe-reference perspective: should repeated same-recipe references remain one reference with accumulated `recipe_scale`, or should individual meal-plan occurrences be traceable separately?
