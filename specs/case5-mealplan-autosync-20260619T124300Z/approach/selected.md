# Case 5 — Selected Approach (Stage 4)

## Selected: **Approach C — Hybrid (polling task + shared manual trigger)**

### One-line justification
Input §2 mandates a polling cadence ("每 30 分钟跑一次") and the spec's implementation constraints forbid building a parallel scheduler — eliminating Approach B (event-driven). Spec §3 separately mandates a manual trigger endpoint. The hybrid pulls both spec requirements into a single shared helper (`_sync_one_household`), giving us scheduler poll + spec-mandated route without code duplication.

---

## Why not the other approaches

- **Approach A (pure polling, manual trigger as duplicated logic)** — rejected because spec §3's run-now endpoint would duplicate the scheduler's per-household block. Any future change to consolidation/event payload would have to be edited in two places, and the case-3 coupling (CC8 in consolidated.md) would create two divergence risks.
- **Approach B (event-driven)** — rejected because:
  1. **Violates input §2** explicit polling mandate.
  2. **Violates spec implementation constraint** "必须复用 `mealie/services/scheduler/` 既有抽象, 不要新建并行 scheduler".
  3. **Eliminates the daily-batch semantic** the spec assumes (§2 step 6 wording implies one consolidated daily run, not per-write fan-out).
  4. **Higher complexity + brittle in tests** — SQLAlchemy ORM event listeners are not currently used in Mealie tasks and would set a new precedent.

---

## Selected approach in detail

### 1. Scheduler task file: `mealie/services/scheduler/tasks/auto_sync_shopping.py` (NEW)

```python
# Pseudocode shape, not final implementation
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from pydantic import UUID4
from sqlalchemy.orm import Session
from sqlalchemy import text

from mealie.db.db_setup import session_context
from mealie.repos.all_repositories import get_repositories
from mealie.schema.response.pagination import PaginationQuery
from mealie.schema.household.group_shopping_list import ShoppingListAddRecipeParamsBulk
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie.services.event_bus_service.event_types import (
    EventTypes,
    EventMealPlanAutoSyncedData,           # NEW
    INTERNAL_INTEGRATION_ID,
)
from mealie.services.household_services.shopping_lists import ShoppingListService

WINDOW_MINUTES = 30


def _resolve_tz(tz_str: str | None) -> ZoneInfo:
    if not tz_str:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_str)
    except Exception:
        return ZoneInfo("UTC")


def _is_in_window(now_local: datetime, run_time_hhmm: str) -> bool:
    run_h, run_m = (int(x) for x in run_time_hhmm.split(":"))
    run_dt = now_local.replace(hour=run_h, minute=run_m, second=0, microsecond=0)
    delta = (now_local - run_dt).total_seconds()
    return 0 <= delta < WINDOW_MINUTES * 60


def _sync_one_household(
    session: Session,
    group_id: UUID4,
    household_id: UUID4,
    *,
    bypass_enabled_check: bool = False,
    bypass_daily_limit: bool = False,
) -> dict:
    """Single-household sync. Shared between the scheduler tick and the run-now route.
    Returns {added_count, skipped_pantry_count, target_list_id, run_at}.
    """
    repos = get_repositories(session, group_id=group_id, household_id=household_id)
    prefs = repos.household_preferences.get_one(household_id, "household_id")
    if not prefs:
        return {"added_count": 0, "skipped_pantry_count": 0, "target_list_id": None, "run_at": datetime.now(UTC)}
    if not bypass_enabled_check and not prefs.auto_sync_meal_plan_to_shopping:
        return {"added_count": 0, "skipped_pantry_count": 0, "target_list_id": None, "run_at": datetime.now(UTC)}

    tz = _resolve_tz(prefs.timezone)
    now_local = datetime.now(tz=tz)
    now_utc = datetime.now(UTC)

    # Scheduler-only: window gate
    if not bypass_daily_limit and not _is_in_window(now_local, prefs.auto_sync_run_time):
        return {"added_count": 0, "skipped_pantry_count": 0, "target_list_id": None, "run_at": now_utc}

    # CAS UPDATE — multi-replica safety (scheduler path only)
    today_start_utc = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
    if not bypass_daily_limit:
        result = session.execute(
            text(
                "UPDATE household_preferences "
                "SET last_auto_synced_at = :now "
                "WHERE id = :id "
                "AND (last_auto_synced_at IS NULL OR last_auto_synced_at < :today_start)"
            ),
            {"now": now_utc.replace(tzinfo=None), "id": str(prefs.id), "today_start": today_start_utc},
        )
        if result.rowcount == 0:
            return {"added_count": 0, "skipped_pantry_count": 0, "target_list_id": None, "run_at": now_utc}
        session.commit()

    # Resolve target list
    target_list_id = prefs.auto_sync_target_shopping_list_id
    if target_list_id is None:
        lists = repos.group_shopping_lists.page_all(
            PaginationQuery(page=1, per_page=1, order_by="created_at", order_direction="asc")
        )
        if not lists.items:
            return {"added_count": 0, "skipped_pantry_count": 0, "target_list_id": None, "run_at": now_utc}
        target_list_id = lists.items[0].id

    # Today's meal plans
    mealplans = repos.meals.get_today(tz=tz)
    skipped_pantry = 0
    recipe_items: list[ShoppingListAddRecipeParamsBulk] = []
    shopping_list_service = ShoppingListService(repos)

    for mp in mealplans:
        if not mp.recipe_id or not mp.recipe:
            continue
        # Pantry filter: rebuild recipe_ingredients with staples excluded
        filtered_ingredients = []
        for ing in mp.recipe.recipe_ingredient or []:
            if ing.food and getattr(ing.food, "is_pantry_staple", False):
                skipped_pantry += 1
                continue
            filtered_ingredients.append(ing)
        if not filtered_ingredients:
            continue
        recipe_items.append(
            ShoppingListAddRecipeParamsBulk(
                recipe_id=mp.recipe_id,
                recipe_increment_quantity=1.0,
                recipe_ingredients=filtered_ingredients,
            )
        )

    added_count = 0
    if recipe_items:
        _updated_list, item_changes = shopping_list_service.add_recipe_ingredients_to_list(
            list_id=target_list_id, recipe_items=recipe_items
        )
        added_count = len(item_changes.created_items) + len(item_changes.updated_items)
        # Manual trigger path: also stamp last_auto_synced_at (spec §3 "仍更新它")
        if bypass_daily_limit:
            session.execute(
                text("UPDATE household_preferences SET last_auto_synced_at = :now WHERE id = :id"),
                {"now": now_utc.replace(tzinfo=None), "id": str(prefs.id)},
            )
            session.commit()

        # Event dispatch
        EventBusService(session=session).dispatch(
            integration_id=INTERNAL_INTEGRATION_ID,
            group_id=group_id,
            household_id=household_id,
            event_type=EventTypes.meal_plan_auto_synced_to_shopping,
            document_data=EventMealPlanAutoSyncedData(
                household_id=household_id,
                shopping_list_id=target_list_id,
                added_item_count=added_count,
                skipped_pantry_count=skipped_pantry,
            ),
        )

    return {
        "added_count": added_count,
        "skipped_pantry_count": skipped_pantry,
        "target_list_id": target_list_id,
        "run_at": now_utc,
    }


def auto_sync_meal_plan_to_shopping() -> None:
    """Scheduler entry-point. Iterates all groups/households and runs sync per household."""
    with session_context() as session:
        repos = get_repositories(session)
        groups = repos.groups.page_all(PaginationQuery(page=1, per_page=-1)).items
        for group in groups:
            group_repos = get_repositories(session, group_id=group.id)
            households = group_repos.households.page_all(PaginationQuery(page=1, per_page=-1)).items
            for household in households:
                try:
                    _sync_one_household(session, group.id, household.id)
                except Exception:
                    session.rollback()
                    # log & continue with next household
                    continue
```

### 2. Manual trigger route in `controller_household_self_service.py`

Add to existing controller (`mealie/routes/households/controller_household_self_service.py:1-92`):

```python
@router.post("/preferences/auto-sync-shopping/run-now", response_model=AutoSyncRunResult)
def auto_sync_shopping_run_now(self) -> AutoSyncRunResult:
    self.checks.can_manage_household()
    result = _sync_one_household(
        session=self.repos.session,
        group_id=self.group_id,
        household_id=self.household_id,
        bypass_enabled_check=True,
        bypass_daily_limit=True,
    )
    return AutoSyncRunResult(**result)
```

### 3. App registration

`mealie/app.py:134-136` becomes:
```python
SchedulerRegistry.register_minutely(
    tasks.post_group_webhooks,
    tasks.auto_sync_meal_plan_to_shopping,
)
```

### 4. Tasks `__init__.py:1-19` adds:
```python
from .auto_sync_shopping import auto_sync_meal_plan_to_shopping
# add to __all__
```

### 5. EventTypes + payload

`mealie/services/event_bus_service/event_types.py`:
- Add `meal_plan_auto_synced_to_shopping = auto()` to `EventTypes` enum (after `shopping_list_deleted` at L44).
- Add new payload class:
```python
class EventMealPlanAutoSyncedData(EventDocumentDataBase):
    document_type: EventDocumentType = EventDocumentType.shopping_list
    operation: EventOperation = EventOperation.create
    household_id: UUID4
    shopping_list_id: UUID4
    added_item_count: int
    skipped_pantry_count: int
```

### 6. Migrations (3 separate alembic files)

Per history H3 recommendation ("one migration per concern, ordered by dependency"):

1. `<ts>_add_is_pantry_staple_to_ingredient_foods.py` — mirrors `32d69327997b_add_staple_flag_to_foods.py:24-46`. Depends on current head `2187537c52b8`.
2. `<ts>_add_auto_sync_to_household_preferences.py` — adds the 5 new columns (`auto_sync_meal_plan_to_shopping`, `auto_sync_target_shopping_list_id`, `auto_sync_run_time`, `last_auto_synced_at`, `timezone`). Mirrors `be568e39ffdf_…:21-75`.
3. `<ts>_add_meal_plan_auto_synced_to_shopping_event.py` — adds Boolean column `meal_plan_auto_synced_to_shopping` to `group_events_notifier_options`. Mirrors `cdc93edaf73d_…:19-50`.

### 7. Schema changes
- `mealie/schema/household/household_preferences.py:10-22` — add 5 fields with validators (HH:MM regex; ZoneInfo validity).
- `mealie/schema/recipe/recipe_ingredient.py:92-95` — add `is_pantry_staple: bool = False` to `CreateIngredientFood`.
- New `AutoSyncRunResult` Pydantic model in `mealie/schema/household/auto_sync.py` (or appended to `household_preferences.py`).

### 8. i18n (en-US only per `.github/copilot-instructions.md`)
`mealie/lang/messages/en-US.json`:
```json
"auto-sync": {
    "no-meal-plan-today": "No meal plan entries for today; auto-sync skipped",
    "no-target-list": "No target shopping list configured and no shopping lists exist in this household",
    "already-synced-today": "This household has already been auto-synced today"
}
```

### 9. Tests (paths follow existing convention, NOT spec wording)
- `tests/unit_tests/services_tests/scheduler/tasks/test_auto_sync.py` — ≥6 unit tests
- `tests/integration_tests/user_household_tests/test_auto_sync_run_now.py` — ≥6 integration tests
- `tests/multitenant_tests/test_auto_sync_isolation.py` — ≥3 multitenant tests

---

## Risk mitigations baked into the selection

| Risk (from history) | Mitigation in selected approach |
|---|---|
| Risk #1 — Cross-household shopping-list mutations buggy | Multitenant test suite is non-optional. Use household-scoped `get_repositories(session, group_id, household_id)` per `repository_factory.py:240-345`. |
| Risk #2 — Per-household timezone absent | Adds `timezone` column to `HouseholdPreferences` with `ZoneInfo` validation; fallback to UTC when None. |
| Risk #3 — `is_pantry_staple` repeats `on_hand` deprecation mistake | Documented as `needs_clarification` (CC2); per-Food per spec literal wording for case-5. |
| Risk #4 — Single-worker `last_ran` module global | Use DB column + CAS UPDATE, never module-global state. |
| Risk #5 — Scheduler bucket additions historically buggy | Reuse `register_minutely`; gate inside the task. Zero scheduler-core surface change. |
| Risk #6 — EventTypes requires migration | Migration #3 explicitly handles the `group_events_notifier_options` column add. |
| Risk #7 — Lifespan-based scheduler start | Tests import the task function directly; never trigger app lifecycle. |
| Risk #8 — No mock-clock infra | Tests drive scenarios by manipulating `last_auto_synced_at` and `auto_sync_run_time` rather than freezing the clock. |
