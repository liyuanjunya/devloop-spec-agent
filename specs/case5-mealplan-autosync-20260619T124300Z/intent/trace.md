# Intent Trace — Case 5 (Meal Plan Auto-Sync to Shopping List)

Run: 2026-06-19T12:43 (single round, no refinement needed)

## Inputs
- `input.md` — Mealie 餐计划→购物清单自动联动. Sections: 业务背景, 功能需求 §1 Household 配置, §2 定时任务, §3 手动触发, §4 跨域配套, §5 测试要求, 实现约束.
- `context/grounding.md` — Mealie repo grounding (commit 4a099c1).
- `.github/copilot-instructions.md` — repo development conventions (Repository/Service/Controller, schema codegen, en-US-only locale).
- Source tree at `C:\Users\v-liyuanjun\Downloads\mealie\`.

## Pipeline

### Step 1 — Read input
Chinese-language Mealie feature spec for "自动联动". 5 numbered sub-requirements (config, scheduler, manual trigger, cross-domain, tests) plus an explicit implementation-constraint section that enumerates multi-replica safety and per-household timezone correctness. Estimated scope in input header: "~12-18 个文件" — confirms feature scale.

The spec is cross-domain: it spans HouseholdPreferences (config), scheduler (orchestration), ShoppingListService (consolidation reuse), Food/IngredientFood (pantry-staple filter), EventTypes (new event), routes (PATCH preferences + run-now), and i18n.

### Step 2 — Generate candidate hypotheses (3+1)
- **H1 add_feature** — end-to-end opt-in auto-sync with per-household config, TZ-aware scheduler, pantry filter, event dispatch, manual run-now, multi-replica safe. Initial prior ≈ 0.85.
- **H2 scheduled_task_only** — just a new task under scheduler/tasks/; everything else is glue. Initial prior ≈ 0.08.
- **H3 automation_of_existing_addRecipe** — equivalent to programmatically invoking POST /shopping/lists/{id}/recipe on a schedule. Initial prior ≈ 0.05.
- **H4 global_admin_setting** — long-shot strawman: single server-wide toggle, no per-household config. Initial prior ≈ 0.02 (added to surface and reject the global-vs-tenant question).

### Step 3 — Verification by source inspection
Verified each hypothesis by opening real files cited in the spec/grounding.

| File | Lines verified | Why it matters |
|------|---------------|----------------|
| `mealie/db/models/household/preferences.py` | 1–44 (full) | HouseholdPreferencesModel has 10 columns today; none of auto_sync_*, auto_sync_target_shopping_list_id, auto_sync_run_time, LastAutoSyncedAt, timezone exist → confirms 3+ NEW columns. |
| `mealie/db/models/household/household.py` | 1–98 (full) | Household model has no timezone field; preferences relationship is intact and ready to carry new fields. |
| `mealie/db/models/group/preferences.py` | 1–37 (full) | GroupPreferences has no timezone either. There is genuinely NO existing timezone column anywhere — case-5 must add one (or fall back to server TZ per spec). |
| `mealie/db/models/household/mealplan.py` | 1–78 (full) | GroupMealPlan has date, entry_type, title, text, group_id, user_id, recipe_id, recipe relationship. household_id is `association_proxy('user','household_id')` (line 65) — same pattern as ShoppingList. |
| `mealie/db/models/household/shopping_list.py` | 1–239 (full) | ShoppingListItem.food_id @ 78, unit_id @ 75, checked @ 65, recipe_references @ 87-89. ShoppingListItemRecipeReference.recipe_id @ 37, recipe_quantity @ 39, recipe_scale @ 40 → confirms (food_id, unit_id) merge key and recipe_references linkage. |
| `mealie/db/models/recipe/ingredient.py` | 1–250 + 340–500 (line ranges) | IngredientFoodModel @ 153-192 has no `is_pantry_staple` — only a Deprecated `on_hand` boolean at line 192. RecipeIngredientModel @ 344-370 has recipe_id/food_id/unit_id/quantity/note/referenced_recipe → confirms ingredient shape. |
| `mealie/alembic/versions/2024-06-22-10.17.03_32d69327997b_add_staple_flag_to_foods.py` | 1–46 (full) | Filename says "staple_flag" but body adds `on_hand`. Misnomer/legacy. Confirms `is_pantry_staple` is genuinely new. Also a reusable migration template for the new column. |
| `mealie/services/scheduler/scheduler_registry.py` | 1–59 (full) | Only register_daily/hourly/minutely buckets exist. No 30-min bucket — auto-sync must reuse minutely + self-gate. |
| `mealie/services/scheduler/scheduler_service.py` | 1–82 (full) | MINUTES_5=5, MINUTES_HOUR=60, MINUTES_DAY=1440 — confirms "minutely" is actually 5-minutely. asyncio.create_task wiring is in-process / single-worker. |
| `mealie/services/scheduler/scheduled_func.py` | 1–18 (full) | ScheduledFunc dataclass shape — informs any new task registration. |
| `mealie/services/scheduler/tasks/create_timeline_events.py` | 1–134 (full) | Direct prior-art for a per-household scheduled task: groups → households → repos.meals.get_today(tz=...) → event_bus_service.dispatch. Auto-sync follows the same shape but writes to shopping_lists. |
| `mealie/services/scheduler/tasks/post_webhooks.py` | 1–101 (full) | Confirms event_bus_service.dispatch usage and EventDocumentData / EventTypes wiring inside scheduler tasks. |
| `mealie/services/scheduler/tasks/__init__.py` | 1–28 (full) | Confirms `from .auto_sync_shopping import auto_sync_shopping_for_all_households` + add to `__all__` is the registration mechanism. |
| `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py` | 1–76 (full) | Direct prior-art for a shopping-list scheduler task using ShoppingListService: per group → per household → per shopping_list, dispatching events via _create_publish_event closure. Auto-sync should mirror this layering. |
| `mealie/services/scheduler/tasks/purge_password_reset.py` | 1–25 (full) | Minimal scheduled-task template using session_context. |
| `mealie/services/household_services/shopping_lists.py` | 1–470 (line ranges) | Confirms can_merge @ 45-71, merge_items @ 73-128, bulk_create_items @ 154-223, get_shopping_list_items_from_recipe @ 323-411, add_recipe_ingredients_to_list @ 413-455. No literal `consolidate_ingredients` function — the spec wording is loose. add_recipe_ingredients_to_list is the highest-level reuse seam. |
| `mealie/services/household_services/household_service.py` | 1–100 (full) | HouseholdService(BaseService) is the right home for any service-level helper that needs both group_id and household_id; could host a sync_meal_plan_to_shopping_list method. |
| `mealie/services/event_bus_service/event_types.py` | 1–208 (full) | EventTypes enum @ 13-60 has 22 members; no MealPlanAutoSyncedToShopping. Docstring @ 17-22 mandates DB migration on subscriber columns when adding new event types. EventDocumentDataBase pattern @ 88-176 → confirms new EventMealPlanAutoSyncedData class shape. |
| `mealie/services/event_bus_service/event_bus_service.py` | 1–106 (full) | dispatch(integration_id, group_id, household_id, event_type, document_data, message="") signature. Loops per-household — tenant isolation is structurally enforced. |
| `mealie/repos/repository_meals.py` | 1–34 (full) | get_today(tz=UTC) filters on date == today AND household_id == self.household_id. The auto-sync task feeds the household's configured TZ here. |
| `mealie/routes/households/controller_household_self_service.py` | 1–92 (full) | Existing routes: GET /preferences @ 54, PUT /preferences @ 58 (NOT PATCH — spec wording drift). update_household_preferences gated by self.checks.can_manage_household(). New POST /preferences/auto-sync-shopping/run-now goes in this controller. |
| `mealie/routes/_base/checks.py` | 1–40 (partial) | can_manage_household @ 23-25 — the auth check already exists; new run-now route reuses it. |
| `mealie/routes/_base/base_controllers.py` | 1–214 (full) | BaseUserController @ 132-172 + BaseAdminController @ 175-189 + BaseCrudController @ 192-214 hierarchy. The household-admin run-now route uses BaseUserController + can_manage_household; the global pantry-staple admin route can use BaseAdminController. |
| `mealie/routes/unit_and_foods/foods.py` | 1–79 (full) | Existing PUT /foods/{item_id} @ 69-73 uses self.checks.can_organize() (not admin). To gate is_pantry_staple to true admins, either extend CreateIngredientFood with the new field + use existing PUT, OR add a new admin-only route. Spec §4 wording 'admin/foods routes' suggests the latter pattern, mirroring mealie/routes/admin/admin_management_households.py. |
| `mealie/routes/admin/admin_management_households.py` | 1–92 (full) | Admin-controller template: APIRouter(prefix='/households') + @controller(router) + BaseAdminController. Reusable verbatim for a /admin/foods/{id}/pantry-staple endpoint. |
| `mealie/routes/households/controller_shopping_lists.py` | 1–284 (line ranges) | add_recipe_ingredients_to_list @ 256-261 is the highest-level reuse seam in the controller layer; uses ShoppingListService.add_recipe_ingredients_to_list internally. publish_list_item_events helper @ 41 is reusable for fan-out events. |
| `mealie/routes/households/controller_mealplan.py` | 1–135 (line ranges) | GET /mealplans/today @ 124-127 uses dateutil.tz.tzlocal() — same server-TZ pattern as create_timeline_events. Confirms the existing "today" semantics is server-TZ, and the auto-sync task must explicitly switch to household-configured TZ. |
| `mealie/schema/household/household_preferences.py` | 1–40 (full) | UpdateHouseholdPreferences hierarchy. Adding three new fields cascades automatically to Create/Save/Read. |
| `mealie/schema/recipe/recipe_ingredient.py` | 60–140 (partial) | UnitFoodBase / CreateIngredientFood / SaveIngredientFood / IngredientFood. None expose `on_hand` or `is_pantry_staple` today. |
| `mealie/lang/messages/en-US.json` | 1–50 (partial) | JSON not YAML (grounding §5 is wrong). No 'auto-sync' namespace. New keys land here, en-US only. |
| `mealie/app.py` | 1–184 (full) | lifespan_fn → start_scheduler → register_daily/minutely/hourly + SchedulerService.start. workers=1 @ 177 confirms single-worker default; multi-replica safety per spec §实现约束 must be implemented in the task itself. |
| `tests/unit_tests/services_tests/scheduler/tasks/` (listed via Get-ChildItem) | n/a | Spec's path `tests/unit_tests/services/scheduler/` is a drift; actual is `tests/unit_tests/services_tests/scheduler/tasks/`. |

### Step 4 — Skeptic pass
Seven challenges raised, all resolved by re-reading the source (see `confirmed.json:skeptic_challenges`). The most consequential were:

1. **No timezone column anywhere** — spec §实现约束 forces a NEW field. Surfaced under scope:[data_model].
2. **`is_pantry_staple` does not exist** despite a misleadingly named 2024 migration that actually adds `on_hand`. Surfaced as a NEW column under scope:[data_model, schema].
3. **No literal `consolidate_ingredients` function** — the spec/grounding wording is loose. The de-facto consolidation lives inline in `ShoppingListService.bulk_create_items + merge_items + can_merge`. Auto-sync should reuse `add_recipe_ingredients_to_list` (highest seam) or `bulk_create_items` (mid seam). Couples to case-3's downstream refactor — flagged as a non-blocker.
4. **No 30-minute scheduler bucket** — must register on `minutely` (which is actually 5-minutely) and self-gate to the household's run-time window.
5. **New EventType requires a DB migration on subscriber columns** per the enum's own docstring — hidden cost not in the spec text. Surfaced under scope:[migration, event_bus].
6. **PUT vs PATCH preferences naming** — spec says PATCH; existing route is PUT. Treated as naming drift, not a behavior gap.
7. **Multi-replica safety required even though Mealie ships single-worker** — spec §实现约束 mandates it. LastAutoSyncedAt CAS update is the cheapest viable mechanism.

### Step 5 — Verdict
- **H1 = primary** (add_feature). Posterior confidence 0.93.
  - 5 spec sub-requirements map cleanly to 5 sub-slices of an add_feature flow (config, scheduler, manual trigger, cross-domain, tests).
  - Counter-indicators of H1 (loose case-3 coupling, missing TZ field) are addressed by widening scope to include data_model + migration + per-household-TZ groundwork.
- **H2, H3 = secondary** (each captures one slice but neither subsumes the whole).
- **H4 = rejected** (the spec is explicit about per-household opt-in, target list, and TZ; cross-household isolation tests in §5 are incompatible with a global toggle).

### Step 6 — Output
- `intent/confirmed.json` written with schema_version 1.0.
- `intent/trace.md` (this file) written.

## Open questions deferred to spec / coding / CR phase

1. **`auto_sync_target_shopping_list_id = null` → "first active main list"** — spec says "household 的第一个 active 主 list", but ShoppingList has no `is_main` or `active` flag in the model. Likely interpretation: order by `created_at ASC` and pick the first non-archived one (case-2's archive feature, if landed, gates this). Flagged for coding/CR.
2. **`LastAutoSyncedAt` storage location** — extend HouseholdPreferences with one more column, or introduce a sidecar table (cleaner isolation but more work)? Spec is silent; prefer extending HouseholdPreferences for symmetry with the other auto_sync_* fields.
3. **Per-household timezone** — add `timezone: str | None` to HouseholdPreferences (default null → fall back to group/server TZ), or to Household? HouseholdPreferences is consistent with the other auto_sync_* fields' location.
4. **Run-time window precision** — "30 分钟窗口" means [run_time, run_time + 30min)? Or [run_time − 15min, run_time + 15min)? The former is simpler and matches the 30-minute scheduler tick; assume former unless spec is clarified.
5. **DST transitions** — if the household's run_time falls in the "skipped" hour during spring-forward, should the task fire on the next valid 30-min slot or skip the day? Spec is silent. Defer to CR.
6. **Pantry-staple visibility** — is `is_pantry_staple` a per-group or global flag? `IngredientFood` is per-group (group_id FK at line 158). Per-group is the correct scope; confirms multitenant tests in §5 ("跨 household 的 food pantry-staple 标记不互相影响") are about within-group household isolation, not group-to-group, since foods are group-scoped to begin with.
7. **Manual trigger response shape** — spec says `{ added_count, skipped_pantry_count, target_list_id, run_at }`. Define a new Pydantic schema `AutoSyncRunResult` at mealie/schema/household/household_preferences.py.
8. **Idempotency vs manual trigger** — spec says manual trigger bypasses LastAutoSyncedAt but still updates it. Confirms a single CAS UPDATE statement for both code paths.
9. **Event type naming** — spec says `MealPlanAutoSyncedToShopping`. The existing EventTypes are snake_case (e.g. `shopping_list_updated`), so the actual enum member should be `meal_plan_auto_synced_to_shopping`. Document data class: `EventMealPlanAutoSyncedData(EventDocumentDataBase)` to match the existing `EventMealplanData` / `EventShoppingListData` naming.
10. **Scheduler bucket choice** — register on minutely (5-min) with internal time-window check, OR add a new 30-min bucket to SchedulerRegistry/SchedulerService? Reusing minutely is less invasive and explicitly satisfies spec §实现约束 ("必须复用既有 scheduler 抽象, 不要新建并行 scheduler"). Adding a 30-min bucket is also valid but touches scheduler core. Prefer minutely + gating.
