# Architecture Review v4 — case-5 LIVE RUN ITER 4

## Verdict
REJECT

v4 makes the right architectural move from direct/after-commit event dispatch to a transactional outbox, and it recognizes the internal-commit problem from v3. However, the proposed no-commit refactor is still not executable as specified, and the outer-transaction boundary conflicts with SQLAlchemy's existing session/autobegin behavior after precondition reads. The outbox retry idempotency contract also names an idempotency key that the current EventBus path regenerates on every retry. Approval is not possible because there are critical/high issues.

## V3 issue resolution table

| v3 issue | Status in v4 | Evidence |
|---|---|---|
| NEW-ARCH-C-1 (CRITICAL): single rollbackable transaction incompatible with internal commits | PARTIALLY_RESOLVED | v4 adds NC-004, FR-030 commit flags, and rewrites FR-011/FR-012/FR-020 around one `with session.begin():` block (`spec_v4.md:42-50`, `spec_v4.md:203-207`, `spec_v4.md:230-231`, `spec_v4.md:260-263`). But FR-030 keeps `create_many`'s post-write refresh loop unchanged while suppressing commit, and FR-011 opens `session.begin()` after repository reads on the same SQLAlchemy 2.0 session; both defects keep the core transaction design from being reliable (see NEW-ARCH-C-1/2 below). |
| NEW-ARCH-H-1 (HIGH): event dispatch specified as both post-commit and rollbackable | PARTIALLY_RESOLVED | v4 correctly decouples external dispatch through `event_outbox` (`spec_v4.md:263-265`) and no longer claims dispatch failure rolls back CAS/items (`spec_v4.md:206-207`). However, retry idempotency is still architecturally wrong because the spec tells subscribers to dedupe using `Event.event_id` while the existing event constructor generates a fresh UUID per dispatch (`event_types.py:204-207`), so retries do not preserve that key (see NEW-ARCH-H-1). |
| NEW-ARCH-M-1 (MEDIUM): US-9 contradicted the 204 No Content contract | RESOLVED | US-9 now explicitly requires 204 with zero body bytes and log-only i18n on run-now precondition failure (`spec_v4.md:155-167`), and FR-020/SC-026 preserve the empty-body contract (`spec_v4.md:230-231`, `spec_v4.md:319-320`). |
| NEW-ARCH-M-2 (MEDIUM): locale scope internally inconsistent | RESOLVED | Out of Scope now correctly says non-en-US locale files are Crowdin-managed and must not be modified (`spec_v4.md:388-395`). |

## New issues in v4

### NEW-ARCH-C-1 (CRITICAL): `create_many(commit=False)` cannot return created schemas with the existing refresh loop

FR-030 says `RepositoryGeneric.create_many(..., commit=False)` only guards `self.session.commit()` and leaves the `session.refresh(...)` loop unchanged (`spec_v4.md:260-261`). The existing implementation adds new pending models, commits, then refreshes each model (`repository_generic.py:195-208`). If commit is skipped, the new models have not been flushed/committed before the refresh loop, and Mealie's SessionLocal is configured with `autoflush=False` (`db_setup.py:38-40`). The auto-sync CAS winner path necessarily calls `ShoppingListService.add_recipe_ingredients_to_list(..., commit=False)`, which delegates to `bulk_create_items(commit=False)` and then `list_items.create_many(..., commit=False)` for new shopping-list rows (`spec_v4.md:203-204`, `shopping_lists.py:213-216`, `shopping_lists.py:433-455`).

As written, the no-commit seam is not a valid transaction-compatible write path: it suppresses the internal commit but does not specify an explicit `session.flush()` before refresh, nor an alternate no-refresh return path while the outer transaction is open. This means the primary feature path can fail before the outbox insert and retry forever for any recipe that creates new list items. The v3 critical is therefore only partially fixed. Required redesign: define the `commit=False` contract to flush pending writes before refresh/model validation, or split repository methods into staged-write methods that return ORM objects/ids without refresh until the outer transaction commits.

### NEW-ARCH-C-2 (CRITICAL): FR-011 opens `with session.begin()` after precondition reads on the same SQLAlchemy 2.0 session

FR-011 explicitly resolves the target list and today's meal plan outside the outer transaction, then opens `with session.begin():` (`spec_v4.md:203-204`). Those precondition checks use repository methods such as `get_one` and `get_today`; `get_one` calls `self.session.execute(...)` (`repository_generic.py:156-179`). Mealie's sessions are SQLAlchemy future sessions (`sessionmaker(..., future=True)`) with `autocommit=False` (`db_setup.py:38-40`), so a SELECT starts an implicit transaction on the session. The spec does not require a `session.rollback()` / `session.commit()` / fresh session between the precondition reads and `with session.begin()`.

Consequently, the proposed sequence can hit SQLAlchemy's “transaction already begun” failure before the CAS update. This is an architectural transaction-boundary defect, not just an implementation typo, because the spec relies on precondition reads outside the rollbackable block while reusing the same session for the rollbackable block. Required redesign: either start the explicit transaction before all reads that share the session, use a separate short-lived read session for preconditions, or explicitly end the implicit read transaction before entering the CAS/items/outbox transaction.

### NEW-ARCH-H-1 (HIGH): Outbox retry idempotency key is not stable across dispatch retries

FR-031 and SC-013 rely on subscriber idempotency for retry paths, saying retries should be deduped by the same `event_outbox.id` / `Event.event_id` (`spec_v4.md:263-264`, `spec_v4.md:293-294`, `spec_v4.md:386-386`). But the existing `EventBusService.dispatch(...)` constructs a new `Event(...)` each time it is called (`event_bus_service.py:66-80`), and `Event.__init__` assigns `self.event_id = uuid.uuid4()` on every instantiation (`event_types.py:204-207`). The proposed `event_outbox` schema does not store an event_id column and FR-031's dispatch call does not pass `event_outbox.id` in the payload or message metadata (`spec_v4.md:263-264`).

Therefore a transient dispatch failure followed by retry will present downstream subscribers with different `Event.event_id` values for the same outbox row. The spec's at-least-once retry contract is acceptable, but the idempotency guidance is currently impossible to implement from the delivered event. Required fix: persist a stable event id on the outbox row and force `Event.event_id` to that value during dispatch, or include `event_outbox.id` as an explicit payload field / metadata field and update SC-013/FR-031 to require subscribers to dedupe on that stable key.

### NEW-ARCH-M-1 (MEDIUM): No-op/error `message_key` events are specified but structurally never enqueued

FR-021 says `message_key` is set on no-meal-plan / no-target-list / already-synced paths (`spec_v4.md:233-234`), and US-9 says operators and downstream event-bus subscribers can observe localized keys (`spec_v4.md:155-167`). But FR-011 step 2 returns before CAS/outbox for no meal plan or no target list, and step 4 returns before outbox for already-synced CAS losers (`spec_v4.md:203-204`); US-9 and SC-025 also require zero `event_outbox` rows for these cases (`spec_v4.md:165-167`, `spec_v4.md:317-318`). That makes the event-payload `message_key` surface unreachable for exactly the no-op paths that mention it. Either narrow the contract to logs-only for no-op paths, or enqueue explicit no-op outbox events without violating idempotency/no-side-effect expectations.

## Summary

- V3 critical/high resolved enough to approve: no
- New critical: 2
- New high: 1
- New medium: 1
- Final verdict: REJECT
