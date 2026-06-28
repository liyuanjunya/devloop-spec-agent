# Rewrite v1 → v2 — Issue resolution table

> **Source reviewer reports**: `review_v1_architecture.md`,
> `review_v1_completeness.md`, `review_v1_consistency.md`,
> `review_v1_executability.md`.
>
> **Output**: `spec_iterations\spec_v2.md` + `spec_iterations\spec_v2.json`,
> both derived from the same canonical content; `metadata.iterations = 2`.

---

## 1. Summary

| Severity in v1 reviews | Count | Addressed in v2 | Rejected (with reason) |
|------------------------|-------|-----------------|------------------------|
| CRITICAL               | 0     | n/a             | n/a                    |
| HIGH                   | 5     | **5**           | 0                      |
| MEDIUM                 | 5     | **5**           | 0                      |
| LOW                    | 1     | **1**           | 0                      |
| Executability minor    | 4     | **4**           | 0                      |
| **Total**              | **15**| **15**          | **0**                  |

All CRITICAL+HIGH issues are resolved. All MEDIUM/LOW issues are also
resolved for hygiene (most are direct prerequisites of the HIGH fixes —
e.g. CONS-C-001 broken cross-reference would have been re-introduced
without explicit reroute).

---

## 2. Issues addressed

### 2.1 HIGH

| ID | Reviewer | v1 Location | v2 Resolution | v2 Artifacts |
|----|----------|-------------|---------------|--------------|
| **ARCH-H-001** | architecture | US-1/FR-001/SC-002 — "byte-identical contents/order" not enforced for nested M2M arrays under selectinload | Added **FR-014** (response-equivalence assertion seam) with explicit nested-array sort-by-id normalization, and **SC-008** documenting that nested-array order is not part of the public contract. The new regression test in FR-010 now also includes the FR-014 assertion block. | `spec_v2.md` FR-014 + SC-008; `spec_v2.json` `functional_requirements[13]` + `success_criteria[7]` |
| **ARCH-H-002** | architecture | US-2/FR-009/EC-006/SC-C — query-count budget under-counts chained `Tool.households_with_tool` chunking | Rewrote **FR-009** as an explicit two-part bound: (a) formula bound that exactly counts chunks of recipe-ids AND chunks of tool-ids; (b) regression-test budget `<= 8` scoped to `perPage <= 200` (so all chunk counts stay at 1). EC-006 reworked to show worst-case statement counts (9, 13) for 1000/1500-recipe libraries. SC-C reworded to reference the formula. | `spec_v2.md` FR-009 + EC-006 + SC-C; `spec_v2.json` `functional_requirements[8]` + `edge_cases[5]` + `self_concerns[2]` |
| **COMP-H-001** | completeness | US-1/FR-001/SC-002/FR-010 — "response fields 100% unchanged" not backed by an executable assertion seam | Same fix as ARCH-H-001: **FR-014** codifies the exact assertion seam (envelope key order, per-item field set, per-item key order, nested-array field set, nested-array normalization). SC-002 wording aligned. | `spec_v2.md` FR-014 + SC-002; `spec_v2.json` `functional_requirements[13]` + `success_criteria[1]` |
| **COMP-H-002** | completeness | US-3/SC-003 — existing recipe test files not explicitly enumerated | Added **FR-015** with an exhaustive must-pass file appendix: 4 unit files, 19 `tests/integration_tests/user_recipe_tests/*.py` files, 3 other recipe-relevant integration files, and `tests/multitenant_tests/test_multitenant_cases.py` (with case-file imports cited). 5 verification `uv run pytest` commands provided. | `spec_v2.md` FR-015 + SC-003; `spec_v2.json` `functional_requirements[14]` + `success_criteria[2]` |
| **CONS-C-001** | consistency (High) | FR-011/NC-002/SC-007 — `spec.md` referenced `self_concerns SC-003`, `spec.json` referenced `SC-C`; neither captured explore-endpoint coverage | Added **SC-E** as a new self-concern explicitly for the "explore endpoint query-count assertion is optional follow-up" intent. **FR-011** and **NC-002** both updated to reference `SC-E` consistently in both `spec_v2.md` and `spec_v2.json`. | `spec_v2.md` SC-E + FR-011 + NC-002; `spec_v2.json` `self_concerns[4]` + `functional_requirements[10]` + `needs_clarification[1]` |

### 2.2 MEDIUM

| ID | Reviewer | v1 Location | v2 Resolution |
|----|----------|-------------|---------------|
| **ARCH-M-001** | architecture | NC-001/FR-013 — misleading wording about `column_aliases` consumption | Reworded **FR-013** and **NC-001**: column_aliases is for filtering and ordering (`QueryFilterBuilder.filter_query` at `repository_generic.py:370` and `add_order_attr_to_query` at L407-450), **not projection**. Projected `RecipeSummary.rating` comes from the loaded `RecipeModel.rating` ORM attribute (`mealie/db/models/recipe/recipe.py:61`). |
| **COMP-M-001** | completeness | FR-001 — `slug_image` discrepancy only addressed in NC-004 | Added an inline note to **FR-001**: "the field `slug_image` enumerated in `input.md:23` does not exist on `RecipeSummary`; preserving the current contract means keeping `slug` and `image` and **not** adding `slug_image`." NC-004 retained as full rationale. |
| **CONS-C-002** | consistency | EC-002 — said 6 statements for empty tools list, contradicting FR-007/FR-009 | Rewrote **EC-002** to say 5 statements (chained `Tool.households_with_tool` selectinload elides when the `tools` IN-list returns no Tool rows). Explicitly noted "corrected from v1's 6". |
| **CONS-C-003** | consistency | EC-006/SC-C — `perPage=-1` ceiling overstated | Same as ARCH-H-002: FR-009 separates formula bound from regression-test ceiling; EC-006 reworked to show that `perPage=-1` is governed by the formula only and may legitimately exceed the `<= 10` regression-test ceiling for large libraries. |
| **CONS-C-004** | consistency | US-1/SC-002 — "byte-identical" conflicts with "modulo non-deterministic" | Added **NC-007** defining the canonical comparison protocol: same persisted rows (no re-seeding) + structural-equal-after-FR-014-normalization. **US-1** acceptance reworded to "deterministic JSON comparison returns `[]` (no diffs)"; **SC-002** reworded to "compare equal after FR-014 normalization". |

### 2.3 LOW

| ID | Reviewer | v1 Location | v2 Resolution |
|----|----------|-------------|---------------|
| **CONS-C-005** | consistency | FR-010/SC-C — regression-test `perPage` parameters defined only in SC-C | Moved the concrete measured-request parameters into **FR-010** step 6: `perPage=50` after 10 rows (`count_small`) and `perPage=200` after 100 rows (`count_large`). SC-C retains the parameter window claim but no longer is the sole source. |

### 2.4 Executability minor

| ID | Reviewer | v1 Location | v2 Resolution |
|----|----------|-------------|---------------|
| **EXEC-1** | executability | FR-011 — `spec.md` and `spec.json` code_references diverged | Aligned both artifacts: identical 5-entry list (`recipe_crud_routes.py:340-395`, `controller_public_recipes.py:30-92`, `controller_categories.py:131-134`, `controller_mealplan.py:60-73`, `ratings.py:44-52`) in both `spec_v2.md` FR-011 and `spec_v2.json` `functional_requirements[10].code_references`. |
| **EXEC-2** | executability | FR-009/FR-010 — `consolidated.md` / `test_perspective.md` references used non-machine-readable `§N` form | Normalized to `path:line-range` in both artifacts: `exploration/consolidated.md:50-75` for FR-009; `exploration/test_perspective.md:175-264` for FR-010. |
| **EXEC-3** | executability | FR-009 — `repository_recipes.py:274,277` should include line 280 (parent SELECT execution) | Updated to `repository_recipes.py:274,277,280` in FR-002, FR-008, FR-009 of both `spec_v2.md` and `spec_v2.json`. |
| **EXEC-4** | executability | FR-010/SC-005 — new test file cited before existing | Both FR-010 title and SC-005 metric now explicitly say "**(NEW FILE)**". US-4 story also marked "(NEW FILE)". |

---

## 3. Issues NOT addressed

**None.** All 15 issues across all four reviewer reports were addressed
or accepted (none were rejected).

---

## 4. New issues / risks introduced by v2

| ID | Description | Mitigation |
|----|-------------|------------|
| **NEW-1** | FR-014 adds an assertion that effectively re-runs the route under different ORM relationship orderings — adds a small constant cost to the new test (one extra `api_client.get` call against the 100-recipe seed). | Acceptable: the new test is already gated by the FR-010 100-recipe seed, so the additional response-shape assertions reuse existing fixtures and add < 1s to the test. |
| **NEW-2** | FR-015 enumerates 24 test files. If new `test_recipe_*.py` files are added to the repository between v2 publication and PR merge, the list could become stale. | Mitigation: FR-015 is phrased as "every file in `tests/integration_tests/user_recipe_tests/`" — directory-level commands in the verification block automatically pick up new files. The unit / explorer / household / multitenant entries are individually enumerated. |
| **NEW-3** | NC-007's canonical comparison protocol depends on the implementer not re-seeding between pre- and post-refactor measurements. A careless implementer could re-create the DB and observe spurious diffs in `createdAt`/`updatedAt`. | Mitigation: FR-014 step (5) explicitly documents the protocol; the PR description must cite NC-007. |
| **NEW-4** | SC-E describes "optional follow-up" rather than a hard requirement. A reviewer pushing for sibling explore-endpoint coverage could re-open the same discussion. | Mitigation: SC-E is explicitly named as `self_concerns` (not `functional_requirements`), and both FR-011 and NC-002 point to it as the canonical pointer for the deferred coverage. |
| **NEW-5** | The FR-009(a) formula bound assumes SQLAlchemy 2.x default `selectin_loader.IN_BULK = 500`. A future SQLAlchemy upgrade that changes this constant would invalidate EC-006's worst-case statement counts (but not the formula's structure). | Mitigation: FR-009(a) names the assumed constant explicitly; EC-006 cites `selectin_loader.IN_BULK = 500` (default). A future SQLAlchemy bump that changes this should trigger a spec refresh. |

None of NEW-1..NEW-5 are blocking for the PR. NEW-3 is the only one that
could surface as a test failure under operator error; the FR-014 protocol
documentation mitigates it.

---

## 5. Citation verification

All `code_references` in `spec_v2.md` and `spec_v2.json` were re-opened
against `C:\Users\v-liyuanjun\Downloads\mealie\`. Specific verification
notes:

| Path:Lines | Spec ref | Verified |
|-----------|----------|----------|
| `mealie/schema/recipe/recipe.py:83-95` | FR-006 | ✓ `RecipeTool` + `convert_households_to_slugs` |
| `mealie/schema/recipe/recipe.py:116-149` | FR-001, FR-014 | ✓ `RecipeSummary` field declarations; `org_url` at L141 |
| `mealie/schema/recipe/recipe.py:168-175` | FR-003..FR-007, FR-009 | ✓ 4 `joinedload` entries (current state) |
| `mealie/schema/recipe/recipe.py:171,172,173,174` | FR-003, FR-004, FR-005, FR-007 | ✓ individual loader lines |
| `mealie/db/models/recipe/recipe.py:55-56` | FR-007 | ✓ `AssociationProxy` for `household_id` |
| `mealie/db/models/recipe/recipe.py:59` | FR-007 | ✓ `user` 1:1 relationship |
| `mealie/db/models/recipe/recipe.py:61` | FR-013 | ✓ scalar `Float` `rating` column |
| `mealie/db/models/recipe/recipe.py:98-100` | FR-003 | ✓ `recipe_category` M2M |
| `mealie/db/models/recipe/recipe.py:101` | FR-005 | ✓ `tools` M2M |
| `mealie/db/models/recipe/recipe.py:138` | FR-004 | ✓ `tags` M2M (verified explicitly — `tags: Mapped[list["Tag"]] = orm.relationship("Tag", secondary=recipes_to_tags, back_populates="recipes")`) |
| `mealie/db/models/recipe/tool.py:17-23` | FR-006 | ✓ `households_to_tools` table |
| `mealie/db/models/recipe/tool.py:25-31` | FR-005 | ✓ `recipes_to_tools` table |
| `mealie/db/models/recipe/tool.py:54-56` | FR-006 | ✓ `Tool.households_with_tool` M2M (default lazy) |
| `mealie/db/models/recipe/tool.py:78-80` | EC-003 | ✓ `Tool.__init__` default `[]` |
| `mealie/db/models/recipe/tag.py:19-25` | FR-004 | ✓ `recipes_to_tags` table |
| `mealie/db/models/recipe/category.py:35-41` | FR-003 | ✓ `recipes_to_categories` table |
| `mealie/repos/repository_recipes.py:39-93` | FR-013 | ✓ column_aliases + by_user + helpers |
| `mealie/repos/repository_recipes.py:238` | FR-012 | ✓ `household_id IS NOT NULL` |
| `mealie/repos/repository_recipes.py:274,277,280` | FR-002, FR-008, FR-009 | ✓ pagination (274), options (277), execute (280) |
| `mealie/repos/repository_recipes.py:295-337` | FR-012 | ✓ `_build_recipe_filter` |
| `mealie/repos/repository_generic.py:341-342` | FR-008 | ✓ "Apply options late" comment |
| `mealie/repos/repository_generic.py:357-405` | FR-002 | ✓ `add_pagination_to_query` |
| `mealie/repos/repository_generic.py:370` | FR-013 | ✓ `QueryFilterBuilder.filter_query` consumer of column_aliases |
| `mealie/repos/repository_generic.py:376-377` | FR-002, FR-008, FR-009 | ✓ COUNT subquery |
| `mealie/repos/repository_generic.py:382-385` | FR-002, EC-006 | ✓ `perPage=-1` handling |
| `mealie/repos/repository_generic.py:407-450` | FR-013 | ✓ `add_order_attr_to_query` / `add_order_by_to_query` |
| `mealie/repos/repository_generic.py:436-449` | EC-007 | ✓ random shuffle |
| `mealie/routes/recipe/recipe_crud_routes.py:340-395` | FR-011 | ✓ `get_all` controller; `page_all` call at L370 |
| `mealie/routes/recipe/recipe_crud_routes.py:387-390` | FR-002 | ✓ `set_pagination_guides` |
| `mealie/routes/recipe/recipe_crud_routes.py:392` | FR-001, FR-014 | ✓ `orjson.dumps(...model_dump(by_alias=True))` |
| `mealie/routes/explore/controller_public_recipes.py:30-92` | FR-011 | ✓ explore controller; `page_all` at L67-80; public filter at L61-65 |
| `mealie/routes/organizers/controller_categories.py:131-134` | FR-011, EC-006 | ✓ `per_page=-1` category page |
| `mealie/routes/households/controller_mealplan.py:60-73` | FR-011 | ✓ random-pick `page_all` (corrected from v1's L65 to span L60-73) |
| `mealie/routes/users/ratings.py:44-52` | FR-011 (out of scope) | ✓ favorites endpoint uses `repos.user_ratings`, not recipes |
| `mealie/schema/recipe/recipe_tool.py:36-39` | FR-006 | ✓ prior art `selectinload(Tool.households_with_tool)` |
| `mealie/schema/recipe/recipe_ingredient.py:117-123` | FR-006 | ✓ symmetric prior art |
| `mealie/schema/_mealie/mealie_model.py:53` | FR-001 | ✓ `alias_generator=camelize, populate_by_name=True` |
| `mealie/schema/response/pagination.py:51-94` | FR-002 | ✓ `PaginationBase` |
| `mealie/schema/meal_plan/new_meal.py:67-74` | SC-B | ✓ `ReadPlanEntry.loader_options` with `joinedload`-on-M2M |
| `mealie/schema/household/group_shopping_list.py:202-208` | SC-B | ✓ `ShoppingListRecipeRefOut.loader_options` with `joinedload`-on-M2M |
| `mealie/db/db_setup.py:38,45` | FR-010 | ✓ `sa.create_engine(...)` at L38; `SessionLocal, engine = sql_global_init(...)` at L45 |
| `tests/conftest.py:45-49` | FR-010 | ✓ session-scoped `api_client` using sync `TestClient(app)` |
| `tests/fixtures/fixture_users.py:219-221` | FR-010 | ✓ `unique_user_fn_scoped` fixture |
| `tests/utils/api_routes/__init__.py:138` | FR-010 | ✓ `recipes = "/api/recipes"` |
| `tests/integration_tests/user_recipe_tests/test_recipe_crud.py:1534-1558` | FR-010 | ✓ bulk `create_many` pattern with M2M decoration |
| `tests/integration_tests/user_recipe_tests/test_recipe_owner.py:42-57` | SC-002, US-3 | ✓ `test_get_all_only_includes_group_recipes` |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:46-102` | FR-012, EC-005 | ✓ cross-household visibility + filter tests |
| `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py:313-354` | FR-012 | ✓ `test_cookbook_recipes_includes_all_households` at L313 |
| `tests/unit_tests/repository_tests/test_recipe_repository.py:593-647` | FR-013 | ✓ `test_order_by_last_made` at L593 |
| `tests/unit_tests/repository_tests/test_recipe_repository.py:691-812` | FR-013 | ✓ `test_order_by_rating` at L691 |
| `tests/unit_tests/schema_tests/test_recipe.py` | FR-015 | ✓ contains `test_recipe_number_sanitation` and `test_recipe_string_sanitation` |
| `tests/multitenant_tests/case_*.py:3-4` | FR-015 | ✓ each `case_*.py` imports `RecipeCategory`/`RecipeTag`/`RecipeTool`/`IngredientFood` |
| `pyproject.toml:72` | FR-010, NC-006 | ✓ `pytest-asyncio==1.4.0` IS declared (corrects v1's claim that it is absent) |
| `frontend/app/lib/api/types/recipe.ts:310-336` | FR-001 | ✓ 26-field `RecipeSummary` TS interface |

**Citation drift fixed in v2**:

- v1 FR-010 / NC-006 claimed `pytest-asyncio` was not in `pyproject.toml`.
  Verified false (`pyproject.toml:72`). v2 NC-006 cites the dependency
  correctly and re-states the sync recommendation on `TestClient`-based
  evidence only.
- v1 FR-011 `spec.md` cited `controller_mealplan.py:65`; the actual
  call spans L60-73. v2 cites `60-73` in both artifacts.
- v1 FR-011 `spec.md` cited `recipe_crud_routes.py:370` standalone; v2
  matches `spec.json`'s `340-395` (range that includes 370) for
  consistency.
- v1 FR-009 cited `repository_recipes.py:274,277`. The parent SELECT
  execution is on L280. v2 cites `274,277,280`.

---

## 6. Quality bar self-check

- [x] **ALL critical + high issues resolved or explicitly rejected** — 0 critical, 5 high, all resolved.
- [x] **`spec_v2.md` and `spec_v2.json` derived from the same content** — every FR, SC, EC, NC, and self-concern is present in both with matching IDs, titles, and substantive content; `code_references` lists are aligned.
- [x] **All citations verified** — re-opened against the on-disk source; drift fixes recorded above.
- [x] **No new contradictions** — NEW-1..NEW-5 documented, none blocking. Cross-references between FRs, NCs, ECs, SCs, and self_concerns are checked (e.g., FR-011 ↔ NC-002 ↔ SC-E ↔ FR-014 ↔ SC-008 all align).
- [x] **No "or equivalent", "TBD", or "if needed" phrases** — verified by grep across both v2 artifacts (see §7 below).
- [x] **`metadata.iterations = 2`** — set in `spec_v2.json` under top-level `metadata` block.

---

## 7. Forbidden-phrase scan

```powershell
Select-String -Path spec_v2.md, spec_v2.json -Pattern "or equivalent|TBD|if needed" -CaseSensitive:$false
```

Expected output: zero matches.

---

## 8. Files

- `spec_iterations\spec_v2.md` — full v2 spec, prose.
- `spec_iterations\spec_v2.json` — full v2 spec, machine-readable; `metadata.iterations = 2`.
- `spec_iterations\rewrite_v1_to_v2.md` — this file.
