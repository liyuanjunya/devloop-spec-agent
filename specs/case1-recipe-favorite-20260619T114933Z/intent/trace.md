# Analyzer hypotheses

## H1 — User-level Recipe favorite/star feature across data model, API, and Recipe responses
Signals: input says Users want to favorite Recipes like a star, explicitly user-level not household-level; requires `user_favorite_recipe(user_id, recipe_id, created_at)` with unique `(user_id, recipe_id)`; requires POST/DELETE/GET under `/api/users/self/favorites`; requires `favorited` and `favorite_count` on `GET /api/recipes` and `GET /api/recipes/{slug}`. Skeleton confirms User and Recipe entities, `routes/users/`, `services/user_services/`, repositories, `PaginationQuery`, and multitenant tests.
Counter-indicators: none material; must avoid treating Recipe household ownership as favorite ownership.

## H2 — Household-level shared favorites for Recipes
Signals: Mealie centers Household collaboration, and grounding says Recipe belongs to Household; skeleton notes per-household filtering.
Counter-indicators: input explicitly says this is a User-level feature, not household-level, and the proposed table key is `user_id` + `recipe_id`.

## H3 — Favorites API only, without extending existing Recipe responses
Signals: the API table focuses on POST/DELETE/GET favorite endpoints under `/api/users/self/favorites`.
Counter-indicators: input has a separate “响应字段扩展” section requiring `favorited` and `favorite_count` in Recipe list/detail, and evaluation notes ask whether the system recognizes both new entity and existing Recipe response extension.

## H4 — Frontend favorite button/list implementation
Signals: the business wording is user-facing (“star”, “conveniently find”), which could imply UI affordances.
Counter-indicators: skeleton states frontend is out of scope for this case; all explicit requirements are backend/data/API/test/OpenAPI-oriented.

## H5 — Generic popularity/like count system not tied to authenticated User access
Signals: the spec asks for public `favorite_count`, which resembles popularity metrics.
Counter-indicators: the core model is User-to-Recipe, `favorited` is current-user-specific, endpoints require logged-in User, and visibility restrictions return 404 for inaccessible Recipes.

# Skeptic challenges

## H1
- What if “favorite_count” is meant as the primary feature and per-user favorites are just a secondary projection?
- Have you considered that Recipe is household-owned, so favorite visibility must still respect group/household access even though favorites are user-owned?

## H2
- What if household collaboration implies all household members should share one favorites list?
- Have you considered that the table has no `household_id`, so household-level state would be derived only through User/Recipe and is not the requested ownership boundary?

## H3
- What if the existing Recipe list/detail schemas cannot easily add computed fields, so only the favorites endpoint should expose them?
- Have you considered the explicit N+1 constraint for `GET /api/recipes`, which only matters if Recipe list responses are extended?

## H4
- What if “方便随时找到” requires navigation/UI changes, not just API support?
- Have you considered that OpenAPI/docstring completeness is requested but no frontend files, components, or e2e tests are requested?

## H5
- What if anonymous users should be able to favorite Recipes because `favorite_count` is public?
- Have you considered that unauthenticated users must receive `favorited: false`, which means the personalized favorite state requires authentication?

# Verifier verdicts

## H1 — confirmed
Evidence: input lines 13, 18-23, 29-31, 34-37, 41-44, 48-53, and 56-66 define exactly a user-level favorite feature spanning model, authenticated APIs, Recipe response extensions, architecture constraints, SQL performance, and tests. Grounding confirms User/Recipe/Group/Household terminology and the 3-layer architecture.

## H2 — rejected
Evidence: input explicitly states “用户级（不是 household 级）”; table uses `user_id`; endpoints are `/api/users/self/...`. Recipe household ownership affects visibility and cascade behavior, not favorite ownership.

## H3 — rejected
Evidence: input requires Recipe list/detail response fields and specifically says list must avoid N+1 via JOIN/IN/EXISTS. The evaluation section calls out the dual demand of new entity plus existing Recipe response extension.

## H4 — rejected
Evidence: repository skeleton marks `frontend/` out of scope for this case. Requested tests are unit/integration/multitenant backend tests; OpenAPI is auto-generated from FastAPI.

## H5 — rejected
Evidence: endpoints require logged-in User; `favorited` is defined for the current User and false for unauthenticated users; cross group/household inaccessible Recipes should return 404.

# Final confirmed intent

Primary intent: add a backend user-level Recipe favorites feature in Mealie, including a `user_favorite_recipe` model/migration, self-service favorite APIs, Recipe response fields `favorited` and `favorite_count`, 3-layer implementation through routes/users → services/user_services → repositories, i18n errors, efficient non-N+1 Recipe list queries, and unit/integration/multitenant tests preserving group and household isolation.

Excluded: household-level shared favorites, API-only favorites without Recipe response changes, frontend UI implementation, and generic anonymous popularity/likes.

Pending clarification: none. The spec is explicit enough; implementation choices such as whether to extend `repository_users.py` or create `repository_favorites.py` are permitted by the input and do not require clarification.
