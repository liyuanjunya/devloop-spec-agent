# V2 self-review — 4-axis rubric + A3 fix_bug rule

**Subject**: `spec_iterations/spec_v2.json` + `spec_iterations/spec_v2.md` (also mirrored to top-level `spec.json` + `spec.md`)
**Validators (4)**: A4 schema PASS · A5 citations 0 problems · B3 trace gaps 0 · B1 roundtrip PASS
**Stats**: 15 FRs · 7 SCs · 6 US (all P1) · 3 NCs · 5 entities · 8 edge cases · 7 assumptions · 8 out-of-scope · 3 self-concerns

## v1 → v2 closure ledger

| ID | Severity | v1 finding | v2 closure |
|---|---|---|---|
| ARCH-NEW-H-001 | HIGH | FR-002 acceptance enumerated only the bulk-add POST; meal-plan persistence was implicit, allowing a spec-compliant test that bypasses the user-visible flow. | **CLOSED**. FR-002 step (2) now mandates `POST /api/households/mealplans` for each occurrence with explicit reference to `test_create_mealplan_with_recipe:80-99`. US-1 AC1 `when` now first persists meal-plan entries before the bulk-add. US-2 description rewritten to call out the meal-plan step. |
| COMP-NEW-M-001 | MEDIUM | Regression tests at FR-008/FR-010/FR-011 didn't say whether to persist meal-plan entries or use bulk-add directly. | **CLOSED**. Each of FR-008/FR-010/FR-011 now states "The test MAY skip the `POST /api/households/mealplans` step because this regression validates [an independent invariant] on the bulk-add path itself". FR-009 explicitly keeps meal-plan persistence under both wire shapes. |
| CONS-NEW-M-001 | MEDIUM | SC-002 metric used `uv run pytest`; SC-007 used `task py:test`. Mismatch with Mealie convention. | **CLOSED**. SC-002 metric now reads `task py:test -- tests/integration_tests/...::test_meal_plan_to_shopping_list_accumulates_duplicate_recipe_ingredients`, matching SC-007 and Mealie's `.github/copilot-instructions.md`. |
| EXEC-NEW-M-001 | MEDIUM | FR-009's wire-shape parametrization left the pytest idiom unspecified. | **CLOSED**. FR-009 now reads "preferred idiom: `@pytest.mark.parametrize` decorator with two cases, matching the convention in `tests/integration_tests/user_recipe_tests/test_recipe_ingredients.py:177-234`". |
| EXEC-NEW-M-002 | MEDIUM | SC-007 threshold `collected >= 542` was vulnerable to upstream baseline drift. | **CLOSED**. SC-007 metric now defines `BASELINE_COLLECTED` (collected count from `task py:test` on the bug-injected branch immediately before adding the new test module) and threshold is `post-fix collected == BASELINE_COLLECTED + 5 AND failed == 0 AND error == 0`. |

## A3 fix_bug rule (intent-conditional)

| Requirement | Status | Evidence |
|---|---|---|
| Spec MUST name the buggy function(s) | ✅ PASS | FR-001 names both `can_merge:45-71` and `merge_items:73-128`; FR-006 pins variant A to `merge_items:96`; US-3 AC1 mandates the PR description name `merge_items` (variant A) or `can_merge` (variant B). |
| Spec MUST require a failing-before-fix repro test | ✅ PASS | FR-002 + US-2 AC1 (`FAILS on the bug-injected branch`) + SC-002 metric (`non-zero exit on bug-injected branch AND zero exit on post-fix branch`). |
| Spec MUST require minimum-scope fix | ✅ PASS | FR-006 + FR-013 + SC-001 (`exactly 1 file`) + SC-004 (`added <= 5 AND removed <= 5`). |
| Spec MUST encode 4 named regression tests | ✅ PASS | FR-008..FR-011 + SC-005 (`exactly 5 passing tests with the required names (1 repro + 4 regressions)`). |

## Architecture (0 C / 0 H / 0 M) — clean

- v2 explicitly mirrors the input's user-visible flow (create meal plan → trigger consolidation), tightening the user→repository boundary.
- Controller/service/repo separation respected: FR-002 cites the controller route, FR-006 pins the service-layer fix location, FR-007 enforces PR-description-level documentation, no repository changes.
- No new layers, schemas, migrations, or routes introduced (FR-013 + out_of_scope item 6).

## Completeness (0 C / 0 H / 0 M) — clean

All input items remain claimed:
- 步骤 1 (复现) → FR-002 + SC-002 (now with explicit meal-plan persistence)
- 步骤 2 (根因) → FR-007 + SC-006
- 步骤 3 (最小修复) → FR-006 + FR-013 + SC-001 + SC-004
- 步骤 4 (四项回归) → FR-008..FR-011 + SC-005
- 实现约束 → FR-013 + FR-014 + SC-001 + SC-004
- 537 pytest baseline → FR-012 + SC-007 (now baseline-relative form)

## Consistency (0 C / 0 H / 0 M) — clean

- NC-001 variant A ↔ FR-006 line-96 fix ↔ US-3 AC1 `merge_items` mention — agrees ✓
- NC-002 `standard_unit=None` ↔ FR-004 ↔ FR-010 — agrees ✓
- NC-003 wire shape ↔ FR-002 (per-occurrence, with meal-plan persistence) ↔ FR-009 parametrize — agrees ✓
- SC-002 invocation `task py:test` ↔ SC-007 invocation `task py:test` — agrees ✓
- Edge-case 1 `internal-duplicate OUT OF SCOPE` ↔ out_of_scope item 1 — agrees ✓
- Cross-references between FR/SC/US resolve symmetrically (B3 confirms 0 gaps).

## Executability (0 C / 0 H / 0 M) — clean

- All 50+ code references mechanically verified by A5 against `C:\Users\v-liyuanjun\Downloads\mealie\`.
- FR-009 parametrize idiom is now pinned (`@pytest.mark.parametrize`).
- SC-007 threshold is invariant to upstream Mealie test additions (baseline-relative).
- The 537 hard-coded number in the spec body (assumptions, edge cases, FR-012 text) is acceptable since FR-012 text and SC-007 threshold both reference it explicitly as the "at time of writing" baseline; the *evaluation criterion* in SC-007 uses the relative form.

## Total: 0 C / 0 H / 0 M = 0 unresolved issues

## Decision: ACCEPT v2 (no v3 needed)

All v1 findings are closed; no new issues surfaced. v2 is the final spec for case-3.
