# A3 perf_opt Rule Check — v1 (case-4 NEW pipeline)

> The A3 perf_opt rule is the new-pipeline v7 defense specifically for `intent_type == "perf_opt"` specs. It requires three explicit defenses; this document confirms all three are present and named in spec_v1.

## Rule

For any `intent_type == "perf_opt"` spec, the writer MUST include:

1. **Quantified performance target** — a numeric bound, not "make it fast". Both relative (delta) and absolute bounds preferred. Must be assertable in code.
2. **Behavior-preservation test** — a separate, named test that asserts the post-refactor behavior (response shape, side effects, etc.) is unchanged from the pre-refactor baseline. Cannot be conflated with the performance test.
3. **Nested-array-order subtle break defense** — for SQL-layer optimizations that change loader strategies (joinedload→selectinload, eager→lazy, etc.), an explicit named defense against silent reordering of nested arrays or any other subtle wire-shape change.

## Check (1) — Quantified performance target

**Status: PASS**

- **Where**: `FR-009 — Query-count bound is a small constant`.
- **Relative bound**: `count(queries for 100 recipes) <= count(queries for 10 recipes) + 3`. Numeric, assertable.
- **Absolute bound**: `<= 8 typical / <= 10 absolute` for `perPage <= 200`. Numeric, scoped, assertable.
- **Minimum proof**: 6 statements (1 COUNT + 1 parent + 3 selectinloads + 1 chained households). Pre-computed, defensible.
- **Implementation in test**: FR-010(7) asserts both bounds: `assert count_large <= count_small + 3` AND `assert count_large <= 10`.
- **Scoping**: FR-009 explicitly says the absolute bound is scoped to `perPage <= 200`; EC-006 gives the chunking formula for larger pages.

This is a fully quantified target — NOT "improve performance" or "reduce queries".

## Check (2) — Behavior-preservation test

**Status: PASS**

- **Where**: `FR-014 — Behavior-preservation test for nested array shape (selectinload-vs-joinedload trap)`. Distinct test file `tests/integration_tests/test_recipe_list_response_shape.py`. Sync `def`. NOT the same file as the perf test (FR-010 → `test_recipe_list_query_count.py`).
- **Asserts**:
  - (c) top-level key list-equality: `list(body['items'][0].keys()) == EXPECTED_KEYS` — catches field additions/removals/reorderings.
  - (d) nested M2M id-set equality per recipe (recipeCategory, tags, tools).
  - (e) `tools[*].householdsWithTool` list[str] set equality — the chained-selectinload seam.
  - (g) pagination envelope key set + values (`total=3, totalPages=1, page=1, perPage=50`).
- **Independence**: FR-014(h) explicitly notes "The test does NOT arm the SQL listener — it is independent of FR-010's query-count test. Both tests exist for orthogonal reasons."
- **Coverage**: SC-002 + SC-008 verify the test exists and passes.

This is a separately-named test that asserts behavior preservation orthogonally to the performance test.

## Check (3) — Nested-array-order subtle break defense

**Status: PASS**

- **Where**: Three coordinated artifacts:
  1. `SC-E — selectinload-vs-joinedload nested array order subtle break (A3 perf_opt rule trap)` — self-concern explicitly named "A3 perf_opt".
  2. `NC-007 — Does switching joinedload→selectinload on M2M collections silently change the ORDER of items inside the nested arrays?` — explicit clarification with multi-DBMS-aware resolution.
  3. `FR-014(f) — Order: assert that nested M2M arrays are set-equal to the seed and ALSO document explicitly in the test docstring whether nested order is deterministic.` — codifies the test behavior.

- **Resolution mechanism**:
  - NC-007 concludes: **set-equal, not list-equal**, because no `order_by=` is declared on `RecipeModel.recipe_category`, `.tools`, `.tags`, or `Tool.households_with_tool` (verified at `mealie/db/models/recipe/recipe.py:98-100,101,138` and `tool.py:54-56`).
  - Adding `order_by=` would be a behavior change requiring a maintainer decision — explicitly OUT OF SCOPE (recorded in `selected_approach_summary.non_actions`).
  - FR-014's test sorts both sides before comparison; the docstring records "nested array order is set-equal, not list-equal — see NC-007".
  - The set-equality assertion preserves the documented field-set contract while honestly disclosing order non-determinism.
- **Trap definition**: SC-E says "Switching joinedload→selectinload changes the SQL strategy that populates child collections. Neither RecipeModel.recipe_category nor RecipeModel.tools nor RecipeModel.tags nor Tool.households_with_tool declares an explicit order_by=. On some DBMS, the implicit row order produced by JOIN+ORDER BY (joinedload) and follow-up SELECT IN (selectinload) is NOT guaranteed to match. A silent reordering of nested arrays inside the JSON response would slip past existing tests and constitute a wire-protocol change that breaks downstream consumers."
- **Mitigation chain**: SC-E mitigation → FR-014 → NC-007 → test docstring.

This is the explicit A3 perf_opt nested-order trap defense, fully wired.

## Summary

| Rule check | Status | Artifact(s) |
|---|---|---|
| (1) Quantified target | ✅ PASS | FR-009 (relative + absolute bounds, scoped), FR-010 test asserts |
| (2) Behavior-preservation test | ✅ PASS | FR-014 (separate test file: `test_recipe_list_response_shape.py`), SC-002, SC-008 |
| (3) Nested-order trap defense | ✅ PASS | SC-E (self-concern), NC-007 (clarification), FR-014(f) (test contract), `non_actions` (no `order_by`) |

**A3 perf_opt rule: FULLY SATISFIED.**
