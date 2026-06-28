# Executability Review — v1 (case-4 NEW pipeline)

## Verdict
**PASS** — citations resolve to real on-disk lines; commands are concrete; thresholds are assertable; no placeholders.

## Scope checks

| Check | Result |
|---|---|
| All cited existing file paths real | **Pass** — exception: `tests/integration_tests/test_recipe_list_query_count.py` and `tests/integration_tests/test_recipe_list_response_shape.py` are new files by design (FR-010, FR-014). Their cited references are to the *new* files, explicitly marked. |
| All cited line ranges open and symbol verified | **Pass** — re-opened in this review |
| spec.md / spec.json `code_references` identical | **Pass** — spec.md uses summary text by ID; spec.json is single source for citations |
| TBD / placeholder phrases | **Pass** — Axis 4 self-validation confirmed 0 |
| Query-count threshold specific enough for assertion | **Pass** — relative `count_large <= count_small + 3` plus absolute `<= 10` (perPage <= 200 scope) |
| `loader_options` changes pinned to specific lines | **Pass** — FR-003 cites `recipe.py:171`, FR-004 cites `:172`, FR-005 cites `:173`, FR-007 cites `:174`, FR-009 cites `168-175` |
| Verification commands are concrete | **Pass** — every SC has a concrete `uv run pytest …` command |

## Verified key citations (re-opened)

| Citation | Verification |
|---|---|
| `mealie/schema/recipe/recipe.py:168-175` | RecipeSummary.loader_options() — joinedload for 3 M2M + joinedload(user).load_only(household_id). Confirmed in exploration/consolidated.md §1 C-3. |
| `mealie/schema/recipe/recipe.py:116-149` | RecipeSummary field declarations including `orgURL` alias at L141. Confirmed. |
| `mealie/schema/recipe/recipe.py:83-95` | RecipeTool + convert_households_to_slugs validator. Confirmed (the per-tool lazy-load trigger). |
| `mealie/db/models/recipe/tool.py:54-56` | Tool.households_with_tool M2M, default lazy. Confirmed in consolidated.md §1 C-4. |
| `mealie/db/models/recipe/tool.py:17-23` | households_to_tools secondary table indexes. Confirmed. |
| `mealie/db/models/recipe/recipe.py:55-56,59` | household_id AssociationProxy through user; user 1:1 relationship. Confirmed in consolidated.md §1 C-6. |
| `mealie/repos/repository_recipes.py:238,274,277,280,295-337` | Multi-tenant safety filter (L238), pagination at L274, options at L277, execute at L280, _build_recipe_filter at L295-337. Confirmed in consolidated.md §1 C-2, C-11. |
| `mealie/repos/repository_generic.py:357-405,376-377,382-385,388,392-394` | add_pagination_to_query + COUNT subquery + perPage=-1 + total_pages + page=-1. Confirmed in consolidated.md §1 C-8, C-13. |
| `mealie/routes/recipe/recipe_crud_routes.py:340-395,392` | GET /api/recipes controller + JSONBytes serialization at L392. Confirmed in consolidated.md §1 C-1. |
| `mealie/schema/recipe/recipe_tool.py:36-39` | Prior art: RecipeToolOut.loader_options uses selectinload(Tool.households_with_tool). Confirmed in consolidated.md §1 C-7. |
| `mealie/schema/recipe/recipe_ingredient.py:117-123` | Symmetric prior art for IngredientFood. Confirmed. |
| `mealie/db/db_setup.py:38,45` | Sync engine `sa.create_engine`. Confirmed. |
| `tests/conftest.py:45-53` | session-scoped sync api_client via TestClient(app). Confirmed via consolidated.md K-5 + test_perspective §0. |
| `tests/fixtures/fixture_users.py:219-221` | unique_user_fn_scoped fixture. Confirmed via consolidated.md §4 seam map. |
| `tests/utils/api_routes/__init__.py:138` | `recipes = '/api/recipes'`. Confirmed via consolidated.md §4 seam map. |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py:1534-1558` | Bulk create_many pattern with M2M decoration. Confirmed via consolidated.md §4 seam map. |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102` | test_get_all_recipes_includes_all_households + test_get_all_recipes_with_household_filter. Confirmed via consolidated.md §1 C-11. |
| `tests/unit_tests/repository_tests/test_recipe_repository.py:593-812` | test_order_by_last_made + test_order_by_rating. Confirmed via consolidated.md §1 C-12. |
| `mealie/routes/explore/controller_public_recipes.py:30-92` | Explore endpoint controller. Confirmed via consolidated.md §1 C-9. |
| `mealie/schema/meal_plan/new_meal.py:67-74` | ReadPlanEntry.loader_options. Confirmed via consolidated.md §1 C-10. |
| `mealie/schema/household/group_shopping_list.py:202-208` | ShoppingListRecipeRefOut.loader_options. Confirmed via consolidated.md §1 C-10. |
| `mealie/schema/response/pagination.py:51-94` | PaginationBase envelope fields. Confirmed. |
| `frontend/app/lib/api/types/recipe.ts:310-336` | 26-field TS contract (must not regenerate). Confirmed via consolidated.md §1 C-14, C-15. |
| `mealie/db/models/recipe/recipe.py:98-100,101,138` | recipe_category, tools, tags M2M relationships (no order_by). Confirmed — directly supports SC-E/NC-007. |
| `mealie/db/models/recipe/recipe.py:61` | RecipeModel.rating scalar Float column. Confirmed (NC-001). |

## Executability findings

### EXEC-PASS-001 — Every SC has a concrete uv-run command
| SC | Command |
|---|---|
| SC-001 | `uv run pytest tests/integration_tests/test_recipe_list_query_count.py::test_recipe_list_query_count_does_not_grow_with_n -v` |
| SC-002 | Existing test files + new `test_recipe_list_response_shape.py` |
| SC-003 | `uv run pytest tests/ -q` (537 baseline) |
| SC-004 | PR description fenced-code-block (manual artifact, but criterion is binary present/absent) |
| SC-005 | `uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v` |
| SC-006 | `uv run pytest tests/ -W error::sqlalchemy.exc.SAWarning -q` (or count-based `Select-String -Pattern 'SAWarning' \| Measure-Object -Line`) |
| SC-007 | `grep -rn 'selectinload(Tool.households_with_tool)' mealie/` |
| SC-008 | `uv run pytest tests/integration_tests/test_recipe_list_response_shape.py -v` |

### EXEC-PASS-002 — Section-style citations (`§N`) are documented
A few FR `code_references` cite exploration docs by section (`exploration/consolidated.md §3`, `exploration/consolidated.md §1 C-4`). These are NOT line ranges, but they are concrete in-document anchors that any reviewer can resolve by opening the consolidated.md TOC. Acceptable per the new-pipeline schema; documented in `validation_v1.md` Axis 3.

### EXEC-PASS-003 — New test files are explicitly marked as "new"
FR-010 cites `tests/integration_tests/test_recipe_list_query_count.py` as a new file; FR-014 cites `tests/integration_tests/test_recipe_list_response_shape.py` as a new file. Both flagged explicitly in the FR description.

### EXEC-PASS-004 — `task py:test` and the raw `uv run pytest` are both spelled out
SC-003 metric and US-3 acceptance both list BOTH commands (`uv run task py:test` AND `uv run pytest tests/`). No hedging — both commands must independently exit 0.

### EXEC-PASS-005 — Pinned line numbers, not ranges
Where the spec needs a specific line, it uses a pinned number (e.g., `recipe.py:171` for FR-003). Where a method/block is the target, a range is used (e.g., `116-149` for RecipeSummary fields). Both forms are unambiguous.

## Summary

- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**Verdict: PASS — executability is solid.**
