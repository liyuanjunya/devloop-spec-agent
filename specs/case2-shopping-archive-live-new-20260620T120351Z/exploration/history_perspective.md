# Case 2 — Shopping List Archive: History Perspective

> Repository: `C:\Users\v-liyuanjun\Downloads\mealie\` (branch `devloop-baseline`, upstream `origin/mealie-next`, 5,014 commits — full clone, no shallow file).
> All git commands below were executed with `git --no-pager`. Per-file logs use `--follow` because PR #3970 renamed the `group/` tree to `households/` in Aug 2024 and bare logs miss the historical context.

> **Path corrections vs. the input spec:**
> - Repository file is `mealie/repos/repository_shopping_list.py` (singular `list`), not `repository_shopping.py`.
> - Model file is `mealie/db/models/household/shopping_list.py` (single file, no `shopping_list*.py` siblings under `household/`).
> - All four target files exist; sizes are: service 23,332 B (matches the spec's "22.7 KB" figure), controller 12,268 B, schema 10,325 B, repo only **492 B** (a thin override — see Risk hotspot #1).

---

## Top 15 recent commits with hash + summary + impact

These are the most recent commits (with `--follow`) that touch the four target files, plus closely-coupled files (event bus, household preferences, alembic migrations) that any archive PR must respect.

| # | Hash | Date | PR | Summary | Impact on archive feature |
|---|------|------|----|---------|---------------------------|
| 1 | `4a099c16` | 2026-06-18 | #7766 | `fix: Various lint issues` | Ruff baseline – any new code must pass `task py:check`. |
| 2 | `642c826f` | 2026-05-21 | #7629 | `fix: Protect sensitive data in query filter API (GHSA-8m57-7cv5-rjp8)` | **High** – rewrote `mealie/db/models/household/shopping_list.py` (62 lines changed) to use `FilterableColumn[…]` annotations everywhere. **Any new column (`archived_at`, `archived_by_user_id`) must use the `FilterableColumn` wrapper** or it will be silently un-filterable and may bypass the security guard. Same PR added `mealie/db/models/_filterable_column.py`. |
| 3 | `742b498c` | 2026-05-?? | #7625 | `fix: enforce ownership check on recipe deletion (GHSA-x5v9-9jvh-7c7q)` | **High** – sets precedent that destructive ops must validate household ownership at the controller layer, not rely solely on repo filters. The archive/unarchive endpoints need the same explicit guard. |
| 4 | `823b938a` | 2026-05-?? | #7651 | `fix: enforce organize-group-data permission on food/tag/category mutations` | Pattern: explicit permission gate before mutation. Archive should check `can_manage_household` or equivalent before mutating list state. |
| 5 | `3d6ff523` | 2026-05-?? | #7638 | `fix: return HTTP 400 for duplicate tag and label creation` | Recent precedent for **what status code to use for state-violation errors**. Spec mandates 409; verify that `HTTPException(status_code=409, detail={"message": t("...")})` follows the same error envelope used here. |
| 6 | `e52a887e` | 2026-03-26 | #7015 | `fix: publish all mealplan create, update, and delete events` | **Very high** – this is the most recent **event-bus payload change** and the canonical template for adding new event types. It added 2 enum members to `EventTypes`, 1 alembic migration (`add_mealplan_updated_and_deleted_to_subscribers`), 1 entry in `frontend/lib/api/types/household.ts`, frontend notifier UI, and an integration test for the new events. The archive PR must follow this same checklist for `shopping_list_archived` / `shopping_list_unarchived`. |
| 7 | `d2b0681d` | 2026-04-11 | #7431 | `feat: Announcements` | The mass-commit that shows up first in plain (non-`--follow`) logs for every shopping list file. Did **not** functionally change shopping lists – it cascaded `FilterableColumn` cleanup. Safe to ignore for archive logic. |
| 8 | `6a8eae7c` | 2026-05-27 | #7689 | `fix: Make most recipe action columns filterable` | Same `FilterableColumn` pattern as #2; reinforces that new columns must declare filterability deliberately. |
| 9 | `b5c089f5` | 2026-02-?? | #7121 | `feat: Unit standardization / conversion` | Last **functional** change to `mealie/services/household_services/shopping_lists.py`. Added unit-merge logic; the file is otherwise quiet. Archive logic should slot in cleanly without conflicting with merge code. |
| 10 | `6cbc308d` | 2025-08-16 | #5892 | `fix: Add Recipe From Another Household To Shopping List` | **High** – existing precedent for **cross-household shopping list interactions**. Added 62 lines of integration tests in `test_group_shopping_lists.py` using the `h2_user` fixture. Reuse this exact test infrastructure for the multitenant test suite. |
| 11 | `716c85cc` | 2025-02-27 | #5054 | `fix: Bulk Add Recipes to Shopping List` | Last large schema/controller co-edit (the canonical "feature touching schema + controller + service + tests" template). Modified 4 of the 4 target files plus `tests/utils/api_routes/__init__.py` (auto-generated route helper – must regenerate via `task dev:generate`). |
| 12 | `f4827abc` | 2024-06-29 | #3760 | `feat: Offline Shopping List` | **High** – introduced the PWA offline queue (`frontend/app/composables/use-shopping-list-item-actions.ts`, 164 lines) that buffers create/update/delete in `localStorage`. **A stale offline client may try to mutate a list that has since been archived – the spec's 409 must round-trip cleanly through this queue without poisoning local state.** |
| 13 | `eb170cc7` | 2024-08-22 | #3970 | `feat: Add Households to Mealie` | The mega-PR that introduced household scoping (renamed `group/` → `households/`, moved 13 shopping-list-related files). Establishes the `AssociationProxy` pattern used at line 153–154 of `shopping_list.py` (`household_id = association_proxy("user", "household_id")`). **The new `archived_by_user_id` FK should sit on `ShoppingList` directly, not via an association proxy, since it represents a discrete action attribution.** |
| 14 | `245ca5fe` | 2025-?? | #5684 | `feat: Remove "Is Food" and "Disable Amounts" Flags` | Last alembic migration touching `ShoppingListItem`/`ShoppingList` columns. Template for column-add migrations: drop-and-recreate flow with `op.add_column` for SQLite + Postgres compatibility. |
| 15 | `e9892aba` | 2025-?? | #4616 | `feat: Move "on hand" and "last made" to household` | Precedent for **moving / introducing user_id-typed FKs scoped to a household**. The `archived_by_user_id` column should mirror the `user_id` FK pattern at line 155 (`mapped_column(GUID, ForeignKey("users.id"), nullable=False, index=True)`) but with `nullable=True` and a CHECK constraint mirroring the rule "`archived_by_user_id IS NULL` when `archived_at IS NULL`". |

---

## Prior soft-delete / archive patterns

**Direct grep for `archived_at|is_archived|archived_by` and `deleted_at|soft.delete|is_deleted` across all of `mealie/`:**
- Only **one** match in the entire backend: `mealie/schema/static/recipe_keys.py:31` — `archived_at = "archivedAt"`. This is a **Schema.org JSON-LD key constant** used by the recipe scraper, not a Mealie data-model field. No business logic consumes it.
- **No `deleted_at` or `soft_delete` anywhere.** Mealie uses hard `DELETE` for every entity and relies on `cascade="all, delete, delete-orphan"` SQLAlchemy relationships (see `shopping_list.py:159–175`).

**Closest analogous pattern** — boolean preference + cross-household lock:
- `mealie/db/models/household/preferences.py:29` — `lock_recipe_edits_from_other_households: FilterableColumn[bool | None]` (default `True`). When set, mutations from outside the owning household return 409/403.
- Used in `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:362–390` with `@pytest.mark.parametrize("household_lock_recipe_edits", [True, False])` to drive both branches.
- **This is the conceptually closest existing mechanism** but is preference-based (sticky toggle) rather than per-row state. The archive feature is genuinely **new ground** — there is no precedent in Mealie for a per-row "frozen" status column on any entity.

**Implications:**
1. There is no shared mixin to extend (no `ArchivableMixin`, no `SoftDeleteMixin`). The columns go directly on `ShoppingList`.
2. There is no shared filter helper to reuse. Spec §7 demands "集中实现归档过滤逻辑 in `repository_shopping_list.py`" — this is correct **and** sets the precedent for future archivable entities; it should be implemented thoughtfully (e.g., a method like `page_all(..., include_archived: bool = False, archived_only: bool = False)` on `RepositoryShoppingList`) rather than ad-hoc filters inside `get_all`.
3. There is no precedent for whether `GET /api/households/shopping/lists/{id}` should return an archived list. The spec doesn't pin this — recommend it returns the list with `archived_at` populated (admin/member can always view by id) and only the **collection** endpoint filters.

---

## Recent event bus payload changes — for risk assessment

| Hash | PR | What changed | Lesson for archive PR |
|------|----|--------------|-----------------------|
| `e52a887e` | #7015 | Added `mealplan_entry_updated` + `mealplan_entry_deleted` to `EventTypes` enum (`mealie/services/event_bus_service/event_types.py:38–40`) + alembic migration `cdc93edaf73d_add_mealplan_updated_and_deleted_to_subscribers.py` to add boolean columns on the notifier-subscriber table. Updated `mealie/schema/household/group_events.py` to expose the new flags in `GroupEventNotifierOptions`. Frontend got new toggle UI in `pages/household/notifiers.vue` + new type fields. | **Adding `shopping_list_archived` / `shopping_list_unarchived` is the same shape of change.** Checklist: enum member → migration adding `bool` column on subscribers table → schema `GroupEventNotifierOptions{Create,Update,Out}` → frontend notifier UI checkbox → run `task dev:generate` to regenerate `frontend/app/lib/api/types/household.ts`. |
| `e52a887e` | #7015 | Reused existing `EventMealplanData` payload (no new payload class). | The spec asks for `list_id, list_name, household_id, archived_by_user_id, item_count, total_estimated_amount` — this **does not fit** the existing `EventShoppingListData` (which carries only `shopping_list_id`). Decide: extend `EventShoppingListData` with optional fields, or add a new `EventShoppingListArchiveData(EventDocumentDataBase)` class in `event_types.py`. Recommend the latter for cleaner serialization. Note that `Event.document_data` is `SerializeAsAny[EventDocumentDataBase]` (line 198), so a discriminated subtype is safe. |
| `e52a887e` | #7015 | `publish_event` signature in `mealie/routes/_base/base_controllers.py:199–214` takes `group_id` and `household_id` **explicitly** and forwards them to `event_bus.dispatch`. | The spec's "payload must not contain other household / group data" is enforced by **passing the correct `group_id` / `household_id` to `publish_event`** — the event bus then filters subscribers by these IDs. The payload itself just needs to avoid embedding cross-household references (e.g., don't embed user objects from other households; UUID is fine). The existing controller already does this correctly at lines 192–194, 209–211, 224–226 — mirror those call sites for archive/unarchive. |
| `d3436a5c` | #5879 | `feat: Add label notifier` | Older but similar: shows that new event types **must** ship with a migration that adds a `bool` column to the subscribers table, otherwise existing notifier rows fail validation. |
| `e52a887e` | #7015 | Added integration test `tests/integration_tests/user_household_tests/test_group_notifications.py` for the new event types. | The spec's "事件总线 payload 校验" test requirement maps directly onto this file. |

**Subtle risk:** The existing `shopping_list_updated` event is dispatched on *every* item check/uncheck via the `publish_list_item_events` helper (controller lines 41–95). If the UI listens to `shopping_list_updated` and re-renders the list, it will **already fire** during the "check everything before archiving" workflow. The archive event should be a *distinct* signal so the UI can show an "archive complete" toast without duplicating the per-item toast.

---

## Risk hotspots — areas with recent churn or structural fragility

1. **`mealie/repos/repository_shopping_list.py` is 492 bytes (12 lines)** — currently just a one-method override (`update`). All real query logic lives in `HouseholdRepositoryGeneric` (`mealie/repos/repository_generic.py`). The spec demands the archive filter live "centrally in `repository_shopping_list.py`", which means **this file will roughly 10× in size**. Risk: the new filter logic needs to coordinate with `HouseholdRepositoryGeneric.page_all()` (which already auto-filters by `household_id` via `_household_id` and the `AssociationProxy` guard at lines around `q.filter(self.model.household_id.is_not(None))`). Don't double-filter or accidentally bypass tenant scoping. Validate by reading `repository_generic.py` end-to-end before adding code.

2. **`shopping_list.py` model uses `AssociationProxy` for `household_id`** (line 153: `household_id = association_proxy("user", "household_id")`). That means `ShoppingList` rows **do not have a direct `household_id` column** — household is inferred via the owning user. If you naively try `select(ShoppingList).filter_by(household_id=...)`, it works for in-Python comparison but the SQL goes through a JOIN on `users`. **The new `archived_by_user_id` FK should be a real column**, not a proxy. Also, if a list's owning user is moved to a different household, the list's effective household_id moves with them — which already makes `archived_by_user_id` belonging to a *different* household than the list possible after archive. The spec is silent; recommend a CR question.

3. **`@event.listens_for(orm.Session, "after_flush")` on lines 214–238** of `shopping_list.py` auto-bumps `ShoppingList.updated_at` whenever a `ShoppingListItem` changes. **This will fire when the spec's "check all items before archive" flow runs**, but it should *not* fire while the list is archived (since item mutation is forbidden). Implementation must enforce the 409 *before* it reaches the ORM (i.e., in the controller or service, not at the model level), or this flush hook will inadvertently mutate `updated_at` on a "frozen" row.

4. **`SessionBuffer` (lines 184–212) uses a module-level `ContextVar`** for cross-session shopping list ID buffering. If the archive logic runs item mutations in a separate session (e.g., bulk un-check during unarchive), make sure the buffer is initialized for that session or the `updated_at` propagation will silently skip.

5. **Offline PWA queue** (`use-shopping-list-item-actions.ts` lines 1–117, introduced by #3760 / `f4827abc`): a user could go offline, archive a list, come back online and find queued create/update/delete operations targeting the now-archived list. The 409s must be **explicit and individually identifiable** (not a single bulk failure) so the queue can either drop them or surface them to the user. The current queue code at `pollForChanges` has a 17,280-attempt budget; a permanent 409 would burn that budget if not handled.

6. **Recent security fixes (`GHSA-x5v9-9jvh-7c7q`, `GHSA-8m57-7cv5-rjp8`)** show that **CR has actively flagged ownership checks** in the past 60 days. Archive/unarchive endpoints **must** explicitly validate that the requesting user's household owns the list before mutating, regardless of repository scoping — Hayden's review comments will look for this.

7. **`task dev:generate` is mandatory** after the schema PR (per copilot-instructions and PR #5054 precedent which regenerated `tests/utils/api_routes/__init__.py`). Missing this step will cause CI route helpers + frontend types to drift and tests will silently target the wrong endpoints.

8. **Migration safety**: most recent column-add migration is `2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py`. Generate via `task py:migrate -- "add archive columns to shopping_lists"`. The migration must:
   - `op.add_column("shopping_lists", sa.Column("archived_at", sa.DateTime, nullable=True))`
   - `op.add_column("shopping_lists", sa.Column("archived_by_user_id", GUID, sa.ForeignKey("users.id"), nullable=True))`
   - Add a CHECK constraint `(archived_at IS NULL) = (archived_by_user_id IS NULL)` — SQLite supports it inline; for Postgres parity, use `op.create_check_constraint`.
   - The `downgrade()` must `op.drop_column` — without this CI rollback test will fail.

---

## Cross-perspective questions (for UI / spec / coding agents)

1. **Schema response shape:** Spec §6 says "default queries don't return `archived_at` field (backward compat)". Generated TypeScript types are auto-derived from Pydantic — if we conditionally include `archived_at` on `ShoppingListOut` only in certain branches, the TS type will become `archivedAt: string | null | undefined` *always*. The UI must treat `undefined` (omitted) and `null` (returned but not archived) as equivalent. Should we instead **always** include `archived_at` in the schema (defaulting to `null`) and just rely on the filter behavior? This simplifies typegen and avoids subtle UI bugs. → **UI perspective should confirm acceptable.**

2. **`archived_by` user summary**: Spec mentions appending `archived_by` (user summary) in archived-list queries. We have no schema for "minimal user summary in shopping list context" — closest is `UserOut` in `mealie/schema/user/user.py`. Does the UI need full user info or just `{id, full_name, username}`? → Affects whether we add a new `UserSummary` schema or reuse `UserOut`.

3. **Default route `GET /api/households/shopping/lists/{id}`** behavior on an archived list: return 404? return 200 with `archived_at` populated? Spec only constrains the *list* endpoint. The Detail page (`pages/shopping-lists/[id].vue` polls every 5 s via `use-shopping-list-data.ts`) will display the list — does it need a banner like "This list is archived (read-only)"? → **UI perspective should propose UX.**

4. **Event payload for archived-by-other-household visibility**: spec says payload "must not contain other household/group data". But if user U1 in household H1 archives a list in H1, and a notifier subscriber is in H2 (same group), should the event fire at all for H2? Existing `event_bus.dispatch(group_id=…, household_id=…)` filters subscribers by both IDs (see `publish_event` impl), so the event naturally won't reach H2 subscribers. But the spec also says "同 group 内的其他 household 看不到对方的归档清单" — this should mean both query isolation and event isolation. Confirm.

5. **Cookbook / mealplan / export downstream consumers** (spec evaluation criterion mentions these): grep shows `mealie/schema/meal_plan/shopping_list.py` exists (separate from `mealie/schema/household/group_shopping_list.py`) and `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` is a scheduled task. **Does the auto-delete scheduler need to skip archived lists?** Almost certainly yes — otherwise it will silently mutate archived items, violating the "frozen" guarantee. This is a hidden coupling the design must address.

6. **Admin force-unarchive** (spec evaluation criterion): the existing `BaseAdminController` is not used by `controller_shopping_lists.py`. If admin force-unarchive is wanted, we need either a new admin route or a permission bypass in the existing route. Recommend deferring to a follow-up PR but call out in spec.

7. **Backup/restore (`backup_v2_tests`)**: PR #7416 (`feat: Added version info to backup file`, commit `e1ddc06e`) is very recent. Adding new columns to `shopping_lists` will change the backup schema version. Verify the backup includes/restores `archived_at` and `archived_by_user_id` and that the version bump is reflected.

8. **Frozen-state error code**: spec wants `shopping-list.archived.frozen` and `shopping-list.archive.unchecked-items` (note: different parent keys `archived` vs `archive`). Confirm the **dot-segment hierarchy** matches existing pattern. Looking at `en-US.json`, the existing convention nests one level deep (`"shopping-list": { "archive-..." : "..." }`), so `shopping-list.archive.frozen` would require a sub-object. **Recommend** flattening to `shopping-list.archive-frozen` and `shopping-list.archive-unchecked-items` to match existing siblings like `shopping-list.delete-checked`, `shopping-list.linked-recipes-count`. → **UI perspective should confirm i18n key style.**
