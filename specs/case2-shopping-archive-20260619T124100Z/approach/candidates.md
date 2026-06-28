# Stage 4 — Approach candidates

Three candidate approaches for the Shopping List Archive feature. All three share the same data-model additions (`archived_at`, `archived_by_user_id`) and event-bus additions; they differ in WHERE the frozen-state behavior is enforced.

> **Notation:** "Filter" = the default-exclude-archived behavior on `GET /lists`. "Guard" = the 409-on-mutation behavior for archived lists.

---

## Candidate A — Soft delete pattern (filter only, no explicit freeze)

**Concept.** Add `archived_at IS NOT NULL` as the only marker of "archived". `GET /lists` defaults to filtering it out; `?archived=true|all` reveals it. No additional enforcement — mutations on archived rows continue to work.

**Implementation sketch:**
- `mealie/db/models/household/shopping_list.py` — add `archived_at` + `archived_by_user_id` columns.
- `mealie/repos/repository_shopping_list.py` — extend `page_all` to accept `archived: ArchivedFilter`, append `.where(ShoppingList.archived_at.is_(None))` etc. as appropriate.
- `mealie/routes/households/controller_shopping_lists.py` — add `POST /{id}/archive` and `POST /{id}/unarchive`, plus `archived` query param on `get_all`.
- No frozen-state guard anywhere — `PUT /lists/{id}`, `POST /items`, etc. continue to mutate archived rows.

**Pros:**
- Smallest change footprint (~5–6 files modified).
- Zero risk of breaking existing test suite (no new exception path).
- Easiest to roll back if business decides "frozen" is too aggressive.
- Matches simplest interpretation of "soft delete" — the row stays mutable, only collection visibility changes.

**Cons:**
- **VIOLATES input §3** — "归档后的不可变性: …必须返回 409". The spec explicitly mandates that PUT/POST/DELETE on archived lists/items return 409 + `shopping-list.archived.frozen`. Without a guard, this requirement is unfulfilled.
- **User can corrupt history.** A user accidentally adds items to an archived list (perhaps via the recipe-add dialog that didn't filter archives correctly) and the historical record is silently mutated.
- **No event semantics.** `archive` is "just a column write" with no business meaning beyond visibility — diverges from event-bus dispatch expected by spec §5.
- **Scheduler still mutates archived lists** — `delete_old_checked_shopping_list_items.py` happily trims their items, which IS data loss on archived records.

**Verdict:** **Rejected.** Fails to satisfy explicit spec requirements (§3, §5 ordering with archive being a distinct lifecycle event).

---

## Candidate B — Soft delete + service-level frozen guard

**Concept.** Filter lives in repo. The 409 enforcement lives in `ShoppingListService` — every mutating service method calls a private `_ensure_not_archived(list_ids)` helper BEFORE delegating to repos. Controllers stay thin.

**Implementation sketch:**
- `mealie/db/models/household/shopping_list.py` — add the two columns.
- `mealie/repos/repository_shopping_list.py` — extend with archive-aware `page_all`; add minimal helper `get_archived_ids(ids: set[UUID4]) -> set[UUID4]` for the service to call.
- `mealie/services/household_services/shopping_lists.py`:
  - New `_ensure_not_archived(self, list_ids: Iterable[UUID4]) -> None` helper that calls `self.shopping_lists.get_archived_ids(...)` and raises `HTTPException(409, ErrorResponse.respond(message=self.t("shopping-list.archived.frozen")))` if non-empty.
  - Call `_ensure_not_archived({list.id})` at the top of: `bulk_create_items` (line 154), `bulk_update_items` (line 225), `bulk_delete_items` (line 312 — needs upfront fetch to resolve item-id → list-id), `add_recipe_ingredients_to_list` (line 413), `remove_recipe_ingredients_from_list` (line 457).
  - New service methods: `archive_list(list_id, user_id) -> ShoppingListOut`, `unarchive_list(list_id) -> ShoppingListOut`.
  - New `update_list_metadata(list_id, data, user_id)` wraps `mixins.update_one` with a guard, OR add a single-line guard at the top of `ShoppingListController.update_one` (it's the only PUT-on-list site).
- `mealie/routes/households/controller_shopping_lists.py` — add 2 new archive endpoints; modify `update_one` (204–215) to call the new service helper; no changes to item controller (the guard lives in service methods the item controller already calls).
- `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` — fetch lists with `archived=ArchivedFilter.exclude` so the scheduler skips archived rows naturally without triggering the guard.

**Pros:**
- **Single chokepoint per mutation surface** — the 5–6 service entry points all gate the same way.
- **Repos remain "dumb"** — no domain rules in the data-access layer, consistent with Mealie convention (verified by reading `repository_recipes.py`, `repository_meals.py`, etc. — all are slim data-access wrappers).
- **i18n + `HTTPException` live where they belong** — the service has `self.t` and is already the integration point for FastAPI exception translation.
- **The archive/unarchive service methods themselves don't need to bypass anything** — they call `self.shopping_lists.update(...)` directly with the new state, not `bulk_update_items`.
- **Easy to add another guarded operation later** — just call `self._ensure_not_archived(...)` at the top.

**Cons:**
- **Multiple call sites to remember.** A future developer adding a new mutating service method must remember to add the guard — there's no compile-time enforcement.
- **Item-deletion path needs an extra fetch.** `bulk_delete_items` receives item IDs, not list IDs; the guard requires `SELECT shopping_list_id FROM shopping_list_items WHERE id IN :ids` first.
- **Does not match input §7 literally.** Input §7 says "在 mealie/repos/repository_shopping.py 中**集中**实现归档过滤逻辑". "过滤逻辑" (filter logic) is what lives in the repo here, but if "归档逻辑" (archive logic) is interpreted broadly to include the guard, the user's preference is more centralised than service-layer.

**Verdict:** **Strong alternative** — would be the recommended choice if the user input were silent on this. But spec text explicitly biases toward the repo layer for centralisation.

---

## Candidate C — Soft delete + repository-level frozen guard ✅ SELECTED

**Concept.** Both the filter and the guard live in the repository layer. `RepositoryShoppingList` extends its existing `update` override (already present at lines 9–11) to raise a typed exception if the row is archived. A new `RepositoryShoppingListItem(HouseholdRepositoryGeneric[...])` subclass wraps `create_many`/`update_many`/`delete_many` with the same guard against the parent list. The service catches the typed exception and translates to `HTTPException(409, …)` because the service holds `self.t` for i18n.

**Implementation sketch:**

### Data layer
- `mealie/db/models/household/shopping_list.py` — add `archived_at: FilterableColumn[datetime | None] = mapped_column(NaiveDateTime, index=True)` and `archived_by_user_id: FilterableColumn[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True)`, plus relationship `archived_by: Mapped[Optional["User"]] = orm.relationship("User", foreign_keys=[archived_by_user_id])`. Disambiguate the existing `user` relationship with `foreign_keys=[user_id]`.
- `mealie/db/models/household/events.py` — add `shopping_list_archived` + `shopping_list_unarchived` Boolean columns after line 37.
- `mealie/alembic/versions/` — two new migration files (data + notifier).

### Repository layer (the centralisation point per input §7)
- `mealie/repos/repository_shopping_list.py`:
  - Add a typed exception class `class ShoppingListIsArchivedError(Exception): pass` (or import from a shared `mealie/core/exceptions.py`).
  - Add `ArchivedFilter` import; extend the existing `update(item_id, data)` override (lines 9–11) to fetch the row, raise `ShoppingListIsArchivedError(item_id)` if `archived_at is not None`, otherwise delegate to super. Add a `_bypass_archive_check` kwarg used internally by the new `archive`/`unarchive` mutators.
  - Add `page_all` override: accepts an extra `archived: ArchivedFilter = ArchivedFilter.exclude` parameter; composes the predicate on top of `_filter_builder` via `.where(...)`.
  - Add `archive(item_id, user_id) -> ShoppingListOut` — sets `archived_at = datetime.now(UTC)` + `archived_by_user_id = user_id`, calls `super().update(...)` to persist (bypass marker prevents self-block).
  - Add `unarchive(item_id) -> ShoppingListOut` — clears both fields, persists via super().
  - Add `get_archived_ids(ids: set[UUID4]) -> set[UUID4]` — single-roundtrip helper that returns the subset of `ids` currently archived. Used by `RepositoryShoppingListItem` (below) for the parent-list-archived check.
- **NEW file** `mealie/repos/repository_shopping_list_item.py`:
  - `class RepositoryShoppingListItem(HouseholdRepositoryGeneric[ShoppingListItemOut, ShoppingListItem])`.
  - Overrides `create_many(items)` — extracts distinct `{i.shopping_list_id for i in items}`, calls `repos.group_shopping_lists.get_archived_ids(...)`, raises `ShoppingListIsArchivedError` if non-empty.
  - Overrides `update_many(items)` — same pattern.
  - Overrides `delete_many(ids)` — first fetches `SELECT DISTINCT shopping_list_id FROM shopping_list_items WHERE id IN :ids` (one query), then checks via `get_archived_ids`.
- `mealie/repos/repository_factory.py` — line 325, swap raw `HouseholdRepositoryGeneric` for the new `RepositoryShoppingListItem`.

### Service layer (catches and translates)
- `mealie/services/household_services/shopping_lists.py`:
  - Import `ShoppingListIsArchivedError`.
  - Wrap each call to `bulk_create_items`/`bulk_update_items`/`bulk_delete_items` (or in a `try/except` at the bulk method bodies themselves) with a translator: `except ShoppingListIsArchivedError: raise HTTPException(409, ErrorResponse.respond(message=self.t("shopping-list.archived.frozen")))`.
  - New `archive_list(list_id, user_id) -> ShoppingListOut` — first validates "all items checked" precondition (raises 409 + `shopping-list.archive.unchecked-items`), then calls `self.shopping_lists.archive(list_id, user_id)`.
  - New `unarchive_list(list_id) -> ShoppingListOut` — calls `self.shopping_lists.unarchive(list_id)`.

### Controller layer (thin)
- `mealie/routes/households/controller_shopping_lists.py`:
  - Add `POST /{item_id}/archive` and `POST /{item_id}/unarchive` after line 229.
  - Add `archived: ArchivedFilter = Query(ArchivedFilter.exclude)` to `get_all` (line 176) and pass to `self.repo.page_all`.
  - `update_one` (204–215) needs ONE line at the top: try/except around `self.mixins.update_one` to translate `ShoppingListIsArchivedError` → 409 (the existing `mixins.update_one` calls `self.repo.update` which is now guarded).

### Other layers
- `mealie/services/event_bus_service/event_types.py` — add 2 enum members at line 44; add new payload class `EventShoppingListArchiveData` after line 132.
- `mealie/schema/household/group_shopping_list.py` — add `archived_at` + `archived_by` to `ShoppingListSummary` (line 216–238) and `ShoppingListOut` (250–285); add `ArchivedFilter(StrEnum)`; extend `loader_options`.
- `mealie/lang/messages/en-US.json` — add `shopping-list` namespace.
- `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` — pass `archived=ArchivedFilter.exclude` when paging shopping lists.

**Pros:**
- **Maximally centralised.** A single change to `RepositoryShoppingList.update` covers PUT /lists. A single new `RepositoryShoppingListItem` covers all item mutations.
- **Defense at the persistence boundary.** Even if a developer adds a new caller in the future, mutations cannot reach the database without passing the guard.
- **Naturally satisfies input §7.** "在 repository 集中实现归档过滤逻辑" reads literally — filter logic centralized; the guard logic is centralized in the same layer.
- **Existing `RepositoryShoppingList.update` override is already a hook.** No structural surgery — just expanding what the hook does.
- **Forces correct handling of bulk vs singular item operations.** Both surfaces go through `create_many`/`update_many`/`delete_many` (verified in controller lines 121–153), so the guard inherently covers both.

**Cons / risks (addressed below):**
1. **"Repos in Mealie are intentionally dumb"** (api perspective Option B rejection point #1). Addressed: the repo raises a TYPED exception (not `HTTPException`), so it doesn't import HTTP / i18n machinery. The service catches and translates. Compromise preserves dumbness of the repo for HTTP concerns while admitting one domain rule that's intrinsic to the entity's state machine.
2. **"Internal callers that legitimately mutate archived state would self-block"** (api perspective Option B rejection point #2). Addressed: the `archive`/`unarchive` mutators in the repo bypass the guard via an internal-only mechanism (e.g., `_bypass_archive_check=True` kwarg on a private `_update_raw` method, OR by writing the new state via `self.session.execute(update(...))` directly without going through the public `update`).
3. **"Item repo doesn't have a back-reference to is-parent-archived"** (api perspective Option B rejection point #3). Addressed: the new `RepositoryShoppingListItem` does ONE roundtrip `get_archived_ids` per bulk call, using the parent repository — this is the same cost the service-layer approach would incur, just relocated.
4. **Extra repo file + factory tweak.** Yes — small structural change but stays small. (NEW file is ~50 lines.)
5. **Slightly harder unit testing of the guard.** Repo-level errors require slightly more orchestration to test in isolation. Mitigated by writing service-layer integration tests where the translation also matters.

**Verdict:** **Selected.** Best match for input §7's "centralised" mandate; addresses all api-perspective concerns through the typed-exception + bypass-mechanism pattern; ensures defense-in-depth at the persistence boundary.

---

## Comparison matrix

| Criterion | A. Filter only | B. Service guard | **C. Repo guard ✅** |
|-----------|:--------------:|:----------------:|:------------------:|
| Satisfies input §3 (409 on archived mutation) | ❌ | ✅ | ✅ |
| Satisfies input §7 ("centralised") | partial | partial | ✅ |
| Defense at persistence boundary | ❌ | ❌ | ✅ |
| Future-proof against new mutation call sites | ❌ | ⚠️ (must remember to add guard) | ✅ |
| Repos remain "dumb" w.r.t. HTTP/i18n | ✅ | ✅ | ✅ (typed exception only) |
| Touches `delete_old_checked_shopping_list_items.py` | required | required | required |
| New files added | 0 | 0 | 1 (`repository_shopping_list_item.py`) |
| Files modified | ~6 | ~7 | ~9 |
| Lines of new code (est.) | ~150 | ~250 | ~280 |
| Unit-test surface | small | medium | medium (typed exception class) |
| Risk of breaking existing tests | low | medium | medium |
| Aligns with the task instruction's named pick | ❌ | ❌ | ✅ |

---

## Decision

**Selected: Candidate C — Soft delete + repository-level frozen guard.**

Rationale captured in `approach/selected.md`.
