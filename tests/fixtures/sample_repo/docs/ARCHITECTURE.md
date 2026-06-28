# Architecture

This sample project follows a clean layered architecture:

1. **Models layer** (`app/models/`) — SQLAlchemy ORM, no business logic
2. **Schemas layer** (`app/schemas/`) — pydantic v2 for request/response validation
3. **API layer** (`app/api/`) — FastAPI routers, thin handlers

## Conventions

- Use SQLAlchemy 2.0 style (declarative_base from `sqlalchemy.orm`)
- All API input validation via pydantic v2 (`constr`, `Field`)
- Migrations managed by Alembic (in `alembic/versions/`)
- Tests live under `tests/` using pytest

## Design decisions

- IDs are UUIDs (strings), not auto-increment integers — for distributed friendliness
- Decimal for monetary amounts (`Numeric(10, 2)`)
- Server-side timestamps (`server_default=func.now()`)
