# Executability Review v1

## Verdict
**PASS with minor citation/spec-sync fixes required.** The implementation seam is executable: the target files exist, the core `RecipeSummary.loader_options()` line references are accurate and pinned, the query-count threshold is assertable, and no TBD / "or equivalent" / "if needed" placeholders were found.

## Scope checks

| Check | Result |
|---|---|
| All cited existing file paths real | **Pass**, except proposed new test path `tests/integration_tests/test_recipe_list_query_count.py` does not exist yet by design. |
| All cited line ranges opened and symbol verified | **Pass** for code references; minor imprecisions below. |
| `spec.md` / `spec.json` `code_references` identical for each FR | **Fail** for FR-009, FR-010, FR-011. |
| TBD / "or equivalent" / "if needed" phrases | **Pass**: none found in `spec.md` or `spec.json`. |
| Query-count threshold specific enough for assertion | **Pass**: relative `count_large <= count_small + 3` plus absolute `<= 10`; typical `<= 8` is documented but test should assert the absolute bound. |
| `loader_options` changes pinned to specific lines | **Pass**: FR-003..FR-007 cite exact current lines `recipe.py:171-174`; FR-009 cites `168-175`. |

## Wrong/imprecise citations

1. **FR-011 `spec.md` vs `spec.json` mismatch.**
   - `spec.md` code references: `recipe_crud_routes.py:370`, `controller_public_recipes.py:67-80`, `controller_categories.py:131-134`, `controller_mealplan.py:65`.
   - `spec.json` code references: broader `recipe_crud_routes.py:340-395`, `controller_public_recipes.py:30-92`, same category/mealplan refs, plus `routes/users/ratings.py:44-52`.
   - Fix: make the lists identical. Prefer adding `ratings.py:44-52` to `spec.md` if the out-of-scope negative reference is intentional, or remove it from JSON.

2. **FR-009 / FR-010 `spec.md` omit section ranges used by JSON.**
   - JSON uses `exploration/consolidated.md` with `line_ranges: "see §3"` and `exploration/test_perspective.md` with `line_ranges: "see §7"`.
   - Markdown cites `exploration\consolidated.md §3` and `exploration\test_perspective.md §7` outside a machine-readable `path:range` form.
   - Fix: normalize both to the same path + range representation.

3. **FR-009 `repository_recipes.py:274,277` note is slightly imprecise.**
   - Lines 274 and 277 verify pagination and loader-option ordering, but the parent SELECT is executed at line 280.
   - Fix note to `274,277,280` if the citation is meant to support "COUNT + parent SELECT".

4. **`tests/integration_tests/test_recipe_list_query_count.py` is cited before it exists.**
   - This is acceptable for FR-010/SC-005 as a required new file, but it is not a real on-disk path pre-implementation. Mark it explicitly as "new file to add" wherever cited.

## Verified key citations

- `mealie/schema/recipe/recipe.py:168-175`: current loader_options has `joinedload(recipe_category)`, `joinedload(tags)`, `joinedload(tools)`, and `joinedload(user).load_only(User.household_id)`.
- `mealie/db/models/recipe/tool.py:17-23,54-56`: `households_to_tools` table and default-lazy `Tool.households_with_tool` relationship are present.
- `mealie/repos/repository_generic.py:357-405`: count, `perPage=-1`, `page=-1`, limit/offset behavior verified.
- `mealie/repos/repository_recipes.py:238,274,277,280,295-337`: multi-tenant filter and apply-options-late invariant verified.
- `mealie/routes/recipe/recipe_crud_routes.py:387-392`: pagination guides and `model_dump(by_alias=True)` serialization verified.
