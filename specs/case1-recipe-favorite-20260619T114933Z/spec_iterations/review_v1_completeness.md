# Completeness Review (v1)

## Verdict: NEEDS_REFINE

The spec is thoughtful and well-grounded — it correctly surfaces the "existing favorites already live in `users_to_recipes`" conflict, decomposes the work into 6 prioritized user stories, gives each P1 story success + failure acceptance scenarios, and populates edge_cases / assumptions / out_of_scope / self_concerns instead of leaving them empty.

However, the spec **silently drops three explicit input requirements** (i18n, 3-layer pattern, exact Pydantic schema file path), **softens a fourth** (cascade-delete is conditional rather than committed), and **leaves the central data-model decision (new table vs. reuse) unresolved as the writer's call instead of a blocking reviewer decision**. Test minimums and migration-filename convention are also missing. This needs one focused refinement pass before it can drive coding.

## Coverage matrix (input requirement → spec coverage)

| Input requirement | Covered in spec? | Where |
|---|---|---|
| `user_favorite_recipe` table | ❌ Inverted — spec explicitly forbids it ("do not add in the default implementation") | FR-001, out_of_scope[0], assumptions[0] |
| Composite unique `(user_id, recipe_id)` | ✅ Already exists in code; spec inherits via reuse | FR-001 → `UserToRecipe.__table_args__` (`user_id_recipe_id_rating_key`) |
| Single `user_id` index | ✅ Already exists in code | FR-001 → `user_to_recipe.py:22` `index=True` |
| POST idempotency | ✅ | FR-003, US-1 AC#2, SC-001 |
| DELETE idempotency | ✅ | FR-004, US-2 AC#2, SC-002 |
| Cross-group 404 | ✅ | FR-005, US-1 AC#3, US-2 AC#3, SC-006 |
| Cascade delete recipe → favorites | ⚠ Acknowledged but not committed ("add migration only if current constraints insufficient") | US-6 AC#3, FR-001 narrative, edge_cases[3], self_concerns[1] |
| Cascade delete user → favorites | ⚠ Same softness | US-6 AC#2 |
| `favorited: bool` on responses | ✅ | FR-007, US-4 AC#1-3, SC-005 |
| `favorite_count: int` on responses | ✅ | FR-007, US-4, SC-005 |
| Anonymous `favorited=false` | ✅ + flagged for impl verification | US-4 AC#3, edge_cases[5], SC-005, self_concerns[3] |
| 3-layer pattern (routes → services → repos) | ❌ Service layer never mentioned | (gap — only `routes/` + `repos/` discussed) |
| i18n for errors (no hardcoded English) | ❌ Not mentioned anywhere | (gap — zero FR, zero SC, zero acceptance) |
| No N+1 | ✅ | FR-009, US-4 AC#4, SC-004 |
| 3+ unit tests | ⚠ Scenarios listed in FR-011 but no minimum count enforced | FR-011 |
| 6+ integration tests | ⚠ Same | FR-011 |
| 2+ multitenant tests | ⚠ Only one scenario described (cross-group); count not enforced | FR-011 |
| Pydantic schemas in `mealie/schema/user/user_favorites.py` | ❌ Not mentioned; this exact path is in the input | (gap) |
| Migration filename format matching alembic convention | ❌ Not mentioned | (gap) |
| OpenAPI / docstring / response_model | ❌ Not mentioned | (gap — input §6) |

## Critical issues

- **COMP-C-001 — i18n requirement completely absent from spec.** Input §4 mandates: *"错误信息使用 mealie 既有 i18n 体系（`lang/messages/*.yaml`），不写硬编码英文"*. The spec has zero FR, SC, or acceptance criterion for this. The 404 responses introduced by FR-005 and the idempotency responses by FR-003/FR-004 will need translator keys (`self.t(...)`), but nothing in the spec forces the implementer to add them — they will almost certainly hardcode English (the existing `ratings.py:39` route already does: `message="Not found."`). Add an FR like "All user-facing error messages MUST be routed through `self.t(...)` keys defined in `mealie/lang/messages/en-US.json`; the implementation MUST NOT introduce new hardcoded English strings in 4xx responses." Verified: lang files are JSON (not YAML as input mis-states — `mealie/lang/messages/en-US.json`), and `crud.py:47,51,63` show the established `self.t("user.xxx")` pattern.

- **COMP-C-002 — 3-layer pattern only covers 2 layers.** Input §4 mandates: *"必须遵循 mealie 三层模式：routes/users/ → services/user_services/ → repos/repository_users.py（或新建 `repository_favorites.py`）"*. The spec discusses routes (FR-002) and repository (FR-001, FR-008) but never mentions adding a service layer. Looking at the existing code, `ratings.py:54-86` is in fact route-direct-to-repo with no service in between, which suggests the implementer will follow that anti-pattern unless the spec explicitly calls for a `mealie/services/user_services/` module. Either (a) add an FR that requires a service layer for the new favorite write/list operations, or (b) explicitly document that this feature follows the existing rating pattern (no service layer) and update the input expectation in the spec. The current spec does neither.

- **COMP-C-003 — Central data-model decision (new table vs. reuse) is left as the writer's pick instead of a blocking reviewer decision.** Input §1 unambiguously says *"新增 `user_favorite_recipe` 表"*. FR-001 inverts this: *"do not add `user_favorite_recipe` in the default implementation"*. The spec documents the rationale (existing storage already does the job) in `assumptions[0]`, `out_of_scope[0]`, and `self_concerns[0]`, but treats reuse as the default and a new table as something a reviewer must opt back into. Given that the input is explicit, this should be inverted: either (a) the spec commits to the new table (and FR-001 specifies the migration + dual-write/cutover with `is_favorite`), or (b) the spec presents reuse vs. new-table as a Phase-0 reviewer decision blocking implementation. As written, an LLM implementer will quietly skip table creation and the test "user_favorite_recipe table exists with composite unique index" — which the input asks for — will be ungrounded.

## High issues

- **COMP-H-001 — FK `ON DELETE CASCADE` is not actually present in current code; spec wrongly assumes it might be sufficient.** Input §1 says cascade delete is part of the data model. Verified by inspection: `user_to_recipe.py:22-24` declares `ForeignKey("users.id")` / `ForeignKey("recipes.id")` with **no** `ondelete=` argument, and the migration at `2024-03-18-02.28.15_d7c6efd2de42...:164-171` likewise uses bare `sa.ForeignKeyConstraint`. The SQLAlchemy `cascade="all, delete, delete-orphan"` on `User.sp_args` (`users.py:84-93`) is **not** applied to `User.rated_recipes` or `User.favorite_recipes` (users.py:103-115 use a plain `orm.relationship(...)`), and `RecipeModel.favorited_by` has no cascade either. The spec's "add the smallest migration needed to enforce cleanup ... only if current constraints do not clean rows" (US-6 AC#3, edge_cases[3]) is too soft — the constraints empirically do not. Either upgrade to a hard FR requiring `ondelete="CASCADE"` on both `user_id` and `recipe_id` in a new migration, or add an FR that mandates ORM-level cascade on `User.favorite_recipes`/`RecipeModel.favorited_by` + an integration test that actually deletes a user/recipe and asserts the row is gone.

- **COMP-H-002 — Test counts from input are not enforced anywhere in the spec.** Input §5 specifies "**至少** 3 / 6 / 2". FR-011 lists scenarios but never says "at least N tests". SC-003's "at least 3 favorites" is about test data volume, not test count. Without explicit counts, an implementer satisfying only the listed scenarios might write 2 unit tests, 4 integration tests, 1 multitenant test, all of which "cover" what FR-011 enumerates but fail the input. Add per-category minimums to FR-011 or a new SC.

- **COMP-H-003 — Required Pydantic schema location (`mealie/schema/user/user_favorites.py`) not mentioned.** Input §4 specifies this exact path. Spec only references `mealie/schema/recipe/recipe.py` (for `favorited`/`favorite_count` field placement) and `mealie/schema/user/user.py` (existing `UserRating*` models). The new self-favorites recipe-list response and any new request/response models will land somewhere arbitrary unless the spec names the file. Add an FR that pins the file path.

- **COMP-H-004 — US-3 / FR-006 leaves the `/api/users/self/favorites` response-model conflict as "decide later" rather than committing to one of: rename, alias, version, or break.** This is the single biggest implementation ambiguity (the writer also flags it as `self_concerns[0]`). Verified at `crud.py:38-40`: the existing endpoint returns `UserRatings[UserRatingSummary]`, but the input asks for a paginated recipe list. SC-003 demands paginated recipe shape but doesn't say what to do with the existing shape. Decision must be in spec, not deferred to an implementer who has every incentive to silently break the old contract or pick a different path than what the next reviewer expects. Promote to a hard decision (suggest one of: (a) keep old route, add new `/api/users/self/favorites/recipes` for recipe list; or (b) break old route and update the one backend caller).

- **COMP-H-005 — Migration filename convention and OpenAPI/docstring requirement (input §4, §6) are silently dropped.** Lower-impact than i18n, but they're explicit input requirements that don't appear in any FR/SC.

## Medium issues

- **COMP-M-001 — US-6 (cascade-cleanup) is P2; input treats it as a P1 data-model invariant.** "外键 ... 级联删除" is in the input's #1 data model section, not "nice to have". Re-prioritize to P1 (or merge into FR-001).

- **COMP-M-002 — Anonymous auth wiring not elevated to FR.** US-4 AC#3 says anonymous users see `favorited=false`. Spec correctly notes in `self_concerns[3]` that this needs `try_get_current_user` wiring not present in current `/api/recipes` (which uses `self.user.id` via `BaseUserController`). Without an explicit FR, the implementer may add an optional-auth dependency wrong (e.g., 401 anonymous users instead of returning `favorited=false`). Add an FR: "Recipe read endpoints MUST allow unauthenticated requests; for anonymous callers, `favorited` MUST be returned as `false` and `favorite_count` MUST still be computed."

- **COMP-M-003 — `favorite_count` visibility semantics named as a self-concern but not picked.** `self_concerns[2]` says "spec assumes group/recipe endpoint visibility, but product may want global or household-scoped counts" — but the spec leaves all three options open. Pick one. The input says `favorite_count` is **public** ("**公开**返回 `favorite_count: int`"), which most naturally reads as "global count of all users who favorited this recipe across all groups" — not group-scoped as the spec currently assumes. Either confirm group-scoped (and explain why "public" doesn't mean cross-group) or switch to global. The reviewer's interpretation will matter; the writer's assumption can flip the SQL aggregate.

- **COMP-M-004 — N+1 SC is measurable in two contradictory ways.** SC-004 threshold reads *"≤10% p95 regression **or** bounded query count independent of page size"*. The "or" makes the SC un-failable: a 50% regression with a constant query count still passes, and a 5-query-per-recipe N+1 still passes if p95 happens to be within 10%. Pick one threshold or require both. Recommend: "bounded query count independent of page size" (testable in unit tests; "p95 latency" needs a baseline benchmark harness the spec doesn't define).

- **COMP-M-005 — Multitenant test scenarios undercounted vs. input.** Input §5 names two scenarios: "household A 的用户无法看到 household B 的用户的收藏" and "不同 group 的 recipe 互不可见". FR-011 says "multitenant isolation" + SC-006 says "cross-group favorite attempts return 404 and cross-tenant favorites do not leak in list/count state" — that's one composite. The input's two distinct scenarios (household-vs-household for favorite *visibility*, and group-vs-group for recipe *visibility*) should each be a separate testable scenario.

## Self-concerns verdicts

1. **`self_concerns[0]` — /api/users/self/favorites response-model conflict.** ✅ Real and important. Verified at `crud.py:38-40`. This is **COMP-H-004**; should be promoted from "writer uncertainty" to "blocking reviewer decision" in the next iteration.
2. **`self_concerns[1]` — FK cascade uncertainty.** ✅ Real. Verified by direct inspection (FK declarations have no `ondelete`; relationship `cascade` not applied to favorite/rated relationships at `users.py:103-115`). This is **COMP-H-001**; the answer is "constraints are insufficient — a migration is required", not "verify before adding".
3. **`self_concerns[2]` — `favorite_count` visibility semantics.** ✅ Real. This is **COMP-M-003**; the input's word "公开" (public) is the clue and should drive a decision.
4. **`self_concerns[3]` — optional-auth wiring for unauthenticated recipe reads.** ✅ Real. Current `BaseUserController` requires auth. This is **COMP-M-002**; should be an FR.

All four self-concerns are legitimate and well-targeted. None should be dropped. The first two should be resolved into hard requirements in v2 rather than left as concerns.

## Summary

The spec catches the hardest landmines (existing favorites code, response-shape collision on `/self/favorites`, N+1 risk, anonymous-user gap, FK cascade uncertainty) and gives every P1 story success + failure acceptance criteria — that's much stronger than the typical first draft. The blocker is that several explicit input requirements (**i18n, 3-layer service layer, exact schema file path, test minimums, migration naming, OpenAPI docstrings**) are silently dropped, the central new-table-vs-reuse decision is taken unilaterally by the writer instead of presented as a reviewer choice, and FK cascade (which is empirically broken in the current code) is downgraded from a hard requirement to a conditional one. Refine once to close the input-coverage gaps, commit the cascade migration, and elevate the two writer "self-concerns" that contradict the input from concerns to decisions — then this is ready.
