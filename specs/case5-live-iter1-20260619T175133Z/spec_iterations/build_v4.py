"""Build spec_v4 from spec_v3 by applying meta_review_v3 actions.

Applies the fixes for the persistent issues flagged by v3 reviewers:
- CRIT NEW-ARCH-C-1 / EXEC-C-001 / EXEC-C-002 (single-transaction + internal commits): outbox pattern + no-commit refactor
- HIGH COMP-H-013 / C3-002 / EXEC-H-001 (US-9 vs FR-020 204 contract): rewrite US-9
- HIGH NEW-ARCH-H-1 (event dispatch contradiction): outbox pattern resolves
- HIGH EXEC-H-002 (event payload missing message_key): add optional field
- MED C3-004 / EXEC-M-001 (stale locale OOS sentence): rewrite
- MED EXEC-M-002 (Postgres isolation level): rewrite edge case
- MED EXEC-M-003 (FR-014/23 filter citations): add lines
- MED C3-003 (US-9 / event-payload localization): add message_key
- LOW C3-005 (reciprocal FR<->SC links): make symmetric

Plus 3 new SCs (SC-030/031/032), new NC-004, 2 new FRs (FR-030/031),
fix references throughout.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(r"C:\Users\v-liyuanjun\source\repos\devloop")
SPECS = ROOT / "specs" / "case5-live-iter1-20260619T175133Z" / "spec_iterations"
MEALIE = pathlib.Path(r"C:\Users\v-liyuanjun\Downloads\mealie")

sys.path.insert(0, str(ROOT))

from devloop.spec_phase.schemas import Spec  # noqa: E402
from devloop.spec_phase.validators.citation_verifier import (  # noqa: E402
    verify_spec_citations,
)
from devloop.spec_phase.validators.trace_matrix import find_trace_gaps  # noqa: E402
from devloop.spec_phase.md_json_bridge import (  # noqa: E402
    assert_spec_roundtrip_consistent,
    spec_to_markdown,
)


def load_v3() -> dict:
    p = SPECS / "spec_v3.json"
    return json.loads(p.read_text(encoding="utf-8"))


def get_fr(spec: dict, fr_id: str) -> dict:
    for fr in spec["functional_requirements"]:
        if fr["id"] == fr_id:
            return fr
    raise KeyError(fr_id)


def get_sc(spec: dict, sc_id: str) -> dict:
    for sc in spec["success_criteria"]:
        if sc["id"] == sc_id:
            return sc
    raise KeyError(sc_id)


def get_us(spec: dict, us_id: str) -> dict:
    for us in spec["user_stories"]:
        if us["id"] == us_id:
            return us
    raise KeyError(us_id)


def apply_v4_changes(spec: dict) -> dict:
    spec = copy.deepcopy(spec)
    spec["metadata"]["iterations"] = 4

    # ------------------------------------------------------------------
    # 1. UPDATE SUMMARY: reflect outbox pattern + no-commit refactor
    # ------------------------------------------------------------------
    spec["summary"] = (
        "Add a per-household preference that, when enabled, automatically pushes the recipes scheduled in today's meal plan into a configured target shopping list. "
        "Per-household state lives on `HouseholdPreferencesModel` (four client-writable columns plus a server-owned `last_auto_synced_at` idempotency marker) and on a new `household_pantry_staples(household_id, food_id)` association table with `ondelete='CASCADE'` on both FKs, parallel to (but deliberately deviating from) `households_to_ingredient_foods` which omits CASCADE. "
        "The scheduler is registered via `SchedulerRegistry.register_minutely` (the existing 5-minute bucket) and each tick computes a household-local `scheduled_local_instant = today_in_household_tz at auto_sync_run_time`, gating execution to runs whose `household_local_now()` falls inside `[scheduled_local_instant, scheduled_local_instant + 30 minutes)`. "
        "Idempotency is enforced by a single conditional UPDATE on `last_auto_synced_at` issued BEFORE any shopping-list mutation, inside ONE outer DB transaction owned by the auto-sync task: if the UPDATE affects 0 rows, the transaction commits empty and the worker returns without writing items or enqueueing an event; if it affects 1 row, the worker proceeds to `bulk_create_items(commit=False)` + recipe-reference update + a single INSERT into a new `event_outbox` table, all inside the same transaction, and the entire pipeline commits atomically (or rolls back atomically on any exception). "
        "Per FR-030, the existing repo seams `RepositoryGeneric.create_many` / `update_many` / `update` AND `ShoppingListService.bulk_create_items` / `add_recipe_ingredients_to_list` are extended with a `commit: bool = True` parameter so the auto-sync task can suppress internal commits and keep the outer transaction open; existing callers keep the default `commit=True` so no behavior changes for current code paths. "
        "Per FR-031, a separate minutely scheduler task `dispatch_event_outbox()` polls undispatched outbox rows and calls `EventBusService.dispatch(...)` outside the originating transaction, marking `dispatched_at` on success and incrementing `attempts` on failure (up to MAX_ATTEMPTS=5 before the row is logged as dead-lettered). "
        "This outbox pattern is the v4 resolution of NEW-ARCH-C-1 / NEW-ARCH-H-1 / EXEC-C-001 / EXEC-C-002 — the rollback claim and exactly-once dispatch contract are now both achievable because all DB state (marker + items + outbox row) commits atomically and event publishing is durably decoupled from the transaction. "
        "Pantry filtering is unconditional and operates on the fully-flattened ingredient list (including sub-recipes via the recursive expansion at `shopping_lists.py:343-355`), with the per-household predicate sourced from the new association table. "
        "The canonical merge seam is `ShoppingListService.bulk_create_items` (`shopping_lists.py:154-220`), which already accumulates quantity into existing unchecked `(food_id, unit_id)` rows via `can_merge`+`merge_items`. "
        "A new `EventTypes.mealplan_auto_synced_to_shopping` event carries `EventMealPlanAutoSyncedData(operation, household_id, shopping_list_id, added_item_count, skipped_pantry_count, message_key)` where `message_key` is an optional `str | None = None` carrying the i18n key for downstream Apprise/webhook subscribers; the dispatcher passes `message=message_key or ''` into `EventBusService.dispatch(...)` so subscribers receive the key via `EventBusMessage.body`. "
        "The subscriber column `mealplan_auto_synced_to_shopping` is added to `group_events_notifier_options` (real table name; v2 wrongly said `group_event_notifier_options`) AND to `GroupEventNotifierOptionsModel` ORM AND to `GroupEventNotifierOptions` Pydantic schema so `AppriseEventListener.get_subscribers` can resolve the per-event flag. "
        "New routes: `PATCH /api/households/preferences` (partial update via `HouseholdPreferencesPartialUpdate` with `model_config = ConfigDict(extra='forbid')` so unknown fields like `last_auto_synced_at` are rejected with 422) and `POST /api/households/preferences/auto-sync-shopping/run-now` (household-admin only, `force=True` replaces the CAS with an unconditional UPDATE, HTTP 200 with EXACTLY `{added_count, skipped_pantry_count, target_list_id, run_at}` on success, HTTP 204 No Content on no-meal-plan / no-target-list precondition failure). "
        "The PATCH handler applies the diff via a column-set UPDATE that targets only `diff` keys so the server-owned marker is structurally protected from full-model writeback. "
        "Three i18n keys are added to the en-US namespace `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today` in `mealie/lang/messages/en-US.json` (only en-US is editable per `.github/copilot-instructions.md`; the other 40+ Crowdin-managed locales MUST NOT be modified). "
        "The migration also creates a FK constraint `fk_household_preferences_auto_sync_target` from `auto_sync_target_shopping_list_id` to `shopping_lists.id` with `ondelete='SET NULL'` so hard-deleting a list clears the field, and creates the new `event_outbox` table with indices on `(dispatched_at, created_at)` for the dispatcher poll query."
    )

    # ------------------------------------------------------------------
    # 2. ADD NC-004: escalate outbox vs partial-failure decision
    # ------------------------------------------------------------------
    spec["needs_clarification"].append({
        "id": "NC-004",
        "title": "Transactional auto-sync architecture: outbox pattern vs. weakened durability",
        "conflict": (
            "The v3 spec promised a single rollbackable DB transaction covering CAS marker, shopping-list writes, "
            "recipe-reference update, and event dispatch, but: (a) `RepositoryGeneric.create_many` / `update_many` / `update` call `session.commit()` "
            "internally (`mealie/repos/repository_generic.py:195-208`, `:210-226`, `:228-244`); (b) `ShoppingListService.bulk_create_items` "
            "delegates to those committing repo methods (`mealie/services/household_services/shopping_lists.py:215-216`); and (c) `EventBusService.dispatch` "
            "publishes immediately to external sinks (Apprise / webhooks) at `mealie/services/event_bus_service/event_bus_service.py:92-96`, which is not "
            "transactionally coupled to the DB. The v3 'after-commit dispatch can still roll back the CAS' wording was therefore impossible. Four "
            "v3 reviewers (NEW-ARCH-C-1, NEW-ARCH-H-1, EXEC-C-001, EXEC-C-002, C3-001, COMP-H-013) independently flagged this as blocking. The "
            "resolution requires an architectural choice that affects FR-011, FR-021, and adds new FRs / migrations."
        ),
        "recommended_default": (
            "Adopt the OUTBOX PATTERN with a no-commit refactor of the existing repo seams. Concretely: "
            "(1) per FR-030, extend `RepositoryGeneric.create_many` / `update_many` / `update` AND `ShoppingListService.bulk_create_items` / `add_recipe_ingredients_to_list` "
            "with a `commit: bool = True` keyword parameter; when `False`, the methods stage writes via `session.add_all` / direct UPDATE but skip `self.session.commit()` so the "
            "outer transaction stays open. Existing callers keep the `commit=True` default and behavior is unchanged for them. "
            "(2) per FR-031, create a new `event_outbox(id, group_id, household_id NULL, event_type, payload_json, created_at, dispatched_at NULL, attempts INT default 0, last_error NULL)` table; "
            "the auto-sync task inserts one row into `event_outbox` inside the same outer transaction as the CAS + items, so all three commit atomically. A separate minutely scheduler task "
            "`dispatch_event_outbox()` polls undispatched rows and calls `EventBusService.dispatch(...)` outside the originating transaction, marking `dispatched_at` on success and incrementing `attempts` on failure (capped at MAX_ATTEMPTS=5). "
            "This satisfies: atomic CAS+items+outbox commit; exactly-one outbox row per CAS winner; durable retry of external dispatch; full rollback of all DB state on any pipeline exception. "
            "The refactor is small (one new kwarg per method, one new table, one new task callable) and confined to the auto-sync code path."
        ),
        "if_rejected": (
            "Take the PARTIAL-FAILURE-TOLERANCE path. Drop FR-030 (no commit-control kwarg) and drop FR-031 (no event_outbox table or dispatcher). Rewrite FR-011 to: "
            "(1) issue the CAS UPDATE in its own short transaction that commits immediately; "
            "(2) on CAS success, proceed with `add_recipe_ingredients_to_list` (which commits internally per existing behavior); "
            "(3) on success, call `EventBusService.dispatch(...)` outside any transaction. "
            "Accept that a partial failure between (2) and (3) leaves the marker set with no event dispatched, and a failure mid-(2) leaves the marker set with partial item writes. "
            "Add a `sync_attempt_id UUID` column on `shopping_list_items` so a retry can detect and skip its own already-written rows. Add a new SC-033 requiring the auto-sync task to retry-on-partial-failure within MAX_ATTEMPTS=3 and to log dead-letter on exhaustion. "
            "Document explicitly in FR-021 and SC-013 that 'exactly once per CAS winner' becomes 'at least once per CAS winner' under this path, and subscribers MUST be idempotent."
        ),
        "related_requirements": ["FR-011", "FR-021", "FR-024", "FR-030", "FR-031"],
    })

    # ------------------------------------------------------------------
    # 3. REWRITE FR-011 — use outbox pattern
    # ------------------------------------------------------------------
    fr011 = get_fr(spec, "FR-011")
    fr011["text"] = (
        "Critical ordering — CAS BEFORE side effects, all inside ONE outer DB transaction owned by the auto-sync task (outbox pattern per NC-004): "
        "(1) resolve preconditions OUTSIDE the outer transaction — target list lookup via household-scoped `self.repos.group_shopping_lists.get_one(target_id)` "
        "(returns None if the id does not belong to this household, per FR-014), today's meal plan via `repos.meals.get_today(tz=tz)` (FR-010); "
        "(2) IF target lookup returns None OR meal plan is empty: log the i18n warning (`auto-sync.no-target-list` or `auto-sync.no-meal-plan-today` per FR-022), DO NOT bump `last_auto_synced_at`, return; "
        "(3) open the outer transaction with `with session.begin():`; "
        "(4) inside the transaction issue the conditional CAS UPDATE specified in FR-012 — "
        "`cas_rows = session.execute(update(HouseholdPreferencesModel).where(...).values(last_auto_synced_at=now_naive_utc)).rowcount`; "
        "if `cas_rows == 0` (another replica won this day's race, OR a non-concurrent second invocation on the same day) the `with` block exits cleanly (empty transaction commits) "
        "and the worker returns — NO `bulk_create_items` call, NO outbox insert, NO `recipe_references` update; "
        "(5) if `cas_rows == 1` (CAS winner), build the `ShoppingListAddRecipeParamsBulk` items (FR-015) and call "
        "`ShoppingListService(repos).add_recipe_ingredients_to_list(target_id, recipe_items, commit=False)` (per FR-030) which delegates to "
        "`bulk_create_items(commit=False)` and `shopping_lists.update(..., commit=False)` so the outer transaction stays open; "
        "(6) INSERT a single row into `event_outbox` (per FR-031) carrying the `EventMealPlanAutoSyncedData` payload serialized as JSON, `event_type='mealplan_auto_synced_to_shopping'`, `group_id`, `household_id`, `created_at=now_utc`, `dispatched_at=NULL`, `attempts=0` — the insert uses `session.add(EventOutbox(...))` so it participates in the same transaction without committing; "
        "(7) the `with session.begin():` block exits — SQLAlchemy issues a single `COMMIT` that atomically persists the marker, all shopping-list item writes, the recipe-reference update, and the outbox row. "
        "Any exception during steps 4-6 raises out of the `with` block, which rolls back the entire transaction (marker + items + outbox row), so the marker reverts to its prior value and the next scheduler tick retries. "
        "Event publishing happens later in the separate `dispatch_event_outbox` task (FR-031) which runs the existing `EventBusService.dispatch(...)` against the durably-stored outbox row, decoupling external delivery from the auto-sync transaction. "
        "The manual run-now path (FR-020) calls this same pipeline with `force=True`, which replaces step 4's conditional WHERE with an unconditional UPDATE that ALWAYS affects 1 row (so the force path always proceeds to step 5)."
    )
    # Update code_references to also cite the commit sites in repository_generic.py
    fr011["code_references"] = [
        {
            "path": "mealie/services/household_services/shopping_lists.py",
            "symbols": ["add_recipe_ingredients_to_list", "bulk_create_items"],
            "line_ranges": [[154, 220], [413, 445]],
            "snippet": None,
        },
        {
            "path": "mealie/repos/repository_generic.py",
            "symbols": ["create_many", "update", "update_many"],
            "line_ranges": [[195, 208], [210, 226], [228, 244]],
            "snippet": None,
        },
        {
            "path": "mealie/services/event_bus_service/event_bus_service.py",
            "symbols": ["dispatch", "_publish_event"],
            "line_ranges": [[60, 96]],
            "snippet": None,
        },
    ]
    # Add SC-030/SC-031/SC-032 reciprocal links
    fr011["related_success_criteria"] = ["SC-007", "SC-017", "SC-025", "SC-030", "SC-032"]

    # ------------------------------------------------------------------
    # 4. REWRITE FR-012 — replace REPEATABLE READ + add outbox note
    # ------------------------------------------------------------------
    fr012 = get_fr(spec, "FR-012")
    fr012["text"] = (
        "Idempotency under multi-replica deployment uses a conditional UPDATE issued INSIDE the FR-011 outer transaction BEFORE any shopping-list mutation: "
        "`UPDATE household_preferences SET last_auto_synced_at = :now_naive_utc WHERE id = :pref_id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local_midnight_utc)`. "
        "`:today_local_midnight_utc` is computed as `datetime.combine(household_local_now.date(), time.min, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)` so the comparison runs against a naive-UTC datetime matching the `NaiveDateTime` column type (mealie/db/models/_model_base.py:18-23). "
        "If the UPDATE affects 0 rows, the household was already synced today (by another replica earlier in the same tick, or by a previous scheduler tick) — FR-011 step 4 catches `rowcount == 0` and SHORT-CIRCUITS: the empty outer transaction commits and the worker returns without calling `bulk_create_items` or inserting an outbox row. "
        "Because the CAS happens BEFORE side effects, a CAS loser performs zero writes — `merge_items` (mealie/services/household_services/shopping_lists.py:73-128) would sum quantities if called twice (sums into to_item.quantity at L96), so it is critical that the loser never reaches the merge code path. "
        "The force-mode (FR-020) replaces the WHERE clause with `WHERE id = :pref_id` (unconditional) so the CAS always affects 1 row and the force path always proceeds to side effects. "
        "Transaction-rollback semantics under the outbox pattern (NC-004 / FR-011 / FR-030 / FR-031): if `bulk_create_items` raises OR the outbox INSERT raises, the rollback reverts the CAS UPDATE AND the partial item writes AND the (uncommitted) outbox row, so the marker stays at its prior value and the next scheduler tick retries the full pipeline. "
        "Event-publishing failures are NOT part of the auto-sync transaction — they are handled by the separate `dispatch_event_outbox` task (FR-031) which retries up to MAX_ATTEMPTS=5."
    )

    # ------------------------------------------------------------------
    # 5. REWRITE FR-020 — explicit outbox path + reciprocal links
    # ------------------------------------------------------------------
    fr020 = get_fr(spec, "FR-020")
    fr020["text"] = (
        "Add the route `POST /api/households/preferences/auto-sync-shopping/run-now` on `HouseholdSelfServiceController` (mealie/routes/households/controller_household_self_service.py:20-62). "
        "Guard: `self.checks.can_manage_household()` (mealie/routes/_base/checks.py:23-26). "
        "Behavior: invokes the per-household auto-sync pipeline (FR-009 through FR-021) with `force=True`. "
        "`force=True` bypasses both the FR-009 30-minute window gate AND the FR-012 conditional CAS — the WHERE clause of the UPDATE becomes unconditional (`WHERE id = :pref_id`) so the CAS always affects 1 row and the marker `last_auto_synced_at` is ALWAYS written on success. "
        "The side-effect ordering is otherwise identical to FR-011 (outbox pattern): the unconditional UPDATE + `bulk_create_items(commit=False)` + outbox INSERT run inside the same `with session.begin():` block, so any exception rolls back the marker write, partial item writes, and the outbox row atomically. "
        "Response: HTTP 200 on success with body matching EXACTLY the four-key shape `{'added_count': int, 'skipped_pantry_count': int, 'target_list_id': UUID4 | null, 'run_at': datetime}` (ISO 8601 UTC). "
        "When preconditions fail (today's meal plan is empty OR no target list resolvable), respond HTTP 204 No Content with NO body — matching the input requirement `204 / 0 added`. "
        "The i18n keys from FR-022 are NOT surfaced in the response body; they appear only in server-side logs and in the `EventMealPlanAutoSyncedData.message_key` field on the eventual outbox-dispatched event. "
        "In the absence of any HTTP body, the client treats 204 as 'nothing to do' and reads the i18n key from the event subscription or server logs instead. "
        "Permission failure returns HTTP 403 via the guard."
    )
    # SC-026 reciprocal link
    fr020["related_success_criteria"] = ["SC-012", "SC-023", "SC-026"]

    # ------------------------------------------------------------------
    # 6. REWRITE FR-021 — outbox-based event with message_key field
    # ------------------------------------------------------------------
    fr021 = get_fr(spec, "FR-021")
    fr021["text"] = (
        "Add a new event type `EventTypes.mealplan_auto_synced_to_shopping` to the `EventTypes(Enum)` in `mealie/services/event_bus_service/event_types.py:13-60` "
        "(the comment in that enum confirms that adding a member requires an alembic migration to the subscriber table — covered by FR-024 + ORM/schema additions in FR-028). "
        "Add a new payload class `EventMealPlanAutoSyncedData(EventDocumentDataBase)` in the same file with fields "
        "`document_type: EventDocumentType = EventDocumentType.shopping_list, household_id: UUID4, shopping_list_id: UUID4, added_item_count: int, skipped_pantry_count: int, message_key: str | None = None`. "
        "The `message_key` is the i18n key surface for downstream subscribers (FR-022); it is None on the success path and set to one of the `auto-sync.*` keys on the no-meal-plan / no-target-list / already-synced paths. "
        "The payload reuses the existing `EventDocumentDataBase` (`mealie/services/event_bus_service/event_types.py:88-91`) which provides `operation: EventOperation`. "
        "Auto-sync emits the event via the outbox pattern (NC-004 / FR-011 / FR-031), NOT directly via `EventBusService.dispatch`: "
        "the auto-sync task writes one `event_outbox` row inside the CAS+items transaction; the separate `dispatch_event_outbox` task later calls "
        "`EventBusService(session=session).dispatch(integration_id=INTERNAL_INTEGRATION_ID, group_id=..., household_id=..., event_type=EventTypes.mealplan_auto_synced_to_shopping, document_data=EventMealPlanAutoSyncedData(operation=EventOperation.update, household_id=..., shopping_list_id=..., added_item_count=..., skipped_pantry_count=..., message_key=...), message=message_key or '')` "
        "per the dispatch pattern at `mealie/services/event_bus_service/event_bus_service.py:66-96`. "
        "The dispatcher passes `message=message_key or ''` so the i18n key surfaces inside `EventBusMessage.body` for Apprise/webhook subscribers; the empty-string default still resolves to `'generic'` per the `populate_body` validator at `event_types.py:188-191`, preserving existing behavior on the success path. "
        "Exactly one outbox row per CAS winner — the INSERT sits inside step 6 of FR-011, which is reached only when the FR-012 CAS UPDATE affected 1 row. CAS losers short-circuit at step 4 of FR-011 and never reach the INSERT, so subscribers receive exactly one event per CAS winner (assuming the dispatcher's `dispatched_at` UPDATE is atomic, which it is because it runs inside its own transaction). "
        "Failures during steps 5-6 roll back the transaction and the marker, so the next scheduler tick retries; no outbox row is written and no event is dispatched in that case. "
        "Dispatch-side failures (network, subscriber down) are retried by `dispatch_event_outbox` up to MAX_ATTEMPTS=5, then logged as dead-lettered."
    )
    fr021["related_success_criteria"] = ["SC-013", "SC-025", "SC-027", "SC-031"]
    # Add reference to dispatch lines L82-96 (where the actual publish loop is)
    # current refs already cover :60-96 which is fine

    # ------------------------------------------------------------------
    # 7. REWRITE FR-022 — clarify localization surfaces + reciprocal SC-026
    # ------------------------------------------------------------------
    fr022 = get_fr(spec, "FR-022")
    fr022["text"] = (
        "Add three i18n keys under a NEW top-level `auto-sync` namespace in `mealie/lang/messages/en-US.json` "
        "(file currently has top-level keys `generic` at line 2 and `mealplan` at line 34). "
        "The hyphenated namespace matches existing conventions (`generic.server-error`, `recipe.unique-name-error`). "
        "Required keys with their exact English strings: "
        "`auto-sync.no-meal-plan-today` = `'No meal plan for today; nothing to sync.'`; "
        "`auto-sync.no-target-list` = `'No shopping list is configured or available for auto-sync.'`; "
        "`auto-sync.already-synced-today` = `'This household was already auto-synced today.'`. "
        "These keys surface in exactly two places: (a) server-side logs (`logger.info` / `logger.warning` calls in the auto-sync pipeline), and (b) the optional `message_key` field on `EventMealPlanAutoSyncedData` per FR-021, which the outbox dispatcher then forwards into `EventBusMessage.body` so Apprise / webhook subscribers receive the key. "
        "The keys are NOT included in the HTTP response body of the run-now route — per FR-020 the run-now route returns HTTP 204 with no body on precondition failure and a fixed 4-key JSON shape with no `detail` on success. "
        "Mealie ships 40+ locale files at `mealie/lang/messages/*.json` (en-US, en-GB, fr-FR, zh-CN, af-ZA, ar-SA, etc.); per `.github/copilot-instructions.md` 'Translations' section ONLY `en-US.json` is editable by repository contributors — every other locale is Crowdin-managed and MUST NOT be edited (PRs touching them are rejected). So only `en-US.json` changes for this feature."
    )
    fr022["related_success_criteria"] = ["SC-019", "SC-026"]

    # ------------------------------------------------------------------
    # 8. REWRITE FR-024 — add event_outbox migration
    # ------------------------------------------------------------------
    fr024 = get_fr(spec, "FR-024")
    fr024["text"] = (
        "Add a single alembic revision file under `mealie/alembic/versions/` modeled on the announcements migration "
        "(`mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py:1-32` for the upgrade template). "
        "The `upgrade()` function MUST: "
        "(A) `with op.batch_alter_table('household_preferences') as batch_op:` add five columns "
        "(`auto_sync_meal_plan_to_shopping Boolean NOT NULL server_default sa.false()`, "
        "`auto_sync_target_shopping_list_id GUID NULL`, "
        "`auto_sync_run_time String NOT NULL server_default '00:00'`, "
        "`timezone String NULL`, "
        "`last_auto_synced_at DateTime NULL`) "
        "AND THEN call `batch_op.create_foreign_key('fk_household_preferences_auto_sync_target', 'shopping_lists', ['auto_sync_target_shopping_list_id'], ['id'], ondelete='SET NULL')` modeled on the FK pattern at `mealie/alembic/versions/2024-02-23-16.15.07_2298bb460ffd_added_user_to_shopping_list.py:86`; "
        "(B) `op.create_table('household_pantry_staples', sa.Column('household_id', GUID, sa.ForeignKey('households.id', ondelete='CASCADE'), index=True), sa.Column('food_id', GUID, sa.ForeignKey('ingredient_foods.id', ondelete='CASCADE'), index=True), sa.UniqueConstraint('household_id', 'food_id', name='household_pantry_staple_unique'))` "
        "— note the explicit `ondelete='CASCADE'` per FR-002, which deliberately deviates from the parallel `households_to_ingredient_foods` table (`mealie/db/models/recipe/ingredient.py:21-27`) that omits CASCADE; "
        "(C) `with op.batch_alter_table('group_events_notifier_options') as batch_op:` add `mealplan_auto_synced_to_shopping Boolean NOT NULL server_default sa.false()` for the new event subscription column "
        "— note the table name is `group_events_notifier_options` (verified at `mealie/db/models/household/events.py:16` and at the existing migration `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py:21`); v2 wrongly said `group_event_notifier_options` (missing the 's' in `events`); "
        "(D) per FR-031, `op.create_table('event_outbox', sa.Column('id', GUID, primary_key=True), sa.Column('group_id', GUID, nullable=False, index=True), sa.Column('household_id', GUID, nullable=True), sa.Column('event_type', String(length=128), nullable=False), sa.Column('payload_json', Text, nullable=False), sa.Column('created_at', DateTime, nullable=False), sa.Column('dispatched_at', DateTime, nullable=True, index=True), sa.Column('attempts', Integer, nullable=False, server_default=sa.text('0')), sa.Column('last_error', Text, nullable=True))` plus `op.create_index('ix_event_outbox_undispatched', 'event_outbox', ['dispatched_at', 'created_at'])` to keep the dispatcher poll query efficient. "
        "The `downgrade()` function reverses each step in reverse order modeled on lines 35-47 of the announcement template: "
        "drop `event_outbox` (and its indices), drop the new subscription column, drop the new association table, drop the new FK constraint via `batch_op.drop_constraint('fk_household_preferences_auto_sync_target', type_='foreignkey')`, drop the five preference columns."
    )
    fr024["related_success_criteria"] = ["SC-002", "SC-020", "SC-027", "SC-028", "SC-031"]

    # ------------------------------------------------------------------
    # 9. UPDATE FR-001 — reciprocal SC-028 link
    # ------------------------------------------------------------------
    fr001 = get_fr(spec, "FR-001")
    if "SC-028" not in fr001["related_success_criteria"]:
        fr001["related_success_criteria"] = list(fr001["related_success_criteria"]) + ["SC-028"]

    # ------------------------------------------------------------------
    # 10. UPDATE FR-014 — add filter implementation citations
    # ------------------------------------------------------------------
    fr014 = get_fr(spec, "FR-014")
    fr014["text"] = (
        "Target shopping list ownership is enforced at TWO checkpoints: "
        "(A) PATCH-time in FR-006 uses `self.repos.group_shopping_lists.get_one(target_id)` against the household-scoped repo (`mealie/repos/repository_factory.py:317-321`); "
        "the generic `get_one` implementation at `mealie/repos/repository_generic.py:156-179` calls `_filter_builder` (`:94-102`) which automatically prepends "
        "`group_id` and `household_id` to the WHERE clause via SQLAlchemy `filter_by(**fltr)` (`:170-172`); "
        "a None return raises HTTP 422 with detail `'auto_sync_target_shopping_list_id does not refer to a shopping list owned by this household'`. "
        "(B) Sync-time in FR-011 re-runs the same `get_one(target_id)` against the household-scoped repo at task execution time so a list that was deleted or transferred after PATCH cannot leak into another household's sync. "
        "Cross-household writes are structurally impossible because `RepositoryShoppingList` carries the `household_id` and `_filter_builder` applies it as a `filter_by` clause on every query (`repository_generic.py:94-102`, `:156-179`, `:316-355`). "
        "See `ShoppingList` (`mealie/db/models/household/shopping_list.py:147-181`) for the model definition."
    )
    fr014["code_references"] = [
        {
            "path": "mealie/repos/repository_factory.py",
            "symbols": ["group_shopping_lists", "RepositoryShoppingList", "household_id"],
            "line_ranges": [[317, 321]],
            "snippet": None,
        },
        {
            "path": "mealie/repos/repository_generic.py",
            "symbols": ["_filter_builder", "get_one", "page_all"],
            "line_ranges": [[94, 102], [156, 179], [315, 355]],
            "snippet": None,
        },
        {
            "path": "mealie/db/models/household/shopping_list.py",
            "symbols": ["ShoppingList", "household_id", "user_id"],
            "line_ranges": [[147, 181]],
            "snippet": None,
        },
    ]

    # ------------------------------------------------------------------
    # 11. UPDATE FR-023 — add filter implementation citations + reciprocal SC-029
    # ------------------------------------------------------------------
    fr023 = get_fr(spec, "FR-023")
    fr023["text"] = (
        "All auto-sync queries MUST use household-scoped repos. `repos.meals` (`mealie/repos/repository_factory.py:297-301`) carries `household_id` and applies it as a WHERE clause in `get_today` (`mealie/repos/repository_meals.py:11-21`). "
        "`repos.household_preferences` (`mealie/repos/repository_factory.py:244-253`) is also household-scoped. "
        "`repos.group_shopping_lists` (`mealie/repos/repository_factory.py:317-321`) is household-scoped via `household_id=self.household_id`. "
        "The generic implementation of household scoping lives in `_filter_builder` at `mealie/repos/repository_generic.py:94-102`, which prepends `group_id` and `household_id` to every `_query_one` / `get_one` / `page_all` WHERE clause (`:156-179`, `:316-355`). "
        "The task loop MUST build `repos = get_repositories(session, group_id=group.id, household_id=household.id)` per household rather than reusing a single `AllRepositories` instance, so the scope is correct on every iteration. Cross-household and cross-group reads are structurally prevented."
    )
    fr023["code_references"] = [
        {
            "path": "mealie/repos/repository_factory.py",
            "symbols": ["household_preferences", "meals", "group_shopping_lists", "household_id"],
            "line_ranges": [[244, 253], [297, 301], [317, 321]],
            "snippet": None,
        },
        {
            "path": "mealie/repos/repository_meals.py",
            "symbols": ["get_today", "household_id"],
            "line_ranges": [[11, 21]],
            "snippet": None,
        },
        {
            "path": "mealie/repos/repository_generic.py",
            "symbols": ["_filter_builder", "get_one", "page_all"],
            "line_ranges": [[94, 102], [156, 179], [315, 355]],
            "snippet": None,
        },
    ]
    fr023["related_success_criteria"] = ["SC-006", "SC-029"]

    # ------------------------------------------------------------------
    # 12. ADD FR-030 — no-commit refactor of repo + shopping-list seams
    # ------------------------------------------------------------------
    fr030 = {
        "id": "FR-030",
        "text": (
            "Extend the existing repo + shopping-list write seams with a `commit: bool = True` keyword parameter so the auto-sync task can keep all writes inside one outer transaction (NC-004 recommended default). "
            "Concretely: "
            "(A) `RepositoryGeneric.create_many(self, data, commit: bool = True)` (`mealie/repos/repository_generic.py:195-208`) — guard the existing `self.session.commit()` call (line 203) with `if commit: self.session.commit()`; the `session.refresh(...)` loop and return value are unchanged. "
            "(B) `RepositoryGeneric.update(self, match_value, new_data, commit: bool = True)` (`:210-226`) — guard the existing `self.session.commit()` (line 225) with `if commit: self.session.commit()`. "
            "(C) `RepositoryGeneric.update_many(self, data, commit: bool = True)` (`:228-244`) — guard the existing `self.session.commit()` (line 243) with `if commit: self.session.commit()`. "
            "(D) `ShoppingListService.bulk_create_items(self, create_items, auto_find_labels=True, commit: bool = True)` (`mealie/services/household_services/shopping_lists.py:154-220`) — forward `commit=commit` into the `self.list_items.create_many(...)` (line 215) and `self.list_items.update_many(...)` (line 216) calls. "
            "(E) `ShoppingListService.add_recipe_ingredients_to_list(self, list_id, recipe_items, commit: bool = True)` (`mealie/services/household_services/shopping_lists.py:413-445`) — forward `commit=commit` into the `bulk_create_items(...)` call (line 433) AND the eventual `shopping_lists.update(...)` call inside the same method (the list-level `recipe_references` update). "
            "Default `commit=True` preserves existing behavior for every current caller; the auto-sync task (FR-011) and the force-mode run-now (FR-020) are the only callers that pass `commit=False`. "
            "Backward compatibility: a repo-wide grep confirms no current caller passes a positional `commit` argument; the new kwarg is keyword-only by convention (placed after existing kwargs) so no signature mismatch occurs at the existing call sites at `mealie/services/household_services/shopping_lists.py:215-216`, `mealie/routes/households/controller_household_self_service.py:58-62` (the existing PUT route), or any other repo client. "
            "The auto-sync task itself issues a single `session.commit()` at the end of the outer `with session.begin():` block (FR-011 step 7), which atomically persists every staged write."
        ),
        "requirement_type": "functional",
        "related_user_stories": ["US-2", "US-3"],
        "related_success_criteria": ["SC-030", "SC-032"],
        "code_references": [
            {
                "path": "mealie/repos/repository_generic.py",
                "symbols": ["create_many", "update", "update_many"],
                "line_ranges": [[195, 208], [210, 226], [228, 244]],
                "snippet": None,
            },
            {
                "path": "mealie/services/household_services/shopping_lists.py",
                "symbols": ["bulk_create_items", "add_recipe_ingredients_to_list"],
                "line_ranges": [[154, 220], [413, 445]],
                "snippet": None,
            },
        ],
        "testable": True,
    }

    # ------------------------------------------------------------------
    # 13. ADD FR-031 — event_outbox table + dispatcher task
    # ------------------------------------------------------------------
    fr031 = {
        "id": "FR-031",
        "text": (
            "Implement the transactional event outbox required by NC-004 / FR-011 / FR-021. "
            "(A) Add a new ORM model `EventOutboxModel(SqlAlchemyBase, BaseMixins)` in `mealie/db/models/group/event_outbox.py` (new file) with columns matching FR-024 step D: "
            "`id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)`, "
            "`group_id: Mapped[GUID] = mapped_column(GUID, nullable=False, index=True)`, "
            "`household_id: Mapped[GUID | None] = mapped_column(GUID, nullable=True)`, "
            "`event_type: Mapped[str] = mapped_column(String(128), nullable=False)`, "
            "`payload_json: Mapped[str] = mapped_column(Text, nullable=False)`, "
            "`created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))`, "
            "`dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)`, "
            "`attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text('0'))`, "
            "`last_error: Mapped[str | None] = mapped_column(Text, nullable=True)`. Register it on the `Base` metadata. "
            "(B) Add a minimal `RepositoryEventOutbox(RepositoryGeneric[EventOutboxOut, EventOutboxModel])` (new file `mealie/repos/repository_event_outbox.py`) and expose it via `AllRepositories.event_outbox` (`mealie/repos/repository_factory.py`). "
            "(C) The auto-sync task (FR-011 step 6) writes one row via `session.add(EventOutboxModel(group_id=..., household_id=..., event_type='mealplan_auto_synced_to_shopping', payload_json=EventMealPlanAutoSyncedData(...).model_dump_json(), created_at=datetime.now(UTC)))` — `session.add` participates in the outer transaction WITHOUT committing, so the row commits atomically with the CAS marker and the shopping-list writes when the `with session.begin():` block exits. "
            "(D) Create a new scheduler task `mealie/services/scheduler/tasks/dispatch_event_outbox.py` with top-level callable `dispatch_event_outbox()` registered via `SchedulerRegistry.register_minutely(dispatch_event_outbox)` in `mealie/services/scheduler/tasks/__init__.py`. "
            "Per tick: `rows = session.execute(select(EventOutboxModel).where(EventOutboxModel.dispatched_at.is_(None), EventOutboxModel.attempts < 5).order_by(EventOutboxModel.created_at).limit(100)).scalars().all()`. "
            "For each row: deserialize `payload_json` into `EventMealPlanAutoSyncedData.model_validate_json(...)`; "
            "construct an `EventBusService(session=session)` and call `service.dispatch(integration_id=INTERNAL_INTEGRATION_ID, group_id=row.group_id, household_id=row.household_id, event_type=EventTypes[row.event_type], document_data=payload, message=payload.message_key or '')` per the dispatch pattern at `mealie/services/event_bus_service/event_bus_service.py:66-96`. "
            "On success: `row.dispatched_at = datetime.now(UTC); session.commit()`. "
            "On exception: `row.attempts += 1; row.last_error = str(exc)[:1000]; session.commit()`. "
            "(E) When `row.attempts >= 5` the dispatcher skips the row and logs a structured dead-letter warning with `event_outbox.id` and `last_error`; operators can re-attempt by updating `attempts` back to 0 via DB. MAX_ATTEMPTS=5 is a constant in `dispatch_event_outbox.py`. "
            "(F) `dispatch_event_outbox` operates on ALL groups/households in one tick — it does NOT use the per-household scoped repos because the outbox is a global publishing channel; cross-tenant correctness comes from `row.group_id` / `row.household_id` being copied verbatim into the dispatch call so the existing `EventBusService._publish_event` -> `AppriseEventListener` / `WebhookEventListener` subscriber resolution operates against the correct tenant. "
            "This design decouples external delivery latency from the auto-sync transaction (NEW-ARCH-H-1 / EXEC-C-002 resolution) and provides at-least-once semantics; combined with the single outbox INSERT per CAS winner (FR-011 step 6), subscribers see exactly one delivery per CAS winner under normal operation and at most MAX_ATTEMPTS deliveries under retry pathways (so subscribers SHOULD treat dispatch as idempotent for the same `event_outbox.id`, surfaced via `Event.event_id` at `event_types.py:204-207`)."
        ),
        "requirement_type": "functional",
        "related_user_stories": ["US-5"],
        "related_success_criteria": ["SC-031", "SC-032"],
        "code_references": [
            {
                "path": "mealie/services/event_bus_service/event_bus_service.py",
                "symbols": ["dispatch", "_publish_event", "EventBusService"],
                "line_ranges": [[42, 96]],
                "snippet": None,
            },
            {
                "path": "mealie/services/event_bus_service/event_types.py",
                "symbols": ["EventTypes", "Event", "EventBusMessage"],
                "line_ranges": [[13, 60], [179, 207]],
                "snippet": None,
            },
            {
                "path": "mealie/services/scheduler/scheduler_registry.py",
                "symbols": ["SchedulerRegistry", "register_minutely", "_minutely"],
                "line_ranges": [[8, 49]],
                "snippet": None,
            },
        ],
        "testable": True,
    }

    spec["functional_requirements"].append(fr030)
    spec["functional_requirements"].append(fr031)

    # ------------------------------------------------------------------
    # 14. UPDATE FR-026 — add tests for outbox + no-commit + dispatch retry
    # ------------------------------------------------------------------
    fr026 = get_fr(spec, "FR-026")
    fr026["text"] = (
        "[NFR] Test matrix per META-011 + META-V2-005 + META-V2-008 + META-V3-NC004: "
        "(A) unit tests under `tests/unit_tests/services/scheduler/` covering: window-gate boundaries (just-before, on-instant, just-after, end-of-window), "
        "CAS UPDATE wins / loses race (mock 0-row response, assert loser writes zero outbox rows and zero items), "
        "force=True bypass (unconditional UPDATE), empty meal plan (no outbox row, no marker), null timezone fallback to UTC, "
        "pantry-filter predicate with empty staple set, pantry-filter with sub-recipe ingredient; "
        "(B) integration tests under `tests/integration_tests/user_household_tests/` covering: "
        "PATCH partial update roundtrip (only requested fields change), PATCH rejects `last_auto_synced_at`-bearing body with 422 (extra='forbid' on the partial schema), "
        "PUT roundtrip with new fields, run-now success with exact 4-key response shape per FR-020 (HTTP 200), "
        "run-now precondition failure returns HTTP 204 with NO body when meal plan is empty (input requirement 5 'when no meal plan today returns 204 / 0 added'), "
        "run-now precondition failure returns HTTP 204 with NO body when no target list resolvable, run-now 403 for non-admin user, "
        "scheduler tick end-to-end exercising `add_recipe_ingredients_to_list(commit=False)` (`mealie/services/household_services/shopping_lists.py:413-445`) and asserting `bulk_create_items` is invoked exactly once per CAS winner per tick AND exactly one row is inserted into `event_outbox` per CAS winner; "
        "(C) new outbox tests under `tests/integration_tests/services/event_bus/`: "
        "atomic-commit test asserting CAS marker + items + outbox row commit together (induce exception inside the outer transaction and assert NONE of the three persists); "
        "no-commit behavior test asserting `create_many(commit=False)` / `update_many(commit=False)` do NOT call `session.commit()` (assert via session state inspection or a `session.commit` spy); "
        "dispatcher poll test asserting `dispatch_event_outbox` reads undispatched rows ordered by `created_at`, calls `EventBusService.dispatch` once per row, and sets `dispatched_at` on success; "
        "dispatcher retry test asserting that on `EventBusService.dispatch` exception the row's `attempts` is incremented and `last_error` is populated, with re-poll until MAX_ATTEMPTS=5 then dead-letter logging. "
        "Multitenant suite under `tests/multitenant_tests/` covers same-group cross-household isolation (FR-027) and cross-group isolation (FR-029)."
    )

    # ------------------------------------------------------------------
    # 15. REWRITE US-9 — align with 204/no-body contract
    # ------------------------------------------------------------------
    us9 = get_us(spec, "US-9")
    us9["description"] = (
        "As an operator monitoring server logs and downstream event-bus subscribers, I want the auto-sync pipeline to surface localized i18n keys "
        "in BOTH server-side logs AND the `EventMealPlanAutoSyncedData.message_key` field on dispatched events (per FR-021), so that the system "
        "message format matches every other Mealie endpoint and the message keys match the input specification verbatim. The HTTP response of the "
        "run-now route does NOT carry the i18n key — precondition-failure responses are HTTP 204 with empty body per FR-020 — so clients distinguish "
        "'work done' (200 + 4-key JSON) from 'nothing to do' (204 empty) by status code alone, while the i18n key remains accessible via server logs "
        "and event subscriptions."
    )
    us9["why_this_priority"] = (
        "Consistency with the repo-wide en-US-only locale convention and input requirement 4 — the keys MUST be exact (auto-sync.no-meal-plan-today, "
        "auto-sync.no-target-list, auto-sync.already-synced-today) so downstream consumers can match against them programmatically. The HTTP 204 / "
        "no-body contract on the run-now precondition-failure path is locked in by FR-020 / SC-026 (input requirement 5: '204 / 0 added')."
    )
    us9["independent_test"] = (
        "Trigger run-now (POST /api/households/preferences/auto-sync-shopping/run-now) on a household with no active meal plan; "
        "assert the HTTP response is exactly status 204 with Content-Length 0 AND a server-side WARN-level log line is emitted whose i18n key field "
        "equals `auto-sync.no-meal-plan-today`. The response body MUST be zero bytes (no JSON `detail`, no localized string)."
    )
    us9["acceptance"] = [
        {
            "given": "a household with no meal plan for today",
            "when": "run-now is invoked (POST /api/households/preferences/auto-sync-shopping/run-now) by a can_manage_household=true user",
            "then": "the HTTP response is status 204 with Content-Length 0 AND zero response body bytes AND a server-side WARN-level log entry is emitted with i18n key field equal to `auto-sync.no-meal-plan-today` AND zero rows are inserted into `event_outbox`",
        },
        {
            "given": "a household whose auto_sync_target_shopping_list_id has been set to a deleted list",
            "when": "the scheduled auto-sync task runs for that household",
            "then": "the server-side WARN-level log entry uses i18n key `auto-sync.no-target-list` AND `last_auto_synced_at` is NOT bumped AND no `event_outbox` row is inserted",
        },
        {
            "given": "a household that has already been auto-synced today AND a subscriber is registered for the mealplan_auto_synced_to_shopping event type",
            "when": "the scheduled auto-sync task fires again on the same household-local day (CAS loser path)",
            "then": "no new outbox row is inserted, so the subscriber receives zero additional events; the only dispatched event for this household-day was the original CAS-winner event whose `EventMealPlanAutoSyncedData.message_key` field was None on the success path",
        },
    ]

    # ------------------------------------------------------------------
    # 16. UPDATE Edge cases:
    #   - Fix Postgres isolation-level wording
    #   - Update force-mode mid-tx exception to reference outbox rollback
    # ------------------------------------------------------------------
    for ec in spec["edge_cases"]:
        if "Two replicas tick" in ec["description"]:
            ec["handling"] = (
                "Each replica opens its own outer DB transaction (`with session.begin():`) and races to issue the FR-012 conditional UPDATE. "
                "The DB serializes the conflicting UPDATEs at the row level (PostgreSQL default isolation level is READ COMMITTED, which still "
                "serializes concurrent UPDATEs on the same row via row-level write locks; SQLite serializes via its per-statement lock). "
                "The second-arriving UPDATE sees the marker already advanced and affects 0 rows. FR-011 step 4 catches rowcount=0, the empty "
                "outer transaction commits cleanly, and the worker returns without calling `bulk_create_items(commit=False)` or inserting a row into `event_outbox`. "
                "Result: exactly one replica (the CAS winner) writes items and inserts exactly one outbox row; the CAS loser is a structural no-op. "
                "Subscribers receive exactly one event per CAS winner because (a) the outbox insert happens only on CAS-winner commit, and (b) the "
                "dispatcher (FR-031) marks `dispatched_at` atomically before the row is re-eligible for polling. There is no duplicate-event "
                "tolerance assumption on subscribers under normal operation."
            )
        elif "Force-mode run-now mid-transaction exception" in ec["description"]:
            ec["handling"] = (
                "FR-020 force=True replaces the CAS WHERE clause with an unconditional UPDATE. The unconditional UPDATE runs inside the same "
                "outer transaction (`with session.begin():`) as `bulk_create_items(commit=False)` + the outbox INSERT. If any step raises an "
                "exception (e.g. DB constraint violation, outbox row INSERT failure), the entire transaction rolls back including the unconditional "
                "UPDATE — so `last_auto_synced_at` reverts to its prior value AND the partial item writes are discarded AND no outbox row is "
                "persisted. The route returns HTTP 500 (the exception surfaces to FastAPI's default error handler); the caller can safely retry "
                "the run-now invocation. Subscribers see no event for this attempt because the outbox INSERT never committed."
            )

    # ------------------------------------------------------------------
    # 17. UPDATE Out of scope — fix the stale locale sentence + drop subscriber-dedup mention if present
    # ------------------------------------------------------------------
    new_oos = []
    for item in spec["out_of_scope"]:
        if "Mealie currently ships only en-US.json" in item:
            new_oos.append(
                "Internationalization changes for non-en-US locales. Mealie ships 40+ Crowdin-managed locale files at `mealie/lang/messages/*.json` "
                "(en-US, en-GB, fr-FR, zh-CN, af-ZA, ar-SA, …); per `.github/copilot-instructions.md` 'Translations' section ONLY `en-US.json` is "
                "editable by repository contributors. PRs touching other locale files are rejected — Crowdin back-fills the keys on its own cadence."
            )
        else:
            new_oos.append(item)
    spec["out_of_scope"] = new_oos

    # ------------------------------------------------------------------
    # 18. UPDATE Self-concerns — revise FR-021 self-concern to reflect outbox
    #    Also add a new self-concern for outbox publisher race
    # ------------------------------------------------------------------
    for sc in spec["self_concerns"]:
        if sc["location"] == "FR-021":
            sc["concern"] = (
                "The outbox INSERT and the migration column AND the ORM/schema additions (FR-028) and the new `event_outbox` model + repo (FR-031) "
                "must all be present in production for the new event type to reach subscribers. If a deployment runs the new code against a partially-"
                "migrated database (subscriber column or `event_outbox` table missing) OR with stale ORM/schema (missing the new field), "
                "the auto-sync transaction will fail at the outbox INSERT step and the CAS marker will roll back so the next tick retries — "
                "but the household will never auto-sync until the migration completes."
            )
            sc["evidence_gap"] = (
                "We have not exercised the pre-migration / stale-ORM path explicitly. The recommended defense is to verify at app startup that "
                "(a) the `event_outbox` table exists via SQLAlchemy reflection, (b) `GroupEventNotifierOptions` has the `mealplan_auto_synced_to_shopping` "
                "attribute, AND (c) the subscriber-options column exists on `group_events_notifier_options` — failing app startup if any is absent."
            )
            sc["suggested_resolution"] = (
                "Implement a startup check (a single integration test covers this) that asserts the `event_outbox` table is reflectable AND the "
                "GroupEventNotifierOptions schema attribute exists AND the underlying column exists; raise a startup exception otherwise so the "
                "deployment fails fast rather than silently misbehaving until the migration runs."
            )

    # NEW self-concern: outbox publisher latency / poison pill behavior
    spec["self_concerns"].append({
        "location": "FR-031",
        "concern": (
            "The `dispatch_event_outbox` task polls every 5 minutes, so worst-case dispatch latency for an auto-sync event is ~5 minutes from CAS-winner commit "
            "to subscriber delivery. For a household whose downstream Apprise / webhook subscriber is itself failing, the same row will be retried up to "
            "MAX_ATTEMPTS=5 times before being dead-lettered — operators relying on real-time webhooks may perceive this as 'event delay' rather than 'event "
            "loss'. The dispatcher's retry uses a constant 5-minute interval (no exponential backoff) because that is the existing scheduler bucket; a "
            "future enhancement could add backoff."
        ),
        "evidence_gap": (
            "We have not benchmarked the dispatch_event_outbox poll throughput against a worst-case backlog (e.g. thousands of households all completing auto-sync "
            "within the same 30-minute window). The 100-row batch limit per tick is a defensive bound but may need tuning under load."
        ),
        "suggested_resolution": (
            "Ship with the 100-row batch limit and constant 5-minute retry interval. Add operational metrics: `event_outbox_undispatched_count`, "
            "`event_outbox_dead_letter_count`, `event_outbox_dispatch_latency_seconds`. Tune batch size and consider exponential backoff if observed "
            "latency exceeds 5 minutes p95 in production."
        ),
    })

    # ------------------------------------------------------------------
    # 19. UPDATE Assumptions — add explicit outbox-related assumption
    # ------------------------------------------------------------------
    spec["assumptions"].append(
        "The new `event_outbox` table is the durable record of pending event dispatches. Operators retain the ability to inspect undispatched / dead-lettered rows "
        "via direct DB query; an admin UI is out of scope for v1. Subscribers SHOULD treat events as idempotent for the same `Event.event_id` (`mealie/services/event_bus_service/event_types.py:204-207`) because the dispatcher may re-deliver on transient failures."
    )

    # ------------------------------------------------------------------
    # 20. UPDATE Key Entities — add EventOutbox + revise EventMealPlanAutoSyncedData
    # ------------------------------------------------------------------
    for ke in spec["key_entities"]:
        if ke["name"] == "EventMealPlanAutoSyncedData":
            ke["description"] = (
                "New EventDocumentDataBase subclass per FR-021 carrying the post-sync payload. No PII (no user names, recipe names, or ingredient details) — only ids, "
                "counts, and an optional i18n key so webhook subscribers can fan out without leaking household data. The `message_key` field carries one of the "
                "`auto-sync.*` i18n keys (FR-022) on the error/no-op event paths, or None on the success path."
            )
            ke["fields"] = [
                "document_type: EventDocumentType = EventDocumentType.shopping_list",
                "operation: EventOperation",
                "household_id: UUID4",
                "shopping_list_id: UUID4",
                "added_item_count: int",
                "skipped_pantry_count: int",
                "message_key: str | None = None",
            ]

    spec["key_entities"].append({
        "name": "EventOutboxModel",
        "description": (
            "Durable record of a pending external event dispatch, per FR-031. Written inside the auto-sync outer transaction (FR-011 step 6) so it commits "
            "atomically with the CAS marker and shopping-list writes. Consumed by the `dispatch_event_outbox` minutely scheduler task (FR-031 step D) which "
            "calls `EventBusService.dispatch` and marks `dispatched_at` on success, or increments `attempts` on failure (capped at MAX_ATTEMPTS=5)."
        ),
        "fields": [
            "id: GUID PRIMARY KEY",
            "group_id: GUID NOT NULL (index)",
            "household_id: GUID NULL",
            "event_type: String(128) NOT NULL (matches EventTypes.name)",
            "payload_json: Text NOT NULL (JSON-serialized EventDocumentDataBase subclass)",
            "created_at: DateTime NOT NULL",
            "dispatched_at: DateTime NULL (index for poll query)",
            "attempts: Integer NOT NULL DEFAULT 0",
            "last_error: Text NULL",
        ],
        "references": ["Household", "Group", "EventMealPlanAutoSyncedData"],
    })

    # ------------------------------------------------------------------
    # 21. ADD NEW SCs: SC-030 (commit-flag), SC-031 (outbox dispatcher),
    #    SC-032 (atomic rollback)
    # ------------------------------------------------------------------
    spec["success_criteria"].append({
        "id": "SC-030",
        "text": (
            "When `RepositoryGeneric.create_many(data, commit=False)` is called inside an explicit outer transaction, `self.session.commit()` is NOT invoked "
            "by the method body (verifiable via a session-spy that records `commit` calls). The same assertion holds for `update(commit=False)`, "
            "`update_many(commit=False)`, `ShoppingListService.bulk_create_items(commit=False)`, and `ShoppingListService.add_recipe_ingredients_to_list(commit=False)`. "
            "When the same methods are called WITHOUT the kwarg or with `commit=True`, exactly one `commit` call is recorded per existing-behavior baseline."
        ),
        "metric": "count of session.commit invocations during create_many/update_many/update/bulk_create_items/add_recipe_ingredients_to_list calls with commit=False vs commit=True",
        "threshold": "exactly 0 commit invocations when commit=False is passed; exactly 1 commit invocation when commit=True is passed (or kwarg omitted)",
        "technology_agnostic": True,
        "related_requirements": ["FR-030", "FR-011"],
    })
    spec["success_criteria"].append({
        "id": "SC-031",
        "text": (
            "After an auto-sync CAS winner commits, exactly one row exists in `event_outbox` with `event_type='mealplan_auto_synced_to_shopping'`, "
            "`group_id` matching the household's group, `household_id` matching the household, `dispatched_at IS NULL`, `attempts=0`, and a "
            "`payload_json` that round-trips back to a valid `EventMealPlanAutoSyncedData` via `model_validate_json`. After one tick of "
            "`dispatch_event_outbox`, `EventBusService.dispatch` has been called exactly once with the correct event_type/document_data/group_id/household_id, "
            "and the row's `dispatched_at` is set to a recent UTC datetime (within the last minute) while `attempts` remains 0. If `EventBusService.dispatch` "
            "raises, the row's `attempts` increments to 1 and `last_error` is populated with the exception string."
        ),
        "metric": "outbox row count + dispatched_at population + attempts increment behavior after one CAS winner + one dispatcher tick",
        "threshold": "exactly 1 outbox row per CAS winner; dispatched_at set within 1 minute of the dispatcher tick on success; attempts=1 and last_error populated on dispatch exception",
        "technology_agnostic": True,
        "related_requirements": ["FR-021", "FR-031"],
    })
    spec["success_criteria"].append({
        "id": "SC-032",
        "text": (
            "Atomicity guarantee for the auto-sync outer transaction (FR-011 / NC-004): inject an exception immediately AFTER the outbox INSERT (step 6) and BEFORE the "
            "implicit commit at the end of the `with session.begin():` block. Assert that ALL THREE pieces of state are absent post-failure: "
            "(a) `household_preferences.last_auto_synced_at` is unchanged from its pre-call value, "
            "(b) `shopping_list_items` count for the target list is unchanged from its pre-call value, "
            "(c) zero rows exist in `event_outbox` for this household-day. "
            "Repeat the assertion injecting the exception (i) before step 5 (CAS only), (ii) during step 5 (CAS + partial items), and (iii) during step 6 (CAS + items + partial outbox) — all three must satisfy (a)+(b)+(c)."
        ),
        "metric": "pre/post equality of last_auto_synced_at, shopping_list_items count, and event_outbox row count when an exception is injected at three different stages of the outer transaction",
        "threshold": "all three pieces of state are byte-equal to their pre-call snapshots in all three injection scenarios; zero partial commits observed",
        "technology_agnostic": True,
        "related_requirements": ["FR-011", "FR-030", "FR-031"],
    })

    # ------------------------------------------------------------------
    # 22. UPDATE SC-013 — clarify outbox semantics
    # ------------------------------------------------------------------
    sc013 = get_sc(spec, "SC-013")
    sc013["text"] = (
        "A successful auto-sync run (CAS winner) results in exactly ONE row inserted into `event_outbox` carrying "
        "`event_type='mealplan_auto_synced_to_shopping'`, `payload_json` deserializable to `EventMealPlanAutoSyncedData` with fields "
        "`{operation, household_id, shopping_list_id, added_item_count, skipped_pantry_count, message_key}`. After the next tick of "
        "`dispatch_event_outbox` (FR-031), `EventBusService.dispatch` is invoked exactly ONCE with that payload and the row's `dispatched_at` is set. "
        "A CAS loser (concurrent replica or same-day re-run) inserts zero outbox rows and therefore triggers zero downstream dispatches. "
        "Under retry (dispatcher exception path), the same outbox row may be redelivered up to MAX_ATTEMPTS=5 times — subscribers MUST treat "
        "deliveries with the same `Event.event_id` as idempotent."
    )
    sc013["metric"] = "outbox row count and EventBusService.dispatch call count per CAS winner vs CAS loser, plus payload field presence on the winner"
    sc013["threshold"] = (
        "exactly 1 outbox row + exactly 1 dispatch per CAS winner under normal operation (all 6 required payload fields including message_key present); "
        "exactly 0 outbox rows + exactly 0 dispatches per CAS loser; at most MAX_ATTEMPTS=5 deliveries per outbox row under retry"
    )
    sc013["related_requirements"] = ["FR-021", "FR-031"]

    # ------------------------------------------------------------------
    # 23. UPDATE SC-007 — clarify outbox semantics for re-run
    # ------------------------------------------------------------------
    sc007 = get_sc(spec, "SC-007")
    sc007["text"] = (
        "Running the auto-sync task twice in a row for the same household on the same household-local day results in: "
        "(a) `last_auto_synced_at` written exactly ONCE across both invocations (first invocation's CAS sets it, second invocation's CAS returns 0 rows and short-circuits); "
        "(b) zero new `shopping_list_item` rows on the second invocation; "
        "(c) zero `event_outbox` rows inserted on the second invocation (so zero additional `EventBusService.dispatch` calls from the dispatcher); "
        "(d) zero calls to `bulk_create_items` on the second invocation."
    )
    sc007["metric"] = "count of marker writes, item inserts, outbox row inserts, and bulk_create_items calls on the second invocation"
    sc007["threshold"] = (
        "exactly 1 marker write across both invocations; 0 new item rows, 0 new outbox row inserts, and 0 bulk_create_items calls on the second invocation"
    )

    # ------------------------------------------------------------------
    # 24. UPDATE SC-025 — outbox-aware
    # ------------------------------------------------------------------
    sc025 = get_sc(spec, "SC-025")
    sc025["text"] = (
        "When `repos.meals.get_today(...)` returns `[]` for a household, no row is inserted into `event_outbox` for that household in that tick "
        "(so the next `dispatch_event_outbox` tick also makes 0 `EventBusService.dispatch` calls related to that household)."
    )
    sc025["metric"] = "event_outbox row insertion count for a household with empty get_today result (and downstream dispatch count)"
    sc025["threshold"] = "exactly 0 event_outbox row inserts; exactly 0 EventBusService.dispatch calls"
    sc025["related_requirements"] = ["FR-011", "FR-021", "FR-031"]

    # ------------------------------------------------------------------
    # 25. UPDATE SC-027 reciprocal links — also list FR-021
    # ------------------------------------------------------------------
    sc027 = get_sc(spec, "SC-027")
    sc027["related_requirements"] = ["FR-021", "FR-024", "FR-028"]

    # SC-028 reciprocal — add FR-001
    sc028 = get_sc(spec, "SC-028")
    sc028["related_requirements"] = ["FR-001", "FR-024"]

    # SC-029 reciprocal — already lists FR-023 implicitly via context; explicit
    sc029 = get_sc(spec, "SC-029")
    if "FR-023" not in sc029["related_requirements"]:
        sc029["related_requirements"] = list(sc029["related_requirements"]) + ["FR-023"]
    if "FR-029" not in sc029["related_requirements"]:
        sc029["related_requirements"] = list(sc029["related_requirements"]) + ["FR-029"]

    # SC-026 reciprocal — already lists FR-020, FR-022; ensure that
    # FR-020 and FR-022 list SC-026 (done above in FR-020/FR-022 updates)

    return spec


def main() -> None:
    v3 = load_v3()
    v4 = apply_v4_changes(v3)

    # Write JSON
    v4_path = SPECS / "spec_v4.json"
    v4_path.write_text(
        json.dumps(v4, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Validate schema first
    print("Validating spec v4 schema...")
    spec_obj = Spec.model_validate(v4)
    print(
        f"  A4+F3 schema: PASS (FRs={len(spec_obj.functional_requirements)}, "
        f"SCs={len(spec_obj.success_criteria)}, NCs={len(spec_obj.needs_clarification)})"
    )

    # Render markdown via the canonical bridge
    md = spec_to_markdown(spec_obj)
    (SPECS / "spec_v4.md").write_text(md, encoding="utf-8")

    # Run validators
    print("Running validators...")
    cit = verify_spec_citations(MEALIE, spec_obj)
    print(f"  A5 citation: {len(cit)} problems")
    for problem in cit:
        print(
            f"    - {problem.fr_id} ref#{problem.ref_index} {problem.path}: "
            f"{problem.problem} - {problem.detail}"
        )

    gaps = find_trace_gaps(spec_obj)
    print(f"  B3 trace: {len(gaps)} gaps")
    for g in gaps:
        print(f"    - {g}")

    try:
        assert_spec_roundtrip_consistent(spec_obj)
        print("  B1 roundtrip: PASS")
    except ValueError as e:
        print(f"  B1 roundtrip: FAIL — {e}")

    if cit or gaps:
        print("\nVALIDATORS REPORTED PROBLEMS — see above for details")
        sys.exit(1)
    print("\nAll 4 validators clean.")


if __name__ == "__main__":
    main()
