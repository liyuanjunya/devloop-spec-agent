# Completeness Review (v1)

## Verdict: NEEDS_REFINE

The spec is strong on the core N+1 design: it enumerates the actual `RecipeSummary` response contract, preserves pagination semantics, captures the `Tool.households_with_tool` assertion seam, makes query-count growth measurable, and includes the required new regression test as FR-010. However, two completeness gaps remain against input §1-§3: the response-preservation guarantee is not backed by an explicit executable JSON equality/key-order assertion seam, and the required existing recipe-test files are not explicitly listed as must-pass.

## Critical issues

(none — the main performance goal and new performance test are present and actionable)

## High issues

- **COMP-H-001 — "response fields 100% unchanged" is stated, but not enforced by an explicit assertion seam.**
  - Location: US-1, FR-001, SC-002, FR-010.
  - Evidence: `input.md:19` requires **保持响应字段 100% 不变**, and the review scope asks for an explicit assertion seam. The spec states byte-identical JSON diff in US-1/SC-002 and enumerates fields in FR-001, but SC-002 verifies primarily by existing tests (`test_recipe_owner.py`, `test_recipe_crud.py`, `test_recipe_cross_household.py`) rather than requiring a concrete assertion that compares pre/post field set, order, values, and pagination envelope. FR-010's new test asserts query counts plus `items` length and `total`, but not full response JSON shape/order/content.
  - Suggested action: Add a hard FR/SC requiring a named assertion seam, e.g. a helper/test that snapshots `orjson.dumps(pagination_response.model_dump(by_alias=True))` or asserts ordered keys for the pagination envelope and `items[*]`, including nested `recipeCategory`, `tags`, and `tools` fields. The seam should fail if any field is added, removed, reordered, renamed, or value/pagination semantics change.

- **COMP-H-002 — Existing recipe test files are not explicitly enumerated as must-pass.**
  - Location: US-3, SC-003, `spec.json` SC-003.
  - Evidence: `input.md:28-33` requires all `tests/unit_tests/test_recipe*.py`, all `tests/integration_tests/test_recipe*.py`, and recipe-related `tests/multitenant_tests/` tests to pass, and the review scope asks whether all existing test files are explicitly listed. The spec lists selected test names and commands for `tests/unit_tests/repository_tests/test_recipe_repository.py`, `tests/unit_tests/schema_tests/test_recipe.py`, and `tests/integration_tests/user_recipe_tests/`, but omits explicit file-level enumeration. At minimum, the Mealie tree also contains `tests/unit_tests/test_recipe_export_types.py`, `tests/unit_tests/test_recipe_parser.py`, many `tests/integration_tests/user_recipe_tests/test_recipe_*.py` files, `tests/integration_tests/public_explorer_tests/test_public_recipes.py`, `tests/integration_tests/recipe_migration_tests/test_recipe_migrations.py`, and organizer/group recipe tests such as `tests/integration_tests/user_household_tests/test_group_recipe_actions.py`. `tests/multitenant_tests/` has no `*recipe*.py` filename, so the spec should explicitly state how recipe-relevant multitenant coverage is determined or that none exists by filename.
  - Suggested action: Add an appendix or FR listing the exact must-pass files/patterns and commands, including the two root unit recipe files and every recursive integration recipe file. If using directory-level commands, still enumerate the files for traceability.

## Medium issues

- **COMP-M-001 — The `slug_image` input field is only handled as a clarification, not in the preserved-field FR.**
  - Location: FR-001, NC-004.
  - Evidence: `input.md:22-26` lists `slug_image` among fields that must remain unchanged. FR-001 enumerates the actual wire fields and omits `slug_image`; NC-004 explains that `slug_image` does not exist and should be dropped. This is probably correct, but reviewers checking input coverage may miss it because the FR itself does not reference the discrepancy.
  - Suggested action: In FR-001, add a short note: "`slug_image` from input is not a current response field; verified absent, so preserving the current response means preserving `slug` and `image` and not adding `slug_image`." Keep NC-004 as rationale.

## Requirement coverage

| Input/review requirement | Spec representation | Completeness verdict |
|---|---|---|
| Enumerate and preserve listed response fields | FR-001 enumerates actual `RecipeSummary` fields and nested organizer/tool fields; NC-004 handles nonexistent `slug_image` | Mostly covered; see COMP-M-001 |
| Enforce "保持响应字段 100% 不变" with explicit assertion seam | US-1/FR-001/SC-002 state it; no concrete executable seam beyond existing tests | Weak; see COMP-H-001 |
| Query count O(N)→O(1) as measurable SC | US-2, FR-009, SC-001 with relative and absolute query bounds | Covered |
| New `tests/integration_tests/test_recipe_list_query_count.py` covered as FR | FR-010 and SC-005 | Covered |
| "API 响应 JSON 字段、顺序、内容、分页行为零变化" reflected | US-1, FR-001, FR-002, SC-002 | Covered in text; assertion seam weak |
| Existing unit/integration/multitenant recipe tests explicitly listed as must-pass | US-3/SC-003 list selected tests and commands, not all files | Incomplete; see COMP-H-002 |

## Summary

Refine once before implementation. The spec already captures the correct SQL-layer approach and measurable query-count criteria, including the new performance test. The remaining completeness work is to make response-shape preservation executable, not just descriptive, and to enumerate the full existing recipe test surface required by input §2.
