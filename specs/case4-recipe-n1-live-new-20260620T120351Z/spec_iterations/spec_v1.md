# Spec v1 — Recipe List N+1 Performance Refactor on Mealie (NEW pipeline)

> Case ID: `case4-recipe-n1-live-new-20260620T120351Z` · Intent: `perf_opt` · Scope: `repo, schema, service, test` · Iteration: v1

---

## Intent

Refactor Mealie's recipe list endpoint (`GET /api/recipes`) to eliminate N+1 query growth: keep the response payload identical (top-level fields, declaration order, aliases, pagination envelope, nested array contents as a set) while making the SQL query count constant in the number of returned recipes. Achieve via SQLAlchemy eager-loading (chained `selectinload`) on the `RecipeSummary.loader_options()` seam. Add two new sync `def` tests — one for query-count regression, one for nested-shape preservation.

This is the **NEW pipeline v1** run with all 19 v7 defenses, with explicit application of:
- **A3 perf_opt**: quantified target (FR-009), behavior-preservation test (FR-014), nested-array-order trap defense (SC-E + NC-007).
- **C3**: performance perspective auto-added — already in `exploration/consolidated.md`.

## Selected approach

**Conservative — single-seam loader-options refactor.** Edit `mealie/schema/recipe/recipe.py:168-175` only. Swap 3× `joinedload` → `selectinload` on M2M collections (`recipe_category`, `tags`, `tools`), chain `selectinload(Tool.households_with_tool)` off the tools loader, keep `joinedload(RecipeModel.user).load_only(User.household_id)` unchanged (load-bearing for the AssociationProxy `household_id`). Add two test files. Transitively benefits every caller of `RepositoryRecipes.page_all` and every consumer of `RecipeSummary.loader_options()` — including the `/api/explore/groups/{slug}/recipes` public route.

**Non-actions** (encoded as guard rails):
- Does **NOT** modify `RepositoryRecipes.page_all` body.
- Does **NOT** touch `_get_rating_col_alias`, `_get_last_made_col_alias`, `column_aliases`.
- Does **NOT** remove `.scalars().unique().all()` at `repository_recipes.py:280` (FR-008).
- Does **NOT** add any new field to `RecipeSummary` (preserves "响应字段 100% 不变").
- Does **NOT** add an alembic migration.
- Does **NOT** add `order_by=...` to any M2M relationship.
- Does **NOT** patch the two adjacent loader sites (`ReadPlanEntry`, `ShoppingListRecipeRefOut`) — out of strict scope.
- Does **NOT** add any application-layer cache.
- Does **NOT** use `lazy='dynamic'` or any "hide-the-query" trick.

**Files**:
- Modified: `mealie/schema/recipe/recipe.py`
- Added: `tests/integration_tests/test_recipe_list_query_count.py`, `tests/integration_tests/test_recipe_list_response_shape.py`

---

## User Stories

### US-1 (P1) — Response wire-shape preservation

**As a** Mealie maintainer, **I want** the `GET /api/recipes` JSON response — field set, declaration order, camelCase aliases (orgURL special-case), pagination envelope, nested array contents (`recipeCategory[]`, `tags[]`, `tools[]`, `tools[*].householdsWithTool[]`) — to be identical to the pre-refactor baseline **so that** existing UI consumers (RecipeCard, RecipeCardMobile, RecipeCardSection, RecipeDialogSearch) and generated TypeScript types keep working without regeneration.

**Acceptance**: Normalized JSON diff between pre- and post-refactor responses returns `{}` after masking documented volatile fields (`createdAt`, `updatedAt`, random UUIDs). Covered by FR-001, FR-002, FR-014, SC-002, SC-008.

### US-2 (P1) — Constant query count

**As a** Mealie maintainer, **I want** the SQL statement count emitted by `GET /api/recipes` to be a small constant **so that** page latency stops scaling linearly with library size.

**Acceptance**: `count(queries for 100 recipes) <= count(queries for 10 recipes) + 3` AND `count(queries for 100 recipes) <= 8 typical / <= 10 absolute` under the spec's seeding profile and `perPage <= 200`. Covered by FR-003..FR-006, FR-009, SC-001, SC-005.

### US-3 (P1) — Existing test surface untouched

**As a** Mealie maintainer, **I want** every existing unit, integration, and recipe-related multi-tenant test to pass without modification **so that** the project's 537-test baseline is preserved.

**Acceptance**: `uv run task py:test` exits 0; no skips/xfails/warnings added. Covered by FR-013, SC-003.

### US-4 (P1) — Query-count regression test

**As a** Mealie maintainer, **I want** a new test that arms a SQLAlchemy `before_cursor_execute` listener and asserts the query count does not grow with N **so that** a future careless re-introduction of `joinedload` on M2M or a missing chained `selectinload` fails CI deterministically.

**Acceptance**: `uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v` passes. Sync `def`; `unique_user_fn_scoped`; warm-up; `try/finally event.remove`; measured `perPage=50` after 10 recipes and `perPage=200` after 100 recipes. Covered by FR-010, SC-005.

### US-5 (P2) — Nested array shape preservation

**As a** Mealie maintainer, **I want** a behavior-preservation test that verifies nested arrays (`recipeCategory[]`, `tags[]`, `tools[]`, `tools[*].householdsWithTool[]`) preserve element identity-set parity post-refactor **so that** the selectinload-vs-joinedload nested-array-order trap is defended.

**Acceptance**: `uv run pytest tests/integration_tests/test_recipe_list_response_shape.py -v` passes. Covered by FR-014, SC-008.

---

## Functional Requirements

| ID | Title | Summary |
|---|---|---|
| **FR-001** | Preserve exact `RecipeSummary` top-level field set, declaration order, aliases | 26 wire fields locked. `orgURL` is a special-cased alias (NOT `orgUrl`). `slug_image` (input typo) is NOT added. |
| **FR-002** | Preserve pagination envelope and 'apply options late' invariant | `page, perPage, total, totalPages, items, next, previous`. Loader options attached AFTER `add_pagination_to_query` (commit 7b325082 regression guard). |
| **FR-003** | Eager-load `recipe_category` via `selectinload` | Replaces `joinedload(RecipeModel.recipe_category)` at `recipe.py:171`. |
| **FR-004** | Eager-load `tags` via `selectinload` | Replaces `joinedload(RecipeModel.tags)` at `recipe.py:172`. |
| **FR-005** | Eager-load `tools` via `selectinload` | Replaces `joinedload(RecipeModel.tools)` at `recipe.py:173`. Must be chained per FR-006. |
| **FR-006** | Chain `selectinload(Tool.households_with_tool)` off tools loader | `selectinload(RecipeModel.tools).selectinload(Tool.households_with_tool)`. Eliminates the dominant N+1 from `RecipeTool.convert_households_to_slugs`. |
| **FR-007** | Preserve `joinedload(RecipeModel.user).load_only(User.household_id)` | Load-bearing for the `household_id` AssociationProxy. KEEP unchanged with explanatory comment. |
| **FR-008** | Keep `.scalars().unique().all()` at `repository_recipes.py:280` | Regression guard for future loader-graph changes. Becomes no-op but cheap. |
| **FR-009** | Query-count bound is a small constant | Relative: `count_large <= count_small + 3`. Absolute: `<= 8 typical / <= 10 absolute` for `perPage <= 200`. Minimum provable: 6. |
| **FR-010** | New `tests/integration_tests/test_recipe_list_query_count.py` (sync) | Detailed scaffolding: imports `engine`, uses `unique_user_fn_scoped`, seeds 10 then +90, warm-up, `try/finally event.remove`, measures `perPage=50` and `perPage=200`. |
| **FR-011** | Shared loader benefits adjacent endpoints | `/api/recipes` + `/api/explore/groups/{slug}/recipes`. NOT `/api/users/{id}/favorites`. |
| **FR-012** | Multi-tenant safety preserved | `household_id IS NOT NULL` + `_build_recipe_filter` chain remain on parent SELECT. `selectinload` adds no JOINs to parent. |
| **FR-013** | Explicit must-pass test enumeration | Unit + integration + cross-household + explore + migrations + group-recipe-actions. Project baseline 537 tests. |
| **FR-014** | Behavior-preservation test (`test_recipe_list_response_shape.py`) | Defends nested-array-order trap. Asserts (a) top-level key list-equality, (b) nested M2M id-set equality, (c) `householdsWithTool` set equality, (d) docstring records order semantics per NC-007. |
| **FR-015** | PR description must document before/after data | Query-count delta + EXPLAIN ANALYZE + "no migration" rationale + "no frontend types regenerated" pre-empt. |

(Full descriptions, code references, and rationale in `spec_v1.json`.)

---

## Success Criteria

| ID | Title | Metric | Verification |
|---|---|---|---|
| **SC-001** | Query-count growth bounded | `count_large - count_small <= 3` | `uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v` exits 0 |
| **SC-002** | Response top-level shape preserved | Normalized JSON diff `{}` | Existing tests + FR-014's `test_recipe_list_response_shape.py` |
| **SC-003** | Existing 537 tests pass unchanged | `uv run task py:test` exit 0 | No skips/xfails/warnings added |
| **SC-004** | Latency improvement documented | PR has before/after counts + EXPLAIN ANALYZE | PR description fenced-code-block |
| **SC-005** | New query-count regression test exists and passes | Sync `def`, collected, exits 0 | `uv run pytest tests/integration_tests/test_recipe_list_query_count.py -v` |
| **SC-006** | No new SAWarnings | Pre/post SAWarning count equal | `Select-String -Pattern 'SAWarning' \| Measure-Object -Line` |
| **SC-007** | Explore endpoint inherits fix (no duplication) | Single `selectinload(Tool.households_with_tool)` in `recipe.py` + prior art only | `grep -rn` shows no duplicate in `routes/explore/` |
| **SC-008** | Nested array shape preserved | `test_recipe_list_response_shape.py` passes | Sync `def`, FR-014 contract |

---

## Edge Cases

- **EC-001** — Empty recipe list → ~2 statements (COUNT returns 0, parent returns 0, follow-ups elided).
- **EC-002** — Single recipe with no organizers/tools → 5 statements (chained households selectinload elided when tools IN-list empty).
- **EC-003** — Tools without households → 6 statements (chained selectinload fires once with empty result).
- **EC-004** — Orphan FK in M2M secondary tables → no new failure modes; cascade is SQLAlchemy session-level.
- **EC-005** — Multi-tenant cross-household within same group → preserved by FR-012; verified by `test_recipe_cross_household.py:46-102`.
- **EC-006** — `perPage=-1` chunking → formula `2 + k_cat + k_tag + k_tool + k_households` (each `k_X = ceil(IDs/500)`). Absolute `<= 10` scoped to `perPage <= 200`. SC-C documents.
- **EC-007** — `orderBy=random` → +1 cursor execute. Not exercised by regression test.
- **EC-008** — `orderBy=lastMade` / `rating` → zero extra executes (correlated subqueries).
- **EC-009** — `search=` param → filter on parent SELECT; selectinload follow-ups only see filtered IDs.

---

## Needs Clarification (resolved)

| ID | Question | Resolution (one-line) |
|---|---|---|
| **NC-001** | Is `rating` aggregate? | Scalar column; correlated subquery used only for sort/filter. No aggregate denormalization. |
| **NC-002** | Scope: only `/api/recipes`? | Seam fixes both `/api/recipes` and `/api/explore/groups/.../recipes`; favorites out of scope. |
| **NC-003** | `count <= 5` from input? | Provably 6 minimum; ceiling relaxed to `<= 8 typical / <= 10 absolute`. |
| **NC-004** | `slug_image` field? | Does not exist; treat as typo for `slug + image`. |
| **NC-005** | `comments_count` N+1? | No comments field exists; adding it would violate FR-001. |
| **NC-006** | Async test? | No — sync `def`. Mealie suite is fully synchronous. |
| **NC-007** | Nested array order under selectinload? | **Set-equal, not list-equal** — no `order_by` on M2M relationships; adding one out of scope; FR-014 asserts set-equal with documented rationale. **A3 perf_opt nested-order trap defense.** |
| **NC-008** | `tests/multitenant_tests/` recipe tests? | None by name; recipe multi-tenancy is `test_recipe_cross_household.py`. |

---

## Self-Concerns

| ID | Concern | Mitigation |
|---|---|---|
| **SC-A** | Reviewers may not connect fix to literal N+1 framing | FR-015 PR description traces N+1 from validator → relationship → per-tool SQL. |
| **SC-B** | Adjacent `ReadPlanEntry` / `ShoppingListRecipeRefOut` retain the anti-pattern | Out-of-scope follow-ups documented in PR. |
| **SC-C** | Chunking caveat for large pages | EC-006 + FR-009 scoping; regression test uses `perPage <= 200`. |
| **SC-D** | `task dev:generate` reflex regenerates frontend types | FR-015 pre-empts: "no Pydantic field changed → no TS regeneration expected". |
| **SC-E** | **selectinload-vs-joinedload nested-array-order subtle break (A3 perf_opt trap)** | FR-014 set-equal assertion + NC-007 explicit resolution + test docstring records semantics. |

---

## V7 Defenses Addressed

This spec applies the new pipeline's v7 defenses with explicit emphasis on the **A3 perf_opt** rule:

| Defense | Where addressed |
|---|---|
| **A3 perf_opt: quantified target** | FR-009 (relative + absolute bounds with explicit minimum) |
| **A3 perf_opt: behavior-preservation test** | FR-014 (`test_recipe_list_response_shape.py`) + SC-002 + SC-008 |
| **A3 perf_opt: nested-array-order subtle break** | SC-E + NC-007 + FR-014(f) set-equal-with-rationale |
| **C3: performance perspective auto-added** | Already in `exploration/consolidated.md` (`data_perspective`, `api_perspective`, `test_perspective`, `history_perspective`, `ui_perspective` cover the perf angle) |
| Executable response-shape assertion seam | FR-014 (list-equal on top-level keys + set-equal on nested) |
| Existing test surface enumeration | FR-013 explicit file list + verification commands |
| `spec.md` / `spec.json` consistency | Single source = `spec_v1.json`; this `.md` is a derived summary |
| No `TBD` / `or equivalent` / `if needed` placeholders | All FRs pinned to specific lines/files; all SCs have explicit verification commands |
| Chunking-aware bound scoping | EC-006 + FR-009 + SC-C documents `perPage <= 200` scope + formula for larger pages |
| Multi-tenant isolation explicit | FR-012 + EC-005 + cite of `d02023e1` security commit |
