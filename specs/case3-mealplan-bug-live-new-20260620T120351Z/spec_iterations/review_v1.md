# V1 self-review — 4-axis rubric + A3 fix_bug rule

**Subject**: `spec_iterations/spec_v1.json` + `spec_iterations/spec_v1.md`
**Validators (4)**: A4 schema PASS · A5 citations 0 problems · B3 trace gaps 0 · B1 roundtrip PASS
**Stats**: 15 FRs · 7 SCs · 6 US (all P1) · 3 NCs · 5 entities · 8 edge cases · 7 assumptions · 8 out-of-scope · 3 self-concerns

## A3 fix_bug rule (intent-conditional)

| Requirement | Status | Evidence |
|---|---|---|
| Spec MUST name the buggy function(s) | ✅ PASS | FR-001 explicitly lists `ShoppingListService.can_merge` (lines 45-71) and `ShoppingListService.merge_items` (lines 73-128); FR-006 pins variant A to `merge_items:96` and variant B to `can_merge` predicate at lines 45-71. |
| Spec MUST require a failing-before-fix repro test | ✅ PASS | FR-002 mandates the repro; US-2 AC1 says `FAILS on the bug-injected branch`; SC-002 measures non-zero exit on bug-injected branch + zero exit on post-fix branch. |
| Spec MUST require minimum-scope fix | ✅ PASS | FR-006 + FR-013 + SC-001 + SC-004 enforce 1 modified file, ≤5+5 line delta, no schema / migration / route changes. |
| Spec MUST encode 4 named regression tests | ✅ PASS | FR-008..FR-011 explicitly name `test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`; SC-005 measures all 4 + repro pass. |

## Architecture (estimated: 0 C / 1 H / 0 M)

- **ARCH-NEW-H-001 (HIGH)** — FR-002 acceptance enumerates only `POST /api/households/shopping/lists/{list_id}/recipe` but does NOT require creating the meal-plan entries first via `POST /api/households/mealplans`. Input section `产品场景` mandates the full user flow: schedule recipe on Monday dinner and Wednesday lunch *in the meal plan*, then click `Add Meal Plan to Shopping List`. A test that satisfies the spec without persisting meal-plan entries does NOT mirror the user-visible flow. The 8th edge case + FR-003's reference to `test_create_mealplan_with_recipe` hint at this but the acceptance contract is loose.  
  **Fix in v2**: tighten FR-002 acceptance to require an upstream `POST /api/households/mealplans` call for each occurrence; add the corresponding step to US-1 AC1 and US-2 description.

## Completeness (estimated: 0 C / 0 H / 1 M)

- **COMP-NEW-M-001 (MEDIUM)** — The regression tests at FR-008..FR-011 don't say whether they should create meal-plan entries first or skip directly to bulk-add. The input's `步骤 4` says they "在步骤 1 的测试文件中追加" (append to the same test file), implying the same pattern. The spec leaves this implicit. Most regressions test independent merge-key invariants and don't *need* meal-plan persistence, but explicitly allowing direct bulk-add for those that don't need it (FR-008 / FR-010 / FR-011) would close the ambiguity.  
  **Fix in v2**: add a one-liner to each regression FR clarifying whether meal-plan persistence is required. Keep FR-009 explicit about both wire shapes and meal-plan persistence (since it tests the full flow under both shapes).

All input items are otherwise claimed:
- 步骤 1 (复现) → FR-002 + SC-002
- 步骤 2 (根因) → FR-007 + SC-006
- 步骤 3 (最小修复) → FR-006 + FR-013 + SC-001 + SC-004
- 步骤 4 (四项回归) → FR-008..FR-011 + SC-005
- 实现约束 → FR-013 + FR-014 + SC-001 + SC-004
- 537 pytest baseline → FR-012 + SC-007

## Consistency (estimated: 0 C / 0 H / 1 M)

- **CONS-NEW-M-001 (MEDIUM)** — SC-002's metric invocation is `uv run pytest ...` while SC-007 uses `task py:test`. Both are valid per Mealie's `Taskfile.yml` (which says `task py:test` invokes `uv run pytest`), but the inconsistency makes the spec read as if two different test runners are at play. Per `.github/copilot-instructions.md`, the canonical command is `task py:test` (or `uv run pytest tests/`).  
  **Fix in v2**: align SC-002 to `task py:test -- <node id>` for consistency with SC-007 and Mealie convention.

All other consistency points are tight:
- NC-001 variant A → FR-006 line-96 fix → US-3 AC1 names `merge_items` ✓
- NC-002 `standard_unit=None` → FR-004 + FR-010 ✓
- NC-003 wire shape → FR-002 + FR-009 parametrization + US-1 AC1 ✓
- FR-013 forbids new feature flags → out_of_scope item 6 confirms ✓
- Edge case 1 "internal duplicate OUT OF SCOPE" ↔ out_of_scope item 1 ✓

## Executability (estimated: 0 C / 0 H / 2 M)

- **EXEC-NEW-M-001 (MEDIUM)** — FR-009 parametrizes "the wire shape" but doesn't specify the pytest idiom. The implementer must pick `@pytest.mark.parametrize`, two separate test functions, or a helper that runs both shapes. Acceptable degree of freedom but worth a one-liner to suggest `@pytest.mark.parametrize` for parity with existing Mealie test style.  
  **Fix in v2**: add a non-binding note in FR-009 pointing at `@pytest.mark.parametrize` as the preferred idiom (matches `test_recipe_ingredients.py:177-234`).

- **EXEC-NEW-M-002 (MEDIUM)** — Self-concern #3 acknowledges baseline-drift risk on the 537 count. SC-007 threshold is `collected >= 542`. A future Mealie test addition that bumps the pre-existing count to 538 would make `collected = 543` still ≥ 542, but `collected == 542` would FAIL. The `>=` is the safer side but the wording invites confusion.  
  **Fix in v2**: rephrase SC-007 to `(post-fix collected) == (pre-fix collected) + 5 AND failed == 0 AND error == 0` so the assertion is invariant to upstream drift.

All 50+ code references have been mechanically verified by A5. spec.md ↔ spec.json is identical by construction (B1). FR ↔ SC ↔ US trace matrix has 0 gaps (B3).

## Total: 0 C / 1 H / 4 M = 5 issues

## Decision: REWRITE v2

The 1 HIGH (ARCH-NEW-H-001) is meaningful — the input demands meal-plan persistence as part of the reproduction. v2 closes it plus the 4 mediums.
