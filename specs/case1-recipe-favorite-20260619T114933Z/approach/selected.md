# Selected Approach: Conservative reuse of `UserToRecipe`

## Candidate plans considered

1. **Conservative** — Reuse `users_to_recipes` / `UserToRecipe.is_favorite`; add missing `/api/users/self/favorites/{recipe_slug}` POST/DELETE wrappers; add a paginated self favorite recipe-list endpoint without changing storage; hydrate `favorited` and `favorite_count` on recipe responses via aggregate/exists queries.
2. **Balanced** — Same storage reuse, but introduce a dedicated favorite repository facade/service and formally deprecate user-id routes. This is cleaner architecturally but increases churn because ratings and favorites are currently coupled in `RepositoryUserRatings`.
3. **Aggressive** — Create a new `user_favorite_recipe` table and migrate/backfill from `UserToRecipe.is_favorite`, then deprecate the old field. This duplicates a migration Mealie already performed in 2024 and risks inconsistency.

## Selection

Choose **Conservative**. Current code already has canonical favorite persistence (`UserToRecipe.is_favorite`), existing repository methods, legacy user-id endpoints, a self favorites read route, frontend favorite UI, and a migration that explicitly consolidated the old favorites table into `users_to_recipes`. A new table would be wasteful and risky. The spec treats this feature as an extension/compatibility improvement, not a greenfield feature: add self-service write aliases, clarify the self favorite list response, and enrich recipe responses without N+1 queries while keeping existing routes operational.
