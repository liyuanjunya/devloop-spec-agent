# Test Perspective — Case 2: Shopping List Archive

Scope: existing test infrastructure in `C:\Users\v-liyuanjun\Downloads\mealie` that the archive/unarchive feature must extend. All line ranges below were verified by direct reads of the source files (file lengths captured: test_group_shopping_lists.py = 1113, test_group_shopping_list_items.py = 623, test_shopping_list_labels.py = 195, fixture_users.py = 286, fixture_shopping_lists.py = 75, conftest.py = 47, fixture_database.py = 15, fixture_multitenant.py = 17, multitenant_tests/case_abc.py = 21, multitenant_tests/case_foods.py = 39, test_multitenant_cases.py = 74, utils/fixture_schemas.py = 23, utils/assertion_helpers.py = 19, test_group_webhooks.py = 104, test_group_notifications.py = 143, unit_tests/services_tests/scheduler/tasks/test_post_webhook.py = 236, test_user_service.py = 85, fixture_admin.py = 45).

---

## 1. Existing shopping list integration tests

> Note: The task brief listed `tests/integration_tests/household_tests/` but the actual directory is `tests/integration_tests/user_household_tests/`. Verified by listing the directory.

| # | Path | Symbols / line_ranges | Importance | Reason |
|---|------|----------------------|------------|--------|
| 1.1 | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` | imports (1–19); `test_shopping_lists_get_all` (22–32), `test_shopping_lists_create_one` (35–46), `test_shopping_lists_get_one` (49–64), `test_shopping_lists_update_one` (67–94), `test_shopping_lists_delete_one` (97–112), `test_shopping_lists_add_recipe` (115–174), `test_shopping_lists_add_cross_household_recipe` (364–422). File = 1113 lines. | **Critical** | Canonical CRUD pattern (`api_client.get/post/put/delete` + `utils.assert_deserialize` + `response.json()` field-by-field checks). New archive tests must follow this exact shape — same imports, same fixtures, same assertion style. Note that line 1111 shows the lone existing pattern for asserting an i18n error message: `response.json()["detail"]["message"] == "No Entry Found"` (it's in `test_recipe_crud.py`, not this file — see §5). |
| 1.2 | `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py` | `create_item(list_id, **kwargs)` helper (17–23), `serialize_list_items` (26–36), `test_shopping_list_items_create_one` (39–69), `test_shopping_list_items_create_many` (72–105), `test_shopping_list_items_get_one` (173–…). File = 623 lines. | **Critical** | Source of truth for item creation/update/delete request shape and for the bulk-response envelope (`createdItems` / `updatedItems` / `deletedItems`). All §3 "frozen after archive" tests issue POST/PUT/DELETE on `/api/households/shopping/items[/{id}]` and must hit these same routes. |
| 1.3 | `tests/integration_tests/user_household_tests/test_shopping_list_labels.py` | `create_labels` helper (14–20), `test_label_create_duplicate_name_returns_400` (23–35), `test_new_list_creates_list_labels` (38–48). | Medium | Shows the **only existing 4xx-from-write-path assertion** in shopping-list tests (400 on duplicate). No 409 assertion exists anywhere in `tests/` (verified: `Get-ChildItem -Recurse -Include '*.py' \| Select-String ' 409'` returned 0 matches). Our archive tests will introduce the first 409 assertions for shopping lists. |

### 1.x How the existing tests are scoped (gotcha for archive tests)

`unique_user` is **module-scoped** (`fixture_users.py:224–226`), so state created in one test persists across the whole module. The `shopping_lists` / `shopping_list` / `list_with_items` fixtures are **function-scoped** and clean up on yield (`fixture_shopping_lists.py:24–47`, 49–65, 68–94). Archive tests that mutate per-test state (archive ↔ unarchive cycling) MUST keep using these function-scoped fixtures **or** use `unique_user_fn_scoped` (`fixture_users.py:219–221`) — see the `test_label_create_duplicate_name_returns_400` precedent (`test_shopping_list_labels.py:23–28`) which switched to `unique_user_fn_scoped` exactly because module-scoped state leaks between tests.

---

## 2. Existing multitenant test pattern

| # | Path | Symbols / line_ranges | Importance | Reason |
|---|------|----------------------|------------|--------|
| 2.1 | `tests/multitenant_tests/case_abc.py` | `ABCMultiTenantTestCase` (9–31): `__init__(database, client)` (10–13), abstract `seed_action(group_id)` (15–16), `seed_multi(group1_id, group2_id)` (18–19), `get_all(token)` (21–22), `cleanup()` (24–25), `__enter__`/`__exit__` context manager (27–31). | **Critical** | Mandatory base class for any new multitenant test case. The framework runs every concrete subclass through `test_multitenant_cases_get_all` and `test_multitenant_cases_same_named_resources` automatically — we just register the class in the `all_cases` list. |
| 2.2 | `tests/multitenant_tests/test_multitenant_cases.py` | `all_cases = [...]` (13–19), `test_multitenant_cases_get_all` parametrized over `all_cases` (22–56), `test_multitenant_cases_same_named_resources` (59–93). | **Critical** | Driver. Fetches `multitenants.user_one`/`user_two` (different **groups**, not households), seeds via repo, then calls `get_all(token)` and asserts user_two sees `[]` and user_one sees the seeded IDs. |
| 2.3 | `tests/multitenant_tests/case_foods.py` | `FoodsTestCase(ABCMultiTenantTestCase)` (9–50): `seed_action` (12–25), `seed_multi` (27–43), `get_all` (45–46), `cleanup` (48–50). Mirror in `case_units.py` (1–51), `case_tags.py`, `case_tools.py`, `case_categories.py`. | **Critical (model after)** | Smallest, cleanest concrete implementation. The new `ArchivedShoppingListsTestCase` (see §10) should be a near-line-for-line clone, substituting `ingredient_foods` for `group_shopping_lists` and setting `archived_at` on the seeded items. |
| 2.4 | `tests/fixtures/fixture_multitenant.py` | `MultiTenant` dataclass (12–15), `multitenants` fixture (18–23). | **Critical** | The cross-**group** fixture used by all parametrized multitenant tests. Note: this fixture only covers cross-group isolation. Cross-**household-within-same-group** (which is what §4 of the spec asks about) is covered by `h2_user` instead (see §3 below) — not by this fixture. |
| 2.5 | `tests/fixtures/fixture_database.py` | `session` module-scoped (10–16), `unfiltered_database` function-scoped (19–21) using `get_repositories(session, group_id=None, household_id=None)`. | High | Provides the unscoped `AllRepositories` instance that `ABCMultiTenantTestCase` uses in `__init__` to bypass per-group filtering when seeding two groups in one test. Required for the seed phase; the `get_all` phase still goes through the API which re-applies filtering. |

### 2.x Important multitenant gotcha for the archive feature

The existing `ABCMultiTenantTestCase` only verifies *cross-group* isolation. The spec §4 requires **three** isolation guarantees:

1. ✅ Cross-group — fits the existing `ABCMultiTenantTestCase`/`multitenants` pattern (use `archived=true` token in `get_all`).
2. ⚠️ Cross-household within the same group — **NOT** covered by `multitenants`. Must use the `h2_user` fixture (`fixture_users.py:55–118`), which builds a second household in `unique_user`'s group via `admin_token` + `api_routes.admin_households`.
3. ⚠️ Cross-household 404/403 when calling archive/unarchive on another household's list — same `h2_user` pattern. The closest existing precedent is `test_shopping_lists_add_cross_household_recipe` (`test_group_shopping_lists.py:364–422`), which uses `h2_user` to create a resource then validates `unique_user`'s view of it. The new tests invert that: `h2_user` creates and archives, `unique_user` tries to access and gets 404.

---

## 3. Test fixtures for creating users / households / groups / shopping_lists / items

| # | Path | Symbols / line_ranges | Scope | Reason |
|---|------|----------------------|-------|--------|
| 3.1 | `tests/fixtures/fixture_users.py` | `build_unique_user(session, group, api_client)` (17–52); `h2_user` (55–118) — same group, **different household**; `g2_user` (121–176) — **different group**; `_unique_user` (179–216); `unique_user_fn_scoped` (219–221, function-scoped); `unique_user` (224–226, module-scoped); `unique_admin` (229–233); `user_tuple` (236–306) — 2 users in same group + household; `user_token` (309–328); `ldap_user` (331–351). | mixed | All identity fixtures. `h2_user` is what we need for §4-2 cross-household-same-group isolation tests. Each `TestUser` carries `.repos` already scoped, so repo-level seeding inside a household just works. |
| 3.2 | `tests/fixtures/fixture_shopping_lists.py` | `create_item(list_id)` helper (10–21) — note `checked=False` default; `shopping_lists` (24–46) — 3 lists, function-scoped; `shopping_list` (49–65) — single list, function-scoped; `list_with_items` (68–94) — 1 list + 10 items, function-scoped. | function | Direct repo-level seeding via `unique_user.repos.group_shopping_lists.create(ShoppingListSave(...))` and `unique_user.repos.group_shopping_list_item.create(ShoppingListItemCreate(...))`. The archive feature will need a new `archived_list` / `archived_lists` fixture (see §10) following this exact pattern; the trick is that you can't set `archived_at` via `ShoppingListSave` (that field doesn't exist yet) — set it via a follow-up `update` once the new field is added, or expose `ShoppingListService.archive_list` and call it. |
| 3.3 | `tests/fixtures/fixture_admin.py` | `admin_token` session-scoped (13–18); `admin_user` module-scoped (21–58). | session/module | Required by `h2_user` (to create the second household via `api_routes.admin_households`) and `g2_user`. |
| 3.4 | `tests/utils/fixture_schemas.py` | `TestUser` dataclass (9–28) — fields: `email`, `user_id`, `username`, `full_name`, `password`, `_group_id`, `_household_id`, `token`, `auth_method`, `repos`. Properties: `group_id` (str) (22–24), `household_id` (str) (26–28). | — | Type used everywhere. Note: pass `unique_user.user_id` (UUID) for things like `archived_by_user_id` in seed; pass `unique_user.group_id` (string) when comparing JSON response fields. |
| 3.5 | `tests/utils/factories.py` | `random_string(length=10)` (7–8), `random_email` (11–12), `random_bool` (15–16), `random_int(min, max)` (19–20), `user_registration_factory` (23–34). | — | Every new test uses `random_string()` for `name` so concurrent module-scoped runs don't collide on uniqueness constraints. |

---

## 4. Async client / TestClient pattern for routes

| # | Path | Symbols / line_ranges | Importance | Reason |
|---|------|----------------------|------------|--------|
| 4.1 | `tests/conftest.py` | Top-of-file MonkeyPatch setting `PRODUCTION=True`, `TESTING=True`, `ALLOW_SIGNUP=True` (19–22); `api_client` session-scoped (45–53) wrapping `TestClient(app)` with `app.dependency_overrides[generate_session] = override_get_db`; `override_get_db` (37–42) yields a fresh `SessionLocal`. File = 47 lines. | **Critical** | Mealie tests use the **synchronous** `fastapi.testclient.TestClient`, NOT `httpx.AsyncClient`. All new tests follow `def test_xxx(api_client: TestClient, ...): response = api_client.post(url, json=..., headers=token)`. No `async def`, no `await`. |
| 4.2 | `tests/utils/api_routes/__init__.py` | Header comment "This Content is Auto Generated for Pytest" (line 1); `households_shopping_lists` constant (114); `households_shopping_items` constant (110); `households_shopping_lists_item_id(item_id)` function (405–407); `households_shopping_items_item_id(item_id)` function (400–402); plus `households_shopping_items_create_bulk` (112), `households_shopping_lists_item_id_recipe(...)` (415–417), etc. | **Critical** | **AUTO-GENERATED FILE.** New routes (`/{id}/archive`, `/{id}/unarchive`) won't exist until `task dev:generate` is rerun after the route is added. Tests may either (a) use the generated constant `api_routes.households_shopping_lists_item_id_archive(id)` after regeneration, or (b) construct the URL inline (`f"{api_routes.households_shopping_lists_item_id(id)}/archive"`) for the first round of TDD. |
| 4.3 | `tests/utils/assertion_helpers.py` | `assert_deserialize(response, expected_status_code=200)` (23–25) — asserts status then returns `response.json()`; `assert_ignore_keys` (4–20). File = 19 lines. | High | Standard helper — every shopping-list test uses `as_json = utils.assert_deserialize(response, 201)`. New tests should do the same. For 409 cases use `assert response.status_code == 409` + `assert response.json()["detail"]["message"] == ...` (no helper for the message part exists). |
| 4.4 | `tests/utils/user_login.py` (re-exported as `utils.login` via `tests/utils/__init__.py:5`) | `login(form_data, api_client)` returns `headers` dict. | High | Used by all `*_user` fixtures to obtain a Bearer token. Tests never call this directly; they receive `unique_user.token` already populated. |

---

## 5. How i18n errors are asserted in tests (current pattern)

**There is no established pattern for asserting i18n error messages by key.** Verified findings:

| # | Path | Line | What it shows |
|---|------|------|---------------|
| 5.1 | `tests/integration_tests/user_recipe_tests/test_recipe_crud.py` | 1109–1111 | `assert response.status_code == 404` then `assert response.json()["detail"]["message"] == "No Entry Found"`. This is a **literal English string** assertion, not an i18n-key assertion. |
| 5.2 | `tests/integration_tests/public_explorer_tests/test_public_recipes.py` | 196, 198, 393, 398 | Same pattern: `assert response.json()["detail"] == "group not found"` (literal string). |
| 5.3 | `mealie/schema/response/responses.py` | 8–19 | `ErrorResponse(message: str, error: bool=True, exception: str \| None=None)` and `ErrorResponse.respond(message, exception=None)` returns the dict. This is what `HTTPException(..., detail=ErrorResponse.respond(message=self.t(key)))` wraps. So the **response body shape** is `{"detail": {"message": "<translated>", "error": true, "exception": null}}`. |
| 5.4 | `mealie/routes/_base/base_controllers.py` | 43–44 | `self.t` is `self.translator.t` (FastAPI dep `get_locale_provider`). At test time the default locale is en-US, so `self.t("shopping-list.archive.unchecked-items")` resolves to the en-US.json value, e.g. `"Cannot archive a shopping list with unchecked items"`. |
| 5.5 | `mealie/lang/messages/en-US.json` | 1–52 | Existing top-level groups: `generic`, `recipe`, `mealplan`, `user`, `exceptions` (with `username-conflict-error`, `email-conflict-error` at 51–52). The new keys belong under a new `shopping-list` group (or `exceptions` for shared error codes). |

### Recommended pattern for archive tests (new convention)

```python
EXPECTED_UNCHECKED_MSG = "Cannot archive a shopping list with unchecked items"  # mirrors lang/messages/en-US.json
EXPECTED_FROZEN_MSG = "This shopping list is archived and cannot be modified"

assert response.status_code == 409
body = response.json()
assert body["detail"]["message"] == EXPECTED_UNCHECKED_MSG
assert body["detail"]["error"] is True
```

The literal strings should be defined once at the top of each test module (or in `tests/utils/assertion_helpers.py`) and must match en-US.json exactly. We are NOT asserting the i18n key itself because the response is already rendered. There is no existing 409 assertion in the entire `tests/` tree to copy from — this case will set the precedent.

---

## 6. Event bus testing pattern (mocking the event dispatcher)

The codebase has **two distinct mocking layers** for event-bus side effects, both in use today:

| # | Path | Symbols / line_ranges | Layer | Reason |
|---|------|----------------------|-------|--------|
| 6.1 | `tests/integration_tests/user_household_tests/test_group_webhooks.py` | `test_post_test_webhook` (91–130): builds `mock_calls = []`, defines `mock_post(*args, **kwargs)` that appends to it, then `monkeypatch.setattr("mealie.services.event_bus_service.publisher.requests.post", mock_post)` (104), then asserts `len(mock_calls) == 1` and inspects `args`/`kwargs[json]`. | **Outbound transport** (HTTP) | Catches what would have gone out the wire to a webhook listener. Useful for end-to-end "event was eventually published" checks but doesn't easily let you inspect the structured payload before serialization. |
| 6.2 | `tests/unit_tests/services_tests/scheduler/tasks/test_post_webhook.py` | `WebhookEventListener(UUID(unique_user.group_id), UUID(unique_user.household_id))` (67, 127); `event_bus_listener.get_scheduled_webhooks(start, end)` (68, 128); `event_bus_listener.publish_to_subscribers(event, subscribers)` (130); manual `Event(...)` and `EventWebhookData(...)` construction (115–125). | **Direct listener** | Tests the listener-side handling of an `Event` object. Useful for ensuring our new `EventShoppingListArchivedData` payload is correctly serialized by listeners — but does NOT cover whether the controller actually dispatches the right event in the first place. |
| 6.3 | `tests/integration_tests/user_household_tests/test_group_notifications.py` | Imports `AppriseEventListener` (line 4), `Event` (5), `EventBusMessage`, `EventDocumentDataBase`, `EventDocumentType`, `EventOperation`, `EventTypes` (6–11); `event_generator()` (line ~56–61) builds `Event(message=EventBusMessage(...), event_type=EventTypes.test_message, integration_id=..., document_data=EventDocumentDataBase(...))`; `test_apprise_event_bus_listener_functions` (152+). | Direct listener | Reference for constructing fake `Event` objects in tests. |
| 6.4 | `mealie/services/event_bus_service/event_bus_service.py` | `EventBusService.dispatch(integration_id, group_id, household_id, event_type, document_data, message)` (66–96); `_publish_event(event, group_id, household_id)` (60–64); `as_dependency(bg, session)` (98–105). | Source | This is the method we need to intercept to verify the spec §5 payload contract (`list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`). |
| 6.5 | `mealie/routes/_base/base_controllers.py` | `BaseCrudController.publish_event(event_type, document_data, group_id, household_id, message)` (199–214) — thin wrapper that calls `self.event_bus.dispatch(...)`. | Source | Controllers call `self.publish_event(...)`, which delegates to `EventBusService.dispatch`. Mocking `EventBusService.dispatch` is the cleanest seam to capture payload. |
| 6.6 | `mealie/services/event_bus_service/event_types.py` | `EventShoppingListData(EventDocumentDataBase)` (130–132) — `document_type = EventDocumentType.shopping_list`, `shopping_list_id: UUID4`. Existing `EventTypes.shopping_list_created/_updated/_deleted` (42–44). | Source | Two new enum values needed: `shopping_list_archived` and `shopping_list_unarchived`. New `EventShoppingListArchivedData` (subclass of `EventDocumentDataBase`) must hold all spec-§5 fields and **only** those fields. |

### Recommended pattern for archive event-bus tests

Combine the existing patterns — intercept at `EventBusService.dispatch` to capture the structured payload before any background-task dispatch happens:

```python
def test_archive_dispatches_event(
    monkeypatch: pytest.MonkeyPatch,
    api_client: TestClient,
    unique_user: TestUser,
    list_with_items: ShoppingListOut,
):
    captured: list[dict] = []

    def fake_dispatch(self, *, integration_id, group_id, household_id, event_type, document_data, message=""):
        captured.append({
            "event_type": event_type,
            "group_id": str(group_id),
            "household_id": str(household_id),
            "document_data": document_data.model_dump() if document_data else None,
            "message": message,
        })

    monkeypatch.setattr(
        "mealie.services.event_bus_service.event_bus_service.EventBusService.dispatch",
        fake_dispatch,
    )
    # ... check all items, then POST archive, then:
    archived_events = [e for e in captured if e["event_type"].name == "shopping_list_archived"]
    assert len(archived_events) == 1
    payload = archived_events[0]["document_data"]
    assert payload["shopping_list_id"] == str(list_with_items.id)
    assert payload["household_id"] == unique_user.household_id  # spec §5 explicit field
    assert "other_household_id" not in payload  # spec §5: payload must NOT contain other household's data
```

Note: monkeypatching `EventBusService.dispatch` bypasses the `BackgroundTasks` plumbing entirely, which is fine because dispatch is called synchronously from the controller before `bg.add_task` queues the actual publish.

---

## 7. Conftest setup for db rollback

| # | Path | Line | Detail |
|---|------|------|--------|
| 7.1 | `tests/conftest.py` | 37–42 | `override_get_db` yields a fresh `SessionLocal()` and closes it on exit. **There is no transaction rollback.** Tests rely on `random_string()` everywhere for uniqueness and on per-fixture `try/except` cleanup in `yield` teardowns. |
| 7.2 | `tests/conftest.py` | 45–53 | `api_client` is **session-scoped** and installs the override exactly once. The override is removed implicitly on session end (the test runner unloads the module). |
| 7.3 | `tests/conftest.py` | 66–71 | `global_cleanup` (session-scoped, autouse) — only cleans the `.temp` directory after the whole session ends; does not touch the DB. |
| 7.4 | `tests/fixtures/fixture_database.py` | 10–16 | `session` fixture is **module-scoped**, not function-scoped — same SQLAlchemy session is reused across all tests in a module. This is why module-scoped `unique_user` works. |
| 7.5 | `tests/fixtures/fixture_shopping_lists.py` | 42–46, 62–65, 91–94 | Cleanup pattern for any new archive fixture: `try: database.group_shopping_lists.delete(model.id) except sqlalchemy.exc.NoResultFound: pass`. The bare `except Exception:` form (lines 45, 64) is also acceptable — it's the prevailing convention. |

**Implication for archive tests:** Because there is no per-test rollback, any test that calls `POST .../archive` and then doesn't unarchive will leave that list in archived state for the rest of the module. The `shopping_list` / `list_with_items` fixtures are function-scoped, so the cleanup `database.group_shopping_lists.delete(...)` removes the row entirely — no leakage. But the **module-scoped** `unique_user`'s default `Family` shopping list (auto-created at user registration) persists; tests that POST to `/lists` without using a fixture leak. Recommended: use the existing `shopping_lists`/`shopping_list` fixtures for all archive tests, never create lists ad-hoc.

---

## 8. Test scaffolding plan (concrete files + test function names required by §8)

### 8A. Unit tests (≥4 required by §8)

**New file:** `tests/unit_tests/services_tests/household_services/__init__.py` (empty) and `tests/unit_tests/services_tests/household_services/test_shopping_list_archive.py`

Model after: `tests/unit_tests/services_tests/user_services/test_user_service.py` (85 lines) — instantiates the service from `unique_user.repos` and calls methods directly.

```python
# tests/unit_tests/services_tests/household_services/test_shopping_list_archive.py
from mealie.services.household_services.shopping_lists import ShoppingListService
from tests.utils.fixture_schemas import TestUser
from mealie.schema.household.group_shopping_list import ShoppingListOut

def test_archive_list_all_items_checked_marks_archived_at(unique_user_fn_scoped: TestUser, list_with_items: ShoppingListOut): ...
def test_archive_list_with_unchecked_items_raises(unique_user_fn_scoped: TestUser, list_with_items: ShoppingListOut): ...
def test_archive_list_records_archived_by_user_id(unique_user_fn_scoped: TestUser, list_with_items: ShoppingListOut): ...
def test_unarchive_list_clears_archived_at_and_user(unique_user_fn_scoped: TestUser, list_with_items: ShoppingListOut): ...
def test_unarchive_already_unarchived_is_noop(unique_user_fn_scoped: TestUser, shopping_list: ShoppingListOut): ...
def test_archive_already_archived_is_noop_or_409(unique_user_fn_scoped: TestUser, list_with_items: ShoppingListOut): ...
```

**New file:** `tests/unit_tests/repository_tests/test_shopping_list_archive_repository.py` — model after `tests/unit_tests/repository_tests/test_food_repository.py:1–40`.

```python
def test_repo_query_default_excludes_archived(unique_user_fn_scoped: TestUser): ...
def test_repo_query_with_archived_true_returns_only_archived(unique_user_fn_scoped: TestUser): ...
def test_repo_query_with_archived_all_returns_both_with_archived_at_field(unique_user_fn_scoped: TestUser): ...
```

These three repo tests verify the spec §7 "implement filter centrally in `mealie/repos/repository_shopping_list.py`" constraint — the repo layer must honor the `archived` parameter without controller help.

### 8B. Integration tests

**New file:** `tests/integration_tests/user_household_tests/test_group_shopping_list_archive.py`

Model after: `test_group_shopping_lists.py` (1113 lines) for CRUD test shape, `test_group_webhooks.py:91–130` for event-bus monkeypatch.

```python
# Mark all archive routes & expected English error strings at top
ARCHIVE_PATH = lambda lid: f"/api/households/shopping/lists/{lid}/archive"
UNARCHIVE_PATH = lambda lid: f"/api/households/shopping/lists/{lid}/unarchive"
ERR_UNCHECKED = "Cannot archive a shopping list with unchecked items"  # MUST match en-US.json
ERR_FROZEN = "This shopping list is archived and cannot be modified"   # MUST match en-US.json

# Spec §8 bullet 1: archive 成功 + list 不在默认查询中
def test_archive_succeeds_with_all_items_checked(api_client, unique_user, list_with_items): ...
def test_archived_list_hidden_from_default_query(api_client, unique_user, list_with_items): ...
def test_archived_list_visible_with_archived_true_query(api_client, unique_user, list_with_items): ...
def test_archive_all_query_returns_both_with_archived_at_field(api_client, unique_user, shopping_list, list_with_items): ...

# Spec §8 bullet 2: archive 失败（有 unchecked items）
def test_archive_fails_409_when_items_unchecked(api_client, unique_user, list_with_items): ...
def test_archive_409_message_matches_en_us_locale(api_client, unique_user, list_with_items): ...

# Spec §8 bullet 3: 归档后 PUT/POST/DELETE item 都返回 409
def test_put_list_metadata_on_archived_returns_409(api_client, unique_user, list_with_items): ...
def test_post_item_to_archived_list_returns_409(api_client, unique_user, list_with_items): ...
def test_put_item_in_archived_list_returns_409(api_client, unique_user, list_with_items): ...
def test_put_item_checked_field_in_archived_list_returns_409(api_client, unique_user, list_with_items): ...
def test_delete_item_in_archived_list_returns_409(api_client, unique_user, list_with_items): ...
def test_all_409_responses_use_frozen_i18n_message(api_client, unique_user, list_with_items): ...

# Spec §8 bullet 4: unarchive 后所有操作恢复
def test_unarchive_restores_put_list_metadata(api_client, unique_user, list_with_items): ...
def test_unarchive_restores_post_item(api_client, unique_user, list_with_items): ...
def test_unarchive_restores_put_item(api_client, unique_user, list_with_items): ...
def test_unarchive_restores_delete_item(api_client, unique_user, list_with_items): ...

# Spec §8 bullet 5: ?archived=true / ?archived=all query 行为 (already partly above)
def test_archived_query_response_includes_archived_at_field(api_client, unique_user, list_with_items): ...
def test_archived_query_response_includes_archived_by_user_summary(api_client, unique_user, list_with_items): ...
def test_default_query_response_omits_archived_at_for_backwards_compat(api_client, unique_user, shopping_list): ...

# Spec §8 bullet 6: 事件总线 payload 校验
def test_archive_dispatches_shopping_list_archived_event(monkeypatch, api_client, unique_user, list_with_items): ...
def test_unarchive_dispatches_shopping_list_unarchived_event(monkeypatch, api_client, unique_user, list_with_items): ...
def test_archive_event_payload_contains_required_fields(monkeypatch, api_client, unique_user, list_with_items): ...
def test_archive_event_payload_does_not_leak_other_household_data(monkeypatch, api_client, unique_user, h2_user, list_with_items): ...
```

Use `unique_user_fn_scoped` instead of `unique_user` for any test that archives without unarchiving (mirroring `test_label_create_duplicate_name_returns_400` at `test_shopping_list_labels.py:23–28`).

### 8C. Multitenant tests (3 scenarios required by §8)

**New file:** `tests/multitenant_tests/case_shopping_list_archive.py` — model after `case_foods.py` (39 lines).

```python
# tests/multitenant_tests/case_shopping_list_archive.py
class ArchivedShoppingListsTestCase(ABCMultiTenantTestCase):
    items: list[ShoppingListOut]

    def seed_action(self, group_id: str) -> set[str]:
        # create N shopping lists in this group's default household, mark archived_at=now
        ...

    def seed_multi(self, group1_id, group2_id) -> tuple[set[str], set[str]]:
        # same-named archived lists in both groups
        ...

    def get_all(self, token: str) -> Response:
        return self.client.get(api_routes.households_shopping_lists, params={"archived": "true"}, headers=token)

    def cleanup(self) -> None:
        for item in self.items:
            self.database.group_shopping_lists.delete(item.id)
```

Then register in `tests/multitenant_tests/test_multitenant_cases.py:13–19`:
```python
all_cases = [UnitsTestCase, FoodsTestCase, ToolsTestCase, TagsTestCase, CategoryTestCase, ArchivedShoppingListsTestCase]
```
This automatically gets coverage for spec §8-multitenant bullet 2 ("cross group complete isolation") via the existing parametrized `test_multitenant_cases_get_all` and `test_multitenant_cases_same_named_resources` (`test_multitenant_cases.py:22–93`).

**New file:** `tests/multitenant_tests/test_shopping_list_archive_household.py` — for the spec's §8-multitenant bullets 1 and 3 that the case-based driver does NOT cover (because `multitenants` is cross-group, not cross-household):

```python
# Spec §8-multitenant bullet 1: 同 group 内其他 household 看不到对方归档 list
def test_archived_list_invisible_to_other_household_in_same_group(api_client, unique_user, h2_user, list_with_items): ...
def test_archived_query_does_not_leak_other_household_lists(api_client, unique_user, h2_user, list_with_items): ...

# Spec §8-multitenant bullet 3: 跨 household 调用 archive 接口返回 404 / 403
def test_archive_other_household_list_returns_404(api_client, unique_user, h2_user, list_with_items): ...
def test_unarchive_other_household_list_returns_404(api_client, unique_user, h2_user, list_with_items): ...
def test_archive_other_group_list_returns_404(api_client, unique_user, g2_user, list_with_items): ...
```

Note: this file goes under `tests/multitenant_tests/` for taxonomic clarity (these are multitenant assertions) but does NOT subclass `ABCMultiTenantTestCase` (the abstract case driver doesn't fit the cross-household-within-group scenario). Precedent for this hybrid: there is no existing file like this — we'd be the first. Alternative: place it in `tests/integration_tests/user_household_tests/test_group_shopping_list_archive_isolation.py`. **Recommendation: place under `multitenant_tests/` to keep all isolation tests together**, but flag this choice for cross-perspective discussion.

---

## 9. Multitenant test patterns to reuse (the exact existing class/function the new tests should model after)

| Spec §8 multitenant scenario | Model after | File:lines |
|------------------------------|-------------|------------|
| Same-group, other-household can't see archived list | `test_shopping_lists_add_cross_household_recipe` | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py:364–422` (uses `h2_user` to create resource in second household, then probes from `unique_user`'s perspective) |
| Cross-group complete isolation | `FoodsTestCase` + `test_multitenant_cases_get_all` | `tests/multitenant_tests/case_foods.py:9–50` and `tests/multitenant_tests/test_multitenant_cases.py:22–56` (parametrized driver — just add `ArchivedShoppingListsTestCase` to `all_cases` list at line 13–19) |
| Same-named archived lists in different groups don't collide | `test_multitenant_cases_same_named_resources` | `tests/multitenant_tests/test_multitenant_cases.py:59–93` (automatic via case driver — `seed_multi` must produce same-named lists) |
| Cross-household calling archive endpoint → 404 | `test_get_household_recipe_invalid_recipe` (precedent for 404 from cross-household-scoped query) | `tests/integration_tests/user_household_tests/test_household_self_service.py:81–85` (asserts `status_code == 404` for a foreign slug). Adapt for `POST .../archive`. |

---

## 10. Cross-perspective questions

These need answers from the **design / coding / spec** perspectives before tests can be finalized:

1. **Fixture surface** — Will the design expose a public `ShoppingListService.archive_list(list_id, user_id)` and `.unarchive_list(list_id)` method that tests can call directly to set up `archived_list` / `archived_lists` fixtures? Or must the fixture create a non-archived list and then POST `/archive` via `api_client`? **Test impact:** if no public service method exists, every archive fixture must perform an API round-trip, slowing the suite and making fixture setup depend on the route working — circular for the first round of TDD.

2. **Pre-existing seeded "Family" list** — The module-scoped `unique_user` triggers user-registration, which creates a default "Family" shopping list. Does the spec want archive tests to ignore that list (use `shopping_list` / `list_with_items` fixtures exclusively and filter by `id in known_ids`), or must `GET /lists` total counts factor it in? **Recommendation:** all `len()` assertions on `/lists` responses should use `len([l for l in items if l["id"] in known_ids])` to be robust against the default Family list.

3. **What's the exact en-US message text for the two new keys?** — Tests must literal-string-match what `self.t(key)` produces. The coding perspective needs to decide:
   - `shopping-list.archive.unchecked-items` → `"Cannot archive a shopping list with unchecked items"` (suggested)
   - `shopping-list.archived.frozen` → `"This shopping list is archived and cannot be modified"` (suggested)
   
   Whoever owns `lang/messages/en-US.json` must agree on the strings before tests can assert them; otherwise tests will be brittle.

4. **`?archived` parameter type** — Is it a string enum (`"true"` / `"false"` / `"all"`) or a more idiomatic `archived: bool | Literal["all"] | None`? Spec §2 implies string. Tests must use the right query-string value: `params={"archived": "true"}` vs. `params={"archived": True}` will differ in how FastAPI parses them. **Decision needed before writing the query-behavior tests.**

5. **Event payload field naming** — Spec §5 lists `list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`. The existing `EventShoppingListData` (event_types.py:130–132) uses `shopping_list_id`, not `list_id`. Should the new `EventShoppingListArchivedData` follow the spec's exact names or align with the existing convention (`shopping_list_id`)? **Test impact:** the payload-validation tests need the exact field names — pick one and document.

6. **Cross-household 404 vs 403** — Spec §8-multitenant says "404 / 403". Mealie's current convention everywhere else is **404** (repos return None for out-of-scope IDs, controllers raise NoEntryFound → 404, e.g., recipe lookup at `test_recipe_crud.py:1109–1111`). Does the archive feature follow the 404 convention or introduce 403? **Recommendation:** stay with 404 to match the existing pattern, but the spec perspective should confirm.

7. **Item-modification 409 routing** — Spec §3 says PUT/POST/DELETE to `/items` on an archived list must 409. The item routes don't know which list they belong to until they look the item up. Where does the check live — in `ShoppingListItemController` (routes/households/controller_shopping_lists.py:98–153), in `ShoppingListService.bulk_create_items` / `bulk_update_items` / `bulk_delete_items` (services/household_services/shopping_lists.py:154, 225, 312), or in the item repository? **Test impact:** unit tests vs. integration tests need to assert the 409 at the same layer the validation lives at. If checks are in the service, we can write fast unit tests; if only in controllers, integration tests are the only option.

8. **Module-scope leakage on `h2_user`-created lists** — `h2_user` is module-scoped (`fixture_users.py:55`). If a multitenant test creates an archived list via `h2_user.repos.group_shopping_lists.create(...)` and forgets to clean up, the row lingers across tests in the same module. Should `list_with_items` accept a `user` parameter, or should we add a new `h2_list_with_items` function-scoped fixture? **Recommendation:** add `tests/fixtures/fixture_shopping_lists.py` helper `_make_list_with_items(user: TestUser) -> ShoppingListOut` and have both fixtures call it; add `h2_list_with_items` for cross-household tests.

9. **Are async tests on the table?** — Mealie tests are 100% sync (`fastapi.testclient.TestClient`). The spec doesn't say `async`. Confirming so we don't accidentally add `pytest-asyncio` and `httpx.AsyncClient` for the first time in this feature.

10. **Default-list creation hook** — Does archiving "the last list in a household" trigger any auto-creation behavior elsewhere (e.g., mealplan view falls back to creating a new default list)? If so, integration tests for `GET /lists` immediately after archive may see an unexpected new list materialize. The spec perspective should enumerate downstream consumers (see the eval rubric §"Spec — 是否枚举出**所有**消费 shopping list 的下游接口"). Tests can only assert what the spec defines; gaps here lead to brittle assertions.
