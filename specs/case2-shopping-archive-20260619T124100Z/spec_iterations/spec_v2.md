# Spec v2 — Case 2: Shopping List Archive (Mealie)

> **Generated:** 2026-06-19
> **Repo:** `C:\Users\v-liyuanjun\Downloads\mealie\` @ `4a099c16`
> **Selected approach:** Repository-level frozen guard + service-level pre-flight (`approach/selected.md`)
> **Input source:** `input.md` §1–§8
> **Status:** v2 — resolves all CRITICAL + HIGH issues from `review_v1_{architecture,completeness,consistency,executability}.md`
> **Iteration:** 2

---

## 1. Summary

Add an "archive" lifecycle to Mealie's `ShoppingList` entity. Archived lists are hidden from the default list view, are revealed via a new `?archived=` query parameter, become **immutable for every list-mutating route** (PUT list, item create/update/delete and their bulk siblings, label-settings, recipe add/remove → all return HTTP 409 with i18n key `shopping-list.archived.frozen`), and emit dedicated `ShoppingListArchived` / `ShoppingListUnarchived` events on the existing event bus. The implementation centralises the default-exclude filter AND the frozen-state guard in the repository layer (per input §7), with a thin service-layer pre-flight on the routes that bypass the repo guard (`update_label_settings`, `add_recipe_ingredients_to_list`, `remove_recipe_ingredients_from_list`); tenancy is preserved via the existing `HouseholdRepositoryGeneric._filter_builder` (`mealie/repos/repository_generic.py:94-102`). Domain exceptions are translated to HTTP 409 in a single FastAPI global exception handler — services stay free of HTTP concerns.

---

## 2. User stories

### US-1 (P1) — Archive a shopping list (success path)
**As** a household member
**I want** to mark a fully-completed shopping list as "archived"
**So that** the main shopping-list view stays uncluttered and I retain a historical record of what I bought.

**Given** I am authenticated as a member of household H1, and `ShoppingList L1` has `household_id == H1` and `all(item.checked is True for item in L1.list_items)`,
**When** I `POST /api/households/shopping/lists/{L1.id}/archive`,
**Then** the response is `200 OK` with body `ShoppingListOut` where `archived_at` is the current UTC timestamp and `archived_by` is a `UserSummary` reflecting my user record;
**And** the row in `shopping_lists` has `archived_at IS NOT NULL` and `archived_by_user_id = me.id`;
**And** one `EventTypes.shopping_list_archived` event is dispatched on the bus with `EventShoppingListArchiveData` payload.

### US-2 (P1) — Archive blocked when unchecked items present
**As** a household member
**I want** the system to refuse to archive a list that still has unchecked items
**So that** I don't accidentally lose track of in-progress purchases.

**Given** `ShoppingList L1` has `any((item.checked is None or item.checked is False) for item in L1.list_items)`,
**When** I `POST /api/households/shopping/lists/{L1.id}/archive`,
**Then** the response is `409 CONFLICT` with body `{"detail": {"message": "Cannot archive a shopping list while items remain unchecked", "error": true, "exception": null}}` (the message is the en-US value of i18n key `shopping-list.archive.unchecked-items`);
**And** the row in `shopping_lists` is unchanged (`archived_at IS NULL`);
**And** no event is dispatched.

### US-3 (P1) — Default GET filters archived lists out
**As** a household member
**I want** the default shopping-lists view to show only active (non-archived) lists
**So that** I see a clean, current working set.

**Given** household H1 contains both `L_active` (archived_at IS NULL) and `L_archived` (archived_at IS NOT NULL),
**When** I `GET /api/households/shopping/lists`,
**Then** the response is `200 OK` and `items` contains `L_active.id` and does NOT contain `L_archived.id`;
**And** the `total` field reflects the active-only count.

### US-4 (P1) — `?archived=true` / `?archived=all` reveal archive history
**As** a household member
**I want** explicit query parameters to view archived-only or all (active+archived) lists
**So that** I can review history without polluting the default view.

**Given** household H1 contains `L_active` and `L_archived` as above,
**When** I `GET /api/households/shopping/lists?archived=true`, **Then** `items` contains only `L_archived.id`, and each item has `archived_at` as ISO-8601 string + `archived_by` as `UserSummary`;
**And when** I `GET /api/households/shopping/lists?archived=all`, **Then** `items` contains both `L_active.id` (with `archived_at: null, archived_by: null`) and `L_archived.id` (populated).

### US-5 (P1) — Frozen-state: every list-mutating route returns 409
**As** a household member
**I want** every mutating operation on an archived list (or its items, labels, or recipe references) to be rejected with a clear "frozen" error
**So that** archived history is preserved as a true historical record.

**Given** `ShoppingList L1` has `archived_at IS NOT NULL` and contains items `I1, I2`,
**When** I attempt any of:
  - `PUT /api/households/shopping/lists/{L1.id}` (with valid `ShoppingListUpdate` body)
  - `POST /api/households/shopping/items` (with `shopping_list_id == L1.id`)
  - `POST /api/households/shopping/items/create-bulk` (with any item targeting `L1.id`)
  - `PUT /api/households/shopping/items/{I1.id}` (any field, including `checked`)
  - `PUT /api/households/shopping/items` (bulk update with any item targeting `L1`)
  - `DELETE /api/households/shopping/items/{I1.id}`
  - `DELETE /api/households/shopping/items?ids=I1,I2`
  - `PUT /api/households/shopping/lists/{L1.id}/label-settings` (any label payload)
  - `POST /api/households/shopping/lists/{L1.id}/recipe` (any recipe params)
  - `POST /api/households/shopping/lists/{L1.id}/recipe/{recipe_id}` (deprecated form)
  - `POST /api/households/shopping/lists/{L1.id}/recipe/{recipe_id}/delete`
**Then** each response is `409 CONFLICT` with body `{"detail": {"message": "This shopping list is archived and cannot be modified. Unarchive it first.", "error": true, "exception": null}}` (en-US value of i18n key `shopping-list.archived.frozen`);
**And** no rows in `shopping_lists`, `shopping_list_items`, `shopping_list_multi_purpose_label_settings`, or `shopping_list_recipe_references` are modified (atomic-pre-flight semantics; the service-layer pre-flight runs BEFORE any sub-call to `bulk_create_items` / `update_many` / `shopping_list_multi_purpose_labels.update_many`);
**And** `L1.updated_at`, `I1.updated_at`, and all related rows' `updated_at` are unchanged.

### US-6 (P1) — Unarchive restores mutable state
**As** a household member
**I want** to "unarchive" a list back to mutable state
**So that** I can correct mistakes or repurpose an archived list.

**Given** `ShoppingList L1` has `archived_at IS NOT NULL`,
**When** I `POST /api/households/shopping/lists/{L1.id}/unarchive`,
**Then** the response is `200 OK` with `ShoppingListOut` where `archived_at == null` and `archived_by == null`;
**And** the row has `archived_at IS NULL` and `archived_by_user_id IS NULL`;
**And** the same `L1` now appears in default `GET /lists` results;
**And** subsequent `PUT /lists/{L1.id}`, `POST /items` (targeting L1), `PUT /items/{I.id}`, `DELETE /items/{I.id}`, `PUT /label-settings`, and recipe routes succeed (no 409);
**And** exactly one `EventTypes.shopping_list_unarchived` event is dispatched (because a state transition occurred).

### US-7 (P1) — Event bus dispatches with correct payload (no cross-household leak)
**As** a webhook/notifier subscriber configured for shopping-list-archive events in my household
**I want** to receive an event when an archive/unarchive occurs in my household, with exactly the spec'd payload fields
**So that** I can integrate downstream systems (analytics, exports) without leaking other tenants' data.

**Given** I am subscribed via `GroupEventNotifier` with `shopping_list_archived = true` for household H1,
**When** any user in H1 archives a list,
**Then** exactly one `Event` arrives at my subscriber with `event_type == EventTypes.shopping_list_archived`, `document_data` of type `EventShoppingListArchiveData` whose `model_dump().keys()` equals exactly `{"document_type", "operation", "list_id", "list_name", "household_id", "archived_by_user_id", "item_count", "total_estimated_amount"}` (the first two are inherited from `EventDocumentDataBase` per `mealie/services/event_bus_service/event_types.py:88-91`; the rest are declared on `EventShoppingListArchiveData`);
**And** `operation == EventOperation.update`;
**And** `household_id` in the payload equals H1;
**And** no Event arrives at subscribers in a different household H2 (same or different group);
**And** the symmetric requirement holds for `shopping_list_unarchived`.

### US-8 (P1) — Multitenant isolation
**As** a member of household H1 in group G1
**I want** archived shopping lists to remain strictly invisible to other households (even within my group) and to other groups
**So that** tenant data boundaries are respected.

**Given** household H1 (group G1) owns archived `L1`; household H2 (group G1) owns archived `L2`; household H3 (group G2) owns archived `L3`,
**When** I (in H1) `GET /api/households/shopping/lists?archived=true`, **Then** items contains only `L1.id` (NOT `L2.id`, NOT `L3.id`);
**And when** I `POST /api/households/shopping/lists/{L2.id}/archive` or `/unarchive`, **Then** the response is `404 NOT FOUND`;
**And when** I `POST /api/households/shopping/lists/{L3.id}/archive` or `/unarchive`, **Then** the response is `404 NOT FOUND`;
**And when** a user in H3 (group G2) issues `GET /api/households/shopping/lists?archived=true`, **Then** the response does NOT include `L1.id` or `L2.id`;
**And** symmetric behavior holds for all six (caller-household, target-household) pairs across the three households.

### US-9 (P2) — Schema backward compatibility (null-default, not field-omit)
**As** an existing API consumer (e.g., the offline-PWA queue or an external integration)
**I want** the existing `ShoppingListOut` / `ShoppingListSummary` shapes to remain backward-compatible
**So that** my pre-feature code continues to work without changes.

**Given** I am an existing consumer that does NOT read `archived_at` / `archived_by`,
**When** I `GET /api/households/shopping/lists` on a database where no list has been archived,
**Then** the response items have `archived_at: null` and `archived_by: null`, which my consumer silently ignores (JSON `null` on an unknown field is forward-compatible by RFC 8259 / Postel's law);
**And** existing tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` (1113 lines, 7 baseline test methods) continue to pass unchanged.

> **Note on input §6 "默认查询不返回这些字段".** Resolved by **default-omit at the request-filtering layer** (the collection endpoint default-hides archived ROWS entirely) rather than field-projection. See `exploration/consolidated.md` CRITICAL-3 for full rationale: conditional fields would force a schema bifurcation that breaks codegen and TypeScript typing. This is a binding interpretation, not a deviation — the literal user-visible behavior matches: a default GET reveals nothing about archive state because no archived rows are returned.

### US-10 (P2) — Scheduled cleanup respects frozen state
**As** a system operator
**I want** the existing `delete_old_checked_shopping_list_items` scheduled task to skip archived lists
**So that** archived history is preserved against automatic trimming.

**Given** the scheduler runs (per `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py:54-75`) and one household has both an active list with >100 checked items and an archived list with >100 checked items,
**When** the task completes,
**Then** the active list's old checked items are trimmed (existing behavior);
**And** the archived list is left fully intact (no items deleted);
**And** no `ShoppingListIsArchivedError` is raised from the scheduler context.

---

## 3. Functional requirements

> Every `code_references` line range below was verified by direct file inspection (June 2026, commit `4a099c16`). Verb tense: **MUST** = required, **SHOULD** = recommended, **MAY** = optional.

### FR-1. Data model — `ShoppingList` extension
The `mealie.db.models.household.shopping_list.ShoppingList` model **MUST** gain two new columns and one relationship:
- `archived_at: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime, index=True)` — default NULL, NULL = active.
- `archived_by_user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), index=True)` — default NULL.
- `archived_by: Mapped[Optional["User"]] = orm.relationship("User", foreign_keys=[archived_by_user_id])` — disambiguating against the existing `user` relationship at line 156.
- The existing `user` relationship at line 156 **MUST** be updated to specify `foreign_keys=[user_id]` for SQLAlchemy disambiguation.

**Invariant (one-way):** `archived_at IS NULL ⇒ archived_by_user_id IS NULL`. Service layer enforces this on archive/unarchive transitions. **The reverse direction does NOT hold:** an archived row (archived_at IS NOT NULL) MAY have `archived_by_user_id IS NULL` after the archiving user is deleted (FK is `ON DELETE SET NULL`). This loosened invariant resolves the contradiction between the original FR-1 invariant and EC-8/NC-5 flagged by review_v1_consistency C-001 and review_v1_completeness COMP-H-002.

**code_references:**
- `mealie/db/models/household/shopping_list.py:147-181` — current `ShoppingList` class declaration (`__tablename__`, `id`, `group_id`, `user`, `user_id`, `name`, `list_items`, `recipe_references`, `label_settings`, `extras`); new columns insert between line 158 (`name`) and line 159 (`list_items`).
- `mealie/db/models/recipe/recipe.py:145,147` — `date_updated`/`last_made` exact `FilterableColumn[datetime | None] = mapped_column(NaiveDateTime)` pattern to mirror.
- `mealie/db/models/household/mealplan.py:67` — `user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)` exact pattern to mirror for `archived_by_user_id` (with `ondelete="SET NULL"` added).

### FR-2. Alembic migration (a) — `shopping_lists` columns
A new alembic migration file under `mealie/alembic/versions/` **MUST** add the two columns to the `shopping_lists` table.
- Use `op.batch_alter_table("shopping_lists")` for SQLite + PostgreSQL portability.
- `archived_at`: `sa.Column("archived_at", mealie.db.migration_types.NaiveDateTime(), nullable=True)`.
- `archived_by_user_id`: `sa.Column("archived_by_user_id", mealie.db.migration_types.GUID(), nullable=True)`.
- `batch_op.create_foreign_key("fk_shopping_lists_archived_by_user_id", "users", ["archived_by_user_id"], ["id"], ondelete="SET NULL")`.
- `batch_op.create_index("ix_shopping_lists_archived_by_user_id", ["archived_by_user_id"])`.
- `batch_op.create_index("ix_shopping_lists_archived_at", ["archived_at"])`.
- `down_revision` **MUST** chain off the current head revision (today: `2187537c52b8` from `2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py`; if a newer migration has landed at generation time, chain off the actual head).
- `downgrade()` **MUST** drop both indexes, the FK, and both columns so that DB rollback succeeds.
- Existing rows **MUST** have `archived_at = NULL` and `archived_by_user_id = NULL` (no `server_default` needed; NULL is the default for nullable columns).

**code_references:**
- `mealie/alembic/versions/2025-09-10-19.21.48_1d9a002d7234_add_referenced_recipe_to_ingredients.py:21-30` — exact `batch_alter_table → add_column → create_index → create_foreign_key` template (nullable GUID FK column pattern).
- `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_.py:183` — `sa.Column("last_made", mealie.db.migration_types.NaiveDateTime(), nullable=True)` — exact `NaiveDateTime` pattern. (Filename truncated by the alembic generator — verified by directory listing.)

### FR-3. Alembic migration (b) — `group_events_notifier_options` columns
A second alembic migration **MUST** add boolean subscription columns to `group_events_notifier_options`.
- `shopping_list_archived: sa.Column(sa.Boolean(), nullable=False, server_default=sa.sql.expression.false())`.
- `shopping_list_unarchived: sa.Column(sa.Boolean(), nullable=False, server_default=sa.sql.expression.false())`.
- `down_revision` chains off the migration in FR-2.
- `downgrade()` drops both columns.

**code_references:**
- `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py:1-51` — exact verbatim template (only difference is column names). (Filename truncated by alembic generator — verified by directory listing.)
- `mealie/db/models/household/events.py:35-37` — `shopping_list_{created,updated,deleted}: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)` — exact column shape to add at lines 38-39 (after the existing shopping_list group).

### FR-4. New API endpoints — archive / unarchive
The `ShoppingListController` in `mealie/routes/households/controller_shopping_lists.py` **MUST** expose two new endpoints. Both follow the existing controller's `publish_event` template (`controller_shopping_lists.py:190-196`).
- `POST /api/households/shopping/lists/{item_id}/archive` → `archive_one(self, item_id: UUID4) -> ShoppingListOut`.
- `POST /api/households/shopping/lists/{item_id}/unarchive` → `unarchive_one(self, item_id: UUID4) -> ShoppingListOut`.

Each MUST:
- Be a `@router.post(...)` decorator with `response_model=ShoppingListOut, status_code=200, responses={409: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}`.
- Auth: same as all existing `ShoppingListController` routes (no extra `Depends` — inherits from `BaseCrudController` which uses `get_current_user`).
- Delegate to `result = self.service.archive_list(item_id, self.user.id)` / `result = self.service.unarchive_list(item_id)`. The service returns `ArchiveTransitionResult(shopping_list: ShoppingListOut, transitioned: bool)`.
- Dispatch `EventTypes.shopping_list_archived` / `EventTypes.shopping_list_unarchived` via `self.publish_event(..., group_id=result.shopping_list.group_id, household_id=result.shopping_list.household_id, ...)` **ONLY when `result.transitioned is True`** (so EC-3 unarchive-no-op does not dispatch a spurious event — resolves review_v1_consistency C-003).
- Multitenant isolation: cross-household / cross-group → `404 NOT FOUND` automatically via `HouseholdRepositoryGeneric._filter_builder` (no extra code; resolves review_v1_architecture H2 via the tenant-scoped repository writes in FR-7).
- Return `result.shopping_list` as the response body.

**code_references:**
- `mealie/routes/households/controller_shopping_lists.py:159-229` — `ShoppingListController` CRUD section (insert new endpoints after `delete_one` at line 229).
- `mealie/routes/households/controller_shopping_lists.py:186-198` — `create_one` pattern (decorator, status_code, `publish_event` template).
- `mealie/routes/_base/base_controllers.py:199-214` — `BaseCrudController.publish_event` signature.

### FR-5. Modified API endpoint — `GET /lists?archived=`
The existing `ShoppingListController.get_all` **MUST** accept a new query parameter:
- `archived: ArchivedFilter = Query(ArchivedFilter.exclude)` from `mealie.schema.household.group_shopping_list.ArchivedFilter` (new enum — see FR-9).
- Pass the parameter to `self.repo.page_all(pagination=q, override=ShoppingListSummary, archived=archived)` (the override of `page_all` is on the new `RepositoryShoppingList` — see FR-7).
- Default behavior (no `archived` param OR `archived=false`) returns `archived_at IS NULL` only.
- `archived=true` returns `archived_at IS NOT NULL` only.
- `archived=all` returns both, ordered as the existing pagination would.

**code_references:**
- `mealie/routes/households/controller_shopping_lists.py:176-184` — current `get_all` implementation.

### FR-6. Frozen routes — 409 on every list-mutating route
> **Resolves review_v1_architecture C1, review_v1_completeness COMP-H-003, and review_v1_consistency C-005.** v1's partial-mutation acceptance of label-settings and recipe routes is rescinded: v2 freezes ALL list-mutating routes. Defense in depth uses BOTH a repository-layer guard (for routes whose write goes through `RepositoryShoppingList.update` or `RepositoryShoppingListItem.{create,update,delete}_many`) AND a service-layer pre-flight (for routes that bypass the repo guard).

The following routes **MUST** return `409 CONFLICT` with body `ErrorResponse.respond(message=t("shopping-list.archived.frozen"))` when the target list is archived. The 409 **MUST** fire BEFORE any DB write occurs on either the list or its children:

**Group A — caught by repo-layer guard (FR-7 + FR-8):**
1. `PUT /api/households/shopping/lists/{item_id}` (handler `ShoppingListController.update_one`, controller_shopping_lists.py:204-215) — guard in `RepositoryShoppingList.update`.
2. `POST /api/households/shopping/items` (handler `ShoppingListItemController.create_one` → delegates to `create_many`, lines 127-129) — guard in `RepositoryShoppingListItem.create_many`.
3. `POST /api/households/shopping/items/create-bulk` (handler `ShoppingListItemController.create_many`, lines 121-125) — same guard.
4. `PUT /api/households/shopping/items/{item_id}` (handler `update_one` → `update_many`, lines 141-143) — guard in `RepositoryShoppingListItem.update_many`.
5. `PUT /api/households/shopping/items` (handler `update_many`, lines 135-139) — same guard.
6. `DELETE /api/households/shopping/items/{item_id}` (handler `delete_one` → `delete_many`, lines 151-153) — guard in `RepositoryShoppingListItem.delete_many`.
7. `DELETE /api/households/shopping/items` (handler `delete_many`, lines 145-149) — same guard.

**Group B — caught by service-layer pre-flight (FR-11 §4):**
8. `PUT /api/households/shopping/lists/{item_id}/label-settings` (handler `update_label_settings`, controller_shopping_lists.py:234-254). The handler writes through `self.repos.shopping_list_multi_purpose_labels.update_many` at line 243, which does NOT pass through `RepositoryShoppingList.update`. **Mitigation:** the controller MUST call `self.service.ensure_list_not_archived(item_id)` (NEW; FR-11 §4) at the very top of the handler, before any other code; the helper raises `ShoppingListIsArchivedError` (translated to 409 by the global handler — FR-11 §5) if archived.
9. `POST /api/households/shopping/lists/{item_id}/recipe` (handler `add_recipe_ingredients_to_list`, controller_shopping_lists.py:256-261) — same pre-flight as #8.
10. `POST /api/households/shopping/lists/{item_id}/recipe/{recipe_id}` (handler `add_single_recipe_ingredients_to_list`, controller_shopping_lists.py:263-272, deprecated) — same pre-flight; OR rely on its delegation to #9 to inherit the pre-flight (acceptable, since the pre-flight is in the called handler).
11. `POST /api/households/shopping/lists/{item_id}/recipe/{recipe_id}/delete` (handler `remove_recipe_ingredients_from_list`, controller_shopping_lists.py:274-283) — same pre-flight as #8.

The pre-flight for Group B routes is invoked from the **controller** layer (not the service) so the service stays HTTP-free, but the actual guard logic lives in `ShoppingListService.ensure_list_not_archived(item_id)`. The helper uses `self.shopping_lists.get_one(item_id)` (which is already tenant-scoped via `_filter_builder`) and raises `ShoppingListIsArchivedError({item_id})` if the row's `archived_at IS NOT NULL`. Cross-household lookups return `None` (404 path); the helper raises `NoEntryFound` for that case (mapped to 404 by `mealie_registered_exceptions`).

The Group B pre-flight runs BEFORE any sub-service call (`add_recipe_ingredients_to_list`, `remove_recipe_ingredients_from_list`, `update_many` on labels), guaranteeing atomic-pre-flight semantics — no partial mutation occurs on an archived list. This resolves the v1 SCN-2 partial-failure concern.

**code_references:**
- `mealie/routes/households/controller_shopping_lists.py:98-153` — `ShoppingListItemController` with all item endpoints.
- `mealie/routes/households/controller_shopping_lists.py:204-215` — `update_one` for `PUT /lists/{id}`.
- `mealie/routes/households/controller_shopping_lists.py:234-254` — `update_label_settings` (Group B route #8); pre-flight inserts at top of method body (line 236).
- `mealie/routes/households/controller_shopping_lists.py:256-261` — `add_recipe_ingredients_to_list` (Group B route #9); pre-flight inserts at top (line 258).
- `mealie/routes/households/controller_shopping_lists.py:263-272` — `add_single_recipe_ingredients_to_list` (Group B route #10, deprecated; inherits via delegation).
- `mealie/routes/households/controller_shopping_lists.py:274-283` — `remove_recipe_ingredients_from_list` (Group B route #11); pre-flight inserts at top (line 278).
- `mealie/schema/response/responses.py:8-19` — `ErrorResponse.respond(message=...)` envelope format.

### FR-7. Repository layer — centralised archive filter + guard (`RepositoryShoppingList`)
The existing `mealie/repos/repository_shopping_list.py` (currently 12 lines) **MUST** be extended to host all archive logic per input §7:

1. **`update(item_id, data)` override (extends existing override at lines 9-11):**
   - Before delegating to `super().update(...)`, perform a tenant-scoped fetch: `row = self.session.execute(self._query(with_options=False).filter_by(**self._filter_builder(id=item_id))).scalars().one_or_none()`.
   - If `row is None`, delegate to `super().update(item_id, data)` (which will itself raise `NoEntryFound` / `sqlalchemy.exc.NoResultFound`) — preserves the existing 404 behavior for cross-household calls.
   - If `row.archived_at is not None`, raise `ShoppingListIsArchivedError({item_id})`.
   - Otherwise delegate to `super().update(item_id, data)` as today.

2. **`archive(item_id, user_id) -> ArchiveTransitionResult` (NEW):**
   - Tenant-scoped fetch first: `row = ...filter_by(**self._filter_builder(id=item_id))...one_or_none()`. If `None`, raise `NoEntryFound()` (mapped to 404 by global handler).
   - If `row.archived_at is not None`, raise `ShoppingListIsArchivedError({item_id})` (idempotent-failure semantics — re-archive is a 409, signalling caller intent error).
   - Otherwise issue a tenant-scoped UPDATE: `stmt = sa.update(ShoppingList).where(ShoppingList.id == item_id, ShoppingList.group_id == self.group_id, ShoppingList.user_id.in_(sa.select(User.id).where(User.household_id == self.household_id))).values(archived_at=datetime.now(UTC), archived_by_user_id=user_id)`; `self.session.execute(stmt)`. The WHERE clause mirrors `_filter_builder`'s tenant scoping, preventing cross-household writes even if a future caller bypasses the pre-fetch (resolves review_v1_architecture H2).
   - Return `ArchiveTransitionResult(shopping_list=self.get_one(item_id), transitioned=True)`.

3. **`unarchive(item_id) -> ArchiveTransitionResult` (NEW):**
   - Tenant-scoped fetch first (same shape as §2). If `None`, raise `NoEntryFound()`.
   - If `row.archived_at is None`, return `ArchiveTransitionResult(shopping_list=<refreshed via get_one>, transitioned=False)` — idempotent no-op, NOT a 409; controller will skip event dispatch (resolves review_v1_consistency C-003).
   - Otherwise issue tenant-scoped UPDATE clearing both columns: `sa.update(ShoppingList).where(<same tenant clause as §2>).values(archived_at=None, archived_by_user_id=None)`; execute; return `ArchiveTransitionResult(shopping_list=self.get_one(item_id), transitioned=True)`.

4. **`page_all(pagination, override=None, search=None, archived: ArchivedFilter = ArchivedFilter.exclude) -> PaginationBase[Schema]` (OVERRIDE):**
   - Builds the base query via `self._query(...)`, applies `self._filter_builder()` via `filter_by(**fltr)`, then appends one of:
     - `archived == ArchivedFilter.exclude`: `.where(ShoppingList.archived_at.is_(None))`
     - `archived == ArchivedFilter.only`: `.where(ShoppingList.archived_at.is_not(None))`
     - `archived == ArchivedFilter.inclusive`: no additional where clause.
   - Continues with `add_pagination_to_query`, `loader_options`, materialize as in `RepositoryGeneric.page_all` (lines 315-355).

5. **`get_archived_ids(ids: set[UUID4]) -> set[UUID4]` (NEW):**
   - Returns the subset of `ids` that are currently archived AND visible to the caller (the existing `_filter_builder` group/household scope still applies — cross-household IDs are silently filtered out and treated as "not archived" for guard purposes; this is safe because cross-household mutations would 404 elsewhere anyway).
   - Single SQL query: `SELECT id FROM shopping_lists WHERE id IN :ids AND archived_at IS NOT NULL AND group_id = :group_id AND user_id IN (SELECT id FROM users WHERE household_id = :household_id)`.

6. **Typed exceptions** declared in `mealie/core/exceptions.py` (alongside existing `NoEntryFound`, `PermissionDenied`, etc.):
   - `class ShoppingListIsArchivedError(Exception): def __init__(self, list_ids: set[UUID4]): self.list_ids = list_ids; super().__init__(f"Shopping list(s) {list_ids} are archived")`.
   - `class ArchiveTransitionResult(NamedTuple): shopping_list: ShoppingListOut; transitioned: bool` — declared in `mealie/services/household_services/shopping_lists.py` (NOT `exceptions.py`).

The default-exclude filter MUST compose correctly with `HouseholdRepositoryGeneric._filter_builder` so that household/group isolation is preserved for all `archived` values.

**code_references:**
- `mealie/repos/repository_shopping_list.py:1-12` — current full file (the seam).
- `mealie/repos/repository_generic.py:79-92` — `_query` with `AssociationProxyInstance` handling.
- `mealie/repos/repository_generic.py:94-102` — `_filter_builder` injecting `group_id`+`household_id`.
- `mealie/repos/repository_generic.py:156-179` — `get_one` pattern (tenant-scoped) to mirror for §1/§2/§3 pre-fetch.
- `mealie/repos/repository_generic.py:315-355` — `page_all` pattern to mirror in §4 override.
- `mealie/repos/repository_generic.py:505-523` — `HouseholdRepositoryGeneric` constructor.
- `mealie/core/exceptions.py:1-90` — existing typed-exception module to extend with `ShoppingListIsArchivedError`.

### FR-8. New repository — `RepositoryShoppingListItem`
A new file `mealie/repos/repository_shopping_list_item.py` **MUST** define `class RepositoryShoppingListItem(HouseholdRepositoryGeneric[ShoppingListItemOut, ShoppingListItem])` that overrides three methods to guard against parent-list-archived state. The constructor **MUST** accept `parent_repo: RepositoryShoppingList` (constructor injection — the single normative wiring; no alternatives accepted, resolves review_v1_architecture M2, review_v1_consistency C-007, and review_v1_executability "or equivalent"):

```python
class RepositoryShoppingListItem(HouseholdRepositoryGeneric[ShoppingListItemOut, ShoppingListItem]):
    def __init__(self, *args, parent_repo: RepositoryShoppingList, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent_repo = parent_repo
```

- `create_many(items: list[ShoppingListItemCreate]) -> list[ShoppingListItemOut]`:
  - Extract `distinct_list_ids = {i.shopping_list_id for i in items}`.
  - `archived = self._parent_repo.get_archived_ids(distinct_list_ids)`.
  - If `archived` is non-empty, raise `ShoppingListIsArchivedError(archived)`.
  - Otherwise delegate to `super().create_many(items)`.
- `update_many(items: list[ShoppingListItemUpdateBulk]) -> list[ShoppingListItemOut]`: same pattern, extracting `distinct_list_ids` from `items`.
- `delete_many(ids: set[UUID4] | list[UUID4]) -> list[ShoppingListItemOut]`:
  - First query: `SELECT DISTINCT shopping_list_id FROM shopping_list_items WHERE id IN :ids` (scoped to current tenant via JOIN on `shopping_lists` if needed) → `distinct_list_ids`.
  - Call `self._parent_repo.get_archived_ids(distinct_list_ids)`; if non-empty, raise.
  - Otherwise delegate to `super().delete_many(ids)`.

The repository factory `mealie/repos/repository_factory.py:323-332` MUST be updated:

```python
@cached_property
def group_shopping_list_item(self) -> RepositoryShoppingListItem:
    return RepositoryShoppingListItem(
        self.session,
        PK_ID,
        ShoppingListItem,
        ShoppingListItemOut,
        group_id=self.group_id,
        household_id=self.household_id,
        parent_repo=self.group_shopping_lists,
    )
```

**code_references:**
- `mealie/repos/repository_factory.py:317-321` — `group_shopping_lists` cached_property (showing factory pattern).
- `mealie/repos/repository_factory.py:323-332` — `group_shopping_list_item` cached_property to swap.
- `mealie/repos/repository_generic.py:505-523` — `HouseholdRepositoryGeneric` ctor signature.

### FR-9. Schema additions
The `mealie/schema/household/group_shopping_list.py` **MUST** be extended with:
1. **New enum `ArchivedFilter(StrEnum)`** at top of file (after the existing imports, before `ShoppingListItemRecipeRefCreate` at line 32):
   - Members: `exclude = "false"`, `only = "true"`, `inclusive = "all"`.
2. **`ShoppingListSummary` (lines 216-238)** gains two optional fields:
   - `archived_at: datetime | None = None`
   - `archived_by: UserSummary | None = None`
   - `loader_options()` (lines 224-238) gains one entry: `selectinload(ShoppingList.archived_by).load_only(User.id, User.group_id, User.household_id, User.username, User.full_name)`.
3. **`ShoppingListOut` (lines 250-285)** gains the same two optional fields and the same `loader_options()` extension at lines 261-285.
4. **Imports** — add `from enum import StrEnum`, `from mealie.schema.user.user import UserSummary` at top.

The default `None` values **MUST** preserve backward compatibility (US-9). Per `exploration/consolidated.md` CRITICAL-3, the field is always present on the schema; the "default omit" requirement in input §6 is satisfied at the **request-filtering** level (collection endpoint default-hides archived ROWS), not at the **field-projection** level. This is a binding interpretation, not a deviation.

**code_references:**
- `mealie/schema/household/group_shopping_list.py:216-238` — `ShoppingListSummary` definition.
- `mealie/schema/household/group_shopping_list.py:250-285` — `ShoppingListOut` definition.
- `mealie/schema/user/user.py:191-197` — `UserSummary` class.

### FR-10. Event bus additions
The `mealie/services/event_bus_service/event_types.py` **MUST** be extended with:
1. **Two new `EventTypes` enum members** at line 44 (after `shopping_list_deleted`):
   - `shopping_list_archived = auto()`
   - `shopping_list_unarchived = auto()`
2. **New payload class `EventShoppingListArchiveData(EventDocumentDataBase)`** after `EventShoppingListData` (lines 130-132):
   ```python
   class EventShoppingListArchiveData(EventDocumentDataBase):
       document_type: EventDocumentType = EventDocumentType.shopping_list
       # `operation` is inherited from EventDocumentDataBase (event_types.py:88-91); callers supply it
       # via the constructor as operation=EventOperation.update for both archive and unarchive dispatches.
       list_id: UUID4
       list_name: str | None = None
       household_id: UUID4
       archived_by_user_id: UUID4 | None = None
       item_count: int = 0
       total_estimated_amount: float | None = None
   ```
3. **Db model `GroupEventNotifierOptionsModel` (events.py:15-57)** gains two boolean columns after line 37: `shopping_list_archived` and `shopping_list_unarchived` (matching FR-3's migration).

**Field name decision (input §5 literal compliance — resolves review_v1_completeness COMP-C-002 and reverses v1 NC-3 default):** Use the input's exact field names `list_id` and `list_name` (NOT `shopping_list_id`/`shopping_list_name`). The new payload class lives in a new namespace dedicated to archive events; ambiguity with `meal_plan_id`/`cookbook_id` is contained within this payload's scope (the `document_type` field disambiguates entity type at the bus level). The asymmetry with existing `EventShoppingListData.shopping_list_id` is acceptable because:
- The input contract explicitly enumerates `list_id`/`list_name`.
- The new payload class is for new event types only; it does NOT replace `EventShoppingListData`.
- Webhook subscribers receive the full envelope including `event_type` and `document_type` for routing; field-name match against `list_id` keeps the integration contract literal.

**Payload field set** — the full `model_dump().keys()` is exactly `{"document_type", "operation", "list_id", "list_name", "household_id", "archived_by_user_id", "item_count", "total_estimated_amount"}` (8 keys). The first two are inherited from `EventDocumentDataBase` (`event_types.py:88-91`); the rest are declared on `EventShoppingListArchiveData`. **NO additional fields** — must NOT embed `User` objects, full `ShoppingListOut`, or any field that references entities in other households/groups. (Resolves review_v1_consistency C-002.)

**Operation value:** Both archive and unarchive dispatches use `operation=EventOperation.update` (consistent with the existing `shopping_list_updated` dispatch at `controller_shopping_lists.py:209/223`; archive/unarchive is conceptually a metadata update on the list).

**`item_count` semantics:** equals `len(shopping_list.list_items)` at the moment of state transition.

**`total_estimated_amount` semantics:** No price column exists on `ShoppingListItem` (verified by inspection of `mealie/db/models/household/shopping_list.py:51-98`). v1 sets this field to `None` unconditionally — it is a forward-compat hook for a future price-tracking feature. Coding phase MUST NOT compute the field from any existing column (no `quantity * price` synthesis; `quantity` is item count, `extras` is a free-form JSON not standardized).

**Dispatcher contract:** the controller MUST pass `group_id=result.shopping_list.group_id, household_id=result.shopping_list.household_id` (NOT `self.group_id`/`self.household_id`) so that `EventBusService.dispatch` (`event_bus_service.py:66-96`) targets exactly the owning household. Per-household subscriber filtering happens in `_get_listeners` / `_publish_event` (`event_bus_service.py:54-64`) — listeners are constructed scoped to `(group_id, household_id)` so cross-household leakage is impossible at the dispatch layer.

**code_references:**
- `mealie/services/event_bus_service/event_types.py:13-60` — `EventTypes` enum.
- `mealie/services/event_bus_service/event_types.py:14-22` — docstring mandating DB migration on enum changes.
- `mealie/services/event_bus_service/event_types.py:88-91` — `EventDocumentDataBase` declaring `document_type` and `operation` (the inherited base fields).
- `mealie/services/event_bus_service/event_types.py:130-132` — existing `EventShoppingListData` (the precedent for the new class).
- `mealie/db/models/household/events.py:35-37` — `shopping_list_{created,updated,deleted}` columns (insertion point at line 38).
- `mealie/services/event_bus_service/event_bus_service.py:54-64` — `_get_listeners` + `_publish_event` constructing tenant-scoped subscribers.
- `mealie/services/event_bus_service/event_bus_service.py:66-96` — `dispatch` method with per-household loop at lines 82-96.

### FR-11. Service layer — `archive_list` / `unarchive_list` + frozen pre-flight (HTTP-free)
The `mealie/services/household_services/shopping_lists.py` **MUST** be extended with:

1. **`ArchiveTransitionResult(NamedTuple)`** declared near the top of the file (after imports):
   ```python
   class ArchiveTransitionResult(NamedTuple):
       shopping_list: ShoppingListOut
       transitioned: bool
   ```

2. **`archive_list(self, list_id: UUID4, user_id: UUID4) -> ArchiveTransitionResult`** (NEW; insert after `create_one_list` at line 554):
   - Fetch the list: `shopping_list = self.shopping_lists.get_one(list_id)`. If `None`, raise `NoEntryFound()` (caught by `mealie_registered_exceptions` → 404).
   - If `shopping_list.archived_at is not None` (already archived), raise `ShoppingListIsArchivedError({list_id})` (caught by global handler → 409 with `shopping-list.archived.frozen`).
   - Validate "all items checked" precondition. The check **MUST** treat `None` as unchecked (per `ShoppingListItem.checked: FilterableColumn[bool | None]`, shopping_list.py:65): `any((item.checked is None or item.checked is False) for item in shopping_list.list_items)`. If True, raise `ShoppingListArchivePreconditionError({list_id})` (NEW typed exception — translated to 409 with `shopping-list.archive.unchecked-items` by the global handler).
   - Call `result = self.shopping_lists.archive(list_id, user_id)` (the new repo method from FR-7 §2).
   - Return `result`.

3. **`unarchive_list(self, list_id: UUID4) -> ArchiveTransitionResult`** (NEW; insert after `archive_list`):
   - Fetch: `shopping_list = self.shopping_lists.get_one(list_id)`. Raise `NoEntryFound()` if `None`.
   - Call `result = self.shopping_lists.unarchive(list_id)`.
   - Return `result` (controller inspects `result.transitioned` to decide event dispatch — see FR-4).

4. **`ensure_list_not_archived(self, list_id: UUID4) -> None`** (NEW; used by FR-6 Group B pre-flight):
   - Fetch: `shopping_list = self.shopping_lists.get_one(list_id)`. If `None`, raise `NoEntryFound()` (→ 404).
   - If `shopping_list.archived_at is not None`, raise `ShoppingListIsArchivedError({list_id})` (→ 409).
   - Otherwise return `None`.

5. **Global FastAPI exception handler** (NEW; in `mealie/routes/handlers.py`). Resolves review_v1_architecture M1 and review_v1_consistency C-004 (HTTP/i18n out of service):
   ```python
   from mealie.core.exceptions import ShoppingListIsArchivedError, ShoppingListArchivePreconditionError
   from mealie.lang.providers import Translator, get_locale_provider
   from mealie.schema.response import ErrorResponse

   def register_archive_handlers(app: FastAPI):
       @app.exception_handler(ShoppingListIsArchivedError)
       async def shopping_list_archived_handler(request: Request, exc: ShoppingListIsArchivedError):
           translator: Translator = get_locale_provider(request)
           return JSONResponse(
               status_code=status.HTTP_409_CONFLICT,
               content=ErrorResponse.respond(message=translator.t("shopping-list.archived.frozen")),
           )

       @app.exception_handler(ShoppingListArchivePreconditionError)
       async def archive_precondition_handler(request: Request, exc: ShoppingListArchivePreconditionError):
           translator: Translator = get_locale_provider(request)
           return JSONResponse(
               status_code=status.HTTP_409_CONFLICT,
               content=ErrorResponse.respond(message=translator.t("shopping-list.archive.unchecked-items")),
           )
   ```
   `register_archive_handlers(app)` is called in `mealie/app.py` (or wherever `register_debug_handler` is currently invoked — verified at `handlers.py:18`).

6. **Service stays HTTP-free.** None of `archive_list`, `unarchive_list`, `ensure_list_not_archived`, or the existing `bulk_create_items` / `bulk_update_items` / `bulk_delete_items` methods raise `HTTPException`. The bulk methods just propagate `ShoppingListIsArchivedError` from the repo (no try/except needed; the global handler catches it at the FastAPI boundary). This eliminates the translator-dependency-injection problem flagged in v1 SCN-1 and the layering violation flagged in review_v1_consistency C-004.

**code_references:**
- `mealie/services/household_services/shopping_lists.py:37-43` — `ShoppingListService.__init__` (unchanged — no translator added).
- `mealie/services/household_services/shopping_lists.py:154-223` — `bulk_create_items` (unchanged — propagates `ShoppingListIsArchivedError` raised by `RepositoryShoppingListItem.create_many`).
- `mealie/services/household_services/shopping_lists.py:225-310` — `bulk_update_items` (unchanged — same propagation).
- `mealie/services/household_services/shopping_lists.py:312-321` — `bulk_delete_items` (unchanged — same propagation).
- `mealie/services/household_services/shopping_lists.py:541-554` — `create_one_list` (insertion point for new methods at line 555+).
- `mealie/routes/handlers.py:1-32` — existing `register_debug_handler`; `register_archive_handlers` lives in the same file.
- `mealie/core/exceptions.py:73-83` — `mealie_registered_exceptions` mapping (existing `NoEntryFound` → 404 wiring; no change needed for `NoEntryFound` raises in the new service methods).

### FR-12. Multitenant isolation
Cross-household and cross-group operations on shopping lists **MUST** continue to return 404 (NOT 403) via the existing `HouseholdRepositoryGeneric._filter_builder` mechanism PLUS the tenant-scoped WHERE clauses in the new `archive` / `unarchive` repo methods (FR-7 §2/§3 — resolves review_v1_architecture H2):
- `GET /api/households/shopping/lists?archived=true` from household H2 MUST NOT include H1's archived lists.
- `POST /api/households/shopping/lists/{H1_list.id}/archive` from household H2 MUST return `404 NOT FOUND` (because `self.shopping_lists.get_one(list_id)` in `archive_list` returns `None` when the list's `user.household_id != self.household_id`, AND the repo's `archive` method's UPDATE WHERE clause would not match anyway).
- Same for `/unarchive`, `PUT /lists/{id}`, item mutations targeting another household's list.
- Event payloads for archive/unarchive MUST contain only the owning household's data (FR-10 payload class enforces this by construction).

`AGR-8` from `consolidated.md` is locked: the new `RepositoryShoppingList.page_all` override composes the archived predicate via `.where(...)` AFTER `_filter_builder` injects `group_id`+`household_id`, preserving isolation for all `archived` values.

**code_references:**
- `mealie/repos/repository_generic.py:94-102` — `_filter_builder`.
- `mealie/repos/repository_generic.py:156-179` — `get_one` tenant-scoped pattern.
- `mealie/repos/repository_generic.py:505-523` — `HouseholdRepositoryGeneric` ctor.
- `mealie/routes/_base/base_controllers.py:199-214` — `publish_event` accepts explicit `group_id`/`household_id`.
- `mealie/services/event_bus_service/event_bus_service.py:54-64` — tenant-scoped listener construction.
- `mealie/services/event_bus_service/event_bus_service.py:66-96` — `dispatch` filters subscribers per household.

### FR-13. i18n
The `mealie/lang/messages/en-US.json` **MUST** gain a new top-level `shopping-list` key with the following nested structure:
```jsonc
"shopping-list": {
  "archive": {
    "unchecked-items": "Cannot archive a shopping list while items remain unchecked"
  },
  "archived": {
    "frozen": "This shopping list is archived and cannot be modified. Unarchive it first."
  }
}
```
- Backend `Translator.t("shopping-list.archive.unchecked-items")` resolves to the en-US string above.
- Backend `Translator.t("shopping-list.archived.frozen")` resolves to the en-US string above.

**Explicit divergence from input §7 "lang/messages/ all existing language files" — review_v1_completeness COMP-C-003 rejected with binding rationale.** All other locale files (`af-ZA.json` through `zh-TW.json`, 41 files per directory listing) **MUST NOT** be modified. This is a hard repository policy stated in `Downloads/mealie/.github/copilot-instructions.md` ("Only modify `en-US` locale files when adding new translation strings — other locales are managed via Crowdin and **must never be modified** (PRs modifying non-English locales will be rejected)"). Adding fallback values in non-English locales would cause the PR to be rejected by CI. The input requirement is reinterpreted as "at minimum en-US, with Crowdin filling in the rest on its normal cadence". Crowdin auto-detects new English keys and surfaces them for translation; no manual cross-locale fan-out is required or permitted in the same PR.

**code_references:**
- `mealie/lang/messages/en-US.json:1-95` — current file (4109 bytes, 9 top-level keys, no `shopping-list` namespace).
- `mealie/lang/messages/en-US.json:46-53` — existing `exceptions` namespace (parallel pattern).
- `Downloads/mealie/.github/copilot-instructions.md` — repository-policy citation: "Only `en-US` locale files when adding new translation strings — other locales are managed via Crowdin and must never be modified".

### FR-14. Scheduled cleanup compatibility
The `delete_old_checked_list_items` task **MUST** skip archived lists to prevent the new repo-level guard from raising `ShoppingListIsArchivedError` from a cron context (which has no HTTP translation layer).
- Modify line 69 of `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py`:
  - Current: `shopping_list_data = household_repos.group_shopping_lists.page_all(PaginationQuery(page=1, per_page=-1))`.
  - New: `shopping_list_data = household_repos.group_shopping_lists.page_all(PaginationQuery(page=1, per_page=-1), archived=ArchivedFilter.exclude)`.
- Import `ArchivedFilter` from `mealie.schema.household.group_shopping_list`.

**code_references:**
- `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py:54-75` — `delete_old_checked_list_items` task.
- `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py:69` — exact line to modify.

### FR-15. Codegen artifacts (auto-regenerated; not hand-edited)
After all backend changes land, `task dev:generate` **MUST** regenerate:
- `frontend/app/lib/api/types/household.ts` — new `archivedAt?: string | null` and `archivedBy?: UserSummary | null` fields on `ShoppingListSummary` (currently lines 735-748) and `ShoppingListOut` (currently lines 673-687).
- `frontend/app/lib/api/types/events.ts` — new enum members + `EventShoppingListArchiveData` interface.
- `mealie/schema/household/__init__.py` — re-export of `ArchivedFilter`.
- `tests/utils/api_routes/__init__.py` — new helpers `households_shopping_lists_item_id_archive(id)`, `households_shopping_lists_item_id_unarchive(id)`.

PR **MUST NOT** hand-edit any of these files (CI will detect drift and reject).

**code_references:**
- `frontend/app/lib/api/types/household.ts:673-687` — current `ShoppingListOut` shape.
- `frontend/app/lib/api/types/household.ts:735-748` — current `ShoppingListSummary` shape.
- `tests/utils/api_routes/__init__.py:114` — current `households_shopping_lists` constant.

---

## 4. Success criteria (measurable acceptance)

| # | Criterion | Measurement |
|---|-----------|-------------|
| SC-1 | **Archive idempotency** | Calling `POST /archive` on an already-archived list returns 409 (not 200, not 500). Verified by integration test asserting `response.status_code == 409` AND `response.json()["detail"]["message"] == "This shopping list is archived and cannot be modified. Unarchive it first."`. |
| SC-2 | **All 11 frozen route variants return 409 with i18n message** | Integration tests cover each of the 11 frozen route variants in FR-6 (Group A: PUT list, POST item, POST items/create-bulk, PUT item, PUT items, DELETE item, DELETE items — 7 tests; Group B: PUT label-settings, POST /recipe, POST /recipe/{rid} deprecated, POST /recipe/{rid}/delete — 4 tests). Each test asserts `response.status_code == 409` AND `response.json()["detail"]["message"] == "This shopping list is archived and cannot be modified. Unarchive it first."` AND that no rows in `shopping_lists`/`shopping_list_items`/`shopping_list_multi_purpose_label_settings`/`shopping_list_recipe_references` were modified (compare `updated_at` and row counts before and after). Count: **11 distinct test methods**. (Resolves review_v1_consistency C-006: title now matches measurement.) |
| SC-3 | **Event payload field-set is exactly the spec'd 8-key set** | A test using `monkeypatch.setattr` on `EventBusService.dispatch` captures dispatched events; asserts `set(payload.model_dump().keys()) == {"document_type", "operation", "list_id", "list_name", "household_id", "archived_by_user_id", "item_count", "total_estimated_amount"}` for both `EventTypes.shopping_list_archived` and `EventTypes.shopping_list_unarchived`. Also asserts `payload.operation == EventOperation.update`. No additional keys (no `User` object, no `list_items` collection). |
| SC-4 | **Event payload household isolation** | A test where user U1 in household H1 archives list L1; a captured `EventBusService.dispatch` shows `household_id` in the dispatch args equals H1.id (NOT H2.id, NOT None). Asserted via `captured[0]["household_id"] == H1.id`. |
| SC-5 | **Default GET filter correctness** | Three integration tests: (a) given one active + one archived list in H1, `GET /api/households/shopping/lists` returns 1 item with the active list's id; `total == 1`. (b) `GET /api/households/shopping/lists?archived=true` returns 1 item with the archived list's id; `total == 1`. (c) `GET /api/households/shopping/lists?archived=all` returns 2 items containing both ids. |
| SC-6 | **Multitenant isolation — same-group different-household (GET + mutations)** | Using `h2_user` fixture: H2 user calls `GET /api/households/shopping/lists?archived=true`, response items DO NOT contain any list owned by H1. H2 user calls `POST /api/households/shopping/lists/{H1_list.id}/archive` → 404. H2 user calls `POST /api/households/shopping/lists/{H1_list.id}/unarchive` → 404. H2 user calls `PUT /api/households/shopping/lists/{H1_list.id}` → 404. H2 user calls `POST /api/households/shopping/items` with `shopping_list_id == H1_list.id` → 404. **5 sub-assertions in 1 test method.** |
| SC-7 | **Multitenant isolation — cross-group (GET via parametrized framework)** | `ArchivedShoppingListsTestCase` registered in `tests/multitenant_tests/test_multitenant_cases.py` `all_cases`; parametrized `test_multitenant_cases_get_all` automatically asserts that `user_two` (different group) sees an empty list when `user_one`'s group has archived lists seeded. |
| SC-8 | **i18n key presence** | A unit test asserts `Translator(locale="en-US").t("shopping-list.archive.unchecked-items") == "Cannot archive a shopping list while items remain unchecked"` and `Translator(locale="en-US").t("shopping-list.archived.frozen") == "This shopping list is archived and cannot be modified. Unarchive it first."`. Both keys MUST be resolvable (no `KeyError`). |
| SC-9 | **Migration reversibility** | Run `alembic upgrade head` then `alembic downgrade -2` (down past both new migrations); database table `shopping_lists` no longer has `archived_at`/`archived_by_user_id` columns; `group_events_notifier_options` no longer has `shopping_list_archived`/`shopping_list_unarchived` columns. All existing rows preserved. Verified by CI matrix on SQLite + PostgreSQL. |
| SC-10 | **Test count by category** | At least: **5 unit tests** (`tests/unit_tests/` covering `archive_list` success, `archive_list` 409 unchecked-items, `archive_list` 409 already-archived, `unarchive_list` no-op success WITHOUT event dispatch, `RepositoryShoppingList.page_all` ArchivedFilter branches); **≥14 integration tests** in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` covering US-1..US-7 + US-10 (11 are the FR-6 frozen-route tests counted under SC-2); **≥5 multitenant tests** (1 new `case_shopping_list_archive.py` registered in `all_cases` + 4 explicit assertions in new `test_shopping_list_archive_household.py` for SC-6 / SC-13). |
| SC-11 | **Backward compatibility — existing tests pass** | All currently-passing tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` (1113 lines, 7+ baseline test methods listed in `consolidated.md` §1.2 T1) and `test_group_shopping_list_items.py` (623 lines) continue to pass without modification. Verified via `task py:test`. |
| SC-12 | **Scheduler does not regress** | Unit test for `delete_old_checked_list_items`: given a household with 1 archived list containing 150 checked items AND 1 active list with 150 checked items, after the task runs, archived list still has 150 items, active list has 100 items (MAX_CHECKED_ITEMS). No `HTTPException`, no `ShoppingListIsArchivedError` raised; logs are clean. |
| SC-13 | **Multitenant isolation — cross-group archive/unarchive returns 404** | New integration test in `tests/multitenant_tests/test_shopping_list_archive_household.py` named `test_cross_group_archive_returns_404`: g2_user (different group) calls `POST /api/households/shopping/lists/{g1_list.id}/archive` → 404; symmetric for `/unarchive`. Plus `test_cross_household_archive_returns_404`: h2_user (same group, different household) calls archive/unarchive on H1's list → 404. Together these enumerate all three multitenant scenarios required by input §8: (1) same-group GET isolation (SC-6), (2) cross-group GET isolation (SC-7), (3) cross-household/cross-group archive 404 (SC-13). Resolves review_v1_completeness COMP-H-001. |
| SC-14 | **Unarchive no-op does NOT dispatch event** | A test where U1 calls `POST /unarchive` on an already-active list `L_active`: asserts `response.status_code == 200`, `response.json()["archivedAt"] is None`; asserts that `EventBusService.dispatch` was NOT called for `EventTypes.shopping_list_unarchived` during the request (verified via `monkeypatch` capture). Resolves review_v1_consistency C-003. |
| SC-15 | **`archived_by_user_id ON DELETE SET NULL` round-trip** | Integration test: U1 archives L1 (`archived_by_user_id == U1.id`). Admin deletes U1's user account. Re-fetch L1 via `GET /lists/{L1.id}`. Assert `response.status_code == 200`, `archived_at is not None` (list is still archived), `archived_by is None` (FK cleared). Verifies the loosened invariant from FR-1 and the `ondelete="SET NULL"` in FR-2. Resolves review_v1_completeness COMP-H-002. |

---

## 5. Edge cases (≥6 required; this spec covers 9)

### EC-1. Archive an empty list (no items)
**Scenario.** `ShoppingList L1` exists with `list_items == []`.
**Expected.** `POST /archive` succeeds (the "all items checked" precondition is vacuously true). `L1.archived_at` is set; event dispatched with `item_count == 0` and `total_estimated_amount: None`.
**Why this matters.** Without explicit handling, `all(item.checked for item in [])` evaluates True (correct), but the event payload's `total_estimated_amount` and downstream consumers might assume non-empty.

### EC-2. Archive a list where exactly 1 item is unchecked, the rest are checked
**Scenario.** `L1` has 9 items with `checked=True`, 1 with `checked=False`.
**Expected.** `POST /archive` returns 409 with `shopping-list.archive.unchecked-items` message. List is NOT archived.
**Why this matters.** Boundary case for the precondition logic; ensures the "any unchecked" check is short-circuiting correctly.

### EC-2b. Archive a list where 1 item has `checked = None` (NULL in DB)
**Scenario.** `L1` has 9 items with `checked=True`, 1 with `checked=None`.
**Expected.** `POST /archive` returns 409 — NULL is treated as unchecked (per the precondition `any((item.checked is None or item.checked is False) for item in shopping_list.list_items)`).
**Why this matters.** `ShoppingListItem.checked: FilterableColumn[bool | None]` (`shopping_list.py:65`) allows NULL. The precondition must treat NULL as unchecked to be safe.

### EC-3. Unarchive a non-archived list (no event dispatched)
**Scenario.** `L1` has `archived_at IS NULL`.
**Expected.** `POST /unarchive` returns **200 OK** with the list unchanged (idempotent no-op). NO event is dispatched (no state change — the controller inspects `ArchiveTransitionResult.transitioned == False` and skips `publish_event`).
**Why this matters.** Distinguishes from "archive an already-archived list" which IS a 409 — the asymmetry is intentional: archive failure signals "you're trying to re-archive" (potentially a programming error worth surfacing), while unarchive on an active list is benign cleanup. Verified by SC-14.

### EC-4. Archive cascade — downstream consumers
**Scenario.** Multiple downstream consumers of shopping lists may exist.
**Inventory and expected behavior:**
- **Cookbook** — Cookbooks are recipe collections (`mealie/db/models/household/cookbook.py`, `mealie/repos/repository_cookbooks.py`, `mealie/routes/households/controller_cookbooks.py`). There is NO `mealie/services/household_services/cookbook_service.py` (verified by directory listing of `mealie/services/household_services/`). Cookbooks do NOT consume shopping lists. ✅
- **Meal plan** — Does not consume shopping lists; meal-plan-to-shopping-list flows one direction (meal plan generates items). Reading: `mealie/routes/households/controller_mealplan.py` does not reference `ShoppingList`. ✅
- **`delete_old_checked_shopping_list_items.py` scheduler** — Currently iterates ALL shopping lists including archived ones (`scheduler/tasks/delete_old_checked_shopping_list_items.py:69`); without FR-14 fix, would trigger `ShoppingListIsArchivedError` from the repo guard in a cron context. ⚠️ Fix mandated in FR-14.
- **Backup/export (`mealie/services/backups_v2/`)** — Dumps full ORM rows; the new columns automatically flow into the backup. Restore re-populates them. No code change needed; verified by the existing backup version-bump tests under `tests/unit_tests/services_tests/backup_v2_tests/`. ✅
- **Frontend offline PWA queue (`frontend/app/composables/use-shopping-list-item-actions.ts`)** — Will receive 409s on flush if the user archived a list while items were queued offline. Recommended (out of v1 scope): drop the failing op rather than retry forever. Flagged in self-concerns. ⚠️

### EC-5. Backup/export of archived lists
**Scenario.** Operator runs `POST /api/admin/backups` after some lists have been archived.
**Expected.** Backup contains all `shopping_lists` rows including `archived_at` + `archived_by_user_id` columns. Restore re-creates them with the same archived state.
**Verification.** `task py:test -- tests/unit_tests/services_tests/backup_v2_tests/` continues to pass (verified path; corrected from v1's incorrect `tests/integration_tests/backup_v2_tests/`). No new test required for v1 (the existing backup-roundtrip test inherently covers new columns).

### EC-6. Admin override / force unarchive
**Scenario.** Per input §三环节考察点: "是否需要 admin 强制 unarchive".
**Expected (v1).** NOT in v1 scope. The existing `BaseAdminController` (`mealie/routes/_base/base_controllers.py:175-189`) clears household scoping, so an admin would naturally see ALL households' archived lists via `GET /api/admin/...` routes. But no admin-specific archive/unarchive endpoint is added in v1.
**Follow-up.** Tracked under `self_concerns` for v2 consideration. The current `archive_one`/`unarchive_one` endpoints inherit `BaseCrudController` behavior; an admin user calling the regular endpoint succeeds only if they belong to the owning household. Force-unarchive across households is a separate feature.

### EC-7. Two users in the same household call `POST /archive` concurrently
**Scenario.** U1 and U2 both belong to H1; both `POST /api/households/shopping/lists/{L1.id}/archive` at the same time when L1 is active.
**Expected.** One succeeds (race winner; sets `archived_by_user_id` to that user). The other receives 409 + `shopping-list.archived.frozen` because by the time `RepositoryShoppingList.archive` runs its pre-fetch (FR-7 §2), it sees `archived_at IS NOT NULL` and raises `ShoppingListIsArchivedError`.
**Risk if not handled.** Without the "already archived" check inside `archive`, both writes would commit and the second silently overwrites `archived_by_user_id`. FR-7 §2 requires the guard. Out of scope for v1: add a unique partial index `WHERE archived_at IS NULL` for stronger DB-level guarantees.

### EC-8. User who archived a list is deleted (FK `SET NULL`)
**Scenario.** User U1 archives list L1 (`archived_by_user_id == U1.id`); later U1's account is deleted.
**Expected.** The `archived_by_user_id` FK is declared with `ondelete="SET NULL"` in BOTH the SQLAlchemy model (FR-1: `ForeignKey("users.id", ondelete="SET NULL")`) AND the Alembic migration (FR-2: `batch_op.create_foreign_key(..., ondelete="SET NULL")`). User deletion succeeds. L1 retains `archived_at IS NOT NULL` (still archived) and gets `archived_by_user_id IS NULL`.
**Consistency.** This is the loosened invariant codified in FR-1: `archived_at IS NULL ⇒ archived_by_user_id IS NULL` (one-way only). Archived rows MAY have `archived_by_user_id IS NULL`. Verified by SC-15.

### EC-9. Frozen Group B routes — atomic pre-flight semantics
**Scenario.** L1 is archived. User U1 calls `POST /api/households/shopping/lists/{L1.id}/recipe` with a payload that would add 5 new ingredients to the list.
**Expected.** The controller's first action (FR-6 #9) is `self.service.ensure_list_not_archived(L1.id)`, which raises `ShoppingListIsArchivedError` (mapped to 409 by the global handler). The handler body — including `self.service.add_recipe_ingredients_to_list(...)` which would call `bulk_create_items` AND `self.shopping_lists.update(...)` — never executes. No new rows in `shopping_list_items`, `shopping_list_recipe_references`. No mutation to `shopping_lists.recipe_references`. **Atomic pre-flight semantics preserved** — resolves v1 SCN-2 partial-failure concern and review_v1_completeness COMP-H-003.
**Verification.** SC-2 row-count assertion after each Group B test confirms zero mutations occurred.

---

## 6. `needs_clarification` (genuine input-vs-code conflicts)

These are points where the input spec is silent or ambiguous AND the existing code creates a constraint that must be resolved before coding. Each item lists the specific question, the discovered conflict, and the resolution.

### NC-1. Frozen scope on Group B routes (label-settings, recipe-add, recipe-remove) — RESOLVED IN v2
- **Question.** Should `PUT /api/households/shopping/lists/{id}/label-settings` and the three recipe-management routes also return 409 on archived lists?
- **Conflict (original).** Spec §3 enumerated exactly 4 routes; the label-settings route bypasses `RepositoryShoppingList.update`, and recipe routes have partial-mutation paths.
- **v2 Resolution.** **FREEZE ALL list-mutating routes** (FR-6 Group B). Service-layer pre-flight `ensure_list_not_archived(item_id)` runs at the top of each Group B controller handler before any write, guaranteeing atomic-pre-flight semantics. This rescinds v1's "v1 freezes ONLY 4 routes" position per review_v1_architecture C1, review_v1_completeness COMP-H-003, and review_v1_consistency C-005.
- **Status.** **NOT BLOCKING** — resolved in spec; no clarification still needed.

### NC-2. Scope of "household 内成员" rule — admin-only or any member?
- **Question.** Input §2 says "household 内成员" (household member) for the archive/unarchive endpoints. Does "member" mean any user belonging to the household (including non-admins), or only an admin within the household?
- **Conflict.** Existing CRUD routes on `ShoppingListController` (`controller_shopping_lists.py:159-229`) use the default `BaseCrudController` permission (any authenticated user whose household_id matches), NOT `BaseAdminController`. The spec uses the same phrase "household 内成员" for the simpler routes too, so the consistent reading is "any household member".
- **Resolution.** Any authenticated household member can archive/unarchive. No admin role required. Consistent with the existing routes that create/update/delete shopping lists.

### NC-3. Exact event payload field names — `list_id` vs `shopping_list_id` — RESOLVED IN v2
- **Question.** Spec §5 lists payload fields as `list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`. The existing `EventShoppingListData` uses `shopping_list_id`. Should the new payload use the spec's exact `list_id`/`list_name` or the existing convention?
- **Conflict.** Spec text vs existing code naming. JSON consumers of the event bus (apprise notifiers, webhooks) might pattern-match either name.
- **v2 Resolution.** **Use the input's exact field names `list_id` and `list_name`** (literal input compliance). The new payload class lives in a new dedicated namespace; the existing `EventShoppingListData.shopping_list_id` is unaffected. Resolves review_v1_completeness COMP-C-002. (v1's "use shopping_list_id" default was REVERSED.)
- **Status.** **NOT BLOCKING** — resolved in FR-10.

### NC-4. `total_estimated_amount` semantics
- **Question.** Spec §5 says payload includes `total_estimated_amount (如有)` (if available). No `price` / `cost` / `amount` column exists on `ShoppingListItem` today.
- **Conflict.** Field is requested in the contract but no source data exists.
- **Resolution.** Field defaults to `None`. Forward-compat hook for a future price-tracking feature. NOT computed from any existing column (no per-item price exists; `ShoppingListItem.quantity` is the count, `ShoppingListItem.extras` is a free-form JSON that COULD contain price but is per-deployment convention). Coding phase MUST NOT attempt to compute this field in v1.

### NC-5. `ON DELETE` behavior for `archived_by_user_id` FK — RESOLVED IN v2
- **Question.** When the user who archived a list is deleted, what happens to `archived_by_user_id`?
- **v2 Resolution.** `ON DELETE SET NULL` is declared explicitly in BOTH FR-1 (SQLAlchemy model: `ForeignKey("users.id", ondelete="SET NULL")`) AND FR-2 (Alembic migration: `batch_op.create_foreign_key("fk_shopping_lists_archived_by_user_id", "users", ["archived_by_user_id"], ["id"], ondelete="SET NULL")`). The FR-1 invariant is loosened to one-way (`archived_at IS NULL ⇒ archived_by_user_id IS NULL`) to accommodate the SET NULL behavior. Verified by SC-15 integration test. Resolves review_v1_architecture H1, review_v1_consistency C-001, review_v1_completeness COMP-H-002.
- **Status.** **NOT BLOCKING** — resolved.

---

## 7. Self-concerns (residual uncertainty)

These are concerns the spec author has about choices made — not blockers, but worth surfacing to the design/coding/CR phases.

### SCN-1. Translator dependency injection into `ShoppingListService` — RESOLVED IN v2
- **v1 concern.** FR-11 required `ShoppingListService.bulk_*` methods to call `self.t(...)` for i18n translation, but the service constructor had no `Translator`.
- **v2 Resolution.** Translation moved to a global FastAPI exception handler in `mealie/routes/handlers.py` (FR-11 §5). `ShoppingListService` stays HTTP-free and translator-free. Resolves review_v1_architecture M1 and review_v1_consistency C-004. **No residual concern.**

### SCN-2. Partial-mutation failure path for recipe-add/recipe-remove routes — RESOLVED IN v2
- **v1 concern.** Recipe routes could create items then fail on the list-level update with 409, leaving partial mutation.
- **v2 Resolution.** Service-layer pre-flight `ensure_list_not_archived(item_id)` runs at the top of each Group B controller handler (FR-6 #8-#11) BEFORE any write. Atomic-pre-flight semantics. **No residual concern.**

### SCN-3. `RepositoryShoppingListItem` constructor — passing the parent repo — RESOLVED IN v2
- **v2 Resolution.** Constructor injection of `parent_repo: RepositoryShoppingList` is the single normative wiring per FR-8 (no "or equivalent"). Factory `repository_factory.py:323-332` is updated to pass `parent_repo=self.group_shopping_lists`. **No residual concern.**

### SCN-4. `archived_by` schema serialization extra cost
- **Concern.** Adding `archived_by: UserSummary | None` to `ShoppingListSummary.loader_options` adds one more `selectinload` per list. For households with hundreds of lists, this is a small N+1 risk. The existing `loader_options` at line 237 already eager-loads `User` via `joinedload(ShoppingList.user).load_only(User.household_id, User.group_id)`; the new `archived_by` eager-load is a separate join because it targets a different FK.
- **Risk.** Slight performance regression in `GET /lists` when many lists are archived.
- **Mitigation.** Only loaded eagerly when needed. Since `archived_by` defaults to None and the relationship FK is also nullable, the join effectively becomes a LEFT OUTER JOIN that's nearly free for active-list-heavy responses. Performance test in v1 not required; benchmark in v2 if reports surface.

### SCN-5. `register_archive_handlers` registration ordering in `mealie/app.py`
- **Concern.** FR-11 §5 introduces a global FastAPI exception handler. The registration call (`register_archive_handlers(app)`) MUST happen during app initialization. The existing `register_debug_handler(app)` is invoked in `mealie/app.py` (per `handlers.py:18` showing it's the only other handler-registration function).
- **Risk.** If a future contributor adds another handler-registration function and forgets to call it, the new exception types will fall through to FastAPI's default 500 handler, producing opaque errors.
- **Mitigation.** Add an integration smoke test that asserts a fresh `archive` request on an archived list returns 409 (not 500). SC-1 already covers this.

---

## 8. Cross-cutting compliance checklist (for coding phase)

This checklist is derived from `Downloads/mealie/.github/copilot-instructions.md` and is recapped here for completeness:

- [ ] All Python commands use `uv run …` (not raw `python` / `pip`).
- [ ] Run `task py:check` (Ruff format + lint + mypy + pytest) before commit.
- [ ] Run `task dev:generate` after any Pydantic schema or `EventTypes` change; commit the regenerated files.
- [ ] Run `task ui:check` if any UI-adjacent file changes (none expected for backend-only v1).
- [ ] All new SQLAlchemy columns use `FilterableColumn[…]` wrapper (per GHSA-8m57-7cv5-rjp8 / FR-1).
- [ ] Migrations use `op.batch_alter_table(...)` for SQLite + PostgreSQL portability.
- [ ] Only `mealie/lang/messages/en-US.json` is touched among locale files; all other locales are Crowdin-managed.
- [ ] Repository methods inherit/call `_filter_builder` to preserve multitenancy scoping (FR-7 §2/§3 archive/unarchive UPDATEs explicitly include the tenant clause in their WHERE).
- [ ] Service methods stay free of HTTP concerns; HTTP translation lives in the global exception handler at `mealie/routes/handlers.py` (FR-11 §5).
- [ ] No hand-edits to `frontend/app/lib/api/types/`, `mealie/schema/*/__init__.py`, or `tests/utils/api_routes/__init__.py` — all autogen.
- [ ] PR title follows Conventional Commits: `feat: add archive lifecycle to shopping lists`.
- [ ] PR description includes release notes and ADR-style rationale for repo-layer guard placement.
