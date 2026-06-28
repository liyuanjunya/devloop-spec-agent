# Consistency Review v2 — Case 3 Mealie Shopping List Consolidation

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION

## Summary

Spec v2 resolves the major v1 consistency defects around `food_salt`, production-code file scope, regression sweep scope, and explicit bug-injection preconditions. However, it still has a blocking arithmetic typo in SC-3, a conflict between the required fix and an out-of-scope bullet, and a few smaller md/json or validation-scope inconsistencies.

## Findings

### C2-001 — SC-3 says 6 cases but its own arithmetic, verification command, and JSON say 8

- **Severity**: High
- **Scope**: SC internal; spec.md ↔ spec.json
- **Locations**:
  - `spec.md`: SC-3 row says "**6 pytest cases pass**" but the same cell computes `1 + 1 + 4 + 1 + 1 = 8 total`.
  - `spec.md`: SC-3 arithmetic note and verification command both require **8 collected cases / 8 passed**.
  - `spec.json`: `success_criteria[2].threshold` correctly says "8 collected pytest cases pass".
- **Issue**: The primary success threshold is contradictory. An implementer following the table literally may think 6 collected cases are acceptable.
- **Recommendation**: Change the SC-3 table threshold in `spec.md` from "**6 pytest cases pass**" to "**8 pytest cases pass**".

### C2-002 — Out-of-scope bullet appears to forbid the required fix

- **Severity**: High
- **Scope**: Baseline precondition / US-3 ↔ Out of scope; spec.md and spec.json
- **Locations**:
  - `spec.md`: baseline section says the working branch is cut from `inject-bug` and "DevLoop fixes the bug by reverting Variant A or Variant B to the canonical implementation".
  - `spec.md`: US-3 requires restoring canonical `can_merge` and/or `merge_items`.
  - `spec.md`: Out of scope says "Modifying or reverting the operator's bug-injection patch from a code-agent commit".
  - `spec.json`: `approach_rationale` says the patch reverts a canonical injection variant, while `out_of_scope[8]` says modifying or reverting the injection patch is out of scope.
- **Issue**: Read literally, the out-of-scope item forbids the exact 1-2 line revert that the spec requires.
- **Recommendation**: Reword the out-of-scope item to forbid modifying the separate `inject-bug` branch or the operator's injection instructions, while explicitly allowing the case-3 fix branch to restore the canonical hunk.

### C2-003 — Metadata "single function" conflicts with `can_merge` and/or `merge_items`

- **Severity**: Medium
- **Scope**: Metadata ↔ US/FR implementation scope
- **Locations**:
  - `spec.md`: Metadata scope says "`service` (single function in `...shopping_lists.py`) + `test`".
  - `spec.md`: selected approach, baseline, US-3, and FR-3 allow `can_merge` and/or `merge_items`.
  - `spec.json`: scope is only `["service", "test"]` and does not assert "single function".
- **Issue**: Variant B fixes `can_merge`, Variant A fixes `merge_items`, and the spec permits "and/or"; "single function" is too narrow.
- **Recommendation**: Change metadata to "single production file; one or both of `can_merge` / `merge_items` depending on injected variant."

### C2-004 — SC-6 requires post-commit production-file count, but verification commands omit it

- **Severity**: Medium
- **Scope**: SC ↔ verification commands; spec.md and spec.json
- **Locations**:
  - `spec.md`: SC-6 measurement requires both `git diff --name-only -- mealie/` and `git diff --name-only HEAD~ -- mealie/`.
  - `spec.md`: verification commands include only "Production-file count check (pre-commit)".
  - `spec.json`: `success_criteria[5].measurement` requires both, but `verification_commands` has only the pre-commit production-file count check.
- **Issue**: The verification checklist cannot fully measure SC-6 as written.
- **Recommendation**: Add a post-commit production-file count row using `git diff --name-only HEAD~ -- mealie/`, or remove the post-commit requirement from SC-6.

### C2-005 — FR-5 validation scope includes `test_group_mealplan.py`, but FR-5 code references omit it

- **Severity**: Low
- **Scope**: FR internal; spec.md and spec.json
- **Locations**:
  - `spec.md`: FR-5 description requires all tests in `test_group_shopping_lists.py`, `test_group_shopping_list_items.py`, and `test_group_mealplan.py`.
  - `spec.md`: FR-5 code references list only the first two files.
  - `spec.json`: same pattern in `functional_requirements[4]`.
- **Issue**: This is mostly documentation drift, because SC-4 and verification commands do include `test_group_mealplan.py`.
- **Recommendation**: Add the relevant `test_group_mealplan.py` line range to FR-5 code references or clarify that FR-5 references are illustrative, not exhaustive.

## Self-concerns vs FRs / ACs

- SCN-1 remains consistent with out-of-scope: the internal duplicate scaling latent bug is explicitly documented and not required for this fix.
- SCN-2 remains consistent with tests using `pytest.approx(..., abs=1e-6)`.
- SCN-3 remains consistent with the `standard_unit=None` regression cases.
- SCN-4 is consistent with the new baseline precondition, but C2-002 must be fixed so the "revert injected hunk" wording is not forbidden elsewhere.

## Edge cases vs FRs / ACs

- EC-1 and EC-2 align with US-4 boundary tests.
- EC-3 aligns with the root-cause boundary-case description, though no dedicated named test covers mixed `recipe_increment_quantity`; acceptable if this remains an edge-case document rather than required coverage.
- EC-4 aligns with approximate assertions.
- EC-5 is explicitly out of scope.
- EC-6 aligns with the `food_id is None` fallback in US-2/FR-2.
- EC-7 aligns with SCN-1/out-of-scope.
- EC-8 aligns with the new `payload_form="consolidated"` parameterization.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| SC-3 threshold | Says "**6 pytest cases pass**" while also computing 8 total and later saying 8 collected cases. | Says "8 collected pytest cases pass". | Blocking md/json disagreement; JSON is consistent with the arithmetic. |
| Metadata scope | Says service scope is a "single function" in `shopping_lists.py`. | Scope is `["service", "test"]`; approach rationale allows `can_merge` and/or `merge_items`. | md is narrower than JSON and the body. |
| FR-7 code references | Lists `bulk_create_items:154-223` but not the specific `create_many` / `update_many` call-site range. | Adds `shopping_lists.py:215-216` for create/update persistence call sites. | JSON is more precise; low-risk documentation drift. |
| Out-of-scope injection wording | Says the patch lives on `inject-bug` and case-3 branches are downstream. | Says the patch lives on `inject-bug` upstream of case-3 branches. | Semantically equivalent; both share C2-002's ambiguity. |

No other substantive spec.md/spec.json disagreements were found; most remaining differences are structured condensation in JSON.

## needs_clarification assessment

`NC-001` is now appropriate: the variant choice is a real operator-time ambiguity, and the spec provides a default plus resolution path. No additional clarification is required for `food_salt`, regression sweep scope, or pytest count once C2-001 is corrected.
