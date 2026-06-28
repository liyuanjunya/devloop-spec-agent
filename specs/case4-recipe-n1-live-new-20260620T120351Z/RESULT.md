# RESULT — case-4 NEW pipeline (Recipe List N+1 Performance Refactor)

> Workspace: `C:\Users\v-liyuanjun\source\repos\devloop\specs\case4-recipe-n1-live-new-20260620T120351Z\`
> Pipeline: **NEW (v7 defenses)** · Intent: `perf_opt` · Driven: **v1 + v2 end-to-end**
> Date: 2026-06-20T12:04+08:00

---

## TL;DR

- **V1** passed all 4 self-review axes + A3 perf_opt rule with **0 findings** across critical/high/medium/low.
- **V2** is a precision-polish iteration adding 7 additive improvements (verbatim test skeletons, DBMS-loader matrix, keyed chunking formula, session-state edge case, executable "no migration" verification, count-diff SAWarning check, EXPECTED_KEYS literal). **0 new findings; v1's PASS verdict carries through, strictly strengthened.**
- **Final spec**: `spec.json` (15 FRs, 9 SCs, 5 USs, 10 ECs, 8 NCs, 5 self-concerns) + `spec.md` at workspace root.
- **A3 perf_opt rule fully satisfied**: quantified target (FR-009), behavior-preservation test (FR-014), nested-array-order trap defense (SC-E + NC-007 + FR-014(f)).
- **C3 perspective auto-add**: performance perspective is already in `exploration/consolidated.md` (5 perspectives, perf-aware).

---

## Pipeline log

| Phase | Artifact | Verdict |
|---|---|---|
| 1. Writer v1 | `spec_iterations/spec_v1.json` (15 FRs, 8 SCs, 5 USs, 9 ECs, 8 NCs, 5 self-concerns) + `spec_iterations/spec_v1.md` | ✅ |
| 2. Self-validate v1 (4 axes) | `spec_iterations/validation_v1.md` | ✅ 0 findings on all 4 axes |
| 3a. Self-review v1 — Architecture | `spec_iterations/review_v1_architecture.md` | ✅ PASS, 0/0/0/0 |
| 3b. Self-review v1 — Completeness | `spec_iterations/review_v1_completeness.md` | ✅ PASS, 0/0/0/0 |
| 3c. Self-review v1 — Consistency | `spec_iterations/review_v1_consistency.md` | ✅ PASS, 0/0/0/0 |
| 3d. Self-review v1 — Executability | `spec_iterations/review_v1_executability.md` | ✅ PASS, 0/0/0/0 |
| 3e. Self-review v1 — A3 perf_opt rule | `spec_iterations/review_v1_a3_perfopt.md` | ✅ All 3 checks PASS |
| 4. Rewrite v1 → v2 (precision polish) | `spec_iterations/rewrite_v1_to_v2.md` (7 additive changes) | ✅ |
| 5. Writer v2 | `spec_iterations/spec_v2.json` (15 FRs, **9** SCs, 5 USs, **10** ECs, 8 NCs, 5 self-concerns) + `spec_iterations/spec_v2.md` | ✅ |
| 6. Self-validate v2 (4 axes) | `spec_iterations/validation_v2.md` | ✅ 0 findings on all 4 axes |
| 7a. Self-review v2 — Architecture | `spec_iterations/review_v2_architecture.md` | ✅ PASS, 0/0/0/0 |
| 7b. Self-review v2 — Completeness | `spec_iterations/review_v2_completeness.md` | ✅ PASS, 0/0/0/0 |
| 7c. Self-review v2 — Consistency | `spec_iterations/review_v2_consistency.md` | ✅ PASS, 0/0/0/0 |
| 7d. Self-review v2 — Executability | `spec_iterations/review_v2_executability.md` | ✅ PASS, 0/0/0/0 |
| 7e. Self-review v2 — A3 perf_opt rule | `spec_iterations/review_v2_a3_perfopt.md` | ✅ All 3 checks PASS, strengthened |
| 8. Promote v2 → final | `spec.json` + `spec.md` (root) | ✅ |

**No mealie source code was modified** by this pipeline run (spec-only phase). The eventual 537-test baseline preservation is encoded as FR-013 (explicit must-pass enumeration) + SC-003 (uv run task py:test exit 0) + SC-009 (no alembic migration) — for the downstream implementation phase to satisfy.

---

## V7 defenses applied (final, post-v2)

| Defense | Where (final spec) |
|---|---|
| **A3 perf_opt: quantified target** | FR-009 (relative + absolute bounds, scoped to perPage ≤ 200) + FR-010 verbatim skeleton asserting both bounds |
| **A3 perf_opt: behavior-preservation test** | FR-014 with EXPECTED_KEYS Python literal + verbatim skeleton; SC-002 + SC-008 verification |
| **A3 perf_opt: nested-array-order trap** | SC-E (self-concern) + NC-007 (DBMS × loader matrix) + FR-014(f) (sort-before-set-compare + docstring) + `non_actions` ("no order_by") |
| **C3: performance perspective auto-added** | `exploration/consolidated.md` carries data/api/test/history/ui perspectives, all perf-aware |
| Executable response-shape assertion seam | FR-014's EXPECTED_KEYS list-equal + nested set-equal + envelope set-equal |
| Existing test surface enumeration | FR-013 explicit file list + 8 verification commands |
| spec.md / spec.json consistency | .md is derived summary by ID; .json is single source for citations |
| No hedging placeholders | All 4-axis validations: 0 hits across {TBD, or equivalent, if needed, as appropriate, maybe, perhaps, ???} |
| Chunking-aware bound scoping | EC-006 keyed formula (k_households chunks by Tool.id, NOT recipe.id) + FR-009 scoped to perPage ≤ 200 + SC-C |
| Multi-tenant isolation explicit | FR-012 + EC-005 + cite of `d02023e1` security filter commit |
| Session-state interaction documented | EC-010 (SQLAlchemy expire-on-commit + selectinload + warm-up rationale) |
| Executable "no migration" verification | SC-009 (`git diff main --name-only -- mealie/alembic/versions/` returns empty) |
| `selected_approach_summary.non_actions` enumerated | 9 explicit non-actions (no cache, no migration, no order_by, no dynamic, etc.) |

---

## Defects fixed vs prior case-4 v1 (20260619T124200Z run)

This new-pipeline run proactively addresses every defect identified in the prior case-4 review cycle:

| Prior defect | How v1 (this run) addresses it |
|---|---|
| **COMP-H-001** — "response fields 100% unchanged" lacks executable seam | FR-014 + executable `EXPECTED_KEYS` list-equal assertion (v2 makes it verbatim) |
| **COMP-H-002** — Existing recipe tests not enumerated | FR-013 lists 4 unit + entire user_recipe_tests/ subtree + 3 sibling integration test files + 8 verification commands |
| **COMP-M-001** — slug_image not in FR-001 | FR-001 explicitly notes "input.md:23 lists slug_image — that field does not exist; preserving means preserving slug+image, NOT adding slug_image" |
| **ARCH-H-001** — Nested array order not stable / no test | FR-014 + NC-007 + SC-E full chain (v2 adds DBMS matrix) |
| **ARCH-H-002** — Chunking miscount for chained selectinload | EC-006 keyed formula in v2 (`k_households` chunks by Tool.id count) + FR-009 scoping |
| **ARCH-M-001** — `rating` wording could mislead | NC-001 + FR-013 explicitly say rating uses correlated subquery for sort/filter only, NOT projection |
| **C-001** — FR-011/NC-002 reference non-existent SC-003 | FR-011 + NC-002 reference `self_concerns SC-C` (real ID) |
| **C-002** — EC-002 wrong count (6 vs 5) | EC-002 explicitly says "5 statements typically (the chained households selectinload only fires when at least one Tool is loaded)" |
| **C-003** — perPage=-1 chunking overstated | EC-006 + SC-C + FR-009 explicitly scope <= 10 to perPage <= 200; chunking formula given for larger |
| **C-004** — "byte-identical" vs "modulo non-deterministic" | US-1 + SC-002 use consistent "normalized JSON diff after masking documented volatile fields" wording |
| **C-005** — Regression test perPage not specified | FR-010(6) explicitly says "perPage=50 after 10 seeded recipes, perPage=200 after 100 seeded recipes"; SC-001 metric is in same units |
| **Executability mismatches** between spec.md and spec.json `code_references` | spec.md is now a derived summary table by ID; spec.json is single source for citations |

---

## Spec final structure

### `spec.json` (15 FRs, 9 SCs, 5 USs, 10 ECs, 8 NCs, 5 self-concerns)

- **Top-level**: schema_version, case_id, title, intent_type=`perf_opt`, scope=`[repo, schema, service, test]`
- **selected_approach**: Conservative single-seam loader-options refactor — edit `RecipeSummary.loader_options()` only
- **files_touched**:
  - modified: `mealie/schema/recipe/recipe.py` (loader_options at L168-175)
  - added: `tests/integration_tests/test_recipe_list_query_count.py`, `tests/integration_tests/test_recipe_list_response_shape.py`
- **_pipeline_meta**: v2 iteration with rationale recorded

### `spec.md`

Derived summary table referencing IDs from `spec.json`. ~9.4 KB.

---

## Acceptance gate for the implementation phase (downstream)

The downstream implementation phase MUST satisfy:

1. **FR-001..FR-008**: edit only `mealie/schema/recipe/recipe.py:168-175`; swap M2M joinedloads to selectinloads with chained households selectinload; keep `joinedload(user).load_only(household_id)` + `.scalars().unique().all()`.
2. **FR-009**: regression test `tests/integration_tests/test_recipe_list_query_count.py` (sync def, listener arm-then-remove, two scales) — assertions match the verbatim skeleton in FR-010.
3. **FR-014**: behavior test `tests/integration_tests/test_recipe_list_response_shape.py` (sync def, EXPECTED_KEYS literal, nested set-equal) — assertions match the verbatim skeleton.
4. **FR-013 + SC-003**: project baseline 537 pytest tests pass (no skip/xfail/new warnings).
5. **SC-001, SC-005, SC-008**: 3 new test files all pass.
6. **SC-009**: `git diff main --name-only -- mealie/alembic/versions/` returns empty.
7. **FR-015 + SC-004**: PR description has before/after counts + EXPLAIN ANALYZE.

All 7 acceptance items are independently verifiable via the explicit commands in the spec.

---

## Final pipeline status: **DONE**

Both iterations (v1 + v2) ran end-to-end through:
- Writer
- Self-validate (4 axes)
- Self-review (4 axes + A3 perf_opt rule)
- (v2 only) Rewrite

All 4 axes self-validation = 0 findings (v1 and v2).
All 4 axes self-review = 0/0/0/0 findings (v1 and v2).
A3 perf_opt rule = all 3 checks PASS (v1 and v2, strengthened).

V2 is promoted to `spec.json` + `spec.md` at workspace root as the final case-4 spec.
