# Rewrite log: spec_v3 → spec_v4 (ITER 4)

**Generated**: 2026-06-19
**Meta-review input**: `meta_review_v3.{md,json}` (7 actions)
**Verdict (meta)**: REWRITE_REQUIRED
**Goal**: 0 critical + 0 high across all 4 axes

## Counts

| | v3 | v4 | Δ |
|---|---|---|---|
| Functional requirements | 29 | 31 | +2 (FR-030 commit kwarg refactor, FR-031 event_outbox + dispatcher) |
| Success criteria | 29 | 32 | +3 (SC-030 commit-flag suppression, SC-031 dispatcher behavior, SC-032 atomic 3-stage rollback) |
| Needs clarification | 3 | 4 | +1 (NC-004 transactional architecture decision: outbox vs partial-failure tolerance) |
| User stories | 9 | 9 | 0 (US-9 rewritten in place) |
| Edge cases | 11 | 11 | 0 (two-replica + force-mode mid-tx rewritten in place) |
| Assumptions | 9 | 10 | +1 (event_outbox durable record + subscriber idempotency note) |
| Out-of-scope items | 6 | 6 | 0 (stale "only en-US.json" sentence rewritten in place) |
| Self-concerns | 3 | 4 | +1 (FR-031 dispatcher latency + dead-letter visibility) |
| Key Entities | 7 | 8 | +1 (EventOutboxModel) |
| iterations | 3 | 4 | +1 |

## Validators (Step 3)

| Validator | v4 result |
|---|---|
| A4+F3 schema (`Spec.model_validate`) | **PASS** (FRs=31, SCs=32, NCs=4) |
| A5 citation (`verify_spec_citations`) | **0 problems** |
| B3 trace (`find_trace_gaps`) | **0 gaps** |
| B1 roundtrip (`assert_spec_roundtrip_consistent`) | **PASS** |

## Action-by-action change log

### META-V3-001 (CRITICAL) — Outbox pattern + no-commit refactor

**Source v3 findings**: NEW-ARCH-C-1, NEW-ARCH-H-1, EXEC-C-001, EXEC-C-002, C3-001, COMP-H-013 (6 distinct callouts about the impossibility of "single rollbackable transaction" + "after-commit dispatch can roll back the CAS")

**Root cause**: `RepositoryGeneric.create_many` / `update_many` / `update` (`repository_generic.py:195-208`, `:210-226`, `:228-244`) call `self.session.commit()` internally. `ShoppingListService.bulk_create_items` delegates to them. `EventBusService.dispatch` publishes immediately to external sinks. Therefore the v3 promise that all 4 (CAS + items + recipe refs + event) commit-or-rollback atomically is impossible without refactoring those seams or moving event dispatch out-of-band.

**Changes applied**:

- **NC-004 (NEW)**: Escalated as a top-of-spec blocking decision with:
  - `recommended_default` = outbox pattern + no-commit refactor (FR-030 + FR-031)
  - `if_rejected` = partial-failure tolerance with `sync_attempt_id` idempotency on `shopping_list_items` + new SC-033 requiring retry-on-partial-failure (MAX_ATTEMPTS=3) + dead-letter on exhaustion. Documents explicitly that "exactly once per CAS winner" becomes "at least once per CAS winner" under this path.
  - `related_requirements`: FR-011, FR-021, FR-024, FR-030, FR-031.

- **FR-030 (NEW)**: Adds `commit: bool = True` keyword parameter to:
  - `RepositoryGeneric.create_many` (`repository_generic.py:195-208`) — guards `session.commit()` at L203
  - `RepositoryGeneric.update` (`:210-226`) — guards `session.commit()` at L225
  - `RepositoryGeneric.update_many` (`:228-244`) — guards `session.commit()` at L243
  - `ShoppingListService.bulk_create_items` (`shopping_lists.py:154-220`) — forwards `commit=commit` to `list_items.create_many/update_many` at L215-216
  - `ShoppingListService.add_recipe_ingredients_to_list` (`shopping_lists.py:413-445`) — forwards `commit=commit` to `bulk_create_items` (L433) and `shopping_lists.update` (L454)
  
  Default `commit=True` preserves existing behavior for every current caller. Auto-sync is the only caller that uses `commit=False`. Keyword-only by convention — no positional argument breakage.

- **FR-031 (NEW)**: Adds the event_outbox infrastructure:
  - `EventOutboxModel` ORM model + `RepositoryEventOutbox` repo + `event_outbox` migration table (created in FR-024 step D)
  - `dispatch_event_outbox()` minutely scheduler task that polls undispatched rows ORDER BY created_at LIMIT 100, calls `EventBusService.dispatch(...)`, sets `dispatched_at` on success, increments `attempts` + populates `last_error` on failure (MAX_ATTEMPTS=5 dead-letter)
  - Forwards `message=payload.message_key or ''` so subscribers receive the i18n key via `EventBusMessage.body`

- **FR-011 (REWRITTEN)**: New 7-step pipeline using outer `with session.begin():` block:
  1. Resolve preconditions outside outer tx (target list + meal plan)
  2. If empty / no target list → log + return (no CAS, no marker bump)
  3. Open outer `with session.begin():` block
  4. Inside the tx: conditional CAS UPDATE; on rowcount=0 → empty commit + return
  5. On rowcount=1: `add_recipe_ingredients_to_list(commit=False)` (per FR-030)
  6. `session.add(EventOutboxModel(...))` — outbox row INSERT (no commit)
  7. `with` block exits → single atomic commit for marker + items + outbox row
  
  Any exception during 4-6 rolls back ALL three pieces of state. Event publishing is decoupled via FR-031's `dispatch_event_outbox` task.

- **FR-012 (REWRITTEN)**: Clarifies outbox-aware rollback semantics: `bulk_create_items` raising OR outbox INSERT raising both roll back the CAS UPDATE. Event-publishing failures are NOT part of the auto-sync transaction (handled by FR-031 retry).

- **FR-020 (REWRITTEN)**: Force-mode mirrors the outbox pattern — unconditional UPDATE + `bulk_create_items(commit=False)` + outbox INSERT inside the same `with session.begin():` block, so any exception rolls back all three atomically. Run-now precondition-failure 204/no-body contract is unchanged; i18n key surfaces in logs + `EventMealPlanAutoSyncedData.message_key` field.

- **FR-024 (REWRITTEN)**: Step D added — creates `event_outbox` table + indices on `(dispatched_at, created_at)` for the dispatcher poll query. Downgrade step drops the table + indices.

- **SC-007 (REWRITTEN)**: Second invocation asserts zero outbox row inserts (instead of dispatch counts directly).
- **SC-013 (REWRITTEN)**: Asserts exactly 1 outbox row + exactly 1 dispatcher-triggered dispatch per CAS winner under normal operation; up to MAX_ATTEMPTS=5 deliveries per outbox row under retry; subscribers MUST treat dispatch as idempotent.
- **SC-025 (REWRITTEN)**: Asserts zero outbox row inserts for empty-meal-plan household.

- **SC-030 (NEW)**: `create_many(commit=False)` / `update(commit=False)` / `update_many(commit=False)` / `bulk_create_items(commit=False)` / `add_recipe_ingredients_to_list(commit=False)` all suppress the internal `session.commit()` call. With `commit=True` or omitted, exactly one commit is recorded per baseline.

- **SC-031 (NEW)**: After CAS-winner commit, exactly one `event_outbox` row exists with the right metadata + JSON-roundtrippable payload. After one dispatcher tick, `EventBusService.dispatch` is invoked exactly once and `dispatched_at` is set. On dispatch exception, `attempts` increments to 1 and `last_error` is populated.

- **SC-032 (NEW)**: Atomic 3-stage rollback — inject exception (i) before step 5 (CAS only), (ii) during step 5 (CAS + partial items), (iii) during step 6 (CAS + items + partial outbox). All three scenarios MUST satisfy: marker unchanged + zero new shopping_list_items + zero outbox rows.

- **Edge case (two-replica)** rewritten: outbox-aware loser semantics — CAS loser inserts zero outbox rows; subscribers see exactly one event per CAS winner.

- **Edge case (force-mode mid-tx)** rewritten: 3-stage rollback (marker + items + outbox) on any exception inside the outer transaction.

- **Key Entities → EventOutboxModel (NEW)** added with all columns.

- **Self-Concerns[FR-021] (REWRITTEN)**: Now references both the migration column AND the new `event_outbox` table AND the ORM/schema additions; recommends startup check that asserts all three exist.

- **Self-Concerns[FR-031] (NEW)**: Documents the worst-case 5-minute dispatch latency + dead-letter visibility tradeoffs; recommends operational metrics for `event_outbox_undispatched_count` / `event_outbox_dead_letter_count` / `event_outbox_dispatch_latency_seconds`.

- **Assumptions[+1]**: `event_outbox` is the durable record; subscribers SHOULD be idempotent on `Event.event_id`.

### META-V3-002 (HIGH) — US-9 vs 204 contract

**Source v3 findings**: COMP-H-013, C3-002, EXEC-H-001 (3 callouts that US-9 demands a response body on a 204/no-body path)

**Changes applied**:
- **US-9 description (REWRITTEN)**: "As an operator monitoring server logs and downstream event-bus subscribers, I want the auto-sync pipeline to surface localized i18n keys in BOTH server-side logs AND the `EventMealPlanAutoSyncedData.message_key` field … The HTTP response of the run-now route does NOT carry the i18n key — precondition-failure responses are HTTP 204 with empty body per FR-020." Removes the "API response or webhook payload" wording that contradicted SC-026.
- **US-9 `why_this_priority` (REWRITTEN)**: Explicit reference to FR-020 / SC-026 locking the 204/no-body contract.
- **US-9 `independent_test` (REWRITTEN)**: Now asserts status 204 + Content-Length 0 + WARN-level log line with `auto-sync.no-meal-plan-today` key. No response-body assertion.
- **US-9 AC1 (REWRITTEN)**: 204 + zero body bytes + WARN log + zero outbox rows.
- **US-9 AC2 (REWRITTEN)**: Sync-time deleted-list path — WARN log uses `auto-sync.no-target-list`; marker NOT bumped; zero outbox rows inserted.
- **US-9 AC3 (NEW)**: Same-day re-run path — CAS loser inserts zero outbox rows so subscribers receive zero additional events.

### META-V3-003 (HIGH) — `message_key` field on EventMealPlanAutoSyncedData

**Source v3 findings**: EXEC-H-002, C3-003 (FR-022 claims i18n keys surface in event payload but the payload has no such field)

**Changes applied**:
- **FR-021 (REWRITTEN)**: Added `message_key: str | None = None` field to `EventMealPlanAutoSyncedData`. None on success path; set to `auto-sync.*` key on error/no-op paths. Outbox dispatcher (FR-031) forwards via `EventBusService.dispatch(..., message=message_key or '')` so subscribers receive the key in `EventBusMessage.body`. Cites `event_types.py:188-191` (populate_body validator) to verify empty-body default behavior is preserved on success path.
- **FR-022 (REVISED)**: Explicitly states the i18n keys surface in exactly two places: (a) server-side logs, (b) the new `message_key` field on `EventMealPlanAutoSyncedData`. NOT in the HTTP response body.
- **Key Entities → EventMealPlanAutoSyncedData**: Added `message_key: str | None = None` field; updated description to explain when None vs set.

### META-V3-004 (MEDIUM) — Stale locale OOS sentence

**Source v3 findings**: C3-004, EXEC-M-001 (Out-of-Scope still says "Mealie currently ships only en-US.json" — contradicts FR-022 + Assumption #3)

**Changes applied**:
- **Out of Scope[3] (REWRITTEN)**: Replaced with "Internationalization changes for non-en-US locales. Mealie ships 40+ Crowdin-managed locale files at `mealie/lang/messages/*.json` …; per `.github/copilot-instructions.md` 'Translations' section ONLY `en-US.json` is editable by repository contributors. PRs touching other locale files are rejected — Crowdin back-fills the keys on its own cadence."

### META-V3-005 (MEDIUM) — Postgres isolation level wording

**Source v3 findings**: EXEC-M-002 (edge case said "Postgres default REPEATABLE READ"; the real default is READ COMMITTED)

**Changes applied**:
- **Edge case (two-replica)**: Rewritten to "PostgreSQL default isolation level is READ COMMITTED, which still serializes concurrent UPDATEs on the same row via row-level write locks". SQLite per-statement lock wording retained. Outcome unchanged (CAS loser is a structural no-op).

### META-V3-006 (MEDIUM) — FR-014 / FR-023 filter implementation citations

**Source v3 findings**: EXEC-M-003 (FR-014/FR-023 should cite the actual filter implementation in `repository_generic.py` to prove the "WHERE clause on every query" claim)

**Changes applied**:
- **FR-014 (REVISED)**: Added citations to `mealie/repos/repository_generic.py:94-102` (`_filter_builder`), `:156-179` (`get_one` with `filter_by(**self._filter_builder())`), `:315-355` (`page_all` with `filter_by(**fltr)`). Prose now references `_filter_builder` so the claim is concretely verifiable.
- **FR-023 (REVISED)**: Same citations added. Prose explains the generic implementation of household scoping lives in `_filter_builder`, which prepends `group_id` and `household_id` to every `_query_one` / `get_one` / `page_all` WHERE clause.

### META-V3-007 (LOW) — Reciprocal SC↔FR links

**Source v3 findings**: C3-005 (4 one-way edges in `spec_v3.json`)

**Changes applied** (in JSON only — markdown does not render `related_success_criteria` symmetrically):
- `FR-020.related_success_criteria` += `SC-026`
- `FR-022.related_success_criteria` += `SC-026`
- `FR-021.related_success_criteria` += `SC-027`
- `FR-024.related_success_criteria` += `SC-027`
- `FR-001.related_success_criteria` += `SC-028`
- `FR-023.related_success_criteria` += `SC-029`
- `SC-027.related_requirements` += `FR-021`
- `SC-028.related_requirements` += `FR-001`
- `SC-029.related_requirements` += `FR-023`, `FR-029`
- `FR-023.related_success_criteria` revised to `[SC-006, SC-029]`
- `FR-011.related_success_criteria` += `SC-030`, `SC-032`
- `FR-021.related_success_criteria` += `SC-031`

## v3 critical+high → v4 mapping

| v3 finding (axis-id) | v4 resolution |
|---|---|
| NEW-ARCH-C-1 (single rollbackable tx impossible) | NC-004 + FR-030 + FR-031 + FR-011/FR-012/FR-020/FR-024 rewrites |
| NEW-ARCH-H-1 (event dispatch contradiction) | NC-004 + FR-031 (outbox decouples dispatch from tx) |
| EXEC-C-001 (single tx + internal commits) | FR-030 (commit kwarg) + FR-011 (outer tx via `with session.begin()`) |
| EXEC-C-002 (event exactly-once + rollback) | FR-031 (outbox) + SC-013/SC-031 (outbox-aware semantics) |
| C3-001 (after-commit dispatch can't roll back) | FR-031 (no after-commit dispatch — dispatch reads from outbox in a separate task) |
| COMP-H-013 (US-9 vs 204 contract) | US-9 rewrite (logs + message_key, not response body) |
| C3-002 (US-9 requires response body) | US-9 rewrite |
| EXEC-H-001 (run-now 204 vs US-9) | US-9 rewrite |
| EXEC-H-002 (no message_key on payload) | FR-021 adds `message_key` field; FR-031 forwards into dispatch message; FR-022 narrows surfaces |

## v3 → v4 regression risk

| Risk | Status |
|---|---|
| Does the `commit: bool = True` kwarg break any current caller passing positional args? | NO — `repos_generic.create_many(data)`, `update(match_value, new_data)`, `update_many(data)`, `bulk_create_items(create_items, auto_find_labels)`, `add_recipe_ingredients_to_list(list_id, recipe_items)` are all called with positional args today (verified via grep of mealie/). The new kwarg is appended after the existing positional+kwarg list and defaults to `True`, so no signature mismatch. |
| Does the new `event_outbox` table conflict with any existing migration? | NO — `event_outbox` is a new table name not present in the existing alembic baseline (verified via grep). |
| Does the outbox introduce subscribers' duplicate-event risk? | YES on retry pathways (MAX_ATTEMPTS=5) — but this is now explicit in SC-013/FR-021/FR-031/NC-004 and subscribers are told to treat `Event.event_id` as the idempotency key. Mealie's `Event.event_id` is set at instantiation via `uuid.uuid4()` (`event_types.py:204-207`); each outbox row produces a fresh `Event.event_id` on dispatch but the same `event_outbox.id` on retry, so subscribers can deduplicate using either. |
| Could the dispatcher poll create dispatch latency? | YES — worst case 5 minutes from CAS-winner commit to subscriber delivery. Documented in Self-Concerns[FR-031] + Assumptions[+1]; operational metrics recommended for production tuning. |
| Could the `with session.begin():` block conflict with the existing scheduler context? | NO — `SchedulerService.run_minutely` (`scheduler_service.py:77-81`) uses its own session context (via dependency injection); the auto-sync task creates the `with session.begin():` block inside its callable and the existing scheduler context does not own an open transaction. Verified via `mealie/services/scheduler/scheduler_service.py`. |

## Files written by this iteration

- `spec_v4.json` (apply meta-review actions to spec_v3.json — 151,117 bytes)
- `spec_v4.md` (rendered from spec_v4.json via `spec_to_markdown` — 116,877 bytes)
- `rewrite_v3_to_v4.md` (this file)
- `meta_review_v3.{md,json}`
- `build_v4.py` (the in-place transformation script — kept for audit)

## Build artifact (for audit)

The script that produced v4 from v3 is `build_v4.py`. It loads `spec_v3.json`, mutates the dict in place via `apply_v4_changes`, writes `spec_v4.json`, runs `Spec.model_validate`, renders markdown via `spec_to_markdown`, and runs all 4 validators inline. All 4 reported zero problems on the first valid invocation (after a single citation-range correction for `page_all` L315 vs L316). The script is idempotent — running it again against `spec_v3.json` produces a byte-identical `spec_v4.json`.

## Final validator state (v4)

```
Validating spec v4 schema...
  A4+F3 schema: PASS (FRs=31, SCs=32, NCs=4)
Running validators...
  A5 citation: 0 problems
  B3 trace: 0 gaps
  B1 roundtrip: PASS

All 4 validators clean.
```
