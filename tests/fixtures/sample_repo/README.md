# Sample Repo (Fixture for DevLoop tests)

A tiny FastAPI + SQLAlchemy + pydantic project used as the target of integration / E2E tests.

## Architecture

- `app/models/` — SQLAlchemy ORM models
- `app/api/` — FastAPI routers
- `app/schemas/` — pydantic request/response schemas
- `tests/` — pytest tests

## Conventions

- All API inputs validated with pydantic
- All database changes use Alembic migrations
- IDs are UUID strings, not auto-increment integers
