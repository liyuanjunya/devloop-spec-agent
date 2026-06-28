# Case 2 — API Perspective Exploration

> Scope: how Mealie's HTTP/route layer currently exposes shopping lists and
> shopping list items, so we can graft on archive/unarchive + frozen-state
> behavior **without rewriting the controller layer**.
>
> Source tree: `C:\Users\v-liyuanjun\Downloads\mealie\`
> Spec: `..\input.md` (5 new routes / 4 frozen routes / query-param semantics)
>
> Mealie convention reminder (from `.github/copilot-instructions.md`): routes
> are thin Controllers (`BaseUserController` / `BaseCrudController`) that
> delegate to a Service (`mealie/services/`) which coordinates Repos
> (`mealie/repos/`). Auto-filter to group/household via repo construction.
> Pydantic schemas use `*Create` / `*Update` / `*Out` / `*Save` suffixes.

---

## 1. Findings (verified by reading each file)

### 1.1 Current shopping list controller

| Path | `mealie/routes/households/controller_shopping_lists.py` |
|---|---|
| Importance | **CRITICAL** — every new route lives here |
| Symbols | `item_router` (line 38), `publish_list_item_events()` (41–95), `ShoppingListItemController` (98–153), `router` (156), `ShoppingListController` (159–283) |
| Reason | One file holds **both** routers — the items controller does **not** live in a separate `controller_shopping_list_items.py`. All 5 new endpoints and the 4 frozen-route mutations land in this one file. |

Key structural facts:
- Both controllers inherit `BaseCrudController` → automatic `self.user`, `self.repos` (group + household scoped), `self.publish_event(...)`, `self.t(...)`.
- `ShoppingListController.service` is `ShoppingListService(self.repos)` (cached_property, line 162–163). Already the right place to drop `archive_list()` / `unarchive_list()` business methods — controller stays a thin pass-through.
- `ShoppingListController.repo` is `self.repos.group_shopping_lists` (line 167) → `RepositoryShoppingList`.
- `mixins` (line 173) is `HttpRepo[ShoppingListCreate, ShoppingListOut, ShoppingListSave]` — the existing 404 wrapper for `get_one`/`update_one`/`delete_one`.

CRUD endpoints today:

| Method | Path | Handler | Line |
|---|---|---|---|
| GET | `/households/shopping/lists` | `get_all(q: PaginationQuery)` | 176–184 |
| POST | `/households/shopping/lists` | `create_one(data: ShoppingListCreate)` | 186–198 |
| GET | `/households/shopping/lists/{item_id}` | `get_one(item_id)` | 200–202 |
| PUT | `/households/shopping/lists/{item_id}` | `update_one(item_id, data)` | 204–215 **← FREEZE** |
| DELETE | `/households/shopping/lists/{item_id}` | `delete_one(item_id)` | 217–229 |
| PUT | `/households/shopping/lists/{id}/label-settings` | `update_label_settings` | 234–254 (also mutates archived list — consider freezing?) |
| POST | `/households/shopping/lists/{id}/recipe` | `add_recipe_ingredients_to_list` | 256–261 (consider freezing) |
| POST | `/households/shopping/lists/{id}/recipe/{recipe_id}` (deprecated) | `add_single_recipe_ingredients_to_list` | 263–272 (consider freezing) |
| POST | `/households/shopping/lists/{id}/recipe/{recipe_id}/delete` | `remove_recipe_ingredients_from_list` | 274–283 (consider freezing) |

### 1.2 Current shopping list **item** controller

| Path | `mealie/routes/households/controller_shopping_lists.py` (same file) |
|---|---|
| Importance | **CRITICAL** — 3 of the 4 frozen routes live here |
| Symbols | `item_router` (38), `ShoppingListItemController` (98–153) |
| Reason | All item mutations route through `ShoppingListService.bulk_create_items` / `bulk_update_items` / `bulk_delete_items` — that means the frozen-state guard naturally belongs in the **service layer** before the bulk operation runs. |

Item endpoints today (prefix `/households/shopping/items`):

| Method | Path | Handler | Line | Freeze? |
|---|---|---|---|---|
| GET | `` | `get_all` | 115–119 | no |
| POST | `/create-bulk` | `create_many` | 121–125 | **yes** (spec implies, see §3.1) |
| POST | `` | `create_one(data)` → `create_many([data])` | 127–129 | **YES** (explicit in spec) |
| GET | `/{item_id}` | `get_one` | 131–133 | no |
| PUT | `` | `update_many` | 135–139 | **yes** (spec implies) |
| PUT | `/{item_id}` | `update_one(data)` → `update_many([…])` | 141–143 | **YES** (explicit; also covers `checked` field per §3) |
| DELETE | `` | `delete_many(ids)` | 145–149 | **yes** (spec implies) |
| DELETE | `/{item_id}` | `delete_one(item_id)` → `delete_many([item_id])` | 151–153 | **YES** (explicit) |

> ⚠️ The spec only enumerates the **singular** PUT/POST/DELETE on `/items/{id}`,
> but the singular forms internally call the bulk forms (lines 129, 143, 153).
> So a single guard in the bulk-service entrypoints covers both surfaces. See
> "Cross-perspective questions" §4.

### 1.3 Router mount

| Path | `mealie/routes/households/__init__.py` |
|---|---|
| Importance | low (no change needed) |
| Symbols | `router` (15), mounts both `controller_shopping_lists.router` (22) and `controller_shopping_lists.item_router` (23) |
| Reason | New `/archive` and `/unarchive` POSTs are just decorated methods on `ShoppingListController` — they auto-mount via the existing include. **No changes to `__init__.py` needed.** |

Upstream the package mounts under `/api` in `mealie/routes/__init__.py:20,25` → final paths are `/api/households/shopping/lists/…`, matching the spec exactly.

### 1.4 GET list pagination & filtering

| Path | `mealie/repos/repository_generic.py` |
|---|---|
| Importance | **CRITICAL** for §7 ("centralize archive filter at repo layer") |
| Symbols | `RepositoryGeneric._filter_builder` (94–102), `RepositoryGeneric.page_all` (315–355), `RepositoryGeneric.add_pagination_to_query` (357–405), `GroupRepositoryGeneric` (489–503), `HouseholdRepositoryGeneric` (505–523) |
| Reason | Two seams compose every list/get-one query: |

1. `_filter_builder(**kwargs)` (94–102) — returns `{"group_id": …, "household_id": …}` plus any caller-supplied kwargs. Used by `page_all` (330), `get_all` (133), `get_one` (172). **This is the natural place to inject `archived_at IS NULL` defaults.**
2. `add_pagination_to_query` (357–405) routes `pagination.query_filter` through `QueryFilterBuilder` (line 369). That already lets callers pass `query_filter="archived_at IS NULL"` from the controller — **but** §7 explicitly forbids per-controller filter strings, so we route through `_filter_builder` instead.

`PaginationQuery.query_filter` is a free-form `str | None` (`schema/response/pagination.py:36`), so we *could* expose a sibling typed query param `archived: ArchivedFilter` on the controller and translate it inside the repo — that keeps controllers thin and makes the OpenAPI schema explicit.

Note: `filter_by(**fltr)` only works for **direct columns**. `archived_at` will be a real column, so this works; but `household_id` on `ShoppingList` is an `AssociationProxy` (see §1.7), which means today's "household scope" filter already relies on the `user` join — important context when designing the archived filter.

### 1.5 Permission / household scoping

| Path | `mealie/routes/_base/base_controllers.py` |
|---|---|
| Importance | high |
| Symbols | `_BaseController` (32–78), `BaseUserController` (132–172), `BaseCrudController` (192–214) |
| Reason | The scoping flows from `BaseUserController.group_id` (153–154) and `.household_id` (157–158), which return `self.user.group_id` / `self.user.household_id`. Those propagate into `self.repos = AllRepositories(session, group_id=…, household_id=…)` (49). |

Multi-tenancy guarantee: because `RepositoryShoppingList` extends `HouseholdRepositoryGeneric` (see `repos/repository_shopping_list.py:9` and `repository_factory.py:317–321`), every `get_one`/`page_all` automatically `.filter_by(household_id=…, group_id=…)`. A cross-household archive request returns 404 from `mixins.get_one` (`mixins.py:79–83`) — **no extra permission check needed** at the controller. This satisfies the multi-tenant test in input §4 "out of the box".

`BaseCrudController.publish_event(group_id, household_id, …)` (199–214) sets the event's tenant scope — caller-supplied, not auto-derived — so we must pass the **list's own** `group_id`/`household_id` when publishing archive/unarchive events (not `self.group_id`), matching the pattern at line 192/210/249.

### 1.6 i18n error pattern

| Path | `mealie/lang/messages/en-US.json` |
|---|---|
| Importance | high (§7 "i18n key must be added to en-US") |
| Symbols | `exceptions` namespace (lines 46–53), `notifications` namespace (54–62) |
| Reason | New keys live under `exceptions` (matches `username-conflict-error` precedent at 51). |

Translation accessor: `self.t("exceptions.shopping-list.archived-frozen", …)` via `_BaseController.t` (`base_controllers.py:42–44`) which delegates to `Translator.t(key, **kwargs)`.

**Per copilot-instructions: only modify `en-US.json` — every other locale is Crowdin-managed and PR-rejected if touched.** New keys to add:

```jsonc
"exceptions": {
  ...
  "shopping-list": {
    "archive": {
      "unchecked-items": "Cannot archive a shopping list while items remain unchecked"
    },
    "archived": {
      "frozen": "This shopping list is archived and cannot be modified. Unarchive it first."
    }
  }
}
```

(Exact key shape can be flat with dots or nested — the existing keys mix both
styles. Spec uses dotted form `shopping-list.archive.unchecked-items` /
`shopping-list.archived.frozen`, which is the natural JSON-nested form.)

### 1.7 ShoppingList model — what `archived_*` columns join

| Path | `mealie/db/models/household/shopping_list.py` |
|---|---|
| Importance | **CRITICAL** for migration + filter |
| Symbols | `ShoppingList` (147–181), `ShoppingListItem` (51–98), `session_buffer_context` (201), `update_shopping_lists` event listener (214–238) |
| Reason | (1) `household_id` on `ShoppingList` is an **`AssociationProxy`** to `user.household_id` (line 153), **not** a real column. The new `archived_at` filter is a *real* column on `ShoppingList` so it's cheap to index, but any join-based archive query must keep the `User` join intact (already present in `ShoppingListSummary.loader_options`, line 237). (2) The existing `after_flush` listener (214–238) bumps `updated_at` on item changes — that listener should be reviewed: do we want item-touch on an archived list to bump `updated_at`? Probably moot once item mutations are blocked. |

The new columns:
```python
archived_at: FilterableColumn[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
archived_by_user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), nullable=True)
archived_by_user: Mapped[Optional["User"]] = orm.relationship("User", foreign_keys=[archived_by_user_id])
```

`index=True` on `archived_at` is essential since every list-view query filters on it.

### 1.8 Existing 409 conflict example

| Path | `mealie/services/user_services/registration_service.py:83-86` and `mealie/routes/admin/admin_management_users.py:45-48` |
|---|---|
| Importance | medium (template for new 409s) |
| Reason | Exact existing pattern: `raise HTTPException(status.HTTP_409_CONFLICT, {"message": self.t("exceptions.username-conflict-error")})` |

**Caveat:** This is the *only* form of 409 in the codebase (verified by repo-wide grep — see findings above). It returns a `{"message": "…"}` dict, **not** the structured `ErrorResponse.respond(message=…)` form that 400/404s use (`mixins.py:59,64,82,93`). For consistency-with-richer-payloads we should prefer:

```python
raise HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail=ErrorResponse.respond(message=self.t("exceptions.shopping-list.archived.frozen")),
)
```

This stays aligned with `ErrorResponse` (`schema/response/responses.py:8-19`) and makes the response shape uniform across all error codes.

### 1.9 OpenAPI `response_model` + docstring conventions

| Path | `mealie/routes/households/controller_shopping_lists.py` (any handler) |
|---|---|
| Importance | low (cosmetic) |
| Reason | Existing handlers declare `response_model=…` on the decorator and use `status_code=201` for creates (line 186, 121, 127). Docstrings are *absent or 1-line* (e.g., line 268 `# Compatibility function for old API`). Bulk endpoints return `ShoppingListItemsCollectionOut`, single-resource endpoints return `ShoppingListOut`. No `responses={409: …}` declarations exist in the file → we **should** add them to the new archive/unarchive routes for accurate OpenAPI docs. |

Suggested decorator for the new archive route:
```python
@router.post(
    "/{item_id}/archive",
    response_model=ShoppingListOut,
    status_code=200,
    responses={
        409: {"model": ErrorResponse, "description": "List has unchecked items"},
        404: {"model": ErrorResponse, "description": "List not found"},
    },
)
def archive_one(self, item_id: UUID4) -> ShoppingListOut: ...
```

### 1.10 Event bus pattern (relevant since spec §5 adds two new event types)

| Path | `mealie/services/event_bus_service/event_types.py` |
|---|---|
| Importance | high (§5) |
| Symbols | `EventTypes` enum (13–60), `EventShoppingListData` (130–133), `EventDocumentDataBase` (88–91) |
| Reason | The `EventTypes` enum docstring (14–22) explicitly states **"any changes made here must also be reflected in the database (and likely requires a database migration)"** — i.e. adding `shopping_list_archived` / `shopping_list_unarchived` requires its own Alembic migration for the subscriber/notifier tables. |

The `event_bus_service.dispatch` signature (`event_bus_service.py:66-80`) already accepts `group_id` and `household_id` — so per spec §5 ("payload must contain *only* this household's data"), we just continue to pass `list.group_id` / `list.household_id` (mirroring lines 192/210/226 of the existing controller) and use a new `EventShoppingListArchivedData(EventDocumentDataBase)` subclass containing exactly the spec's payload fields (`list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`) — **no recipe refs, no other lists, no neighboring household data**.

---

## 2. New routes proposed (mapped to existing patterns)

| # | New route | Mirror existing route | Same file/line | Controller method to add | Service method to add |
|---|---|---|---|---|---|
| 1 | `POST /api/households/shopping/lists/{id}/archive` | `POST /api/households/shopping/lists/{id}/recipe` (controller_shopping_lists.py:256-261) — same "POST verb action on a list" shape, returns the updated `ShoppingListOut`, publishes one event | controller_shopping_lists.py — new method right after `delete_one` (~line 230) | `archive_one(self, item_id: UUID4) -> ShoppingListOut` | `ShoppingListService.archive_list(list_id, user_id) -> ShoppingListOut` |
| 2 | `POST /api/households/shopping/lists/{id}/unarchive` | Same as #1 | controller_shopping_lists.py — directly after #1 | `unarchive_one(self, item_id: UUID4) -> ShoppingListOut` | `ShoppingListService.unarchive_list(list_id) -> ShoppingListOut` |
| 3 | `GET /api/households/shopping/lists` (default = unarchived only) | **Modify** existing `get_all` (controller_shopping_lists.py:176-184) | controller_shopping_lists.py:176-184 | Add `archived: ArchivedFilter = Query(ArchivedFilter.exclude)` param to `get_all`; pass it through to `self.repo.page_all_with_archive(q, archived=…)` | New repo method `RepositoryShoppingList.page_all` override OR new `page_all_with_archive(...)` (see §3) |
| 4 | `GET /api/households/shopping/lists?archived=true` | Same handler as #3 | same | `archived=ArchivedFilter.only` branch of the same handler | same |
| 5 | `GET /api/households/shopping/lists?archived=all` | Same handler as #3 | same | `archived=ArchivedFilter.all` branch | same |

`ArchivedFilter` would be a new `StrEnum` in `schema/household/group_shopping_list.py`:

```python
class ArchivedFilter(StrEnum):
    exclude = "false"  # default — archived_at IS NULL
    only    = "true"   # archived_at IS NOT NULL
    all     = "all"    # no filter; response includes archived_at field
```

The 4 frozen-route enforcement points (cross-referenced with §1.2):

| # | Frozen route | Existing handler | Best place to inject 409 |
|---|---|---|---|
| F1 | `PUT /api/households/shopping/lists/{id}` | `ShoppingListController.update_one` (204-215) | **Service** — new `ShoppingListService.update_list_metadata` wrapping `mixins.update_one` after the frozen check; or simplest: inline check at the top of `update_one` controller |
| F2 | `POST /api/households/shopping/items` (+ `/create-bulk`) | `ShoppingListItemController.create_many` (121-125) | **Service** — `bulk_create_items` already iterates per-list (uses `existing_items_map[create_item.shopping_list_id]` at line 184) so it knows every distinct shopping_list_id without an extra query → cheap to check archived flag once per distinct list |
| F3 | `PUT /api/households/shopping/items/{id}` (+ bulk) | `ShoppingListItemController.update_many` (135-139) | **Service** — `bulk_update_items` same pattern (line 258) |
| F4 | `DELETE /api/households/shopping/items/{id}` (+ bulk) | `ShoppingListItemController.delete_many` (145-149) | **Service** — `bulk_delete_items` (312-321) needs an upfront lookup of distinct list_ids from item_ids; check archived on each. |

---

## 3. Frozen-state enforcement seam (where to inject the guard)

**Recommendation: service layer, single helper, called from every mutating service method.**

Three candidate seams, evaluated:

### Option A — Controller-layer guard (rejected)

Inline an `if list.archived_at: raise HTTPException(409, …)` at the top of every PUT/POST/DELETE controller. **Rejected** because:
- Spec §7 explicitly says "do not scatter archive logic across controllers".
- Item-controller methods take *item IDs*, not list IDs, so each controller would need to fetch the list first → duplicated query.
- HTTPException belongs at the HTTP boundary, but the *decision* belongs to the domain.

### Option B — Repository-layer guard (rejected)

Override `RepositoryShoppingList.update` (already overridden, see `repository_shopping_list.py:10-11`) and `RepositoryShoppingListItem.create/update/delete` to raise if parent list is archived. **Rejected** because:
- Repos in Mealie are intentionally dumb (no domain logic; verified across `repository_*.py`) — they don't even know about `HTTPException`/i18n.
- It would conflict with internal callers that legitimately mutate archived state — e.g., the `archive_list` service method itself sets `archived_at` via `repo.update(...)`. A repo-level guard would either need a bypass flag (smell) or would self-block.
- Item repo doesn't have a back-reference to "is parent list archived" without an extra join.

### Option C — Service-layer guard (recommended ✅)

Add **one** private helper on `ShoppingListService`:

```python
def _ensure_not_archived(self, shopping_list_ids: Iterable[UUID4]) -> None:
    """Raise 409 if any of the given lists is currently archived.

    Centralised guard for the §3 frozen-state rule. Called by every public
    service method that mutates a shopping list's content or items.
    """
    archived_ids = self.shopping_lists.get_archived_ids(set(shopping_list_ids))
    if archived_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse.respond(
                message=self.t("exceptions.shopping-list.archived.frozen"),
            ),
        )
```

Where:
- `RepositoryShoppingList.get_archived_ids(ids: set[UUID4]) -> set[UUID4]` is a single-roundtrip helper (`SELECT id FROM shopping_lists WHERE id IN :ids AND archived_at IS NOT NULL AND household_id = :hh`). Tenant filter still applied via repo scoping.
- The service holds `self.t` by accepting a translator at construction (today `ShoppingListService.__init__` takes only `repos` — minor signature change, or thread `t` through method args).

Call sites in the **service** (lines from current file):

| Service method | Action | Insert guard at |
|---|---|---|
| `bulk_create_items` (154) | uses `create_item.shopping_list_id` (line 184) | top of method, after line 162, on `{ci.shopping_list_id for ci in create_items}` |
| `bulk_update_items` (225) | uses `update_item.shopping_list_id` (line 258) | top of method, on distinct `shopping_list_id` set |
| `bulk_delete_items` (312) | takes `delete_items: list[UUID4]` of *item* ids | needs upfront `self.list_items.get_many(...)` to resolve parent list_ids, then guard |
| `add_recipe_ingredients_to_list` (413) | takes `list_id` | top of method |
| `remove_recipe_ingredients_from_list` (457) | takes `list_id` | top of method |
| (new) `update_list_metadata` | wraps `mixins.update_one` | top |
| (new) `archive_list` / `unarchive_list` | **bypass** — these are the exception in spec §3 | guard NOT applied; `unarchive_list` is the documented escape hatch |

This means the controller-side change is essentially zero for items (the guard fires automatically); for `PUT /lists/{id}` we either:
- Move `update_one` body into a new `ShoppingListService.update_list_metadata(list_id, data, user_id)` that runs the guard then delegates to `mixins.update_one`-equivalent (clean), OR
- Add a single guarding call at the top of the controller's `update_one` (lighter; consistent with `archive_one`'s placement). Either is fine; the **service** option is closer to spec §7's "centralize in service" spirit.

### List-view query filter (separate seam, repo layer)

For the GET list endpoint, the natural place is `RepositoryShoppingList` itself (subclass already exists at `repository_shopping_list.py:9`). Add:

```python
class RepositoryShoppingList(HouseholdRepositoryGeneric[ShoppingListOut, ShoppingList]):
    def page_all(  # type: ignore[override]
        self,
        pagination: PaginationQuery,
        override=None,
        search: str | None = None,
        archived: ArchivedFilter = ArchivedFilter.exclude,
    ) -> PaginationBase[ShoppingListSummary]:
        # delegate to the generic logic, but mix the archive filter
        # into the base filter set
        ...
```

Either by overriding `_filter_builder` to peek at `self._archived_filter` (mutable instance attr set per-request — ugly), or by literally re-implementing `page_all` with the archive predicate added via SQLAlchemy `where(...)`. Recommended path: a *minimal* override that calls `super().page_all(...)` but first sets a transient SQLAlchemy condition on the query — concretely, add an `archived` keyword to `RepositoryGeneric.page_all` itself (small change, all 1 caller in our scope) or expose a new `page_archived_aware(...)` method that wraps the generic one.

> **Bottom line for the seam question:** *Frozen-state guard → Service (one helper, ~6 call sites). Default-exclude-archived filter → Repository (one subclass override). No controller-side scatter.*

---

## 4. Cross-perspective questions

These are decisions the API exploration cannot answer alone:

1. **Bulk endpoints inside the freeze scope?** Spec §3 enumerates the singular `POST /items`, `PUT /items/{id}`, `DELETE /items/{id}` but **not** the bulk forms `POST /items/create-bulk`, `PUT /items` (bulk), `DELETE /items?ids=…`. Because the singular forms delegate to the bulk forms (controller_shopping_lists.py:129, 143, 153), a service-layer guard catches both — but if Spec intended only singular freezes (allowing bulk-edit), we'd need to put guards in the controller path instead. **Recommended interpretation: freeze the bulk forms too** — otherwise users could bypass by sending a 1-item bulk request, which is silly. → Confirm with spec author or treat singular as a subset of bulk.

2. **`/{id}/label-settings`, `/{id}/recipe`, `/{id}/recipe/{recipe_id}`, `/{id}/recipe/{recipe_id}/delete`** routes (controller_shopping_lists.py:234-283) all *materially mutate* a shopping list. Spec §3 lists 4 frozen routes but is silent on these. → Most likely they should be frozen too (a recipe added to an archived list violates "freeze"); needs confirmation. The "design" perspective and "spec" perspective should weigh in.

3. **What about cookbook / mealplan / export / analytics consumers of shopping lists?** Spec §90 (考察点 / Spec) explicitly asks: "是否枚举出**所有**消费 shopping list 的下游接口？" — i.e., the spec evaluator is looking for whether we identified non-obvious consumers. From API perspective the visible route surface is `controller_shopping_lists.py` only, but we should grep for `shopping_lists`/`group_shopping_lists`/`ShoppingListOut` usages in `mealie/services/backups/`, `mealie/services/group_services/`, `mealie/routes/groups/data_migrations.py`, and the `?include_archived` semantics for export need a decision. → "data" or "downstream" perspective should map this.

4. **Schema for the GET response with `archived=true`/`archived=all`** — spec §6 says "default query does *not* return `archived_at`/`archived_by`" but archived queries *do*. Pydantic's natural answer is two separate response models (`ShoppingListSummary` vs. `ShoppingListSummaryWithArchive`). Today the `get_all` endpoint declares `response_model=ShoppingListPagination` (controller line 176) which embeds `list[ShoppingListSummary]`. A schema split changes the generated OpenAPI + TypeScript types ⇒ requires `task dev:generate`. → Coordinate with "schema" perspective.

5. **`integration_id` of the archiver vs `archived_by_user_id`** — `BaseUserController.user.id` (line 154) is what we'd store. But Mealie supports API-token integrations (`get_integration_id` at base_controllers.py:140), and an integration's tokens still map to a user. Confirm we want `user.id` (the human owner of the token) and not "system" for integration-driven archives. → "auth" / "integrations" perspective.

6. **Cross-household same-group visibility** — spec §4 requires "同 group 内的其他 household 看不到对方的归档清单". Today's `HouseholdRepositoryGeneric` filter (line 519/523) already enforces this for **all** queries, archived or not, because `BaseUserController.household_id` returns `self.user.household_id`. ✅ No new code needed at API layer — but worth a test (input §8 multitenant tests). The `BaseAdminController` (`base_controllers.py:185-189`) clears household scoping, which means **admin** routes WOULD see all households' archived lists — that's pre-existing behavior, not a regression, but spec doesn't say whether admin-level archive operations are in scope. → "spec" perspective.

7. **Event bus migration for the 2 new EventTypes enum members** — `event_types.py:14-22` says new entries need an Alembic migration. That ripples into the Coding phase's "alembic migration must be backwards-compatible" requirement (§7). → "data" / "migration" perspective should own.

---

## Appendix — File quick-reference

| Concern | File | Lines |
|---|---|---|
| New routes go here | `mealie/routes/households/controller_shopping_lists.py` | after 229 (list controller), after 153 (item controller) |
| Frozen-state service guard | `mealie/services/household_services/shopping_lists.py` | new helper near 130; call from 154, 225, 312, 413, 457 |
| New `archive_list` / `unarchive_list` | same file | after `create_one_list` (line 541) |
| Centralised archived-filter on GET | `mealie/repos/repository_shopping_list.py` | extend the existing 12-line subclass |
| Schema for `ArchivedFilter` enum + `archived_at` / `archived_by` fields | `mealie/schema/household/group_shopping_list.py` | new enum + extend `ShoppingListSummary` (216), `ShoppingListOut` (250) |
| DB column + index | `mealie/db/models/household/shopping_list.py` | extend `ShoppingList` (147-181) |
| Alembic migration | `mealie/alembic/versions/` | new revision (per copilot-instructions `task py:migrate`) |
| New i18n keys (en-US only — do **not** touch other locales) | `mealie/lang/messages/en-US.json` | extend `exceptions` (46-53) |
| New EventTypes | `mealie/services/event_bus_service/event_types.py` | extend enum (42-44) + new `EventShoppingListArchivedData` class near 130 |
| Subscriber DB columns for the new EventTypes | model in `mealie/db/models/household/events.py` | requires its own migration (per event_types.py:14-22 docstring) |
