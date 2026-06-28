# Executability Review (v4)

## Verdict: NEEDS_REFINE

v4 resolves the v3 post-commit dispatch contradiction by adding a no-commit refactor and an outbox, but it is still not executable as written. The new `commit=False` contract leaves `RepositoryGeneric.create_many`'s refresh loop unchanged, which fails before the outer transaction can commit; the specified `with session.begin()` placement conflicts with SQLAlchemy 2.0 autobegin after the mandated precondition reads; and the no-op/i18n event contract still contradicts the zero-outbox no-op requirements. Do **not** approve: there is at least 1 critical and multiple high findings.

---

## Scope checks

| Check | Result |
|---|---|
| All cited paths real? | ✅ Pass. Parsed `spec_v4.json`: 64 `code_references` paths, 0 missing under `C:\Users\v-liyuanjun\Downloads\mealie`. |
| All cited line ranges in bounds? | ✅ Pass for file bounds. 0 ranges exceeded file length. |
| Strict line ranges substantiate claims? | ⚠️ Fail. Some cited ranges are too short for the claims; see `EXEC-M-001`. |
| v3 critical/high mapped? | ⚠️ Partially. The outbox direction addresses the v3 dispatch issue, but the new no-commit and outbox details introduce fresh executability blockers. |
| Verdict gate (0 critical + 0 high)? | ❌ Fail. |

---

## Executability concerns

### Critical

- **EXEC-C-001 — `create_many(commit=False)` is specified to fail before the outer transaction can commit.** FR-030 requires `RepositoryGeneric.create_many(..., commit=False)` to merely guard the existing `self.session.commit()` while leaving the `session.refresh(...)` loop unchanged (`spec_v4.md` L260; `repository_generic.py` L195-208). In the actual method, objects are only `add_all`'d at L202, committed at L203, and refreshed at L205-206. If L203 is skipped, the new rows are still pending/unflushed when L205 calls `refresh`, which SQLAlchemy cannot do for non-persistent instances. Auto-sync reaches this path through `bulk_create_items(commit=False)` / `add_recipe_ingredients_to_list(commit=False)` (`spec_v4.md` L203, L260), so the CAS+items+outbox transaction will raise on normal item creation. Specify `session.flush()` before refresh, skip refresh on `commit=False`, or otherwise make the no-commit path persistent before refresh.

- **EXEC-C-002 — `with session.begin()` is placed after reads that begin the same SQLAlchemy 2.0 session transaction.** FR-011 says to resolve target list and meal plan preconditions outside the outer transaction and then open `with session.begin():` (`spec_v4.md` L203). FR-009 also enumerates enabled households with `session.execute(...)` before per-household work (`spec_v4.md` L197). Mealie uses SQLAlchemy 2.0.50 (`pyproject.toml` L8-12) with `sessionmaker(autocommit=False, future=True)` (`db_setup.py` L38-40), and the cited repo reads use `session.execute` (`repository_generic.py` L166-174; `repository_meals.py` L11-21). In SQLAlchemy 2.x, those reads autobegin a transaction on the session; entering `session.begin()` afterward on the same session raises that a transaction is already begun. The spec must either put the reads inside the explicit transaction, end/rollback the read transaction before `begin()`, or use a separate fresh session for the write transaction.

### High

- **EXEC-H-001 — No-op i18n event payload is still contradictory.** US-9 says the pipeline surfaces i18n keys in both logs and `EventMealPlanAutoSyncedData.message_key` on dispatched events (`spec_v4.md` L155-162). FR-020 repeats that precondition failures expose keys in logs and in the eventual outbox-dispatched event (`spec_v4.md` L230), and FR-021 says `message_key` is set on no-meal-plan / no-target-list / already-synced paths (`spec_v4.md` L233). But FR-011 step 2 returns before CAS/outbox on no meal or no target (`spec_v4.md` L203), US-9 AC1 requires zero `event_outbox` rows for no meal (`spec_v4.md` L165), SC-025 requires zero outbox rows for empty `get_today` (`spec_v4.md` L317-318), and the no-op edge case says only logs surface the key (`spec_v4.md` L373). An implementer cannot both dispatch a payload carrying `message_key` and insert zero outbox rows. Choose logs-only for no-ops, or insert no-op outbox events and update SC/US accordingly.

- **EXEC-H-002 — Retry idempotency key is specified as `Event.event_id`, but that value is regenerated on every dispatch.** FR-031 says subscribers should treat retries as idempotent for the same `event_outbox.id`, “surfaced via `Event.event_id`” (`spec_v4.md` L263), and Assumption 10 says subscribers should use `Event.event_id` because the dispatcher may re-deliver (`spec_v4.md` L386). The cited `Event` constructor always overwrites `event_id` with a fresh `uuid.uuid4()` at instantiation (`event_types.py` L204-207), and FR-031's dispatcher calls `EventBusService.dispatch`, which constructs a new `Event` for each attempt (`event_bus_service.py` L66-80). Therefore retries of the same outbox row will have different `Event.event_id` values, so subscribers cannot deduplicate as specified. Add `event_outbox_id` to the payload/message, or change `Event` construction to preserve a supplied stable event id.

- **EXEC-H-003 — SC-030's `commit=True` count is incompatible with the existing baseline it claims to preserve.** SC-030 requires exactly 1 `session.commit` when `bulk_create_items` or `add_recipe_ingredients_to_list` is called with `commit=True` or omitted (`spec_v4.md` L327-328), while FR-030 says default `commit=True` preserves existing behavior (`spec_v4.md` L260). Existing `bulk_create_items` can call both `create_many` and `update_many` in one invocation (`shopping_lists.py` L215-216), each of which commits (`repository_generic.py` L203, L243). Existing `add_recipe_ingredients_to_list` calls `bulk_create_items` at L433 and then `shopping_lists.update` at L454, adding another generic commit at `repository_generic.py` L225. The “exactly one commit” acceptance criterion is false for mixed create/update batches and for any recipe-reference update, unless behavior is changed rather than preserved.

### Medium

- **EXEC-M-001 — FR-030 / FR-011 line ranges miss the list-level update they rely on.** FR-030 claims `add_recipe_ingredients_to_list` forwards `commit=commit` into the eventual `shopping_lists.update(...)` call, but its code reference is only `shopping_lists.py` L413-445 (`spec_v4.md` L260-261). The actual update is at L454-455, outside that range. FR-011 has the same short range (`spec_v4.md` L203-204). This fails strict line-range substantiation for the recipe-reference update commit seam.

---

## Verified fixes from v3

- The event dispatch rollback contradiction is directionally fixed by moving external delivery to `event_outbox` (`spec_v4.md` L263-264) instead of calling `EventBusService.dispatch` inside/after the CAS transaction (`event_bus_service.py` L66-96).
- US-9 no longer requires a response body on HTTP 204; the independent test now asserts status 204 and zero body bytes (`spec_v4.md` L161-165), matching SC-026 (`spec_v4.md` L319-320).
- Locale scope and PostgreSQL isolation wording were corrected (`spec_v4.md` L379, L393; L365).

