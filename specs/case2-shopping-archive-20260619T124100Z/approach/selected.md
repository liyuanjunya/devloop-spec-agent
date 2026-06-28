# Stage 4 — Selected approach

## Decision

**Candidate C: Soft delete + repository-level frozen guard.**

> Source of truth: `approach/candidates.md` evaluation table.
> Input alignment: §7 — "在 mealie/repos/repository_shopping.py 中**集中**实现归档过滤逻辑（不要在每个 controller 中手写过滤）". Repository-level guard places both the filter AND the freeze guard in `repository_shopping_list.py`, fully satisfying the "centralised" mandate at the strongest possible layer.

---

## Why this approach wins

1. **Defense at the persistence boundary.** Any path that ultimately writes through `RepositoryShoppingList.update` or `RepositoryShoppingListItem.{create,update,delete}_many` is automatically guarded — a future developer adding a new mutation route cannot bypass the check by forgetting a service-level helper.

2. **The existing override is the natural seam.** `mealie/repos/repository_shopping_list.py:9-11` already overrides `update`. We're growing that override from a one-line passthrough into a guarded passthrough — no structural surgery, just expansion of an existing hook.

3. **Matches the user input's wording.** Input §7 explicitly calls for centralisation in the repository file. Service-layer (Candidate B) requires interpreting "filter logic" narrowly; repository-layer (Candidate C) satisfies both narrow and broad readings.

4. **Addresses api-perspective's objections to "Option B (Repo-level guard)" via three concrete mechanisms** (see §"Addressing API perspective concerns" below).

5. **Filter + guard share one file.** The reader only has to look in one place to understand the archive lifecycle behavior. `RepositoryShoppingList` grows from 12 lines to ~80 lines but stays a single conceptual unit.

---

## High-level architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Controller layer (thin):                                                │
│   ShoppingListController.archive_one / unarchive_one                    │
│   ShoppingListController.update_one (existing, +1-line try/except)      │
│   ShoppingListController.get_all (existing, +1 query param)             │
│   ShoppingListItemController.* (existing, NO changes)                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ↓ calls
┌─────────────────────────────────────────────────────────────────────────┐
│ Service layer (translates typed exception → HTTP):                      │
│   ShoppingListService.archive_list / unarchive_list   (NEW)             │
│   ShoppingListService.bulk_create_items / bulk_update_items /           │
│     bulk_delete_items  (existing, +try/except wrapper)                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ↓ calls
┌─────────────────────────────────────────────────────────────────────────┐
│ Repository layer (CENTRALISED archive logic — input §7):                │
│   RepositoryShoppingList (extended):                                    │
│     - update(): raises ShoppingListIsArchivedError if row is archived   │
│     - archive(): bypasses guard, sets archived_at + archived_by_user_id │
│     - unarchive(): bypasses guard, clears both fields                   │
│     - page_all(archived: ArchivedFilter): default-exclude / only / all  │
│     - get_archived_ids(ids): bulk helper for item repo                  │
│   RepositoryShoppingListItem (NEW subclass):                            │
│     - create_many() / update_many() / delete_many(): guards via         │
│       RepositoryShoppingList.get_archived_ids                           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ↓ writes
┌─────────────────────────────────────────────────────────────────────────┐
│ Data layer:                                                             │
│   ShoppingList: + archived_at + archived_by_user_id                     │
│   GroupEventNotifierOptionsModel:                                       │
│     + shopping_list_archived + shopping_list_unarchived                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Concrete change list (final)

### NEW files
1. `mealie/repos/repository_shopping_list_item.py` — `RepositoryShoppingListItem(HouseholdRepositoryGeneric[...])` with guarded `create_many` / `update_many` / `delete_many`.
2. `mealie/alembic/versions/<ts>_<rev>_add_shopping_list_archive_columns.py` — adds `archived_at` + `archived_by_user_id` to `shopping_lists`.
3. `mealie/alembic/versions/<ts>_<rev>_add_shopping_list_archive_notifier_options.py` — adds `shopping_list_archived` + `shopping_list_unarchived` to `group_events_notifier_options`.
4. `mealie/core/exceptions.py` — add `ShoppingListIsArchivedError(Exception)` (or alternatively, define inside `repository_shopping_list.py`; preferred location is `core/exceptions.py` for the same reason `UnexpectedNone` lives there per `services/household_services/shopping_lists.py:5`).
5. `tests/multitenant_tests/case_shopping_list_archive.py` — `ArchivedShoppingListsTestCase(ABCMultiTenantTestCase)`.
6. `tests/multitenant_tests/test_shopping_list_archive_household.py` — cross-household-same-group isolation tests (h2_user-based).

### Modified files (≈ 13)
1. `mealie/db/models/household/shopping_list.py` — extend `ShoppingList` (lines 147–181) with 2 new columns + 1 new relationship.
2. `mealie/db/models/household/events.py` — extend `GroupEventNotifierOptionsModel` (lines 35–37) with 2 new boolean columns.
3. `mealie/services/event_bus_service/event_types.py` — extend `EventTypes` enum at line 44; add `EventShoppingListArchiveData` class after line 132.
4. `mealie/schema/household/group_shopping_list.py` — add `ArchivedFilter(StrEnum)` (top of file); extend `ShoppingListSummary` (216–238) + `ShoppingListOut` (250–285) with `archived_at` and `archived_by`; extend `loader_options` to eager-load `archived_by`.
5. `mealie/repos/repository_shopping_list.py` — grow from 12 lines to ~80 lines per architecture above.
6. `mealie/repos/repository_factory.py` — line 325 swap `HouseholdRepositoryGeneric` → `RepositoryShoppingListItem`.
7. `mealie/services/household_services/shopping_lists.py` — add `archive_list` / `unarchive_list`; wrap existing `bulk_*` methods to translate `ShoppingListIsArchivedError` → `HTTPException(409, …)`.
8. `mealie/routes/households/controller_shopping_lists.py` — add 2 endpoints after line 229; modify `get_all` (176–184) for `archived` query param; modify `update_one` (204–215) with try/except for `ShoppingListIsArchivedError`.
9. `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` — pass `archived=ArchivedFilter.exclude` to `page_all` at line 69 (CRITICAL-4 fix).
10. `mealie/lang/messages/en-US.json` — add new top-level `shopping-list` namespace with two keys.
11. `tests/fixtures/fixture_shopping_lists.py` — add `archived_list` / `archived_list_with_items` / `h2_list_with_items` fixtures.
12. `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` — append archive lifecycle / frozen-state / query-behavior tests.
13. `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py` — append item-level 409 tests (per spec §8 bullet 3).
14. `tests/multitenant_tests/test_multitenant_cases.py` — add `ArchivedShoppingListsTestCase` to `all_cases` at lines 13–19.

### Auto-regenerated (via `task dev:generate`)
- `frontend/app/lib/api/types/household.ts` — new optional fields on schema types.
- `frontend/app/lib/api/types/events.ts` — new enum members + payload class.
- `mealie/schema/household/__init__.py` — re-export of `ArchivedFilter`.
- `tests/utils/api_routes/__init__.py` — new route helpers `households_shopping_lists_item_id_archive(id)`, `households_shopping_lists_item_id_unarchive(id)`.

---

## Addressing API perspective's three concerns (re: repo-level guard)

API perspective rejected the repo-level guard ("Option B" in its terms) for three reasons. Each is fully addressable:

### Concern 1: "Repos in Mealie are intentionally dumb (no domain logic; verified across repository_*.py) — they don't even know about HTTPException/i18n."

**Resolution.** The repository does NOT raise `HTTPException` and does NOT call any i18n function. It raises a typed Python exception (`ShoppingListIsArchivedError`) — a pure-Python concept independent of HTTP, FastAPI, or i18n. The exception carries the offending `list_id` for caller context.

The **service layer** catches this typed exception and translates it to `HTTPException(409, ErrorResponse.respond(message=self.t("shopping-list.archived.frozen")))`. The service is where `self.t` is available and HTTP semantics belong. This is exactly the same pattern used by `UnexpectedNone` (defined in `mealie/core/exceptions.py`, raised by repos, sometimes caught and translated by services) — see `mealie/services/household_services/shopping_lists.py:469-470` for an existing example.

The "dumbness" invariant is preserved: repos still don't know about HTTP, FastAPI, or i18n.

### Concern 2: "It would conflict with internal callers that legitimately mutate archived state — e.g., the archive_list service method itself sets archived_at via repo.update(...). A repo-level guard would either need a bypass flag (smell) or would self-block."

**Resolution.** The repository exposes TWO public mutators for state changes:
- `update(item_id, data)` — guarded. Raises `ShoppingListIsArchivedError` if the row is currently archived. Used by every external caller (controllers, services, mixins).
- `archive(item_id, user_id)` and `unarchive(item_id)` — explicitly state-transition methods. These do NOT call the guarded `update`; they perform the SQL update directly via `self.session.execute(sa.update(ShoppingList).where(ShoppingList.id == item_id).values(...))` or by accessing `super().update` via a private alias.

This is the same pattern used in `mealie/repos/repository_users.py` for password updates vs profile updates — separate public methods for distinct state transitions. There's no "bypass flag" needed; the two state transitions get dedicated public methods.

### Concern 3: "Item repo doesn't have a back-reference to is-parent-archived without an extra join."

**Resolution.** The new `RepositoryShoppingListItem.create_many / update_many / delete_many` makes ONE extra query per bulk call:
- For `create_many`/`update_many`: `distinct_list_ids = {item.shopping_list_id for item in items}` (free, in-memory), then `archived_ids = self.repos.group_shopping_lists.get_archived_ids(distinct_list_ids)` → ONE `SELECT id FROM shopping_lists WHERE id IN :ids AND archived_at IS NOT NULL` query.
- For `delete_many(ids: list[UUID4])`: ONE extra `SELECT DISTINCT shopping_list_id FROM shopping_list_items WHERE id IN :ids` query, then `get_archived_ids`.

This is the same number of queries the service-layer approach would issue. The cost is paid once per bulk call, not per item. For singular endpoints (which delegate to bulk per controller lines 129, 143, 153), it's one extra roundtrip per request — acceptable given the security-critical nature of the guard.

---

## Public API surface (frozen contract for downstream phases)

### New typed exception
```python
# mealie/core/exceptions.py
class ShoppingListIsArchivedError(Exception):
    """Raised when a write would mutate a shopping list (or its items) that is archived."""
    def __init__(self, shopping_list_ids: set[UUID4]) -> None:
        self.shopping_list_ids = shopping_list_ids
        super().__init__(f"shopping list(s) archived: {sorted(shopping_list_ids)}")
```

### New `ArchivedFilter` enum
```python
# mealie/schema/household/group_shopping_list.py
class ArchivedFilter(StrEnum):
    exclude = "false"   # default — archived_at IS NULL only
    only    = "true"    # archived_at IS NOT NULL only
    inclusive = "all"   # no filter; both archived & active returned
```

### New event payload class
```python
# mealie/services/event_bus_service/event_types.py
class EventShoppingListArchiveData(EventDocumentDataBase):
    document_type: EventDocumentType = EventDocumentType.shopping_list
    shopping_list_id: UUID4
    shopping_list_name: str | None = None
    household_id: UUID4
    archived_by_user_id: UUID4 | None = None
    item_count: int = 0
    total_estimated_amount: float | None = None
```

### Schema additions (both apply to `ShoppingListSummary` AND `ShoppingListOut`)
```python
archived_at: datetime | None = None
archived_by: UserSummary | None = None
```

### New repository public methods
```python
class RepositoryShoppingList(HouseholdRepositoryGeneric[ShoppingListOut, ShoppingList]):
    def update(self, item_id, data) -> ShoppingListOut: ...   # NOW GUARDED
    def archive(self, item_id: UUID4, user_id: UUID4) -> ShoppingListOut: ...    # NEW
    def unarchive(self, item_id: UUID4) -> ShoppingListOut: ...                  # NEW
    def page_all(self, pagination, override=None, search=None,
                 archived: ArchivedFilter = ArchivedFilter.exclude
                 ) -> PaginationBase[ShoppingListSummary]: ...                    # OVERRIDE
    def get_archived_ids(self, ids: set[UUID4]) -> set[UUID4]: ...               # NEW
```

### New service methods
```python
class ShoppingListService:
    def archive_list(self, list_id: UUID4, user_id: UUID4) -> ShoppingListOut: ...    # NEW
    def unarchive_list(self, list_id: UUID4) -> ShoppingListOut: ...                  # NEW
```

### New controller endpoints
```python
@router.post("/{item_id}/archive", response_model=ShoppingListOut,
             responses={409: {"model": ErrorResponse, "description": "..."}})
def archive_one(self, item_id: UUID4) -> ShoppingListOut: ...

@router.post("/{item_id}/unarchive", response_model=ShoppingListOut)
def unarchive_one(self, item_id: UUID4) -> ShoppingListOut: ...
```

### New i18n keys
```jsonc
// mealie/lang/messages/en-US.json
"shopping-list": {
  "archive": {
    "unchecked-items": "Cannot archive a shopping list while items remain unchecked"
  },
  "archived": {
    "frozen": "This shopping list is archived and cannot be modified. Unarchive it first."
  }
}
```

---

## What the spec phase locks in

1. ✅ **Repository-layer centralisation** — both filter and guard live in `repository_shopping_list.py` (+ new sibling `repository_shopping_list_item.py`).
2. ✅ **Typed exception pattern** — `ShoppingListIsArchivedError` (Python exception) is the transport between layers; HTTP/i18n translation happens at service layer.
3. ✅ **Two-migration sequence** — `(a) shopping_lists columns` then `(b) group_events_notifier_options columns`.
4. ✅ **Default-include `archived_at` in schema** (sent as `null` for active rows). Filter behavior is enforced at the **request** level (`get_all` default-omits archived rows from the collection), NOT at the field-projection level.
5. ✅ **Scheduler skip** — `delete_old_checked_shopping_list_items.py` filters with `archived=ArchivedFilter.exclude` to avoid triggering the guard from a cron context.
6. ✅ **Frozen scope = 4 spec'd routes + their bulk siblings** — explicitly NOT `label-settings`, `recipe-add`, `recipe-remove` (those are flagged in `needs_clarification`).

These decisions are now binding for `spec.md` / `spec.json` and downstream design/coding/CR phases.
