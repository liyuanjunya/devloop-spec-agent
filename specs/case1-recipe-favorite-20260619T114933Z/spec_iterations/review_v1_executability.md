# Executability Review (v1)

## Verdict: NEEDS_REFINE

A downstream code agent can implement most of this spec without further clarification: file paths are real, cited symbols exist, success criteria are measurable, and entity fields are derivable from related existing entities. However, **US-3 / FR-006 is explicitly unimplementable as written** (it defers a compatibility decision rather than choosing one), **several `code_references` line ranges exceed actual file lengths or omit cited symbols**, and **`spec.md` and `spec.json` disagree on the line ranges for several FRs** — so an agent that pulls ranges programmatically will sometimes read empty/wrong slices.

---

## Code reference verification

All paths were opened from `C:\Users\v-liyuanjun\Downloads\mealie\`. "Claim" merges what `spec.json` says with what `spec.md` adds where they diverge.

| FR | path | claim | verified? |
|---|---|---|---|
| FR-001 | `mealie/db/models/users/user_to_recipe.py` | `UserToRecipe` / `is_favorite` at L17–30 | ✅ class@L17, `is_favorite`@L29 (composite PK `(user_id, recipe_id, id)` confirmed) |
| FR-001 | `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py` | `upgrade` at L153–194 | ✅ `upgrade`@L153–195; creates `users_to_recipes`, drops `users_to_favorites` |
| FR-002 | `mealie/routes/users/crud.py` | `UserController` / `get_logged_in_user_favorites` at L19–40 | ⚠ Symbols exist (`UserController`@L17, `get_logged_in_user_favorites`@L38–40) but cited range starts mid-class at L19; minor |
| FR-002 | `mealie/routes/users/ratings.py` | `add_favorite` / `remove_favorite` at L78–86 | ✅ `add_favorite`@L78–81, `remove_favorite`@L83–86 |
| FR-002 | `mealie/routes/users/__init__.py` | router registration L10–15 (spec.md only) | ✅ exists; `ratings.router` registered@L15. *Note: this reference appears in spec.md but is **missing from spec.json**.* |
| FR-003 | `mealie/routes/users/ratings.py` | `set_rating` at L54–76 | ✅ `set_rating`@L54–76 (calls `assert_user_change_allowed`@L57 and `get_recipe_or_404`) |
| FR-003 | `mealie/repos/repository_users.py` | `RepositoryUserRatings.get_by_user_and_recipe` at L98–101 | ✅ `get_by_user_and_recipe`@L98–101 |
| FR-004 | `mealie/routes/users/ratings.py` | `set_rating` / `remove_favorite` at L70–86 | ✅ end of `set_rating` (L70–76) and `remove_favorite` (L83–86) covered |
| FR-004 | `mealie/repos/repository_users.py` | L98–101 | ✅ same as FR-003 |
| FR-005 | `mealie/routes/users/ratings.py` | `group_recipes` / `get_recipe_or_404` at L19–42 | ✅ `group_recipes`@L19–21, `get_recipe_or_404`@L23–42 |
| FR-005 | `mealie/routes/recipe/_base.py` | `BaseRecipeController.group_recipes` at L37–48 (spec.md says L37–56) | ✅ `BaseRecipeController`@L37, `group_recipes`@L42–44; both ranges valid |
| FR-005 | `mealie/repos/repository_generic.py` | `get_one` / `_filter_builder` at L94–102 + L156–179 (spec.json) | ✅ `_filter_builder`@L94–102, `get_one`@L156–179 |
| FR-005 | (same file, spec.md) | L104–179 (spec.md single range) | ⚠ Covers `get_one` but **omits `_filter_builder` (L94–102)** — a cited symbol is outside the cited range in `spec.md` |
| FR-006 | `mealie/routes/users/crud.py` | `get_logged_in_user_favorites` at L38–40 | ✅ method@L38–40, returns `UserRatings[UserRatingSummary]` |
| FR-006 | `mealie/schema/response/pagination.py` | `PaginationQuery` / `PaginationBase` at L46–56 (spec.json) | ⚠ `PaginationQuery`@L46–48 ✅, but `PaginationBase` starts@L51 and ends@L58 → spec.json range [46,56] **truncates `PaginationBase` (misses L57–58, `items`/`next`/`previous`)** |
| FR-006 | (same, spec.md) | L32–49 | ❌ Range covers `RequestQuery`@L32–43 and `PaginationQuery`@L46–48, but **`PaginationBase` (L51–58) is entirely outside the range** — one of two cited symbols is missing |
| FR-006 | `frontend/app/lib/api/user/users.ts` | `getFavorites` / `getSelfFavorites` / `getSelfRatings` at L58–75 | ✅ `getFavorites`@L58–60, `getSelfFavorites`@L62–64, `getSelfRatings`@L74–76 (range misses last line of `getSelfRatings` by 1) |
| FR-007 | `mealie/schema/recipe/recipe.py` | `RecipeSummary` / `Recipe` at L116–149 + L182–190 | ✅ `RecipeSummary`@L116–175 (range covers core fields only), `Recipe`@L182–393 (range covers initial body only) |
| FR-007 | `mealie/routes/recipe/recipe_crud_routes.py` | `get_all` / `get_one` at L340–395 + L415–424 | ✅ `get_all`@L341–395, `get_one`@L415–424 |
| FR-008 | `mealie/repos/repository_recipes.py` | `by_user`, `column_aliases`, `_get_rating_col_alias` at L36–52 + L72–93 | ✅ `RepositoryRecipes`@L36, `column_aliases`@L39–47, `by_user`@L49–52, `_get_rating_col_alias`@L72–93 |
| FR-008 | `mealie/db/models/recipe/recipe.py` | `RecipeModel.favorited_by` at L68–74 | ✅ `favorited_by`@L68–74 with `primaryjoin="and_(RecipeModel.id==UserToRecipe.recipe_id, UserToRecipe.is_favorite==True)"` |
| FR-008 | `mealie/repos/repository_users.py` | `get_by_user` / `get_by_recipe` at L82–96 | ✅ `get_by_user`@L82–88, `get_by_recipe`@L90–96 |
| FR-009 | `mealie/routes/recipe/recipe_crud_routes.py` | `get_all` at L367–383 | ✅ covers `by_user(self.user.id).page_all(...)` invocation |
| FR-009 | `mealie/schema/recipe/recipe.py` | `RecipeSummary.loader_options` at L168–175 | ✅ `loader_options`@L168–175 |
| FR-009 | `mealie/repos/repository_recipes.py` | `column_aliases` at L40–52 | ✅ `column_aliases`@L39–47, `by_user`@L49–52 |
| FR-010 | `mealie/routes/users/ratings.py` | `get_favorites` / `add_favorite` / `remove_favorite` at L44–86 | ✅ `get_favorites`@L49–52, `add_favorite`@L78–81, `remove_favorite`@L83–86 |
| FR-010 | `frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue` | `toggleFavorite` at L53–64 | ⚠ `toggleFavorite`@L53–65; range ends 1 line short |
| FR-010 | `frontend/app/pages/user/[id]/favorites.vue` | `query` at L30–32 | ✅ exact match; uses `queryFilter: favoritedBy.id = "<id>"` against `/api/recipes`, **not** the `/api/users/{id}/favorites` route |
| FR-011 | `tests/fixtures/fixture_users.py` | `build_unique_user`, `h2_user` at L17–80 (spec.json) | ✅ `build_unique_user`@L17–52, `h2_user`@L55–106 (range truncates `h2_user`) |
| FR-011 | (same, spec.md) | L17–276 | ⚠ Valid range (file has 286 lines) but extremely broad |
| FR-011 | `tests/fixtures/fixture_recipe.py` | L31–80 (spec.json) | ✅ `recipe_ingredient_only`@L31–54, `recipes_ingredient_only`@L57–85 (range truncates by 5) |
| FR-011 | (same, spec.md) | L16–131 | ❌ **File is only 103 lines — range L16–131 exceeds file length** |
| FR-011 | `tests/multitenant_tests/test_multitenant_cases.py` | L22–94 (spec.json) | ❌ **File is only 74 lines — range L22–94 exceeds file length**. Cited symbols `test_multitenant_cases_get_all`@L23–56 and `test_multitenant_cases_same_named_resources`@L60–93 do exist. |
| FR-011 | (same, spec.md) | L1–94 | ❌ **Range exceeds 74-line file length** |
| FR-011 | `tests/integration_tests/user_recipe_tests/test_recipe_cross_household.py` | `test_get_all_recipes_includes_all_households` at L45–70 (spec.json) | ✅ `test_get_all_recipes_includes_all_households`@L46–70 |

---

## Critical issues

- **EXEC-C-001 — FR-006 / US-3 cannot be implemented as written: the compatibility decision is deferred to the reviewer, not chosen.**
  The text says *"include an explicit compatibility decision before changing the response model"* and AC #4 requires *"compatibility is explicitly resolved before implementing"*. A code agent has nothing to act on: it does not know whether to (a) break `/api/users/self/favorites` to return `PaginationBase[RecipeSummary]`, (b) add a parallel route like `/api/users/self/favorites/recipes`, or (c) introduce a content-negotiation/alias. Without a default direction, the agent will either stall or guess. Self-Concern #1 acknowledges this but the FR still ships unresolved.
  *Suggested fix:* pick a default (e.g., "add `GET /api/users/self/favorites/recipes` returning `PaginationBase[RecipeSummary]`; leave `GET /api/users/self/favorites` returning rating summaries unchanged") and demote the alternatives to "may be revisited."

## High issues

- **EXEC-H-001 — `spec.md` line range `mealie/schema/response/pagination.py:32-49` does not contain `PaginationBase`.**
  `PaginationBase` is at L51–58 — entirely outside the cited range. `spec.json`'s `[46, 56]` is closer but still truncates `PaginationBase` mid-body (misses `items`/`next`/`previous`@L56–58). An agent reading only the cited slice would not see the response contract it is supposed to mirror.
  *Suggested fix:* use `[[46, 48], [51, 58]]` or simply `[46, 58]` and update `spec.md` to match.

- **EXEC-H-002 — `spec.md` FR-005 range `mealie/repos/repository_generic.py:104-179` omits `_filter_builder`.**
  `_filter_builder` (a cited symbol) lives at L94–102 and the spec.md range starts at L104. `spec.json` correctly uses `[[94, 102], [156, 179]]`. Sync `spec.md` to the JSON, otherwise readers of `spec.md` will not see the group/household scoping logic the FR depends on.

- **EXEC-H-003 — `spec.md` and `spec.json` disagree on `code_references` for multiple FRs.**
  Concrete drift:
  - FR-002: `spec.md` lists 3 paths (adds `mealie/routes/users/__init__.py:10-15`); `spec.json` lists only 2.
  - FR-005: line ranges differ as above (EXEC-H-002).
  - FR-006: line ranges differ (EXEC-H-001).
  - FR-008: `spec.md` lists `mealie/schema/recipe/recipe.py:168-175` and `mealie/routes/recipe/recipe_crud_routes.py` (referenced in surrounding FRs), while `spec.json` does not include these in FR-008 — only in FR-007/FR-009.
  - FR-011: line ranges differ on three of four test files.
  An agent that follows `spec.json` programmatically will get a different bill of materials than a human reading `spec.md`. Pick one source of truth and align the other.

- **EXEC-H-004 — Two FR-011 `code_references` line ranges exceed actual file length.**
  - `tests/fixtures/fixture_recipe.py:16-131` (spec.md) — file has 103 lines.
  - `tests/multitenant_tests/test_multitenant_cases.py:1-94` (spec.md) and `[22, 94]` (spec.json) — file has 74 lines.
  Cited symbols *do* exist (`recipe_ingredient_only`, `recipes_ingredient_only`, `test_multitenant_cases_get_all`, `test_multitenant_cases_same_named_resources`), but tooling that range-checks references will flag these as broken.

## Medium issues

- **EXEC-M-001 — No reference to the recipe service layer (`mealie/services/recipe/recipe_service.py`) despite it being the natural seam for hydrating `favorited`/`favorite_count`.**
  `RecipeService` is used by `recipe_crud_routes.get_one` (L419) and threads `self.user.id`. The consolidated exploration explicitly called this out as a likely touch point. FR-007/FR-008/FR-009 only point at schemas, the route, and the repository — so an agent that strictly follows the references will likely add hydration to the repository column-alias layer and miss the service path, or vice versa.

- **EXEC-M-002 — FR-007 mandates `favorited=false` for unauthenticated reads but cites no public/anonymous code path.**
  `recipe_crud_routes.get_all` (L341) uses `self.user.id` — i.e., the cited route already requires auth via `BaseRecipeController`. Self-Concern #4 acknowledges that an `optional-auth/try_get_current_user` path needs to be inspected, but the FR is written as if those endpoints are already identified. An agent will either:
  - assume the cited routes are public and add `Depends(try_get_current_user)` plumbing without spec guidance, or
  - implement `favorited`/`favorite_count` only on authenticated routes and leave the AC ("unauthenticated request to supported public recipe reads") untestable.
  *Suggested fix:* either name the public/anonymous recipe endpoints explicitly or restrict the AC to authenticated reads + recipe-share-token reads.

- **EXEC-M-003 — Response shape and status code for the new `POST` / `DELETE` self routes are unspecified.**
  Existing `add_favorite`/`remove_favorite` return `None` (FastAPI default 200, no body). The spec does not say whether the new self routes should mirror that, return the updated favorite state, return 201/204, or return a `SuccessResponse`. The idempotency AC is satisfied by 200, but an agent will have to choose between "mirror legacy" and "be more RESTful" without guidance, and tests for SC-001/SC-002 may be brittle.

- **EXEC-M-004 — FR-010 / spec narrative overstates frontend dependence on `GET /api/users/self/favorites`.**
  The favorites page (`frontend/app/pages/user/[id]/favorites.vue:31`) queries `/api/recipes` with `queryFilter=favoritedBy.id = "<id>"`, **not** `/api/users/{id}/favorites` or `/api/users/self/favorites`. The frontend client's `getSelfFavorites()` (L62–64) calls `routes.ratingsSelf` (= `/api/users/self/ratings`), **not** `/api/users/self/favorites`. So the only confirmed bundled consumer of `/api/users/self/favorites` is OpenAPI generation — which weakens the "compatibility-first" rationale that drives FR-006. Worth surfacing so the reviewer making the FR-006 decision is not over-anchored on a non-existent UI dependency.

- **EXEC-M-005 — FR-003 does not state the intended delegation pattern, leaving room for the `assert_user_change_allowed` invariant to be reimplemented inconsistently.**
  The natural implementation is `set_rating(self.user.id, slug, UserRatingUpdate(is_favorite=True))`, which trivially satisfies `assert_user_change_allowed(id, self.user, self.user)`@L57. But an agent could also bypass `set_rating` and call `RepositoryUserRatings.create`/`update` directly — losing the centralized rating-creation path and risking divergence in how the `rating` field is preserved on idempotent re-POST. Calling out "delegate to `set_rating`" would close this.

## Self-concerns verdicts

- **SC-#1 (FR-006 compatibility)** — Agreed and **escalated to EXEC-C-001**. The self-concern is correctly identified but must be resolved (a default chosen) before the spec is implementable; flagging the concern is not sufficient.
- **SC-#2 (FK cascade behavior on `users_to_recipes`)** — Accepted as a discover-at-impl-time item; implementers can read the migration (verified at L155–179 of the cited migration, which shows `ForeignKeyConstraint` *without* `ondelete=`, so deletes will fail until cascade is added or rows are cleaned first). Worth elevating to a Medium-severity *known* gap rather than uncertainty, since the cited file confirms no cascade exists today.
- **SC-#3 (favorite_count visibility)** — Accepted; the spec's chosen default ("group-scoped, follow recipe endpoint visibility") is reasonable and consistent with `RepositoryRecipes._get_rating_col_alias` (L72–93), which is the canonical pattern for user-aware aggregates.
- **SC-#4 (unauthenticated/optional-auth wiring)** — See EXEC-M-002; this should be resolved in the spec, not deferred.

## Summary

The spec is well-grounded in real code — every cited file exists, every cited symbol is present in the source, and most line ranges land on the right function. The blockers to executability are concentrated: FR-006 hands an open product decision to the implementer (EXEC-C-001), several line ranges either omit a cited symbol or exceed the file length (EXEC-H-001/002/004), `spec.md` and `spec.json` have drifted on multiple FRs (EXEC-H-003), and the service-layer seam plus unauthenticated-read path are under-specified for FR-007/FR-008. Resolve those and a junior dev could ship this PR.
