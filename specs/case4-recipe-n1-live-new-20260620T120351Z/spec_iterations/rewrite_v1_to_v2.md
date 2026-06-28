# Rewrite v1 → v2 — case-4 NEW pipeline

## Decision: PROCEED with v2 precision iteration

**V1 review verdict**: All 4 axes (Architecture, Completeness, Consistency, Executability) + A3 perf_opt rule → **PASS** with 0 critical/high/medium/low findings.

**Rationale for v2**: Per the live-pipeline task spec, drive both iterations end-to-end. V2 is therefore a **precision polish** iteration — not a defect fix — applying the seven improvements below identified as "nice-to-have" during v1 review but not blocking.

## V2 changes (additive, no semantic regression)

### Change 1 — FR-010 gains a verbatim test-code skeleton block
**Why**: V1's FR-010 described the regression test behavior in prose. V2 adds a verbatim Python skeleton fenced block so the implementer can paste-and-fill, eliminating residual ambiguity about exact assertion call signatures.

### Change 2 — FR-014 gains a verbatim test-code skeleton + EXPECTED_KEYS literal
**Why**: V1 described the shape test in prose. V2 includes the literal `EXPECTED_KEYS` list (the 26 field names in declaration order) inline, so the test is a one-glance contract reference.

### Change 3 — NC-007 gains a DBMS x loader-strategy decision matrix
**Why**: V1 explained set-equal vs list-equal in prose. V2 adds a small matrix (SQLite/Postgres × joinedload/selectinload × default-order) so reviewers can verify the claim "no order_by → implementation-defined" against each supported DBMS in one glance.

### Change 4 — SC-006 verification command reformed
**Why**: V1 SC-006 offered `-W error::SAWarning` as the verification, then a count-based fallback. V2 makes the count-based form primary (because escalating SAWarning to error can flag unrelated pre-existing warnings unrelated to this refactor). The primary command becomes a pre/post diff.

### Change 5 — EC-006 chunking formula is keyed explicitly
**Why**: V1 said `k_X = ceil(IDs/500)` without naming which IN-list each k counts. V2 spells out:
  - `k_cat = ceil(recipe_ids_count / 500)` (selectinload on `recipe_category` IN-list keyed by recipe.id)
  - `k_tag = ceil(recipe_ids_count / 500)` (selectinload on `tags` keyed by recipe.id)
  - `k_tool = ceil(recipe_ids_count / 500)` (selectinload on `tools` keyed by recipe.id)
  - `k_households = ceil(distinct_tool_ids_count / 500)` (chained selectinload keyed by Tool.id, NOT recipe.id)
This corrects a subtle but important point: the chained households selectinload chunks by distinct tool count (which can grow faster than recipe count for diverse tool libraries), not by recipe count.

### Change 6 — New EC-010: SQLAlchemy expire-on-commit + selectinload
**Why**: Mealie's session is typically `expire_on_commit=False` (or default True with explicit refresh patterns); selectinload's follow-up queries fire on attribute access, so a write+read pattern in tests can introduce unexpected statements. V2 documents this so the implementer doesn't double-count session-refresh queries in the FR-010 listener.

### Change 7 — New SC-009: no migration files added (executable assertion)
**Why**: V1's FR-015(c) said "no migration is added" in PR description; SC-004 verified PR description. V2 adds SC-009 with a concrete executable command: `Test-Path mealie/alembic/versions/*recipe*list*` returns false, AND the diff against main does not introduce any new `mealie/alembic/versions/*.py` file.

## What stays identical

- All FR-IDs, SC-IDs (primary), US-IDs, EC-IDs (001-009), NC-IDs (001-008), self-concern IDs (A-E).
- The selected approach (Conservative — single-seam loader-options refactor).
- The non_actions list.
- The files_touched list (modified / added).
- The intent_type (`perf_opt`) and scope.
- The A3 perf_opt rule satisfaction (Check 1, 2, 3 all pass).

## What is added

- FR-014 inline `EXPECTED_KEYS` Python list literal.
- FR-010 verbatim test skeleton.
- NC-007 DBMS × loader-strategy matrix.
- EC-010 (new edge case).
- SC-009 (new success criterion).

## What is reformed (no semantic change)

- SC-006 verification (count-based primary, escalation fallback).
- EC-006 chunking formula keyed explicitly.

## What is removed

Nothing.
