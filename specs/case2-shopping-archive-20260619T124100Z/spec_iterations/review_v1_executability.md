# Executability Review v1 — Case-2 Shopping List Archive

## Verdict

**Needs revision before implementation.** The core feature is mostly executable, but several cited paths are not real in the checked Mealie tree, `spec.md` and `spec.json` code references diverge for three FRs, and the event/translator/repository-constructor seams still contain ambiguity that a coding agent would have to resolve.

## Checks performed

- Opened `spec.md` and `spec.json`.
- Opened every concrete existing Mealie file cited by FR `code_references` and relevant inline/test-plan citations.
- Verified each cited line range contains the cited symbol/pattern.
- Compared FR `code_references` in `spec.md` vs `spec.json`.
- Searched both specs for `TBD`, `TODO`, `or equivalent`, `if needed`, `如有`, `类似`, and related ambiguous phrases.

## Path reality

### Missing / wrong cited existing paths

- **FR-2 `spec.json`** cites `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_and_household_to_foods_and_household_to_tools.py`; the real file is `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_.py`.
- **FR-3 `spec.md` and `spec.json`** cite `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_group_notifier_options.py`; the real file is `mealie/alembic/versions/2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_.py`.
- **EC-4** cites `mealie/services/household_services/cookbook_service.py`; no such file exists in this tree.
- **EC-5** cites `tests/integration_tests/backup_v2_tests/`; the real backup tests are under `tests/unit_tests/services_tests/backup_v2_tests/`.

### Planned new paths not yet real

Expected/new paths are not on disk yet and should be marked as new files, not verified existing references: `mealie/repos/repository_shopping_list_item.py`, new alembic migrations, `tests/multitenant_tests/case_shopping_list_archive.py`, and `tests/multitenant_tests/test_shopping_list_archive_household.py`.

All other concrete existing FR paths checked exist.

## Wrong/imprecise citations

1. **FR-2 migration filename mismatch.** `spec.md` uses a wildcard for the `2024-11-20...` migration, while `spec.json` uses a non-existent full filename. Normalize both to the actual truncated filename.
2. **FR-3 migration filename is wrong in both specs.** The cited line range `1-51` is accurate only if applied to the actual truncated file `...add_mealplan_updated_and_deleted_to_.py`.
3. **FR-10 / FR-12 `event_bus_service.py:66-96` is imprecise for subscriber filtering.** It shows `dispatch` and the per-household loop, but actual listener/subscriber selection is at `event_bus_service.py:54-64`. Add that range if claiming household-filtered subscribers.
4. **FR-10 event payload field-set conflicts with SC-3.** The proposed `EventShoppingListArchiveData` field list omits `operation`, but SC-3 expects `operation` in `payload.model_dump().keys()`, and `EventDocumentDataBase` requires it. Specify the operation value for archive/unarchive, likely `EventOperation.update` or `info`.
5. **FR-8 contains “or equivalent reference”.** `spec.json` line 246 leaves constructor wiring open. `spec.md` later recommends parent-repo injection, but JSON still permits alternatives. Pick one.
6. **FR-11 translator seam is not executable as written.** `spec.md` says translator parameter, method args, or global fallback; `spec.json` says dependency injection deferred. Choose the exact translation layer or mark it a design decision, not an implementation requirement.
7. **FR-15 `spec.md` combines two line ranges while `spec.json` splits them.** Both ranges are accurate, but the `code_references` arrays are not identical.
8. **SC-2 wording says “All 4 frozen routes” but then requires 7 variants.** The measurable count is clear, but the title should say 7 variants or 4 route families.

## Verified key line ranges

- `shopping_list.py:147-181` contains `ShoppingList`, `group_id`, `household_id` association proxy, `user_id`, `user`, `name`, `list_items`, `recipe_references`, `label_settings`, `extras`.
- `controller_shopping_lists.py:98-153` contains all item CRUD endpoints; `159-283` contains `ShoppingListController`; `176-184`, `186-198`, and `204-215` contain the cited handlers.
- `repository_shopping_list.py:1-12`, `repository_factory.py:317-332`, and `repository_generic.py:79-102,315-355,505-523` contain the cited repository seams/patterns.
- `group_shopping_list.py:216-238,250-285` and `user.py:191-197` contain the cited schema classes.
- `event_types.py:13-60,130-132`, `events.py:35-37`, `base_controllers.py:199-214`, `responses.py:8-19`, and scheduler lines `54-75` are accurate.
- `frontend/app/lib/api/types/household.ts:673-687,735-748` and `tests/utils/api_routes/__init__.py:114` are accurate current generated-code references.

## `spec.md` vs `spec.json` `code_references`

They are **not identical** for:

- **FR-2:** markdown uses wildcard `2024-11-20..._*.py`; JSON uses a non-existent full filename.
- **FR-10:** markdown includes `event_types.py:14-22`; JSON omits it.
- **FR-15:** markdown combines `frontend/app/lib/api/types/household.ts:673-687,735-748`; JSON splits them into two reference entries.

All other FR reference lists match after ignoring prose-description differences.

## TBD / “or equivalent” / “if needed” phrases

- No `TBD`, `TODO`, or English `if needed` found in `spec.md`/`spec.json`.
- `spec.json` contains **“or equivalent reference”** in FR-8.
- `spec.json` contains **“may need translator parameter”** in a code-reference description.
- `spec.md` and `spec.json` both retain **`total_estimated_amount (如有 / if available)`**, but NC-4 resolves it to `None`; this is acceptable if the original phrase is treated as background, not a requirement.

## Multitenant tests

Partially concrete:

- Concrete: `ArchivedShoppingListsTestCase`, `tests/multitenant_tests/test_multitenant_cases.py`, and parametrized `test_multitenant_cases_get_all` are named.
- Not concrete enough: the “≥4 in `test_shopping_list_archive_household.py`” tests are counted but not named. Add exact test function names for same-group/different-household GET, archive 404, unarchive 404, and item-mutation 404/409 behavior.

## Event payload schema executability

Mostly concrete but requires revision:

- Concrete: class name, base class, document type, id/name fields, household id, actor id, item count, and `total_estimated_amount=None` semantics.
- Blocking ambiguity: `operation` is required by the base class and SC-3 but omitted from the FR-10 allowed field list; archive/unarchive operation values are unspecified.
- Recommendation: include `operation: EventOperation = EventOperation.update` (or another explicit value) in FR-10 and update the “MUST NOT contain any field not listed above” sentence to include base fields intentionally.

## Recommendation

Revise filenames, sync `code_references`, and resolve the event/translator/repository-constructor ambiguities before handing this spec to implementation.
