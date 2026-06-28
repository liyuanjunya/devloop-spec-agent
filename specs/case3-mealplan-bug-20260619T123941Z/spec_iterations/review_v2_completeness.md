# Completeness Review (v2)

## Verdict: NEEDS_REFINE

Spec v2 resolves both v1 completeness issues: the reproduction ingredients now consistently use `food_salt`, and the implementation constraints from `input.md` are explicitly represented as FR-7 / SC-8. Against the original input, all required phases, named regression tests, root-cause questions, and constraints are covered. I found no critical or high completeness gaps. One new medium issue remains: `spec_v2.md` has an internal pass-count contradiction in SC-3 (`6 pytest cases pass` vs the correct 8-case arithmetic and `spec_v2.json`), which should be fixed before implementation handoff.

## v1 issue resolution table

| v1 issue | v1 severity | v2 status | Evidence | Completeness assessment |
|---|---:|---|---|---|
| COMP-M-001: reproduction used `food_egg` despite input requiring salt | Medium | Resolved | `spec_v2.md:63-70` now creates `food_tomato` and `food_salt`, recipe ingredients include tomato quantity `2.0` and salt quantity `1.0`, and assertions expect tomato `4.0` / salt `2.0`. `spec_v2.json` has no `food_egg` matches. | The Step 1 fixture data now matches `input.md:25-29`. |
| COMP-M-002: implementation constraints were implied but not explicitly traceable | Medium | Resolved | `spec_v2.md:176-186` adds FR-7 with explicit no toggle/config/feature-flag workaround, no broad mechanical edit, and no parallel implementation using new shopping-item models/schemas. `spec_v2.md:201` adds SC-8 audit checks. | The constraints from `input.md:55-59` are now acceptance gates, not just diff-size implications. |

## New issues

### Medium issues

- **COMP-M-003**: `spec_v2.md` contradicts itself on the required pytest case count for the new regression file.
  - Location: `spec_v2.md:196`, with conflicting corrections at `spec_v2.md:203` and `spec_v2.md:249-250`; `spec_v2.json` SC-3 is already correct.
  - Evidence: `spec_v2.md:196` says the SC-3 threshold is `**6 pytest cases pass**`, but the same cell enumerates `1 repro + 1 single + 4 parametrized + 1 different-units + 1 same-name = **8 total**`. The explanatory note at `spec_v2.md:203`, the verification command at `spec_v2.md:249-250`, and `spec_v2.json` SC-3 all require 8 collected cases.
  - Impact: Implementers may stop after satisfying the lower `6` threshold or treat the Markdown and JSON specs as disagreeing, even though the test matrix is otherwise complete.
  - Suggested action: Change `spec_v2.md` SC-3 threshold from `**6 pytest cases pass**` to `**8 pytest cases pass**`.

## Requirement coverage

| Input requirement | v2 representation | Completeness verdict |
|---|---|---|
| Step 1: new repro test under `tests/integration_tests/` | US-1 / FR-1 names `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` | Covered |
| Step 1: recipe A with tomato quantity 2 each and salt quantity 1 tsp | US-1 AC steps 1-3 and 7 | Covered; v1 salt typo fixed |
| Step 1: Monday dinner + Wednesday lunch meal plan entries | US-1 AC step 4 | Covered |
| Step 1: call appropriate add-to-shopping-list interface | US-1 AC step 6; frontend/backend payload discussion | Covered |
| Step 1: assert tomato total 4 and no duplicate rows | US-1 AC step 7, SC-1/SC-2 | Covered |
| Step 1: repro fails before fix | Baseline precondition section, US-1 final AC, SC-1 | Covered on bug-injected branch |
| Step 2: PR root cause answers function, variant, boundaries | US-2 / FR-2 | Covered |
| Step 3: minimum fix in 1-3 functions; no refactor | US-3 / FR-3 / SC-5 / SC-6 | Covered |
| Step 4: four named regression tests | US-4 / FR-4 | Covered |
| Implementation constraints: no toggle, no broad edit, no parallel schema/model path | FR-7 / SC-8 | Covered |

## Summary

Completeness is substantially improved from v1. The only required edit is to align the Markdown SC-3 threshold with the already-correct 8-case test matrix and JSON spec. After that correction, v2 is complete enough for implementation from a requirements-coverage perspective.
