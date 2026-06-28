# Executability Review (v2)

## Verdict: NEEDS_CLARIFICATION

Spec v2 is much more executable than v1: all cited paths exist, `spec_v2.md` and `spec_v2.json` have identical `code_references`, most v1 line-range drift is fixed, public anonymous recipe paths are now cited, and the success criteria are mostly measurable. However, coding still must not start until the two explicit `NEEDS_CLARIFICATION` decisions are recorded, and a few implementation-facing ambiguities remain. Executability score: **7/10 while NC-001/NC-002 are unresolved; 8/10 if the recommended defaults are formally accepted**.

---

## Code reference verification

All cited paths were opened under `C:\Users\v-liyuanjun\Downloads\mealie\`. Every cited file exists and every numeric range is within the current file length. I also cross-checked that the claimed symbol or code concept appears in the cited slice.

### Dedicated wrong / imprecise citation subsection

- **FR-011 — `tests/fixtures/fixture_users.py:17-106` truncates the `h2_user` household fixture.**
  - Verified: `build_unique_user` is complete at L17-52 and `h2_user` starts at L55.
  - Problem: the cited range ends at L106 in the middle of `yield utils.TestUser(...)`; the complete yielded fixture object continues through L115, with the `finally` block at L116-118.
  - Impact: an agent reading only the cited range sees an incomplete fixture construction and may miss the token/repo fields needed for household/user fixture patterns.
  - Suggested fix: use `tests/fixtures/fixture_users.py:17-118` or split into `17-52,55-118`.

No cited path is missing. No range exceeds file length. No `spec.md` vs `spec.json` `code_references` mismatch was found.

### Verified reference highlights

| Area | Result |
|---|---|
| Storage model | `UserToRecipe`, `is_favorite`, unique `(user_id, recipe_id)`, indexed `user_id`/`recipe_id`, and non-cascading FKs verified at `mealie/db/models/users/user_to_recipe.py:17-30` / `22-24`. |
| 2024 migration | `users_to_recipes` creation, indexes, and `users_to_favorites` drop verified at `...d7c6efd2de42...py:153-194`; constraints have no `ondelete`. |
| Existing favorite routes | `get_recipe_or_404`, `set_rating`, `add_favorite`, `remove_favorite`, and legacy `GET /{id}/favorites` verified in `mealie/routes/users/ratings.py`. |
| Self-route collision | Existing `GET /self/favorites` returns `UserRatings[UserRatingSummary]` at `mealie/routes/users/crud.py:38-40`; test/constants callers verified. |
| Recipe read paths | Authenticated `/recipes` uses `UserAPIRouter` and `BaseUserController`; anonymous reads are correctly cited in `PublicRecipesController` under `/explore/groups/{group_slug}/recipes`. |
| Hydration seam | `RepositoryRecipes.column_aliases` is only used for queryFilter/orderBy; `page_all` serializes via schema validation. v2 correctly forbids using aliases as projection. |
| Cleanup | Recipe delete cleanup exists in `RepositoryRecipes._delete_recipe`; user delete still lacks `UserToRecipe` cleanup; user/recipe relationships lack cascade. |
| Tests | Cited tests/fixtures exist; only `fixture_users.py:17-106` is materially truncated as noted above. |

---

## Critical issues

- **EXEC-C-001 — Spec remains intentionally blocked by NC-001 and NC-002, so a code agent should not start implementation yet.**
  - Location: `NEEDS_CLARIFICATION`, FR-001, NC-002/FR-004, status line.
  - Evidence: v2 states "Stage-0 data-model decision MUST be recorded before coding" and says the feature status is "Draft v2 — needs blocking decisions recorded." That is clear and safe, but it means the spec is not yet directly executable by an autonomous code agent.
  - Suggested action: record explicit decisions before handing to coding, e.g. "Accepted: reuse `users_to_recipes` / `UserToRecipe.is_favorite`" and "Accepted: move rating-summary favorites to `GET /api/users/self/ratings/favorites`."

## High issues

- **EXEC-H-001 — FR-004 / NC-002 still says `/api/users/self/ratings/favorites` "or equivalent", leaving the replacement route name non-deterministic.**
  - Location: NC-002 and FR-004.
  - Why this matters: endpoint paths are observable API contract. A code agent can guess the parenthesized path, but tests and generated clients need one exact path.
  - Suggested action: replace "or equivalent" with the exact selected route, preferably `GET /api/users/self/ratings/favorites`, and name any helper route constants/tests to update.

## Medium issues

- **EXEC-M-001 — New self POST/DELETE response body and status code are still not explicitly specified.**
  - Existing legacy `add_favorite` / `remove_favorite` return `None`, which FastAPI exposes as 200 with an empty/null body. v2 says mutations return success and use the same storage/service path, but it does not explicitly say whether self routes must mirror 200/no-body, use 204, or return a state payload.
  - Suggested action: add "POST and DELETE self routes MUST mirror legacy behavior: HTTP 200 with no response body" (or the desired alternative).

- **EXEC-M-002 — SC-004's no-N+1 threshold is directionally testable but lacks a concrete query-count bound.**
  - "Bounded query count independent of page size" is measurable by comparing two page sizes, but the spec does not define page sizes or allowed delta.
  - Suggested action: define an assertion such as "query count for 1 item vs 50 items differs by at most 1-2 queries" or cite the existing query-count helper if one exists.

- **EXEC-M-003 — FR-006 contains an approval-dependent alternative outside `NEEDS_CLARIFICATION`.**
  - The requirement is implementable if the agent adds `errors.no-entry-found` to `en-US` and uses it. However, the alternative "obtain reviewer approval to use `exceptions.no-entry-found`" is not executable in autonomous coding.
  - Suggested action: choose one path in the spec. If preserving the requested namespace matters, require adding the alias and remove the approval branch.

## V1 executability issue check

| v1 issue | v2 status |
|---|---|
| EXEC-C-001 route compatibility deferred | **Partially resolved**: v2 chooses a default and records NC-002, but coding remains blocked until the decision is formally accepted. |
| EXEC-H-001 pagination line range wrong | **Resolved**: `mealie/schema/response/pagination.py:46-58` contains both `PaginationQuery` and full `PaginationBase`. |
| EXEC-H-002 `repository_generic` range omitted `_filter_builder` | **Resolved by rewrite**: v2 no longer relies on that old citation. |
| EXEC-H-003 `spec.md` / `spec.json` code reference drift | **Resolved**: all FR `code_references` are identical. |
| EXEC-H-004 ranges exceeded file length | **Resolved**: all cited ranges are within file length. One new truncation remains in `fixture_users.py:17-106`. |
| EXEC-M-001 missing recipe service seam | **Resolved**: v2 cites `mealie/services/recipe/recipe_service.py:63-68` and adds user-service requirement. |
| EXEC-M-002 anonymous/public recipe path missing | **Resolved**: v2 explicitly cites `PublicRecipesController` and explore mount. |
| EXEC-M-003 POST/DELETE response shape unspecified | **Still open**: see EXEC-M-001. |
| EXEC-M-004 frontend dependence overstated | **Resolved**: v2 states backend test/route constants are the verified blast radius. |
| EXEC-M-005 delegation invariant under-specified | **Mostly resolved**: FR-002/FR-005 require a shared service/repository path and preserve permission/rating behavior. |

## Placeholder / TBD scan

No literal `TBD`, `to be decided`, or `placeholder` language remains. The remaining placeholder-like terms are intentional blockers/alternatives: `NEEDS_CLARIFICATION`, `recommended default`, `or equivalent`, and reviewer-approval wording. The `or equivalent` route wording is the only one I consider newly unexecutable.

## Success criteria review

SC-001, SC-002, SC-003, SC-005, SC-006, SC-007, and SC-008 are testable. SC-004 is testable in principle but should define a concrete query-count threshold for deterministic CI assertions.

## New unexecutable claims in v2

1. **FR-004 / NC-002 route replacement path**: `GET /api/users/self/ratings/favorites` is suggested but not made exact because of "or equivalent".
2. **FR-006 i18n key alternative**: reviewer approval branch is not actionable for a code agent; choose alias-addition or existing key.
3. **SC-004 no-N+1 metric**: lacks exact query-count bound/page-size comparison for an automated test.

## Summary

v2 fixed the major v1 evidence and pathing problems. The remaining blockers are not hidden: NC-001/NC-002 are clearly marked, and that is good process hygiene. To make the spec fully executable, record the two decisions, pin the moved ratings route path exactly, specify self mutation response status/body, tighten SC-004, and fix the truncated `fixture_users.py` citation.
