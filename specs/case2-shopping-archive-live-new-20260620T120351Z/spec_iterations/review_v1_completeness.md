# Review v1 — Completeness axis

Mapped every requirement in input §1-§8 to a concrete FR / SC / US /
edge case in the spec, plus the rubric's three-checkpoint review items.

## Verdict
APPROVE

## Critical issues
None.

## High issues

### H1. `?archived=all` field-projection contract is implicit, not explicit

Input §2 row 5 says `?archived=all` "returns everything, **附带
archived_at 字段**" — i.e. when querying with `?archived=all`, the
response MUST attach the `archived_at` field. Input §6 also says
"default query 不返回 archived_at / archived_by" (default query does
NOT return these fields).

The spec resolves the tension correctly per consolidated CC-3
("Critical-3. Default-include vs default-omit `archived_at` in
response") and writes the resolution into NC handled implicitly via
FR-012 (always-present Optional defaulting to None). However the FR
text itself does NOT explicitly call out that:

1. Default-mode responses MUST set `archived_at = null` and
   `archived_by = null` for all rows (this is true by construction
   because they're Optional defaulting to None, but the test SC-008
   doesn't actually pin this);
2. `?archived=all` responses MUST populate `archived_at` (and
   `archived_by`) on archived rows, with `archived_at IS NOT NULL`.

A reviewer reading only FR-012 + SC-008 might miss that the
`always-include-as-optional` choice is a binding decision and write a
test that asserts the fields are ABSENT from default responses (which
would fail). Recommend tightening SC-008's threshold to require the
field shape explicitly. Severity High because a downstream test author
could implement the wrong contract.

## Medium issues

### M1. Bulk-vs-singular `/items` route coverage is named but not enumerated in FR text

Consolidated CC-3 resolves bulk-route freezing by routing through
`RepositoryShoppingListItem.create_many` / `update_many` / `delete_many`
(FR-008 does name these). However the test-shaped requirements
(SC-004) only enumerate the singular endpoints. Recommend either
adding a separate SC for the bulk routes or amending SC-004's metric to
include `/items/create-bulk`, `PUT /items`, `DELETE /items` so the
acceptance criterion exercises both surfaces. Severity Medium because
FR-008 covers the code; the gap is only in the success-criterion text.

### M2. The eval rubric "下游消费 list 的接口枚举" is partially covered

Input rubric (三环节考察点 §Spec column) asks whether the spec
enumerates every downstream consumer of shopping lists. The spec
covers:

- the scheduled-pruner consumer (FR-014 + SC-009) ✓
- meal-plan, cookbook, backups_v2 (out_of_scope item 5) ✓ documented

But it does NOT name:

- `mealie/services/backups_v2/` (handled in edge case "Database
  backup/restore round-trips" but not in any FR)
- `frontend/` consumers (consolidated U2/U3/U8/U9 — meal-plan dropdown
  filter, recipe-add-to-list dropdown). The spec defers the entire
  frontend (assumption #1) but the rubric explicitly asks about
  consumers across the project, including UI.

Recommend tightening assumption #1 to enumerate which consumer
contracts the backend ships preserves (the codegen-emitted TS types
remain backwards compatible for U1, and the new optional fields are
ignored by U8/U9 dropdown filters until they are updated). Severity
Medium because the work itself is correctly scoped; only the rubric
documentation gap remains.

### M3. `DELETE /lists/{id}` policy not stated

Same observation as Architecture-M2. The spec is silent on whether
deleting an archived list is allowed. Recommend either an explicit FR
that says "DELETE /lists/{id} is NOT in the frozen route set" or a
sentence in assumptions.

## Coverage matrix (input §1-§8 → spec)

| Input section | Covered by |
|---------------|------------|
| §1.1 archived_at column | FR-001 |
| §1.2 archived_by_user_id column | FR-001 |
| §1.3 migration backwards-compat | FR-002 |
| §2 POST /archive | FR-010, US-1, SC-003 |
| §2 POST /unarchive | FR-010, US-4, SC-003 |
| §2 GET default = archived omitted | FR-011, US-3, SC-008 |
| §2 GET ?archived=true | FR-011, US-3, SC-008 |
| §2 GET ?archived=all | FR-011, US-3, SC-008 (see H1) |
| §2 archive 409 unchecked-items | FR-009, US-2, SC-004 |
| §3 frozen PUT /lists | FR-007, US-5, SC-004 |
| §3 frozen POST/PUT/DELETE /items | FR-008, US-5, SC-004 |
| §3 unarchive exception | FR-010, US-4 |
| §4 multitenancy | FR-006 (uses _filter_builder), FR-015, US-6, SC-007, EC cross-household |
| §5 event types | FR-003, FR-004, FR-005 |
| §5 payload fields | FR-005, SC-006 |
| §5 no cross-household | FR-015, SC-007, US-7 |
| §6 schema additions | FR-012 |
| §6 backwards-compat | FR-011, FR-012, US-9, SC-002 |
| §7 centralised filter | FR-006 |
| §7 reuse shopping_lists service | FR-009 |
| §7 backward-compat migration | FR-002, SC-001 |
| §7 i18n keys | FR-013 |
| §8 unit tests | FR-016 |
| §8 integration tests | FR-016, SC-002, SC-003, SC-004 |
| §8 multitenant tests | FR-016, SC-010 |
| Rubric: scheduler consumer | FR-014, US-8, SC-009 |
| Rubric: cross-household payload | FR-005, FR-015, SC-007 |
| Rubric: admin force-unarchive | out_of_scope #1 |
| Rubric: unarchive item-state | out_of_scope #4 |

## Summary

- Critical: 0 | High: 1 | Medium: 3
