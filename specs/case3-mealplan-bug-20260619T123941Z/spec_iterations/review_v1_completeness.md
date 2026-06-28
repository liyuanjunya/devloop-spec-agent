# Completeness Review (v1)

## Verdict: NEEDS_REFINE

The spec is broadly complete against `input.md`: all four requested phases are represented, the three root-cause questions are captured in US-2/FR-2, the minimum-fix boundary is captured in US-3/FR-3/SC-5/SC-6, and the four exact regression test names and expected behaviors are present in US-4/FR-4/SC-3. I found no critical or high completeness gaps. Two medium issues should be fixed before implementation: the reproduction AC has an inconsistent ingredient name (`food_egg` vs required salt), and the implementation constraints are mostly implied by diff limits rather than explicitly enumerated, especially the no-toggle requirement.

## Critical issues

(none — no required step or named regression test is entirely absent)

## High issues

(none — every required step is actionable enough to implement)

## Medium issues

- **COMP-M-001**: Step 1's specific ingredient requirement is inconsistently represented as `food_egg` in one AC, while the input requires salt.
  - Location: US-1 AC1 / `spec.json` US-1 AC2.
  - Evidence: `input.md:25-29` requires recipe A to include `番茄` quantity `2` unit `个` and `盐` quantity `1` unit `小勺`, then assert tomato accumulates to `4`. The spec later uses salt correctly in US-1 AC3/AC7 (`food_salt`, quantity `1.0`, `unit_tsp`, expected salt `2.0`), but US-1 AC1 says to create `food_tomato` and `food_egg`.
  - Suggested action: Replace `food_egg` with `food_salt` everywhere in the reproduction setup so the specific food/quantity requirement is unambiguous.

- **COMP-M-002**: The implementation constraints are satisfied in spirit but not explicitly traceable as their own acceptance criteria.
  - Location: US-3 / FR-3 / Out of scope.
  - Evidence: `input.md:55-59` explicitly forbids a toggle/config workaround, global grep+sed-style broad edits, and a parallel implementation outside existing `RepositoryShoppingItem` / `ShoppingListItem` schema. The spec strongly implies the latter two through `FR-3` (only `shopping_lists.py`, only `can_merge`/`merge_items`, ≤5 changed lines, no new methods/schema changes), but it never states "no toggle/config workaround" verbatim and does not name `RepositoryShoppingItem` / `ShoppingListItem` as a constraint.
  - Suggested action: Add an implementation-constraints FR or US-3 AC that explicitly says: no feature flag/config/toggle workaround; no global grep+sed/broad mechanical changes; no parallel shopping-item model/path, continue using existing `RepositoryShoppingItem` / `ShoppingListItem` schemas.

## Requirement coverage

| Input requirement | Spec representation | Completeness verdict |
|---|---|---|
| Step 1: new repro test under `tests/integration_tests/` | US-1 AC1, FR-1, SC-1/SC-2 | Covered |
| Step 1: recipe A with tomato quantity 2 each and salt quantity 1 tsp | US-1 AC3/AC7, FR-1 | Mostly covered; see COMP-M-001 for `food_egg` typo |
| Step 1: Monday dinner + Wednesday lunch meal plan entries | US-1 AC4, `spec.json` US-1 AC5 | Covered |
| Step 1: call appropriate shopping-list endpoint | Problem statement, US-1 AC6, FR-1 | Covered |
| Step 1: assert tomato total quantity 4 and not duplicate rows | US-1 AC7, FR-1, SC-1/SC-2 | Covered |
| Step 1: repro test fails before fix | US-1 final AC, FR-1, SC-1 | Covered |
| Step 2: answer buggy function in PR description | US-2 AC1, FR-2 | Covered |
| Step 2: answer merge-key vs overwrite/accumulate | US-2 AC2, FR-2 | Covered |
| Step 2: answer unit and same-name food boundaries | US-2 AC3, FR-2, EC-1/EC-2 | Covered |
| Step 3: minimal fix in 1-3 functions, no surrounding refactor | US-3, FR-3, SC-5/SC-6, Out of scope | Covered |
| Step 4: `test_single_occurrence` exact behavior | US-4 AC1, FR-4 | Covered |
| Step 4: `test_multiple_occurrences_same_unit` exact behavior | US-4 AC2, FR-4 | Covered |
| Step 4: `test_multiple_occurrences_different_units` exact behavior | US-4 AC3, FR-4, EC-1 | Covered |
| Step 4: `test_different_food_same_name` exact behavior | US-4 AC4, FR-4, EC-2 | Covered |
| Constraint: no toggle/config workaround | Implied by US-3/FR-3 only | Weak; see COMP-M-002 |
| Constraint: no global grep+sed broad changes | FR-3, SC-5/SC-6 | Covered |
| Constraint: no parallel implementation; use existing shopping item schemas | US-3/FR-3/FR-6, Out of scope | Mostly covered; see COMP-M-002 |

## Summary

The spec passes completeness review at the structural level: every requested phase and every exact regression test is present and mapped to executable acceptance criteria. The remaining completeness work is editorial but important for implementation clarity: fix the `food_egg`/salt inconsistency and make the three implementation constraints explicit rather than inferred from narrow diff limits.
