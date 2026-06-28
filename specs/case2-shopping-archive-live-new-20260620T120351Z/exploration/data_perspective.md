# Data Perspective — Case 2 (Shopping List Archive)

Run: 2026-06-19T12:42

Lens: data model, persistence layer, query/filtering, schemas, event payloads, migration patterns.
Every line range below was opened and visually verified during this pass.

---

## Artifacts

### A1. `ShoppingList` SQLAlchemy model — current shape
- **Path:** `mealie/db/models/household/shopping_list.py`
- **Key symbols:** `ShoppingList` (class), `id`, `group_id`, `user_id`, `household_id` (assoc proxy), `household` (assoc proxy), `name`, `list_items`, `recipe_references`, `label_settings`, `extras`
- **Line ranges:**
  - `class ShoppingList` declaration & columns: **lines 147–181**
  - `household_id: AssociationProxy[GUID] = association_proxy("user", "household_id")`: **line 153**
  - `user_id: ... ForeignKey("users.id"), nullable=False, index=True`: **line 155**
  - relationships (`list_items`, `recipe_references`, `label_settings`, `extras`): **lines 159–175**
  - `@event.listens_for(ShoppingListItem, "after_insert/update/delete") buffer_shopping_list_updates`: **lines 204–211** (auto-bumps shopping_list.updated_at on item change — relevant when items are mutated)
  - `update_shopping_lists @ "after_flush"`: **lines 214–238**
- **Importance:** HIGH. Direct surface for adding `archived_at` + `archived_by_user_id` columns. The fact that `household_id` is an `association_proxy` through `user` (not a real column) means filtering by it requires a JOIN on user — relevant for the centralised archive filter in the repository.
- **Reason:** ShoppingList only has `group_id` and `user_id` as real FK columns; household scoping piggybacks on `user.household_id`. New archive columns can be plain `mapped_column`s and need NO association proxy. `BaseMixins.update()` (auto-calls `__init__`) is the integration point — `archived_at` / `archived_by_user_id` must be present in `__init__` kwargs for normal updates not to wipe them.

### A2. `ShoppingListItem.checked` field
- **Path:** `mealie/db/models/household/shopping_list.py`
- **Key symbols:** `ShoppingListItem`, `checked`, `position`, `quantity`, `shopping_list_id`
- **Line ranges:**
  - `class ShoppingListItem(SqlAlchemyBase, BaseMixins)`: **lines 51–98**
  - `checked: FilterableColumn[bool | None] = mapped_column(Boolean, default=False)`: **line 65**
  - `position: ... nullable=False, default=0, index=True`: **line 64**
  - `shopping_list_id` FK: **line 57**
- **Importance:** HIGH. The archive precondition "all items checked=true → otherwise 409" maps directly to this column.
- **Reason:** `checked` is **nullable** (`bool | None`), default False. The archive-precondition logic in the service layer needs to treat NULL as unchecked to be safe (e.g. `AND (checked IS NULL OR checked = false)` returns the set of "not yet checked" items).

### A3. Alembic migration pattern for adding a nullable column + FK
- **Path:** `mealie/alembic/versions/2025-09-10-19.21.48_1d9a002d7234_add_referenced_recipe_to_ingredients.py`
- **Key symbols:** `upgrade`, `downgrade`, `batch_alter_table`, `add_column`, `create_index`, `create_foreign_key`
- **Line ranges:**
  - Full file: **lines 1–41**
  - revision id / down_revision: **lines 14–16** (head-pointer pattern)
  - upgrade body — `batch_alter_table("recipes_ingredients") → add_column(nullable=True) → create_index → create_foreign_key`: **lines 21–30**
  - downgrade body: **lines 33–40**
- **Importance:** HIGH. Direct template for `archived_by_user_id`'s FK migration.
- **Reason:** Mealie supports both SQLite and Postgres → migrations MUST use `op.batch_alter_table(...)` context (line 23) instead of bare `op.add_column`/`op.create_foreign_key`, otherwise SQLite breaks. `nullable=True` + named FK constraint (`fk_recipe_subrecipe`) is the established pattern. Use `mealie.db.migration_types.GUID()` for UUID columns.

### A3b. Alembic precedent for adding a NaiveDateTime column
- **Path:** `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_and_household_to_foods_and_household_to_tools.py`
- **Key symbols:** `mealie.db.migration_types.NaiveDateTime()` import + usage
- **Line ranges:**
  - import: **line 15** (`import mealie.db.migration_types`)
  - example `sa.Column("last_made", mealie.db.migration_types.NaiveDateTime(), nullable=True)`: **line 183**
  - `created_at`/`update_at` columns also use the same type: **lines 184–185**
- **Importance:** MEDIUM. Confirms `archived_at` column should be `mealie.db.migration_types.NaiveDateTime(), nullable=True`, no `server_default` (so existing rows stay NULL, matching spec §1 "默认 NULL = 未归档").
- **Reason:** Mealie wraps `DateTime` in `NaiveDateTime` (mealie/db/models/_model_utils/datetime.py:20-50) to strip timezones at write time and reinsert UTC at read time. Using bare `sa.DateTime` would diverge from convention.

### A3c. Alembic precedent for extending the GroupEventNotifierOptions table
- **Path:** `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_group_notifier_options.py`
- **Key symbols:** `mealplan_entry_updated`, `mealplan_entry_deleted` boolean subscription flags
- **Line ranges:**
  - Full file: **lines 1–51**
  - upgrade: `batch_alter_table("group_events_notifier_options") → add_column(Boolean, nullable=False, server_default=false())`: **lines 19–39**
  - downgrade: `drop_column` for each: **lines 44–49**
- **Importance:** HIGH (hidden requirement). Adding `ShoppingListArchived` / `ShoppingListUnarchived` event types to `EventTypes` enum (mealie/services/event_bus_service/event_types.py:13-22 docstring mandates this) requires the **same** migration shape against the `group_events_notifier_options` table — to add `shopping_list_archived` / `shopping_list_unarchived` boolean subscription columns matching the new enum members.
- **Reason:** `GroupEventNotifierOptionsModel` (mealie/db/models/household/events.py:15-57) has one boolean column per EventTypes enum value (e.g. `shopping_list_created`/`shopping_list_updated`/`shopping_list_deleted` at lines 35–37). Skipping this migration would break subscriber-flag persistence for the new event types.

### A4. `repository_shopping_list.py` — current query / filter patterns
- **Path:** `mealie/repos/repository_shopping_list.py`
- **Key symbols:** `RepositoryShoppingList(HouseholdRepositoryGeneric[ShoppingListOut, ShoppingList])`, `update`
- **Line ranges:** Full file: **lines 1–12** (only ~12 lines; trivial subclass with one `update` override)
- **Importance:** HIGH. **This is the file the spec §7 refers to as "repository_shopping.py" (naming drift).** It is where the centralised `archived` filter must live.
- **Reason:** Because the class is so thin today, adding methods like `page_all_archived`/`page_all_active` (or a `filter_archived: ArchivedFilter` enum parameter to a wrapper around `page_all`) is straightforward and keeps controllers free of filter logic.

### A4b. `HouseholdRepositoryGeneric` — household-scoped filter machinery
- **Path:** `mealie/repos/repository_generic.py`
- **Key symbols:** `RepositoryGeneric`, `HouseholdRepositoryGeneric`, `_query`, `_filter_builder`, `page_all`
- **Line ranges:**
  - `class RepositoryGeneric`: **lines 33–58** (constructor + group_id/household_id properties)
  - `_query` with `AssociationProxyInstance` special-case for `household_id`: **lines 79–92**
  - `_filter_builder` (injects group_id + household_id into filter_by kwargs): **lines 94–102**
  - `page_all` (the method actually called by ShoppingListController.get_all): **lines 315–355**
    - applies `self._filter_builder()` at line 330–331 → household scoping is automatic
    - applies pagination/search/order/options: 332–344
  - `add_pagination_to_query` with `QueryFilterBuilder` integration (supports `?query_filter=archived_at IS NULL`): **lines 357–405**, esp. lines 367–374
  - `class HouseholdRepositoryGeneric`: **lines 505–523** (adds `household_id` constructor kwarg + setter)
- **Importance:** CRITICAL. This is the spine of the data access layer; all archive-related query branches must compose with `_filter_builder` so household isolation survives.
- **Reason:** The archived/active/all switch can be implemented by adding a `.filter(ShoppingList.archived_at.is_(None))` / `.is_not(None)` on top of the existing `_query()` *before* `page_all` applies pagination. Bypassing `_filter_builder` would break multitenancy.

### A4c. Existing query_filter expression support
- **Path:** `mealie/services/query_filter/builder.py`
- **Key symbols:** `QueryFilterBuilder`, `is_not(None)` for IS NULL semantics
- **Line ranges:**
  - `class QueryFilterBuilder`: **line 162**
  - `is_not` operator wiring: **line 302** (`element = model_attr.is_not(value)`)
- **Importance:** MEDIUM. Mealie already supports `archived_at IS NULL` style filters via pagination's `query_filter` param. The new `?archived=` flag could either reuse this OR be a dedicated query param translated into the same filter — the latter is cleaner because spec §2 uses a tri-state (`omitted` / `true` / `all`).
- **Reason:** Avoids inventing a new filter DSL.

### A5. Pydantic schemas for `ShoppingListSummary` / `ShoppingListOut`
- **Path:** `mealie/schema/household/group_shopping_list.py`
- **Key symbols:** `ShoppingListCreate`, `ShoppingListSave`, `ShoppingListUpdate`, `ShoppingListSummary`, `ShoppingListOut`, `ShoppingListPagination`, `loader_options`
- **Line ranges:**
  - `class ShoppingListCreate(MealieModel)` — base (name, extras, created_at, updated_at): **lines 177–189**
  - `class ShoppingListSave(ShoppingListCreate)` — adds group_id, user_id: **lines 211–213**
  - `class ShoppingListSummary(ShoppingListSave)` — adds id, household_id, recipe_references, label_settings, `loader_options()` selectinload+joinedload chain: **lines 216–238**
  - `class ShoppingListPagination(PaginationBase)`: **lines 241–242**
  - `class ShoppingListUpdate(ShoppingListSave)`: **lines 245–247**
  - `class ShoppingListOut(ShoppingListUpdate)` — adds list_items via `ShoppingListUpdate`, declares `loader_options()` with full eager-loading: **lines 250–285**
- **Importance:** CRITICAL. These are the response shapes that need conditional `archived_at` and `archived_by: UserSummary | None` fields per spec §6.
- **Reason:** Inheritance chain is **Create → Save → Update → Out**; `Summary` branches off `Save`. Adding `archived_at: datetime | None = None` and `archived_by: UserSummary | None = None` on `ShoppingListSummary` will propagate to `ShoppingListOut` via the shared `Update` chain only if added on `Save` or higher. Best placement to honour spec §6 ("默认查询不返回这些字段") is to add them on `ShoppingListSummary` with defaults of `None`, then mutate the controller to filter them out unless the caller asked for `?archived=true|all`. The `loader_options` at lines 224–238 currently joins `User` with `load_only(User.household_id, User.group_id)` — the archived_by user fetch will need to extend that loader.

### A6. Nullable timestamp + nullable user FK precedents (for `archived_at` + `archived_by_user_id` modelling)
- **Path A:** `mealie/db/models/recipe/recipe.py`
  - `last_made: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime)`: **line 147**
  - `date_updated: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime)`: **line 145**
- **Path B:** `mealie/db/models/recipe/recipe_timeline.py`
  - `user_id: FilterableColumn[GUID] = mapped_column(GUID, ForeignKey("users.id"), nullable=False, index=True)`: **line 31**
  - `timestamp: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime, index=True)`: **line 43**
- **Path C:** `mealie/db/models/users/users.py`
  - Nullable self-referencing user FK: `user_id: Mapped[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)`: **line 33**
- **Path D:** `mealie/db/models/household/mealplan.py`
  - `user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)`: **line 67**
  - `household: AssociationProxy["Household"] = association_proxy("user", "household")`: **line 66**
- **Path E:** `mealie/db/models/_model_base.py`
  - `class SqlAlchemyBase(DeclarativeBase)` with `created_at`/`update_at`/`updated_at` (synonym) all NaiveDateTime: **lines 18–28**
- **Importance:** HIGH. Defines the **exact** types/conventions to use.
- **Reason:** `archived_at` should mirror `recipe.last_made` (line 147) — `FilterableColumn[datetime | None] = mapped_column(NaiveDateTime)` (no `nullable=True` needed; the `| None` annotation + lack of `nullable=False` makes it nullable). `archived_by_user_id` should mirror `mealplan.user_id` (line 67) — `FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)`. Optionally add a `archived_by: Mapped[Optional["User"]] = orm.relationship("User", foreign_keys=[archived_by_user_id])` — but disambiguation is needed since `user_id` already targets users.id; explicit `foreign_keys=` is required.

### A7. Event bus payload schemas
- **Path:** `mealie/services/event_bus_service/event_types.py`
- **Key symbols:** `EventTypes` (enum), `EventDocumentType`, `EventOperation`, `EventDocumentDataBase`, `EventShoppingListData`, `EventShoppingListItemData`, `EventShoppingListItemBulkData`, `Event`
- **Line ranges:**
  - `class EventTypes(Enum)` with docstring warning "any changes here must also be reflected in the database": **lines 13–60**
  - existing shopping_list_{created,updated,deleted}: **lines 42–44** (insertion point for `shopping_list_archived` / `shopping_list_unarchived`)
  - `class EventDocumentType(Enum)`: **lines 63–77** (insertion point if a new doc-type variant like `shopping_list_archive` is desired; current `shopping_list` may suffice)
  - `class EventOperation(Enum)` with `info/create/update/delete`: **lines 80–85** (consider adding `archive`/`unarchive` OR reusing `update`)
  - `class EventDocumentDataBase(MealieModel)`: **lines 88–91**
  - `class EventShoppingListData(EventDocumentDataBase)` — current payload, **only carries shopping_list_id**: **lines 130–132**
  - `class EventShoppingListItemData`: **lines 135–138**, `class EventShoppingListItemBulkData`: **lines 141–144**
  - `class Event(MealieModel)` with integration_id + document_data: **lines 194–207**
- **Path B:** `mealie/services/event_bus_service/event_bus_service.py`
  - `class EventBusService.dispatch(...)` — already loops per-household at **lines 82–96** (structural multitenancy guard for event payloads)
- **Importance:** CRITICAL. The richer payload spec §5 requires (`list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`) does not match the current `EventShoppingListData` shape (only `shopping_list_id`). A new subclass — e.g. `class EventShoppingListArchiveData(EventDocumentDataBase)` — is needed.
- **Reason:** Reusing `EventShoppingListData` would violate spec §5's enumeration of payload fields. The dispatch loop at lines 82–96 already ensures the event is published once per household and only to that household's subscribers, structurally meeting spec §5's "payload 必须不包含任何其他 household / group 的数据" — but **the payload class itself must not include cross-household state** (e.g. don't dump the whole list_items collection — restrict to `item_count` and an aggregate `total_estimated_amount`).

### A8. Supporting infra (used to assemble the surface)

| Path | Lines | Why it matters |
|------|-------|----------------|
| `mealie/routes/households/controller_shopping_lists.py` | full file 1–284 | The two controllers (`ShoppingListItemController` at 98–153 and `ShoppingListController` at 159–283) are where archive endpoints land; existing `publish_event` calls at 190–196, 207–213, 220–227, 246–252 are the template for `ShoppingListArchived`/`Unarchived` dispatches. |
| `mealie/routes/_base/base_controllers.py` | 192–214 (`BaseCrudController`), 199–213 (`publish_event`) | Confirms `publish_event(event_type, document_data, group_id, household_id, message)` signature — the new event dispatch will use this verbatim. |
| `mealie/services/household_services/shopping_lists.py` | 34–43 (`ShoppingListService.__init__`), 154–223 (`bulk_create_items`), 225–310 (`bulk_update_items`), 312–321 (`bulk_delete_items`), 541–554 (`create_one_list`) | This is the 22.7KB orchestration layer the spec §7 demands archive logic live in. The bulk methods (lines 154–321) are the right interception points for "frozen list rejects item mutations". |
| `mealie/repos/repository_factory.py` | 21–27 (imports of all ShoppingList* models), 53–59 (imports of all ShoppingList* schemas), 317–371 (`group_shopping_lists`, `group_shopping_list_item`, `group_shopping_list_item_references`, `group_shopping_list_recipe_refs`, `shopping_list_multi_purpose_labels` cached_properties) | Wiring point; no change needed unless a new specialised repo subclass for archive queries is added. Confirms RepositoryShoppingList is constructed with `group_id`+`household_id` (line 320). |
| `mealie/schema/user/user.py` | 191–197 (`class UserSummary`) | The exact Pydantic shape (`id`, `group_id`, `household_id`, `username`, `full_name`) for spec §6's `archived_by: UserSummary` response field. |
| `mealie/lang/messages/en-US.json` | 1–95 (full file, 4109 bytes) | JSON (not YAML — grounding §5 incorrect). Currently has 9 top-level keys (`generic`, `recipe`, `mealplan`, `user`, `group`, `exceptions`, `notifications`, `datetime`, `emails`). A new top-level `shopping-list` namespace must be added with kebab-case keys `archive.unchecked-items` and `archived.frozen`. **Per .github/copilot-instructions.md, only `en-US.json` may be edited — Crowdin manages all other locales.** |
| `mealie/db/models/household/events.py` | 15–57 (`GroupEventNotifierOptionsModel` with one bool column per EventType) | Confirms the hidden alembic migration: adding `shopping_list_archived` + `shopping_list_unarchived` boolean columns mirroring the existing `shopping_list_{created,updated,deleted}` columns at lines 35–37. |

---

## Likely surfaces for archive feature

Concrete change-set the design phase should target (each item is independently verifiable from the artifacts above):

1. **`mealie/db/models/household/shopping_list.py` (~lines 156–157)** — add inside `class ShoppingList` body (right after the existing `name` column declaration at line 158, or before `list_items` at line 159):
   ```python
   archived_at: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime)
   archived_by_user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)
   archived_by: Mapped[Optional["User"]] = orm.relationship("User", foreign_keys=[archived_by_user_id])
   ```
   Plus add `from datetime import datetime`, `NaiveDateTime` import, and disambiguate the existing `user` relationship via `foreign_keys=[user_id]`.

2. **NEW alembic migration** `mealie/alembic/versions/<ts>_<rev>_add_shopping_list_archive_columns.py` — model on artifact A3 (single FK column) and A3b (NaiveDateTime column) templates. `down_revision` should chain off `2187537c52b8` (current head per A3c lookup).

3. **SECOND alembic migration** `mealie/alembic/versions/<ts>_<rev>_add_shopping_list_archive_notifier_options.py` — model on artifact A3c. Adds `shopping_list_archived` + `shopping_list_unarchived` boolean columns to `group_events_notifier_options`. Without this the new EventTypes enum members will break the subscriber repo.

4. **`mealie/db/models/household/events.py` (lines 35–37)** — add two new boolean columns right after the existing `shopping_list_deleted` line.

5. **`mealie/services/event_bus_service/event_types.py`** — add at line 44 (after `shopping_list_deleted = auto()`):
   ```python
   shopping_list_archived = auto()
   shopping_list_unarchived = auto()
   ```
   And add a new payload class around line 134 (after `EventShoppingListData`):
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

6. **`mealie/schema/household/group_shopping_list.py`** — extend `ShoppingListSummary` (lines 216–238) and `ShoppingListOut` (lines 250–285) with `archived_at: datetime | None = None` and `archived_by: UserSummary | None = None`. Extend their `loader_options()` (lines 224–238 and 261–285) to `selectinload(ShoppingList.archived_by)` so the user join doesn't N+1.

7. **`mealie/repos/repository_shopping_list.py`** — expand from 12 lines to host the centralised filter logic (an `ArchivedFilter` enum: `EXCLUDE`/`ONLY`/`ALL`, plus `page_all_with_archive_filter(pagination, filter)` wrapping `page_all` after applying `_query().filter(ShoppingList.archived_at.is_(None))` etc.). All controllers route through this.

8. **`mealie/services/household_services/shopping_lists.py`** — new methods `archive_list(list_id, user_id) -> ShoppingListOut`, `unarchive_list(list_id) -> ShoppingListOut`, plus a `_guard_not_archived(list_id)` helper invoked from `bulk_create_items` (line 154), `bulk_update_items` (line 225), `bulk_delete_items` (line 312), and from the controller-level `update_one` (artifact A8/controller). Helper raises a typed exception that the controller maps to HTTP 409 + `shopping-list.archived.frozen`.

9. **`mealie/routes/households/controller_shopping_lists.py`** — two new endpoints on `ShoppingListController` (around line 230, after the existing CRUD block): `POST /{item_id}/archive` and `POST /{item_id}/unarchive`. Each calls the service method and dispatches the new `EventShoppingListArchiveData` payload via the existing `self.publish_event(...)` template at lines 190–196. The existing `get_all` (line 176) gets a new `archived: Literal["true","all"] | None = Query(None)` parameter that routes through artifact #7.

10. **`mealie/lang/messages/en-US.json`** — add top-level key:
    ```json
    "shopping-list": {
      "archive": { "unchecked-items": "Cannot archive: some items are unchecked" },
      "archived": { "frozen": "This shopping list is archived and cannot be modified" }
    }
    ```

11. **`tests/integration_tests/user_household_tests/test_group_shopping_lists.py`** — extend with archive/unarchive lifecycle + frozen-state 409 tests.

12. **`tests/multitenant_tests/case_shopping_lists.py`** (NEW) plus a register in `test_multitenant_cases.py` — model on existing `case_categories.py` / `case_foods.py` (peers in the same dir per `Get-ChildItem` above). Validates that archived lists are not visible from a sibling household / cross-group caller.

13. **`tests/unit_tests/`** — at least 4 service-layer tests for `archive_list`/`unarchive_list`/`_guard_not_archived`/the "all items checked" precondition.

---

## Cross-perspective questions

These need answers from the API perspective, the multitenancy perspective, the test perspective, and/or product/spec clarification — flagging for the next pipeline stages.

1. **API**: Should `?archived=true|all` return the **same** `ShoppingListSummary` shape (just with `archived_at` populated when non-null) or a distinct response model (e.g. `ArchivedShoppingListSummary`)? Spec §6 reads as a conditional shape, but Pydantic strict-mode prefers distinct types. → **Recommendation:** single shape with `archived_at: datetime | None = None`, no schema bifurcation.

2. **API**: How does `?archived=true` interact with the existing `query_filter` / pagination `?orderBy` parameters? Must `archived_at` become a sortable column (e.g. for "most recently archived first")? → Default `order_by="archived_at"` desc when `?archived=true|all`.

3. **Multitenancy**: When a user is deleted, what happens to `archived_by_user_id` (FK to `users.id`)? Spec doesn't say. → Need either `ON DELETE SET NULL` semantics (Postgres CASCADE behaviour) or an application-side check.

4. **Multitenancy**: Does the **owner** of an archived list (`shopping_lists.user_id`) being moved to a different household change visibility? The `household_id` association proxy goes through `user`, so a user move would reassign the archived list to a new household. Possibly a bug the CR phase should surface.

5. **State machine**: Spec §3 says PUT label-settings is NOT in the frozen list. Is that intentional (label_settings is a display ordering, not list content) or an oversight? `add_recipe_ingredients_to_list` (controller line 256) and `remove_recipe_ingredients_from_list` (line 274) also mutate items via the service — must they also reject when archived?

6. **Event payload**: Spec §5 lists `total_estimated_amount (如有)`. There is no `estimated_amount` column on `ShoppingListItem` (verified — see A2). The `extras` JSON column might be where consumers store it; otherwise this field should default to `None` and downstream code shouldn't rely on it.

7. **Concurrency**: Two users in the same household call `POST /archive` simultaneously. Without a unique partial index `WHERE archived_at IS NULL`, both succeed and the second silently overwrites `archived_by_user_id`. → Consider a check in the service: `if archived_at IS NOT NULL: noop / 409 already-archived`.

8. **Backups / exports**: How are archived lists treated by `mealie/services/backups_v2/` and `exporter/`? Out of scope per spec but called out in input.md §三环节考察点 for CR.

9. **Scheduled cleanup**: `tests/unit_tests/services_tests/scheduler/tasks/test_delete_old_checked_shopping_items.py` exists (per `Get-ChildItem` output), implying an existing cleanup task for old checked items. Does it need to exempt archived lists (so archived history isn't auto-pruned)? Likely yes; high-risk silent-data-loss bug if missed.

10. **Naming drift**: Grounding §3 says `mealie/repos/repository_shopping.py`; actual file is `repository_shopping_list.py` (verified `Get-ChildItem -Filter "*shopping*"`). Confirm the spec's references to "repository_shopping" land on `repository_shopping_list.py` to avoid creating a duplicate file.
