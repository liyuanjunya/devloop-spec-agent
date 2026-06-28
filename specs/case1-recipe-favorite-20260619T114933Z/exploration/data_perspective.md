# Data Perspective

## Critical artifacts (must read to write the spec)

- `mealie/db/models/_model_base.py:18-33` — base model conventions (`id`, `created_at`, `updated_at`) and normalization helpers
- `mealie/db/models/users/users.py:51-115` — `User` model patterns, `sp_args` cascade template, and existing `favorite_recipes` / `rated_recipes` relationships
- `mealie/db/models/recipe/recipe.py:42-179` — `RecipeModel` relationship/cascade patterns, loader-related fields, and current user-specific recipe data wiring
- **★ `mealie/db/models/users/user_to_recipe.py:17-54` — EXISTING join-table model for user↔recipe; the closest reference for a new join model AND already implements `is_favorite` (conflict signal!)**
- `mealie/db/models/recipe/tag.py:19-25,57-59` — many-to-many `sa.Table` pattern with composite unique constraint
- `mealie/db/models/recipe/category.py:19-41,63-65` — another many-to-many pattern with composite unique constraint
- `mealie/schema/response/pagination.py:32-56` — `PaginationQuery` / `PaginationBase` conventions for list endpoints
- `mealie/schema/user/user.py:28-103,191-239` — schema naming patterns (`*In`, `*Out`, `*Summary`, `*Pagination`) and `UserRatingOut` template
- `mealie/schema/recipe/recipe.py:61-179,182-320` — recipe schema naming + loader options for avoiding N+1
- `mealie/repos/repository_factory.py:105-188,240-264` — `AllRepositories` factory wiring and cached-property repository registration pattern
- `mealie/repos/repository_users.py:18-102` — repository template for CRUD + custom query methods (AND already contains `RepositoryUserRatings` that uses favorites)
- `mealie/repos/repository_recipes.py:36-93,220-355` — recipe pagination/query patterns and user-specific data injection
- **★ `mealie/alembic/versions/2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py:153-226` — closest migration precedent — and TITLE confirms favorites already migrated once to UserToRecipe table**
- `mealie/alembic/versions/2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py:1-25,170-263` — recent migration header + table/index declaration style

## Relevant artifacts (provide context)

- `mealie/db/models/group/ai_providers.py` — `delete-orphan` on 1:many child collections
- `mealie/db/models/group/group.py` — more `delete-orphan` examples
- `mealie/db/models/household/household.py` — more `delete-orphan` examples
- `mealie/db/models/recipe/ingredient.py` — `delete, delete-orphan` with collection ordering
- `mealie/db/models/household/shopping_list.py` — `delete, delete-orphan` with back_populates
- `mealie/alembic/versions/2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_.py` — table/index creation style for join tables with `created_at` + unique constraints
- `mealie/repos/repository_generic.py` — generic repository base used by most repos

## Conventions discovered

1. SQLAlchemy base models inherit `SqlAlchemyBase` and `BaseMixins`; audit columns are `id`, `created_at`, `update_at` (synonym `updated_at`)
2. Join-table data uses either: pure `sa.Table(...)` with composite unique (`recipes_to_tags`, `recipes_to_categories`), OR full model class when extra per-link fields/events needed (`UserToRecipe`)
3. Join models typically include FK columns indexed individually plus composite unique on the pair
4. **★ Existing user↔recipe linkage is already modeled by `UserToRecipe`; `User.favorite_recipes` / `RecipeModel.favorited_by` are FILTERED relationships on that table using `is_favorite`**
5. `delete-orphan` used on owned child collections, usually with `back_populates` and often `single_parent=True` in `sp_args`
6. Schema naming: `Create*`, `*Out`, `*Summary`, `*Pagination`, `*InDB`; pagination wraps `items: list[T]`
7. Loader optimization: explicit in schema via `loader_options()` using `joinedload` / `selectinload` — main anti-N+1 pattern
8. Repository factory exposes each repo as `@cached_property`; adding a new repo means importing and wiring property in `AllRepositories`
9. Alembic migrations use `YYYY-MM-DD-HH.MM.SS_<rev>_<slug>.py` with module docstring, `revision`, `down_revision`, `upgrade()`, `downgrade()`
10. Migrations: unique constraints declared inline in `op.create_table(...)`; indexes via `op.create_index(...)` or `batch_op.create_index(...)`
11. Recipe list endpoints currently load `RecipeSummary.loader_options()` before validation — that's where per-user favorite/count hydration would go without N+1

## Open questions for spec

- Should the new favorite link be full model class (like `UserToRecipe`) or pure `sa.Table`? Requested `created_at` → full model
- Should `favorited` be computed from per-request user context in repository layer, or exposed as schema field populated by query annotations?
- Should `favorite_count` use grouped subquery/join in recipe query or separate aggregate loader?
- **★ Conflict to resolve: the input asks for a NEW `user_favorite_recipe` table, but `UserToRecipe.is_favorite` already serves this purpose. New table → migrate/backfill? Reuse `UserToRecipe`? Have both?**

## Tool calls used: ~12
