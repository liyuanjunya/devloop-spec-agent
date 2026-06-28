# Spec v1 → v2 Rewrite Change Log

Feature: Meal Plan auto-sync to Shopping List (case5-live-iter1-20260619T175133Z)

This rewrite applies the prioritized action list from `meta_review_v1.json`
(META-001 through META-018). Validator status after rewrite:

- A4+F3 schema (pydantic + soft-language + under-escalation): **PASS** (FRs=27, SCs=25, NCs=3)
- A5 citation verifier: **0 problems**
- B3 trace matrix: **0 gaps**
- B1 md↔json roundtrip: **PASS**

## Spec size

|             | v1 | v2 |
|---          |--- |--- |
| Functional requirements | 22 | 27 |
| Success criteria        | 12 | 25 |
| User stories            |  9 |  9 |
| Blocking decisions      |  3 |  3 |
| Key entities            |  ~ |  7 |
| Edge cases              |  ~ |  9 |
| Self-concerns           |  ~ |  3 |
| Iterations bumped       |  1 → 2 |

---

## Issues addressed (META action → FR/SC/NC that resolves it)

### Priority 1 (critical) — all applied

| META | Action | Resolved in |
|---   |---     |---          |
| **META-001** | Replace group-scoped `IngredientFoodModel.is_pantry_staple` with `household_pantry_staples(household_id, food_id)` association table | **FR-002** (new association table), **FR-016** (filter predicate reads from it), **FR-025** (admin route inserts/deletes the row), **FR-027** (multitenant isolation test), **NC-001** (recommended_default updated to mandate the association table; if_rejected preserves the input-literal fallback) |
| **META-002** | CAS ordering must be: resolve preconditions → load mealplan → run transaction → write marker on success only | **FR-011** (explicit step ordering with the marker as step 6 on success only), **FR-012** (conditional UPDATE specification), **SC-007** (idempotency test), **SC-017** (no-op never bumps marker) |
| **META-003** | Field name is `auto_sync_meal_plan_to_shopping` (no `_list` suffix); add `auto_sync_run_time: str`; register on 5-min bucket with internal 30-min window gating; drop `auto_sync_pantry_filter_enabled` | **FR-001** (4 writable columns with correct names — no `_list` suffix; no `auto_sync_pantry_filter_enabled`), **FR-009** (window gating implementation), **FR-016** (pantry filter is unconditional — no flag), **SC-004** (window-gate test) |
| **META-004** | Validate `auto_sync_target_shopping_list_id` ownership at PATCH-time AND sync-time via household-scoped `get_one(target_id)` | **FR-006** (PATCH-time check at step 3 via `self.repos.group_shopping_lists.get_one(...)`), **FR-014** (TWO checkpoints A and B with explicit detail), **SC-016** (cross-household PATCH returns 422) |
| **META-005** | Pantry filtering must be UNCONDITIONAL; pipeline = fetch+recursive expand → per-household predicate → call `add_recipe_ingredients_to_list` with explicit `recipe_ingredients=` | **FR-015** (4-step pipeline with explicit `recipe_ingredients=` arg in step 4), **FR-016** (unconditional, no flag), **SC-009** (sub-recipe aggregation), **SC-014** (pantry filter excludes food F) |
| **META-006** | New `EventTypes.mealplan_auto_synced_to_shopping` + `EventMealPlanAutoSyncedData(EventDocumentDataBase)` carrying `operation, household_id, shopping_list_id, added_item_count, skipped_pantry_count` — no PII | **FR-021** (event type + payload class definition), **SC-013** (single-dispatch test), **SC-025** (no dispatch on empty meal plan), entity definition for `EventMealPlanAutoSyncedData` |
| **META-007** | Exact route `POST /api/households/preferences/auto-sync-shopping/run-now`; `force=True` bypasses CAS but writes marker; exact return shape `{added_count, skipped_pantry_count, target_list_id, run_at}` | **FR-020** (route + force=True semantics + exact return shape), **SC-012** (exact JSON key/type assertion), **SC-023** (force=True bypass succeeds when marker is today), **US-3** acceptance scenario asserts the response shape |

### Priority 2 (high) — all applied

| META | Action | Resolved in |
|---   |---     |---          |
| **META-008** | Remove `last_auto_synced_at` from PATCH/PUT writable schemas; keep in read | **FR-003** (`UpdateHouseholdPreferences` excludes marker), **FR-004** (`HouseholdPreferencesPartialUpdate` excludes marker), **FR-005** (`ReadHouseholdPreferences` includes marker), **FR-007** (PUT preserves exclusion), **NC-003** (recommended_default updated; if_rejected is now the discouraged path), **SC-018** (PATCH with marker is rejected 422) |
| **META-009** | Three exact i18n keys: `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today` (hyphenated, unqualified `auto-sync` namespace) | **FR-022** (exact keys + namespace + en-US-only target), **SC-019** (exact key-set assertion), **US-9** acceptance scenarios |
| **META-010** | `consolidate_ingredients` does not exist — use `bulk_create_items` at L154-220 as canonical seam | **FR-017** (explicit docstring stating `bulk_create_items` is canonical and `consolidate_ingredients` does NOT exist), **SC-010** (merge contract test through `bulk_create_items`), Assumption #8 (canonical-seam assumption) |
| **META-011** | Add unit + integration test matrix | **FR-026** (NFR with explicit unit + integration test list), **FR-027** (multitenant pantry isolation test), **SC-022** (CI pass assertion) |

### Priority 3 (medium) — applied where non-conflicting

| META | Action | Disposition |
|---   |---     |---          |
| **META-012** | Add `HouseholdPreferencesPartialUpdate` all-optional schema for PATCH | **Applied: FR-004**. Schema is defined with every field `Optional[...] = None`, applied via `model_dump(exclude_unset=True)`. |
| **META-013** | FR-019 default-list fallback should cite `created_at` ordering explicitly | **Applied: FR-013** (cites `created_at` from `mealie/db/models/_model_base.py:18-23`) + **NC-002** (recommended_default = ascending `created_at` with explicit rationale). |
| **META-014** | Document that `ShoppingListItemRecipeRefCreate` carries only recipe_id/quantity/scale/note (no meal_plan_entry_id) | **Applied: FR-019** explicitly documents the carried fields and the meta-decision to keep recipe-only refs in v1. Out-of-scope item also added. |
| **META-015** | Document the append/merge contract preservation via `can_merge`/`merge_items` | **Applied: FR-018** documents the `can_merge` short-circuit conditions and how auto-sync preserves the contract; **SC-010** asserts the (food_id, unit_id) merge behavior. |
| **META-016** | Add admin route for per-household pantry-staple toggle | **Applied: FR-025** adds `POST/DELETE /api/households/self/pantry-staples/{food_id}` modeled on `IngredientFoodsController`. **SC-021** asserts non-admin gets 403. |
| **META-017** | Citation fixes: FR-019 → `shopping_list.py:147-181` + `_model_base.py:18-23`; FR-018 → add migration downgrade citation L35-47; FR-015 → cite `EventDocumentDataBase` L88-91 | **Applied across the board.** New citations: FR-014 cites `shopping_list.py:147-181`; FR-013 + FR-012 cite `_model_base.py:18-23`; FR-024 cites both upgrade (L1-32) AND downgrade (L35-47) of the announcement migration template; FR-021 cites `event_types.py:88-91` for `EventDocumentDataBase`. All citations verified against the Mealie source. |

### Priority 4 (low) — applied

| META | Action | Disposition |
|---   |---     |---          |
| **META-018** | Cross-reference the new association table's CASCADE behavior in an edge case | **Applied** as an explicit edge case ("Pantry-staple food F is deleted from the group...") that documents the CASCADE on `household_pantry_staples.food_id`. |

---

## Issues NOT addressed (with rationale)

**None.** Every META action in `meta_review_v1.json` was either fully addressed
in v2 or, in the case of design contradictions, escalated to a
BlockingDecision (`needs_clarification`) so a reviewer/user can flip the
decision before coding starts.

The three blocking decisions (NC-001 pantry-staple scope, NC-002 default-list
ordering, NC-003 PATCH marker semantics) carry a `recommended_default` plus an
`if_rejected` reset path so the rewriter has not consumed any decisions
unilaterally on questions where the input requirements contradict the code.

---

## New issues introduced (honest list)

1. **NEW: Subscription column auto-migration.** FR-024 extends the alembic
   migration to add a `mealplan_auto_synced_to_shopping` column on the event
   subscriber options table. This was not in the v1 spec. If the v1 reviewer
   intended the subscriber table to be updated by hand, this is a divergence.
   Concern #2 in self-concerns surfaces the deployment-order risk (new code +
   old database).

2. **NEW: Self-concern about ZoneInfo lookup cost** at FR-009 (per-tick cost
   for thousands of households). Marked as a concern rather than a
   BlockingDecision because the implementation default (no cache) is correct
   and the cache is a follow-up optimization gated on profiling evidence.

3. **NEW: en-US-only baseline assumption** is now explicit (Assumption #3 +
   Concern #3). The v1 spec did not call out the en-US-only constraint
   explicitly, even though every existing locale path implicitly assumes it.

4. **NEW: PATCH responds with `ReadHouseholdPreferences` rather than the
   diff-only body.** FR-006 spells out `ReadHouseholdPreferences.model_validate(
   current)` as the response, matching the PUT route's existing contract for
   consistency. The v1 PATCH FR was silent on the response shape.

5. **NEW: Acceptance scenario for US-3 asserts the exact 4-key response shape**
   of the run-now endpoint. The v1 user story was vague on the response body.

6. **NEW: Edge case for recipe sub-recipe cycles** with a per-household
   recovery path. The v1 spec did not address cycles; the existing
   `get_shopping_list_items_from_recipe` (L323-355) does not guard either, so
   v2 documents the catch-and-skip behavior.

7. **NEW: NC-003 recommended_default explicitly rejects monotonicity-only
   alternatives** in the `if_rejected` text, so a reviewer who selects the
   client-writable marker path is also signing up for the monotonicity-rule
   amendment to FR-011 / FR-012. The v1 NC was silent on the downstream
   implications.

---

## Verification trail

All `code_references[].line_ranges` re-verified against
`C:\Users\v-liyuanjun\Downloads\mealie\` by reading every cited file:
- `mealie/db/models/recipe/ingredient.py` (L21-27, L153-192)
- `mealie/db/models/household/preferences.py` (L16-44)
- `mealie/db/models/household/household.py` (L29-97)
- `mealie/db/models/household/shopping_list.py` (L147-181)
- `mealie/db/models/_model_base.py` (L18-23)
- `mealie/db/models/_model_utils/datetime.py` (L1-50)
- `mealie/schema/household/household_preferences.py` (L10-22, L32-40)
- `mealie/services/household_services/shopping_lists.py` (L45-71, L73-128, L154-220, L323-411, L413-455)
- `mealie/services/event_bus_service/event_types.py` (L13-60, L80-91, L130-132)
- `mealie/services/event_bus_service/event_bus_service.py` (L60-96)
- `mealie/services/scheduler/scheduler_registry.py` (L8-49)
- `mealie/services/scheduler/scheduler_service.py` (L15-17, L77-81)
- `mealie/repos/repository_factory.py` (L244-253, L297-301, L317-321)
- `mealie/repos/repository_meals.py` (L11-21)
- `mealie/routes/households/controller_household_self_service.py` (L20-62, L58-62)
- `mealie/routes/_base/checks.py` (L23-26)
- `mealie/routes/unit_and_foods/foods.py` (L24-78)
- `mealie/alembic/versions/2026-03-27-20.19.07_4395a04f7784_add_announcements.py` (L1-32, L35-47)
- `mealie/lang/messages/en-US.json` (L1-50)

Final validator output:
```
A4+F3 schema: PASS (FRs=27, SCs=25, NCs=3)
A5 citation: 0 problems
B3 trace: 0 gaps
B1 roundtrip: PASS
```
