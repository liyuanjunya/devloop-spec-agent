# Architecture Review — v1

## Verdict
REJECT
The spec has blocking architecture gaps in tenant isolation and idempotency ordering. It also leaves a required per-household pantry-staple semantic unresolved, so implementation would likely ship cross-household behavioral leakage.

## Critical issues
### ARCH-C-1 (CRITICAL)
**Location**: spec.md FR-010 / Edge Cases
**Issue**: The CAS marker is acquired before the sync work, so any commit inside shopping-list mutation can persist `last_auto_synced_at` before all work is complete. Mealie repository methods commit inside `bulk_create_items`/`add_recipe_ingredients_to_list`, so a later failure can leave the household marked synced while list references/event dispatch are incomplete; this is the known marker-before-work idempotency bug pattern.
**Evidence**: `spec.md:187`: "If the UPDATE returns row count zero the task aborts before reading meal plans." `mealie/services/household_services/shopping_lists.py:433`: "item_changes = self.bulk_create_items(items_to_create)" and `mealie/repos/repository_generic.py:195-203`: "def create_many(self, data: Iterable[Schema | dict]) -> list[Schema]: ... self.session.add_all(new_documents) ... self.session.commit()".
**Fix**: Use a per-household/day claim that does not equal completion (row lock/lease/job table/status), perform all list mutations in a controlled transaction, then set `last_auto_synced_at` only after successful item creation, list-reference update, and event dispatch decision. Add failure/retry tests proving a mid-sync exception does not suppress the next run.

### ARCH-C-2 (CRITICAL)
**Location**: spec.md FR-011 / FR-017 / FR-019
**Issue**: The spec relies on scoped repositories but does not require validating a configured `auto_sync_target_shopping_list_id` belongs to the current household before passing it to `ShoppingListService.add_recipe_ingredients_to_list`. That service creates `ShoppingListItem` rows for the supplied `list_id` before it reads the list through the scoped shopping-list repo, so a stale/cross-household target id can write into another household's list.
**Evidence**: `spec.md:190`: "Push items via ShoppingListService.add_recipe_ingredients_to_list(list_id=auto_sync_target_shopping_list_id..." `spec.md:208`: "All writes go through repos scoped to that single household_id". But `mealie/services/household_services/shopping_lists.py:426-433`: "items_to_create = [...] ShoppingListItemCreate(shopping_list_id=list_id, ...) ... item_changes = self.bulk_create_items(items_to_create)" and `mealie/repos/repository_generic.py:195-203`: "self.session.add_all(new_documents) ... self.session.commit()".
**Fix**: Before syncing, resolve the target with the household-scoped shopping-list repo (`repos.group_shopping_lists.get_one(target_id)`) and abort if missing. Also validate PATCH rejects target list ids outside the current household, and add a multitenant test where household A configures B's list id and no B rows change.

### ARCH-C-3 (CRITICAL)
**Location**: spec.md FR-002 / NC-001 / US-6
**Issue**: The chosen `IngredientFoodModel.is_pantry_staple` column is group-scoped, contradicting the requirement that pantry-staple markers must not affect other households. In a group with multiple households sharing a food row, household A marking flour as a pantry staple would cause household B's auto-sync to skip flour too.
**Evidence**: `spec.md:15`: "IngredientFoodModel is group-scoped today, so a flag on that table is shared across every household in the group." `spec.md:163`: "This column lives next to the deprecated on_hand column and remains group-scoped". Existing model confirms this: `mealie/db/models/recipe/ingredient.py:157-162`: "group_id ... ForeignKey('groups.id')" and "households_with_ingredient_food ... secondary=households_to_ingredient_foods".
**Fix**: Do not use a group-wide boolean for household pantry state. Model pantry staples with a household-food association table (parallel to `households_to_ingredient_foods`) or another household-scoped table, update schemas/routes accordingly, and test that two households in one group can set different staple state for the same food.

## High issues
### ARCH-H-1 (HIGH)
**Location**: spec.md Summary / FR-015 / US-5
**Issue**: The event plan does not define the requested `MealPlanAutoSyncedToShopping` payload and does not actually include `household_id`, `added_item_count`, or `skipped_pantry_count` in webhook-visible `document_data`. Dispatch scoping prevents broadcast leakage, but subscribers cannot distinguish an auto-sync from an ordinary shopping-list update or audit the counts requested by the input.
**Evidence**: `spec.md:9`: "dispatches an `EventTypes.shopping_list_updated` notification". `spec.md:202-203`: "document_data set to an EventShoppingListData subclass carrying the shopping_list_id." Existing payload is only `shopping_list_id`: `mealie/services/event_bus_service/event_types.py:130-132`: "class EventShoppingListData... shopping_list_id: UUID4".
**Fix**: Add a dedicated event/document data shape (or explicit subtype fields) for auto-sync with household_id, shopping_list_id, added_item_count, skipped_pantry_count, and no recipe/item details from other households. Register/migrate subscriber fields if a new EventTypes member is used.

### ARCH-H-2 (HIGH)
**Location**: spec.md FR-001 / FR-008
**Issue**: The spec drops the required per-household `auto_sync_run_time` preference and hard-codes the local-day boundary/midnight behavior. This prevents households from configuring the requested HH:MM run time and makes the 30-minute window semantics only correct for midnight.
**Evidence**: `input.md:22`: "auto_sync_run_time: str（24h 制 HH:MM，默认 `\"00:00\"`，per-household 可配置". `spec.md:160`: the five columns are "auto_sync_meal_plan_to_shopping_list ... auto_sync_pantry_filter_enabled ... last_auto_synced_at ... timezone" with no run-time field. `spec.md:181`: the task exits based on "household_local_today - 30 minutes".
**Fix**: Add `auto_sync_run_time` with validation for HH:MM, compute the household-local scheduled instant for that day, gate on that 30-minute window, and keep `last_auto_synced_at` comparisons aligned to the scheduled local date.

## Medium issues
### ARCH-M-1 (MEDIUM)
**Location**: spec.md FR-005 / NC-003
**Issue**: PATCH semantics are left partially unresolved and may not fit Mealie's current generic update path, which uses `model_dump()` and commits a full update. A partial PATCH needs a separate schema or explicit diff application to avoid resetting unspecified preferences to defaults.
**Evidence**: `spec.md:37`: "Use UpdateHouseholdPreferences.model_dump(exclude_unset=True) to build the diff". Existing PUT route uses the generic update path: `mealie/routes/households/controller_household_self_service.py:58-62`: "def update_household_preferences(...): ... return self.repos.household_preferences.update(self.household_id, new_pref)" and `mealie/repos/repository_generic.py:220-225`: "new_data = ... new_data.model_dump() ... entry.update(...) ... self.session.commit()".
**Fix**: Define an explicit partial update schema with all fields optional, use `model_dump(exclude_unset=True)`, and apply only those keys to the loaded household preference row.

## Self-concerns verdict
The writer's concerns are valid but under-severity. FR-010 is not just an evidence gap; with Mealie's commit-in-repository pattern it is a blocking idempotency design issue. NC-001 must be resolved before coding because the selected group-scoped food column violates the multitenant pantry-staple requirement.

## Summary
- Critical: 3 | High: 2 | Medium: 1 | Low: 0
- Overall: FAIL
