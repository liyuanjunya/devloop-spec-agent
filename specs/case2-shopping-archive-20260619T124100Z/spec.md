# Spec — Case 2: Shopping List Archive (Mealie)

> **Generated:** 2026-06-19
> **Repo:** `C:\Users\v-liyuanjun\Downloads\mealie\` @ `4a099c16`
> **Selected approach:** Repository-level frozen guard (`approach/selected.md`)
> **Input source:** `input.md` §1–§8
> **Status:** v1, ready for design phase

---

## 1. Summary

Add an "archive" lifecycle to Mealie's `ShoppingList` entity. Archived lists are hidden from the default list view, are revealed via a new `?archived=` query parameter, become **immutable** (all mutating endpoints on the list and its items return HTTP 409 with i18n key `shopping-list.archived.frozen`), and emit dedicated `ShoppingListArchived` / `ShoppingListUnarchived` events on the existing event bus. The implementation centralises both the default-exclude filter AND the frozen-state guard in the repository layer (per input §7) and remains fully tenancy-isolated via the existing `HouseholdRepositoryGeneric._filter_builder` (`mealie/repos/repository_generic.py:94-102`).

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

### US-5 (P1) — Frozen-state: PUT list / POST item / PUT item / DELETE item → 409
**As** a household member  
**I want** every mutating operation on an archived list (or its items) to be rejected with a clear "frozen" error  
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
**Then** each response is `409 CONFLICT` with body `{"detail": {"message": "This shopping list is archived and cannot be modified. Unarchive it first.", "error": true, "exception": null}}` (en-US value of i18n key `shopping-list.archived.frozen`);  
**And** no rows in `shopping_lists` or `shopping_list_items` are modified;  
**And** `L1.updated_at` and `I1.updated_at` are unchanged.

### US-6 (P1) — Unarchive restores mutable state
**As** a household member  
**I want** to "unarchive" a list back to mutable state  
**So that** I can correct mistakes or repurpose an archived list.

**Given** `ShoppingList L1` has `archived_at IS NOT NULL`,  
**When** I `POST /api/households/shopping/lists/{L1.id}/unarchive`,  
**Then** the response is `200 OK` with `ShoppingListOut` where `archived_at == null` and `archived_by == null`;  
**And** the row has `archived_at IS NULL` and `archived_by_user_id IS NULL`;  
**And** the same `L1` now appears in default `GET /lists` results;  
**And** subsequent `PUT /lists/{L1.id}`, `POST /items` (targeting L1), `PUT /items/{I.id}`, and `DELETE /items/{I.id}` succeed (no 409);  
**And** one `EventTypes.shopping_list_unarchived` event is dispatched.

### US-7 (P1) — Event bus dispatches with correct payload
**As** a webhook/notifier subscriber configured for shopping-list-archive events in my household  
**I want** to receive an event when an archive/unarchive occurs in my household, with exactly the spec'd payload fields  
**So that** I can integrate downstream systems (analytics, exports) without leaking other tenants' data.

**Given** I am subscribed via `GroupEventNotifier` with `shopping_list_archived = true` for household H1,  
**When** any user in H1 archives a list,  
**Then** exactly one `Event` arrives at my subscriber with `event_type == EventTypes.shopping_list_archived`, `document_data` of type `EventShoppingListArchiveData` containing **exactly** fields `{document_type, operation, shopping_list_id, shopping_list_name, household_id, archived_by_user_id, item_count, total_estimated_amount}` and NO additional fields;  
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
**And when** I `POST /api/households/shopping/lists/{L3.id}/archive`, **Then** the response is `404 NOT FOUND`;  
**And** symmetric behavior for users in H2 (cannot see/modify L1 or L3) and H3 (cannot see/modify L1 or L2).

### US-9 (P2) — Schema is backward-compatible
**As** an existing API consumer (e.g., the offline-PWA queue or an external integration)  
**I want** the existing `ShoppingListOut` / `ShoppingListSummary` shapes to remain backward-compatible  
**So that** my pre-feature code continues to work without changes.

**Given** I am an existing consumer that does NOT read `archived_at` / `archived_by`,  
**When** I `GET /api/households/shopping/lists` on a database where no list has been archived,  
**Then** the response items have `archived_at: null` and `archived_by: null`, which my consumer silently ignores;  
**And** existing tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` (1113 lines, 7 baseline test methods) continue to pass unchanged.

### US-10 (P2) — Scheduled cleanup respects frozen state
**As** a system operator  
**I want** the existing `delete_old_checked_shopping_list_items` scheduled task to skip archived lists  
**So that** archived history is preserved against automatic trimming.

**Given** the scheduler runs (per `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py:54-75`) and one household has both an active list with >100 checked items and an archived list with >100 checked items,  
**When** the task completes,  
**Then** the active list's old checked items are trimmed (existing behavior);  
**And** the archived list is left fully intact (no items deleted);  
**And** no `409` exceptions are logged from the scheduler context.

---

## 3. Functional requirements

> Every `code_references` line range below was verified by direct file inspection. Verb tense: **MUST** = required, **SHOULD** = recommended, **MAY** = optional.

### FR-1. Data model — `ShoppingList` extension
The `mealie.db.models.household.shopping_list.ShoppingList` model **MUST** gain two new columns and one relationship:
- `archived_at: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime, index=True)` — default NULL, NULL = active.
- `archived_by_user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)` — default NULL.
- `archived_by: Mapped[Optional["User"]] = orm.relationship("User", foreign_keys=[archived_by_user_id])` — disambiguating against the existing `user` relationship at line 156.
- The existing `user` relationship at line 156 **MUST** be updated to specify `foreign_keys=[user_id]` for SQLAlchemy disambiguation.
- The pair MUST satisfy invariant: `archived_at IS NULL ⇔ archived_by_user_id IS NULL` (enforced at the service layer; not a DB CHECK constraint to preserve cross-DB portability, though a CHECK constraint MAY be added later).

**code_references:**
- `mealie/db/models/household/shopping_list.py:147-181` — current `ShoppingList` class declaration (`__tablename__`, `id`, `group_id`, `user`, `user_id`, `name`, `list_items`, `recipe_references`, `label_settings`, `extras`); new columns insert between line 158 (`name`) and line 159 (`list_items`).
- `mealie/db/models/recipe/recipe.py:145,147` — `date_updated`/`last_made` exact NaiveDateTime pattern to mirror.
- `mealie/db/models/household/mealplan.py:67` — `user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)` exact pattern to mirror for `archived_by_user_id`.

### FR-2. Alembic migration (a) — `shopping_lists` columns
A new alembic migration file under `mealie/alembic/versions/` **MUST** add the two columns to the `shopping_lists` table.
- Use `op.batch_alter_table("shopping_lists")` for SQLite + PostgreSQL portability.
- `archived_at`: `sa.Column("archived_at", mealie.db.migration_types.NaiveDateTime(), nullable=True)`.
- `archived_by_user_id`: `sa.Column("archived_by_user_id", mealie.db.migration_types.GUID(), nullable=True)` + `batch_op.create_foreign_key("fk_shopping_lists_archived_by_user_id", "users", ["archived_by_user_id"], ["id"])` + `batch_op.create_index("ix_shopping_lists_archived_by_user_id", ["archived_by_user_id"])`.
- `batch_op.create_index("ix_shopping_lists_archived_at", ["archived_at"])`.
- `down_revision` **MUST** chain off the current head revision in `mealie/alembic/versions/` (currently `2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py` per directory listing; the actual head is whatever is latest at migration generation time — confirm via `task py:migrate` autogeneration).
- `downgrade()` **MUST** drop both columns and the FK and the indexes so that DB rollback succeeds.
- Existing rows **MUST** have `archived_at = NULL` and `archived_by_user_id = NULL` (no `server_default` needed; NULL is the default for nullable columns).

**code_references:**
- `mealie/alembic/versions/2025-09-10-19.21.48_1d9a002d7234_add_referenced_recipe_to_ingredients.py:21-30` — exact `batch_alter_table → add_column → create_index → create_foreign_key` template (nullable GUID FK column pattern).
- `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_*.py:183` — `sa.Column("last_made", mealie.db.migration_types.NaiveDateTime(), nullable=True)` — exact NaiveDateTime pattern.

### FR-3. Alembic migration (b) — `group_events_notifier_options` columns
A second alembic migration **MUST** add boolean subscription columns to `group_events_notifier_options`.
- `shopping_list_archived: Boolean, nullable=False, server_default=false()`.
- `shopping_list_unarchived: Boolean, nullable=False, server_default=false()`.
- `down_revision` chains off the migration in FR-2.
- `downgrade()` drops both columns.

**code_references:**
- `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_group_notifier_options.py:1-51` — exact verbatim template (the only difference being the column names).
- `mealie/db/models/household/events.py:35-37` — `shopping_list_{created,updated,deleted}: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)` — exact column shape to add at lines 38-39 (after the existing shopping_list group).

### FR-4. New API endpoints — archive / unarchive
The `ShoppingListController` in `mealie/routes/households/controller_shopping_lists.py` **MUST** expose two new endpoints. Both follow the existing controller's `publish_event` template (controller_shopping_lists.py:190–196).
- `POST /api/households/shopping/lists/{item_id}/archive` → `archive_one(self, item_id: UUID4) -> ShoppingListOut`.
- `POST /api/households/shopping/lists/{item_id}/unarchive` → `unarchive_one(self, item_id: UUID4) -> ShoppingListOut`.

Each MUST:
- Be a `@router.post(...)` decorator with `response_model=ShoppingListOut, status_code=200, responses={409: {"model": ErrorResponse, ...}, 404: {"model": ErrorResponse, ...}}`.
- Auth: same as all existing `ShoppingListController` routes (no extra `Depends` — inherits from `BaseCrudController` which uses `get_current_user`).
- Delegate to `self.service.archive_list(item_id, self.user.id)` / `self.service.unarchive_list(item_id)` (the service method is responsible for catching `ShoppingListIsArchivedError` and translating; archive_one will surface a different 409 for "unchecked items").
- Dispatch `EventTypes.shopping_list_archived` / `EventTypes.shopping_list_unarchived` via `self.publish_event(..., group_id=shopping_list.group_id, household_id=shopping_list.household_id, ...)` after success.
- Multitenant isolation: cross-household / cross-group → `404 NOT FOUND` automatically via `HouseholdRepositoryGeneric._filter_builder` (no extra code).
- Return the updated `ShoppingListOut` with `archived_at` / `archived_by` populated for archive and `null` for unarchive.

**code_references:**
- `mealie/routes/households/controller_shopping_lists.py:159-283` — `ShoppingListController` class (insert new endpoints after `delete_one` at line 229).
- `mealie/routes/households/controller_shopping_lists.py:186-198` — `create_one` pattern (decorator, status_code, mixins call, publish_event template).
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

### FR-6. Frozen routes — 409 on archived list mutation
The following routes **MUST** return `409 CONFLICT` with body `ErrorResponse.respond(message=self.t("shopping-list.archived.frozen"))` when the target list is archived:
1. `PUT /api/households/shopping/lists/{item_id}` (handler `ShoppingListController.update_one`, controller_shopping_lists.py:204-215).
2. `POST /api/households/shopping/items` (handler `ShoppingListItemController.create_one` → delegates to `create_many`, lines 127-129).
3. `POST /api/households/shopping/items/create-bulk` (handler `ShoppingListItemController.create_many`, lines 121-125) — same enforcement as #2 since spec §3 implies bulk MUST be frozen for consistency (rationale: singular forms delegate to bulk).
4. `PUT /api/households/shopping/items/{item_id}` (handler `update_one` → `update_many`, lines 141-143).
5. `PUT /api/households/shopping/items` (handler `update_many`, lines 135-139) — same as #4, bulk variant.
6. `DELETE /api/households/shopping/items/{item_id}` (handler `delete_one` → `delete_many`, lines 151-153).
7. `DELETE /api/households/shopping/items` (handler `delete_many`, lines 145-149) — same as #6, bulk variant.

The 409 **MUST** be triggered before any DB write occurs (i.e., the data row's `updated_at` is unchanged after a 409). Enforcement lives in the repository layer (FR-7 + FR-8); the service layer translates the typed `ShoppingListIsArchivedError` to `HTTPException(409, ...)`. The controller calling pattern is preserved with one new try/except block in `update_one` (line 204-215).

The following routes are **explicitly NOT** frozen in v1 (deferred to `needs_clarification`):
- `PUT /api/households/shopping/lists/{id}/label-settings` (controller_shopping_lists.py:234-254) — bypasses `RepositoryShoppingList.update` (uses `self.repos.shopping_list_multi_purpose_labels.update_many`).
- `POST /api/households/shopping/lists/{id}/recipe` (line 256-261), `POST /lists/{id}/recipe/{recipe_id}` (263-272, deprecated), `POST /lists/{id}/recipe/{recipe_id}/delete` (274-283) — these go through `ShoppingListService.add_recipe_ingredients_to_list` / `remove_recipe_ingredients_from_list`, which themselves call the guarded `bulk_*` methods; so technically items get partially blocked, but the list-level recipe_reference mutation (`updated_list.recipe_references.append(...)` followed by `self.shopping_lists.update(updated_list.id, updated_list)` at line 454) WILL be blocked by the guard on the `update` call, leading to a partially-applied error path. Behavior here is undefined in v1; see `needs_clarification`.

**code_references:**
- `mealie/routes/households/controller_shopping_lists.py:98-153` — `ShoppingListItemController` with all item endpoints.
- `mealie/routes/households/controller_shopping_lists.py:204-215` — `update_one` for `PUT /lists/{id}`, needs try/except for `ShoppingListIsArchivedError`.
- `mealie/schema/response/responses.py:8-19` — `ErrorResponse.respond(message=...)` envelope format.

### FR-7. Repository layer — centralised archive filter + guard (`RepositoryShoppingList`)
The existing `mealie/repos/repository_shopping_list.py` (currently 12 lines) **MUST** be extended to host all archive logic per input §7:

1. **`update(item_id, data)` override (extends existing override at lines 9-11):**
   - Before delegating to `super().update(...)`, fetch the current row via `self.session.get(self.model, item_id)`.
   - If the row exists and `row.archived_at is not None`, raise `ShoppingListIsArchivedError({item_id})`.
   - Otherwise delegate to `super().update(item_id, data)` as today.

2. **`archive(item_id, user_id) -> ShoppingListOut` (NEW):**
   - Performs the state transition via raw SQLAlchemy `update(ShoppingList).where(id=item_id).values(archived_at=datetime.now(UTC), archived_by_user_id=user_id)` — does NOT route through the guarded `update`.
   - Returns the updated row via `self.get_one(item_id)`.
   - Raises `ShoppingListIsArchivedError` if the row is already archived (idempotent-failure semantics: archiving an already-archived list returns 409, not 200, so the caller knows).

3. **`unarchive(item_id) -> ShoppingListOut` (NEW):**
   - Performs the state transition via raw SQLAlchemy `update(ShoppingList).where(id=item_id).values(archived_at=None, archived_by_user_id=None)`.
   - Returns the updated row via `self.get_one(item_id)`.
   - If the row is currently NOT archived, returns the row unchanged (idempotent — unarchiving an active list is a no-op, NOT a 409).

4. **`page_all(pagination, override=None, search=None, archived: ArchivedFilter = ArchivedFilter.exclude) -> PaginationBase[ShoppingListSummary]` (OVERRIDE):**
   - Builds the base query via `self._query(...)`, applies `self._filter_builder()` via `filter_by(**fltr)`, then appends one of:
     - `archived == ArchivedFilter.exclude`: `.where(ShoppingList.archived_at.is_(None))`
     - `archived == ArchivedFilter.only`: `.where(ShoppingList.archived_at.is_not(None))`
     - `archived == ArchivedFilter.inclusive`: no additional where clause.
   - Continues with `add_pagination_to_query`, `loader_options`, materialize as in `RepositoryGeneric.page_all` (lines 315-355).

5. **`get_archived_ids(ids: set[UUID4]) -> set[UUID4]` (NEW):**
   - Returns the subset of `ids` that are currently archived AND visible to the caller (i.e., the existing `_filter_builder` group/household scope still applies — cross-household IDs are silently filtered out and treated as "not archived" for guard purposes; this is safe because cross-household mutations would 404 elsewhere anyway).
   - Single SQL query: `SELECT id FROM shopping_lists WHERE id IN :ids AND archived_at IS NOT NULL AND group_id = :group_id AND user_id IN (SELECT id FROM users WHERE household_id = :household_id)`.

The default-exclude filter MUST compose correctly with `HouseholdRepositoryGeneric._filter_builder` so that household/group isolation is preserved for all `archived` values.

**code_references:**
- `mealie/repos/repository_shopping_list.py:1-12` — current full file (the seam).
- `mealie/repos/repository_generic.py:79-92` — `_query` with `AssociationProxyInstance` handling.
- `mealie/repos/repository_generic.py:94-102` — `_filter_builder` injecting `group_id`+`household_id`.
- `mealie/repos/repository_generic.py:315-355` — `page_all` pattern to mirror in the override.
- `mealie/repos/repository_generic.py:505-523` — `HouseholdRepositoryGeneric` constructor.

### FR-8. New repository — `RepositoryShoppingListItem`
A new file `mealie/repos/repository_shopping_list_item.py` **MUST** define `class RepositoryShoppingListItem(HouseholdRepositoryGeneric[ShoppingListItemOut, ShoppingListItem])` that overrides three methods to guard against parent-list-archived state:
- `create_many(items: list[ShoppingListItemCreate]) -> list[ShoppingListItemOut]`:
  - Extract `distinct_list_ids = {i.shopping_list_id for i in items}`.
  - `archived = self.repos.group_shopping_lists.get_archived_ids(distinct_list_ids)` — but the `RepositoryShoppingListItem` doesn't have a back-reference to `AllRepositories`. **Resolution:** add a class attribute / constructor injection: the `repository_factory.py` line 325 wiring passes `parent_repo=group_shopping_lists` OR `RepositoryShoppingListItem` is constructed with the same `session` and uses `from mealie.repos.repository_shopping_list import RepositoryShoppingList` directly to query.
  - If `archived` is non-empty, raise `ShoppingListIsArchivedError(archived)`.
  - Otherwise delegate to `super().create_many(items)`.
- `update_many(items: list[ShoppingListItemUpdateBulk]) -> list[ShoppingListItemOut]`: same pattern.
- `delete_many(ids: set[UUID4] | list[UUID4]) -> list[ShoppingListItemOut]`:
  - First query: `SELECT DISTINCT shopping_list_id FROM shopping_list_items WHERE id IN :ids` → `distinct_list_ids`.
  - Call `get_archived_ids(distinct_list_ids)`; if non-empty, raise.
  - Otherwise delegate to `super().delete_many(ids)`.

The repository factory `mealie/repos/repository_factory.py:323-332` MUST be updated to instantiate `RepositoryShoppingListItem` (current code instantiates raw `HouseholdRepositoryGeneric`).

**code_references:**
- `mealie/repos/repository_factory.py:317-321` — `group_shopping_lists` cached_property (showing factory pattern; the new ItemRepo will be at line 323-332).
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

The default `None` values **MUST** preserve backward compatibility (US-9).

**code_references:**
- `mealie/schema/household/group_shopping_list.py:216-238` — `ShoppingListSummary` definition.
- `mealie/schema/household/group_shopping_list.py:250-285` — `ShoppingListOut` definition.
- `mealie/schema/user/user.py:191-197` — `UserSummary` class.

### FR-10. Event bus additions
The `mealie/services/event_bus_service/event_types.py` **MUST** be extended with:
1. **Two new `EventTypes` enum members** at line 44 (after `shopping_list_deleted`):
   - `shopping_list_archived = auto()`
   - `shopping_list_unarchived = auto()`
2. **New payload class `EventShoppingListArchiveData(EventDocumentDataBase)`** after `EventShoppingListData` (line 132):
   ```python
   class EventShoppingListArchiveData(EventDocumentDataBase):
       document_type: EventDocumentType = EventDocumentType.shopping_list
       shopping_list_id: UUID4
       shopping_list_name: str | None = None
       household_id: UUID4
       archived_by_user_id: UUID4 | None = None
       item_count: int = 0
       total_estimated_amount: float | None = None
   ```
3. **Db model `GroupEventNotifierOptionsModel` (events.py:15-57)** gains two boolean columns after line 37: `shopping_list_archived` and `shopping_list_unarchived` (matching FR-3's migration).

Payload **MUST NOT** contain any field not listed above. In particular, MUST NOT embed `User` objects, full `ShoppingListOut`, or any field that references entities in other households/groups.

The dispatcher **MUST** pass `group_id=shopping_list.group_id, household_id=shopping_list.household_id` (NOT `self.group_id`/`self.household_id`) so that `EventBusService.dispatch` (event_bus_service.py:66-96) targets exactly the owning household.

**code_references:**
- `mealie/services/event_bus_service/event_types.py:13-60` — `EventTypes` enum.
- `mealie/services/event_bus_service/event_types.py:14-22` — docstring mandating DB migration on enum changes.
- `mealie/services/event_bus_service/event_types.py:130-132` — existing `EventShoppingListData` (the precedent for the new class).
- `mealie/db/models/household/events.py:35-37` — `shopping_list_{created,updated,deleted}` columns (insertion point at 38-39).
- `mealie/services/event_bus_service/event_bus_service.py:66-96` — `dispatch` method with per-household loop at 92-96.

### FR-11. Service layer — `archive_list` / `unarchive_list` + 409 translation
The `mealie/services/household_services/shopping_lists.py` **MUST** be extended with:
1. **`archive_list(self, list_id: UUID4, user_id: UUID4) -> ShoppingListOut`** (NEW; insert after `create_one_list` at line 554):
   - Fetch the list: `shopping_list = self.shopping_lists.get_one(list_id)`. If `None`, raise `HTTPException(404, ErrorResponse.respond(message=self.t("exceptions.no-entry-found")))`.
   - If `shopping_list.archived_at is not None` (already archived), raise `HTTPException(409, ErrorResponse.respond(message=self.t("shopping-list.archived.frozen")))` — idempotent-failure: caller learns the operation is a no-op.
   - Validate "all items checked" precondition. SQL form: `any((item.checked is None or item.checked is False) for item in shopping_list.list_items)`. If True, raise `HTTPException(409, ErrorResponse.respond(message=self.t("shopping-list.archive.unchecked-items")))`.
   - Call `self.shopping_lists.archive(list_id, user_id)` (the new repo method from FR-7).
   - Return the result.

2. **`unarchive_list(self, list_id: UUID4) -> ShoppingListOut`** (NEW; insert after `archive_list`):
   - Fetch: `shopping_list = self.shopping_lists.get_one(list_id)`. 404 if None.
   - Call `self.shopping_lists.unarchive(list_id)`.
   - Return the result.

3. **Translation wrappers around existing bulk methods.** The simplest implementation: wrap each `bulk_create_items`, `bulk_update_items`, `bulk_delete_items` body in:
   ```python
   try:
       ...existing body...
   except ShoppingListIsArchivedError:
       raise HTTPException(
           status_code=status.HTTP_409_CONFLICT,
           detail=ErrorResponse.respond(message=self.t("shopping-list.archived.frozen")),
       )
   ```
   - `self.t` is NOT currently available on `ShoppingListService` (which has only `__init__(self, repos)` at line 37). **Resolution:** add `translator: Translator` parameter to `ShoppingListService.__init__`, or thread `t` via method args, or import a global translator fallback. The lowest-risk path: pass the translator from the controller/scheduler call site. (Coding phase decides; spec keeps the option open.)
   - **Important: do NOT wrap `bulk_*` methods inside `archive_list` / `unarchive_list`** — those don't call the bulk methods.

**code_references:**
- `mealie/services/household_services/shopping_lists.py:37-43` — `ShoppingListService.__init__`.
- `mealie/services/household_services/shopping_lists.py:154-223` — `bulk_create_items`.
- `mealie/services/household_services/shopping_lists.py:225-310` — `bulk_update_items`.
- `mealie/services/household_services/shopping_lists.py:312-321` — `bulk_delete_items`.
- `mealie/services/household_services/shopping_lists.py:541-554` — `create_one_list` (insertion point for new methods at line 555+).

### FR-12. Multitenant isolation
Cross-household and cross-group operations on shopping lists **MUST** continue to return 404 (NOT 403) via the existing `HouseholdRepositoryGeneric._filter_builder` mechanism (no NEW code required; existing scoping at `mealie/repos/repository_generic.py:94-102` automatically applies):
- `GET /api/households/shopping/lists?archived=true` from household H2 MUST NOT include H1's archived lists.
- `POST /api/households/shopping/lists/{H1_list.id}/archive` from household H2 MUST return `404 NOT FOUND` (because `self.shopping_lists.get_one(list_id)` returns None when the list's `user.household_id != self.household_id`).
- Same for `/unarchive`, `PUT /lists/{id}`, item mutations targeting another household's list.
- Event payloads for archive/unarchive MUST contain only the owning household's data (FR-10 payload class enforces this by construction).

`AGR-8` from `consolidated.md` is locked: the new `RepositoryShoppingList.page_all` override composes the archived predicate via `.where(...)` AFTER `_filter_builder` injects `group_id`+`household_id`, preserving isolation for all `archived` values.

**code_references:**
- `mealie/repos/repository_generic.py:94-102` — `_filter_builder`.
- `mealie/repos/repository_generic.py:505-523` — `HouseholdRepositoryGeneric` ctor.
- `mealie/routes/_base/base_controllers.py:199-214` — `publish_event` accepts explicit `group_id`/`household_id`.
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
- All other locale files (`af-ZA.json` through `zh-TW.json`, ~35 files) **MUST NOT** be modified; per `.github/copilot-instructions.md`, they are Crowdin-managed and PRs touching them are rejected.

**code_references:**
- `mealie/lang/messages/en-US.json:1-95` — current file (4109 bytes, 9 top-level keys, no `shopping-list` namespace).
- `mealie/lang/messages/en-US.json:46-53` — existing `exceptions` namespace (parallel pattern).

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
- `frontend/app/lib/api/types/household.ts` — new `archivedAt?: string | null` and `archivedBy?: UserSummary | null` fields on `ShoppingListSummary` (lines 735-748 today) and `ShoppingListOut` (lines 673-687 today).
- `frontend/app/lib/api/types/events.ts` — new enum members + `EventShoppingListArchiveData` interface.
- `mealie/schema/household/__init__.py` — re-export of `ArchivedFilter`.
- `tests/utils/api_routes/__init__.py` — new helpers `households_shopping_lists_item_id_archive(id)`, `households_shopping_lists_item_id_unarchive(id)`.

PR **MUST NOT** hand-edit any of these files (CI will detect drift and reject).

**code_references:**
- `frontend/app/lib/api/types/household.ts:673-687,735-748` — current `ShoppingListOut` / `ShoppingListSummary` shapes.
- `tests/utils/api_routes/__init__.py:114` — current `households_shopping_lists` constant.

---

## 4. Success criteria (measurable acceptance)

| # | Criterion | Measurement |
|---|-----------|-------------|
| SC-1 | **Archive idempotency** | Calling `POST /archive` on an already-archived list returns 409 (not 200, not 500). Verified by integration test asserting `response.status_code == 409` and message text. |
| SC-2 | **All 4 frozen routes return 409 with i18n message** | Integration tests cover each of the 7 frozen route variants in FR-6 (PUT list, POST item, POST items/create-bulk, PUT item, PUT items, DELETE item, DELETE items). Each test asserts `response.status_code == 409` AND `response.json()["detail"]["message"] == "This shopping list is archived and cannot be modified. Unarchive it first."`. Count: 7 distinct test methods. |
| SC-3 | **Event payload field-set is exactly the spec'd set** | A test using `monkeypatch.setattr` on `EventBusService.dispatch` captures dispatched events; asserts `set(payload.model_dump().keys()) == {"document_type", "operation", "shopping_list_id", "shopping_list_name", "household_id", "archived_by_user_id", "item_count", "total_estimated_amount"}` for `EventTypes.shopping_list_archived` and `EventTypes.shopping_list_unarchived`. No additional keys (no `User` object, no `list_items` collection). |
| SC-4 | **Event payload household isolation** | A test where user U1 in household H1 archives list L1; a captured `EventBusService.dispatch` shows `household_id` in the dispatch args equals H1.id (NOT H2.id). Asserted via `captured[0]["household_id"] == H1.id`. |
| SC-5 | **Default GET filter correctness** | Two integration tests: (a) given one active + one archived list in H1, `GET /api/households/shopping/lists` returns 1 item with the active list's id; `total == 1`. (b) `GET /api/households/shopping/lists?archived=true` returns 1 item with the archived list's id; `total == 1`. (c) `GET /api/households/shopping/lists?archived=all` returns 2 items containing both ids. |
| SC-6 | **Multitenant isolation — same-group different-household** | Integration test (using `h2_user` fixture): H2 user calls `GET /api/households/shopping/lists?archived=true`, response items DO NOT contain any list owned by H1. H2 user calls `POST /api/households/shopping/lists/{H1_list.id}/archive`, response status is 404. |
| SC-7 | **Multitenant isolation — cross-group** | `ArchivedShoppingListsTestCase` registered in `tests/multitenant_tests/test_multitenant_cases.py` `all_cases`; parametrized `test_multitenant_cases_get_all` automatically asserts that user_two (different group) sees an empty list when user_one's group has archived lists seeded. |
| SC-8 | **i18n key presence** | A unit test asserts `Translator(locale="en-US").t("shopping-list.archive.unchecked-items") == "Cannot archive a shopping list while items remain unchecked"` and `Translator(locale="en-US").t("shopping-list.archived.frozen") == "This shopping list is archived and cannot be modified. Unarchive it first."`. Both keys MUST be resolvable (no `KeyError`). |
| SC-9 | **Migration reversibility** | Run `alembic upgrade head` then `alembic downgrade -2` (down past both new migrations); database table `shopping_lists` no longer has `archived_at`/`archived_by_user_id` columns; `group_events_notifier_options` no longer has `shopping_list_archived`/`shopping_list_unarchived` columns. All existing rows preserved. Verified by CI matrix on SQLite + PostgreSQL. |
| SC-10 | **Test count by category** | At least: **4 unit tests** (`tests/unit_tests/` covering `archive_list` success, `archive_list` 409 unchecked-items, `unarchive_list` success, `RepositoryShoppingList.page_all` ArchivedFilter branches); **≥10 integration tests** in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` covering US-1..US-7 + US-10; **≥5 multitenant tests** (1 new `case_shopping_list_archive.py` + ≥4 in new `test_shopping_list_archive_household.py`). |
| SC-11 | **Backward compatibility — existing tests pass** | All currently-passing tests in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` (1113 lines, 7+ baseline test methods listed in `consolidated.md` §1.2 T1) and `test_group_shopping_list_items.py` (623 lines) continue to pass without modification. Verified via `task py:test`. |
| SC-12 | **Scheduler does not regress** | Unit test for `delete_old_checked_list_items`: given a household with 1 archived list containing 150 checked items AND 1 active list with 150 checked items, after the task runs, archived list still has 150 items, active list has 100 items (MAX_CHECKED_ITEMS). No `HTTPException` or `ShoppingListIsArchivedError` raised. |

---

## 5. Edge cases (≥6 required; this spec covers 9)

### EC-1. Archive an empty list (no items)
**Scenario.** `ShoppingList L1` exists with `list_items == []`.
**Expected.** `POST /archive` succeeds (the "all items checked" precondition is vacuously true). `L1.archived_at` is set; event dispatched with `item_count == 0`.
**Why this matters.** Without explicit handling, `all(item.checked for item in [])` evaluates True (correct), but the event payload's `total_estimated_amount` and downstream consumers might assume non-empty.

### EC-2. Archive a list where exactly 1 item is unchecked, the rest are checked
**Scenario.** `L1` has 9 items with `checked=True`, 1 with `checked=False`.
**Expected.** `POST /archive` returns 409 with `shopping-list.archive.unchecked-items` message. List is NOT archived.
**Why this matters.** Boundary case for the precondition logic; ensures the "any unchecked" check is short-circuiting correctly.

### EC-2b. Archive a list where 1 item has `checked = None` (NULL in DB)
**Scenario.** `L1` has 9 items with `checked=True`, 1 with `checked=None`.
**Expected.** `POST /archive` returns 409 — NULL is treated as unchecked.
**Why this matters.** `ShoppingListItem.checked: FilterableColumn[bool | None]` (`shopping_list.py:65`) allows NULL. The precondition must treat NULL as unchecked to be safe.

### EC-3. Unarchive a non-archived list
**Scenario.** `L1` has `archived_at IS NULL`.
**Expected.** `POST /unarchive` returns **200 OK** with the list unchanged (idempotent no-op). NO event is dispatched (no state change).
**Why this matters.** Distinguishes from "archive an already-archived list" which IS a 409 — the asymmetry is intentional: archive failure signals "you're trying to re-archive" (potentially a programming error worth surfacing), while unarchive on an active list is benign cleanup.

### EC-4. Archive cascade — does it affect cookbook/analytics/scheduler consumers?
**Scenario.** Multiple downstream consumers of shopping lists may exist.
**Inventory and expected behavior:**
- **Cookbook (`mealie/services/household_services/cookbook_service.py`)** — Does NOT consume shopping lists (cookbooks are recipe collections). No interaction. ✅
- **Meal plan** — Does not consume shopping lists; meal-plan-to-shopping-list flows one direction (meal plan generates items). Reading: `mealie/routes/households/controller_mealplan.py` does not reference `ShoppingList`. ✅
- **`delete_old_checked_shopping_list_items.py` scheduler** — Currently iterates ALL shopping lists including archived ones; without FR-14 fix, would trigger 409s from the repo guard in a cron context. ⚠️ Fix mandated in FR-14.
- **Backup/export (`mealie/services/backups_v2/`)** — Dumps full ORM rows; the new columns automatically flow into the backup. Restore re-populates them. No code change needed; this is verified by the existing backup version-bump test (PR #7416, commit `e1ddc06e`). ✅
- **Frontend offline PWA queue (`frontend/app/composables/use-shopping-list-item-actions.ts`)** — Will receive 409s on flush if the user archived a list while items were queued offline. Recommended (out of v1 scope): drop the failing op rather than retry forever. Flagged in self-concerns. ⚠️

### EC-5. Backup/export of archived lists
**Scenario.** Operator runs `POST /api/admin/backups` after some lists have been archived.
**Expected.** Backup contains all `shopping_lists` rows including `archived_at` + `archived_by_user_id` columns. Restore re-creates them with the same archived state.
**Verification.** `task py:test -- tests/integration_tests/backup_v2_tests/` continues to pass. No new test required for v1 (the existing backup-roundtrip test inherently covers new columns).

### EC-6. Admin override / force unarchive
**Scenario.** Per input §三环节考察点: "是否需要 admin 强制 unarchive".
**Expected (v1).** NOT in v1 scope. The existing `BaseAdminController` (`mealie/routes/_base/base_controllers.py:180-189`) clears household scoping, so an admin would naturally see ALL households' archived lists via `GET /api/admin/...` routes. But no admin-specific archive/unarchive endpoint is added in v1.
**Follow-up.** Tracked under `self_concerns` for v2 consideration. The current `archive_one`/`unarchive_one` endpoints inherit `BaseCrudController` behavior; an admin user calling the regular endpoint succeeds only if they belong to the owning household. Force-unarchive across households is a separate feature.

### EC-7. Two users in the same household call `POST /archive` concurrently
**Scenario.** U1 and U2 both belong to H1; both `POST /api/households/shopping/lists/{L1.id}/archive` at the same time when L1 is active.
**Expected.** One succeeds (race winner; sets `archived_by_user_id` to that user). The other receives 409 + `shopping-list.archived.frozen` because by the time `RepositoryShoppingList.archive` queries the row, it sees `archived_at IS NOT NULL` and treats it as already-archived.
**Risk if not handled.** Without the "already archived" check inside `archive`, both writes would commit and the second silently overwrites `archived_by_user_id`. FR-7 §2 requires the guard. Out of scope for v1: add a unique partial index `WHERE archived_at IS NULL` for stronger DB-level guarantees.

### EC-8. User who archived a list is deleted
**Scenario.** User U1 archives list L1; later U1's account is deleted.
**Expected (v1, default).** Without an explicit `ON DELETE SET NULL` on the FK, the DELETE on `users` would fail with a constraint violation. **Resolution:** the alembic migration (FR-2) declares the FK without `ondelete=` (default behavior). Since `shopping_lists.archived_by_user_id` is nullable and is just an attribution field, the most correct option is `ON DELETE SET NULL` so user-deletion cascades cleanly.
**Follow-up (v1 decision).** Use `ON DELETE SET NULL` to avoid breaking user-deletion. Document in the migration. Tested via integration test: delete a user who archived a list, then re-fetch the list, assert `archived_by_user_id is None`.

---

## 6. `needs_clarification` (genuine input-vs-code conflicts)

These are points where the input spec is silent or ambiguous AND the existing code creates a constraint that must be resolved before coding. Each item lists the specific question, the discovered conflict, and a default resolution that the spec assumes if no clarification is provided.

### NC-1. Frozen scope on "other operations" routes (label-settings, recipe-add, recipe-remove)
- **Question.** Should `PUT /api/households/shopping/lists/{id}/label-settings` (line 234-254) and the three recipe-management routes (lines 256-283) ALSO return 409 on archived lists?
- **Conflict.** Spec §3 enumerates exactly 4 routes (`PUT /lists/{id}`, `POST /items`, `PUT /items/{id}`, `DELETE /items/{id}`). The label-settings route bypasses `RepositoryShoppingList.update` (it uses `self.repos.shopping_list_multi_purpose_labels.update_many` at line 243), so the repo guard does NOT cover it. The recipe-add/recipe-remove routes go through `bulk_create_items`/`bulk_update_items`/`bulk_delete_items` which ARE guarded, but they also call `self.shopping_lists.update(...)` at line 454 to update list-level recipe references — that call WILL trigger the guard and produce a partially-applied-then-409 error path.
- **Default resolution (assumed unless clarified).** v1 freezes ONLY the 4 spec'd routes + their bulk siblings. Label-settings remains mutable on archived lists. Recipe-add/recipe-remove produce a partial mutation failure path that is acceptable in v1; document the limitation in the PR description.
- **Why this needs clarification.** The intent ("frozen" archived lists) implies all mutations blocked; the explicit list is shorter. Without clarification, the test suite cannot decide whether to assert 409 or 200 on these routes.

### NC-2. Scope of "household 内成员" rule — admin-only or any member?
- **Question.** Input §2 says "household 内成员" (household member) for the archive/unarchive endpoints. Does "member" mean any user belonging to the household (including non-admins), or only an admin within the household?
- **Conflict.** Existing CRUD routes on `ShoppingListController` (line 159-283) use the default `BaseCrudController` permission (any authenticated user whose household_id matches), NOT `BaseAdminController`. The spec uses the same phrase "household 内成员" for the simpler routes too, so the consistent reading is "any household member".
- **Default resolution.** Any authenticated household member can archive/unarchive. No admin role required. Consistent with the existing routes that create/update/delete shopping lists.

### NC-3. Exact event payload field names — `list_id` vs `shopping_list_id`
- **Question.** Spec §5 lists payload fields as `list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`. The existing `EventShoppingListData` uses `shopping_list_id`. Should the new payload use the spec's exact `list_id`/`list_name` or the existing convention's `shopping_list_id`/`shopping_list_name`?
- **Conflict.** Spec text vs existing code naming. JSON consumers of the event bus (apprise notifiers, webhooks) might pattern-match either name.
- **Default resolution.** Use existing-code convention: `shopping_list_id` and `shopping_list_name`. Rationale: (a) consistency with `EventShoppingListData.shopping_list_id` and `EventShoppingListItemBulkData.shopping_list_id`; (b) the spec's `list_id` is a shorthand that creates ambiguity (there could be `meal_plan_id`, `cookbook_id` collisions); (c) any auto-generated TypeScript consumer prefers the long form. The spec's `list_id` is interpreted as informal shorthand for `shopping_list_id`.

### NC-4. `total_estimated_amount` semantics
- **Question.** Spec §5 says payload includes `total_estimated_amount (如有)` (if available). No `price` / `cost` / `amount` column exists on `ShoppingListItem` today.
- **Conflict.** Field is requested in the contract but no source data exists.
- **Default resolution.** Field defaults to `None`. Forward-compat hook for a future price-tracking feature. NOT computed from any existing column (no per-item price exists; `ShoppingListItem.quantity` is the count, `ShoppingListItem.extras` is a free-form JSON that COULD contain price but is per-deployment convention). Coding phase must NOT attempt to compute this field in v1.

### NC-5. `ON DELETE` behavior for `archived_by_user_id` FK
- **Question.** When the user who archived a list is deleted, what happens to `archived_by_user_id`?
- **Default resolution.** `ON DELETE SET NULL`. Migration FR-2 declares `batch_op.create_foreign_key("fk_shopping_lists_archived_by_user_id", "users", ["archived_by_user_id"], ["id"], ondelete="SET NULL")`. (See EC-8.)

---

## 7. Self-concerns (residual uncertainty)

These are concerns the spec author has about choices made — not blockers, but worth surfacing to the design/coding/CR phases.

### SCN-1. Translator dependency injection into `ShoppingListService`
- **Concern.** FR-11 requires `ShoppingListService.bulk_*` methods to call `self.t(...)` to translate `ShoppingListIsArchivedError`. The service constructor today (`shopping_lists.py:37-43`) takes ONLY `repos: AllRepositories` — no translator. Adding `translator: Translator` to `__init__` is a breaking change for every caller (controller, scheduler, test fixtures).
- **Risk.** Coding phase might pick a different layering: (a) inject translator via method-level kwarg; (b) put the try/except in the controller instead of service; (c) raise `ShoppingListIsArchivedError` all the way to the FastAPI exception handler and translate there in `mealie/routes/handlers.py`. Option (c) is the cleanest if a global handler can be registered.
- **Recommendation.** Use option (c): register a global exception handler in `mealie/routes/handlers.py` that maps `ShoppingListIsArchivedError → HTTPException(409, ErrorResponse.respond(...))`. The handler can access the request's translator via the FastAPI dependency machinery.

### SCN-2. Partial-mutation failure path for recipe-add/recipe-remove routes
- **Concern.** As noted in NC-1, the recipe-add/recipe-remove routes call BOTH guarded methods (`bulk_create_items`) AND the guarded `update` on the list (line 454: `self.shopping_lists.update(updated_list.id, updated_list)`). The `bulk_create_items` could succeed (creating items) then the subsequent `update` call could fail with 409 if the list happens to be archived. The user sees a 409 but the database has new items.
- **Risk.** Data-inconsistency edge case. Mealie has no SQL-level "transaction guard" against this in v1.
- **Recommendation.** Acceptable in v1 since these routes aren't in spec §3's frozen list. Document the partial-failure mode in the PR description.

### SCN-3. `RepositoryShoppingListItem` constructor — passing the parent repo
- **Concern.** `RepositoryShoppingListItem` needs to call `self.repos.group_shopping_lists.get_archived_ids(...)` from inside `create_many/update_many/delete_many`. But `HouseholdRepositoryGeneric.__init__` doesn't take an `AllRepositories` reference (verified: `repository_generic.py:505-523`).
- **Options.** (a) Pass a `parent_repo: RepositoryShoppingList` to the constructor (extends factory wiring at `repository_factory.py:325`). (b) Construct a private `RepositoryShoppingList(self.session, ...)` inline whenever needed (cheap; reuses `self.session`). (c) Move the check up to the service layer for ITEMS (asymmetric design — repo guards LIST mutations, service guards ITEM mutations).
- **Recommendation.** Option (a). Cleanest, single source of truth, explicit dependency. Adds ~3 lines to `repository_factory.py`.

### SCN-4. `archived_by` schema serialization extra cost
- **Concern.** Adding `archived_by: UserSummary | None` to `ShoppingListSummary.loader_options` adds one more `selectinload` per list. For households with hundreds of lists, this is a small N+1 risk. The existing `loader_options` at line 224-238 already eager-loads `User` via `joinedload(ShoppingList.user).load_only(...)`; the new `archived_by` eager-load is a separate join because it targets a different FK.
- **Risk.** Slight performance regression in `GET /lists` when many lists are archived.
- **Mitigation.** Only loaded eagerly when needed. Since `archived_by` defaults to None and is populated only when archived, the join effectively becomes a LEFT OUTER JOIN that's nearly free for active-list-heavy responses. Performance test in v1 not required; benchmark in v2 if reports surface.

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
- [ ] Repository methods inherit/call `_filter_builder` to preserve multitenancy scoping.
- [ ] Service methods stay free of HTTP concerns; HTTP translation lives at the controller or exception-handler layer.
- [ ] No hand-edits to `frontend/app/lib/api/types/`, `mealie/schema/*/__init__.py`, or `tests/utils/api_routes/__init__.py` — all autogen.
- [ ] PR title follows Conventional Commits: `feat: add archive lifecycle to shopping lists`.
- [ ] PR description includes release notes and ADR-style rationale for repo-layer guard placement.
