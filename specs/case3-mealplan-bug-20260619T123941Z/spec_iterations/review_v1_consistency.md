# Consistency Review v1 — Case 3 Mealie Shopping List Consolidation

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION  

## Summary

The spec is mostly coherent, but several consistency defects should be fixed before implementation. The most important are the `food_egg` vs `food_salt` contradiction, ambiguous "only file modified" wording despite required new tests, and inconsistent expected pytest case counts for a parametrized test.

## Findings

### C-001 — US-1 ingredient name contradicts itself

- **Severity**: High
- **Scope**: US ↔ AC internal; spec.md and spec.json
- **Locations**:
  - `spec.md`: US-1 AC step 1 says `food_tomato` and `food_egg`; steps 3 and 7 assert/use `food_salt`.
  - `spec.json`: `user_stories[0].acceptance_criteria[1]` says `food_egg`; `[3]` and `[7]` use/assert `food_salt`.
- **Issue**: The reproduction test cannot literally satisfy both "create food_egg" and "recipe/list assertions use food_salt".
- **Recommendation**: Replace `food_egg` with `food_salt` everywhere, or update all later recipe/assertion text to use egg. Given the intended tomato + salt assertions, `food_salt` is the likely correction.

### C-002 — File-scope wording conflicts with required test additions

- **Severity**: High
- **Scope**: US ↔ FR ↔ SC contradiction
- **Locations**:
  - `spec.md`: US-1/US-4 require new file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py`.
  - `spec.md`: US-3 AC says "Only `mealie/services/household_services/shopping_lists.py` is modified"; FR-3 says "The diff modifies only ..." that file.
  - `spec.json`: same ambiguity in US-3 and FR-3.
- **Issue**: Read literally, US-3/FR-3 forbid the new test file required by US-1/US-4. SC-6 narrows this to production code, but FR-3 does not.
- **Recommendation**: Change US-3/FR-3 to "Only production-code modification is `mealie/services/household_services/shopping_lists.py`; the new test file is allowed/required."

### C-003 — Parametrized test count conflicts with success criteria

- **Severity**: Medium
- **Scope**: AC-internal; SC ↔ verification
- **Locations**:
  - `spec.md`: US-4 requires `test_multiple_occurrences_same_unit` parametrized over `[2, 3]`.
  - `spec.md`: SC-3 says "All 5 tests ... 5 / 5 PASS".
  - `spec.md`: verification says "5 passed (or more with parametrization expansion)".
  - `spec.json`: SC-3 says "5/5 named tests PASS (parametrized expansion may yield more)".
- **Issue**: Pytest will collect 6 cases: 1 repro + 1 single + 2 parametrized + 1 different-units + 1 same-name.
- **Recommendation**: State "5 named tests / 6 collected pytest cases pass" consistently in SC-3 and verification commands.

### C-004 — Related regression validation scope differs across sections

- **Severity**: Medium
- **Scope**: US ↔ FR ↔ SC inconsistency
- **Locations**:
  - US-3 AC mentions pre-existing tests in `test_group_shopping_lists.py` and `test_group_shopping_list_items.py`.
  - FR-5, SC-4, and verification commands also require `test_group_mealplan.py`.
- **Issue**: The required regression sweep is broader in FR/SC than in the user-story AC.
- **Recommendation**: Add `test_group_mealplan.py` to US-3 AC, or explicitly mark it as an additional non-functional validation requirement.

### C-005 — `needs_clarification: None` is too strong until contradictions are resolved

- **Severity**: Medium
- **Scope**: needs_clarification ↔ AC/defaults
- **Locations**:
  - `spec.md`: `needs_clarification` says none.
  - `spec.json`: `"needs_clarification": []`.
- **Issue**: The food name contradiction and pytest count mismatch require spec-owner resolution or correction.
- **Recommendation**: Either fix C-001/C-003 directly, or add clarification items for ingredient identity and collected test-count expectation.

## Self-concerns vs FRs / ACs

- SCN-1 (in-recipe duplicate scaling latent bug) is consistent with FR-3 and out-of-scope because `get_shopping_list_items_from_recipe` is explicitly unchanged.
- SCN-2 (float precision) is consistent with FR/AC expectations because tests use approximate assertions.
- SCN-3 (future unit conversion) is consistent with EC-1 and US-4 because tests intentionally create `standard_unit=None` units.

## Edge cases vs FRs / ACs

- EC-1 aligns with US-4 `test_multiple_occurrences_different_units` and FR-2 boundary cases.
- EC-2 aligns with US-4 `test_different_food_same_name` and FR-2 boundary cases.
- EC-3 aligns with FR-2/FR-4 recipe-reference accumulation, though no named test covers mixed `recipe_increment_quantity`; this is acceptable unless intended as required coverage.
- EC-4 aligns with approximate quantity assertions.
- EC-5 is explicitly out of test scope and does not contradict any FR.
- EC-6 aligns with FR-2 note fallback.
- EC-7 aligns with SCN-1/out-of-scope and does not contradict the minimum fix.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| US-1 ingredient setup | Says create `food_tomato` and `food_egg`, then later uses `food_salt`. | Same contradiction. | No md/json disagreement, but both contain the same internal contradiction (C-001). |
| US-1 meal-plan entries | Specifies Monday dinner and Wednesday lunch entries. | Says two entries but only details Monday dinner; adds date string / `recipeId` normalization. | JSON is missing the second exact entry and adds normalization detail absent from md. |
| US-2 PR description wording | Requires answers "verbatim and in order". | Requires answers "in order" but omits "verbatim". | JSON weakens the md requirement. |
| US-3/FR-3 file scope | Wording can read as only `shopping_lists.py` modified, despite required tests. | Same ambiguity. | No md/json disagreement, but both conflict with US-1/US-4 unless scoped to production code. |
| SC-3 threshold | Says `5 / 5 PASS`. | Says `5/5 named tests PASS (parametrized expansion may yield more)`. | JSON partially resolves parametrization; md is stricter and likely wrong for pytest collection count. |
| EC-6 source | Cites `can_merge` line 71. | Cites lines 70-71. | Minor code-reference granularity mismatch. |

No other semantic spec.md/spec.json disagreements were found; remaining differences appear to be condensation, formatting, or structured representation.

## needs_clarification assessment

The current "None" is not consistent with the spec as written. At minimum, clarify or correct:

1. Whether the second ingredient is `food_salt` or `food_egg`.
2. Whether success criteria count named tests (5) or collected pytest cases (expected 6 with parametrization).
3. Whether `test_group_mealplan.py` is mandatory in the pre-existing regression sweep.
