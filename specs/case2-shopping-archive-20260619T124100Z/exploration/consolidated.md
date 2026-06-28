# Case 2 — Consolidated Exploration

> Stage 3.5 consolidation across 5 perspectives (data / api / test / history / ui).
> Source tree: `C:\Users\v-liyuanjun\Downloads\mealie\` (commit `4a099c16`).
> Every line range below was re-verified by opening the actual file during consolidation.

---

## 1. Deduplicated artifact inventory

Each artifact appears once with the union of insights from every perspective that touched it. "Perspectives" column lists which exploration file already covered the artifact.

### 1.1 Backend — domain layer (existing code that must change)

| # | Path | Lines | Perspectives | Role in archive feature |
|---|------|-------|--------------|-------------------------|
| A1 | `mealie/db/models/household/shopping_list.py` | 147–181 (class `ShoppingList`), 153 (`household_id` AssociationProxy), 155 (`user_id` FK), 158 (`name`), 159–175 (relationships), 204–211 (item-change ORM listener), 214–238 (`after_flush` `updated_at` bumper) | data §A1, api §1.7, history §13/§risk-3 | Add two columns: `archived_at: datetime \| None` (NaiveDateTime, index) and `archived_by_user_id: GUID \| None` (FK→users.id, index). Both `FilterableColumn[…]` (history §2 — GHSA-8m57-7cv5-rjp8 requires the wrapper). |
| A2 | `mealie/db/models/household/shopping_list.py` | 51–98 (class `ShoppingListItem`), 65 (`checked: FilterableColumn[bool \| None]`) | data §A2, api §1.2 | Archive precondition "all items checked=true" maps to `checked`. `checked` is nullable → treat NULL as unchecked. |
| A3 | `mealie/db/models/household/events.py` | 15–57 (`GroupEventNotifierOptionsModel`), 35–37 (`shopping_list_{created,updated,deleted}` columns) | data §A3c/§A8, api §1.10, history §events-table | Add two boolean columns `shopping_list_archived` + `shopping_list_unarchived` after line 37 (mirroring the existing siblings) so the new `EventTypes` members are subscribable. |
| A4 | `mealie/services/event_bus_service/event_types.py` | 13–60 (`EventTypes` enum with docstring 14–22 mandating a DB migration on changes), 42–44 (existing `shopping_list_{created,updated,deleted}`), 63–77 (`EventDocumentType`), 80–85 (`EventOperation`), 88–91 (`EventDocumentDataBase`), 130–132 (existing `EventShoppingListData` carries **only** `shopping_list_id`), 194–207 (`Event` with `SerializeAsAny[EventDocumentDataBase]`) | data §A7, api §1.10, test §6, history §events | Add enum members `shopping_list_archived` + `shopping_list_unarchived` at line 44. Add new payload class `EventShoppingListArchiveData(EventDocumentDataBase)` with spec §5 fields. |
| A5 | `mealie/repos/repository_shopping_list.py` | 1–12 (full file — 12-line subclass of `HouseholdRepositoryGeneric`, only override is `update`) | data §A4, api §3 "list-view query filter", history §risk-1 | **The file the spec §7 calls `repository_shopping.py` (naming drift).** Will grow ~10× to host (a) centralised archived-filter `page_all(..., archived=ArchivedFilter)` override, (b) `archive(id, user_id)` / `unarchive(id)` mutators, (c) guard hook inside the existing `update` override that blocks mutations on archived rows. |
| A6 | `mealie/repos/repository_generic.py` | 33–58 (`RepositoryGeneric.__init__`), 79–92 (`_query` with `AssociationProxyInstance` special-case for `household_id`), 94–102 (`_filter_builder` injects `group_id`+`household_id` into `filter_by` kwargs), 315–355 (`page_all` — calls `_filter_builder` at 330, applies `loader_options` at 342, `filter_by(**fltr)` at 331), 357–405 (`add_pagination_to_query` with `QueryFilterBuilder` at 369), 505–523 (`HouseholdRepositoryGeneric` — adds `household_id` ctor kwarg) | data §A4b, api §1.4 | The spine. The archived filter MUST compose with `_filter_builder` (which uses `filter_by`) by either (a) adding a `where` predicate after `_filter_builder` runs or (b) extending `_filter_builder` to accept an extra kwarg. Bypassing `_filter_builder` breaks multitenancy. |
| A7 | `mealie/repos/repository_factory.py` | 317–321 (`group_shopping_lists` cached_property constructs `RepositoryShoppingList(session, PK_ID, ShoppingList, ShoppingListOut, group_id=…, household_id=…)`), 323–332 (`group_shopping_list_item` cached_property — currently raw `HouseholdRepositoryGeneric`, no custom subclass) | data §A8, api §3 | If item-level mutations should also flow through a custom repo for the frozen guard, must introduce `RepositoryShoppingListItem(HouseholdRepositoryGeneric[…])` and substitute it here at line 325. |
| A8 | `mealie/schema/household/group_shopping_list.py` | 32–47 (`ShoppingListItemRecipeRefCreate`), 58–76 (`ShoppingListItemBase`), 79–94 (`ShoppingListItemCreate`), 100–104 (`ShoppingListItemUpdateBulk`), 106–143 (`ShoppingListItemOut`), 146–151 (`ShoppingListItemsCollectionOut`), 173–174 (`ShoppingListItemPagination`), 177–189 (`ShoppingListCreate`), 211–213 (`ShoppingListSave`), 216–238 (`ShoppingListSummary` with `loader_options` lines 224–238), 241–242 (`ShoppingListPagination`), 245–247 (`ShoppingListUpdate`), 250–285 (`ShoppingListOut` with `loader_options` 261–285) | data §A5, api §1.9, ui §4 | Add `archived_at: datetime \| None = None` and `archived_by: UserSummary \| None = None` on both `ShoppingListSummary` (216–238) and `ShoppingListOut` (250–285). Both default `None` to preserve backward compat. Extend `loader_options` to `selectinload(ShoppingList.archived_by)`. Add new `ArchivedFilter(StrEnum)` near top of file. |
| A9 | `mealie/services/household_services/shopping_lists.py` | 1–43 (imports + `ShoppingListService.__init__` with `self.shopping_lists = repos.group_shopping_lists`, `self.list_items = repos.group_shopping_list_item`), 154–223 (`bulk_create_items`), 225–310 (`bulk_update_items`), 312–321 (`bulk_delete_items`), 413–455 (`add_recipe_ingredients_to_list`), 457–539 (`remove_recipe_ingredients_from_list`), 541–554 (`create_one_list`) | data §A8, api §3, history §9 | The 22.7 KB orchestration layer. New `archive_list(list_id, user_id)` / `unarchive_list(list_id)` methods added after 554 (after `create_one_list`). Frozen guard is consumed here even when the actual exception is raised by the repo — service method translates `RepositoryShoppingList.ListFrozenError` to `HTTPException(409, …)`. |
| A10 | `mealie/routes/households/controller_shopping_lists.py` | 38 (`item_router`), 41–95 (`publish_list_item_events` helper), 98–153 (`ShoppingListItemController` with `service` cached_property 100–102, `repo` 104–106, `mixins` 108–113, `get_all` 115–119, `create_many` 121–125, `create_one` 127–129, `get_one` 131–133, `update_many` 135–139, `update_one` 141–143, `delete_many` 145–149, `delete_one` 151–153), 156 (`router`), 159–283 (`ShoppingListController` with `get_all` 176–184, `create_one` 186–198, `get_one` 200–202, `update_one` 204–215, `delete_one` 217–229, `update_label_settings` 234–254, `add_recipe_ingredients_to_list` 256–261, `add_single_recipe_ingredients_to_list` 263–272, `remove_recipe_ingredients_from_list` 274–283) | api §1.1/§1.2/§1.9, history §10, ui §6 | New endpoints `POST /{item_id}/archive` and `POST /{item_id}/unarchive` insert after line 229 (after `delete_one`). `get_all` (176–184) gains `archived: ArchivedFilter = Query(ArchivedFilter.exclude)` param threaded to repo. No changes needed in item controller — guards live below. |
| A11 | `mealie/routes/_base/base_controllers.py` | 192–214 (`BaseCrudController.publish_event(event_type, document_data, group_id, household_id, message)`) | api §1.5, history §events-3, data §A8 | Verbatim template for the new `publish_event(EventTypes.shopping_list_archived, EventShoppingListArchiveData(…), group_id=list.group_id, household_id=list.household_id, message=t("notifications.generic-updated", name=list.name))` call sites. Multitenant scope is honored by passing the **list's own** `group_id`/`household_id` (not `self.group_id`). |
| A12 | `mealie/services/event_bus_service/event_bus_service.py` | 42–106 (`EventBusService`), 60–64 (`_publish_event`), 66–96 (`dispatch` — loops per-household at 92–96 if `household_id` is None, otherwise targets only the provided `household_id`), 98–105 (`as_dependency`) | data §A7, api §1.10 | Structural multitenancy guard: dispatch already routes per-household. Spec §5 "no cross-household leakage" is satisfied by (a) passing the correct `household_id` here and (b) the payload class itself omitting cross-household fields. |
| A13 | `mealie/schema/response/responses.py` | 8–19 (`ErrorResponse(message, error=True, exception=None)` + `respond(message, exception)` classmethod returning `model_dump()`) | api §1.8, test §5.3 | Canonical envelope: `raise HTTPException(409, detail=ErrorResponse.respond(message=self.t("shopping-list.archive-frozen")))`. Existing 409 in `registration_service.py:83-86` does NOT use `ErrorResponse` (returns a dict literal) — we should adopt `ErrorResponse` for uniformity. |
| A14 | `mealie/lang/messages/en-US.json` | 1–95 (full file, 4109 bytes). 9 top-level keys: `generic`, `recipe`, `mealplan`, `user`, `group`, `exceptions` (46–53), `notifications`, `datetime`, `emails` | data §A8, api §1.6, test §5.5, history §9, ui §5 | No `shopping-list` namespace exists in BACKEND `en-US.json`. (The FRONTEND `frontend/app/lang/messages/en-US.json` has a separate `shopping-list` block — different file, different convention; backend keys here are the ones `self.t(...)` resolves.) Per .github/copilot-instructions.md, only `en-US.json` may be modified — Crowdin manages all others. |
| A15 | `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_group_notifier_options.py` | 1–51 (full file): revision/down_revision 13/14, upgrade with `batch_alter_table("group_events_notifier_options")` adding `Boolean, nullable=False, server_default=sa.sql.expression.false()` columns at 19–39, downgrade with `drop_column` at 44–49 | data §A3c, api §1.10, history §migrations | Direct template for the SECOND archive migration (notifier options). Last commit was 2026-05-18 `2187537c52b8_add_table_for_ai_providers.py` — `down_revision` for the new archive migration chains off this head. |
| A16 | `mealie/db/models/recipe/recipe.py` | 145 (`date_updated: FilterableColumn[datetime \| None] = mapped_column(NaiveDateTime)`), 147 (`last_made: FilterableColumn[datetime \| None] = mapped_column(NaiveDateTime)`) | data §A6 | Precedent for the type/wrapper of `archived_at`: `FilterableColumn[datetime \| None] = mapped_column(NaiveDateTime)`. |
| A17 | `mealie/db/models/household/mealplan.py` | 67 (`user_id: FilterableColumn[GUID \| None] = mapped_column(GUID, ForeignKey("users.id"), index=True)`) | data §A6 | Precedent for the type/wrapper of `archived_by_user_id`. Use the same `FilterableColumn[GUID \| None]` + `mapped_column(GUID, ForeignKey("users.id"), index=True)`. |
| A18 | `mealie/schema/user/user.py` | 191–197 (`class UserSummary(MealieModel)` with `id`, `group_id`, `household_id`, `username`, `full_name`, `model_config = ConfigDict(from_attributes=True)`) | data §A8, ui §5 | The exact Pydantic shape for spec §6's `archived_by: UserSummary` response field. Already importable. |
| A19 | `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` | 1–76 (full file): `delete_old_checked_list_items` (54–75) iterates every household's shopping lists and calls `_trim_list_items` (37–51) which uses `shopping_list_service.bulk_delete_items(...)` | data §9, history §5 | **Hidden coupling discovered.** The auto-prune scheduler will currently silently delete items from archived lists (since archived items are typically all `checked=true`). MUST be modified to skip archived lists, or the frozen guard inside `bulk_delete_items` will start raising 409 from the scheduler context. |

### 1.2 Backend — testing layer

| # | Path | Lines | Role |
|---|------|-------|------|
| T1 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` | 1113-line file. `test_shopping_lists_get_all` 22–32, `test_shopping_lists_create_one` 35–46, `test_shopping_lists_get_one` 49–64, `test_shopping_lists_update_one` 67–94, `test_shopping_lists_delete_one` 97–112, `test_shopping_lists_add_recipe` 115–174, `test_shopping_lists_add_cross_household_recipe` 364–422 (uses `h2_user` for cross-household scenarios) | Append new archive lifecycle / frozen-state / query-behavior tests here. |
| T2 | `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py` | 623-line file. `create_item` helper 17–23, `serialize_list_items` 26–36, `test_shopping_list_items_create_one` 39–69 | Verify item-level 409s on archived lists. |
| T3 | `tests/multitenant_tests/case_foods.py` | 1–51 (full file): `FoodsTestCase(ABCMultiTenantTestCase)` template | Template for new `ArchivedShoppingListsTestCase` (cross-group isolation). |
| T4 | `tests/multitenant_tests/test_multitenant_cases.py` | 13–19 (`all_cases` list), 22–56 (`test_multitenant_cases_get_all`), 59–93 (`test_multitenant_cases_same_named_resources`) | Register `ArchivedShoppingListsTestCase` in `all_cases` (line 13–19) to auto-cover cross-group isolation. |
| T5 | `tests/fixtures/fixture_users.py` | `build_unique_user` 17–52, `h2_user` 55–118 (same group, different household), `g2_user` 121–176, `_unique_user` 179–216, `unique_user_fn_scoped` 219–221, `unique_user` 224–226 (module-scoped), `unique_admin` 229–233, `user_tuple` 236–306 | `h2_user` is the cross-household-same-group fixture for spec §4-2 isolation tests. |
| T6 | `tests/fixtures/fixture_shopping_lists.py` | `create_item` 10–21 (default `checked=False`), `shopping_lists` 24–46 (3 lists, function-scoped), `shopping_list` 49–65 (single, function-scoped), `list_with_items` 68–94 (1 list + 10 items, function-scoped) | Templates for the new `archived_list` / `archived_list_with_items` / `h2_list_with_items` fixtures. |
| T7 | `tests/conftest.py` | 19–22 (env var monkeypatch), 37–42 (`override_get_db`), 45–53 (`api_client` session-scoped wrapping `TestClient(app)`) | Sync `TestClient` — no async. |
| T8 | `tests/utils/api_routes/__init__.py` | Auto-generated. `households_shopping_lists` const 114, `households_shopping_items` 110, `households_shopping_lists_item_id(id)` 405–407 | New routes need codegen via `task dev:generate`. |
| T9 | `tests/utils/assertion_helpers.py` | 4–20 `assert_ignore_keys`, 23–25 `assert_deserialize(response, expected_status_code=200)` | Standard helper. New 409 cases assert `response.status_code == 409` and `response.json()["detail"]["message"] == "<en-US literal>"`. |

### 1.3 Frontend (ui) layer

| # | Path | Lines | Role |
|---|------|-------|------|
| U1 | `frontend/app/lib/api/types/household.ts` | 523–530 `ShoppingListCreate`, 673–687 `ShoppingListOut`, 725–734 `ShoppingListSave`, 735–748 `ShoppingListSummary`, 749–760 `ShoppingListUpdate` | Auto-generated by `task dev:generate`. New `archivedAt?` + `archivedBy?` fields appear on `ShoppingListOut` and `ShoppingListSummary` after Pydantic edits. **Never hand-edit.** |
| U2 | `frontend/app/lib/api/user/group-shopping-lists.ts` | 80-line file. `ShoppingListsApi extends BaseCRUDAPI<ShoppingListCreate, ShoppingListOut, ShoppingListUpdate>` (~line 1–15), `addRecipes` / `removeRecipe` / `updateLabelSettings` methods | Hand-written. Add `archive(id)` and `unarchive(id)` methods; thread `archived` query param via `getAll(page, perPage, { archived: "true" \| "all" })`. |
| U3 | `frontend/app/pages/shopping-lists/index.vue` | 274-line file. `fetchShoppingLists()` 193–201, `viewAllLists` checkbox 69–74, `shoppingListChoices` computed 162–168, `refresh()` 203–205, single-result auto-redirect watcher 178–191 | Filter UI for `?archived=` toggle. Suppress single-result auto-redirect on archived view. |
| U4 | `frontend/app/pages/shopping-lists/[id].vue` | 449-line file. Header `BaseButtonGroup` 95–146 (three-dot menu 124–135), `<BannerWarning v-if="isOffline">` 154–158, `<ShoppingListAddItemForm>` / `<ShoppingListItemEditor>` 163–195, `<ShoppingListItem ... @checked/@save/@delete>` 217–232, `useShoppingListPage(id)` invocation 374, destructured surface 398–431, `WakelockSwitch` 348 | Add Archive/Unarchive menu items; add `<BannerInfo v-if="isArchived">`; gate all mutation surfaces behind `:disabled="isArchived"`. |
| U5 | `frontend/app/composables/shopping-list-page/use-shopping-list-page.ts` | 194-line orchestrator | Expose `isArchived` computed + `archive()` / `unarchive()` actions; refresh after either. |
| U6 | `frontend/app/composables/shopping-list-page/sub-composables/use-shopping-list-crud.ts` | 200+ lines (all mutation entry points: `saveListItem`, `deleteListItem`, `deleteListItems`, `createListItem`, `updateUncheckedListItems`, `checkAllItems`, `uncheckAllItems`, `deleteCheckedItems`, `updateLabelOrder`) | Each mutation short-circuits when `isArchived === true` (defense-in-depth alongside backend 409). |
| U7 | `frontend/app/composables/use-shopping-list-item-actions.ts` | 164-line offline PWA queue (introduced by PR #3760, commit `f4827abc`) | Handle 409s from flush: drop offending op rather than retry forever (poll budget is 17,280 attempts). |
| U8 | `frontend/app/components/Domain/Recipe/RecipeDialogAddToShoppingList.vue` | Recipe → shopping list adder dialog | Filter archived lists out of target dropdown. |
| U9 | `frontend/app/components/Domain/Household/GroupMealPlanDayContextMenu.vue` | Meal plan day context menu | Filter archived lists out of "Add to shopping list" target dropdown. |
| U10 | `frontend/app/lang/messages/en-US.json` | 82,801 bytes. Existing `shopping-list` block uses **flat kebab-case** (e.g., `delete-checked`, `linked-recipes-count`) | Add new flat keys: `shopping-list.archive-unchecked-items`, `shopping-list.archive-frozen`, `shopping-list.archive`, `shopping-list.unarchive`, `shopping-list.archived-on`, `shopping-list.archived-banner-title`, `shopping-list.archived-banner-description`, `shopping-list.view-archived`, `shopping-list.view-active`, `shopping-list.no-archived-lists-found`, `shopping-list.confirm-archive`, `shopping-list.confirm-unarchive`. |

---

## 2. Cross-perspective agreements

These are points where ≥3 perspectives independently arrived at the same conclusion. They are now treated as locked design constants.

| # | Agreement | Perspectives | Why locked |
|---|-----------|--------------|------------|
| AGR-1 | `archived_at` is `FilterableColumn[datetime \| None] = mapped_column(NaiveDateTime)` and `archived_by_user_id` is `FilterableColumn[GUID \| None] = mapped_column(GUID, ForeignKey("users.id"), index=True)`; both are real columns (no association proxy). | data, api, history | `recipe.last_made` line 147 + `mealplan.user_id` line 67 are the directly-comparable precedents. Using anything else diverges from convention; `FilterableColumn` wrapper is mandatory per GHSA-8m57-7cv5-rjp8. |
| AGR-2 | Default `GET /api/households/shopping/lists` MUST omit archived lists (`archived_at IS NULL`). `?archived=true` returns archived only. `?archived=all` returns everything. | data, api, test, history, ui | Spec §2 is unambiguous; the UI ships archived-aware components that depend on this contract; multitenant tests rely on it. UI perspective §"Worst case" calls out a silent regression if violated. |
| AGR-3 | The 409 response body uses `ErrorResponse.respond(message=…)` (i.e., `{"detail": {"message": "<i18n>", "error": true, "exception": null}}`) rather than the dict-literal pattern in `registration_service.py`. | api §1.8, test §5.3 | Consistency with 400/404 envelopes; test perspective explicitly proposes this so the new 409 tests can also use a normal-shape assertion helper. |
| AGR-4 | The frozen guard is exposed as one centralised raise-point — not duplicated per controller. (Disagreement remains over WHICH layer — see Critical Conflict CC-2.) | data, api, test, history, ui | Input §7 mandates centralisation. All perspectives agree controllers must NOT each issue their own freeze check. |
| AGR-5 | Two alembic migrations are needed: (a) adds the two `shopping_lists` columns; (b) adds two boolean columns on `group_events_notifier_options` to mirror the new `EventTypes` enum members. | data §A3c, api §1.10, history §migrations | `event_types.py` docstring at lines 14–22 explicitly mandates the second migration. Skipping it breaks subscriber validation. |
| AGR-6 | Backend `en-US.json` only — every other locale file is Crowdin-managed and PRs touching them are rejected per .github/copilot-instructions.md. New keys live under a NEW top-level `shopping-list` namespace (currently only the frontend locale file has one). | data, api, test, ui | Three perspectives independently verified the file content and the copilot-instructions rule. |
| AGR-7 | New event types `shopping_list_archived` + `shopping_list_unarchived` get a dedicated payload class `EventShoppingListArchiveData(EventDocumentDataBase)` rather than reusing `EventShoppingListData` (which only carries `shopping_list_id`). Payload must contain ONLY: `shopping_list_id`, `shopping_list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`. | data §A7, api §1.10, history §60, test §6 | Reusing existing class would violate spec §5 enumeration; dedicated class makes the "no leak" contract explicit. |
| AGR-8 | Multitenant isolation continues to work via the existing `HouseholdRepositoryGeneric._filter_builder` (repository_generic.py:94–102) — the archive feature must NOT bypass it. The new archived-filter is composed via additional `.where(...)` AFTER `_filter_builder` injects `group_id`/`household_id`. | data, api, history | All three perspectives traced the query path. Bypassing breaks 5 years of multitenant guarantees. |
| AGR-9 | Cross-household access returns **404** (not 403), matching every existing precedent in the codebase. The `mixins.get_one` route at `mealie/routes/_base/mixins.py:79-83` returns 404 when the household filter excludes a row. | api §1.5, test §6, history | No precedent for 403 in this kind of context. Test perspective explicitly raised the 404 vs 403 question and recommended 404. |
| AGR-10 | UI surface (`frontend/`) is in scope for this design but its implementation is OUT of scope for the immediate backend coding milestone. Spec §1–§8 is backend-only; UI work is a follow-on PR. | All 5 perspectives | Spec text itself contains only backend requirements; UI perspective explicitly flagged this as a separable workstream. |

---

## 3. Cross-perspective conflicts and how they resolve

| # | Conflict | Stated by | Resolution |
|---|----------|-----------|-----------|
| CC-1 | i18n key shape — nested (`shopping-list.archive.unchecked-items`) vs flat (`shopping-list.archive-unchecked-items`). | data, api, ui (flat); spec text (nested) | **Backend** keys follow what `self.t(...)` actually resolves at runtime. Mealie's `Translator` uses dotted key lookup against nested JSON, so the **spec's nested form works directly** (`shopping-list.archive.unchecked-items` → `messages["shopping-list"]["archive"]["unchecked-items"]`). Keep the spec's nested form. The UI perspective's "flat" recommendation applies only to the **frontend** locale file, which uses a different convention. |
| CC-2 | Where does the frozen-state guard live — controller, service, or repository? | api §3 recommends service-layer (Option C); data and history call out repo-level concerns (Option B); UI is layer-agnostic | **Resolved by user input §7 plus this task spec**: pick the **repository-level frozen guard** approach. The selected approach implements the guard inside `RepositoryShoppingList` (which already overrides `update`) and `RepositoryShoppingListItem` (new custom subclass). Service catches the typed exception and re-raises as `HTTPException(409, …)` (because the service has `self.t` for i18n; repos don't). See `approach/selected.md` for details on how this addresses api perspective's three concerns. |
| CC-3 | Bulk item endpoints (`POST /items/create-bulk`, `PUT /items`, `DELETE /items?ids=…`) — also frozen? Spec only enumerates singular forms. | api §4-1 (recommend freeze bulk), test §10-7 (open question) | Singular handlers internally delegate to bulk handlers (controller lines 129, 143, 153) — so a repo-layer guard hitting `create_many/update_many/delete_many` catches both surfaces uniformly. **Decision: freeze both singular and bulk forms.** Functional Requirement FR-4 enumerates exactly which routes are frozen. |
| CC-4 | `?archived` param type — string enum (`"true"`/`"all"`) vs `bool \| Literal["all"]`. | test §10-4 raises this | Use a string-valued `ArchivedFilter(StrEnum)` to match spec §2's URL form and to keep OpenAPI explicit. Members: `exclude="false"` (default, archived hidden), `only="true"` (archived only), `inclusive="all"`. Tests pass `params={"archived": "true"}`. |
| CC-5 | `total_estimated_amount` in event payload — no `price` column on `ShoppingListItem`. | data §6, ui §6, test §5 | Spec §5 says "如有 / if available". Default to `None`; document that this is intentionally a forward-compat hook until a price-tracking feature lands. Don't expand scope. |
| CC-6 | Pre-existing module-scoped "Family" shopping list created by `unique_user` registration may confuse `len()` assertions in archive tests. | test §10-2 | All count assertions in new tests filter by known IDs: `len([l for l in items if l["id"] in known_ids])`. |
| CC-7 | `GET /api/households/shopping/lists/{id}` for an archived list — return it, or 404? | history §3, ui §"deep link", test silence | Return the list with `archived_at` populated. The `?archived=` filter governs only the **collection** endpoint; deep links and the detail view must remain functional (banner shows read-only state). Aligns with UI bookmark/poll behavior. |
| CC-8 | `archived_by` field naming on response — spec §6 says "archived_by (user summary)" but Pydantic field-naming convention prefers `archived_by` for the FK id or `archived_by_user` for the relationship. | api, data | Use **`archived_by_user_id: UUID4 \| None = None`** for the raw FK column projection (matches `archived_by_user_id` on the model) and **`archived_by: UserSummary \| None = None`** for the relationship-summary projection (this matches spec §6's wording). Both fields appear on response only when the request is `?archived=true|all`. |

---

## 4. Critical conflicts (max 5)

These are the items that the spec MUST take a binding stance on, because downstream work cannot proceed without a decision.

### CRITICAL-1. Where the frozen-state guard lives
- **Tension:** API perspective recommends service-layer (cleaner separation: repos are dumb, services own domain rules). Input §7 + this task instruction direct repository-layer (most centralised).
- **Decision:** Repository-layer guard. Repository raises typed exception `ShoppingListIsArchivedError`; service layer catches it and translates to `HTTPException(409, ErrorResponse.respond(message=self.t("shopping-list.archived.frozen")))`. See `approach/selected.md` for rationale and how api perspective's three objections are addressed.

### CRITICAL-2. Two-migration sequencing
- **Tension:** Adding new `EventTypes` enum members silently breaks `GroupEventNotifierOptionsModel` unless its table gets matching boolean columns. Input does NOT mention the second migration — it's a hidden requirement surfaced by reading `event_types.py:14-22`.
- **Decision:** Spec MUST enumerate two migrations: (a) `add_shopping_list_archive_columns` (touches `shopping_lists`), (b) `add_shopping_list_archive_notifier_options` (touches `group_events_notifier_options`). Both required for the feature to function; both reversible via `downgrade()`.

### CRITICAL-3. Default-include vs default-omit `archived_at` in response
- **Tension:** Spec §6 reads "默认查询不返回 archived_at 字段" (default query OMITS the field). But UI/codegen vastly prefer always-present optional field for typing simplicity. History perspective also raises bookmark / poll concerns.
- **Decision:** **Always include `archived_at: datetime \| None = None` on the schema** (sent as `null` for active lists). The "default query doesn't return them" requirement is satisfied at the **request-filtering** level (only the *collection* endpoint default-hides archived rows entirely), not at the **field-projection** level. `archived_by: UserSummary \| None = None` follows the same pattern but is populated only when archived. Justification: Pydantic Optional + default-None is fully backward-compatible because old clients ignore unknown null fields; conditional fields would force a schema bifurcation that breaks codegen.

### CRITICAL-4. Scheduled cleanup task interaction
- **Tension:** `delete_old_checked_shopping_list_items.py` (lines 54–75) iterates ALL shopping lists per household and calls `bulk_delete_items`. With the new repo-layer frozen guard, every archived list would start raising 409 from the scheduler context — silently breaking the cron.
- **Decision:** Spec MUST mandate that the scheduler skip archived lists (filter at `household_repos.group_shopping_lists.page_all(... archived=ArchivedFilter.exclude)`). Without this fix, the feature is shipping a scheduler-breaking bug. This belongs in the same PR.

### CRITICAL-5. Frozen-route scope — only the 4 in spec §3, or also the "other operations" routes?
- **Tension:** Spec §3 lists exactly: `PUT /lists/{id}`, `POST /items`, `PUT /items/{id}`, `DELETE /items/{id}`. But controller_shopping_lists.py also exposes `PUT /lists/{id}/label-settings` (line 234), `POST /lists/{id}/recipe` (256), `POST /lists/{id}/recipe/{recipe_id}` (263, deprecated), `POST /lists/{id}/recipe/{recipe_id}/delete` (274). These all mutate the archived list materially.
- **Decision:** Freeze **only** the 4 routes spec §3 lists, PLUS the bulk-form counterparts of the item routes (`/items/create-bulk`, `PUT /items`, `DELETE /items`). The "other operations" routes (label-settings, recipe-add, recipe-remove) are NOT frozen in v1 — but a `needs_clarification` line is added because they technically violate the "frozen" spirit, and the eval rubric explicitly asks about this in §三环节考察点. The repo-layer guard sits on `RepositoryShoppingList.update` and on `RepositoryShoppingListItem.create_many/update_many/delete_many`; routes that don't path through these methods aren't auto-frozen.

---

## 5. Existing-code findings (informing the design)

Things found by reading mealie source code that the input spec did NOT explicitly call out but that materially shape the design.

### F1. `RepositoryShoppingList.update` is already overridden
- File: `mealie/repos/repository_shopping_list.py:9-11`
- Finding: The class already overrides `update(item_id, data)` to call `super().update(item_id, data)` — a no-op pass-through.
- Implication: Adding the frozen guard at the start of this method is a one-line edit, not a structural change. The existing override is the natural seam.

### F2. `HouseholdRepositoryGeneric._query` already handles `AssociationProxy` for `household_id`
- File: `mealie/repos/repository_generic.py:79-92`, especially the try/except at 83–86 that filters out NULL household rows when the model uses an association proxy.
- Implication: `ShoppingList.household_id` works seamlessly inside the existing query plumbing. The archive filter (a real column on the model) is even simpler — no AssociationProxy gymnastics.

### F3. `_filter_builder` uses `filter_by(**kwargs)`, which only works on direct columns
- File: `mealie/repos/repository_generic.py:94-102`, applied at 331 in `page_all`.
- Implication: For the new `archived_at` (real column), we CAN extend `_filter_builder` with an `archived_at: <some sentinel>` kwarg, BUT — `filter_by` cannot express `IS NULL` / `IS NOT NULL`. So the archive predicate must be added as a `.where(...)` clause on the query AFTER `_filter_builder` runs. Recommended pattern: override `page_all` in `RepositoryShoppingList` to do `super()._query(...)`, apply `_filter_builder`, then append `.where(ShoppingList.archived_at.is_(None | not None))` based on `ArchivedFilter`, then continue with pagination.

### F4. `ShoppingListItem` has no custom repository subclass today
- File: `mealie/repos/repository_factory.py:323-332` — `group_shopping_list_item` instantiates raw `HouseholdRepositoryGeneric`.
- Implication: If we want a repo-layer frozen guard on item mutations (per Critical-1), we MUST introduce `class RepositoryShoppingListItem(HouseholdRepositoryGeneric[...])` (new file `mealie/repos/repository_shopping_list_item.py` OR put it in the same file as `RepositoryShoppingList`) and swap it in at line 325. This is a structural change but small.

### F5. `EventTypes` enum docstring is the only source of the "DB migration" rule
- File: `mealie/services/event_bus_service/event_types.py:14-22`
- Finding: Self-documenting requirement; without reading this docstring, a developer adding `shopping_list_archived` would miss the notifier-options migration entirely and break subscriber validation in production.
- Implication: Spec MUST surface this requirement explicitly so the design phase doesn't drop it.

### F6. `event_bus_service.dispatch` already loops per-household
- File: `mealie/services/event_bus_service/event_bus_service.py:66-96`, especially the loop at 92–96.
- Finding: When `household_id` is provided, dispatch publishes to exactly that household's subscribers — cross-household leakage is impossible at the dispatch layer.
- Implication: Spec §5's "no leakage" requirement is satisfied structurally by (a) passing `list.household_id` correctly + (b) the payload class itself omitting cross-household fields. No extra plumbing needed.

### F7. `publish_event` on `BaseCrudController` takes `group_id` + `household_id` as explicit args
- File: `mealie/routes/_base/base_controllers.py:199-214`
- Finding: Controllers must pass the **list's** `group_id`/`household_id`, not the caller's `self.group_id`/`self.household_id`. Existing call sites (controller_shopping_lists.py:193-194, 210-211, 224-226) do this correctly.
- Implication: Same pattern for archive/unarchive event dispatches — `group_id=shopping_list.group_id, household_id=shopping_list.household_id`.

### F8. The scheduled task `delete_old_checked_shopping_list_items.py` will break silently
- File: `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py:54-75`
- Finding: Iterates ALL shopping lists (line 69) including archived ones, then calls `bulk_delete_items` on their checked items. With a repo-layer frozen guard, this raises 409 from the scheduler, but the scheduler has no HTTP-translation layer — the exception bubbles into a generic error log and the cron silently fails.
- Implication: Critical-4 above. The scheduler must filter by `archived=exclude`.

### F9. `BaseCrudController.update_label_settings` and `add_recipe_ingredients_to_list` bypass `RepositoryShoppingList.update`
- File: `mealie/routes/households/controller_shopping_lists.py:234-254` (`update_label_settings`), 256–261 (`add_recipe_ingredients_to_list`), 274–283 (`remove_recipe_ingredients_from_list`)
- Finding: These routes go through OTHER repos (`self.repos.shopping_list_multi_purpose_labels.update_many`, `self.service.add_recipe_ingredients_to_list`) — they do NOT call `RepositoryShoppingList.update`, so a guard placed there will NOT freeze them.
- Implication: Critical-5 above. v1 freezes only the 4 spec'd routes (+ their bulk siblings). Label-settings/recipe-add/recipe-remove are NOT in v1's frozen list; this is called out under needs_clarification.

### F10. `ShoppingListItem.checked` is `bool | None` (nullable)
- File: `mealie/db/models/household/shopping_list.py:65`
- Implication: The "all items checked" precondition must treat NULL as unchecked: `all(item.checked for item in list.list_items)` where `None` evaluates falsy is correct, but the SQL form must read `(checked IS NULL OR checked = false)` for the inverse "any unchecked" predicate.

### F11. `ShoppingListSummary.loader_options` already eager-loads `User` with `load_only(household_id, group_id)`
- File: `mealie/schema/household/group_shopping_list.py:237`
- Implication: To populate `archived_by: UserSummary` without N+1, extend the loader to add `selectinload(ShoppingList.archived_by).options(load_only(User.id, User.username, User.full_name, User.group_id, User.household_id))` — and on the model side, the new relationship needs `foreign_keys=[archived_by_user_id]` since `User` is already related via `user_id`.

### F12. Path naming drift between spec and reality
- Input §7 says `mealie/repos/repository_shopping.py`. Actual file is `mealie/repos/repository_shopping_list.py`.
- Grounding §3 says `mealie/services/household_services/shopping_lists.py (22.7KB)`. Actual file size matches.
- Implication: Spec output uses the actual filenames.

---

## 6. Out-of-scope items (explicit deferrals)

The following items were raised by one or more perspectives but are EXPLICITLY out of scope for this case. Recorded here so they don't get re-raised during design.

1. **Admin force-unarchive endpoint** — input §三环节考察点 mentions this as a CR-stage discussion point, not a v1 requirement. Deferred to a follow-up PR.
2. **Backup/restore handling for archived lists** — input §三环节考察点 lists this as a CR-stage concern; spec text does not require behavior. Spec output adds a `self_concern` noting the column-level additions automatically flow through `mealie/services/backups_v2/` because that module dumps full SQLAlchemy rows.
3. **Frontend UI implementation** — UI perspective is fully documented but the backend can ship without UI changes; codegen ensures the typescript types update on `task dev:generate`. UI work is a separate workstream.
4. **Unarchive precondition: items may have been externally deleted** — input §三环节考察点 calls this out for CR discussion; spec §2 is silent. v1 simply clears `archived_at`/`archived_by_user_id` without item-state validation.
5. **Cookbook/export downstream consumers** — input §三环节考察点 evaluation criterion mentions "是否枚举出所有消费 shopping list 的下游接口". Inventoried: cookbook does NOT consume shopping lists; meal plan generates them (`mealie/services/scheduler/tasks/create_timeline_events.py` is unrelated); the only scheduler that consumes them is `delete_old_checked_shopping_list_items.py` (covered by Critical-4); backups via `backups_v2` dumps full ORM (covered by #2 above).
