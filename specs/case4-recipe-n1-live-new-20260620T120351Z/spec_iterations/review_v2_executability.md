# Executability Review — v2 (case-4 NEW pipeline)

## Verdict
**PASS** — v2 strictly improves executability over v1 by adding paste-and-fill code skeletons (FR-010, FR-014), a DBMS reference matrix (NC-007), and a `git diff` verification command (SC-009). Zero placeholders.

## V2 executability improvements

### EXEC-PASS-V2-001 — FR-010 verbatim Python skeleton
The implementer can copy the skeleton, fill in `_seed_recipes(db, user, count, tags, categories, tools)`, and have a working test. The skeleton is:
- Syntactically correct Python (parses).
- Uses real, on-disk fixtures (`api_client`, `unique_user_fn_scoped`, `database`) verified in v1.
- Uses real, on-disk constants (`api_routes.recipes` at `tests/utils/api_routes/__init__.py:138`).
- Uses real, on-disk engine global (`from mealie.db.db_setup import engine`).
- Listener arm/remove sequence is correct SQLAlchemy 2.x API (`event.listen(...)` / `event.remove(...)`).
- Both assertions (relative + absolute) are explicit with failure messages.

### EXEC-PASS-V2-002 — FR-014 verbatim skeleton + EXPECTED_KEYS literal
- The EXPECTED_KEYS list literal is paste-able and matches the FR-001 enumeration character-for-character.
- The test skeleton uses real fixtures and runs `_seed_three_recipes` (helper to write) + GET + assertions.
- Set-comparison assertions are guard-railed by `.slug`-based seeded names, making failures human-readable.

### EXEC-PASS-V2-003 — NC-007 DBMS × loader matrix
A reviewer can verify the "set-equal is necessary" claim in 30 seconds:
- SQLite → joinedload uses LEFT OUTER JOIN rowid order; selectinload uses IN-list rowid order.
- Postgres → joinedload uses planner-chosen JOIN order; selectinload uses IN-list order (UNDEFINED without ORDER BY).
- MySQL/MariaDB → same as Postgres for the selectinload case.

Therefore at least one DBMS configuration breaks list-equal but not set-equal. The matrix makes this checkable per DBMS, not just descriptive.

### EXEC-PASS-V2-004 — SC-009 executable migration check
Command: `(git diff main --name-only -- mealie/alembic/versions/ | Measure-Object -Line).Lines` MUST equal 0.
Plus positive: 3-file diff cap. Both are CI-grade assertions.

### EXEC-PASS-V2-005 — SC-006 verification reform
V1's `-W error::SAWarning` strict form was fragile against pre-existing baseline SAWarnings. V2's count-diff primary form is:
```powershell
$pre = uv run pytest tests/ 2>&1 | Select-String -Pattern 'SAWarning' | Measure-Object -Line | Select-Object -ExpandProperty Lines
# (apply refactor)
$post = uv run pytest tests/ 2>&1 | Select-String -Pattern 'SAWarning' | Measure-Object -Line | Select-Object -ExpandProperty Lines
# Assert: $post -eq $pre
```
This is robust to pre-existing warnings unrelated to this refactor.

### EXEC-PASS-V2-006 — EC-010 codifies the warm-up sequence rationale
The warm-up sequence in FR-010(4) ("warms up the test client with one throwaway api_client.get") gains an explicit "why" in EC-010 — it absorbs incidental expire-on-commit refresh queries that would otherwise inflate the count_small measurement. The implementer no longer has to infer the warm-up purpose from the prose.

## Verified citations (v2-specific re-verification)

| Citation | Result |
|---|---|
| `mealie/db/db_setup.py:45` (session factory referenced by EC-010) | Verified in v1 executability review |
| `tests/utils/api_routes/__init__.py:138` (referenced by skeleton) | Verified in v1 executability review |
| `tests/fixtures/fixture_users.py:219-221` (referenced by skeleton) | Verified in v1 executability review |
| `mealie/alembic/versions/` (SC-009 target directory) | Real directory in the Mealie repo |

## Summary

- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**Verdict: PASS — v2 executability is strictly stronger than v1.**
