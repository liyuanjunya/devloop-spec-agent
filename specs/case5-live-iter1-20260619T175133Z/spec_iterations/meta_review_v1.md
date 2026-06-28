# Meta-Review v1 — Case-5 LIVE RUN

**Judge:** claude-opus-4.7
**Inputs:** `review_v1_{architecture,completeness,executability,consistency}.md`, `spec.md`, `spec.json`, `input.md`

## Verdict

v1 spec **FAILS** across all four axes with strong reviewer convergence. **7 critical actions (P1)**, **4 high (P2)**, **6 medium (P3)**, **1 low (P4)** — 18 total deduped actions from 22 raw findings across the four reviews. The architecture reviewer's 3 critical + 2 high are correctly placed at P1, and completeness/consistency surface 4 additional critical actions that the architecture reviewer did not flag at that severity (event payload, pantry-filter seam, manual-trigger route shape, and run-time field).

## Recommended fix order

1. **META-001** (per-household pantry model) — unblocks META-005, META-011, META-016
2. **META-002** (CAS / marker ordering) — unblocks META-007 force-mode semantics
3. **META-003** (`auto_sync_run_time` + 30-min cadence + window gating)
4. **META-004** (target list household-ownership validation)
5. **META-005** (pantry filter unconditional + concrete seam)
6. **META-006** (`MealPlanAutoSyncedToShopping` event + safe payload)
7. **META-007** (manual-trigger route + response + force-mode)
8. then P2/P3 in numerical order.

## Actions

| ID | Pri | Sev | Axes | Sources | Action |
|---|---|---|---|---|---|
| META-001 | 1 | critical | arch, comp, cons | ARCH-C-3, COMP-C8, CON-C-008 | Resolve NC-001: model pantry-staple per-household via a `household_pantry_staples` association table (parallel to `households_to_ingredient_foods`); update schemas/routes; test two same-group households with divergent staple state. |
| META-002 | 1 | critical | arch, exec, cons | ARCH-C-1, EXEC-C-001, CON-C-001, CON-C-002 | Specify exact CAS ordering: resolve target+meal first → no-op skips do NOT touch marker → wrap item-create + recipe-ref + event-dispatch in one transaction → set `last_auto_synced_at` only on success. Add mid-sync failure-injection test. |
| META-003 | 1 | critical | arch, comp, exec, cons | ARCH-H-2, COMP-C1, COMP-C2, EXEC-C-002, CON-C-001 | Add `auto_sync_run_time: str` (HH:MM, default `"00:00"`); register on 30-minute cadence; gate execution to `[scheduled_local_instant, +30min)`; unify idempotency predicate to that scheduled day; restore input field naming; drop `auto_sync_pantry_filter_enabled`. |
| META-004 | 1 | critical | arch, cons | ARCH-C-2, CON-C-006 | Validate `auto_sync_target_shopping_list_id` ownership at two seams: PATCH-time rejection + sync-time `get_one(target_id)` via household-scoped repo. Add cross-household-id multitenant test asserting zero rows change in the other list. |
| META-005 | 1 | critical | comp, exec, cons | COMP-C3, EXEC-H-001, EXEC-H-002, CON-C-004 | Make pantry filtering unconditional; pin pipeline as: fetch + recursively expand sub-recipes → apply per-household pantry predicate (META-001) → call `add_recipe_ingredients_to_list` with explicit filtered `recipe_ingredients=`, NOT `None`. Cite `shopping_lists.py:323-340` and `:343-350`. Add sub-recipe staple SC + test. |
| META-006 | 1 | critical | arch, comp, exec | ARCH-H-1, COMP-C6, EXEC-H-003 | Add `EventTypes.mealplan_auto_synced_to_shopping` + `EventMealPlanAutoSyncedData(EventDocumentDataBase)` with `operation`, `household_id`, `shopping_list_id`, `added_item_count`, `skipped_pantry_count` — no recipe/user-PII fields. Update subscriber registration migration. |
| META-007 | 1 | critical | comp, cons | COMP-C5, CON-C-003 | Use exact `POST /api/households/preferences/auto-sync-shopping/run-now`; household-admin permission; `force=True` param that bypasses daily CAS but still writes marker on success; return `{added_count, skipped_pantry_count, target_list_id, run_at}`; add SC + integration tests. |
| META-008 | 2 | high | cons, arch | CON-C-005 | Remove `last_auto_synced_at` from client-writable PATCH/PUT schemas (keep in read schema). Add SC asserting PATCH attempts to set it are ignored/rejected. |
| META-009 | 2 | high | comp, exec, cons | COMP-C7, EXEC-M-002, CON-C-007 | Adopt exact input keys `auto-sync.no-meal-plan-today` / `auto-sync.no-target-list` / `auto-sync.already-synced-today`. Pick one naming convention everywhere (recommend the unqualified hyphenated namespace). Update summary, US-9, FR-016, SC-011, edge cases. |
| META-010 | 2 | high | comp | COMP-C4 | Locate, cite by full `path:lines`, and require reuse of `consolidate_ingredients` (or document the verified canonical equivalent seam) in FR-011/FR-012. Add SC asserting `(food_id, unit_id)` consolidation parity. |
| META-011 | 2 | high | comp | COMP-C9 | Add SC+test for each missing bullet: disabled-scheduled-skip, no-meal-plan 204/0-added, cross-group isolation, per-household pantry-staple isolation (depends on META-001), scheduler-mock 30-min cadence assertion, manual-trigger response exact counts. |
| META-012 | 3 | medium | arch | ARCH-M-1 | Define `HouseholdPreferencesPartialUpdate` with all-optional fields (excluding `last_auto_synced_at`); apply via `model_dump(exclude_unset=True)` merged into loaded row, bypassing `repository_generic.update()`'s full-overwrite path. |
| META-013 | 3 | medium | exec | EXEC-M-001 | Cite exact repo seam for FR-019 fallback: `repos.group_shopping_lists.query(order_by=ShoppingList.created_at).first()` (or equivalent) plus correct model cites (`shopping_list.py:147-181`, `_model_base.py:18-23`). |
| META-014 | 3 | medium | comp | COMP-M1 | Verify whether `ShoppingListItem.recipe_references` can carry a meal-plan-entry id; either accept recipe-only refs with documented rationale or add an extras/column strategy for `meal_plan_entry_id`. Add SC/test. |
| META-015 | 3 | medium | comp | COMP-M2 | Add explicit FR + test: for each filtered ingredient, accumulate quantity into existing unchecked `(food_id, unit_id)` rows and merge recipe_references; create new item otherwise. |
| META-016 | 3 | medium | comp | COMP-M3 | Specify admin route + permission + repo surface for pantry-staple toggle. **Note:** after META-001 this writes to the household-pantry-staple association table, not to a `Food` column. Flagged as conflicting-with META-001 in JSON. |
| META-017 | 3 | medium | exec | EXEC wrong/imprecise | Fix citations: FR-019 → `shopping_list.py:147-181` (ShoppingList) + `_model_base.py:18-23` (created_at); FR-018 → add downgrade range L35-45 of the announcements migration example; FR-015 → add `event_types.py:88-91` (EventDocumentDataBase.operation). Sync spec.md and spec.json. |
| META-018 | 4 | medium | cons | CON-C-009 | Either reciprocate FR-020 links from SC-001/002/003/008.`related_requirements` or drop FR-020's outbound SC links and recast as a test-coverage NFR. Optionally surface FR↔SC links in spec.md for field parity. |

## Cross-axis conflicts

| # | Type | Where | Resolution |
|---|---|---|---|
| 1 | Latent | ARCH-H-1 wants a new event type vs EXEC-H-003 wants `operation` field on existing `EventShoppingListData` | **Merged in META-006:** add the new `MealPlanAutoSyncedToShopping` event type AND include the `operation` field on the new payload (inherited from `EventDocumentDataBase`). Input's explicit naming requirement wins. |
| 2 | Latent | ARCH-C-1 (mark-after-success) vs spec FR-010 (CAS-before-work) | **Merged in META-002:** use CON-C-002's compromise — resolve preconditions first, then CAS immediately before the append+event transaction, then write marker on success only. |
| 3 | Latent | COMP-C3 (drop pantry-filter gate flag) + ARCH-C-3 (per-household pantry model) | **Compatible — both required:** META-005 drops the gate AND META-001 moves the boolean to a per-household association used by the unconditional filter. |
| 4 | Internal cross-action | META-016 (admin route for `Food.is_pantry_staple`) conflicts with META-001 (no group-scoped column) | **Sequencing:** implement META-001 first; META-016 admin endpoint should write to the new household association table, not a Food column. Flagged in JSON `conflicts_with`. |
| 5 | Reviewer-vs-reviewer substantive | — | **None found.** All four axes converge on the same core defects; disagreements are about which layer to fix, not whether to fix. |

## Severity rollup vs reviewer claims

| Reviewer | Reviewer-claimed counts | Folded into meta priority |
|---|---|---|
| Architecture | 3 critical + 2 high + 1 medium | All 3 critical → P1 (META-001, -002, -004). Both high → P1 (META-003 absorbs ARCH-H-2; META-006 absorbs ARCH-H-1). Medium → P3 (META-012). |
| Completeness | 9 critical + 3 major | 4 critical mapped to P1 already in arch's set; 3 unique critical promoted to P1 (META-005, -006, -007 — confirmed via 2+ axis convergence); 2 critical de-prioritized to P2 (META-009 i18n, META-010 consolidate_ingredients, META-011 tests) as they are high-blocking but not behavior-corrupting; 3 majors → P3 (META-014/-015/-016). |
| Executability | 2 critical + 3 high + 2 medium | Both critical fold into META-002 + META-003. EXEC-H-001/-002 fold into META-005; EXEC-H-003 folds into META-006. EXEC-M-001 → META-013; EXEC-M-002 → META-009. Wrong-citation block → META-017. |
| Consistency | 5 blocking + 1 high + 2 medium + 1 low | C-001/C-002 → META-002; C-003 → META-007; C-004 → META-005; C-005 → META-008 (only un-shared finding worth its own P2 action); C-006 → META-004; C-007 → META-009; C-008 → META-001; C-009 → META-018. |

## Summary

The four reviews converge tightly on **7 critical defects** that block implementation: per-household pantry-staple modeling, CAS/marker ordering, missing `auto_sync_run_time` + 30-min cadence, target-list household-ownership validation, pantry-filter implementation seam, dedicated `MealPlanAutoSyncedToShopping` event + safe payload, and the exact manual-trigger route + response shape with idempotency-bypass. Fixing META-001 through META-007 is required before any coding can begin. P2 actions (server-owned marker, exact i18n keys, `consolidate_ingredients` reuse, test matrix completion) are high-blocking and should be addressed in the same revision pass. P3/P4 actions are polish/traceability and can be addressed alongside.
