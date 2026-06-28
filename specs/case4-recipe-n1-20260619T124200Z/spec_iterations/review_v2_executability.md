# Executability Review v2

## Verdict

**PASS with low-priority spec-sync/path-hygiene fixes.** v2 is executable: the implementation seam is specific, the new-test recipe is implementable, the query-count assertions are concrete, and every blocking v1 executability issue is resolved. I found no CRITICAL/HIGH executability blockers.

## Scope checks

| Check | Result |
|---|---|
| `spec_v2.json` parses and `metadata.iterations = 2` | **Pass** |
| All Mealie code/test file paths in JSON `code_references` exist | **Pass** |
| All numeric Mealie line ranges opened and verified | **Pass** |
| `exploration/*.md` line ranges opened and verified | **Pass**, but path base is ambiguous; see EXEC-V2-002 |
| v1 executability issues EXEC-1..EXEC-4 resolved | **Pass** |
| Exact forbidden phrase scan (`or equivalent`, `TBD`, `if needed`) | **Pass**: zero matches |
| New test path marked as new | **Pass**: FR-010/SC-005 say `(NEW FILE)` |

## Findings

### EXEC-V2-001 — LOW — `spec_v2.md` / `spec_v2.json` `code_references` are still not byte-identical

The remaining drift is non-blocking because the cited facts are present and verifiable, but it weakens machine-readability:

1. **FR-001**: JSON includes `mealie/schema/_mealie/mealie_model.py:53`; markdown mentions it in prose at `spec_v2.md:113` but omits it from the FR-001 `code_references` block at `spec_v2.md:120-125`.
2. **FR-010**: JSON includes `pyproject.toml:72`; markdown mentions it in prose at `spec_v2.md:321` but omits it from the FR-010 `code_references` block at `spec_v2.md:325-332`.
3. **FR-013**: JSON uses `mealie/repos/repository_generic.py:407-450`; markdown uses `mealie/repos/repository_generic.py:407-430,432-450` at `spec_v2.md:415-420`. Both are valid, but not identical.
4. **FR-015**: JSON marks appendix files with `line_ranges: all` / `all 19 files`; markdown `code_references` at `spec_v2.md:532-540` lists the same paths without explicit `:all` ranges.

**Suggested fix**: make markdown and JSON code-reference lists mechanically identical for these FRs.

### EXEC-V2-002 — LOW — `exploration/*.md` references use a mixed path base

`spec_v2.md:290` cites `exploration/consolidated.md:50-75`, and `spec_v2.md:332` cites `exploration/test_perspective.md:175-264`. These files do **not** exist under `C:\Users\v-liyuanjun\Downloads\mealie\` and are not relative to `spec_iterations\`; they exist under the case root:

- `C:\Users\v-liyuanjun\source\repos\devloop\specs\case4-recipe-n1-20260619T124200Z\exploration\consolidated.md:50-75`
- `C:\Users\v-liyuanjun\source\repos\devloop\specs\case4-recipe-n1-20260619T124200Z\exploration\test_perspective.md:175-264`

**Suggested fix**: either document the path base as the case root or cite these as `..\exploration\...` from `spec_iterations\`.

### EXEC-V2-003 — LOW — Forbidden-phrase scan has a near-miss

The exact scan for `or equivalent|TBD|if needed` is clean, but `spec_v2.md:476-477` says `task py:test (or equivalently the listed uv run pytest commands)`. This is executable because the five exact commands are listed at `spec_v2.md:522-528`, so it is not blocking. For hygiene, prefer `task py:test; alternatively, run exactly the five listed commands`.

## Verified key line ranges

| Reference | Verification |
|---|---|
| `mealie/schema/recipe/recipe.py:83-95` | `RecipeTool.households_with_tool` and validator that iterates household slugs |
| `mealie/schema/recipe/recipe.py:116-149` | `RecipeSummary` field declaration order and `orgURL` alias |
| `mealie/schema/recipe/recipe.py:168-175` | Current `loader_options()` contains three M2M `joinedload`s plus user `joinedload` |
| `mealie/repos/repository_recipes.py:274,277,280` | Pagination first, loader options late, then parent SELECT execution |
| `mealie/repos/repository_generic.py:357-405` | count, `perPage=-1`, `page=-1`, limit/offset behavior |
| `mealie/repos/repository_generic.py:407-450` | `column_aliases` ordering path and random-order extra execute |
| `mealie/routes/recipe/recipe_crud_routes.py:340-395` | `/api/recipes` controller, `page_all`, pagination guides, serialization |
| `mealie/routes/explore/controller_public_recipes.py:30-92` | explore endpoint uses shared `page_all` path |
| `mealie/routes/households/controller_mealplan.py:60-73` | random-pick `cross_household_recipes.page_all` call |
| `tests/integration_tests/user_recipe_tests/` | exactly 19 `test_recipe_*.py` files on disk |
| `exploration/consolidated.md:50-75` | current/target query trace and six-statement target |
| `exploration/test_perspective.md:175-264` | concrete new-test scaffolding |

## v1 executability issue resolution

| v1 issue | v2 status |
|---|---|
| EXEC-1 FR-011 md/json mismatch | **Resolved** for FR-011: both artifacts list the same five references |
| EXEC-2 non-machine-readable `§N` references | **Resolved** for the two load-bearing references: now `path:line-range` |
| EXEC-3 missing `repository_recipes.py:280` | **Resolved** in FR-002/FR-008/FR-009 |
| EXEC-4 new test path cited before existing | **Resolved**: `(NEW FILE)` is explicit |

## Bottom line

No blocker prevents implementation. Address EXEC-V2-001/002 before handing to automation that expects identical `code_references` or a single path base; otherwise v2 is ready for implementation.
