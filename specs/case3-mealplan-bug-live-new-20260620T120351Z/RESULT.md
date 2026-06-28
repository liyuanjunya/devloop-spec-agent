# Case-3 RESULT — Mealie meal-plan-to-shopping bug fix, NEW DevLoop pipeline (v7 with 19 defenses)

**Workspace**: `specs/case3-mealplan-bug-live-new-20260620T120351Z/`
**intent_type**: `fix_bug` (A3 conditional rules apply)
**Iterations executed**: 2 (v1 + v2)
**Final spec**: `spec.json` + `spec.md` (mirrors `spec_iterations/spec_v2.{json,md}`)

## TL;DR

| Iteration | A4 schema | A5 citations | B3 trace | B1 roundtrip | Self-review (C/H/M) | Decision |
|---|---|---|---|---|---|---|
| **v1** | PASS (15 FRs, 7 SCs, 6 US, 3 NCs) | PASS (0 problems, after fixing 2 `merge_items` symbol/range mismatches) | PASS (0 gaps) | PASS | 0 / 1 / 4 = 5 issues | REWRITE v2 |
| **v2** | PASS (15 FRs, 7 SCs, 6 US, 3 NCs) | PASS (0 problems) | PASS (0 gaps) | PASS | 0 / 0 / 0 | ACCEPT |

All 4 deterministic validators pass on both iterations. v2 closes the 1 HIGH + 4 MEDIUM findings surfaced in v1's 4-axis self-review.

## A3 fix_bug rule compliance

A3 = the intent-conditional reviewer rule: when `intent_type=fix_bug`, the spec MUST (a) name the buggy function(s), (b) require a failing-before-fix reproduction test, (c) require minimum-scope fix wording, (d) require 4 named regression tests. The new pipeline's A3 rule fires automatically because `intent/confirmed.json` declares `intent_type=fix_bug`.

| A3 sub-rule | Evidence in v2 spec | Status |
|---|---|---|
| Name buggy function(s) | FR-001 names `ShoppingListService.can_merge` (`mealie/services/household_services/shopping_lists.py:45-71`) and `ShoppingListService.merge_items` (`:73-128`); FR-006 pins variant A to `merge_items` line 96; US-3 AC1 names `merge_items` (variant A) or `can_merge` (variant B). | ✅ |
| Require failing-before-fix repro test | FR-002 + US-2 AC1 (`the test FAILS … on the bug-injected branch`) + SC-002 metric (`non-zero exit on bug-injected branch AND zero exit on post-fix branch`). | ✅ |
| Require minimum-scope fix | FR-006 + FR-013 + SC-001 (`exactly 1 file modified`) + SC-004 (`added <= 5 AND removed <= 5`). | ✅ |
| Require 4 named regression tests | FR-008..FR-011 individually name `test_single_occurrence`, `test_multiple_occurrences_same_unit`, `test_multiple_occurrences_different_units`, `test_different_food_same_name`; SC-005 measures `exactly 5 passing tests with the required names (1 repro + 4 regressions)`. | ✅ |

The spec never says "code doesn't exist" or any equivalent — the entire FR/SC structure presumes existing buggy code in `shopping_lists.py` and prescribes a tactical fix.

## v1 → v2 closure ledger

| ID | Axis | Severity | v1 finding | v2 closure |
|---|---|---|---|---|
| ARCH-NEW-H-001 | Architecture | **HIGH** | FR-002 acceptance enumerated only the bulk-add POST; meal-plan persistence was implicit, allowing a spec-compliant test that bypasses the user-visible flow. | **CLOSED**. FR-002 step (2) now mandates `POST /api/households/mealplans` for each occurrence with explicit reference to `test_create_mealplan_with_recipe:80-99`. US-1 AC1 `when` now first persists meal-plan entries before the bulk-add. US-2 description rewritten to call out the meal-plan step. |
| COMP-NEW-M-001 | Completeness | MEDIUM | Regression tests at FR-008/FR-010/FR-011 didn't say whether to persist meal-plan entries or use bulk-add directly. | **CLOSED**. Each of FR-008/FR-010/FR-011 now says "The test MAY skip the `POST /api/households/mealplans` step because this regression validates [an independent invariant] on the bulk-add path itself". FR-009 explicitly keeps meal-plan persistence under both wire shapes. |
| CONS-NEW-M-001 | Consistency | MEDIUM | SC-002 metric used `uv run pytest`; SC-007 used `task py:test`. | **CLOSED**. SC-002 metric now uses `task py:test -- …`, matching SC-007 and Mealie's `.github/copilot-instructions.md`. |
| EXEC-NEW-M-001 | Executability | MEDIUM | FR-009 wire-shape parametrization left the pytest idiom unspecified. | **CLOSED**. FR-009 now reads "preferred idiom: `@pytest.mark.parametrize` decorator with two cases, matching the convention in `tests/integration_tests/user_recipe_tests/test_recipe_ingredients.py:177-234`". |
| EXEC-NEW-M-002 | Executability | MEDIUM | SC-007 threshold `collected >= 542` was vulnerable to upstream baseline drift. | **CLOSED**. SC-007 now defines `BASELINE_COLLECTED` (collected count from `task py:test` on the bug-injected branch immediately prior) and threshold is `post-fix collected == BASELINE_COLLECTED + 5 AND failed == 0 AND error == 0`. |

## v1 4-axis findings table (5 issues, what each defense caught vs missed)

| Axis | Defense that caught / missed it | Notes |
|---|---|---|
| Architecture (ARCH-NEW-H-001) | **Missed by all 4 deterministic validators.** A4/A5/B3/B1 pass without inspecting flow fidelity. Caught by self-review reading the input scenario and comparing it to FR-002's `when` clause. | Confirms self-review remains essential even when all deterministic checks are green. |
| Completeness (COMP-NEW-M-001) | Missed by validators. Caught by self-review. | Ambiguity vs. omission — the regression FRs were under-specified, not missing. |
| Consistency (CONS-NEW-M-001) | Missed by A4 (`task py:test` and `uv run pytest` are both valid free-form text per the soft-language rule). Caught by self-review cross-reading SC-002 vs SC-007. | A4 doesn't enforce inter-SC metric coherence. |
| Executability (EXEC-NEW-M-001) | Missed by A5/B3 (line ranges and references are valid). Caught by self-review thinking about the implementer's day-1 task. | A degree of freedom that needs to be pinned. |
| Executability (EXEC-NEW-M-002) | Missed by A4/A5/B3/B1 (the threshold parses cleanly). Caught by self-review applying self-concern #3 (baseline drift). | The deterministic validators can't enforce robustness to external state changes. |

## Final stats (v2)

- **15 functional requirements** (FR-001..FR-015), 14 type=`functional`, 1 type=`non_functional` (FR-013), 1 type=`non_functional` (FR-014).
- **7 success criteria** (SC-001..SC-007), 6 measurable / 1 narrative (SC-006), all bound to ≥1 FR.
- **6 user stories** (US-1..US-6), all P1, 3 acceptance criteria per story average.
- **3 blocking decisions** (NC-001 bug-injection variant; NC-002 PR #7121 unit-conversion vs different-unit; NC-003 wire shape).
- **5 key entities** (`ShoppingListItem`, `ShoppingListItemRecipeReference`, `IngredientFood`, `IngredientUnit`, `MealPlan`).
- **8 edge cases**, **7 assumptions**, **8 out-of-scope items**, **3 self-concerns**.
- All **50+ code references** mechanically verified against `C:\Users\v-liyuanjun\Downloads\mealie\` by A5.
- **0 trace gaps** per B3 (every FR linked to ≥1 SC, every SC linked to ≥1 FR, every P1 story claimed by some FR).
- **md ↔ json identical** per B1 (constructed from a single source via `spec_to_markdown`).

## Production-code impact

This is a spec-only deliverable. No files under `C:\Users\v-liyuanjun\Downloads\mealie\` were modified. Therefore all 537 pre-existing pytest tests remain unchanged (and trivially passing — no regression possible from spec metadata).

## Artifacts

```
case3-mealplan-bug-live-new-20260620T120351Z/
├── build_spec_v1.py            # programmatic v1 builder (1617 lines)
├── build_spec_v2.py            # v2 builder with v1-finding closures
├── spec.json                   # final (= v2)
├── spec.md                     # final (= v2)
├── RESULT.md                   # this file
└── spec_iterations/
    ├── spec_v1.json
    ├── spec_v1.md
    ├── review_v1.md            # 4-axis findings table for v1
    ├── spec_v2.json
    ├── spec_v2.md
    └── review_v2.md            # 4-axis closure table for v2
```

## Pipeline-version comparison hint (for downstream report)

The NEW pipeline's deterministic-validator quartet (A4/A5/B3/B1) caught zero of the 5 self-review findings but established a clean foundation by eliminating soft language, false citations, trace gaps, and md/json drift. The 5 findings all required reading-the-input-with-fresh-eyes review, suggesting:

1. The deterministic validators are necessary but not sufficient. Self-review or model review is still required for flow-fidelity and inter-SC coherence.
2. A3 fix_bug compliance was satisfied in both iterations (function naming + failing repro test), validating the new conditional-reviewer rule.
3. NC blocking decisions (3 in this case) were the right escape hatch for input-vs-code conflicts that can't be auto-resolved.
