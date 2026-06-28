# Consolidated Exploration

## Summary
Mealie already appears to have user-recipe favorite concepts in both backend and frontend: explorers reported `UserToRecipe.is_favorite`, existing `/users/{id}/favorites/{slug}` endpoints, a `RecipeFavoriteBadge.vue`, and a user favorites page. The requested input, however, describes a new `user_favorite_recipe` table and new authenticated self endpoints, so the spec must decide whether to refactor existing behavior, add compatibility wrappers, or intentionally create a replacement system. Backend work still needs to preserve group/household isolation, avoid N+1 queries when adding `favorited` and `favorite_count`, and follow Mealie's migration/schema/repository/route/test conventions.

## Critical conflicts (must be addressed in the spec)
1. **Greenfield request vs existing favorites code**: The input requests a new `user_favorite_recipe` table and new `/api/users/self/favorites/{recipe_slug}` endpoints, but the Data/API/UI findings indicate an existing favorites implementation already exists (`UserToRecipe.is_favorite`, `/users/{id}/favorites/{slug}`, frontend favorite badge, and favorites page). This is not safely specifiable as pure greenfield without deciding whether to reuse, migrate, or replace the existing implementation.
   - Evidence: `input.md:17-31`; task prompt reports Data/API findings for `UserToRecipe.is_favorite` and `/users/{id}/favorites/{slug}`; `ui_perspective.md:6-16`; `ui_perspective.md:25-34`.
   - Possible resolutions: (a) treat the feature as a refactor/extension of existing favorites and avoid a new table unless justified; (b) add `/api/users/self/favorites/...` as compatibility/new self-service wrappers over the existing model; (c) introduce `user_favorite_recipe` as a replacement table with an explicit migration/backfill/deprecation plan for `UserToRecipe.is_favorite` and old endpoints.
2. **Persistence model conflict: boolean association field vs new join table**: Existing backend reportedly stores favorites on `UserToRecipe.is_favorite`, while the input mandates a dedicated `user_favorite_recipe` table with FKs, `created_at`, unique `(user_id, recipe_id)`, and `user_id` index. These are different data models with different migration, cascade, query, and compatibility implications.
   - Evidence: task prompt reports Data explorer found `UserToRecipe.is_favorite`; `input.md:17-23`; `input.md:36-37`; `input.md:52`.
   - Possible resolutions: (a) keep `UserToRecipe.is_favorite` and update spec to match existing schema; (b) create the new table and backfill from `UserToRecipe.is_favorite`; (c) keep both temporarily with one canonical write path and tests proving consistency.
3. **API path/naming conflict**: Existing API/UI appears to use user-id based paths like `/users/{id}/favorites/{slug}`, while the requested feature uses current-user self paths `/api/users/self/favorites/{recipe_slug}`. The spec must define canonical paths, compatibility behavior, auth semantics, and whether UI/API clients need updates.
   - Evidence: task prompt reports API explorer found `/users/{id}/favorites/{slug}`; `input.md:25-31`; `ui_perspective.md:8-16`; `ui_perspective.md:31-34`.
   - Possible resolutions: (a) preserve old `/users/{id}/favorites/{slug}` and add `/users/self/...` aliases; (b) migrate frontend client to `/api/users/self/favorites/...` and deprecate old endpoints; (c) reject new path and align the spec to existing route conventions.
4. **History perspective says greenfield, but static/UI perspectives found existing implementation**: The history perspective found no prior favorite/star/bookmark implementation in commit search and labeled it greenfield, which contradicts Data/API/UI findings. The spec should trust current code over commit-grep results and treat history as incomplete for this feature area.
   - Evidence: `history_perspective.md:37-40`; task prompt reports Data/API existing backend findings; `ui_perspective.md:6-16`.
   - Possible resolutions: (a) update the spec with a current-code discovery section; (b) require implementer to inspect existing model/routes before designing migration; (c) retain history conventions only for migration/test style, not for feature existence.
5. **Backend-only scope vs existing frontend dependency**: Confirmed intent excludes frontend implementation, but the existing UI client and components may already call favorite endpoints. Backend-only changes could break or strand existing UI unless compatibility or a frontend follow-up is specified.
   - Evidence: `confirmed.json:5-21`; `ui_perspective.md:3-16`; `ui_perspective.md:21-34`.
   - Possible resolutions: (a) keep UI out of scope but mandate backend compatibility with current UI calls; (b) include minimal API-client/type regeneration in scope; (c) explicitly create a follow-up UI migration task.

## Consolidated relevant artifacts

### Critical
- `mealie/db/models/**/UserToRecipe*` — Existing backend association/model reportedly already contains `is_favorite`; must be inspected before adding or replacing a `user_favorite_recipe` table.
- `mealie/routes/users/**` — Existing user favorites endpoints reportedly include `/users/{id}/favorites/{slug}` and conflict with the requested `/api/users/self/favorites/{recipe_slug}` contract.
- `frontend/app/lib/api/user/users.ts` — Existing frontend API client already has favorite endpoints; backend compatibility or client migration must be decided.
- `frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue` — Existing favorite toggle UI means favorites are not purely new from a product/code perspective.
- `frontend/app/pages/user/[id]/favorites.vue` — Existing user favorites page likely depends on old endpoint semantics and may need compatibility or migration.
- `mealie/schema/recipe/**` — Recipe list/detail schemas must expose `favorited` and `favorite_count` without breaking anonymous responses.
- `mealie/routes/recipe/recipe_crud_routes.py` — Recipe list/detail responses must be extended and query behavior must avoid N+1.
- `mealie/services/recipe/recipe_service.py` — Likely service layer touch point for adding current-user favorite state and aggregate counts to recipe responses.
- `tests/integration_tests/**` — Required for idempotent favorite/unfavorite, anonymous `favorited=false`, cross-group 404, favorite count, cascade cleanup, and pagination behavior.
- `tests/multitenant_tests/**` — Required to prove household/group isolation for favorites.

### Relevant
- `mealie/alembic/versions/` — If a new table or migration/backfill is chosen, follow existing timestamp/revision filename convention.
- `mealie/repos/repository_users.py` — Input suggests using or extending this repository layer for user favorite operations.
- `mealie/repos/repository_favorites.py` — Possible new repository if the spec chooses a dedicated favorite repository/table.
- `mealie/schema/user/user_favorites.py` — Requested location for Pydantic schemas if new self favorites API remains in scope.
- `mealie/routes/admin/admin_management_ai_providers.py` — History template example for recent table-backed route/controller feature structure.
- `mealie/routes/groups/controller_group_ai_providers.py` — History template example for route/controller organization and integration testing style.
- `mealie/schema/group/ai_providers.py` — History template example for Pydantic schema organization in a table-backed feature.
- `mealie/db/models/group/ai_providers.py` — History template example for DB model conventions.
- `mealie/repos/repository_ai_provider.py` — History template example for repository conventions.
- `mealie/alembic/versions/2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py` — Concrete migration naming/template example.
- `frontend/app/components/Domain/Recipe/RecipeCard.vue` — Existing recipe card favorite surface; relevant if frontend compatibility is tested or migrated.
- `frontend/app/components/Domain/Recipe/RecipeCardMobile.vue` — Existing mobile recipe card favorite surface; relevant for follow-up UI verification.
- `frontend/app/components/Domain/Recipe/RecipePage/RecipePageParts/RecipePageHeader.vue` — Existing recipe detail header/action surface for favorite state.
- `frontend/app/lib/api/types/` — Generated API types; do not edit manually if frontend API contract changes.
- `lang/messages/*.yaml` — Error messages should use Mealie i18n rather than hard-coded English.

## Consolidated conventions
- New table-backed features typically ship migration, DB model, repository, route/controller, schema, and integration/unit tests together in one PR.
- Alembic migration filenames use `YYYY-MM-DD-HH.MM.SS_<revision_hash>_<snake_case_desc>.py`.
- Household/group isolation should be enforced by service/query logic and proven in integration or multitenant tests.
- User-facing errors should use Mealie's i18n message files instead of hard-coded English.
- Pydantic/OpenAPI schemas and `response_model` definitions should be complete so FastAPI OpenAPI generation remains accurate.
- Recipe list enrichment must avoid N+1; fetch `favorited` and `favorite_count` with joins, `IN`, aggregate subqueries, or `EXISTS`.
- Frontend API types are generated from Pydantic/OpenAPI via `task dev:generate`; do not manually edit generated files under `frontend/app/lib/api/types/`.
- Frontend API clients live under `frontend/app/lib/api/` and extend `BaseAPI` / `BaseCRUDAPI`.
- Commit history suggests concise `feat:` / `fix:` PR-numbered commits, but current-code inspection is more reliable than grep history for feature existence.

## Cross-perspective open questions
- Is `UserToRecipe.is_favorite` the canonical current storage, and if so why is a new `user_favorite_recipe` table required?
- Should the new `/api/users/self/favorites/{recipe_slug}` endpoints be aliases over existing `/users/{id}/favorites/{slug}` endpoints, replacements, or a separate API version?
- If a new table is introduced, what is the migration/backfill plan for existing favorite data and how long should old endpoints/fields remain supported?
- Should `favorite_count` count all users globally, only users who can see the recipe, or only users in the recipe's group/household?
- Must the backend-only spec include compatibility tests for the existing frontend API client paths?
- Where exactly should repository ownership live: `repository_users.py`, a new `repository_favorites.py`, or the existing `UserToRecipe` repository pattern?
- Are the missing Data/API/Test perspective files expected to be regenerated before final spec writing, or should the Writer proceed with the prompt-provided findings plus available UI/History files?

## Source perspectives (provenance)
- data: 1 critical, 0 relevant (file missing at expected path; prompt-provided critical finding used: `UserToRecipe.is_favorite` existing)
- api: 1 critical, 0 relevant (file missing at expected path; prompt-provided critical finding used: `/users/{id}/favorites/{slug}` existing)
- test: 0 critical, 0 relevant (file missing at expected path; no direct counts available)
- history: 0 critical, 3 relevant convention/history findings
- ui: 5 critical, 4 relevant/future touch points

