# Executability Review (v1)

## Verdict: NEEDS_REFINE

The spec is close, but not fully executable as written. Every cited Mealie path exists, the markdown and JSON `code_references` are identical for every FR, and there are no leftover `TBD`, `or equivalent`, or `if needed` phrases. However, at least one citation is materially wrong/imprecise, and the scheduler/idempotency flow contradicts itself about when `last_auto_synced_at` is updated.

---

## Scope checks

| Check | Result |
|---|---|
| All cited paths real? | ✅ Pass. Opened every cited path under `C:\Users\v-liyuanjun\Downloads\mealie\`; all exist. |
| All line ranges accurate and cited symbol in range? | ⚠️ Mostly pass. The cited symbols are present in their listed ranges, but FR-019 cites the wrong model/range for its target-list selection behavior. See wrong/imprecise citations. |
| `spec.md` / `spec.json` `code_references` identical for each FR? | ✅ Pass. Parsed all 22 FRs; ordered path/range/symbol lists match exactly between markdown and JSON. |
| TBD / `or equivalent` / `if needed` phrases? | ✅ Pass. No exact matches in `spec.md` or `spec.json`. |
| ≥3 options pattern in `self_concerns`? | ✅ Pass. The self-concerns section has three concerns, each with one suggested resolution; no untriaged ≥3-options pattern remains there. |
| Scheduler task implementation seam concrete enough? | ❌ Not yet. Module/function/registration seam is concrete, but gating/CAS/update timing is internally inconsistent. |
| Pantry filter algorithm pin-pointed? | ⚠️ Partially. The predicate is concrete, but the spec does not pin whether filtering happens before or after recursive sub-recipe expansion. |
| `LastAutoSyncedAt` storage column concrete? | ⚠️ Column/migration/CAS are concrete, but server update timing conflicts across FR-010 and edge cases. |
| Concrete query for today's MealPlan in household tz? | ✅ Pass. `RepositoryMeals.get_today(tz=ZoneInfo(...))` maps to `today = datetime.now(tz).date()` and `GroupMealPlan.date == today AND household_id == current household`. |

---

## Wrong/imprecise citations

1. **FR-019** — `mealie/db/models/household/shopping_list.py` L51-98 cites `ShoppingListItem`, `food_id`, and `checked`, but FR-019 is about selecting the first household shopping list ordered by `ShoppingList.created_at`. The relevant `ShoppingList` model is at `shopping_list.py` L147-181, while `created_at` comes from `mealie/db/models/_model_base.py` L18-23. The cited range does not substantiate `ShoppingList.created_at` or target-list fallback selection.
2. **FR-018** — `mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py` L20-32 only shows `upgrade()` and an example `household_preferences` `batch_alter_table`; FR-018 also requires a downgrade pair, which is at L35-45 and is not cited.
3. **FR-015** — citations to `EventShoppingListData` L130-132 are accurate but incomplete for construction: `EventShoppingListData` inherits required `operation` from `EventDocumentDataBase` L88-91. The requirement says the subclass carries `shopping_list_id` but does not specify `operation=EventOperation.update`, unlike existing call sites such as `controller_shopping_lists.py` L246-249.

---

## Executability concerns

### Critical

- **EXEC-C-001 — `last_auto_synced_at` update timing contradicts itself.** FR-010 says perform the conditional UPDATE before reading meal plans and abort on rowcount zero. Edge cases say no meal plan or missing/deleted target list should not bump `last_auto_synced_at`, and claim the conditional UPDATE only fires when items are appended. Both cannot be true. Choose one concrete flow; recommended: acquire a per-day claim before side effects, but if later no-op/error should not count as synced, explicitly reset or defer the CAS with a separate claim column.
- **EXEC-C-002 — 30-minute scheduler window is not executable as specified.** FR-008 says skip when `last_auto_synced_at` is later than `(household_local_today - 30 minutes)`, while FR-010 uses `last_auto_synced_at < :today_local_midnight_utc`. These are different day-boundary predicates. The spec also does not state the actual “only run during first 30 minutes after local midnight” condition, despite the summary claiming a 30-minute window.

### High

- **EXEC-H-001 — Pantry filtering and recipe loading need one precise implementation path.** FR-011 passes `recipe_ingredients=None`, which makes `ShoppingListService.get_shopping_list_items_from_recipe()` fetch full recipe ingredients internally. FR-012 says pre-filter the recipe-ingredient list passed to `add_recipe_ingredients_to_list`, which requires the task to fetch full recipes first and pass a filtered `recipe_ingredients` override. Add explicit steps and citations to `get_shopping_list_items_from_recipe()` L323-340 and the full `Recipe.recipe_ingredient` schema/model path.
- **EXEC-H-002 — Sub-recipe pantry behavior is undefined.** Existing shopping-list generation recursively expands referenced recipes at `shopping_lists.py` L343-350. FR-012 only describes filtering the top-level list before calling `add_recipe_ingredients_to_list`; it does not say whether pantry staples inside referenced/sub-recipes are filtered. Pin this before implementation.
- **EXEC-H-003 — Event payload is missing required `operation`.** FR-015 should require `EventShoppingListData(operation=EventOperation.update, shopping_list_id=...)` and cite/import `EventOperation`, otherwise a coding agent may construct an invalid pydantic payload.

### Medium

- **EXEC-M-001 — Target list fallback needs a real repository/query seam.** FR-019’s desired behavior is concrete in prose, but it cites only the item model. Add the exact repository call or SQLAlchemy query, including household scoping, non-deleted semantics if applicable, and `order_by=ShoppingList.created_at`.
- **EXEC-M-002 — i18n key spelling is inconsistent.** The summary and US-9 use `mealplan.auto_sync.*` with underscores, while FR-016 and edge cases use `mealplan.auto-sync.*` with hyphens. Choose one key namespace.

---

## Verified key citations

- `mealie/services/scheduler/scheduler_registry.py` L41-48, `mealie/app.py` L124-144, and `mealie/services/scheduler/scheduler_service.py` L15-17/L77-81 verify the registration and 5-minute minutely bucket seam.
- `mealie/repos/repository_meals.py` L11-21 verifies the household-timezone “today” query shape.
- `mealie/db/models/household/preferences.py` L16-44, `mealie/db/models/_model_utils/datetime.py` L20-50, and the migration example verify the intended storage layer for `last_auto_synced_at`.
- `mealie/services/household_services/shopping_lists.py` L413-455 verifies the add-recipe seam; L323-350 verifies the full-recipe fetch and recursive sub-recipe expansion path that the spec still needs to address.
