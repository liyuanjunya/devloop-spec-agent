# Consistency Review (v1)

## Verdict: NEEDS_REFINE

The spec is mostly self-consistent: terminology around `UserToRecipe` / `users_to_recipes` / `is_favorite` is tight, the legacy and new route paths are used consistently within their own scopes, and the Conservative approach lines up cleanly with FR-001/FR-002/FR-009/FR-010. Two issues block PASS: a hard contradiction inside US-3 about what `/api/users/self/favorites` returns (CONS-C-001), and an ambiguous default rule in FR-007 that conflicts with three other locations that promise a populated `favorite_count` for unauthenticated readers (CONS-H-001). A third issue is a missing FR for the cascade migration that US-6 AC3 actually requires (CONS-H-002).

## Terminology audit

| Term | Used in | Consistent? |
|---|---|---|
| `UserToRecipe` / `users_to_recipes` (canonical storage) | Summary, Existing-code findings, FR-001, FR-003, FR-004, FR-005, FR-008, Key Entities, Selected Approach, US-1/US-2 ACs | Yes — uniformly the canonical favorite store |
| `user_favorite_recipe` (the table NOT to add) | Summary, FR-001, Out of Scope, Approach's rejected "Aggressive" plan | Yes — uniformly "do not create" |
| `users_to_favorites` (the dropped legacy table) | Existing-code findings only | Yes — mentioned only as historical context |
| `POST/DELETE /api/users/self/favorites/{recipe_slug}` | US-1, US-2, FR-002, Edge Cases, Out of Scope, Independent tests | Yes |
| `GET /api/users/self/favorites` (list) | US-3 (description, independent test, AC1, AC2, AC4), FR-006, Edge Cases, Assumptions | **Internally inconsistent role — see CONS-C-001** |
| `/api/users/{id}/favorites/{slug}` (legacy single) | Existing-code findings, US-5, FR-010, SC-007 | Yes — consistently uses `{slug}` (legacy param) |
| `/api/users/{id}/favorites` (legacy list) | FR-010, SC-007 | Yes |
| `favorited` (response bool) | US-4 (all ACs), FR-007, FR-008, FR-011, SC-005, Edge Cases, Key Entities | Yes |
| `favorite_count` (response int) | US-4 (AC1–AC3), FR-007, FR-008, FR-009, SC-005, Edge Cases, Key Entities | Yes (but FR-007's default condition is ambiguous — see CONS-H-001) |
| `is_favorite` (UserToRecipe column) | FR-001, FR-003, FR-004, FR-008, Key Entities, US-1 AC1, US-2 AC1, US-3 description | Yes |
| Slug path param naming | Legacy routes use `{slug}`; new self routes use `{recipe_slug}` | Drift, but each is internally consistent within its route family — intentional and documented |

## Critical issues

- **CONS-C-001**: US-3 acceptance criteria 1 and 4 directly contradict each other on the response contract for `GET /api/users/self/favorites`, and the Assumptions section sides with AC4 against AC1.
  - **US-3 AC1** (`spec.md:40`, `spec.json` user_stories[2].acceptance[0]): "When they GET `/api/users/self/favorites`, Then the API returns a paginated recipe-summary collection."
  - **US-3 AC4** (`spec.md:43`): "compatibility must be explicitly resolved: **either retain a rating-summary alias** and add a documented recipe-list response path, or coordinate the response-model migration with generated clients."
  - **Assumption** (`spec.md:149`): "implementers **may use a temporary alias or compatibility response** only with explicit reviewer approval."
  - **Independent test** (`spec.md:38`): explicitly probes `GET /api/users/self/favorites?page=1&perPage=50` and verifies "only visible recipes favorited by the current user are returned" — only satisfiable if the path returns recipes.
  - If the implementer picks the "retain a rating-summary alias" branch from AC4 (which the Assumption sanctions), then `/api/users/self/favorites` will keep returning rating summaries and the recipe list lives at an undocumented different path — directly violating US-3 AC1 and the Independent test.
  - FR-006 inherits the same conflict: it mandates "a paginated self favorite recipe-list contract for `/api/users/self/favorites`" while simultaneously requiring "an explicit compatibility decision before changing the response model" (i.e., the model might not change at all).
  - SC-003 ("Self favorite list is paginated") is path-agnostic, so it does not catch this drift.
  - **Fix:** Pick one outcome before implementation, and write it into US-3 AC1, the Independent test, FR-006, and the Assumption simultaneously:
    1. Recipe-list at `/api/users/self/favorites` — drop the "retain a rating-summary alias" option from AC4, drop the "compatibility response" carve-out from Assumptions, and add an explicit FR-010-style backward-compatibility note for any existing rating-summary callers, or
    2. Recipe-list at a NEW path (e.g., `/api/users/self/favorite-recipes`) — rename US-3, FR-006, the Independent test, edge case, and SC-003 to reference the new path; keep `/api/users/self/favorites` returning ratings unchanged.

## High issues

- **CONS-H-001**: FR-007 default rule contradicts US-4 AC3, the unauthenticated-read Edge Case, and SC-005.
  - **FR-007** (`spec.md:96`, `spec.json` functional_requirements[6].text): "Add `favorited: bool` and `favorite_count: int` to recipe list/detail schemas, **defaulting to `false` and `0` when no authenticated user/favorites exist**."
  - Read in its plainest sense, the default conditions ("no authenticated user/favorites exist") apply to **both** fields, so an anonymous caller would receive `favorite_count = 0` regardless of how many favorites the recipe actually has.
  - **US-4 AC3** (`spec.md:51`): "Given an unauthenticated request to supported public recipe reads… `favorited=false` and **`favorite_count` is populated**."
  - **Edge case** (`spec.md:139`): "Unauthenticated GET /api/recipes → `favorited=false`, **`favorite_count` populated**."
  - **SC-005** (`spec.md:122`): "authenticated favoriting user sees `favorited=true`; other/anonymous users see `favorited=false`; **all see correct `favorite_count`**."
  - **FR-011** (`spec.md:112`): test scope includes "anonymous `favorited=false`" but tellingly says nothing about anonymous `favorite_count=0`, implying the writer's intent matched US-4 AC3, not the literal reading of FR-007.
  - Three sources (US-4, Edge Case, SC-005) demand a real count for anonymous callers; one source (FR-007) is naturally read to forbid it. Implementer needs an unambiguous rule.
  - **Fix:** Rewrite FR-007 to scope the two defaults independently, e.g., "`favorited` defaults to `false` when the request is unauthenticated **or** no `(user, recipe)` favorite row exists. `favorite_count` defaults to `0` **only** when no favorite rows exist for the recipe — it is always populated, including for unauthenticated requests, subject to the visibility scoping in FR-008."

- **CONS-H-002**: US-6 AC3 makes a deliverable commitment (a migration) that no FR captures.
  - **US-6 AC3** (`spec.md:68`, `spec.json` user_stories[5].acceptance[2]): "Given existing FK cascade behavior is insufficient, When implementing, Then **add the smallest migration needed to enforce cleanup on `users_to_recipes`**, not a new favorites table."
  - No FR covers this. FR-001 only **forbids** a new `user_favorite_recipe` table; it does not authorize or require a cascade migration on the existing table. FR-011 calls for "deletion cleanup" tests, which can only pass if the behavior exists — but the spec leaves the source of that behavior unspecified.
  - The `Related: US-1, US-2, US-6` mapping on FR-001 implies FR-001 is the home for US-6, but FR-001's text never addresses cascade behavior.
  - Self-concern #2 acknowledges the cascade behavior is uncertain in code, but uncertainty is not a substitute for an FR that captures the conditional deliverable.
  - **Fix:** Add an FR such as: "FR-012 [functional]: If FK cascade behavior on `users_to_recipes.user_id` or `users_to_recipes.recipe_id` does not remove rows when the parent `users` / `recipes` row is deleted, add the smallest Alembic migration to enforce `ON DELETE CASCADE` (or equivalent service-level cleanup). Do not introduce a new favorites table. Related: US-6."

## Medium issues

- **CONS-M-001**: FR-008 visibility scoping is undefined for unauthenticated callers, which the spec elsewhere explicitly supports.
  - **FR-008** (`spec.md:100`): `favorite_count` is computed "counting only visible/group-appropriate data."
  - **US-4 AC3** + Edge Case require `favorite_count` populated for **unauthenticated** requests, where there is no `current_user` and therefore no group to scope by.
  - The spec never defines what "visible/group-appropriate" means without an authenticated user. Implementer will have to invent semantics (count across all users? restrict to recipes that are publicly readable? restrict to the recipe's owning group?).
  - Self-concern #3 acknowledges this exact gap. The implementation cannot be made deterministic without resolution.
  - **Fix:** Define the unauthenticated visibility model in FR-008 explicitly (e.g., "for anonymous requests, `favorite_count` is the count of `is_favorite=true` rows whose recipe id matches the returned recipe, with no additional group filter beyond what the recipe endpoint itself enforces"), or reference the named visibility model already used by `mealie/routes/recipe/recipe_crud_routes.py` `get_one`/`get_all`.

- **CONS-M-002**: SC-004's headline and threshold are inconsistent on what counts as acceptable.
  - **SC-004** (`spec.md:121`): "GET /api/recipes p95 latency **does NOT regress** vs baseline after adding `favorited`/`favorite_count` (no N+1) | metric=p95 latency or query-count test on a seeded page | threshold=**≤10% p95 regression** or bounded query count independent of page size."
  - "Does NOT regress" is a 0% bound; "≤10% p95 regression" allows up to 10% slowdown. Either reword the headline ("does not significantly regress") to match the 10% tolerance, or tighten the threshold to "0% regression / no detectable p95 increase".
  - Soft issue (this is a common SLO pattern), but the two statements should not directly contradict each other in the same SC.

- **CONS-M-003**: spec.md ↔ spec.json divergence on US-3 acceptance #3.
  - spec.md (`:42`): "those recipes are not included unless also favorited by the current user **and visible in the current group**."
  - spec.json (`user_stories[2].acceptance[2]`): "only current-user visible favorites are included."
  - The spec.json wording drops the explicit group-visibility constraint, leaving "visible" undefined. Downstream consumers reading only the JSON (e.g., implement/test agents) could miss the group-scoping requirement that the markdown asserts.
  - **Fix:** Align the spec.json clause with the spec.md clause (preferred — more specific).

- **CONS-M-004**: spec.md ↔ spec.json divergence on Edge Cases.
  - The spec.md edge case "`favorite_count` for private/hidden recipes → count only within the recipe visibility model used by the recipe endpoint" (`spec.md:141`) is **absent** from `spec.json.edge_cases`. This is the same scoping question raised in CONS-M-001 and will be lost to any tool that consumes only the JSON.
  - **Fix:** Add the missing edge case to `spec.json.edge_cases`.

## Self-concerns verdicts

- **Self-concern 1** (US-3/FR-006 self-list route conflict): **Valid; identifies the real contradiction in CONS-C-001.** The writer correctly flagged the conflict but deferred resolution to the reviewer. Implementation cannot proceed deterministically until a branch is chosen.
- **Self-concern 2** (US-6/FR-001 cascade behavior uncertain): **Valid; same gap as CONS-H-002.** Implementer-time verification of FK behavior is reasonable, but the spec still owes an FR that commits to the migration deliverable that US-6 AC3 mandates.
- **Self-concern 3** (US-4/FR-008 `favorite_count` visibility): **Valid; same gap as CONS-M-001.** The concern's framing (group vs global vs household-scoped) is exactly what FR-008 should resolve before implementation picks arbitrarily.
- **Self-concern 4** (US-4/FR-007 optional-auth wiring): **Valid, but implementation-level, not a spec consistency defect.** Whether `try_get_current_user` is wired into recipe routes is a how-detail; the observable behavior is already captured in US-4 AC3 / Edge Case / SC-005 (and will be unambiguous once CONS-H-001 is resolved). No spec change required for this self-concern beyond CONS-H-001.

All four self-concerns reference real spec elements — none point at FRs, stories, fields, or entities that don't exist.

## Summary

The spec is internally consistent on storage, entities, and the Conservative approach: `UserToRecipe.is_favorite` is the single source of truth in every FR, entity, edge case, and assumption; the legacy `/api/users/{id}/favorites/{slug}` route is consistently described as backward-compatible; and the new `/api/users/self/favorites/{recipe_slug}` write paths line up across US-1/US-2/FR-002. The blocker is US-3, which simultaneously asserts that `GET /api/users/self/favorites` returns paginated recipes (AC1, Independent test, FR-006) and explicitly allows it to keep returning rating summaries (AC4, Assumptions) — only one of those can be true. Resolving that, tightening FR-007's default-condition wording so `favorite_count` matches US-4 AC3 / Edge Case / SC-005, and adding the missing cascade-migration FR demanded by US-6 AC3 should bring this spec to PASS.
