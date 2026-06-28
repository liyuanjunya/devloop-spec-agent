# Architecture Review — v1 (case-4 NEW pipeline)

## Verdict
**PASS** — the spec's architectural choices are sound. No critical or high issues.

## Selected seam analysis

The spec edits exactly one production file (`mealie/schema/recipe/recipe.py:168-175`, the `RecipeSummary.loader_options()` body) and adds two test files. The seam choice is correct:

1. **Why loader_options() instead of repository_recipes.py?** `RepositoryRecipes.page_all` already applies `RecipeSummary.loader_options()` at line 277 AFTER `add_pagination_to_query` at line 274 — preserving the "apply options late" invariant from commit `7b325082`. Editing only the loader function leaves the load-bearing line sequence at L274/277/280 unchanged (FR-008 preserves L280's `.scalars().unique().all()`). Smallest blast radius.
2. **Why selectinload instead of subqueryload?** subqueryload also issues a follow-up SELECT but uses a correlated subquery against the original query, which can re-trigger filter inflation. selectinload uses `WHERE recipe_id IN (...)` against already-loaded IDs — provably independent of recipe count. The existing prior art in `RecipeToolOut.loader_options` (`mealie/schema/recipe/recipe_tool.py:36-39`) uses exactly this pattern, confirming codebase idiom.
3. **Why keep joinedload(user)?** AssociationProxy `RecipeModel.household_id = association_proxy('user', 'household_id')` requires `recipe.user` to be loaded. A 1:1 joinedload adds no cartesian risk. FR-007 explicitly codifies this.

## Architecture findings

### ARCH-PASS-001 — Nested array order trap is explicitly defended
**Resolution**: The prior case-4 v1 had ARCH-H-001 (nested-array-order risk) and ARCH-H-002 (chunking miscount) as HIGH findings. This v1:
- Addresses ARCH-H-001 via FR-014 (sync def behavior-preservation test) + NC-007 (explicit resolution: set-equal, not list-equal, because no `order_by` on M2M relationships and adding one is out of scope) + SC-E (self-concern explicitly named "selectinload-vs-joinedload nested-array-order subtle break — A3 perf_opt trap"). 
- Addresses ARCH-H-002 via EC-006 (chunking-aware formula `2 + k_cat + k_tag + k_tool + k_households`) + FR-009 (absolute bound `<= 10` SCOPED to `perPage <= 200`) + SC-C self-concern explicitly capturing the chunking caveat.

### ARCH-PASS-002 — Multi-tenant isolation correctly preserved
selectinload issues follow-up SELECT against pre-filtered IDs (the parent SELECT's results); it CANNOT widen the household/group filter. Verified by FR-012 (cites `repository_recipes.py:238` and `_build_recipe_filter` at L295-337) and EC-005 (cites `test_recipe_cross_household.py:46-102` as the regression guard).

### ARCH-PASS-003 — Sequence invariant preserved (apply options late)
FR-002 explicitly cites the `add_pagination_to_query` at L274 → `q.options(...)` at L277 → `.scalars().unique().all()` at L280 sequence. Editing only `loader_options()` cannot break this. Commit `7b325082` regression risk is fully addressed.

### ARCH-PASS-004 — Adjacent loader sites correctly scoped out
SC-B explicitly captures `ReadPlanEntry.loader_options` (`new_meal.py:67-74`) and `ShoppingListRecipeRefOut.loader_options` (`group_shopping_list.py:202-208`) as out-of-scope follow-ups. FR-011 limits scope to the two endpoints that share `RepositoryRecipes.page_all` (primary `/api/recipes` + explore route).

### ARCH-PASS-005 — Non-actions are explicit
The `selected_approach_summary.non_actions` list enumerates exactly what is OFF-LIMITS: no `order_by=` on relationships, no migration, no cache, no `lazy='dynamic'`, no removal of `.unique()`, no new field on `RecipeSummary`. This pre-empts the most common over-engineering missteps.

## Self-concerns assessment

- **SC-A** (reviewers may not connect fix to literal N+1 framing) — VALID; FR-015 mitigates via PR description requirement.
- **SC-B** (adjacent loader sites) — VALID follow-up, correctly out of scope.
- **SC-C** (chunking caveat) — VALID; EC-006 + FR-009 scoping correctly resolves.
- **SC-D** (frontend types regeneration confusion) — VALID; FR-015 pre-empts.
- **SC-E** (nested-array-order trap, A3 perf_opt) — VALID; FR-014 + NC-007 correctly mitigates.

## Related-route assessment

- `/api/explore/groups/{group_slug}/recipes`: safe and covered — calls `cross_household_recipes.page_all(...)` and uses `RecipeSummary.loader_options()` (`controller_public_recipes.py:67-80`). Correctly captured by FR-011 and SC-007.
- `/api/users/self/favorites`: unaffected — different repository (`UserRatingOut`). Correctly excluded by FR-011 and NC-002.
- `/organizers/categories/slug/{slug}`: `per_page=-1` path; covered transitively. Chunking risk documented in EC-006.

## Summary

- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**Verdict: PASS — no architectural blockers.**
