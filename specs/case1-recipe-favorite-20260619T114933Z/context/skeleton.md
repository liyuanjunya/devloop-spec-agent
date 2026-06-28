# Repo skeleton — Mealie (commit 4a099c1)

**Stats**: 590 Python source files, ~50,340 LOC

## Top-level layout

```
mealie/                          # Python source
  app.py, main.py                # FastAPI entry
  core/                          # config, DI, security, settings
  db/models/                     # SQLAlchemy ORM (users/, recipe/, household/, group/)
  repos/                         # Repository pattern — entry: repository_factory.AllRepositories
  schema/                        # Pydantic v2 (recipe/, household/, group/, user/, _mealie/)
  routes/                        # FastAPI controllers
    auth/, admin/, app/, comments/, explore/, groups/,
    households/    # ★ meal plan, shopping list, cookbook
    media/, organizers/, parser/, recipe/, users/
  services/                      # Business logic
    recipe/, household_services/, group_services/, user_services/,
    scraper/, openai/, parser_services/, scheduler/, event_bus_service/
  middleware/, pkgs/, lang/ (i18n yaml), assets/
  alembic/versions/              # DB migrations
tests/
  unit_tests/                    # fast, pure unit
  integration_tests/             # HTTP client + DB
  multitenant_tests/   # ★ MANDATORY for cross-household features
  e2e/                           # Playwright
  fixtures/                      # factories (unique_user, recipe, etc.)
frontend/                        # Nuxt 4 + Vue 3 (out of scope for this case)
```

## 3-layer architecture (must follow)

```
HTTP → routes/<area>/controller_*.py
     → services/<area>/*_service.py
     → repos/repository_*.py
     → db/models/*.py
```

`AllRepositories` (in `mealie/repos/repository_factory.py`) is the single entry point for all queries; it auto-injects household_id filter.

## Existing entities relevant to "favorites" feature

- **User**: `mealie/db/models/users/users.py` — id, email, username, group_id, household_id
- **Recipe**: `mealie/db/models/recipe/recipe.py` — id, slug, name, group_id, household_id
- **BaseUserController**: `mealie/routes/_base/` — auto-injects current user + household filter
- **PaginationQuery**: reuse from `mealie/schema/_mealie/`

## Project conventions

| Concern | Convention |
|---|---|
| Authentication | `Depends(get_current_user)` from `core/dependencies/dependencies.py` |
| Per-household filtering | Automatic in `routes/_base/` controllers |
| Pagination | Reuse `PaginationQuery` from `schema/_mealie/` |
| Migrations | `uv run alembic revision --autogenerate -m "..."`, files in `alembic/versions/` |
| i18n | `lang/messages/*.yaml`, use `t('errors.xxx')`, NEVER hardcoded English |
| Test framework | pytest with fixtures in `tests/fixtures/` |
| **Cross-household features** | MUST add tests in `tests/multitenant_tests/` |
| Event bus | `services/event_bus_service/` for cross-module dispatch |
| Repository extension | Extend existing in `repository_factory.AllRepositories`, don't bypass |
