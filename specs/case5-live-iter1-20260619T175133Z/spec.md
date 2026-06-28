# Feature Specification: Meal Plan auto-sync to Shopping List

**Feature ID**: `case5-live-iter1-20260619T175133Z`
**Schema version**: 1.0
**Status**: ⚠ NEEDS HUMAN REVIEW

## Summary

Add a per-household preference that, when enabled, automatically pushes the recipes scheduled in today's meal plan into a configured target shopping list. The scheduler runs the synchroniser once every minutely-bucket tick and gates execution on a 30-minute window plus a DB-level conditional UPDATE on `last_auto_synced_at`, so a household is synced at most once per local day even under multi-replica deployments. The implementation extends `HouseholdPreferencesModel` with five columns (enable flag, target list id, pantry filter flag, last-synced timestamp, IANA timezone string), adds an `is_pantry_staple` boolean to `IngredientFoodModel`, registers `sync_meal_plan_to_shopping_lists` via `SchedulerRegistry.register_minutely`, reuses `ShoppingListService.add_recipe_ingredients_to_list` so the existing merge / consolidate / checked-item semantics are inherited, and dispatches an `EventTypes.shopping_list_updated` notification through `EventBusService.dispatch`. A new PATCH endpoint accepts partial preference updates, and a new POST run-now endpoint lets a household administrator trigger the sync on demand. Three i18n keys are added under `mealplan.auto_sync.*` in `en-US.json` per the en-US-only convention.

## NEEDS_CLARIFICATION (blocking decisions)

### NC-001 — Pantry-staple scope: group column versus per-household association

**Conflict**: Input requirement 4 states 'add Boolean is_pantry_staple on the foods table'. IngredientFoodModel is group-scoped today, so a flag on that table is shared across every household in the group. Per-household semantics require a new households_to_pantry_staple_foods association table mirroring the households_to_ingredient_foods correction landed in PR 4616.

**Recommended default**: Implement the spec literally as a group-scoped Boolean column on IngredientFoodModel (FR-002). Surface the per-household alternative here so a reviewer can flip to the association-table design before coding begins.

**If rejected**: Drop FR-002 in its current form. Add an association table named households_to_pantry_staple_foods following the shape of households_to_ingredient_foods (ingredient.py:20-27 today). Add a relationship IngredientFoodModel.households_with_pantry_staple. Replace FR-022 with a route that toggles the association row rather than updating a column on the food.

**Related**: FR-002, FR-012, FR-022

### NC-002 — Default target shopping list resolution when auto_sync_target_shopping_list_id is null

**Conflict**: Input requirement 1 states the auto-sync target list defaults to 'the household's first active main list when null'. Mealie has no concept of an 'active main' shopping list — every ShoppingList is equal. The chosen ordering (creation order, alphabetical, smallest id) materially changes which list receives the sync.

**Recommended default**: Use the household's first shopping list ordered by ShoppingList.created_at ascending (FR-019). created_at is the column most likely to align with operator intuition of 'first' since lists are created in chronological order.

**If rejected**: Replace the created_at ORDER BY with the chosen alternative (alphabetical on ShoppingList.name, or smallest GUID lexicographic order, or a new is_default Boolean column with a maintenance route). Adjust FR-019 and the corresponding FR-019 test in FR-020 to assert the new ordering.

**Related**: FR-019

### NC-003 — PATCH semantics for explicit null in preference fields

**Conflict**: Input requirement 1 specifies a PATCH endpoint with exclude_unset semantics, but is silent on whether sending '{ "auto_sync_target_shopping_list_id": null }' should clear the field or be rejected. Pydantic's exclude_unset treats unset and null differently, but downstream HouseholdRepositoryGeneric.update may collapse both into a no-op depending on the persistence path chosen.

**Recommended default**: Interpret an explicit null as 'clear the field'. Use UpdateHouseholdPreferences.model_dump(exclude_unset=True) to build the diff, then apply it field-by-field to the loaded model. Document this in the PATCH route docstring.

**If rejected**: Reject any payload that contains a null value for a non-nullable column with HTTP 422 Unprocessable Entity via a pydantic field_validator. For nullable columns (auto_sync_target_shopping_list_id, last_auto_synced_at, timezone) treat null as clear; for non-nullable columns reject.

**Related**: FR-003, FR-005

## User Scenarios & Testing

### US-1 — Household administrator enables auto-sync (Priority: P1)

As a household administrator, I want to toggle on automatic meal-plan-to-shopping-list sync and pick the target shopping list, so my weekly grocery list is built without manual clicks.

**Why this priority**: Core configuration surface that gates every downstream behavior.

**Independent test**: PATCH /api/households/preferences with auto_sync_meal_plan_to_shopping_list=true and auto_sync_target_shopping_list_id=<list-id>; GET /api/households/preferences returns the same values.

**Acceptance Scenarios**:

1. **Given** a household with at least one shopping list and a user with can_manage_household=true, **When** the user PATCHes /api/households/preferences with auto_sync_meal_plan_to_shopping_list=true and a valid auto_sync_target_shopping_list_id, **Then** the response body contains the updated values and a subsequent GET returns identical values
2. **Given** a household preference document with auto_sync_meal_plan_to_shopping_list=true, **When** the user PATCHes /api/households/preferences with auto_sync_meal_plan_to_shopping_list=false, **Then** the scheduled task skips this household on its next tick

### US-2 — Scheduled task syncs today's meal plan into the shopping list (Priority: P1)

As a household member, I want today's planned recipes to appear in my chosen shopping list within five minutes of the scheduled trigger, so I do not have to remember to copy ingredients over manually.

**Why this priority**: Primary value delivery — without this the feature does nothing.

**Independent test**: Seed a GroupMealPlan row for today, enable auto_sync_meal_plan_to_shopping_list, invoke the registered task callback directly, assert the target list contains the recipe ingredients and last_auto_synced_at is set.

**Acceptance Scenarios**:

1. **Given** a household with auto_sync_meal_plan_to_shopping_list=true and a meal plan dated today in the household timezone, **When** the registered minutely task fires, **Then** the recipes' ingredients are merged into the configured target list and last_auto_synced_at is set to current UTC time
2. **Given** the task was already invoked once for today (last_auto_synced_at is set to today's local midnight or later), **When** the task fires again within the same household-local day, **Then** no new items are added and last_auto_synced_at is not bumped

### US-3 — Household administrator triggers an on-demand sync (Priority: P1)

As a household administrator, I want a manual run-now action so I can sync immediately after editing today's meal plan without waiting for the next scheduler tick.

**Why this priority**: Direct workflow gap that the input requirements call out explicitly.

**Independent test**: POST /api/households/preferences/auto-sync/run-now as a can_manage_household user; assert 200 and that the target list received the expected items.

**Acceptance Scenarios**:

1. **Given** a user with can_manage_household=true and a household configured for auto-sync, **When** the user POSTs to /api/households/preferences/auto-sync/run-now, **Then** the synchroniser executes for this household synchronously and returns a localized success payload
2. **Given** a user without can_manage_household permission, **When** the user POSTs to /api/households/preferences/auto-sync/run-now, **Then** the response status is 403 Forbidden and no shopping-list items are created

### US-4 — Pantry-staple filter skips already-stocked foods (Priority: P2)

As a household member, I want ingredients that I have marked as pantry staples to be skipped during auto-sync, so the shopping list only contains items I still need to buy.

**Why this priority**: Quality-of-life filter that reduces manual list pruning.

**Independent test**: Mark a food as is_pantry_staple=true, enable auto_sync_pantry_filter_enabled, run the task, assert no shopping-list item references that food_id.

**Acceptance Scenarios**:

1. **Given** auto_sync_pantry_filter_enabled=true and a recipe ingredient pointing to a food with is_pantry_staple=true, **When** the auto-sync task runs for the household, **Then** the pantry-staple ingredient is excluded from the items added to the target list

### US-5 — Event bus subscribers learn about each auto-sync (Priority: P2)

As an integration developer subscribed to shopping_list_updated events, I want to receive a payload describing each auto-sync action so my downstream webhook or Apprise alert fires reliably.

**Why this priority**: Existing notifier integrations rely on event_types for downstream automation.

**Independent test**: Mock the event bus, run the task end-to-end, assert dispatch was called once with EventTypes.shopping_list_updated and a payload containing the household_id and the list_id.

**Acceptance Scenarios**:

1. **Given** a household with a webhook subscriber listening for shopping_list_updated, **When** auto-sync runs successfully, **Then** EventBusService.dispatch is invoked exactly once with the household_id, group_id, and the shopping_list_id

### US-6 — Multi-tenant isolation across households (Priority: P2)

As a household administrator in household A, I want the assurance that running auto-sync never modifies a shopping list owned by household B, even when both households share a group.

**Why this priority**: Hard correctness boundary — a leakage bug is a critical incident.

**Independent test**: Create two households in the same group; configure auto-sync only for household A; run the task; assert household B's lists are byte-identical before and after.

**Acceptance Scenarios**:

1. **Given** two households A and B in the same group, both with shopping lists, **When** auto-sync runs for household A, **Then** every shopping_list row belonging to household B is unchanged

### US-7 — Household member marks a food as a pantry staple (Priority: P2)

As a household member with can_organize permission, I want to set is_pantry_staple on a food via the existing foods PUT endpoint so the pantry filter has data to act on.

**Why this priority**: Without a way to set the flag, the pantry-filter feature is unreachable.

**Independent test**: PUT /api/foods/{id} with is_pantry_staple=true; GET /api/foods/{id} returns the same value.

**Acceptance Scenarios**:

1. **Given** a user with can_organize=true, **When** the user PUTs an updated CreateIngredientFood payload with is_pantry_staple=true, **Then** the persisted row reflects the new flag and the response body returns the updated value

### US-8 — Household configures a timezone so today reflects the locale (Priority: P3)

As a household administrator in a non-UTC region, I want to set the household timezone so the daily auto-sync window respects my local midnight rather than the server's UTC midnight.

**Why this priority**: Required for correctness in non-UTC deployments; tagged P3 because a null timezone falls back to UTC and still works.

**Independent test**: Set HouseholdPreferences.timezone='Asia/Shanghai'; freeze the wall clock at 16:05 UTC; invoke the task; assert it picks up the GroupMealPlan with date=tomorrow_utc but today in Shanghai.

**Acceptance Scenarios**:

1. **Given** a household with timezone='Asia/Shanghai' and a meal plan dated 2026-06-20 (Shanghai local), **When** the task runs at 16:05 UTC on 2026-06-19 (i.e., 00:05 on 2026-06-20 in Shanghai), **Then** the meal plan for 2026-06-20 is selected as today and synced

### US-9 — Operator sees localized success and error messages (Priority: P2)

As an operator reading the API response or webhook payload, I want localized strings drawn from the en-US locale so the system message format matches every other Mealie endpoint.

**Why this priority**: Consistency with the repo-wide en-US-only locale convention.

**Independent test**: Trigger run-now with no active meal plan; assert the response body's detail equals the registered en-US.json string for mealplan.auto_sync.no_active_meal_plan.

**Acceptance Scenarios**:

1. **Given** a household with no meal plan for today, **When** run-now is invoked, **Then** the response contains the localized string for mealplan.auto_sync.no_active_meal_plan

## Requirements

### Functional Requirements

- **FR-001** [FR]: Extend HouseholdPreferencesModel with five columns: auto_sync_meal_plan_to_shopping_list (Boolean, server_default false), auto_sync_target_shopping_list_id (GUID FK to shopping_lists.id, nullable), auto_sync_pantry_filter_enabled (Boolean, server_default false), last_auto_synced_at (NaiveDateTime, nullable), and timezone (String, nullable, holding an IANA tz name).
  - Code references: `mealie/db/models/household/preferences.py` L16-44 (HouseholdPreferencesModel), `mealie/db/models/household/household.py` L29-97 (Household, preferences, group_id)
  - Related: US-1, US-2, US-8
- **FR-002** [FR]: Extend IngredientFoodModel with a new column is_pantry_staple (Boolean, server_default false). This column lives next to the deprecated on_hand column and remains group-scoped because IngredientFoodModel is group-scoped today.
  - Code references: `mealie/db/models/recipe/ingredient.py` L153-192 (IngredientFoodModel, on_hand)
  - Related: US-4, US-7
- **FR-003** [FR]: Extend UpdateHouseholdPreferences pydantic schema with the five new fields from FR-001 so the existing PUT route, the new PATCH route, and the persistence layer share one shape.
  - Code references: `mealie/schema/household/household_preferences.py` L10-22 (UpdateHouseholdPreferences)
  - Related: US-1
- **FR-004** [FR]: ReadHouseholdPreferences must expose the five new fields by virtue of inheriting from CreateHouseholdPreferences which inherits from UpdateHouseholdPreferences.
  - Code references: `mealie/schema/household/household_preferences.py` L32-40 (ReadHouseholdPreferences)
  - Related: US-1
- **FR-005** [FR]: Add PATCH /api/households/preferences on HouseholdSelfServiceController. The route accepts a partial body, applies exclude_unset semantics, gates on self.checks.can_manage_household(), and returns ReadHouseholdPreferences.
  - Code references: `mealie/routes/households/controller_household_self_service.py` L20-62 (HouseholdSelfServiceController, get_household_preferences, update_household_preferences), `mealie/routes/_base/checks.py` L6-26 (OperationChecks, can_manage_household)
  - Related: US-1
- **FR-006** [FR]: Preserve the existing PUT /api/households/preferences route so older clients that send a full UpdateHouseholdPreferences body continue to work without modification.
  - Code references: `mealie/routes/households/controller_household_self_service.py` L20-62 (HouseholdSelfServiceController, get_household_preferences, update_household_preferences)
  - Related: US-1
- **FR-007** [FR]: Implement a new task module mealie/services/scheduler/tasks/auto_sync_shopping.py exposing sync_meal_plan_to_shopping_lists() and register it inside start_scheduler via SchedulerRegistry.register_minutely alongside post_group_webhooks.
  - Code references: `mealie/services/scheduler/scheduler_registry.py` L13-48 (register_minutely, _minutely), `mealie/services/scheduler/tasks/__init__.py` L1-19 (create_mealplan_timeline_events), `mealie/app.py` L124-144 (start_scheduler, register_minutely)
  - Related: US-2
- **FR-008** [FR]: Inside sync_meal_plan_to_shopping_lists the task computes household-local now via ZoneInfo(prefs.timezone) when prefs.timezone is set, otherwise ZoneInfo('UTC'), and exits early when prefs.last_auto_synced_at is later than (household_local_today - 30 minutes). This bounds wakeup-to-effect latency to within one minutely tick (MINUTES_5 = 5 minutes).
  - Code references: `mealie/services/scheduler/scheduler_service.py` L16-81 (MINUTES_5, SchedulerService, run_minutely)
  - Related: US-2, US-8
- **FR-009** [FR]: Resolve the household timezone via ZoneInfo(prefs.timezone) when prefs.timezone is not null, otherwise ZoneInfo('UTC'). The fall-back is UTC rather than tzlocal() so the behavior is deterministic across replicas regardless of host timezone.
  - Code references: `mealie/services/scheduler/tasks/create_timeline_events.py` L1-37 (tzlocal, _create_mealplan_timeline_events_for_household), `mealie/db/models/_model_utils/datetime.py` L6-50 (NaiveDateTime, get_utc_now)
  - Related: US-8
- **FR-010** [FR]: Implement idempotency via a single SQL conditional UPDATE: UPDATE household_preferences SET last_auto_synced_at = :now_utc WHERE id = :id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local_midnight_utc). If the UPDATE returns row count zero the task aborts before reading meal plans. This DB-level compare-and-set protects against multi-replica double-sync without dialect-specific row locking.
  - Code references: `mealie/db/models/household/preferences.py` L16-44 (HouseholdPreferencesModel), `mealie/db/models/_model_utils/datetime.py` L6-50 (NaiveDateTime, get_utc_now)
  - Related: US-2
- **FR-011** [FR]: Push items via ShoppingListService.add_recipe_ingredients_to_list(list_id=auto_sync_target_shopping_list_id, recipe_items=[ShoppingListAddRecipeParamsBulk(recipe_id=mealplan.recipe_id, recipe_increment_quantity=1, recipe_ingredients=None) for each meal plan with a recipe]). This reuses the existing get_shopping_list_items_from_recipe + bulk_create_items pipeline so consolidate_ingredients, label propagation, and merge behavior are inherited unchanged.
  - Code references: `mealie/services/household_services/shopping_lists.py` L413-455 (add_recipe_ingredients_to_list), `mealie/db/models/household/mealplan.py` L55-77 (GroupMealPlan, recipe_id)
  - Related: US-2
- **FR-012** [FR]: When prefs.auto_sync_pantry_filter_enabled is true the recipe-ingredient list passed to add_recipe_ingredients_to_list is pre-filtered so any ingredient whose food.is_pantry_staple is true is omitted before items are created. Ingredients with food_id IS NULL are not affected by this filter.
  - Code references: `mealie/db/models/recipe/ingredient.py` L153-192 (IngredientFoodModel, on_hand)
  - Related: US-4
- **FR-013** [FR]: The existing ShoppingListService.can_merge logic returns False when either item is checked, so checked items in the target list are left intact and the new sync items are appended as additional rows rather than merged into a checked row.
  - Code references: `mealie/services/household_services/shopping_lists.py` L34-71 (ShoppingListService, can_merge), `mealie/db/models/household/shopping_list.py` L51-98 (ShoppingListItem, food_id, checked)
  - Related: US-2
- **FR-014** [FR]: Add POST /api/households/preferences/auto-sync/run-now on HouseholdSelfServiceController. The route gates on self.checks.can_manage_household(), invokes the same sync_meal_plan_to_shopping_lists for the current household synchronously, and returns the localized success payload referenced in FR-016.
  - Code references: `mealie/routes/households/controller_household_self_service.py` L20-62 (HouseholdSelfServiceController, get_household_preferences, update_household_preferences), `mealie/routes/_base/checks.py` L6-26 (OperationChecks, can_manage_household), `mealie/routes/_base/base_controllers.py` L132-172 (BaseUserController)
  - Related: US-3
- **FR-015** [FR]: After a successful sync (item_changes non-empty) the task calls EventBusService.dispatch with integration_id=DEFAULT_INTEGRATION_ID, group_id, household_id, event_type=EventTypes.shopping_list_updated, and document_data set to an EventShoppingListData subclass carrying the shopping_list_id.
  - Code references: `mealie/services/event_bus_service/event_bus_service.py` L42-105 (EventBusService, dispatch), `mealie/services/event_bus_service/event_types.py` L13-60 (EventTypes, shopping_list_updated), `mealie/services/event_bus_service/event_types.py` L88-91 (EventDocumentDataBase), `mealie/services/event_bus_service/event_types.py` L130-132 (EventShoppingListData)
  - Related: US-5
- **FR-016** [FR]: Add three i18n keys under the mealplan section of mealie/lang/messages/en-US.json: mealplan.auto-sync.success, mealplan.auto-sync.no-active-meal-plan, and mealplan.auto-sync.target-shopping-list-not-found. Only the en-US locale is touched per the en-US-as-source-of-truth repo convention.
  - Code references: `mealie/lang/messages/en-US.json` L34-36 (mealplan)
  - Related: US-9
- **FR-017** [FR]: Multi-tenant isolation is enforced because the task obtains AllRepositories with group_id and household_id set, and RepositoryMeals.get_today raises when household_id is not set. All writes go through repos scoped to that single household_id, so a task invocation for household A cannot reach household B's shopping_lists rows.
  - Code references: `mealie/repos/repository_meals.py` L11-21 (RepositoryMeals, get_today), `mealie/repos/repository_factory.py` L244-253 (household_preferences), `mealie/repos/repository_factory.py` L297-301 (meals), `mealie/repos/repository_factory.py` L139-141 (ingredient_foods)
  - Related: US-6
- **FR-018** [FR]: A single Alembic migration in mealie/alembic/versions/ adds the five household_preferences columns from FR-001, the is_pantry_staple column from FR-002, and an upgrade/downgrade pair using batch_alter_table for SQLite compatibility. Server defaults are used so the migration is non-blocking for large tables.
  - Code references: `mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py` L20-32 (upgrade, household_preferences)
  - Related: US-1, US-2, US-4, US-7
- **FR-019** [FR]: When auto_sync_target_shopping_list_id is null at sync time the task selects the first non-deleted shopping list belonging to the current household ordered by ShoppingList.created_at ascending. If the household has no shopping lists the task skips this household and logs at INFO level.
  - Code references: `mealie/db/models/household/shopping_list.py` L51-98 (ShoppingListItem, food_id, checked)
  - Related: US-2
- **FR-020** [NFR]: Add unit tests under tests/unit_tests/services/scheduler/tasks/test_auto_sync_shopping.py and integration tests under tests/integration_tests/user_household_tests/ covering: PATCH/PUT preference round-trip; task selects today's meal plan in household tz; idempotent second invocation is a no-op; pantry filter removes is_pantry_staple foods; run-now route requires can_manage_household; localized error returned when target list is missing. Use freezegun.freeze_time to control the wall clock.
  - Code references: `mealie/repos/repository_meals.py` L11-21 (RepositoryMeals, get_today)
  - Related: US-1, US-2, US-3, US-4, US-8, US-9
- **FR-021** [NFR]: Add a multi-tenant test under tests/integration_tests/user_household_tests/ that creates two households A and B in the same group, configures auto-sync only for A, invokes the task callback once, and asserts every row in household B's shopping_lists and shopping_list_items tables has byte-identical updated_at and content.
  - Code references: `mealie/repos/repository_factory.py` L244-253 (household_preferences), `mealie/repos/repository_factory.py` L297-301 (meals)
  - Related: US-6
- **FR-022** [FR]: Extend IngredientFoodsController.update_one and create_one paths to accept the new is_pantry_staple field via CreateIngredientFood / SaveIngredientFood. Persistence uses the existing self.mixins.update_one path with no new repository method required.
  - Code references: `mealie/routes/unit_and_foods/foods.py` L24-78 (IngredientFoodsController, update_one, create_one)
  - Related: US-7

## Success Criteria

- **SC-001**: Preference round-trip — PATCH then GET returns the new values
  - Metric: round_trip_value_equality | Threshold: exact match for all five new fields after PATCH then GET
- **SC-002**: Scheduler latency — registered task runs within one minutely tick of registration
  - Metric: elapsed_seconds_from_start_to_first_invocation | Threshold: <= 300 seconds (MINUTES_5 bucket)
- **SC-003**: Idempotency — task invoked twice in the same household-local day produces one merge
  - Metric: shopping_list_item_count_delta_after_second_invocation | Threshold: 0
- **SC-004**: Pantry filter — foods marked is_pantry_staple are absent from the appended items
  - Metric: count_of_appended_items_whose_food_id_is_in_pantry_staple_set | Threshold: 0
- **SC-005**: Event dispatch — exactly one shopping_list_updated event per successful sync
  - Metric: EventBusService.dispatch call count with EventTypes.shopping_list_updated | Threshold: 1 per successful sync invocation
- **SC-006**: Multi-tenant isolation — household B's rows are unchanged after household A's sync
  - Metric: byte_equality_of_household_b_shopping_lists_rows_before_and_after | Threshold: 100% rows equal
- **SC-007**: Localized error — missing target list returns the registered en-US string
  - Metric: response_body_detail_equals_en_us_mealplan_auto_sync_target_shopping_list_not_found | Threshold: exact string match against the en-US.json value
- **SC-008**: Timezone boundary — meal plan selected matches household-local today
  - Metric: get_today_tz_argument_equals_ZoneInfo_of_prefs_timezone | Threshold: ZoneInfo(prefs.timezone) when set else ZoneInfo('UTC')
- **SC-009**: Authorization — non-admin user receives 403 from PATCH and run-now
  - Metric: http_status_code_for_user_without_can_manage_household | Threshold: 403 for PATCH /preferences and POST /preferences/auto-sync/run-now
- **SC-010**: Migration — alembic upgrade and downgrade both succeed on a fresh test DB
  - Metric: alembic_upgrade_head_then_downgrade_minus_1_exit_code | Threshold: 0 for both invocations against the sqlite test DB
- **SC-011**: i18n key presence — three new keys exist with non-empty string values
  - Metric: count_of_present_non_empty_keys_under_mealplan_auto_sync | Threshold: 3
- **SC-012**: Merge fidelity — pre-existing checked rows in the target list are not modified
  - Metric: byte_equality_of_pre_existing_checked_shopping_list_items | Threshold: 100% rows equal

## Key Entities

- **HouseholdPreferences (extended)**: Per-household preference document with five new fields driving auto-sync: auto_sync_meal_plan_to_shopping_list, auto_sync_target_shopping_list_id, auto_sync_pantry_filter_enabled, last_auto_synced_at, timezone.
  - Fields: auto_sync_meal_plan_to_shopping_list: bool, auto_sync_target_shopping_list_id: UUID4 | None, auto_sync_pantry_filter_enabled: bool, last_auto_synced_at: datetime | None (NaiveDateTime, stored as UTC), timezone: str | None (IANA tz name)
  - References: Household, ShoppingList
- **IngredientFood (extended)**: Group-scoped food entity with one new boolean column is_pantry_staple driving the pantry filter.
  - Fields: is_pantry_staple: bool (server_default false)
  - References: Household, IngredientFoodModel
- **EventShoppingListData**: Existing event payload reused for the shopping_list_updated dispatch; carries shopping_list_id.
  - Fields: document_type: EventDocumentType.shopping_list, shopping_list_id: UUID4
  - References: EventBusService, EventTypes.shopping_list_updated

## Edge Cases

- No meal plan exists for today in the household timezone → RepositoryMeals.get_today returns an empty list; the task logs at INFO level, does not invoke add_recipe_ingredients_to_list, does not dispatch an event, and does not bump last_auto_synced_at (the conditional UPDATE only fires when items are appended).
- auto_sync_target_shopping_list_id is null at sync time → The task falls back per FR-019: it selects the household's first shopping list ordered by created_at ascending. When the household owns zero shopping lists the task logs and skips that household.
- auto_sync_target_shopping_list_id points to a deleted shopping_lists row → ShoppingListService.shopping_lists.get_one returns None; the task logs the localized mealplan.auto-sync.target-shopping-list-not-found message at WARNING level and skips this household without bumping last_auto_synced_at.
- A recipe ingredient has food_id IS NULL (note-only ingredient) → The pantry-filter predicate skips ingredients with food_id IS NULL and lets them pass through to add_recipe_ingredients_to_list unchanged. They will be merged on note equality per the existing can_merge contract.
- Household-local midnight boundary — wall clock is 23:55 UTC on 2026-06-19 while the household timezone is UTC+8 (already 07:55 on 2026-06-20) → ZoneInfo('Asia/Shanghai') resolves household_local_today to 2026-06-20; RepositoryMeals.get_today is called with tz=ZoneInfo('Asia/Shanghai') so the 2026-06-20 GroupMealPlan rows are selected even though the server UTC date is still 2026-06-19.
- Two replicas reach the conditional UPDATE simultaneously for the same household → Only one UPDATE returns row count one; the other returns zero and the second replica aborts before reading meal plans. No duplicate items, no duplicate events.
- Operator toggles auto_sync_meal_plan_to_shopping_list off while a task tick is mid-run for that household → The current tick completes because the prefs object was loaded at the top of the task; the next tick reads the new value and skips the household. last_auto_synced_at is set by the in-flight tick, which is harmless because the user disabled the sync.
- Household timezone is null → FR-009 falls back to ZoneInfo('UTC'); the task uses UTC midnight as the local-day boundary. This matches the documented NaiveDateTime convention which stores all datetimes as UTC.
- Pre-existing checked item in the target list shares a food_id with a new ingredient → ShoppingListService.can_merge returns False when either item is checked, so the new ingredient is appended as a fresh row rather than merged into the checked row.

## Assumptions

- Mealie's deployment runs at least one worker that owns the scheduler (the SchedulerService.start()) and the running worker is reachable from the PATCH and run-now HTTP routes via the shared database.
- freezegun==1.5.5 is already an installed dev dependency (verified in the test perspective exploration) and works with ZoneInfo on Python 3.12.
- The existing ShoppingListService.add_recipe_ingredients_to_list contract — recipe items merged via consolidate_ingredients, label propagation from food.label_id — is the intended sync behaviour; this spec does not re-derive merge semantics.
- PR 4616's households_to_ingredient_foods correction has landed on the working branch, so the spec may reference its association-table pattern as the per-household-scoping precedent for NC-001 escalation.
- The en-US locale file is the single source of truth for strings (per the copilot-instructions.md repo convention); other locale files are regenerated by Crowdin and are out of scope for this spec.

## Out of Scope

- Frontend (Nuxt 3) wiring for the new preference toggles, target list picker, and pantry-staple checkbox — covered by a follow-up frontend spec.
- Cross-household pantry-staple sharing semantics — escalated to NC-001 for reviewer decision.
- Backfilling last_auto_synced_at for existing households on migration upgrade — left as NULL so the first scheduler tick after upgrade triggers a sync for every enabled household.
- A new scheduler bucket (e.g. MINUTES_30) — the design reuses the existing register_minutely + internal 30-minute window check to avoid changing the SchedulerService surface area.
- PostgreSQL-specific row locking (SELECT FOR UPDATE SKIP LOCKED) — the conditional UPDATE in FR-010 already provides DB-level CAS that works on both SQLite and PostgreSQL.
- Modifications to GroupMealPlan or its repository beyond the existing get_today() call.
- Per-recipe quantity overrides or per-ingredient unit conversion beyond what add_recipe_ingredients_to_list already provides.

## Self-Concerns (writer self-reflection)

- **FR-008**: The internal 30-minute window plus the MINUTES_5 scheduler bucket means wakeup-to-effect latency is bounded by the next minutely tick after household-local midnight. Under heavy asyncio event-loop load that bound has been observed to slip by tens of seconds.
  - Evidence gap: No empirical measurement of run_minutely jitter under realistic Mealie workload has been captured in this repo. The 5-minute SLA in SC-002 is derived from the bucket constant rather than from a load test.
  - Suggested resolution: Add a smoke test that registers a noop callback, runs the scheduler for 10 minutes, and records the actual tick intervals. Compare against MINUTES_5 = 5 to confirm the SLA holds.
- **FR-020**: The freezegun-based timezone boundary test assumes ZoneInfo and freezegun interact consistently across DST transitions. The test fixture freezes a single UTC instant and translates it via ZoneInfo at runtime; a DST boundary between freeze time and household-local midnight could produce ambiguous local-time arithmetic.
  - Evidence gap: No existing Mealie test exercises freezegun across a DST boundary, so the regression risk is unmeasured.
  - Suggested resolution: Parametrise the timezone boundary test across pre-DST, mid-DST, and post-DST instants for at least one non-UTC zone such as America/New_York.
- **FR-010**: The conditional UPDATE relies on SQLite enforcing serializability under WAL mode for this single-row write. SQLite documents that concurrent writers serialize via a global write lock in WAL mode, but the Mealie test database initialisation has not been audited to confirm WAL is enabled.
  - Evidence gap: The mealie/db/db_setup.py initialisation path has not been re-read in this stage to confirm the WAL pragma. PostgreSQL test runs via task py:postgres are gated on a different code path that this spec did not enumerate.
  - Suggested resolution: Audit db_setup.py for journal_mode=WAL during the implementation phase, and add a pytest-xdist concurrent-call test that invokes the task on the same household_id from two threads to verify the CAS contract under SQLite.

---

_Generated by DevLoop spec phase — writer=claude-sonnet-4.6, reviewer=, iterations=1_