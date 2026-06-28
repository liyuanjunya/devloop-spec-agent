# Architecture Review — v2

## Verdict
NEEDS_REFINE

v2 fixes the core loader seam and the SQLAlchemy selectinload chunking model, but it still has blocking gaps in the executable contract tests. Do **not** approve until the new HIGH issues below are resolved.

## v1 issue resolution

| v1 issue | Status | Evidence |
|---|---|---|
| ARCH-H-001 — nested M2M array order could change under `selectinload` while v1 claimed byte-identical responses | PARTIALLY_RESOLVED | v2 adds FR-014 and SC-008, normalizing `recipeCategory`, `tags`, and `tools` arrays by child `id` before comparison (`spec_v2.md:426-459`, `641-655`). This explicitly resolves array element ordering, but FR-014 still misses/wrongly states nested object field order and field count; see ARCH-H-003. |
| ARCH-H-002 — query-count budget under-counted chained `Tool.households_with_tool` chunking | RESOLVED | FR-009 now includes `chunks_of_tool_ids(T)` for the chained selectinload and scopes the absolute `<= 8` test budget to `perPage <= 200` (`spec_v2.md:246-284`). EC-006 also moves large `perPage=-1` pages to the formula bound (`spec_v2.md:713-729`). |
| ARCH-M-001 — misleading wording implied `column_aliases` affected response projection | RESOLVED | FR-013/NC-001 now state `column_aliases["rating"]` and `["last_made"]` are used only for filtering/ordering, while serialized `RecipeSummary.rating` comes from `RecipeModel.rating` (`spec_v2.md:394-413`, `751-765`). This matches `repository_recipes.py:39-93` and `RecipeModel.rating` at `recipe.py:61`. |

## New v2 issues

### ARCH-H-003 (HIGH)
**Location**: US-1, FR-001, FR-014, SC-002

**Issue**: The response-contract assertions still cannot reliably prove the declared nested field-order contract. v2 says `RecipeSummary` has 26 fields, but the on-disk schema and generated TS interface have 25 fields. It also lists nested organizer fields as `{id, name, slug, groupId}`, while the Pydantic declaration order is `id, group_id, name, slug` (`groupId` second). FR-014 only asserts nested field **sets**, so it would not catch a nested field-order regression despite US-1 explicitly requiring nested item field order.

**Evidence**: `spec_v2.md:94-109` and `:433-449`; `mealie/schema/recipe/recipe.py:61-65,83-85,116-149`; `frontend/app/lib/api/types/recipe.ts:102-112,265-270,310-336`.

**Fix**: Correct the count to 25 and define/assert exact nested object key order, e.g. `["id", "groupId", "name", "slug"]` and `["id", "groupId", "name", "slug", "householdsWithTool"]`, or explicitly downgrade nested object key order out of the public contract.

### ARCH-H-004 (HIGH)
**Location**: FR-010, FR-009(b), SC-001, SC-C

**Issue**: The new query-count test seeding is ambiguous and may not be load-bearing. FR-010 says each recipe has 3 tools and cites a pattern that creates only 3 total tools then reuses/randomly selects them. If implementers reuse a small global tool set, the pre-refactor `Tool.households_with_tool` lazy-load N+1 is only O(3), so the 10-vs-100 recipe test can pass without proving the dominant per-unique-tool regression is fixed.

**Evidence**: FR-010 (`spec_v2.md:292-315`) cites `test_recipe_crud.py:1534-1558`, where only 3 tools are created and reused. SC-C assumes "3 unique tools per recipe" (`spec_v2.md:881-888`), but FR-010 does not require that.

**Fix**: Require and assert at least one load-bearing distinct-tool threshold, preferably 3 newly created `Tool` rows per recipe (≈300 distinct tools at 100 recipes), and assert the measured page contains that distinct tool count before checking SQL counts.

### ARCH-M-002 (MEDIUM)
**Location**: FR-014, NC-007

**Issue**: The baseline comparison protocol is under-specified for CI. Persisting a sorted JSON fixture captured from `main` is brittle unless all UUIDs, timestamps, slugs, and organizer IDs are deterministic; recomputing "from a `from_baseline(...)` helper" is not defined and cannot run old loader code in the same PR test.

**Evidence**: FR-014 requires capturing a pre-refactor response from `main` or recomputing via a helper (`spec_v2.md:461-464`), while NC-007 depends on "same persisted rows" with no re-seeding (`spec_v2.md:834-850`).

**Fix**: Specify a deterministic fixture protocol (fixed IDs/timestamps and checked-in canonical JSON) or replace the baseline diff with explicit schema/value assertions that are fully computable in CI.

## Summary

- Critical: 0
- High: 2
- Medium: 1
- Low: 0
- Overall: FAIL / NEEDS_REFINE. Do not APPROVE until ARCH-H-003 and ARCH-H-004 are addressed.
