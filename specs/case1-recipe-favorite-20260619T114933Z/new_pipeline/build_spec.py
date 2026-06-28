"""Build the NEW-pipeline spec for Mealie case-1 (recipe favorites).

Programmatically constructs spec.json so each FR/SC/citation is validated
against the new defenses (A4, A5, B1, B3) before being written to disk.

Run:
    python build_spec.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\v-liyuanjun\source\repos\devloop")
sys.path.insert(0, str(ROOT))

from devloop.spec_phase.md_json_bridge import (  # noqa: E402
    assert_spec_roundtrip_consistent,
    spec_to_markdown,
)
from devloop.spec_phase.schemas import Spec  # noqa: E402
from devloop.spec_phase.validators.citation_verifier import (  # noqa: E402
    verify_spec_citations,
)
from devloop.spec_phase.validators.trace_matrix import find_trace_gaps  # noqa: E402

MEALIE = Path(r"C:\Users\v-liyuanjun\Downloads\mealie")
OUT_DIR = (
    ROOT
    / "specs"
    / "case1-recipe-favorite-20260619T114933Z"
    / "new_pipeline"
)


def cref(path: str, line_ranges: list[tuple[int, int]], symbols: list[str]) -> dict:
    """Build a CodeRef dict; the verifier confirms each symbol is in the cited range."""
    return {"path": path, "symbols": symbols, "line_ranges": line_ranges}


# ---------------------------------------------------------------------------
# NEEDS_CLARIFICATION (blocking decisions) — addresses input-vs-code conflicts
# that must be resolved before coding.
# ---------------------------------------------------------------------------
needs_clarification = [
    {
        "id": "NC-001",
        "title": "Storage model: new `user_favorite_recipe` table vs reuse `UserToRecipe.is_favorite`",
        "conflict": (
            "Input §1 requests a new `user_favorite_recipe` table with composite "
            "unique (user_id, recipe_id), single user_id index, and cascade FKs. "
            "Mealie code already persists favorites on the existing `users_to_recipes` "
            "table via `UserToRecipe.is_favorite` (boolean column), and the 2024-03-18 "
            "Alembic migration `d7c6efd2de42` explicitly consolidated favorites into "
            "that table and dropped the older `users_to_favorites` table. Implementing "
            "both storage models simultaneously would double-write favorite state and "
            "break the existing legacy routes plus the rating coexistence on the same row."
        ),
        "recommended_default": (
            "Reuse `UserToRecipe.is_favorite` as the canonical favorite storage. "
            "Rationale: (1) the 2024-03-18 migration already collapsed favorites into "
            "this row; (2) the unique constraint `user_id_recipe_id_rating_key` on "
            "`UserToRecipe.__table_args__` already enforces the same (user_id, recipe_id) "
            "invariant that input §1 asks for; (3) indexes on user_id and recipe_id "
            "already exist via `index=True` on the columns; (4) the existing legacy "
            "routes at `/api/users/{id}/favorites/{slug}` and the frontend "
            "`RecipeFavoriteBadge.vue` already depend on this storage, so a parallel "
            "table would require dual-write, backfill, and deprecation work that input "
            "§1 does not justify. The composite uniqueness, cascade, and indexing "
            "requirements from input §1 are satisfied by adding `ON DELETE CASCADE` "
            "to the existing FKs (see FR-015)."
        ),
        "if_rejected": (
            "Implement a separate `user_favorite_recipe` table per input §1, plus an "
            "Alembic migration that (a) creates the table with FKs ON DELETE CASCADE, "
            "(b) backfills rows from `users_to_recipes` where `is_favorite = true`, "
            "(c) introduces a dual-write window in `UserRatingsController.set_rating` "
            "writing to both tables, (d) cuts over reads, and (e) drops "
            "`UserToRecipe.is_favorite` in a follow-up migration. In this branch "
            "FR-001 / FR-003 / FR-004 / FR-007 / FR-008 / FR-015 must be re-pointed "
            "at the new table."
        ),
        "related_requirements": ["FR-001", "FR-003", "FR-004", "FR-007", "FR-008", "FR-015"],
    },
    {
        "id": "NC-002",
        "title": "`GET /api/users/self/favorites` response contract: break the existing rating-summary endpoint or add a parallel path",
        "conflict": (
            "Input §2 requests `GET /api/users/self/favorites?page=1&perPage=50` "
            "returning a paginated recipe list (response shape "
            "`PaginationBase[RecipeSummary]`). Mealie code already has an endpoint "
            "at that exact path: `UserController.get_logged_in_user_favorites` at "
            "`mealie/routes/users/crud.py:38-40` returns `UserRatings[UserRatingSummary]` "
            "(a non-paginated list of rating summaries). Silently overwriting the "
            "response model would break OpenAPI clients, generated TypeScript types, "
            "and the existing integration test `test_user_recipe_favorites` at "
            "`tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:43`."
        ),
        "recommended_default": (
            "Add a new endpoint `GET /api/users/self/favorites/recipes` returning "
            "`PaginationBase[RecipeSummary]` per input §2. Leave the existing "
            "`GET /api/users/self/favorites` returning `UserRatings[UserRatingSummary]` "
            "unchanged so the one integration test caller and any external clients "
            "(generated TypeScript, third-party API consumers) continue to work. "
            "Document the legacy endpoint as deprecated in its OpenAPI docstring and "
            "schedule removal in the next minor release. Rationale: zero breakage, "
            "matches input §2 exactly (the path the input specifies still works), "
            "and the alias is one extra route handler delegating to "
            "`RepositoryUserRatings.get_by_user(self.user.id, favorites_only=True)`."
        ),
        "if_rejected": (
            "Change `UserController.get_logged_in_user_favorites` response_model "
            "to `PaginationBase[RecipeSummary]`, update the single test caller in "
            "`tests/integration_tests/user_recipe_tests/test_recipe_ratings.py:43-95` "
            "to expect the new shape, regenerate frontend API types via "
            "`task dev:generate`, and add a CHANGELOG entry flagging the breaking "
            "response-shape change. Drop FR-006's parallel-route requirement and "
            "update SC-003's path."
        ),
        "related_requirements": ["FR-006"],
    },
    {
        "id": "NC-003",
        "title": "`favorite_count` visibility scope: global vs group-scoped vs public-only",
        "conflict": (
            "Input §3 says `favorite_count` is `公开` (publicly returned). The "
            "natural reading is a global count across all users who favorited the "
            "recipe. But the spec must also avoid leaking cross-tenant data: a "
            "household-private recipe should not have its count visible to "
            "outsiders, and the existing recipe endpoints scope reads by group/"
            "household visibility. The choice changes the SQL aggregate (no "
            "WHERE clause vs join through recipe visibility filter) and the "
            "tenant isolation guarantee in SC-006."
        ),
        "recommended_default": (
            "Compute `favorite_count` as the number of `UserToRecipe` rows with "
            "`is_favorite = true` AND `recipe_id = <recipe.id>`, with no additional "
            "filter on the favoriting user's group or household. Visibility of the "
            "count is bounded only by visibility of the recipe itself: the existing "
            "recipe endpoint already returns 404 for cross-group recipes (per "
            "FR-005), so a caller who can read the recipe is allowed to see how "
            "many distinct users favorited it. Rationale: input §3 explicitly says "
            "`公开` (public), and the existing `RecipeModel.favorited_by` "
            "relationship at `mealie/db/models/recipe/recipe.py:68` has no "
            "tenant filter — matching that behavior keeps the count consistent "
            "with the relationship and avoids surprising drops when admins move "
            "users between households."
        ),
        "if_rejected": (
            "Switch the aggregate to count only `UserToRecipe` rows whose user is "
            "in the same group as the recipe (join `UserToRecipe.user_id` to "
            "`users.group_id` and filter `users.group_id = recipe.group_id`). "
            "Document the choice in FR-008 and add a multitenant test asserting "
            "that cross-group favorites do not contribute to the count. SC-005 "
            "and SC-006 thresholds must be updated accordingly."
        ),
        "related_requirements": ["FR-007", "FR-008"],
    },
]

# ---------------------------------------------------------------------------
# User stories
# ---------------------------------------------------------------------------
user_stories = [
    {
        "id": "US-1",
        "priority": "P1",
        "title": "Authenticated user favorites a recipe via self route",
        "description": (
            "As a signed-in user, I can favorite a recipe visible to my group "
            "without sending my own user id in the URL."
        ),
        "why_this_priority": (
            "Core write path requested by input §2; without it the feature does "
            "not exist."
        ),
        "independent_test": (
            "Log in as user A, POST `/api/users/self/favorites/{visible_recipe_slug}` "
            "twice, then GET the new self favorites recipe list and assert the "
            "recipe appears exactly once."
        ),
        "acceptance": [
            {
                "given": "an authenticated user and a recipe visible to their group",
                "when": "they POST `/api/users/self/favorites/{recipe_slug}`",
                "then": "the response is 200, a `UserToRecipe` row exists for "
                        "(user_id, recipe_id) with `is_favorite = true`, and no "
                        "duplicate row is created on repeat POSTs",
            },
            {
                "given": "an authenticated user POSTing the same favorite twice",
                "when": "the second POST is observed",
                "then": "the response is 200 (idempotent) and the row count for "
                        "(user_id, recipe_id) in `users_to_recipes` remains 1",
            },
            {
                "given": "a recipe whose group is not the user's group",
                "when": "the user POSTs the self favorite route for that slug",
                "then": "the response is 404 and no `UserToRecipe` row is created",
            },
            {
                "given": "an authenticated request to the self favorite POST route",
                "when": "the implementation looks up the user id",
                "then": "the user id is read from `self.user.id` (the JWT-resolved "
                        "current user) and never from a URL path parameter",
            },
        ],
    },
    {
        "id": "US-2",
        "priority": "P1",
        "title": "Authenticated user unfavorites a recipe via self route",
        "description": (
            "As a signed-in user, I can remove a favorite using a self route, "
            "without sending my own user id in the URL."
        ),
        "why_this_priority": (
            "Symmetric counterpart to US-1; required by input §2 idempotency rules."
        ),
        "independent_test": (
            "Favorite a recipe as user A, DELETE "
            "`/api/users/self/favorites/{recipe_slug}` twice, then assert "
            "`is_favorite = false` in `users_to_recipes` and 200 status on both "
            "DELETEs."
        ),
        "acceptance": [
            {
                "given": "an authenticated user with an existing favorite for a recipe",
                "when": "they DELETE `/api/users/self/favorites/{recipe_slug}`",
                "then": "the `UserToRecipe` row is updated to `is_favorite = false` "
                        "and the response is 200",
            },
            {
                "given": "an authenticated user with no favorite for a recipe",
                "when": "they DELETE `/api/users/self/favorites/{recipe_slug}`",
                "then": "the response is 200 (idempotent) and no error is raised",
            },
            {
                "given": "a recipe whose group is not the user's group",
                "when": "the user DELETEs the self favorite route for that slug",
                "then": "the response is 404 and no row in `users_to_recipes` is "
                        "modified",
            },
        ],
    },
    {
        "id": "US-3",
        "priority": "P1",
        "title": "User lists their favorited recipes (paginated)",
        "description": (
            "As a signed-in user, I can list my favorited recipes with Mealie "
            "pagination semantics, getting a paginated recipe list (not a rating "
            "summary list)."
        ),
        "why_this_priority": (
            "Required by input §2; gives users the 'my collection' surface that "
            "motivates the whole favoriting feature."
        ),
        "independent_test": (
            "Favorite 60 recipes across two pages and GET "
            "`/api/users/self/favorites/recipes?page=1&perPage=50` then "
            "`?page=2&perPage=50`; assert items length 50 then 10, total=60, "
            "and items are `RecipeSummary` shape."
        ),
        "acceptance": [
            {
                "given": "an authenticated user with favorited recipes visible in their group",
                "when": "they GET the new self favorites recipe-list endpoint",
                "then": "the response shape is `PaginationBase[RecipeSummary]` with "
                        "`page`, `per_page`, `total`, `total_pages`, `items`, "
                        "`next`, and `previous` fields per "
                        "`mealie/schema/response/pagination.py:51`",
            },
            {
                "given": "an authenticated user with N favorites and a query "
                         "`page=2&perPage=10`",
                "when": "the user lists favorites",
                "then": "exactly the second 10 items are returned and `total = N`",
            },
            {
                "given": "another user B has favorited a recipe that user A has not",
                "when": "user A lists their favorites",
                "then": "user B's favorite is not included unless user A also "
                        "favorited it and the recipe is visible to user A's group",
            },
        ],
    },
    {
        "id": "US-4",
        "priority": "P1",
        "title": "Recipe list and detail responses include `favorited` and `favorite_count`",
        "description": (
            "As any recipe reader, I see `favorite_count: int` on every recipe "
            "response; as an authenticated reader, I additionally see "
            "`favorited: bool` indicating whether I favorited the recipe."
        ),
        "why_this_priority": (
            "Required by input §3; UI badge depends on the bool, ranking/sort "
            "depends on the count."
        ),
        "independent_test": (
            "User A favorites recipe R. User A GETs `/api/recipes/{R.slug}` and "
            "asserts `favorited = true`, `favorite_count = 1`. User B (different "
            "user, same group) GETs the same and asserts `favorited = false`, "
            "`favorite_count = 1`."
        ),
        "acceptance": [
            {
                "given": "user A favorited recipe R",
                "when": "user A GETs `/api/recipes` or `/api/recipes/{R.slug}`",
                "then": "the returned recipe has `favorited = true` and "
                        "`favorite_count >= 1`",
            },
            {
                "given": "user A did NOT favorite recipe R but recipe R has favorites from other users",
                "when": "user A GETs the same recipe",
                "then": "the returned recipe has `favorited = false` and "
                        "`favorite_count` equals the total count under the "
                        "visibility model fixed in NC-003",
            },
            {
                "given": "a list endpoint returning many recipes",
                "when": "favorites are hydrated",
                "then": "the implementation uses a single bulk query (correlated "
                        "EXISTS, joined subquery, GROUP BY aggregate, or one "
                        "batched lookup keyed by page item ids) rather than one "
                        "extra query per recipe",
            },
        ],
    },
    {
        "id": "US-5",
        "priority": "P1",
        "title": "Anonymous reader sees `favorited=false` and a real `favorite_count`",
        "description": (
            "As an unauthenticated reader of public recipe endpoints, I see "
            "`favorited = false` (no per-user state) but a non-zero "
            "`favorite_count` when the recipe has favorites."
        ),
        "why_this_priority": (
            "Explicitly required by input §3 (`未登录用户：favorited 字段恒为 false`); "
            "the public count is the social-proof signal the input asks for."
        ),
        "independent_test": (
            "User A favorites recipe R. Anonymous client (no Authorization "
            "header) GETs the public recipe endpoint for R; assert "
            "`favorited = false` and `favorite_count = 1`."
        ),
        "acceptance": [
            {
                "given": "an unauthenticated request to a public recipe endpoint",
                "when": "the recipe is returned",
                "then": "`favorited = false` regardless of whether any user "
                        "favorited the recipe",
            },
            {
                "given": "an unauthenticated request to a public recipe endpoint and the recipe has favorites",
                "when": "the recipe is returned",
                "then": "`favorite_count` reflects the real count under the "
                        "visibility model fixed in NC-003 (not 0)",
            },
            {
                "given": "the `/api/recipes/*` controller currently requires authentication via `UserAPIRouter`",
                "when": "implementing US-5",
                "then": "either the existing public controller "
                        "`PublicRecipesController` at "
                        "`mealie/routes/explore/controller_public_recipes.py:21` "
                        "is extended to hydrate `favorited`/`favorite_count`, or "
                        "the authenticated `/api/recipes/*` routes are migrated "
                        "to `Depends(try_get_current_user)` so anonymous reads "
                        "are served from the same handler",
            },
        ],
    },
    {
        "id": "US-6",
        "priority": "P1",
        "title": "Cross-group isolation: users cannot favorite or see favorites of other groups' recipes",
        "description": (
            "As a tenant-isolated user, I cannot favorite a recipe outside my "
            "group, list other users' favorites, or have my favorites leak into "
            "another household's responses."
        ),
        "why_this_priority": (
            "Required by input §2 multitenant rules; failure leaks "
            "cross-tenant data."
        ),
        "independent_test": (
            "Create user A in group G1 and user B in group G2. Recipe R "
            "belongs to G1. Assert (a) user B POSTing the self favorite route "
            "for R returns 404, (b) user B's favorites list does not include R, "
            "(c) user A's favorites list does not include any recipe owned by G2."
        ),
        "acceptance": [
            {
                "given": "user A in group G1, user B in group G2, recipe R in G1",
                "when": "user B POSTs `/api/users/self/favorites/{R.slug}`",
                "then": "the response is 404 and no `UserToRecipe` row is created "
                        "for (B.id, R.id)",
            },
            {
                "given": "user A favorited recipe R (in G1)",
                "when": "user B (in G2) lists their own favorites",
                "then": "R does not appear in user B's response",
            },
            {
                "given": "two households H1 and H2 within group G1",
                "when": "user in H1 favorites a recipe owned by H1",
                "then": "users in H2 reading their own self favorites list do "
                        "not see that recipe (favorites are per-user, not "
                        "per-household)",
            },
        ],
    },
    {
        "id": "US-7",
        "priority": "P2",
        "title": "Cascade cleanup when a recipe or user is deleted",
        "description": (
            "As an operator, when I delete a recipe I expect every related "
            "favorite row to disappear; when I delete a user I expect every "
            "favorite that user owned to disappear; no orphan rows remain to "
            "skew `favorite_count`."
        ),
        "why_this_priority": (
            "Required by input §2 (`食谱被删除时：cascade 删除所有相关 favorite`); "
            "P2 rather than P1 because it depends on US-4 having shipped the "
            "`favorite_count` aggregate before the orphan effect is observable."
        ),
        "independent_test": (
            "(a) Favorite recipe R, DELETE R via the recipe DELETE endpoint, "
            "assert no `UserToRecipe` row with `recipe_id = R.id` remains. "
            "(b) Favorite recipe R as user A, DELETE user A via the admin user "
            "DELETE endpoint, assert no `UserToRecipe` row with "
            "`user_id = A.id` remains and that `favorite_count` on R drops by 1."
        ),
        "acceptance": [
            {
                "given": "a favorited recipe is deleted via the recipe DELETE flow",
                "when": "the favorites list and `favorite_count` are queried",
                "then": "the deleted recipe is absent from every favorites list "
                        "and contributes 0 to any aggregate",
            },
            {
                "given": "a user with favorite rows is deleted via the user DELETE flow",
                "when": "the favorites and `favorite_count` aggregates are queried for remaining users",
                "then": "the deleted user's `UserToRecipe` rows are absent and "
                        "`favorite_count` is decremented for every recipe the "
                        "user had favorited",
            },
            {
                "given": "FK definitions on `users_to_recipes.user_id` and `users_to_recipes.recipe_id` currently lack `ondelete=CASCADE`",
                "when": "the implementation adds the cascade behavior",
                "then": "the new Alembic migration (FR-015) modifies the FKs to "
                        "`ON DELETE CASCADE` AND `RepositoryUsers.delete` is "
                        "extended (FR-016) so both the database and application "
                        "layers agree on the cascade outcome",
            },
        ],
    },
    {
        "id": "US-8",
        "priority": "P2",
        "title": "Existing `/api/users/{id}/favorites/{slug}` routes keep working",
        "description": (
            "As a client of the legacy user-id favorite routes (single test "
            "caller plus any third-party OpenAPI consumer), my requests "
            "continue to land on the same storage and return the same shape."
        ),
        "why_this_priority": (
            "Backward compat; failure breaks the existing `test_user_recipe_favorites` "
            "test plus any external client."
        ),
        "independent_test": (
            "Run the existing parametrized "
            "`test_user_recipe_favorites[use_self_route=False]` test in "
            "`tests/integration_tests/user_recipe_tests/test_recipe_ratings.py` "
            "and confirm it still passes after the change."
        ),
        "acceptance": [
            {
                "given": "an existing client calling POST/DELETE `/api/users/{id}/favorites/{slug}` for its own user id",
                "when": "the legacy route is invoked",
                "then": "the behavior, status code, and storage effect are "
                        "unchanged from the pre-feature baseline",
            },
            {
                "given": "a client calling the legacy route with another user's id",
                "when": "the id mismatch is detected via `assert_user_change_allowed`",
                "then": "the existing permission check still rejects the request",
            },
            {
                "given": "the new self routes (FR-002) and the legacy routes (FR-011)",
                "when": "both mutate the same (user, recipe) pair",
                "then": "they call the same repository method "
                        "(`RepositoryUserRatings.create` / `.update`) so storage "
                        "stays consistent",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Functional requirements — every functional FR links to ≥1 SC (B3)
# ---------------------------------------------------------------------------
functional_requirements = [
    {
        "id": "FR-001",
        "requirement_type": "functional",
        "text": (
            "Under the NC-001 recommended default, favorite persistence MUST use "
            "the existing `users_to_recipes` table and `UserToRecipe.is_favorite` "
            "boolean column as the canonical storage; no new "
            "`user_favorite_recipe` table is introduced. The composite uniqueness "
            "input §1 requires is already enforced by the table-level "
            "`UniqueConstraint(\"user_id\", \"recipe_id\", "
            "name=\"user_id_recipe_id_rating_key\")` and the existing per-column "
            "`index=True` declarations satisfy the user_id index. If NC-001 is "
            "rejected, FR-001 is replaced per the NC-001 `if_rejected` block."
        ),
        "code_references": [
            cref(
                "mealie/db/models/users/user_to_recipe.py",
                [(17, 30)],
                ["UserToRecipe", "is_favorite", "users_to_recipes",
                 "user_id_recipe_id_rating_key", "user_id", "recipe_id"],
            ),
            cref(
                "mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py",
                [(153, 195)],
                ["users_to_recipes", "users_to_favorites", "is_favorite",
                 "user_id_recipe_id_rating_key"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-3", "US-6"],
        "related_success_criteria": ["SC-001", "SC-002"],
        "testable": True,
    },
    {
        "id": "FR-002",
        "requirement_type": "functional",
        "text": (
            "Add two authenticated self routes that resolve the user id from "
            "`self.user.id` (JWT) and never accept a user id from the URL: "
            "`POST /api/users/self/favorites/{recipe_slug}` and "
            "`DELETE /api/users/self/favorites/{recipe_slug}`. The new routes "
            "live on the existing `UserController` in `mealie/routes/users/crud.py` "
            "(which extends `BaseUserController`) and are mounted via the "
            "existing `user_router` registered in `mealie/routes/users/__init__.py`."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/crud.py",
                [(17, 40)],
                ["UserController", "BaseUserController", "user_router",
                 "get_logged_in_user_favorites"],
            ),
            cref(
                "mealie/routes/users/ratings.py",
                [(78, 86)],
                ["add_favorite", "remove_favorite", "set_rating",
                 "is_favorite"],
            ),
            cref(
                "mealie/routes/users/__init__.py",
                [(1, 15)],
                ["user_prefix", "router", "include_router", "ratings"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2"],
        "related_success_criteria": ["SC-001", "SC-002", "SC-006"],
        "testable": True,
    },
    {
        "id": "FR-003",
        "requirement_type": "functional",
        "text": (
            "POST `/api/users/self/favorites/{recipe_slug}` MUST be idempotent. "
            "When no `UserToRecipe` row exists for (self.user.id, recipe.id), "
            "create one with `is_favorite = true`; when one exists, update its "
            "`is_favorite` to true. Re-POST MUST return 200 and the row count "
            "for (self.user.id, recipe.id) in `users_to_recipes` MUST remain "
            "exactly 1. Delegate the row create-or-update to "
            "`UserRatingsController.set_rating(self.user.id, slug, "
            "UserRatingUpdate(is_favorite=True))` so the existing "
            "`assert_user_change_allowed` invariant is preserved."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/ratings.py",
                [(54, 86)],
                ["set_rating", "assert_user_change_allowed",
                 "UserRatingUpdate", "is_favorite", "add_favorite"],
            ),
            cref(
                "mealie/repos/repository_users.py",
                [(78, 101)],
                ["RepositoryUserRatings", "get_by_user_and_recipe", "UserToRecipe"],
            ),
            cref(
                "mealie/db/models/users/user_to_recipe.py",
                [(17, 30)],
                ["UserToRecipe", "user_id_recipe_id_rating_key", "is_favorite"],
            ),
        ],
        "related_user_stories": ["US-1"],
        "related_success_criteria": ["SC-001"],
        "testable": True,
    },
    {
        "id": "FR-004",
        "requirement_type": "functional",
        "text": (
            "DELETE `/api/users/self/favorites/{recipe_slug}` MUST be idempotent. "
            "When a `UserToRecipe` row exists, set `is_favorite = false` and "
            "return 200; when no row exists, return 200 without raising. "
            "Delegate to `UserRatingsController.set_rating(self.user.id, slug, "
            "UserRatingUpdate(is_favorite=False))` to keep the storage path "
            "identical to FR-003."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/ratings.py",
                [(54, 86)],
                ["set_rating", "remove_favorite", "is_favorite",
                 "UserRatingUpdate"],
            ),
            cref(
                "mealie/repos/repository_users.py",
                [(78, 101)],
                ["RepositoryUserRatings", "get_by_user_and_recipe", "UserToRecipe"],
            ),
        ],
        "related_user_stories": ["US-2"],
        "related_success_criteria": ["SC-002"],
        "testable": True,
    },
    {
        "id": "FR-005",
        "requirement_type": "functional",
        "text": (
            "All favorite mutation and list endpoints MUST resolve recipes "
            "through `UserRatingsController.group_recipes.get_one(...)` (or the "
            "equivalent `BaseRecipeController.group_recipes` repository), which "
            "scopes lookups to the current user's group. Recipes outside the "
            "user's group MUST return 404 via `get_recipe_or_404`. The new self "
            "routes MUST reuse the same `group_recipes` repository pattern as "
            "the existing legacy `/api/users/{id}/favorites/{slug}` route — no "
            "global recipe lookup is permitted on these handlers."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/ratings.py",
                [(17, 42)],
                ["UserRatingsController", "group_recipes", "get_recipe_or_404",
                 "HTTPException"],
            ),
            cref(
                "mealie/routes/recipe/_base.py",
                [(37, 44)],
                ["BaseRecipeController", "group_recipes", "RepositoryRecipes"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-6"],
        "related_success_criteria": ["SC-006"],
        "testable": True,
    },
    {
        "id": "FR-006",
        "requirement_type": "functional",
        "text": (
            "Add a new endpoint `GET /api/users/self/favorites/recipes` "
            "returning `PaginationBase[RecipeSummary]` per the NC-002 "
            "recommended default. The existing `GET /api/users/self/favorites` "
            "endpoint at `mealie/routes/users/crud.py:38-40` returning "
            "`UserRatings[UserRatingSummary]` MUST stay unchanged in shape and "
            "behavior. The new endpoint MUST accept `page` and `per_page` query "
            "parameters wired through `PaginationQuery` "
            "(`mealie/schema/response/pagination.py:46`) and produce a "
            "`PaginationBase`-shaped response. If NC-002 is rejected, the new "
            "endpoint is dropped and the existing endpoint's response model is "
            "replaced per the NC-002 `if_rejected` block."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/crud.py",
                [(17, 40)],
                ["UserController", "BaseUserController", "user_router",
                 "get_logged_in_user_favorites", "UserRatingSummary"],
            ),
            cref(
                "mealie/schema/response/pagination.py",
                [(32, 58)],
                ["RequestQuery", "PaginationQuery", "PaginationBase",
                 "page", "per_page", "items"],
            ),
            cref(
                "mealie/repos/repository_users.py",
                [(78, 96)],
                ["RepositoryUserRatings", "get_by_user", "favorites_only",
                 "UserToRecipe"],
            ),
        ],
        "related_user_stories": ["US-3"],
        "related_success_criteria": ["SC-003"],
        "testable": True,
    },
    {
        "id": "FR-007",
        "requirement_type": "functional",
        "text": (
            "Extend `RecipeSummary` (and therefore `Recipe`, which inherits from "
            "it) in `mealie/schema/recipe/recipe.py` with two fields: "
            "`favorite_count: int` and `favorited: bool`. Default rules are "
            "scoped independently to close the old CONS-H-001 ambiguity: "
            "(a) `favorite_count` defaults to `0` only when the recipe has zero "
            "favorite rows under the NC-003 visibility model — for "
            "unauthenticated callers the count MUST still be computed and "
            "returned, not forced to 0; (b) `favorited` defaults to `false` "
            "when (i) the request is unauthenticated, OR (ii) no `UserToRecipe` "
            "row exists for the current `(user_id, recipe_id)` with "
            "`is_favorite = true`."
        ),
        "code_references": [
            cref(
                "mealie/schema/recipe/recipe.py",
                [(116, 175)],
                ["RecipeSummary", "MealieModel", "loader_options",
                 "recipe_yield_display"],
            ),
            cref(
                "mealie/schema/recipe/recipe.py",
                [(182, 190)],
                ["Recipe", "RecipeSummary", "recipe_ingredient"],
            ),
        ],
        "related_user_stories": ["US-4", "US-5"],
        "related_success_criteria": ["SC-005"],
        "testable": True,
    },
    {
        "id": "FR-008",
        "requirement_type": "functional",
        "text": (
            "Hydrate `favorited` and `favorite_count` via a query mechanism that "
            "projects values into the response (NOT via "
            "`RepositoryRecipes.column_aliases`, which only feeds ORDER BY and "
            "query-filter expressions — see ARCH-H-002). Implementation MUST "
            "use one of: (a) a SQLAlchemy `column_property` or "
            "`hybrid_property` on `RecipeModel` whose loader option is added to "
            "`RecipeSummary.loader_options()`; or (b) a post-query batched "
            "lookup keyed by the page's recipe ids, hydrated onto the "
            "`RecipeSummary` payloads in the recipe service or route layer. "
            "`favorited` MUST be derived from "
            "`UserToRecipe.user_id == self.user.id AND "
            "UserToRecipe.recipe_id == recipe.id AND "
            "UserToRecipe.is_favorite == true`. `favorite_count` MUST be the "
            "count of `UserToRecipe` rows for the recipe with `is_favorite = "
            "true`, under the visibility model fixed by NC-003."
        ),
        "code_references": [
            cref(
                "mealie/repos/repository_recipes.py",
                [(36, 52), (72, 93)],
                ["RepositoryRecipes", "column_aliases", "by_user",
                 "_get_rating_col_alias", "UserToRecipe"],
            ),
            cref(
                "mealie/db/models/recipe/recipe.py",
                [(42, 74)],
                ["RecipeModel", "favorited_by", "rating"],
            ),
            cref(
                "mealie/schema/recipe/recipe.py",
                [(168, 175)],
                ["loader_options", "joinedload", "RecipeModel"],
            ),
        ],
        "related_user_stories": ["US-4", "US-6"],
        "related_success_criteria": ["SC-005", "SC-006"],
        "testable": True,
    },
    {
        "id": "FR-009",
        "requirement_type": "non_functional",
        "text": (
            "Recipe list queries hydrating `favorited`/`favorite_count` MUST "
            "execute a bounded number of database queries that does NOT scale "
            "with page size. Concretely: for `GET /api/recipes?per_page=N` the "
            "total query count for favorite hydration MUST be at most a "
            "constant K (target K ≤ 3) regardless of N. The acceptable "
            "implementation shapes are: correlated EXISTS subquery, GROUP BY "
            "aggregate in the main SELECT, joined `column_property`, or a "
            "single batched lookup keyed by the page's recipe ids."
        ),
        "code_references": [
            cref(
                "mealie/routes/recipe/recipe_crud_routes.py",
                [(85, 90), (341, 345)],
                ["router", "UserAPIRouter", "RecipeController",
                 "BaseRecipeController", "get_all"],
            ),
            cref(
                "mealie/repos/repository_recipes.py",
                [(36, 52)],
                ["RepositoryRecipes", "column_aliases", "by_user"],
            ),
            cref(
                "mealie/repos/repository_recipes.py",
                [(220, 225)],
                ["page_all"],
            ),
        ],
        "related_user_stories": ["US-4"],
        "related_success_criteria": ["SC-004"],
        "testable": True,
    },
    {
        "id": "FR-010",
        "requirement_type": "functional",
        "text": (
            "`favorited`/`favorite_count` MUST be observable on at least one "
            "anonymous-readable recipe endpoint. Two valid implementation paths: "
            "(a) extend `PublicRecipesController` at "
            "`mealie/routes/explore/controller_public_recipes.py:21-31` to "
            "hydrate both fields on the public list and detail routes; or "
            "(b) migrate the authenticated `RecipeController` routes from "
            "`UserAPIRouter` (which forces `Depends(get_current_user)` and "
            "returns 401 to anonymous callers per "
            "`mealie/routes/_base/routers.py:20-24`) to "
            "`Depends(try_get_current_user)` so the same handler serves both "
            "anonymous and authenticated callers. The implementer MUST choose "
            "exactly one path and add an integration test asserting an "
            "anonymous GET returns 200 with `favorited = false` and the real "
            "`favorite_count`."
        ),
        "code_references": [
            cref(
                "mealie/routes/explore/controller_public_recipes.py",
                [(17, 31)],
                ["router", "APIRouter", "PublicRecipesController",
                 "BasePublicHouseholdExploreController",
                 "cross_household_recipes"],
            ),
            cref(
                "mealie/routes/_base/routers.py",
                [(20, 25)],
                ["UserAPIRouter", "APIRouter", "get_current_user"],
            ),
            cref(
                "mealie/core/dependencies/dependencies.py",
                [(77, 86)],
                ["try_get_current_user", "oauth2_scheme_soft_fail",
                 "get_current_user"],
            ),
            cref(
                "mealie/routes/_base/base_controllers.py",
                [(132, 140)],
                ["BaseUserController", "get_current_user"],
            ),
        ],
        "related_user_stories": ["US-5"],
        "related_success_criteria": ["SC-005"],
        "testable": True,
    },
    {
        "id": "FR-011",
        "requirement_type": "functional",
        "text": (
            "The existing legacy routes `POST/DELETE/GET "
            "/api/users/{id}/favorites/...` MUST keep their current request and "
            "response contracts; both legacy and new self routes MUST delegate "
            "to the same `RepositoryUserRatings.create`/`update` call path so "
            "the (user_id, recipe_id, is_favorite) row state is identical "
            "whichever route is used. The existing parametrized test "
            "`test_user_recipe_favorites[use_self_route=False]` MUST continue "
            "to pass without modification."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/ratings.py",
                [(49, 86)],
                ["get_favorites", "add_favorite", "remove_favorite",
                 "set_rating", "is_favorite"],
            ),
            cref(
                "mealie/repos/repository_users.py",
                [(78, 101)],
                ["RepositoryUserRatings", "get_by_user", "get_by_recipe",
                 "get_by_user_and_recipe"],
            ),
        ],
        "related_user_stories": ["US-8"],
        "related_success_criteria": ["SC-007"],
        "testable": True,
    },
    {
        "id": "FR-012",
        "requirement_type": "functional",
        "text": (
            "Implementation MUST follow the three-layer pattern input §4 "
            "requires: HTTP routes in `mealie/routes/users/` (favorite write/list) "
            "and `mealie/routes/recipe/` (recipe response hydration) delegate to "
            "a service module under `mealie/services/user_services/` "
            "(create the directory if absent) for favorite write/list business "
            "logic, which in turn calls the repository layer "
            "(`mealie/repos/repository_users.py` `RepositoryUserRatings` or a "
            "new `mealie/repos/repository_favorites.py`). The recipe-side "
            "hydration MAY route through the existing "
            "`mealie/services/recipe/recipe_service.py` `RecipeService`. No "
            "favorite SQL or favorite-domain logic is permitted in route "
            "handlers."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/ratings.py",
                [(78, 86)],
                ["add_favorite", "remove_favorite", "set_rating"],
            ),
            cref(
                "mealie/repos/repository_users.py",
                [(78, 101)],
                ["RepositoryUserRatings", "GroupRepositoryGeneric",
                 "UserToRecipe"],
            ),
            cref(
                "mealie/routes/recipe/_base.py",
                [(37, 53)],
                ["BaseRecipeController", "recipes", "group_recipes", "service",
                 "RecipeService"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-3"],
        "related_success_criteria": ["SC-013"],
        "testable": True,
    },
    {
        "id": "FR-013",
        "requirement_type": "functional",
        "text": (
            "Pydantic request/response models for the new self favorite "
            "endpoints (and any new shared favorite types) MUST live at "
            "`mealie/schema/user/user_favorites.py` per input §4. The recipe "
            "response field additions (`favorited`, `favorite_count`) stay on "
            "`RecipeSummary` in `mealie/schema/recipe/recipe.py` per FR-007 "
            "because they are recipe-scoped, not user-scoped."
        ),
        "code_references": [
            cref(
                "mealie/schema/recipe/recipe.py",
                [(116, 130)],
                ["RecipeSummary", "MealieModel"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-3"],
        "related_success_criteria": ["SC-014"],
        "testable": True,
    },
    {
        "id": "FR-014",
        "requirement_type": "functional",
        "text": (
            "All user-facing error messages introduced by this feature MUST be "
            "routed through `self.t(\"<key>\")` keys defined in "
            "`mealie/lang/messages/en-US.json` (the file is JSON, not YAML as "
            "input §4 states). The implementation MUST NOT introduce any new "
            "hardcoded English strings in 4xx responses. Existing pattern: "
            "`mealie/routes/users/crud.py:47,51` uses "
            "`self.t(\"user.ldap-update-password-unavailable\")` etc. "
            "Translations for the non-English locale files under "
            "`mealie/lang/messages/*.json` are out of scope (see Out of Scope)."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/crud.py",
                [(42, 60)],
                ["self.t", "update_password", "ErrorResponse"],
            ),
            cref(
                "mealie/lang/messages/en-US.json",
                [(1, 10)],
                ["generic", "server-error", "recipe"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-6"],
        "related_success_criteria": ["SC-008"],
        "testable": True,
    },
    {
        "id": "FR-015",
        "requirement_type": "functional",
        "text": (
            "Add a new Alembic migration that alters the existing "
            "`users_to_recipes` foreign keys to `ON DELETE CASCADE` on BOTH "
            "`recipe_id` (FK to `recipes.id`) AND `user_id` (FK to `users.id`). "
            "The current FK declarations in migration `d7c6efd2de42` at lines "
            "164-171 use bare `sa.ForeignKeyConstraint([...], [...])` with no "
            "`ondelete` keyword, so neither database-level cascade fires today. "
            "This FR is required by input §1 (`级联删除`) and by US-7. The new "
            "migration MUST handle the SQLite path via "
            "`op.batch_alter_table(\"users_to_recipes\")` (matching the "
            "pattern at lines 190-191 of the cited migration)."
        ),
        "code_references": [
            cref(
                "mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py",
                [(153, 195)],
                ["upgrade", "users_to_recipes", "ForeignKeyConstraint",
                 "recipe_id", "user_id", "batch_alter_table"],
            ),
            cref(
                "mealie/db/models/users/user_to_recipe.py",
                [(17, 30)],
                ["UserToRecipe", "user_id", "recipe_id", "ForeignKey"],
            ),
        ],
        "related_user_stories": ["US-7"],
        "related_success_criteria": ["SC-009", "SC-011"],
        "testable": True,
    },
    {
        "id": "FR-016",
        "requirement_type": "functional",
        "text": (
            "Extend `RepositoryUsers.delete` at "
            "`mealie/repos/repository_users.py:55-65` to explicitly "
            "`sa.delete(UserToRecipe).where(UserToRecipe.user_id == value)` "
            "BEFORE calling `super().delete(...)`, mirroring the existing "
            "recipe-side pattern in `RepositoryRecipes._delete_recipe` at "
            "`mealie/repos/repository_recipes.py:110-128` which already deletes "
            "`UserToRecipe` rows before deleting the recipe. This is the "
            "application-layer half of US-7 and runs even on backends where "
            "FK ON DELETE CASCADE (FR-015) is not honored at the database "
            "level."
        ),
        "code_references": [
            cref(
                "mealie/repos/repository_users.py",
                [(18, 65)],
                ["RepositoryUsers", "delete", "PrivateUser", "shutil"],
            ),
            cref(
                "mealie/repos/repository_recipes.py",
                [(110, 130)],
                ["_delete_recipe", "UserToRecipe", "sa.delete"],
            ),
            cref(
                "mealie/db/models/users/user_to_recipe.py",
                [(17, 30)],
                ["UserToRecipe", "user_id"],
            ),
        ],
        "related_user_stories": ["US-7"],
        "related_success_criteria": ["SC-009"],
        "testable": True,
    },
    {
        "id": "FR-017",
        "requirement_type": "functional",
        "text": (
            "The new Alembic migration for FR-015 MUST use the existing "
            "filename convention "
            "`YYYY-MM-DD-HH.MM.SS_<revision_hash>_<snake_case_description>.py` "
            "(example: `2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py`). "
            "The revision hash MUST be the new alembic revision id generated "
            "by `alembic revision`, the `down_revision` MUST point at the "
            "current head, and the file MUST be placed under "
            "`mealie/alembic/versions/`."
        ),
        "code_references": [
            cref(
                "mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py",
                [(153, 195)],
                ["upgrade", "users_to_recipes"],
            ),
        ],
        "related_user_stories": ["US-7"],
        "related_success_criteria": ["SC-011"],
        "testable": True,
    },
    {
        "id": "FR-018",
        "requirement_type": "functional",
        "text": (
            "Every new endpoint (FR-002, FR-006) MUST be defined with a "
            "FastAPI `response_model=` argument matching its Pydantic schema "
            "and MUST include a docstring describing the operation. The "
            "auto-generated OpenAPI spec MUST cover both new endpoints; no "
            "manual edits to `frontend/app/lib/api/types/` are permitted "
            "(generation runs via `task dev:generate`)."
        ),
        "code_references": [
            cref(
                "mealie/routes/users/crud.py",
                [(17, 40)],
                ["UserController", "response_model", "user_router",
                 "get_logged_in_user"],
            ),
            cref(
                "mealie/routes/users/ratings.py",
                [(44, 86)],
                ["response_model", "UserRatings", "UserRatingOut",
                 "add_favorite", "remove_favorite"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-3"],
        "related_success_criteria": ["SC-012"],
        "testable": True,
    },
    {
        "id": "FR-019",
        "requirement_type": "functional",
        "text": (
            "Test coverage MUST meet input §5 minimums. Under "
            "`tests/unit_tests/` add at least 3 tests covering "
            "`RepositoryUserRatings` add/remove/list. Under "
            "`tests/integration_tests/user_recipe_tests/` add at least 6 tests "
            "covering: (a) self POST then re-POST returns 200 and row count == "
            "1; (b) self DELETE then re-DELETE returns 200; (c) anonymous "
            "list-recipes returns `favorited = false` always; (d) cross-group "
            "POST returns 404; (e) post-favorite `favorite_count` increments; "
            "(f) post-DELETE recipe cascade-removes favorites; (g) pagination "
            "returns the right slice. Under `tests/multitenant_tests/` add at "
            "least 2 tests covering: (i) household A user cannot see "
            "household B user's favorites; (ii) cross-group recipes are not "
            "visible to a non-member's favorites attempt."
        ),
        "code_references": [
            cref(
                "tests/fixtures/fixture_users.py",
                [(17, 56)],
                ["build_unique_user", "TestUser"],
            ),
            cref(
                "tests/fixtures/fixture_recipe.py",
                [(32, 90)],
                ["recipe_ingredient_only", "recipes_ingredient_only"],
            ),
            cref(
                "tests/multitenant_tests/test_multitenant_cases.py",
                [(23, 60)],
                ["test_multitenant_cases_get_all"],
            ),
            cref(
                "tests/integration_tests/user_recipe_tests/test_recipe_ratings.py",
                [(42, 96)],
                ["test_user_recipe_favorites", "use_self_route",
                 "users_self_favorites"],
            ),
        ],
        "related_user_stories": ["US-1", "US-2", "US-3", "US-4", "US-5",
                                 "US-6", "US-7"],
        "related_success_criteria": ["SC-010"],
        "testable": True,
    },
]

# ---------------------------------------------------------------------------
# Success criteria — every SC links to ≥1 FR (B3)
# ---------------------------------------------------------------------------
success_criteria = [
    {
        "id": "SC-001",
        "text": "Self favorite POST is idempotent under sequential repeat",
        "metric": "row count in users_to_recipes plus HTTP status of the second POST",
        "threshold": "second POST returns HTTP 200 and row count for (user_id, recipe_id) equals 1",
        "technology_agnostic": True,
        "related_requirements": ["FR-001", "FR-002", "FR-003"],
    },
    {
        "id": "SC-002",
        "text": "Self favorite DELETE is idempotent under sequential repeat",
        "metric": "is_favorite value and HTTP status of the second DELETE",
        "threshold": "second DELETE returns HTTP 200 and is_favorite equals false (or row absent)",
        "technology_agnostic": True,
        "related_requirements": ["FR-001", "FR-002", "FR-004"],
    },
    {
        "id": "SC-003",
        "text": "Self favorite recipe list at the new path is paginated correctly",
        "metric": "response shape and item slicing under page=1/per_page=50 then page=2/per_page=50 with 60 seeded favorites",
        "threshold": "first page items length equals 50, second page items length equals 10, total equals 60, response contains page per_page total total_pages items next previous fields",
        "technology_agnostic": True,
        "related_requirements": ["FR-006"],
    },
    {
        "id": "SC-004",
        "text": "Recipe list hydration of favorited and favorite_count is bounded query count",
        "metric": "number of SQL queries issued by GET /api/recipes?per_page=N attributable to favorite hydration, measured with N=10 and N=50",
        "threshold": "favorite-hydration query count is at most 3 and does not increase between N=10 and N=50",
        "technology_agnostic": True,
        "related_requirements": ["FR-008", "FR-009"],
    },
    {
        "id": "SC-005",
        "text": "favorited and favorite_count are correct for authenticated and anonymous callers",
        "metric": "field values returned by GET /api/recipes/{slug} and the anonymous-readable path chosen in FR-010",
        "threshold": "favoriting user sees favorited equals true and favorite_count greater than or equal to 1; other authenticated users see favorited equals false and the same favorite_count; anonymous caller sees favorited equals false and favorite_count equals the value from the visibility model fixed by NC-003",
        "technology_agnostic": True,
        "related_requirements": ["FR-007", "FR-008", "FR-010"],
    },
    {
        "id": "SC-006",
        "text": "Cross-group and cross-household isolation holds for favorites",
        "metric": "HTTP status of POST self favorite against a foreign-group recipe slug, plus presence of foreign-group recipes in self favorites list",
        "threshold": "POST returns HTTP 404 and zero foreign-group recipes appear in any authenticated user self favorites list",
        "technology_agnostic": True,
        "related_requirements": ["FR-005", "FR-008"],
    },
    {
        "id": "SC-007",
        "text": "Legacy /api/users/{id}/favorites/{slug} routes remain backward compatible",
        "metric": "pass status of the existing parametrized test_user_recipe_favorites with use_self_route equals False after the change",
        "threshold": "all use_self_route equals False assertions pass without modification",
        "technology_agnostic": True,
        "related_requirements": ["FR-011"],
    },
    {
        "id": "SC-008",
        "text": "All new 4xx error messages flow through the i18n provider",
        "metric": "grep across mealie/routes/users and mealie/routes/recipe for new hardcoded English error strings introduced by this feature",
        "threshold": "zero new hardcoded English error strings; every new HTTPException detail uses self.t(<key>) where the key exists in mealie/lang/messages/en-US.json",
        "technology_agnostic": True,
        "related_requirements": ["FR-014"],
    },
    {
        "id": "SC-009",
        "text": "Cascade cleanup works for both recipe-delete and user-delete paths",
        "metric": "row count of UserToRecipe entries referencing a deleted parent after DELETE recipe and DELETE user flows complete",
        "threshold": "zero UserToRecipe rows reference a deleted recipe id and zero rows reference a deleted user id",
        "technology_agnostic": True,
        "related_requirements": ["FR-015", "FR-016"],
    },
    {
        "id": "SC-010",
        "text": "Test count minimums from input §5 are met",
        "metric": "count of new test functions under tests/unit_tests, tests/integration_tests/user_recipe_tests, and tests/multitenant_tests attributable to this feature",
        "threshold": "unit count greater than or equal to 3, integration count greater than or equal to 6, multitenant count greater than or equal to 2",
        "technology_agnostic": True,
        "related_requirements": ["FR-019"],
    },
    {
        "id": "SC-011",
        "text": "New Alembic migration filename matches the existing convention",
        "metric": "regex match of the new migration filename against the convention YYYY-MM-DD-HH.MM.SS_<hash>_<snake>.py",
        "threshold": "filename matches the regex and the file lives under mealie/alembic/versions/",
        "technology_agnostic": True,
        "related_requirements": ["FR-015", "FR-017"],
    },
    {
        "id": "SC-012",
        "text": "OpenAPI spec covers both new endpoints with response_model and docstring",
        "metric": "presence of the two new operations in the generated openapi.json with non-empty description and a non-default response schema",
        "threshold": "both POST /api/users/self/favorites/{recipe_slug} and GET /api/users/self/favorites/recipes appear in openapi.json with response_model schemas and descriptions",
        "technology_agnostic": True,
        "related_requirements": ["FR-018"],
    },
    {
        "id": "SC-013",
        "text": "Three-layer pattern is observed for new favorite logic",
        "metric": "presence of a mealie/services/user_services/ module with favorite write/list logic AND absence of direct repository or SQL calls in the new route handlers",
        "threshold": "the new service module exists and is imported by the new route handlers; new route handlers contain zero direct SQLAlchemy session calls",
        "technology_agnostic": True,
        "related_requirements": ["FR-012"],
    },
    {
        "id": "SC-014",
        "text": "Pydantic favorite schemas live at the required path",
        "metric": "existence and contents of mealie/schema/user/user_favorites.py",
        "threshold": "the file exists and contains at least the request/response models used by the new self favorite endpoints",
        "technology_agnostic": True,
        "related_requirements": ["FR-013"],
    },
]

# ---------------------------------------------------------------------------
# Key entities
# ---------------------------------------------------------------------------
key_entities = [
    {
        "name": "UserToRecipe (extended)",
        "description": (
            "Existing association model in `users_to_recipes` "
            "(`mealie/db/models/users/user_to_recipe.py:17-30`). Holds "
            "`user_id`, `recipe_id`, `is_favorite`, `rating`, `id`, "
            "`created_at`, `updated_at`. Canonical favorite storage under the "
            "NC-001 default. After FR-015 its FKs gain ON DELETE CASCADE."
        ),
        "fields": ["user_id (GUID FK users.id)", "recipe_id (GUID FK recipes.id)",
                   "is_favorite (bool, indexed)", "rating (float)", "id (GUID)",
                   "created_at (datetime)", "updated_at (datetime)"],
        "references": ["User", "RecipeModel"],
    },
    {
        "name": "Recipe favorite response metadata",
        "description": (
            "Two new response-only fields on `RecipeSummary` (and `Recipe` via "
            "inheritance): `favorited: bool` (current request user's favorite "
            "state, false for anonymous) and `favorite_count: int` (count "
            "under the visibility model fixed by NC-003)."
        ),
        "fields": ["favorited: bool", "favorite_count: int"],
        "references": ["RecipeSummary", "Recipe"],
    },
    {
        "name": "Self favorite recipe-list response",
        "description": (
            "`PaginationBase[RecipeSummary]` returned by the new "
            "`GET /api/users/self/favorites/recipes` endpoint (NC-002 default). "
            "Items are `RecipeSummary` rows filtered to "
            "`UserToRecipe.user_id == current_user.id AND is_favorite = true` "
            "and bounded by the current user's group/household visibility."
        ),
        "fields": ["page: int", "per_page: int", "total: int", "total_pages: int",
                   "items: list[RecipeSummary]", "next: str | None",
                   "previous: str | None"],
        "references": ["PaginationBase", "RecipeSummary"],
    },
    {
        "name": "UserFavoriteRequest / UserFavoriteOut (new)",
        "description": (
            "New Pydantic models living at "
            "`mealie/schema/user/user_favorites.py` per FR-013. Wraps any "
            "favorite-specific request/response payloads (e.g., a typed empty "
            "request body for the POST self route, or a thin wrapper around "
            "`UserToRecipe` for internal use). Recipe-side fields stay on "
            "`RecipeSummary` per FR-007."
        ),
        "fields": [],
        "references": ["RecipeSummary", "UserToRecipe"],
    },
]

# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
edge_cases = [
    {
        "description": (
            "Idempotent POST of an already-favorited recipe by the same user"
        ),
        "handling": (
            "return HTTP 200 with the existing favorite state intact; no "
            "second `UserToRecipe` row is inserted (FR-003)"
        ),
    },
    {
        "description": "DELETE of a recipe the user never favorited",
        "handling": (
            "return HTTP 200 with `is_favorite = false` and no error response "
            "(FR-004)"
        ),
    },
    {
        "description": "POST or DELETE self favorite for a recipe outside the user's group",
        "handling": "return HTTP 404 via `get_recipe_or_404` (FR-005, US-6)",
    },
    {
        "description": "Recipe is deleted while it has favorite rows",
        "handling": (
            "`RepositoryRecipes._delete_recipe` already deletes UserToRecipe "
            "rows; FR-015 additionally adds ON DELETE CASCADE on the FK so "
            "raw SQL deletes also clean up (US-7 AC1)"
        ),
    },
    {
        "description": "User is deleted while owning favorite rows",
        "handling": (
            "FR-016 extends `RepositoryUsers.delete` to delete UserToRecipe "
            "rows for that user first; FR-015 also adds ON DELETE CASCADE on "
            "the user_id FK (US-7 AC2)"
        ),
    },
    {
        "description": "Anonymous GET to a public recipe endpoint",
        "handling": (
            "`favorited` is returned as false and `favorite_count` is the "
            "non-zero real count per FR-007 default (a) and FR-010 (US-5)"
        ),
    },
    {
        "description": (
            "`GET /api/users/self/favorites` already exists returning rating "
            "summaries (UserRatings[UserRatingSummary])"
        ),
        "handling": (
            "NC-002 default keeps the old route unchanged and adds the "
            "recipe-list at the new path `/api/users/self/favorites/recipes`"
        ),
    },
    {
        "description": "Concurrent POSTs to the same self favorite slug from the same user",
        "handling": (
            "The existing `set_rating` path reads then writes (no UPSERT), so "
            "two concurrent inserts can race against the "
            "`user_id_recipe_id_rating_key` UniqueConstraint; the loser "
            "raises IntegrityError translated to HTTP 500. This pre-existing "
            "behavior is preserved; SC-001 asserts only sequential idempotency"
        ),
    },
    {
        "description": "`favorite_count` for a private recipe under NC-003 default",
        "handling": (
            "the count is the global tally of `UserToRecipe` rows for the "
            "recipe; the recipe endpoint itself returns 404 to non-members, "
            "so unauthorized callers cannot observe the count for hidden "
            "recipes"
        ),
    },
    {
        "description": (
            "Existing `UserToRecipe` after_insert/after_update/after_delete "
            "event listener at "
            "`mealie/db/models/users/user_to_recipe.py:46-49` fires on every "
            "favorite toggle"
        ),
        "handling": (
            "the listener calls `update_recipe_rating` to flag a recipe rating "
            "recompute; favorite POST/DELETE pay this SELECT+UPDATE cost. "
            "FR-009 bounds total query count but does not eliminate this "
            "listener; if FR-009 implementation introduces a denormalized "
            "favorite_count column on `recipes`, it MUST hook into the same "
            "listener"
        ),
    },
]

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------
assumptions = [
    (
        "The NC-001 recommended default is accepted (reuse "
        "`UserToRecipe.is_favorite`). All FRs are written for that branch; "
        "the `if_rejected` block in NC-001 enumerates the FR rewrites for the "
        "alternative."
    ),
    (
        "The NC-002 recommended default is accepted (new endpoint at "
        "`/api/users/self/favorites/recipes`; legacy endpoint untouched)."
    ),
    (
        "The NC-003 recommended default is accepted (favorite_count is the "
        "global tally, bounded only by recipe visibility)."
    ),
    (
        "The backend API root is `/api`; route decorators may show paths "
        "relative to `/users` or `/recipes`."
    ),
    (
        "Frontend code changes are out of scope for this spec; the existing "
        "`RecipeFavoriteBadge.vue`, `RecipeCard.vue`, `RecipeCardMobile.vue`, "
        "and `pages/user/[id]/favorites.vue` continue to work because the "
        "legacy `/api/users/{id}/favorites/{slug}` and `/api/recipes` routes "
        "they call are preserved by FR-011 and FR-010."
    ),
    (
        "Non-English translation files under `mealie/lang/messages/*.json` "
        "are out of scope; only `en-US.json` must gain new keys for the new "
        "error messages."
    ),
    (
        "The integration test runner already exercises both SQLite and "
        "Postgres paths; FR-015's batch_alter_table approach is required to "
        "make the cascade migration SQLite-safe."
    ),
]

# ---------------------------------------------------------------------------
# Out of scope
# ---------------------------------------------------------------------------
out_of_scope = [
    (
        "Migrating the frontend client from `/api/users/{id}/favorites/{slug}` "
        "to the new self routes (FR-011 preserves the legacy contract for "
        "this reason)"
    ),
    (
        "Manual edits to `frontend/app/lib/api/types/` — these are "
        "generated by `task dev:generate` per FR-018"
    ),
    (
        "Reworking the rating feature beyond preserving "
        "favorite/rating coexistence on the same `UserToRecipe` row"
    ),
    (
        "Translating new error message keys into the non-English locale "
        "files under `mealie/lang/messages/*.json`"
    ),
    (
        "Adding household-level or shared favorites — favorites stay "
        "per-user per input scope"
    ),
    (
        "Adding a denormalized `favorite_count` column on `recipes` — the "
        "hydration mechanism (FR-008) computes it on read"
    ),
    (
        "Upgrading concurrent-POST idempotency to UPSERT — pre-existing "
        "behavior preserved per edge-case 8"
    ),
]

# ---------------------------------------------------------------------------
# Self-concerns (writer's residual uncertainty — NOT for input-vs-code
# conflicts, which go in needs_clarification per the C3/NEEDS_CLARIFICATION
# defense)
# ---------------------------------------------------------------------------
self_concerns = [
    {
        "location": "FR-008",
        "concern": (
            "The hydration shape (column_property vs hybrid_property vs "
            "post-query batched lookup) is intentionally left as a choice "
            "between three valid mechanisms. The implementer's choice affects "
            "the exact SQL but every option satisfies SC-004's bounded "
            "query-count threshold."
        ),
        "evidence_gap": (
            "No existing mealie precedent projects a user-specific bool field "
            "into RecipeSummary; the closest precedent is "
            "`_get_rating_col_alias` at repository_recipes.py:72-93 which is "
            "a sort/filter alias, not a projection. The three options were "
            "validated by inspecting the mechanism each one would use."
        ),
        "suggested_resolution": (
            "The implementer picks one of the three options at design time; "
            "the FR enumerates the acceptable shapes so the choice is "
            "constrained but not pre-committed."
        ),
    },
    {
        "location": "FR-010",
        "concern": (
            "Whether to extend the existing PublicRecipesController or "
            "migrate RecipeController to try_get_current_user is a "
            "controller-architecture choice with downstream implications for "
            "test setup and OpenAPI tag organization."
        ),
        "evidence_gap": (
            "Both controllers exist and both can host the hydration logic. "
            "The decision rests on whether the team wants to keep "
            "explore-vs-user-router separation or unify."
        ),
        "suggested_resolution": (
            "The implementer picks one path and writes the integration test "
            "specified in FR-010 against that chosen path."
        ),
    },
    {
        "location": "Edge case 10 (event listener)",
        "concern": (
            "Existing `update_recipe_rating` event listener on UserToRecipe "
            "adds a hidden SELECT+UPDATE cost on every favorite POST/DELETE. "
            "SC-004 measures recipe-list latency, not favorite-toggle "
            "latency, so this cost is not currently bounded by any SC."
        ),
        "evidence_gap": (
            "The listener at user_to_recipe.py:46-49 is unchanged by this "
            "spec; impact on favorite POST/DELETE latency was not measured."
        ),
        "suggested_resolution": (
            "If the listener cost becomes observable, add a follow-up SC for "
            "favorite-toggle latency; this spec preserves the existing "
            "behavior."
        ),
    },
]

# ---------------------------------------------------------------------------
# Assemble the Spec
# ---------------------------------------------------------------------------
spec_dict = {
    "schema_version": "1.0",
    "metadata": {
        "feature_id": "recipe-favorites-self-api",
        "title": "Recipe Favorites — Self-Service API (new pipeline)",
        "writer_model": "claude-sonnet-4.5",
        "reviewer_model": "n/a (new-pipeline single-shot, validator-checked)",
        "iterations": 1,
        "needs_review": False,
        "total_llm_calls": 0,
        "total_tool_calls": 0,
    },
    "summary": (
        "Mealie case-1 (recipe favorites) re-run under the NEW DevLoop "
        "pipeline. Goal: add authenticated self favorite routes and "
        "`favorited`/`favorite_count` fields on recipe responses while "
        "respecting the existing Mealie favorite storage on "
        "`UserToRecipe.is_favorite`. Three input-vs-code conflicts are "
        "surfaced as `needs_clarification` blocking decisions (storage model, "
        "self-favorites response contract, count visibility) so a human "
        "reviewer fixes them before coding. Functional requirements pin the "
        "concrete decisions: reuse the existing `users_to_recipes` table per "
        "NC-001, add a parallel `/api/users/self/favorites/recipes` endpoint "
        "per NC-002, count favorites globally bounded by recipe visibility "
        "per NC-003, hydrate the recipe response without N+1, add the "
        "missing FK cascade migration, mirror the deletion-cleanup path for "
        "users, keep all 4xx errors flowing through `self.t(...)` i18n, "
        "follow the three-layer routes/services/repos pattern, place new "
        "Pydantic schemas at `mealie/schema/user/user_favorites.py`, and "
        "meet input §5 test-count minimums (3 unit, 6 integration, 2 "
        "multitenant). Every functional FR is linked to a measurable SC "
        "and every P1 user story is claimed by a FR per the B3 trace-matrix "
        "rule."
    ),
    "needs_clarification": needs_clarification,
    "user_stories": user_stories,
    "functional_requirements": functional_requirements,
    "success_criteria": success_criteria,
    "key_entities": key_entities,
    "edge_cases": edge_cases,
    "assumptions": assumptions,
    "out_of_scope": out_of_scope,
    "self_concerns": self_concerns,
}


def main() -> int:
    print("=== validating Spec (A4 soft-language enforced via pydantic) ===")
    spec = Spec.model_validate(spec_dict)
    print(f"  A4 schema validation: PASS  ({len(spec.functional_requirements)} FRs, "
          f"{len(spec.success_criteria)} SCs, {len(spec.user_stories)} stories, "
          f"{len(spec.needs_clarification)} NCs)")

    print()
    print("=== A5 citation verifier ===")
    cit_problems = verify_spec_citations(MEALIE, spec)
    if cit_problems:
        for p in cit_problems:
            print(f"  - {p.fr_id} ref[{p.ref_index}] {p.path} {p.line_ranges}: "
                  f"{p.problem} — {p.detail}")
        print(f"  A5 citation verifier: {len(cit_problems)} PROBLEMS")
        return 1
    print("  A5 citation verifier: PASS (0 problems)")

    print()
    print("=== B3 trace matrix ===")
    gaps = find_trace_gaps(spec)
    if gaps:
        for g in gaps:
            print(f"  - [{g.kind}] {g.actor}: {g.detail}")
        print(f"  B3 trace gaps: {len(gaps)} GAPS")
        return 1
    print("  B3 trace gaps: PASS (0 gaps)")

    print()
    print("=== B1 md-json roundtrip ===")
    assert_spec_roundtrip_consistent(spec)
    print("  B1 roundtrip: PASS")

    print()
    print("=== writing artifacts ===")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spec_json_path = OUT_DIR / "spec.json"
    spec_md_path = OUT_DIR / "spec.md"
    spec_json_path.write_text(
        json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    spec_md_path.write_text(spec_to_markdown(spec), encoding="utf-8")
    print(f"  wrote {spec_json_path}")
    print(f"  wrote {spec_md_path}")

    print()
    print("=== final stats ===")
    print(f"FRs: {len(spec.functional_requirements)}")
    print(f"SCs: {len(spec.success_criteria)}")
    print(f"US: {len(spec.user_stories)}")
    print(f"NCs: {len(spec.needs_clarification)}")
    print(f"key_entities: {len(spec.key_entities)}")
    print(f"edge_cases: {len(spec.edge_cases)}")
    print(f"assumptions: {len(spec.assumptions)}")
    print(f"out_of_scope: {len(spec.out_of_scope)}")
    print(f"self_concerns: {len(spec.self_concerns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
