"""Build spec_v5 from spec_v3 (NOT v4 — v4 regressed per A1 protocol).

ITER 5 strategy (Regression-Aware Rewriter):

- v4 tried to design an outbox + no-commit refactor in FR text and introduced
  NEW critical/high issues (NEW-ARCH-C-1/2 in v4, C4-001/2, EXEC-C-001/2/H-001/2/3).
  Lesson: the transactional architecture choice CANNOT be designed inside FR text
  without exhaustive codebase knowledge — it must be escalated.

- v5 reverts to v3 and addresses v3 issues by:
  (a) Escalating the transactional architecture decision to NC-004 (blocking)
      instead of trying to "design" the outbox in spec FR text.
  (b) Neutralizing FR-011 / FR-012 / FR-020 prose about transactions to defer
      to NC-004 — explicitly stating that the writer cannot resolve this without
      user input on the durability tradeoff.
  (c) Cleanly fixing the resolvable v3 issues: US-9 ↔ 204 contract,
      message_key field on EventMealPlanAutoSyncedData (logs+payload only on
      SUCCESS path; no-op paths are LOGS-ONLY — avoiding v4's contradiction),
      locale OOS sentence, Postgres isolation level wording, FR-014/23
      filter citations, reciprocal SC↔FR links.

This is the FINAL rewrite attempt per A2 stagnation rule. Honest goal: validators
all 0, no NEW critical/high vs v3, escalate what can't be cleanly resolved.
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


def apply_v5_changes(spec: dict) -> dict:
    spec = copy.deepcopy(spec)
    spec["metadata"]["iterations"] = 5

    # ------------------------------------------------------------------
    # 1. UPDATE SUMMARY: explicitly note that transactional architecture
    #    is escalated to NC-004 and not designed in this spec.
    # ------------------------------------------------------------------
    spec["summary"] = (
        "Add a per-household preference that, when enabled, automatically pushes the recipes scheduled in today's meal plan into a configured target shopping list. "
        "Per-household state lives on `HouseholdPreferencesModel` (four client-writable columns plus a server-owned `last_auto_synced_at` idempotency marker) and on a new `household_pantry_staples(household_id, food_id)` association table with `ondelete='CASCADE'` on both FKs, parallel to (but deliberately deviating from) `households_to_ingredient_foods` which omits CASCADE. "
        "The scheduler is registered via `SchedulerRegistry.register_minutely` (the existing 5-minute bucket) and each tick computes a household-local `scheduled_local_instant = today_in_household_tz at auto_sync_run_time`, gating execution to runs whose `household_local_now()` falls inside `[scheduled_local_instant, scheduled_local_instant + 30 minutes)`. "
        "Idempotency is enforced by a single conditional UPDATE on `last_auto_synced_at` issued BEFORE any shopping-list mutation: if the UPDATE affects 0 rows the worker returns without writing items or dispatching an event; if it affects 1 row the worker proceeds to `bulk_create_items` + recipe-reference update + event dispatch. "
        "**IMPORTANT — open blocking decision NC-004**: the *exact* DB-transaction / event-dispatch durability contract (single rollbackable transaction vs. accept partial-failure tolerance vs. add a transactional outbox) is escalated to NC-004 because the v3 spec promised a single rollbackable transaction across CAS + items + recipe-refs + event dispatch, but the existing `RepositoryGeneric.create_many` / `update_many` / `update` methods commit internally (`mealie/repos/repository_generic.py:195-244`) and `EventBusService.dispatch` publishes immediately to external sinks (`mealie/services/event_bus_service/event_bus_service.py:66-96`). Resolving this requires either (a) a code refactor outside the auto-sync feature (no-commit kwarg + transactional outbox table), or (b) an explicit relaxation of the durability claim. The writer cannot pick between these without architectural sign-off — see NC-004 for the two paths and the per-path FR-011/FR-012/FR-020/FR-021 edits each requires. The remainder of this spec uses NEUTRAL transaction wording ('within the auto-sync side-effect boundary') that holds under either NC-004 outcome. "
        "Pantry filtering is unconditional and operates on the fully-flattened ingredient list (including sub-recipes via the recursive expansion at `shopping_lists.py:343-355`), with the per-household predicate sourced from the new association table. "
        "The canonical merge seam is `ShoppingListService.bulk_create_items` (`shopping_lists.py:154-220`), which already accumulates quantity into existing unchecked `(food_id, unit_id)` rows via `can_merge`+`merge_items`. "
        "A new `EventTypes.mealplan_auto_synced_to_shopping` event carries `EventMealPlanAutoSyncedData(operation, household_id, shopping_list_id, added_item_count, skipped_pantry_count, message_key)` where `message_key` is an optional `str | None = None` that is None on the SUCCESS dispatch path (the only path that emits an event); no-op / precondition-failure paths (no meal plan, no target list, already synced) do NOT emit events and surface their i18n key only in server-side logs (clarified per v4 lessons — see Out of Scope and US-9). "
        "The subscriber column `mealplan_auto_synced_to_shopping` is added to `group_events_notifier_options` (real table name; v2 wrongly said `group_event_notifier_options`) AND to `GroupEventNotifierOptionsModel` ORM AND to `GroupEventNotifierOptions` Pydantic schema so `AppriseEventListener.get_subscribers` can resolve the per-event flag. "
        "New routes: `PATCH /api/households/preferences` (partial update via `HouseholdPreferencesPartialUpdate` with `model_config = ConfigDict(extra='forbid')` so unknown fields like `last_auto_synced_at` are rejected with 422) and `POST /api/households/preferences/auto-sync-shopping/run-now` (household-admin only, `force=True` replaces the CAS with an unconditional UPDATE, HTTP 200 with EXACTLY `{added_count, skipped_pantry_count, target_list_id, run_at}` on success, HTTP 204 No Content on no-meal-plan / no-target-list precondition failure). "
        "The PATCH handler applies the diff via a column-set UPDATE that targets only `diff` keys so the server-owned marker is structurally protected from full-model writeback. "
        "Three i18n keys are added to the en-US namespace `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today` in `mealie/lang/messages/en-US.json` (only en-US is editable per `.github/copilot-instructions.md`; the other 40+ Crowdin-managed locales MUST NOT be modified). "
        "The migration also creates a FK constraint `fk_household_preferences_auto_sync_target` from `auto_sync_target_shopping_list_id` to `shopping_lists.id` with `ondelete='SET NULL'` so hard-deleting a list clears the field."
    )

    # ------------------------------------------------------------------
    # 2. ADD NC-004: escalate transactional architecture decision
    #    (instead of v4's mistake of designing outbox in FR prose)
    # ------------------------------------------------------------------
    spec["needs_clarification"].append({
        "id": "NC-004",
        "title": "Transactional / event-dispatch durability contract for the auto-sync pipeline",
        "conflict": (
            "v3 promised that CAS marker write, shopping-list item writes, recipe-reference update, AND event dispatch would all live inside ONE rollbackable DB transaction (FR-011 step 3, FR-012 rollback clause, FR-021 'exactly once per CAS winner'). "
            "Four v3 reviewers (NEW-ARCH-C-1, NEW-ARCH-H-1, EXEC-C-001, EXEC-C-002, C3-001, COMP-H-013) independently flagged that this is impossible to implement against the existing codebase as-is: "
            "(a) `RepositoryGeneric.create_many` / `update_many` / `update` call `self.session.commit()` internally (`mealie/repos/repository_generic.py:195-208`, `:210-226`, `:228-244`); "
            "(b) `ShoppingListService.bulk_create_items` and `add_recipe_ingredients_to_list` delegate to those committing repo methods (`mealie/services/household_services/shopping_lists.py:215-216`, `:433`, `:454`); "
            "(c) `EventBusService.dispatch` publishes immediately to external sinks (Apprise / webhooks) at `mealie/services/event_bus_service/event_bus_service.py:66-96` — it is NOT transactionally coupled to the DB. "
            "Therefore the v3 'after-commit dispatch can still roll back the CAS' wording was structurally impossible, and an `after_commit` hook cannot undo an already-committed transaction. "
            "v4 (the previous rewrite attempt) tried to design a no-commit-kwarg refactor + transactional outbox table inline in FR-011/FR-020/FR-021/FR-024/FR-030/FR-031, but that introduced 2 NEW critical issues (NEW-ARCH-C-1: `create_many(commit=False)` plus the existing refresh loop is broken; NEW-ARCH-C-2: `with session.begin()` after preconditioning reads conflicts with SQLAlchemy 2.0 autobegin) and 3 NEW high issues (idempotency key not preserved across retries; no-op message_key promised to subscribers but never enqueued; exactly-once dispatch claim violated by multi-replica dispatcher race). "
            "v4 was therefore reverted. The choice between the three paths below is a non-trivial architectural decision that touches code OUTSIDE the auto-sync feature scope (the generic repo seam, the event-bus service contract, the alembic baseline) AND has different operational/observability tradeoffs (dispatch latency, dead-letter visibility, subscriber idempotency requirements). It needs human/PM sign-off before the auto-sync FRs can commit to one path."
        ),
        "recommended_default": (
            "PATH A — Add a transactional outbox with a no-commit refactor of the existing repo seams. "
            "Concretely: (1) Add `commit: bool = True` keyword parameter to `RepositoryGeneric.create_many` / `update_many` / `update` AND `ShoppingListService.bulk_create_items` / `add_recipe_ingredients_to_list`; when `False` the methods stage writes via `session.add_all` / direct UPDATE and skip the internal `self.session.commit()` — `create_many(commit=False)` MUST also call `session.flush()` BEFORE the existing `session.refresh(...)` loop so refresh works on a flushed-but-uncommitted row. Existing callers keep `commit=True` default; auto-sync is the only `commit=False` caller. "
            "(2) Add an `event_outbox(id GUID PK, group_id GUID, household_id GUID NULL, event_type str, payload_json text, created_at ts, dispatched_at ts NULL, attempts int=0, last_error text NULL, event_id GUID)` table — note `event_id` is persisted on the row so retries reuse the SAME `Event.event_id` (this is the v4 lesson — without a persisted stable id, subscribers cannot dedupe). "
            "(3) The auto-sync task issues all reads INSIDE the outer transaction, then runs the CAS UPDATE + `bulk_create_items(commit=False)` + `add_recipe_ingredients_to_list(commit=False)` + `session.add(EventOutboxModel(..., event_id=uuid.uuid4()))` inside one `with session.begin():` block (started BEFORE any read on the same session to avoid SQLAlchemy 2.0 autobegin conflict). "
            "(4) A separate minutely scheduler task `dispatch_event_outbox()` polls undispatched rows USING a `SELECT ... FOR UPDATE SKIP LOCKED` claim on PostgreSQL (and a conditional UPDATE-with-WHERE on SQLite where `FOR UPDATE` is not supported) so two replicas cannot dispatch the same row, calls `EventBusService.dispatch(..., event_id_override=row.event_id, message=payload.message_key or '')`, marks `dispatched_at` on success, increments `attempts` on failure (MAX_ATTEMPTS=5 dead-letter). `EventBusService.dispatch` MUST be extended with an optional `event_id_override` parameter that, when set, replaces the `uuid.uuid4()` default at `event_types.py:204-207`, so retries deliver the SAME `Event.event_id`. "
            "Pros: atomic CAS+items+outbox commit; exactly-one dispatch per CAS winner under normal operation; durable retry on dispatch failure; full rollback on any pipeline exception. "
            "Cons: requires `event_id_override` parameter on `EventBusService.dispatch` (extends a shared service contract); requires `commit=False` + `session.flush()` discipline on 5 repo seams; requires `FOR UPDATE SKIP LOCKED` on Postgres (SQLite uses BEGIN IMMEDIATE; need test coverage on both); worst-case dispatch latency = 1 dispatcher tick = 5 minutes."
        ),
        "if_rejected": (
            "PATH B — Accept partial-failure tolerance (no outbox, no no-commit refactor). "
            "Concretely: (1) The auto-sync task issues the CAS UPDATE in its OWN short transaction that commits immediately on rowcount=1. "
            "(2) On CAS success, it calls `add_recipe_ingredients_to_list` (which commits internally via the existing seams — no signature change). "
            "(3) On success, it calls `EventBusService.dispatch(...)` outside any transaction. "
            "Accept: a failure between (2) and (3) leaves the marker set with no event dispatched; a failure mid-(2) leaves the marker set with partial item writes. "
            "Mitigation: add a `sync_attempt_id UUID` column on `shopping_list_items` so the next-tick retry can detect and skip its own already-written rows; add a new success criterion requiring the auto-sync task to retry-on-partial-failure within MAX_ATTEMPTS=3 and log dead-letter on exhaustion. "
            "Document explicitly that 'exactly once per CAS winner' becomes 'at least once per CAS winner under normal operation, with possible partial-failure gaps under crash recovery' and subscribers MUST be idempotent. "
            "Pros: no shared-service changes; no codebase-wide refactor; simpler test surface. "
            "Cons: weaker durability guarantee; subscribers can miss events on crash between commit and dispatch; partial item writes possible on crash mid-bulk-insert (mitigated by sync_attempt_id but not eliminated). "
            "PATH C — Same as PATH B but ALSO drop the 'all in one transaction' wording entirely and accept best-effort dispatch with no retry mechanism. This is the simplest path but provides no recovery on transient subscriber failures. Reviewer can pick A, B, or C; the writer recommends A."
        ),
        "related_requirements": ["FR-011", "FR-012", "FR-020", "FR-021"],
    })

    # ------------------------------------------------------------------
    # 3. REWRITE FR-011 — neutral transaction wording deferring to NC-004
    # ------------------------------------------------------------------
    fr011 = get_fr(spec, "FR-011")
    fr011["text"] = (
        "Critical ordering — CAS BEFORE side effects. The auto-sync side-effect boundary contains four operations that MUST happen in this order per invocation: "
        "(1) resolve preconditions FIRST — target list lookup via household-scoped `self.repos.group_shopping_lists.get_one(target_id)` (returns None if the id does not belong to this household, per FR-014), today's meal plan via `repos.meals.get_today(tz=tz)` (FR-010); "
        "(2) IF target lookup returns None OR meal plan is empty: log the i18n warning (`auto-sync.no-target-list` or `auto-sync.no-meal-plan-today` per FR-022), DO NOT bump `last_auto_synced_at`, do NOT dispatch an event, return; "
        "(3) issue the conditional CAS UPDATE specified in FR-012 — `cas_rows = session.execute(update(HouseholdPreferencesModel).where(...).values(last_auto_synced_at=now_naive_utc)).rowcount`; "
        "(4) if `cas_rows == 0` (another replica won this day's race, OR a non-concurrent second invocation on the same day), return WITHOUT calling `bulk_create_items`, WITHOUT updating `recipe_references`, and WITHOUT dispatching an event; "
        "(5) if `cas_rows == 1` (CAS winner), build the `ShoppingListAddRecipeParamsBulk` items (FR-015) and call `ShoppingListService.add_recipe_ingredients_to_list` (`mealie/services/household_services/shopping_lists.py:413-455`) which internally delegates to `bulk_create_items` (`mealie/services/household_services/shopping_lists.py:154-220`) and updates the list-level `recipe_references`; "
        "(6) dispatch the event (FR-021) via `EventBusService.dispatch(...)` per the pattern at `mealie/services/event_bus_service/event_bus_service.py:66-96`. "
        "The manual run-now path (FR-020) calls this same pipeline with `force=True`, which replaces step 3's conditional WHERE with an unconditional UPDATE that ALWAYS affects 1 row (so the force path always proceeds to step 5). "
        "**Durability / rollback contract deferred to NC-004**: the v3 wording that 'all four operations live in one rollbackable DB transaction' is structurally impossible against the existing codebase (`RepositoryGeneric.create_many` / `update_many` / `update` commit internally at `mealie/repos/repository_generic.py:195-244`; `EventBusService.dispatch` publishes immediately to external sinks at `mealie/services/event_bus_service/event_bus_service.py:66-96`). "
        "The exact rollback semantics — whether step 5 partial failure rolls back step 3, whether step 6 dispatch failure rolls back step 5, whether retry-on-failure is exactly-once or at-least-once — depend on which of NC-004's three paths is chosen and require either a code refactor (PATH A: no-commit kwarg + outbox) or an explicit relaxation (PATH B/C: partial-failure tolerance). "
        "Until NC-004 is resolved, this FR specifies ONLY the ORDERING of the four operations and the CAS-loser short-circuit (steps 1-4); the per-step rollback / retry contract for steps 5-6 is determined by NC-004's resolution. The test matrix in FR-026 covers steps 1-4 unconditionally; tests for the durability/rollback behavior of steps 5-6 are gated on NC-004."
    )
    fr011["related_success_criteria"] = ["SC-007", "SC-017", "SC-025"]
    # Add NC-004 dependency annotation via a note in needs_clarification linkage
    if "needs_clarification" not in fr011 or not isinstance(fr011.get("needs_clarification"), list):
        pass  # FR schema may not have this field, but NC-004 lists this FR in related_requirements

    # ------------------------------------------------------------------
    # 4. REWRITE FR-012 — neutral wording + fix Postgres isolation level
    # ------------------------------------------------------------------
    fr012 = get_fr(spec, "FR-012")
    fr012["text"] = (
        "Idempotency under multi-replica deployment uses a conditional UPDATE issued BEFORE any shopping-list mutation: "
        "`UPDATE household_preferences SET last_auto_synced_at = :now_naive_utc WHERE id = :pref_id AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local_midnight_utc)`. "
        "`:today_local_midnight_utc` is computed as `datetime.combine(household_local_now.date(), time.min, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)` so the comparison runs against a naive-UTC datetime matching the `NaiveDateTime` column type (`mealie/db/models/_model_base.py:18-23`). "
        "If the UPDATE affects 0 rows, the household was already synced today (by another replica earlier in the same tick, or by a previous scheduler tick) — FR-011 step 4 catches `rowcount == 0` and SHORT-CIRCUITS: the worker returns without calling `bulk_create_items` and without dispatching an event. "
        "Because the CAS happens BEFORE side effects, a CAS loser performs zero writes — `merge_items` (`mealie/services/household_services/shopping_lists.py:73-128`) would sum quantities if called twice (sums into `to_item.quantity` at L96), so it is critical that the loser never reaches the merge code path. "
        "The force-mode (FR-020) replaces the WHERE clause with `WHERE id = :pref_id` (unconditional) so the CAS always affects 1 row and the force path always proceeds to side effects. "
        "**Rollback semantics deferred to NC-004**: whether a failure during the FR-011 step 5 `bulk_create_items` call or the FR-011 step 6 event dispatch rolls back the CAS UPDATE is governed by NC-004's chosen path. Under PATH A (outbox + no-commit refactor) the entire side-effect boundary rolls back atomically on any exception. Under PATH B/C (partial-failure tolerance) the CAS commits immediately on rowcount=1 and subsequent failures leave the marker set; recovery is via the optional `sync_attempt_id` idempotency mechanism described in NC-004. "
        "The v3 wording 'rollback reverts the CAS UPDATE as well' is REMOVED here pending NC-004 because it is impossible to implement under PATH B/C and requires a non-trivial code refactor under PATH A."
    )

    # ------------------------------------------------------------------
    # 5. REWRITE FR-020 — neutral on transactions, keep 204 contract
    # ------------------------------------------------------------------
    fr020 = get_fr(spec, "FR-020")
    fr020["text"] = (
        "Add the route `POST /api/households/preferences/auto-sync-shopping/run-now` on `HouseholdSelfServiceController` (`mealie/routes/households/controller_household_self_service.py:20-62`). "
        "Guard: `self.checks.can_manage_household()` (`mealie/routes/_base/checks.py:23-26`). "
        "Behavior: invokes the per-household auto-sync pipeline (FR-009 through FR-021) with `force=True`. "
        "`force=True` bypasses both the FR-009 30-minute window gate AND the FR-012 conditional CAS — the WHERE clause of the UPDATE becomes unconditional (`WHERE id = :pref_id`) so the CAS always affects 1 row and the marker `last_auto_synced_at` is ALWAYS written on success. "
        "The side-effect ordering is otherwise identical to FR-011. "
        "Response: HTTP 200 on success with body matching EXACTLY the four-key shape `{'added_count': int, 'skipped_pantry_count': int, 'target_list_id': UUID4 | null, 'run_at': datetime}` (ISO 8601 UTC). "
        "When preconditions fail (today's meal plan is empty OR no target list resolvable), respond HTTP 204 No Content with NO body — matching the input requirement `204 / 0 added`. "
        "The i18n keys from FR-022 are NOT surfaced in the response body and are NOT carried in any dispatched event for these no-op paths; they appear ONLY in server-side logs (see FR-022). "
        "In the absence of any HTTP body, the client treats 204 as 'nothing to do' and reads the i18n key from server-side logs. "
        "Permission failure returns HTTP 403 via the guard. "
        "**Rollback semantics deferred to NC-004**: whether a mid-pipeline exception in force-mode rolls back the unconditional UPDATE is governed by NC-004's chosen path (see FR-012 last paragraph)."
    )
    fr020["related_success_criteria"] = ["SC-012", "SC-023", "SC-026"]

    # ------------------------------------------------------------------
    # 6. REWRITE FR-021 — add message_key field; SUCCESS-only event
    # ------------------------------------------------------------------
    fr021 = get_fr(spec, "FR-021")
    fr021["text"] = (
        "Add a new event type `EventTypes.mealplan_auto_synced_to_shopping` to the `EventTypes(Enum)` in `mealie/services/event_bus_service/event_types.py:13-60` "
        "(the comment in that enum confirms that adding a member requires an alembic migration to the subscriber table — covered by FR-024 + ORM/schema additions in FR-028). "
        "Add a new payload class `EventMealPlanAutoSyncedData(EventDocumentDataBase)` in the same file with fields "
        "`document_type: EventDocumentType = EventDocumentType.shopping_list, household_id: UUID4, shopping_list_id: UUID4, added_item_count: int, skipped_pantry_count: int, message_key: str | None = None`. "
        "The `message_key` field is present on the schema for forward compatibility (in case future warning-event variants are introduced), but in v1 it is **always None on every dispatched event** because the only path that dispatches the event is the SUCCESS path (FR-011 step 6, reached only when FR-012 CAS UPDATE affects 1 row). "
        "The no-op / precondition-failure paths (no meal plan, no target list, already synced / CAS loser) do NOT dispatch this event — they log the i18n key per FR-022 and return. This avoids the v4 contradiction where the no-op message_key was promised to subscribers but never actually enqueued. "
        "The payload reuses the existing `EventDocumentDataBase` (`mealie/services/event_bus_service/event_types.py:88-91`) which provides `operation: EventOperation`. "
        "The auto-sync task dispatches via `EventBusService.dispatch(integration_id=DEFAULT_INTEGRATION_ID, group_id=..., household_id=..., event_type=EventTypes.mealplan_auto_synced_to_shopping, document_data=EventMealPlanAutoSyncedData(operation=EventOperation.update, household_id=..., shopping_list_id=..., added_item_count=..., skipped_pantry_count=..., message_key=None))` per the dispatch pattern at `mealie/services/event_bus_service/event_bus_service.py:66-96`. "
        "Exactly one dispatch per CAS winner under normal operation — the dispatch sits inside step 6 of FR-011, which is reached only when the FR-012 CAS UPDATE affected 1 row. CAS losers short-circuit at step 4 of FR-011 and never reach the dispatch. "
        "**Retry / exactly-once semantics deferred to NC-004**: whether dispatch failures roll back the CAS, whether retries deliver the SAME `Event.event_id` (stable idempotency key) or a fresh one per retry, and whether subscribers can ever see duplicate deliveries depend on NC-004's chosen path. Under PATH A (outbox) subscribers MUST deduplicate on a persisted event_id; under PATH B/C subscribers SHOULD be idempotent because partial-failure recovery is best-effort."
    )
    fr021["related_success_criteria"] = ["SC-013", "SC-025", "SC-027"]

    # ------------------------------------------------------------------
    # 7. REWRITE FR-022 — clarify localization surfaces: logs-only for no-op
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
        "These keys surface ONLY in server-side logs (logger.info / logger.warning calls in the auto-sync pipeline). "
        "They are NOT included in the HTTP response body of the run-now route (per FR-020 the run-now route returns HTTP 204 with no body on precondition failure). "
        "They are NOT carried as a dispatched event payload for no-op paths — per FR-021 the auto-sync event is dispatched ONLY on the SUCCESS path with `message_key=None`. "
        "The `message_key` field on `EventMealPlanAutoSyncedData` exists for forward compatibility (future warning-event variants) but is always None in v1. "
        "Mealie ships 40+ locale files at `mealie/lang/messages/*.json` (en-US, en-GB, fr-FR, zh-CN, af-ZA, ar-SA, etc.); per `.github/copilot-instructions.md` 'Translations' section ONLY `en-US.json` is editable by repository contributors — every other locale is Crowdin-managed and MUST NOT be edited (PRs touching them are rejected). So only `en-US.json` changes for this feature."
    )
    fr022["related_success_criteria"] = ["SC-019", "SC-026"]

    # ------------------------------------------------------------------
    # 8. UPDATE FR-014 — add filter implementation citations
    # ------------------------------------------------------------------
    fr014 = get_fr(spec, "FR-014")
    fr014["text"] = (
        "Target shopping list ownership is enforced at TWO checkpoints: "
        "(A) PATCH-time in FR-006 uses `self.repos.group_shopping_lists.get_one(target_id)` against the household-scoped repo (`mealie/repos/repository_factory.py:317-321`); "
        "the generic `get_one` implementation at `mealie/repos/repository_generic.py:156-179` calls `_filter_builder` (`:94-102`) which automatically prepends "
        "`group_id` and `household_id` to the WHERE clause via SQLAlchemy `filter_by(**fltr)` (`:170-172`); "
        "a None return raises HTTP 422 with detail `'auto_sync_target_shopping_list_id does not refer to a shopping list owned by this household'`. "
        "(B) Sync-time in FR-011 re-runs the same `get_one(target_id)` against the household-scoped repo at task execution time so a list that was deleted or transferred after PATCH cannot leak into another household's sync. "
        "Cross-household writes are structurally impossible because `RepositoryShoppingList` carries the `household_id` and `_filter_builder` applies it as a `filter_by` clause on every query (`repository_generic.py:94-102`, `:156-179`, `:315-355`). "
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
    # 9. UPDATE FR-023 — add filter implementation citations + reciprocal SC-029
    # ------------------------------------------------------------------
    fr023 = get_fr(spec, "FR-023")
    fr023["text"] = (
        "All auto-sync queries MUST use household-scoped repos. `repos.meals` (`mealie/repos/repository_factory.py:297-301`) carries `household_id` and applies it as a WHERE clause in `get_today` (`mealie/repos/repository_meals.py:11-21`). "
        "`repos.household_preferences` (`mealie/repos/repository_factory.py:244-253`) is also household-scoped. "
        "`repos.group_shopping_lists` (`mealie/repos/repository_factory.py:317-321`) is household-scoped via `household_id=self.household_id`. "
        "The generic implementation of household scoping lives in `_filter_builder` at `mealie/repos/repository_generic.py:94-102`, which prepends `group_id` and `household_id` to every `_query_one` / `get_one` / `page_all` WHERE clause (`:156-179`, `:315-355`). "
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
    # 10. UPDATE FR-001 — reciprocal SC-028 link
    # ------------------------------------------------------------------
    fr001 = get_fr(spec, "FR-001")
    if "SC-028" not in fr001["related_success_criteria"]:
        fr001["related_success_criteria"] = list(fr001["related_success_criteria"]) + ["SC-028"]

    # ------------------------------------------------------------------
    # 11. REWRITE US-9 — align with 204/no-body contract; logs-only for no-op
    # ------------------------------------------------------------------
    us9 = get_us(spec, "US-9")
    us9["description"] = (
        "As an operator monitoring server logs, I want the auto-sync pipeline to surface localized i18n keys "
        "in server-side logs for every no-op / precondition-failure path (no meal plan, no target list, already synced), "
        "so the system message format matches every other Mealie endpoint and the message keys match the input specification verbatim. "
        "The HTTP response of the run-now route does NOT carry the i18n key — precondition-failure responses are HTTP 204 with empty body per FR-020 — "
        "so clients distinguish 'work done' (200 + 4-key JSON) from 'nothing to do' (204 empty) by status code alone. "
        "No-op paths do NOT dispatch the `mealplan_auto_synced_to_shopping` event (per FR-021 the event is dispatched ONLY on the SUCCESS path), "
        "so the i18n key is NOT carried in any event payload either — it surfaces exclusively in server logs."
    )
    us9["why_this_priority"] = (
        "Consistency with the repo-wide en-US-only locale convention and input requirement 4 — the keys MUST be exact "
        "(`auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today`) so log-monitoring "
        "tools can match against them programmatically. The HTTP 204 / no-body contract on the run-now precondition-failure "
        "path is locked in by FR-020 / SC-026 (input requirement 5: '204 / 0 added')."
    )
    us9["independent_test"] = (
        "Trigger run-now (POST /api/households/preferences/auto-sync-shopping/run-now) on a household with no active meal plan; "
        "assert the HTTP response is exactly status 204 with Content-Length 0 AND a server-side WARN-level log line is emitted "
        "whose i18n key field equals `auto-sync.no-meal-plan-today`. The response body MUST be zero bytes (no JSON `detail`, "
        "no localized string). Assert NO `EventBusService.dispatch` call is made for this household in this run."
    )
    us9["acceptance"] = [
        {
            "given": "a household with no meal plan for today",
            "when": "run-now is invoked (POST /api/households/preferences/auto-sync-shopping/run-now) by a can_manage_household=true user",
            "then": "the HTTP response is status 204 with Content-Length 0 AND zero response body bytes AND a server-side WARN-level log entry is emitted with i18n key field equal to `auto-sync.no-meal-plan-today` AND zero `EventBusService.dispatch` calls are made for this household",
        },
        {
            "given": "a household whose auto_sync_target_shopping_list_id has been set to a deleted list",
            "when": "the scheduled auto-sync task runs for that household",
            "then": "the server-side WARN-level log entry uses i18n key `auto-sync.no-target-list` AND `last_auto_synced_at` is NOT bumped AND zero `EventBusService.dispatch` calls are made for this household",
        },
        {
            "given": "a household that has already been auto-synced today",
            "when": "the scheduled auto-sync task fires again on the same household-local day (CAS loser path)",
            "then": "no event is dispatched (CAS loser short-circuits before FR-011 step 6), so subscribers receive zero additional events for this household-day; the only dispatched event for this household-day was the original CAS-winner event whose `EventMealPlanAutoSyncedData.message_key` field was None on the success path",
        },
    ]

    # ------------------------------------------------------------------
    # 12. UPDATE Edge cases:
    #     - Fix Postgres isolation-level wording (READ COMMITTED, not REPEATABLE READ)
    #     - Update no-meal-plan run-now edge case to clarify no event
    # ------------------------------------------------------------------
    for ec in spec["edge_cases"]:
        if "Two replicas tick" in ec["description"]:
            ec["handling"] = (
                "Each replica races to issue the FR-012 conditional UPDATE on the same row. The DB serializes the conflicting UPDATEs "
                "at the row level (PostgreSQL default isolation level is READ COMMITTED, which still serializes concurrent UPDATEs on the same row via "
                "row-level write locks; SQLite serializes via its per-statement lock). "
                "The second-arriving UPDATE sees the marker already advanced and affects 0 rows. FR-011 step 4 catches `rowcount == 0` and returns "
                "without calling `bulk_create_items` or `EventBusService.dispatch`. "
                "Result: exactly one replica (the CAS winner) writes items and dispatches the event; the CAS loser is a structural no-op. "
                "Whether subscribers can ever see a duplicate dispatch under retry / crash conditions is governed by NC-004's chosen path "
                "(PATH A: subscribers MUST deduplicate using a persisted stable event_id; PATH B/C: subscribers SHOULD be idempotent because "
                "best-effort retry can re-deliver). Under normal (non-failure) operation, exactly one dispatch per CAS winner is guaranteed."
            )
        elif "Force-mode run-now mid-transaction exception" in ec["description"]:
            ec["handling"] = (
                "FR-020 force=True replaces the CAS WHERE clause with an unconditional UPDATE. The exact rollback semantics on mid-pipeline "
                "exception are governed by NC-004's chosen path. Under PATH A (outbox + no-commit refactor) the unconditional UPDATE, partial item "
                "writes, and outbox row all roll back atomically and the route returns HTTP 500. Under PATH B/C (partial-failure tolerance) the "
                "unconditional UPDATE commits immediately on rowcount=1 and subsequent failures leave the marker set; the route returns HTTP 500 "
                "and the operator must invoke run-now again to retry. In both cases the caller can safely retry the run-now invocation."
            )
        elif "No-meal-plan / no-target-list precondition fails on run-now" in ec["description"]:
            ec["handling"] = (
                "FR-020 returns HTTP 204 No Content with an empty body — matching input requirement 5 'when no meal plan today returns 204 / 0 added'. "
                "No `detail` field, no i18n key in the response. No event is dispatched (per FR-021 the auto-sync event is dispatched ONLY on the "
                "SUCCESS path). The i18n key surfaces only in server-side logs. Frontend / client integrations distinguish 200 (work done) from 204 "
                "(no work) by status code alone."
            )

    # ------------------------------------------------------------------
    # 13. UPDATE Out of scope — fix the stale locale sentence
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
    # 14. UPDATE Self-concerns:
    #     - Add a new self-concern for NC-004 (transactional architecture)
    #     - Keep FR-021 self-concern as-is (about migration + ORM + schema)
    # ------------------------------------------------------------------
    spec["self_concerns"].append({
        "location": "FR-011",
        "concern": (
            "FR-011 and FR-012 specify the ORDERING of CAS + side effects + event dispatch but defer the per-step rollback / retry contract to NC-004 "
            "because the v3 'all four operations in one rollbackable DB transaction' wording is structurally impossible against the existing codebase "
            "(`RepositoryGeneric.create_many` / `update_many` / `update` commit internally at `mealie/repos/repository_generic.py:195-244`; `EventBusService.dispatch` "
            "publishes immediately at `mealie/services/event_bus_service/event_bus_service.py:66-96`). v4 attempted to design an outbox + no-commit refactor "
            "inline in FR text but introduced 2 new critical + 3 new high issues (failed refresh after suppressed commit, SQLAlchemy 2.0 autobegin conflict, "
            "unstable retry idempotency key, no-op message_key contradiction, multi-replica dispatcher race). Lesson: the durability contract is non-trivial "
            "and requires architectural sign-off before the FRs can commit to one path."
        ),
        "evidence_gap": (
            "No human / PM has chosen between NC-004's three paths yet. The reviewer must pick one before coding can begin on FR-011 step 5-6 rollback "
            "tests (FR-026 covers steps 1-4 unconditionally). Whichever path is chosen, the auto-sync FRs gain concrete rollback semantics; the SUCCESS path "
            "behavior (FR-011 steps 1-4 + CAS-winner happy path) is unchanged across all three paths."
        ),
        "suggested_resolution": (
            "Escalate NC-004 to a human reviewer. The writer recommends PATH A (transactional outbox + no-commit refactor + persisted stable event_id) "
            "but acknowledges it requires (i) extending the shared `EventBusService.dispatch` signature with an `event_id_override` parameter, "
            "(ii) adding a `commit: bool = True` kwarg to 5 repo seams with disciplined `session.flush()` use, and (iii) adding a `FOR UPDATE SKIP LOCKED` "
            "dispatcher claim on Postgres (with SQLite fallback). PATH B/C is simpler but weakens the durability guarantee. The choice is the reviewer's."
        ),
    })

    # ------------------------------------------------------------------
    # 15. UPDATE Assumptions — note NC-004 dependency
    # ------------------------------------------------------------------
    spec["assumptions"].append(
        "The auto-sync side-effect boundary (FR-011 step 1-6) has a non-trivial transactional / event-dispatch durability decision escalated to NC-004. "
        "The remainder of the spec is written in NEUTRAL transaction language that holds under any of NC-004's three resolution paths. "
        "The SUCCESS-path behavior (FR-011 steps 1-4 + CAS-winner happy path + single SUCCESS event dispatch) is unchanged across all three paths; only "
        "the failure-rollback / retry / exactly-once semantics differ."
    )

    # ------------------------------------------------------------------
    # 16. UPDATE Key Entities — add message_key to EventMealPlanAutoSyncedData
    # ------------------------------------------------------------------
    for ke in spec["key_entities"]:
        if ke["name"] == "EventMealPlanAutoSyncedData":
            ke["description"] = (
                "New EventDocumentDataBase subclass per FR-021 carrying the post-sync payload. No PII (no user names, recipe names, or ingredient details) "
                "— only ids and counts plus an optional `message_key` so future warning-event variants can carry an i18n key. In v1, `message_key` is ALWAYS "
                "None on every dispatched event because the only dispatch path is the SUCCESS path (no-op / precondition-failure paths log the key but do "
                "NOT dispatch the event)."
            )
            ke["fields"] = [
                "document_type: EventDocumentType = EventDocumentType.shopping_list",
                "operation: EventOperation",
                "household_id: UUID4",
                "shopping_list_id: UUID4",
                "added_item_count: int",
                "skipped_pantry_count: int",
                "message_key: str | None = None  # always None in v1; reserved for future warning events",
            ]

    # ------------------------------------------------------------------
    # 17. UPDATE SCs:
    #     - SC-013: keep dispatch-count-per-CAS-winner contract but defer
    #       exactly-once retry semantics to NC-004
    #     - SC-007: zero dispatches on second invocation (CAS loser)
    #     - SC-025: zero dispatches when meal plan is empty
    #     - SC-027: reciprocal FR-021/FR-024/FR-028
    #     - SC-028: reciprocal FR-001/FR-024
    #     - SC-029: reciprocal FR-023/FR-029
    # ------------------------------------------------------------------
    sc013 = get_sc(spec, "SC-013")
    sc013["text"] = (
        "Under normal (non-failure) operation, a successful auto-sync run (CAS winner) results in `EventBusService.dispatch` being invoked exactly ONCE "
        "with `event_type=EventTypes.mealplan_auto_synced_to_shopping` and `document_data` of type `EventMealPlanAutoSyncedData` carrying "
        "`household_id, shopping_list_id, added_item_count, skipped_pantry_count, operation, message_key=None`. "
        "A CAS loser (concurrent replica or same-day re-run) dispatches zero events because FR-011 step 4 short-circuits before step 6. "
        "Whether retries under failure conditions can ever cause duplicate dispatches with the SAME or DIFFERENT `Event.event_id` is governed by NC-004's "
        "chosen path (PATH A: same persisted event_id, subscribers MUST dedupe; PATH B/C: best-effort, subscribers SHOULD be idempotent)."
    )
    sc013["metric"] = "number of EventBusService.dispatch invocations per CAS winner and per CAS loser under normal operation, plus payload field presence on the winner"
    sc013["threshold"] = (
        "exactly 1 dispatch per CAS winner under normal operation (all 6 required payload fields present including message_key=None); "
        "exactly 0 dispatches per CAS loser under normal operation"
    )
    sc013["related_requirements"] = ["FR-021"]

    sc007 = get_sc(spec, "SC-007")
    sc007["text"] = (
        "Running the auto-sync task twice in a row for the same household on the same household-local day results in: "
        "(a) `last_auto_synced_at` written exactly ONCE across both invocations (first invocation's CAS sets it, second invocation's CAS returns 0 rows and short-circuits); "
        "(b) zero new `shopping_list_item` rows on the second invocation; "
        "(c) zero `EventBusService.dispatch` calls on the second invocation (CAS loser short-circuits before FR-011 step 6); "
        "(d) zero calls to `bulk_create_items` on the second invocation."
    )

    sc025 = get_sc(spec, "SC-025")
    sc025["text"] = (
        "When `repos.meals.get_today(...)` returns `[]` for a household, no `EventBusService.dispatch` call is made for that household in that tick. "
        "FR-011 step 2 returns before the CAS UPDATE, so no event is dispatched."
    )
    sc025["related_requirements"] = ["FR-011", "FR-021"]

    sc027 = get_sc(spec, "SC-027")
    sc027["related_requirements"] = ["FR-021", "FR-024", "FR-028"]

    sc028 = get_sc(spec, "SC-028")
    sc028["related_requirements"] = ["FR-001", "FR-024"]

    sc029 = get_sc(spec, "SC-029")
    if "FR-023" not in sc029["related_requirements"]:
        sc029["related_requirements"] = list(sc029["related_requirements"]) + ["FR-023"]
    if "FR-029" not in sc029["related_requirements"]:
        sc029["related_requirements"] = list(sc029["related_requirements"]) + ["FR-029"]

    sc026 = get_sc(spec, "SC-026")
    if "FR-020" not in sc026["related_requirements"]:
        sc026["related_requirements"] = list(sc026["related_requirements"]) + ["FR-020"]
    if "FR-022" not in sc026["related_requirements"]:
        sc026["related_requirements"] = list(sc026["related_requirements"]) + ["FR-022"]

    return spec


def write_json(spec: dict, path: pathlib.Path) -> None:
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")


def write_md(spec_obj: Spec, path: pathlib.Path) -> None:
    md = spec_to_markdown(spec_obj)
    path.write_text(md, encoding="utf-8")


def main() -> None:
    print("Loading v3 baseline (NOT v4 — v4 regressed per A1 protocol)...")
    v3 = load_v3()

    print("Applying v5 changes...")
    v5 = apply_v5_changes(v3)

    v5_json_path = SPECS / "spec_v5.json"
    write_json(v5, v5_json_path)
    print(f"Wrote {v5_json_path}")

    print("Validating spec v5 schema...")
    spec_obj = Spec.model_validate(v5)
    print(f"  A4+F3 schema: PASS (FRs={len(spec_obj.functional_requirements)}, SCs={len(spec_obj.success_criteria)}, NCs={len(spec_obj.needs_clarification)})")

    print("Running validators...")
    cit = verify_spec_citations(MEALIE, spec_obj)
    cit_count = len(cit) if isinstance(cit, list) else getattr(cit, "problem_count", 0)
    print(f"  A5 citation: {cit_count} problems")
    if cit_count:
        for p in (cit if isinstance(cit, list) else getattr(cit, "problems", [])):
            print(f"    - {p}")

    trace = find_trace_gaps(spec_obj)
    trace_count = len(trace) if isinstance(trace, list) else getattr(trace, "gap_count", 0)
    print(f"  B3 trace: {trace_count} gaps")
    if trace_count:
        for g in (trace if isinstance(trace, list) else getattr(trace, "gaps", [])):
            print(f"    - {g}")

    v5_md_path = SPECS / "spec_v5.md"
    write_md(spec_obj, v5_md_path)
    print(f"Wrote {v5_md_path}")

    print("Roundtrip check...")
    assert_spec_roundtrip_consistent(spec_obj)
    print("  B1 roundtrip: PASS")

    print("\nAll 4 validators clean." if (cit_count == 0 and trace_count == 0) else "\nSome validators have issues.")


if __name__ == "__main__":
    main()
