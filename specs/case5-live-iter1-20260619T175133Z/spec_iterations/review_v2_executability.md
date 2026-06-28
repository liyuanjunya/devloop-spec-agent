# Executability Review (v2)

## Verdict: NEEDS_REFINE

v2 fixes several v1 issues: markdown/JSON code references match exactly, all cited paths exist, cited symbols appear within the stated ranges, the target-list fallback now cites `ShoppingList.created_at`, i18n spelling is consistent, pantry filtering is explicitly after sub-recipe expansion, and the event payload includes `operation`. However, the spec is still not executable as written because the idempotency/CAS ordering permits duplicate quantity side effects and duplicate events, PATCH marker rejection relies on a false `extra='forbid'` assumption, and event subscription/migration details contain concrete table/model gaps.

---

## Scope checks

| Check | Result |
|---|---|
| All cited paths real? | ✅ Pass. Every `code_references[].path` in `spec_v2.json` exists under `C:\Users\v-liyuanjun\Downloads\mealie\`. |
| All line ranges accurate and cited symbols in range? | ⚠️ Mostly pass. A literal verifier found every cited symbol inside the combined cited ranges, but some ranges do not substantiate the stronger behavioral claims; see wrong/imprecise citations. |
| `spec.md` / `spec.json` `code_references` identical for each FR? | ✅ Pass. Parsed all 27 FRs; ordered path/range/symbol lists match exactly between markdown and JSON. |
| TBD / `or equivalent` / `if needed` phrases? | ✅ Pass. No exact matches in `spec_v2.md` or `spec_v2.json`. |
| ≥3 options pattern in `self_concerns`? | ✅ Pass. Three self-concerns remain, each with a single suggested resolution. |
| Scheduler task implementation seam concrete enough? | ⚠️ Partially. Module/function/registration/window are concrete, but the per-household enumeration query is still implicit. |
| Pantry filter algorithm pin-pointed? | ✅ Pass. v2 pins filter-after-recursive-expansion and explicit `recipe_ingredients=` override. |
| `LastAutoSyncedAt` storage column concrete? | ❌ Not executable. Column is concrete, but CAS timing is unsafe and contradicts idempotency success criteria. |
| Concrete query for today's MealPlan in household tz? | ✅ Pass. `RepositoryMeals.get_today(tz=ZoneInfo(...))` maps to `datetime.now(tz).date()` and household-scoped `GroupMealPlan.date == today`. |

---

## Wrong/imprecise citations

1. **FR-002 / FR-024 / edge case cascade claim** — `mealie/db/models/recipe/ingredient.py` L21-27 is cited as the byte-for-byte model for `household_pantry_staples(... ON DELETE CASCADE ...)`, but the cited table uses `sa.ForeignKey("households.id")` and `sa.ForeignKey("ingredient_foods.id")` with no `ondelete="CASCADE"`. The line range supports the two-column association shape and uniqueness, not the cascade behavior that FR-002 and the deleted-food edge case depend on.
2. **FR-024 event subscription table name** — FR-024 says to alter `group_event_notifier_options`, but the real model table is `group_events_notifier_options` (`mealie/db/models/household/events.py` L15-19), and the existing event-option migration also alters `group_events_notifier_options` (`2026-03-26-20.48.28_cdc93edaf73d...` L21-46). The cited announcement migration L1-47 is only a generic `batch_alter_table` example and does not substantiate the singular table name.
3. **FR-012 / FR-018 duplicate-race safety** — the cited merge code proves the opposite of the prose. `can_merge` allows matching unchecked `(food_id, unit_id)` rows (`shopping_lists.py` L45-71), and `merge_items` sums quantities (`shopping_lists.py` L95-97). Therefore a losing replica that runs side effects before the CAS will double the quantity, not merely avoid duplicate rows.
4. **FR-022 / assumption about locales** — FR-022 cites `en-US.json` L1-50 correctly for existing key structure, but the prose/assumption says Mealie ships only en-US. The directory actually contains many locale JSON files (`af-ZA.json`, `de-DE.json`, `fr-FR.json`, `zh-CN.json`, etc.). The repo convention may still be “modify only en-US,” but the “only locale exists” citation/fact is false.

---

## Executability concerns

### Critical

- **EXEC-C-001 — CAS after side effects is not idempotent.** FR-011 performs `add_recipe_ingredients_to_list` and event dispatch before the FR-012 conditional marker update. FR-012 says a 0-row CAS after commit is acceptable because `bulk_create_items` merges duplicates. But `merge_items` adds quantities (`shopping_lists.py` L95-97), so the second same-day invocation or a losing replica changes the list quantity. This violates US-2, SC-007, and SC-010. Move the conditional claim before side effects, or add a separate in-progress claim/outbox design.
- **EXEC-C-002 — Event dispatch cardinality contradicts itself.** FR-021 requires exactly one dispatch per successful sync and zero dispatch on short-circuit. The edge case for two replicas admits both replicas run FR-011 steps 1-5 and the loser emits a duplicate event before the CAS fails. That contradicts SC-013 and makes subscriber behavior non-deterministic.
- **EXEC-C-003 — PATCH rejection of `last_auto_synced_at` is not guaranteed.** SC-018 says Pydantic raises 422 because `extra='forbid'` is set on `MealieModel`, but `MealieModel.model_config` only sets `alias_generator` and `populate_by_name` (`mealie/schema/_mealie/mealie_model.py` L45-53). Add `model_config = ConfigDict(extra='forbid')` specifically to `HouseholdPreferencesPartialUpdate` or change SC-018 to “silently ignored.”
- **EXEC-C-004 — Event subscription model/schema updates are missing.** FR-021 adds an `EventTypes` enum value and FR-024 adds a migration column, but the spec does not require adding `mealplan_auto_synced_to_shopping` to `GroupEventNotifierOptionsModel` (`events.py` L15-53) or `GroupEventNotifierOptions` (`group_events.py` L13-55). `AppriseEventListener.get_subscribers()` uses `getattr(notifier.options, event.event_type.name)` (`event_bus_listeners.py` L76-83), so the new event can fail at runtime or remain unsubscribable.

### High

- **EXEC-H-001 — Migration omits the target-list foreign key it relies on.** FR-001 requires `auto_sync_target_shopping_list_id` to be an FK to `shopping_lists.id` with `ON DELETE SET NULL`, and Assumption #6 relies on that behavior. FR-024 only says to add a nullable GUID column; it does not require creating the FK constraint or index.
- **EXEC-H-002 — Run-now response shape is internally inconsistent.** The summary, US-3, FR-020, and SC-012 require the exact four-key shape `{added_count, skipped_pantry_count, target_list_id, run_at}`. FR-020 then says precondition failures return HTTP 200 with those fields plus a `detail` field. Define a separate response schema with optional `detail`, or keep the exact four-key contract and put the i18n key in an existing field.
- **EXEC-H-003 — `force=True` semantics are under-specified after CAS rework.** FR-020 says force bypasses both the window gate and conditional-update guard but still writes the marker. Once EXEC-C-001 is fixed by moving CAS before side effects, the manual path needs exact marker-write ordering and duplicate-quantity expectations.

### Medium

- **EXEC-M-001 — Per-household task enumeration is not concrete.** FR-009 says iterate households whose preference flag is true, but no exact repository/SQLAlchemy query is specified for loading all enabled households across groups and building `AllRepositories(session, group_id=..., household_id=...)` per household.
- **EXEC-M-002 — Locale statement should be corrected.** The actionable convention is “add only en-US because other locales are Crowdin-managed,” not “Mealie ships only en-US.” This matters for reviewers who may otherwise delete/ignore existing locale files.

---

## Verified key citations

- `mealie/services/scheduler/scheduler_registry.py` L8-49, `mealie/app.py` L124-144, and `mealie/services/scheduler/scheduler_service.py` L15-17/L77-81 verify the minutely scheduler seam.
- `mealie/repos/repository_meals.py` L11-21 verifies household-timezone “today” selection via `datetime.now(tz).date()`.
- `mealie/services/household_services/shopping_lists.py` L323-455 verifies recursive recipe expansion and the `add_recipe_ingredients_to_list` entrypoint.
- `mealie/services/household_services/shopping_lists.py` L45-128 and L154-220 verify merge behavior; importantly, they also show why post-side-effect CAS is unsafe.
- `mealie/db/models/household/events.py` L15-53, `mealie/schema/household/group_events.py` L13-55, and `mealie/services/event_bus_service/event_bus_listeners.py` L76-83 verify the missing event-subscription model/schema seam.
