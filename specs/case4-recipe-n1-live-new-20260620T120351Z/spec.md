# Spec v2 — Recipe List N+1 Performance Refactor on Mealie (NEW pipeline)

> Case ID: `case4-recipe-n1-live-new-20260620T120351Z` · Intent: `perf_opt` · Scope: `repo, schema, service, test` · Iteration: **v2 (precision polish over v1)**

---

## V2 changes vs V1 (summary)

V1 passed all 4 review axes + A3 perf_opt rule with **0 findings**. V2 is a precision-polish iteration applying seven additive improvements; **no semantic regression**.

| # | Change | Where | Why |
|---|---|---|---|
| 1 | Verbatim test skeleton | FR-010 description | Paste-and-fill executability for the query-count regression test |
| 2 | EXPECTED_KEYS Python literal + test skeleton | FR-014 description | One-glance contract reference for the shape test |
| 3 | DBMS × loader-strategy matrix | NC-007 resolution | Cross-DBMS clarity on set-equal vs list-equal decision |
| 4 | SC-006 verification reformed | SC-006 | Count-diff primary; escalation fallback (avoids unrelated SAWarning noise) |
| 5 | EC-006 chunking formula keyed | EC-006 expected | `k_households` chunks by `Tool.id` count, NOT `recipe.id` count — important caveat |
| 6 | New EC-010 | edge_cases | SQLAlchemy expire-on-commit + selectinload interaction; warm-up sequence rationale |
| 7 | New SC-009 | success_criteria | Executable "no alembic migration" verification command |

Counts: FR=15 (same), SC=**9** (+1), EC=**10** (+1), NC=8 (same), US=5 (same), Self-concerns=5 (same).

---

## Intent (unchanged from v1)

Refactor Mealie's recipe list endpoint (`GET /api/recipes`) to eliminate N+1 query growth: keep the response payload identical (top-level fields, declaration order, aliases, pagination envelope, nested array contents as a set) while making the SQL query count constant in the number of returned recipes. Achieve via SQLAlchemy eager-loading (chained `selectinload`) on the `RecipeSummary.loader_options()` seam. Add two new sync `def` tests — one for query-count regression, one for nested-shape preservation.

**V7 defenses still applied** (A3 perf_opt: quantified target FR-009, behavior-preservation test FR-014, nested-array-order trap defense SC-E + NC-007; C3: performance perspective in `exploration/consolidated.md`).

## Selected approach (unchanged from v1)

Conservative — single-seam loader-options refactor. Edit `mealie/schema/recipe/recipe.py:168-175` only. Add two test files.

**Non-actions** identical to v1.

**Files**:
- Modified: `mealie/schema/recipe/recipe.py`
- Added: `tests/integration_tests/test_recipe_list_query_count.py`, `tests/integration_tests/test_recipe_list_response_shape.py`

---

## User Stories (unchanged from v1)

| ID | Priority | Summary |
|---|---|---|
| **US-1** | P1 | Response wire-shape preservation (normalized JSON diff = {}) |
| **US-2** | P1 | Constant query count (relative + absolute bounds) |
| **US-3** | P1 | Existing 537 tests pass unchanged |
| **US-4** | P1 | New query-count regression test |
| **US-5** | P2 | Nested array shape preservation test |

---

## Functional Requirements

| ID | Title | Summary |
|---|---|---|
| **FR-001** | Preserve exact `RecipeSummary` top-level field set, declaration order, aliases | 26 wire fields locked. `orgURL` is a special-cased alias. `slug_image` (input typo) is NOT added. |
| **FR-002** | Preserve pagination envelope and 'apply options late' invariant | `page, perPage, total, totalPages, items, next, previous`. Loader options attached AFTER `add_pagination_to_query`. |
| **FR-003** | Eager-load `recipe_category` via `selectinload` | Replaces `joinedload(RecipeModel.recipe_category)` at `recipe.py:171`. |
| **FR-004** | Eager-load `tags` via `selectinload` | Replaces `joinedload(RecipeModel.tags)` at `recipe.py:172`. |
| **FR-005** | Eager-load `tools` via `selectinload` | Replaces `joinedload(RecipeModel.tools)` at `recipe.py:173`. Must be chained per FR-006. |
| **FR-006** | Chain `selectinload(Tool.households_with_tool)` off tools loader | Eliminates dominant N+1. |
| **FR-007** | Preserve `joinedload(RecipeModel.user).load_only(User.household_id)` | Load-bearing for `household_id` AssociationProxy. |
| **FR-008** | Keep `.scalars().unique().all()` at `repository_recipes.py:280` | Regression guard. |
| **FR-009** | Query-count bound is a small constant | Relative: `count_large <= count_small + 3`. Absolute: `<= 10` for `perPage <= 200`. |
| **FR-010** | New `test_recipe_list_query_count.py` (sync) | **V2: includes verbatim Python skeleton for paste-and-fill.** |
| **FR-011** | Shared loader benefits adjacent endpoints | `/api/recipes` + `/api/explore/groups/{slug}/recipes`. |
| **FR-012** | Multi-tenant safety preserved | `household_id IS NOT NULL` + `_build_recipe_filter` on parent SELECT. |
| **FR-013** | Explicit must-pass test enumeration | Project baseline 537 tests. |
| **FR-014** | Behavior-preservation test (`test_recipe_list_response_shape.py`) | **V2: includes EXPECTED_KEYS literal + verbatim test skeleton.** |
| **FR-015** | PR description must document before/after data | Query-count delta + EXPLAIN ANALYZE + "no migration" + "no frontend types regenerated". |

(Full descriptions, code references, and rationale in `spec_v2.json`.)

---

## Success Criteria

| ID | Title |
|---|---|
| **SC-001** | Query-count growth bounded |
| **SC-002** | Response top-level shape preserved (normalized JSON diff = {}) |
| **SC-003** | Existing 537 tests pass unchanged |
| **SC-004** | Latency improvement documented in PR |
| **SC-005** | New query-count regression test passes |
| **SC-006** | No new SAWarnings (**V2: count-diff primary, strict escalation fallback**) |
| **SC-007** | Explore endpoint inherits fix (no code duplication) |
| **SC-008** | Nested array shape preserved (FR-014 test passes) |
| **SC-009** | **NEW — No alembic migration is added** (executable verification: `git diff main --name-only -- mealie/alembic/versions/` returns empty) |

---

## Edge Cases

| ID | Title |
|---|---|
| **EC-001** | Empty recipe list (~2 statements) |
| **EC-002** | Single recipe, no organizers, no tools (5 statements typical) |
| **EC-003** | Tools without households (6 statements) |
| **EC-004** | Orphan FK in M2M secondary tables (no new failure modes) |
| **EC-005** | Multi-tenant cross-household within same group (preserved) |
| **EC-006** | `perPage=-1` chunking (**V2: keyed formula** — `k_households = ceil(distinct_tool_ids/500)`, NOT recipe-id-keyed) |
| **EC-007** | `orderBy=random` (+1 statement) |
| **EC-008** | `orderBy=lastMade` / `rating` (zero extra) |
| **EC-009** | `search=` filter (filter on parent SELECT) |
| **EC-010** | **NEW — SQLAlchemy `expire_on_commit` interaction with selectinload** — warm-up GET absorbs incidental refresh queries; chained selectinload does not fire per-attribute |

---

## Needs Clarification

| ID | Question | Resolution |
|---|---|---|
| **NC-001** | `rating` aggregate? | Scalar column; correlated subquery used only for sort/filter. |
| **NC-002** | Scope = only `/api/recipes`? | Seam fixes `/api/recipes` AND `/api/explore/groups/.../recipes`. |
| **NC-003** | `count <= 5` from input? | Minimum provably 6; ceiling relaxed to `<= 10`. |
| **NC-004** | `slug_image` field? | Typo for `slug + image`; doesn't exist. |
| **NC-005** | `comments_count` N+1? | No comments field; adding would violate FR-001. |
| **NC-006** | Async test? | No — sync `def`. |
| **NC-007** | Nested array order under selectinload? | **Set-equal, not list-equal. V2: explicit DBMS × loader matrix.** |
| **NC-008** | `tests/multitenant_tests/` recipe tests? | None by name; recipe multi-tenancy = `test_recipe_cross_household.py`. |

---

## Self-Concerns

| ID | Concern |
|---|---|
| **SC-A** | Reviewers may not connect fix to literal N+1 framing |
| **SC-B** | Adjacent `ReadPlanEntry` / `ShoppingListRecipeRefOut` retain anti-pattern (out of scope) |
| **SC-C** | Chunking caveat for large pages |
| **SC-D** | `task dev:generate` reflex regenerates frontend types |
| **SC-E** | **selectinload-vs-joinedload nested-array-order trap (A3 perf_opt defense)** |

---

## V7 Defenses Still Applied

All v7 defenses from v1 carry through to v2 unchanged. V2's precision improvements strengthen the executability and cross-DBMS clarity but do NOT change which defenses are applied.

| Defense | Where (v2 ref) |
|---|---|
| A3 perf_opt: quantified target | FR-009 + FR-010 (now with verbatim skeleton) |
| A3 perf_opt: behavior-preservation test | FR-014 (now with EXPECTED_KEYS literal + skeleton) + SC-002 + SC-008 |
| A3 perf_opt: nested-array-order trap | SC-E + NC-007 (now with DBMS matrix) + FR-014(f) |
| C3: performance perspective | `exploration/consolidated.md` (5 perspectives, perf-aware) |
| Executable assertion seam | FR-014 (paste-able skeleton + EXPECTED_KEYS) |
| Existing test enumeration | FR-013 explicit list |
| `spec.md` / `spec.json` consistency | This .md summarizes by ID; .json is single source |
| No hedging placeholders | Axis 4 self-validation = 0 |
| Chunking-aware bound scoping | EC-006 keyed formula + FR-009 + SC-C |
| Multi-tenant isolation explicit | FR-012 + EC-005 |
| **NEW V2:** Executable "no migration" check | SC-009 |
| **NEW V2:** Session-state interaction documented | EC-010 |
