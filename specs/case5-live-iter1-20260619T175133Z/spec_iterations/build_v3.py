"""Build spec_v3 from spec_v2 by applying META-V2-001 through META-V2-012.

Run from devloop root:
    python specs/case5-live-iter1-20260619T175133Z/spec_iterations/build_v3.py
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(r"C:\Users\v-liyuanjun\source\repos\devloop")
SPEC_DIR = ROOT / "specs" / "case5-live-iter1-20260619T175133Z" / "spec_iterations"
MEALIE = pathlib.Path(r"C:\Users\v-liyuanjun\Downloads\mealie")

sys.path.insert(0, str(ROOT))

V2 = SPEC_DIR / "spec_v2.json"
V3_JSON = SPEC_DIR / "spec_v3.json"
V3_MD = SPEC_DIR / "spec_v3.md"


def main() -> None:
    data = json.loads(V2.read_text(encoding="utf-8"))

    # ----- metadata: bump iterations to 3 ------------------------------------
    data["metadata"]["iterations"] = 3

    # ----- summary: reflect META-V2-001 (CAS-before-side-effects) and
    #               META-V2-005 (HTTP 204 contract) ----------------------------
    data["summary"] = (
        "Add a per-household preference that, when enabled, automatically pushes "
        "the recipes scheduled in today's meal plan into a configured target "
        "shopping list. Per-household state lives on `HouseholdPreferencesModel` "
        "(four client-writable columns plus a server-owned `last_auto_synced_at` "
        "idempotency marker) and on a new `household_pantry_staples(household_id, "
        "food_id)` association table with `ondelete='CASCADE'` on both FKs, "
        "parallel to (but deliberately deviating from) `households_to_ingredient_foods` "
        "which omits CASCADE. The scheduler is registered via "
        "`SchedulerRegistry.register_minutely` (the existing 5-minute bucket) and "
        "each tick computes a household-local `scheduled_local_instant = "
        "today_in_household_tz at auto_sync_run_time`, gating execution to runs "
        "whose `household_local_now()` falls inside `[scheduled_local_instant, "
        "scheduled_local_instant + 30 minutes)`. Idempotency is enforced by a "
        "single conditional UPDATE on `last_auto_synced_at` issued BEFORE any "
        "shopping-list mutation, inside the same DB transaction as the "
        "side effects: if the UPDATE affects 0 rows, the transaction commits "
        "empty and the worker returns without writing items or dispatching an "
        "event; if it affects 1 row, the worker proceeds to "
        "`bulk_create_items` + recipe-reference update + event dispatch in the "
        "same transaction, and any exception rolls back the CAS too. "
        "Pantry filtering is unconditional and operates on the fully-flattened "
        "ingredient list (including sub-recipes via the recursive expansion at "
        "`shopping_lists.py:343-355`), with the per-household predicate sourced "
        "from the new association table. The canonical merge seam is "
        "`ShoppingListService.bulk_create_items` (`shopping_lists.py:154-220`), "
        "which already accumulates quantity into existing unchecked `(food_id, "
        "unit_id)` rows via `can_merge`+`merge_items`. A new "
        "`EventTypes.mealplan_auto_synced_to_shopping` event carries "
        "`EventMealPlanAutoSyncedData(operation, household_id, shopping_list_id, "
        "added_item_count, skipped_pantry_count)` and is dispatched exactly "
        "once per CAS winner. The subscriber column "
        "`mealplan_auto_synced_to_shopping` is added to "
        "`group_events_notifier_options` (real table name; v2 wrongly said "
        "`group_event_notifier_options`) AND to "
        "`GroupEventNotifierOptionsModel` ORM AND to "
        "`GroupEventNotifierOptions` Pydantic schema so "
        "`AppriseEventListener.get_subscribers` can resolve the per-event flag. "
        "New routes: `PATCH /api/households/preferences` (partial update via "
        "`HouseholdPreferencesPartialUpdate` with `model_config = "
        "ConfigDict(extra='forbid')` so unknown fields like `last_auto_synced_at` "
        "are rejected with 422) and `POST /api/households/preferences/"
        "auto-sync-shopping/run-now` (household-admin only, "
        "`force=True` replaces the CAS with an unconditional UPDATE, "
        "HTTP 200 with EXACTLY `{added_count, skipped_pantry_count, "
        "target_list_id, run_at}` on success, HTTP 204 No Content on "
        "no-meal-plan / no-target-list precondition failure). The PATCH "
        "handler applies the diff via a column-set UPDATE that targets "
        "only `diff` keys so the server-owned marker is structurally "
        "protected from full-model writeback. Three i18n keys are added to "
        "the en-US namespace `auto-sync.no-meal-plan-today`, "
        "`auto-sync.no-target-list`, `auto-sync.already-synced-today` in "
        "`mealie/lang/messages/en-US.json` (only en-US is editable per "
        "`.github/copilot-instructions.md`; the other 40+ Crowdin-managed "
        "locales MUST NOT be modified). The migration also creates a "
        "FK constraint `fk_household_preferences_auto_sync_target` from "
        "`auto_sync_target_shopping_list_id` to `shopping_lists.id` with "
        "`ondelete='SET NULL'` so hard-deleting a list clears the field."
    )

    # ----- NC-003: PATCH semantics now explicitly mention column-set UPDATE ---
    for nc in data["needs_clarification"]:
        if nc["id"] == "NC-003":
            nc["recommended_default"] = (
                "Define `HouseholdPreferencesPartialUpdate(MealieModel)` (FR-004) with "
                "all four writable fields as `Optional[...] = None`, EXCLUDING "
                "`last_auto_synced_at`, AND declare `model_config = "
                "ConfigDict(extra='forbid')` directly on the schema class so "
                "unknown fields are rejected with HTTP 422. Apply the diff via "
                "`model_dump(exclude_unset=True)` and merge into the DB row via a "
                "column-set UPDATE: "
                "`session.execute(update(HouseholdPreferencesModel).where("
                "HouseholdPreferencesModel.household_id == self.household_id"
                ").values(**diff))` — NOT through the generic `repository_generic.update()` "
                "full-model path which would otherwise rewrite all columns including the "
                "server-owned marker. The existing PUT body (`UpdateHouseholdPreferences` "
                "at `mealie/schema/household/household_preferences.py:10-22`) is "
                "extended with the four writable fields but also omits "
                "`last_auto_synced_at`. The Read schema retains the marker for "
                "diagnostics. An explicit `null` for "
                "`auto_sync_target_shopping_list_id` (nullable column) clears the "
                "field; an explicit `null` for `auto_sync_meal_plan_to_shopping` "
                "(non-null column) is rejected with HTTP 422."
            )

    # ----- Helper: locate FR by id ------------------------------------------
    frs = {fr["id"]: fr for fr in data["functional_requirements"]}
    scs = {sc["id"]: sc for sc in data["success_criteria"]}

    # =====================================================================
    # META-V2-007: FR-002 ondelete=CASCADE deviation documented
    # =====================================================================
    frs["FR-002"]["text"] = (
        "Add a new association table `household_pantry_staples(household_id GUID FK "
        "households.id ondelete='CASCADE', food_id GUID FK ingredient_foods.id "
        "ondelete='CASCADE', UNIQUE (household_id, food_id))`. The column shape and "
        "uniqueness constraint follow the parallel "
        "`households_to_ingredient_foods` (mealie/db/models/recipe/ingredient.py:21-27), "
        "but the new table deliberately adds `ondelete='CASCADE'` to both FKs — the "
        "cited parallel table omits ondelete entirely, and a repo-wide grep of "
        "`mealie/` confirms no existing table uses `ondelete='CASCADE'`. The CASCADE "
        "is required by the deleted-food edge case so that "
        "`IngredientFoodsController.delete_one` does not raise IntegrityError on "
        "lingering pantry-staple rows. Add a new relationship "
        "`IngredientFoodModel.households_with_pantry_staple` paired with a "
        "back-reference `Household.pantry_staple_foods` so the secondary join works "
        "in both directions. NOT a column on `IngredientFoodModel` (which is "
        "group-scoped at mealie/db/models/recipe/ingredient.py:153-192 and would "
        "leak across households per NC-001). The membership row IS the staple flag "
        "— INSERT marks a food as a staple for that household; DELETE clears it."
    )

    # =====================================================================
    # META-V2-003: FR-004 add extra='forbid'
    # =====================================================================
    frs["FR-004"]["text"] = (
        "Add a new pydantic schema `HouseholdPreferencesPartialUpdate(MealieModel)` "
        "in `mealie/schema/household/household_preferences.py` whose every field is "
        "`Optional[...] = None`. The four new auto-sync fields appear as "
        "`auto_sync_meal_plan_to_shopping: bool | None = None`, "
        "`auto_sync_target_shopping_list_id: UUID4 | None = None`, "
        "`auto_sync_run_time: str | None = None`, `timezone: str | None = None`. "
        "The schema MUST also declare `model_config = ConfigDict(extra='forbid', "
        "alias_generator=camelize, populate_by_name=True)` directly on the "
        "`HouseholdPreferencesPartialUpdate` class so unknown fields (e.g. a client "
        "attempting to PATCH `last_auto_synced_at`) are rejected by pydantic with "
        "HTTP 422 `validation_error[extra_forbidden]`. `MealieModel.model_config` "
        "(mealie/schema/_mealie/mealie_model.py:45-53) only sets `alias_generator` "
        "and `populate_by_name=True` so the `extra='forbid'` MUST be declared on "
        "this specific schema and not globally on MealieModel (which would break "
        "every other route in the codebase). The PATCH route (FR-006) applies the "
        "diff via `payload.model_dump(exclude_unset=True)` so unset fields are not "
        "touched. An explicit JSON `null` for `auto_sync_target_shopping_list_id` "
        "(nullable column) clears the field; an explicit `null` for "
        "`auto_sync_meal_plan_to_shopping` (non-null column) is rejected with HTTP "
        "422. The schema MUST NOT include `last_auto_synced_at` for the same reason "
        "as FR-003."
    )
    # add citation to mealie_model.py
    frs["FR-004"]["code_references"] = [
        {
            "path": "mealie/schema/household/household_preferences.py",
            "symbols": ["UpdateHouseholdPreferences", "CreateHouseholdPreferences"],
            "line_ranges": [[10, 25]],
            "snippet": None,
        },
        {
            "path": "mealie/schema/_mealie/mealie_model.py",
            "symbols": ["MealieModel", "model_config"],
            "line_ranges": [[45, 53]],
            "snippet": None,
        },
    ]

    # =====================================================================
    # META-V2-004: FR-006 use column-set UPDATE instead of full-model write
    # =====================================================================
    frs["FR-006"]["text"] = (
        "Add a new route `PATCH /api/households/preferences` on "
        "`HouseholdSelfServiceController` "
        "(mealie/routes/households/controller_household_self_service.py:20-62). Body "
        "type: `HouseholdPreferencesPartialUpdate` (FR-004). Guard: "
        "`self.checks.can_manage_household()` (mealie/routes/_base/checks.py:23-26). "
        "Pipeline: (1) parse the body — pydantic rejects unknown fields with HTTP "
        "422 because of the schema-level `extra='forbid'` (FR-004); (2) compute "
        "`diff = payload.model_dump(exclude_unset=True)`; if `diff` is empty, "
        "return the current row unchanged; (3) if `'auto_sync_target_shopping_list_id' "
        "in diff` and the value is not None, look up "
        "`self.repos.group_shopping_lists.get_one(diff['auto_sync_target_shopping_list_id'])` "
        "using the household-scoped repo and raise HTTP 422 if it returns None "
        "(cross-household ids are filtered out by the scope) — per FR-014 / NC-001 "
        "this is the PATCH-time ownership validation; (4) issue a column-set UPDATE "
        "that writes ONLY the `diff` keys: `self.repos.session.execute("
        "update(HouseholdPreferencesModel).where("
        "HouseholdPreferencesModel.household_id == self.household_id"
        ").values(**diff)); self.repos.session.commit()`. This bypasses the "
        "generic `repository_generic.update()` full-model path "
        "(`mealie/repos/repository_generic.py` `update`) which would otherwise "
        "serialize the loaded read object — including the server-owned "
        "`last_auto_synced_at` — and clobber concurrent scheduler writes. The "
        "structural guarantee is: because `diff` is built from "
        "`HouseholdPreferencesPartialUpdate.model_dump(exclude_unset=True)` and "
        "that schema does not declare `last_auto_synced_at`, the marker key is "
        "never in `diff` and therefore never in `values(**diff)`; (5) re-fetch the "
        "row via `self.repos.household_preferences.get_one(self.household_id, "
        "'household_id')`; (6) return "
        "`ReadHouseholdPreferences.model_validate(refetched)`. Response model: "
        "`ReadHouseholdPreferences`."
    )

    # =====================================================================
    # META-V2-009: FR-009 pin per-household enumeration query, add SC-024 link
    # =====================================================================
    frs["FR-009"]["text"] = (
        "Each `auto_sync_meal_plan_to_shopping_lists()` tick first enumerates "
        "enabled households via: `enabled_households = session.execute("
        "select(Household).join(HouseholdPreferencesModel, "
        "HouseholdPreferencesModel.household_id == Household.id).where("
        "HouseholdPreferencesModel.auto_sync_meal_plan_to_shopping == True"
        ")).scalars().all()`. Per household: build a scoped repos via "
        "`repos = get_repositories(session, group_id=household.group_id, "
        "household_id=household.id)` (mealie/repos/all_repositories.py:8-11) "
        "so every downstream query (FR-010/FR-011/FR-014) is bounded by "
        "(group_id, household_id). Resolve `tz = "
        "ZoneInfo(household.preferences.timezone) if "
        "household.preferences.timezone else ZoneInfo('UTC')`, compute "
        "`household_local_now = datetime.now(tz)`, parse `auto_sync_run_time` "
        "via `datetime.strptime(value, '%H:%M').time()`, build "
        "`scheduled_local_instant = household_local_now.replace("
        "hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)`. "
        "Gate: skip unless `scheduled_local_instant <= household_local_now < "
        "scheduled_local_instant + timedelta(minutes=30)`. The 30-minute window "
        "covers the worst-case 5-minute scheduler tick interval (MINUTES_5 per "
        "FR-008) with margin for slow processing. The manual run-now path "
        "(FR-020) sets `force=True` and bypasses the gate."
    )
    frs["FR-009"]["code_references"] = [
        {
            "path": "mealie/services/scheduler/scheduler_service.py",
            "symbols": ["MINUTES_5", "run_minutely"],
            "line_ranges": [[15, 17], [77, 81]],
            "snippet": None,
        },
        {
            "path": "mealie/repos/all_repositories.py",
            "symbols": ["get_repositories"],
            "line_ranges": [[1, 11]],
            "snippet": None,
        },
        {
            "path": "mealie/db/models/household/household.py",
            "symbols": ["Household"],
            "line_ranges": [[29, 50]],
            "snippet": None,
        },
        {
            "path": "mealie/db/models/household/preferences.py",
            "symbols": ["HouseholdPreferencesModel", "household_id"],
            "line_ranges": [[16, 44]],
            "snippet": None,
        },
    ]
    frs["FR-009"]["related_success_criteria"] = ["SC-004", "SC-024"]

    # =====================================================================
    # META-V2-001: FR-011 + FR-012 rewrite (CAS BEFORE side effects)
    # =====================================================================
    frs["FR-011"]["text"] = (
        "Critical ordering — CAS BEFORE side effects, all in one transaction: "
        "(1) resolve preconditions FIRST — target list lookup via household-scoped "
        "`self.repos.group_shopping_lists.get_one(target_id)` (returns None if the "
        "id does not belong to this household, per FR-014), today's meal plan via "
        "`repos.meals.get_today(tz=tz)` (FR-010); (2) IF target lookup returns None "
        "OR meal plan is empty: log the i18n warning (auto-sync.no-target-list or "
        "auto-sync.no-meal-plan-today per FR-022), DO NOT bump `last_auto_synced_at`, "
        "return; (3) open a single DB transaction "
        "(`session.begin()` or `with session.begin_nested()` — the existing "
        "scheduler context already owns the session); (4) inside the transaction "
        "issue the conditional CAS UPDATE specified in FR-012 — `cas_rows = "
        "session.execute(update(HouseholdPreferencesModel).where(...).values("
        "last_auto_synced_at=now_naive_utc)).rowcount`; if "
        "`cas_rows == 0` (another replica won this day's race, OR a non-concurrent "
        "second invocation on the same day), COMMIT the empty transaction and "
        "return — NO `bulk_create_items` call, NO event dispatch, NO `recipe_references` "
        "update; (5) if `cas_rows == 1` (CAS winner), build the "
        "`ShoppingListAddRecipeParamsBulk` items (FR-015) and call "
        "`ShoppingListService.add_recipe_ingredients_to_list` "
        "(mealie/services/household_services/shopping_lists.py:413-455) which "
        "internally delegates to `bulk_create_items` "
        "(mealie/services/household_services/shopping_lists.py:154-220) and updates "
        "the list-level `recipe_references`; (6) dispatch the event (FR-021) via "
        "`session.commit()` followed by `EventBusService.dispatch(...)`, OR via "
        "SQLAlchemy `event.listens_for(session, 'after_commit')` hook attached at "
        "step 3 — either way the dispatch happens exactly once per CAS winner and "
        "never on the loser. Any exception during steps 4-6 raises out of the "
        "transaction context, which rolls back the CAS UPDATE as well as the "
        "`bulk_create_items` writes, so the marker reverts to its prior value and "
        "the next scheduler tick retries. The manual run-now path (FR-020) calls "
        "this same pipeline with `force=True`, which replaces step 4's conditional "
        "WHERE with an unconditional UPDATE that ALWAYS affects 1 row (so the "
        "force path always proceeds to step 5)."
    )
    frs["FR-011"]["related_success_criteria"] = ["SC-007", "SC-017", "SC-025"]

    frs["FR-012"]["text"] = (
        "Idempotency under multi-replica deployment uses a conditional UPDATE "
        "issued INSIDE the FR-011 transaction BEFORE any shopping-list mutation: "
        "`UPDATE household_preferences SET last_auto_synced_at = :now_naive_utc "
        "WHERE id = :pref_id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < "
        ":today_local_midnight_utc)`. `:today_local_midnight_utc` is computed as "
        "`datetime.combine(household_local_now.date(), time.min, tzinfo=tz)"
        ".astimezone(UTC).replace(tzinfo=None)` so the comparison runs against a "
        "naive-UTC datetime matching the `NaiveDateTime` column type "
        "(mealie/db/models/_model_base.py:18-23). If the UPDATE affects 0 rows, "
        "the household was already synced today (by another replica earlier in the "
        "same tick, or by a previous scheduler tick) — FR-011 step 4 catches "
        "`rowcount == 0` and SHORT-CIRCUITS: COMMIT the empty transaction and "
        "return without calling `bulk_create_items` or `EventBusService.dispatch`. "
        "Because the CAS happens BEFORE side effects, a CAS loser performs zero "
        "writes — `merge_items` (mealie/services/household_services/shopping_lists.py:73-128) "
        "would sum quantities if called twice (sums into to_item.quantity at L96), so it "
        "is critical that the loser never reaches the merge code path. The "
        "force-mode (FR-020) replaces the WHERE clause with `WHERE id = :pref_id` "
        "(unconditional) so the CAS always affects 1 row and the force path "
        "always proceeds to side effects. Transaction-rollback semantics: if "
        "`bulk_create_items` or the event dispatch raises, the rollback reverts "
        "the CAS UPDATE as well, so the marker stays at its prior value and the "
        "next scheduler tick retries."
    )
    frs["FR-012"]["code_references"] = [
        {
            "path": "mealie/db/models/_model_base.py",
            "symbols": ["SqlAlchemyBase", "created_at", "NaiveDateTime"],
            "line_ranges": [[18, 23]],
            "snippet": None,
        },
        {
            "path": "mealie/services/household_services/shopping_lists.py",
            "symbols": ["merge_items", "bulk_create_items"],
            "line_ranges": [[73, 128], [154, 220]],
            "snippet": None,
        },
    ]

    # =====================================================================
    # META-V2-001: FR-018 — drop the "CAS race is safe because of merge"
    # justification; the new safety is from CAS-before-side-effects
    # =====================================================================
    frs["FR-018"]["text"] = (
        "Append-only / merge contract preservation: incoming auto-sync items MUST "
        "flow through `can_merge` "
        "(mealie/services/household_services/shopping_lists.py:45-71) and "
        "`merge_items` (mealie/services/household_services/shopping_lists.py:73-128) "
        "rather than direct INSERTs. `can_merge` short-circuits on (A) either item "
        "`checked=true`, (B) mismatched `food_id`, (C) mismatched `unit_id` with no "
        "compatible `UnitConverter.can_convert` path. Auto-sync therefore: (1) "
        "NEVER touches checked rows; (2) merges into existing unchecked rows with "
        "matching `(food_id, unit_id)`; (3) creates a fresh row only when no merge "
        "candidate exists. This is the same contract used by every other Mealie "
        "shopping-list write path. Note: `merge_items` SUMS quantities at line 96 "
        "(`to_item.quantity += from_item.quantity`), so multi-replica safety must "
        "be enforced UPSTREAM by the CAS in FR-012 — the merge code itself is NOT "
        "idempotent across duplicate invocations. FR-011's pre-side-effect CAS "
        "ensures only one replica per household per day ever reaches "
        "`bulk_create_items`."
    )

    # =====================================================================
    # META-V2-001 + META-V2-005 + META-V2-007 (force semantics rewrite):
    # FR-020 — HTTP 204 on precondition failure, no `detail` field
    # =====================================================================
    frs["FR-020"]["text"] = (
        "Add the route `POST /api/households/preferences/auto-sync-shopping/run-now` "
        "on `HouseholdSelfServiceController` "
        "(mealie/routes/households/controller_household_self_service.py:20-62). "
        "Guard: `self.checks.can_manage_household()` "
        "(mealie/routes/_base/checks.py:23-26). Behavior: invokes the per-household "
        "auto-sync pipeline (FR-009 through FR-021) with `force=True`. "
        "`force=True` bypasses both the FR-009 30-minute window gate AND the "
        "FR-012 conditional CAS — the WHERE clause of the UPDATE becomes "
        "unconditional (`WHERE id = :pref_id`) so the CAS always affects 1 row "
        "and the marker `last_auto_synced_at` is ALWAYS written on success. The "
        "side-effect ordering is otherwise identical to FR-011: the unconditional "
        "UPDATE still runs inside the same transaction as `bulk_create_items` + "
        "event dispatch, so any exception rolls back the marker write too. "
        "Response: HTTP 200 on success with body matching EXACTLY the four-key "
        "shape `{'added_count': int, 'skipped_pantry_count': int, "
        "'target_list_id': UUID4 | null, 'run_at': datetime}` (ISO 8601 UTC). "
        "When preconditions fail (today's meal plan is empty OR no target list "
        "resolvable), respond HTTP 204 No Content with NO body — matching the "
        "input requirement `204 / 0 added`. The i18n keys from FR-022 are NOT "
        "surfaced in the response body; they appear only in server-side logs "
        "and in the absence of any body the client treats 204 as 'nothing to "
        "do'. Permission failure returns HTTP 403 via the guard."
    )

    # =====================================================================
    # META-V2-001: FR-021 — dispatch only on CAS winner; remove dup-event
    # tolerance assumption; add SC-025 link
    # =====================================================================
    frs["FR-021"]["text"] = (
        "Add a new event type `EventTypes.mealplan_auto_synced_to_shopping` to the "
        "`EventTypes(Enum)` in mealie/services/event_bus_service/event_types.py:13-60 "
        "(the comment in that enum confirms that adding a member requires an alembic "
        "migration to the subscriber table — covered by FR-024 + ORM/schema "
        "additions in FR-028). Add a new payload class "
        "`EventMealPlanAutoSyncedData(EventDocumentDataBase)` in the same file with "
        "fields `document_type: EventDocumentType = EventDocumentType.shopping_list, "
        "household_id: UUID4, shopping_list_id: UUID4, added_item_count: int, "
        "skipped_pantry_count: int`. The payload reuses the existing "
        "`EventDocumentDataBase` "
        "(mealie/services/event_bus_service/event_types.py:88-91) which provides "
        "`operation: EventOperation`. The auto-sync task dispatches via "
        "`EventBusService.dispatch(integration_id=DEFAULT_INTEGRATION_ID, "
        "group_id=..., household_id=..., "
        "event_type=EventTypes.mealplan_auto_synced_to_shopping, "
        "document_data=EventMealPlanAutoSyncedData(operation=EventOperation.update, "
        "household_id=..., shopping_list_id=..., added_item_count=..., "
        "skipped_pantry_count=...))` per the dispatch pattern at "
        "mealie/services/event_bus_service/event_bus_service.py:66-96. Exactly one "
        "dispatch per CAS winner — the dispatch sits inside step 6 of FR-011, "
        "which is reached only when the FR-012 CAS UPDATE affected 1 row. CAS "
        "losers short-circuit at step 4 of FR-011 and never reach the dispatch. "
        "Failures during steps 5-6 roll back the transaction and the marker, "
        "so the next scheduler tick retries; no event is dispatched in that case."
    )
    frs["FR-021"]["related_success_criteria"] = ["SC-013", "SC-025"]

    # =====================================================================
    # META-V2-005 + META-V2-010: FR-022 — drop `detail` mention, fix locale
    # =====================================================================
    frs["FR-022"]["text"] = (
        "Add three i18n keys under a NEW top-level `auto-sync` namespace in "
        "mealie/lang/messages/en-US.json (file currently has top-level keys "
        "`generic` at line 2 and `mealplan` at line 34). The hyphenated namespace "
        "matches existing conventions (`generic.server-error`, "
        "`recipe.unique-name-error`). Required keys with their exact English "
        "strings: `auto-sync.no-meal-plan-today` = `'No meal plan for today; "
        "nothing to sync.'`; `auto-sync.no-target-list` = `'No shopping list is "
        "configured or available for auto-sync.'`; `auto-sync.already-synced-today` "
        "= `'This household was already auto-synced today.'`. These keys surface "
        "in server-side logs (logger.info / logger.warning calls in the auto-sync "
        "pipeline) and in the event payload dispatched by FR-021 when applicable; "
        "they are NOT included in the HTTP response body of the run-now route "
        "(per FR-020 v3 the run-now route returns HTTP 204 with no body on "
        "precondition failure). Mealie ships 40+ locale files at "
        "`mealie/lang/messages/*.json` (en-US, en-GB, fr-FR, zh-CN, af-ZA, "
        "ar-SA, etc.); per `.github/copilot-instructions.md` 'Translations' "
        "section ONLY `en-US.json` is editable by repository contributors — every "
        "other locale is Crowdin-managed and MUST NOT be edited (PRs touching "
        "them are rejected). So only `en-US.json` changes for this feature."
    )

    # =====================================================================
    # META-V2-002 + META-V2-006: FR-024 — fix table name, add FK with
    # ondelete='SET NULL', CASCADE on association table, link to SC-002
    # =====================================================================
    frs["FR-024"]["text"] = (
        "Add a single alembic revision file under `mealie/alembic/versions/` "
        "modeled on the announcements migration "
        "(mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py:1-32 "
        "for the upgrade template). The `upgrade()` function MUST: (A) "
        "`with op.batch_alter_table('household_preferences') as batch_op:` add "
        "five columns "
        "(`auto_sync_meal_plan_to_shopping Boolean NOT NULL server_default sa.false()`, "
        "`auto_sync_target_shopping_list_id GUID NULL`, `auto_sync_run_time String "
        "NOT NULL server_default '00:00'`, `timezone String NULL`, "
        "`last_auto_synced_at DateTime NULL`) AND THEN call "
        "`batch_op.create_foreign_key('fk_household_preferences_auto_sync_target', "
        "'shopping_lists', ['auto_sync_target_shopping_list_id'], ['id'], "
        "ondelete='SET NULL')` modeled on the FK pattern at "
        "`mealie/alembic/versions/2024-02-23-16.15.07_2298bb460ffd_added_user_to_shopping_list.py:86`; "
        "(B) `op.create_table('household_pantry_staples', "
        "sa.Column('household_id', GUID, sa.ForeignKey('households.id', "
        "ondelete='CASCADE'), index=True), sa.Column('food_id', GUID, "
        "sa.ForeignKey('ingredient_foods.id', ondelete='CASCADE'), index=True), "
        "sa.UniqueConstraint('household_id', 'food_id', "
        "name='household_pantry_staple_unique'))` — note the explicit "
        "`ondelete='CASCADE'` per FR-002, which deliberately deviates from the "
        "parallel `households_to_ingredient_foods` table "
        "(mealie/db/models/recipe/ingredient.py:21-27) that omits CASCADE; "
        "(C) `with op.batch_alter_table('group_events_notifier_options') as "
        "batch_op:` add `mealplan_auto_synced_to_shopping Boolean NOT NULL "
        "server_default sa.false()` for the new event subscription column — note "
        "the table name is `group_events_notifier_options` (verified at "
        "mealie/db/models/household/events.py:16 and at the existing migration "
        "mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py:21); "
        "v2 wrongly said `group_event_notifier_options` (missing the 's' in "
        "`events`). The `downgrade()` function reverses each step in reverse order "
        "modeled on lines 35-47 of the announcement template: drop the new "
        "subscription column, drop the new association table, drop the new FK "
        "constraint via `batch_op.drop_constraint("
        "'fk_household_preferences_auto_sync_target', type_='foreignkey')`, drop "
        "the five preference columns."
    )
    frs["FR-024"]["code_references"] = [
        {
            "path": "mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py",
            "symbols": ["upgrade", "batch_alter_table", "show_announcements"],
            "line_ranges": [[1, 32]],
            "snippet": None,
        },
        {
            "path": "mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py",
            "symbols": ["downgrade", "drop_column", "batch_alter_table"],
            "line_ranges": [[35, 47]],
            "snippet": None,
        },
        {
            "path": "mealie/db/models/recipe/ingredient.py",
            "symbols": ["households_to_ingredient_foods", "UniqueConstraint"],
            "line_ranges": [[21, 27]],
            "snippet": None,
        },
        {
            "path": "mealie/alembic/versions/2024-02-23-16.15.07_2298bb460ffd_added_user_to_shopping_list.py",
            "symbols": ["create_foreign_key"],
            "line_ranges": [[80, 100]],
            "snippet": None,
        },
        {
            "path": "mealie/db/models/household/events.py",
            "symbols": ["GroupEventNotifierOptionsModel"],
            "line_ranges": [[15, 19]],
            "snippet": None,
        },
        {
            "path": "mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py",
            "symbols": ["upgrade", "batch_alter_table", "group_events_notifier_options"],
            "line_ranges": [[19, 50]],
            "snippet": None,
        },
    ]
    frs["FR-024"]["related_success_criteria"] = ["SC-020", "SC-002", "SC-028"]

    # =====================================================================
    # META-V2-005: FR-026 — add no-meal-plan integration test for HTTP 204
    # =====================================================================
    frs["FR-026"]["text"] = (
        "[NFR] Test matrix per META-011 + META-V2-005 + META-V2-008: (A) unit "
        "tests under `tests/unit_tests/services/scheduler/` covering: window-gate "
        "boundaries (just-before, on-instant, just-after, end-of-window), CAS "
        "UPDATE wins / loses race (mock 0-row response, assert loser dispatches "
        "no event and writes no items), force=True bypass (unconditional UPDATE), "
        "empty meal plan (no event, no marker), null timezone fallback to UTC, "
        "pantry-filter predicate with empty staple set, pantry-filter with "
        "sub-recipe ingredient; (B) integration tests under "
        "`tests/integration_tests/user_household_tests/` covering: PATCH partial "
        "update roundtrip (only requested fields change), PATCH rejects "
        "`last_auto_synced_at`-bearing body with 422 (extra='forbid' on the "
        "partial schema), PUT roundtrip with new fields, run-now success with "
        "exact 4-key response shape per FR-020 (HTTP 200), run-now precondition "
        "failure returns HTTP 204 with NO body when meal plan is empty (input "
        "requirement 5 'when no meal plan today returns 204 / 0 added'), run-now "
        "precondition failure returns HTTP 204 with NO body when no target list "
        "resolvable, run-now 403 for non-admin user, scheduler tick end-to-end "
        "exercising `add_recipe_ingredients_to_list` "
        "(mealie/services/household_services/shopping_lists.py:413-455) and "
        "asserting `bulk_create_items` is invoked exactly once per CAS winner per "
        "tick. Multitenant suite under `tests/multitenant_tests/` covers same-group "
        "cross-household isolation (FR-027) and cross-group isolation (FR-029)."
    )

    # =====================================================================
    # META-V2-002 + META-V2-008: NEW FRs (FR-028 and FR-029)
    # =====================================================================
    fr_028 = {
        "id": "FR-028",
        "text": (
            "Add the new event subscription bool to BOTH the ORM model and the "
            "Pydantic schema so `AppriseEventListener.get_subscribers` can resolve "
            "the per-event flag. (A) In `GroupEventNotifierOptionsModel` "
            "(mealie/db/models/household/events.py:15-53) add "
            "`mealplan_auto_synced_to_shopping: Mapped[bool] = mapped_column(Boolean, "
            "default=False, nullable=False)` following the existing column pattern "
            "(e.g. `shopping_list_updated` at line 36). (B) In "
            "`GroupEventNotifierOptions` Pydantic schema "
            "(mealie/schema/household/group_events.py:13-55) add "
            "`mealplan_auto_synced_to_shopping: bool = False` following the "
            "existing pattern (e.g. `shopping_list_updated` at line 37). Without "
            "these two additions, the migration column (FR-024) is present on "
            "disk but `AppriseEventListener.get_subscribers` "
            "(mealie/services/event_bus_service/event_bus_listeners.py:76-83) "
            "uses `getattr(notifier.options, event.event_type.name)` to resolve "
            "the subscription, so the new event type would always silently return "
            "False and no subscribers would be notified."
        ),
        "requirement_type": "functional",
        "related_user_stories": ["US-5"],
        "related_success_criteria": ["SC-027"],
        "code_references": [
            {
                "path": "mealie/db/models/household/events.py",
                "symbols": [
                    "GroupEventNotifierOptionsModel",
                    "shopping_list_updated",
                ],
                "line_ranges": [[15, 55]],
                "snippet": None,
            },
            {
                "path": "mealie/schema/household/group_events.py",
                "symbols": ["GroupEventNotifierOptions", "shopping_list_updated"],
                "line_ranges": [[13, 55]],
                "snippet": None,
            },
            {
                "path": "mealie/services/event_bus_service/event_bus_listeners.py",
                "symbols": ["AppriseEventListener", "get_subscribers"],
                "line_ranges": [[72, 90]],
                "snippet": None,
            },
        ],
        "testable": True,
    }
    fr_029 = {
        "id": "FR-029",
        "text": (
            "[NFR] Cross-group multitenant isolation test (input requirement 5 "
            "'cross group complete isolation'). Create household A in group G1 and "
            "household B in group G2 (different groups). For each household: seed "
            "a `GroupMealPlan` row for today, configure auto-sync, mark a "
            "different food as a pantry staple via `household_pantry_staples`. "
            "Trigger the auto-sync task for both households. Assert: (a) the row "
            "count and content of every `ShoppingList`, `GroupMealPlan`, "
            "`IngredientFood`, and `household_pantry_staples` row belonging to G2 "
            "is byte-identical before and after household A's sync; (b) the "
            "household-scoped repos built per FR-009 enumerate only G1 entities "
            "during household A's iteration "
            "(`repos.meals.get_today` returns 0 G2 rows; "
            "`repos.group_shopping_lists.get_one(<G2 list id>)` returns None even "
            "when called with a known-valid G2 list id); (c) the inverse asserts "
            "hold when triggering for household B. This is the cross-group "
            "regression guard — if any assertion fails, the household-scoped repo "
            "pattern is being bypassed."
        ),
        "requirement_type": "non_functional",
        "related_user_stories": ["US-6"],
        "related_success_criteria": ["SC-029"],
        "code_references": [
            {
                "path": "mealie/repos/repository_factory.py",
                "symbols": ["AllRepositories", "group_id", "household_id"],
                "line_ranges": [[105, 130]],
                "snippet": None,
            },
            {
                "path": "mealie/repos/repository_meals.py",
                "symbols": ["get_today", "household_id"],
                "line_ranges": [[11, 21]],
                "snippet": None,
            },
        ],
        "testable": True,
    }
    data["functional_requirements"].append(fr_028)
    data["functional_requirements"].append(fr_029)

    # =====================================================================
    # META-V2-001 + META-V2-003: SC updates
    # =====================================================================
    # SC-007: emphasize zero events + zero items + exactly one marker write
    scs["SC-007"]["text"] = (
        "Running the auto-sync task twice in a row for the same household on the "
        "same household-local day results in: (a) `last_auto_synced_at` written "
        "exactly ONCE across both invocations (first invocation's CAS sets it, "
        "second invocation's CAS returns 0 rows and short-circuits); (b) zero new "
        "`shopping_list_item` rows on the second invocation; (c) zero "
        "`EventBusService.dispatch` calls on the second invocation; (d) zero "
        "calls to `bulk_create_items` on the second invocation."
    )
    scs["SC-007"]["metric"] = (
        "count of marker writes, item inserts, event dispatches, and "
        "bulk_create_items calls on the second invocation"
    )
    scs["SC-007"]["threshold"] = (
        "exactly 1 marker write across both invocations; 0 new item rows, 0 "
        "event dispatches, and 0 bulk_create_items calls on the second invocation"
    )

    # SC-013: exactly one dispatch per CAS winner; zero on loser
    scs["SC-013"]["text"] = (
        "A successful auto-sync run (CAS winner) dispatches "
        "`EventBusService.dispatch` exactly ONCE with "
        "`event_type=EventTypes.mealplan_auto_synced_to_shopping` and "
        "`document_data` of type `EventMealPlanAutoSyncedData` carrying "
        "household_id, shopping_list_id, added_item_count, skipped_pantry_count, "
        "and operation. A CAS loser (concurrent replica or same-day re-run) "
        "dispatches zero events."
    )
    scs["SC-013"]["metric"] = (
        "number of EventBusService.dispatch invocations per CAS winner and per "
        "CAS loser, plus payload field presence on the winner's dispatch"
    )
    scs["SC-013"]["threshold"] = (
        "exactly 1 dispatch per CAS winner with all 5 required payload fields "
        "present; exactly 0 dispatches per CAS loser"
    )

    # SC-018: schema-level extra='forbid' on HouseholdPreferencesPartialUpdate
    scs["SC-018"]["text"] = (
        "A PATCH /api/households/preferences body that contains "
        "`last_auto_synced_at` is rejected with HTTP 422 by "
        "`HouseholdPreferencesPartialUpdate` because the schema declares "
        "`model_config = ConfigDict(extra='forbid')` directly on its own class "
        "(NOT globally on `MealieModel`, which only sets `alias_generator` and "
        "`populate_by_name=True` at `mealie/schema/_mealie/mealie_model.py:45-53`). "
        "Pydantic raises `validation_error[extra_forbidden]` for the undeclared "
        "field."
    )
    scs["SC-018"]["related_requirements"] = ["FR-003", "FR-004", "FR-006", "FR-007"]

    # =====================================================================
    # META-V2-005 + META-V2-002 + META-V2-006 + META-V2-008: NEW SCs
    # =====================================================================
    sc_026 = {
        "id": "SC-026",
        "text": (
            "A POST to /api/households/preferences/auto-sync-shopping/run-now by "
            "a can_manage_household=true user when today's meal plan is empty "
            "returns HTTP 204 No Content with an empty body (zero bytes). "
            "Equivalent assertion holds when the household has no resolvable "
            "target list. This matches input requirement 5 "
            "'when no meal plan today returns 204 / 0 added'."
        ),
        "metric": (
            "HTTP status and body length of run-now when today's meal plan is "
            "empty or no target list is resolvable"
        ),
        "threshold": (
            "status code exactly 204 and Content-Length 0 for both no-meal-plan "
            "and no-target-list cases"
        ),
        "technology_agnostic": True,
        "related_requirements": ["FR-020", "FR-022"],
    }
    sc_027 = {
        "id": "SC-027",
        "text": (
            "After running the alembic upgrade (FR-024 step C) AND the ORM/schema "
            "additions (FR-028), a `GroupEventNotifierOptions` instance has the "
            "attribute `mealplan_auto_synced_to_shopping` accessible via "
            "`getattr(options, 'mealplan_auto_synced_to_shopping')` defaulting to "
            "False, AND the underlying ORM row has the matching column. This "
            "verifies the seam at "
            "`mealie/services/event_bus_service/event_bus_listeners.py:76-83` "
            "where `AppriseEventListener.get_subscribers` calls "
            "`getattr(notifier.options, event.event_type.name)` to resolve "
            "subscriptions."
        ),
        "metric": (
            "presence of mealplan_auto_synced_to_shopping attribute on "
            "GroupEventNotifierOptions schema and column on "
            "group_events_notifier_options table"
        ),
        "threshold": (
            "attribute exists with default False AND column exists with default "
            "false AND getattr(notifier.options, 'mealplan_auto_synced_to_shopping') "
            "returns a bool"
        ),
        "technology_agnostic": True,
        "related_requirements": ["FR-021", "FR-024", "FR-028"],
    }
    sc_028 = {
        "id": "SC-028",
        "text": (
            "After running the alembic upgrade (FR-024 step A), "
            "`inspect(engine).get_foreign_keys('household_preferences')` includes "
            "one foreign key on column "
            "`auto_sync_target_shopping_list_id` referencing "
            "`shopping_lists.id` with `options={'ondelete': 'SET NULL'}` (the "
            "exact key/value depends on the SQLAlchemy dialect's reflection of "
            "the constraint metadata). Hard-deleting a row from `shopping_lists` "
            "whose id appears in `household_preferences.auto_sync_target_shopping_list_id` "
            "sets that column to NULL rather than raising IntegrityError."
        ),
        "metric": (
            "FK presence and ondelete action on "
            "household_preferences.auto_sync_target_shopping_list_id, plus "
            "post-delete null behavior"
        ),
        "threshold": (
            "exactly one FK on auto_sync_target_shopping_list_id referencing "
            "shopping_lists.id with ondelete='SET NULL', and a referencing row's "
            "column is NULL after the parent shopping list is deleted"
        ),
        "technology_agnostic": True,
        "related_requirements": ["FR-001", "FR-024"],
    }
    sc_029 = {
        "id": "SC-029",
        "text": (
            "Given households A in group G1 and B in group G2 (DIFFERENT groups), "
            "with seeded meal plans, auto-sync configured for both, and pantry "
            "staples set in each, running auto-sync for household A leaves the "
            "byte-equal serialization of every G2 `ShoppingList`, `GroupMealPlan`, "
            "`IngredientFood`, and `household_pantry_staples` row unchanged. The "
            "inverse assertion holds when running for household B against G1 rows."
        ),
        "metric": (
            "byte equality of G2 entity rows before and after household A's sync, "
            "and vice versa"
        ),
        "threshold": (
            "zero diff bytes between pre-sync and post-sync snapshots for G2 "
            "entities during A's sync, AND zero diff for G1 entities during B's "
            "sync"
        ),
        "technology_agnostic": True,
        "related_requirements": ["FR-023", "FR-029"],
    }
    data["success_criteria"].append(sc_026)
    data["success_criteria"].append(sc_027)
    data["success_criteria"].append(sc_028)
    data["success_criteria"].append(sc_029)

    # =====================================================================
    # META-V2-012: reciprocal-link fixes
    # =====================================================================
    # FR-009.related_success_criteria already includes SC-024 above
    # FR-011.related_success_criteria already includes SC-025 above
    # FR-021.related_success_criteria already includes SC-025 above
    # FR-024.related_success_criteria already includes SC-002, SC-028 above
    # SC-018.related_requirements already includes FR-007 above
    # SC-002.related_requirements already lists FR-001/FR-024
    # SC-024.related_requirements -> add nothing else; FR-009 now points back
    # SC-025.related_requirements: ensure includes FR-011 + FR-021
    scs["SC-025"]["related_requirements"] = ["FR-011", "FR-021"]

    # =====================================================================
    # META-V2-001: edge cases rewrite (two-replica case, plus tighten
    # no-meal-plan and add force-mode rollback)
    # META-V2-011: tighten the no-meal-plan re-trigger window edge case
    # =====================================================================
    new_edge_cases = []
    for ec in data["edge_cases"]:
        d = ec["description"]
        if "no meal plan exists for today" in d:
            new_edge_cases.append(
                {
                    "description": (
                        "Household has auto_sync_meal_plan_to_shopping=true but "
                        "no meal plan exists for today"
                    ),
                    "handling": (
                        "FR-011 step 2: skip the household BEFORE the CAS UPDATE "
                        "fires, log the i18n warning auto-sync.no-meal-plan-today, "
                        "and DO NOT bump last_auto_synced_at. A meal plan added "
                        "later in the same household-local day will trigger a real "
                        "sync only when BOTH (a) the meal plan is created before "
                        "the current day's [scheduled_local_instant, "
                        "scheduled_local_instant + 30min) window closes AND (b) "
                        "the next 5-minute scheduler tick fires inside that window. "
                        "If the meal plan is created after the window closes, only "
                        "POST /api/households/preferences/auto-sync-shopping/run-now "
                        "syncs that day; the next automatic sync is tomorrow's "
                        "window."
                    ),
                }
            )
        elif "Two replicas tick the same household" in d:
            new_edge_cases.append(
                {
                    "description": (
                        "Two replicas tick the same household in the same "
                        "5-minute bucket"
                    ),
                    "handling": (
                        "Each replica opens its own transaction and races to "
                        "issue the FR-012 conditional UPDATE. The DB serializes "
                        "the conflicting UPDATEs at the row level (Postgres "
                        "default REPEATABLE READ or SQLite's per-statement lock); "
                        "the second-arriving UPDATE sees the marker already "
                        "advanced and affects 0 rows. FR-011 step 4 catches "
                        "rowcount=0, COMMITs the empty transaction, and returns "
                        "without calling `bulk_create_items` or "
                        "`EventBusService.dispatch`. Result: exactly one replica "
                        "(the CAS winner) writes items and dispatches the event; "
                        "the CAS loser is a structural no-op. There is no "
                        "duplicate-event tolerance assumption on subscribers."
                    ),
                }
            )
        elif "Recipe contains a sub-recipe reference cycle" in d:
            new_edge_cases.append(
                {
                    "description": (
                        "Recipe contains a sub-recipe reference cycle (recipe A "
                        "includes recipe B includes recipe A)"
                    ),
                    "handling": (
                        "The existing `get_shopping_list_items_from_recipe` "
                        "(mealie/services/household_services/shopping_lists.py:323-355) "
                        "does not guard against cycles, and Mealie's data model "
                        "assumes acyclic recipe references. The auto-sync task "
                        "wraps the recursive expansion in a `try/except RecursionError`. "
                        "On failure, the exception propagates out of the FR-011 "
                        "transaction context which ROLLS BACK the CAS UPDATE "
                        "alongside any partial item writes — so last_auto_synced_at "
                        "reverts and the marker is NOT touched. The task logs an "
                        "error with the recipe id and continues to the next "
                        "household."
                    ),
                }
            )
        elif "POST run-now invoked when the household is in a different group" in d:
            new_edge_cases.append(ec)
        else:
            new_edge_cases.append(ec)
    # add new edge cases:
    new_edge_cases.append(
        {
            "description": (
                "Force-mode run-now mid-transaction exception"
            ),
            "handling": (
                "FR-020 force=True replaces the CAS WHERE clause with an "
                "unconditional UPDATE. The unconditional UPDATE runs inside the "
                "same transaction as `bulk_create_items` + event dispatch. If any "
                "step raises an exception (e.g. DB constraint violation, "
                "event-bus connection failure), the entire transaction rolls back "
                "including the unconditional UPDATE — so last_auto_synced_at "
                "reverts to its prior value. The route returns HTTP 500 (the "
                "exception surfaces to FastAPI's default error handler); the "
                "caller can safely retry the run-now invocation."
            ),
        }
    )
    new_edge_cases.append(
        {
            "description": (
                "No-meal-plan / no-target-list precondition fails on run-now"
            ),
            "handling": (
                "FR-020 returns HTTP 204 No Content with an empty body — matching "
                "input requirement 5 'when no meal plan today returns 204 / 0 "
                "added'. No `detail` field, no i18n key in the response; the i18n "
                "key surfaces only in server-side logs. Frontend / client "
                "integrations distinguish 200 (work done) from 204 (no work) by "
                "status code alone."
            ),
        }
    )
    data["edge_cases"] = new_edge_cases

    # =====================================================================
    # META-V2-010: assumption fixes for locale
    # META-V2-001: drop "subscriber dedup tolerance" out-of-scope
    # =====================================================================
    data["assumptions"] = [
        (
            "The Mealie deployment runs Python 3.11+ so `zoneinfo.ZoneInfo` is "
            "available without the `tzdata` backport. The Dockerfile already pins "
            "3.11+ per the repo README."
        ),
        (
            "The scheduler clock and the database clock are synchronized within a "
            "few seconds; the FR-009 30-minute window is wide enough to tolerate "
            "up to ~5 minutes of clock skew."
        ),
        (
            "Mealie ships 40+ locale files at `mealie/lang/messages/*.json` "
            "(en-US, en-GB, fr-FR, zh-CN, af-ZA, ar-SA, etc.), but only "
            "`en-US.json` is editable by repository contributors per "
            "`.github/copilot-instructions.md` 'Translations' section. All other "
            "locale files are Crowdin-managed and MUST NOT be edited (PRs "
            "touching them are rejected). The three i18n keys in FR-022 are added "
            "ONLY to `en-US.json`."
        ),
        (
            "The existing `EventBusService.dispatch` "
            "(mealie/services/event_bus_service/event_bus_service.py:66-96) is the "
            "canonical entry point for all event-bus integrations. Subscribers "
            "(Apprise, webhooks) are registered via `_get_listeners` and resolve "
            "per-event subscription state via `getattr(notifier.options, "
            "event.event_type.name)` (`event_bus_listeners.py:76-83`); the new "
            "event type therefore requires both the migration column (FR-024 step "
            "C) AND the ORM/schema additions (FR-028) before subscribers can opt "
            "in."
        ),
        (
            "A household administrator (can_manage_household=true) has the right "
            "to write to any shopping list owned by their household. There is no "
            "per-shopping-list ACL inside a household — household membership IS "
            "the access boundary."
        ),
        (
            "Hard deletes of shopping lists set `auto_sync_target_shopping_list_id` "
            "to NULL via the `ON DELETE SET NULL` foreign key constraint declared "
            "in FR-001 / FR-024 step A (via `batch_op.create_foreign_key(..., "
            "ondelete='SET NULL')`)."
        ),
        (
            "The PATCH-time and sync-time ownership validation in FR-014 use the "
            "same `household_id`-scoped repo, so the validation rule is consistent "
            "regardless of which path the value travels."
        ),
        (
            "`bulk_create_items` "
            "(mealie/services/household_services/shopping_lists.py:154-220) is and "
            "remains the canonical consolidator. The function "
            "`consolidate_ingredients` mentioned in some older PR discussions does "
            "not exist in this codebase; the auto-sync task MUST NOT introduce one."
        ),
        (
            "`merge_items` SUMS quantities at "
            "`mealie/services/household_services/shopping_lists.py:96` "
            "(`to_item.quantity += from_item.quantity`), so the merge code is NOT "
            "idempotent across duplicate invocations. Per-day idempotency is "
            "enforced UPSTREAM by the FR-012 CAS UPDATE which prevents a second "
            "invocation from ever reaching `bulk_create_items`."
        ),
    ]

    # out_of_scope: drop the subscriber-dedup tolerance item
    data["out_of_scope"] = [
        item
        for item in data["out_of_scope"]
        if "Subscriber-side dedup" not in item
    ]

    # =====================================================================
    # META-V2-010: self_concerns — fix the locale concern; the FR-021
    # startup-check concern is now superseded by FR-028 (model/schema)
    # =====================================================================
    new_self_concerns = []
    for sc in data["self_concerns"]:
        if sc["location"] == "FR-022":
            new_self_concerns.append(
                {
                    "location": "FR-022",
                    "concern": (
                        "The i18n keys `auto-sync.no-meal-plan-today`, "
                        "`auto-sync.no-target-list`, and "
                        "`auto-sync.already-synced-today` are added only to "
                        "`mealie/lang/messages/en-US.json` because all other "
                        "locale files are Crowdin-managed and MUST NOT be edited "
                        "per `.github/copilot-instructions.md` 'Translations' "
                        "section. Crowdin will eventually back-fill the keys "
                        "into the 40+ other locale files via its upstream sync, "
                        "but until then non-English users see the en-US strings "
                        "as fallbacks via the i18n resolver's default behavior."
                    ),
                    "evidence_gap": (
                        "We confirmed via repository inspection that 40+ locales "
                        "ship today and that `.github/copilot-instructions.md` "
                        "forbids editing them in PRs. Crowdin's sync cadence is "
                        "out of scope. The fallback to en-US for missing keys is "
                        "consistent with the rest of the Mealie i18n surface."
                    ),
                    "suggested_resolution": (
                        "Accept the en-US-only PR baseline. Crowdin handles the "
                        "translation back-fill on its own cadence."
                    ),
                }
            )
        elif sc["location"] == "FR-021":
            new_self_concerns.append(
                {
                    "location": "FR-021",
                    "concern": (
                        "The new `EventTypes.mealplan_auto_synced_to_shopping` "
                        "member requires the matching subscriber-options column "
                        "(FR-024 step C) AND the ORM/schema additions (FR-028) to "
                        "be reachable by `AppriseEventListener.get_subscribers`. "
                        "If a deployment runs the new code against a partially-"
                        "migrated database (column missing) OR with stale ORM/"
                        "schema (missing the new field), dispatch succeeds but "
                        "subscribers silently fail to resolve the new event."
                    ),
                    "evidence_gap": (
                        "We have not exercised the pre-migration / stale-ORM path "
                        "explicitly. The recommended defense is to verify the "
                        "subscriber-options column at app startup via SQLAlchemy "
                        "reflection AND assert the schema field exists via "
                        "`hasattr(GroupEventNotifierOptions, "
                        "'mealplan_auto_synced_to_shopping')`."
                    ),
                    "suggested_resolution": (
                        "Implement a startup check (a single integration test "
                        "covers this) that asserts both the column and the schema "
                        "attribute exist; raise a startup exception otherwise."
                    ),
                }
            )
        else:
            new_self_concerns.append(sc)
    data["self_concerns"] = new_self_concerns

    # =====================================================================
    # WRITE + VALIDATE
    # =====================================================================
    V3_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {V3_JSON}")

    from devloop.spec_phase.schemas import Spec
    from devloop.spec_phase.validators.citation_verifier import verify_spec_citations
    from devloop.spec_phase.validators.trace_matrix import find_trace_gaps
    from devloop.spec_phase.md_json_bridge import (
        assert_spec_roundtrip_consistent,
        spec_to_markdown,
    )

    spec = Spec.model_validate(data)
    print(
        f"A4+F3 schema: PASS (FRs={len(spec.functional_requirements)}, "
        f"SCs={len(spec.success_criteria)}, NCs={len(spec.needs_clarification)})"
    )

    citation_problems = verify_spec_citations(MEALIE, spec)
    print(f"A5 citation: {len(citation_problems)} problems")
    for p in citation_problems:
        print(f"  - {p.fr_id} [{p.path}] {p.problem}: {p.detail}")

    gaps = find_trace_gaps(spec)
    print(f"B3 trace: {len(gaps)} gaps")
    for g in gaps:
        print(f"  - [{g.kind}] {g.actor}: {g.detail}")

    md = spec_to_markdown(spec)
    V3_MD.write_text(md, encoding="utf-8")
    print(f"Wrote {V3_MD}")

    assert_spec_roundtrip_consistent(spec)
    print("B1 roundtrip: PASS")


if __name__ == "__main__":
    main()
