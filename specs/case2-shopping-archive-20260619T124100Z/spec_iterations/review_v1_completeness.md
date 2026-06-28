# Completeness Review (v1)

## Verdict: NEEDS_REFINE

The spec is broadly strong: it covers the two nullable shopping-list columns and migration, all five archive/listing endpoints, frozen mutations including `checked`, repository/service-layer placement, event bus types, multitenant isolation, and a concrete test plan. However, it still misses or changes several explicit input §1-§8 requirements. The main blockers are schema compatibility (`archived_at`/`archived_by` must be omitted from the default response, not emitted as `null`), exact event payload field names, all-locale i18n coverage, and test acceptance for the full multitenant matrix.

## Critical issues

- **COMP-C-001 — Default schema response violates §6 compatibility: fields are not omitted.**
  - Location: `spec.md` US-9 lines 114-122, FR-9 lines 287-299, SC-11 lines 442-443; `spec.json` US-9 lines 94-100 / FR-9 lines 255-264.
  - Evidence: input §6 requires `ShoppingListSummary` / `ShoppingListOut` to add `archived_at` and `archived_by` for archive queries, and **default query not to return these fields** for compatibility. The spec instead says default responses include `archived_at: null` and `archived_by: null`, and FR-9 adds optional fields directly to both schemas with default `None`. That changes the default wire shape and fails the explicit “default omit” requirement.
  - Required fix: Define a response-shaping rule or separate summary/out variants so default `GET /api/households/shopping/lists` omits both fields, while `?archived=true` and `?archived=all` include them.

- **COMP-C-002 — Event payload schema changes explicit `list_id` / `list_name` fields.**
  - Location: `spec.md` FR-10 lines 305-325, SC-3 lines 434-435, NC-3 lines 515-519; `spec.json` FR-10 lines 272-280 / SC-3 lines 379-382.
  - Evidence: input §5 requires payload fields `list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`. The spec uses `shopping_list_id` and `shopping_list_name` and treats the mismatch as a non-blocking default resolution. Because the review scope asks for payload schema coverage, this is an input-contract deviation, not just an implementation naming preference.
  - Required fix: Either use exact `list_id` / `list_name` in the payload contract, or make the naming deviation a blocking reviewer/product decision before coding.

- **COMP-C-003 — i18n requirement is weakened from all existing language files to en-US only.**
  - Location: `spec.md` FR-13 lines 383-397; `spec.json` FR-13 lines 323-331.
  - Evidence: input §7 says error keys must be added to `lang/messages/` all existing language files (at least en-US). The spec explicitly says all other locale files **MUST NOT** be modified. That may be a repository-policy conflict, but the spec does not preserve the input requirement or record it as blocking clarification.
  - Required fix: Add a clarification/decision: either update every locale with fallback values as input requires, or explicitly document the repository-policy exception and require en-US plus Crowdin follow-up.

## High issues

- **COMP-H-001 — Multitenant acceptance tests do not fully enumerate the three required scenarios.**
  - Location: `spec.md` SC-6/SC-7 lines 437-438, SC-10 line 440; `spec.json` SC-6/SC-7 lines 394-402.
  - Evidence: input §8 requires multitenant tests for (1) same-group other household cannot see archived list, (2) cross-group complete isolation, and (3) cross-household archive call returns 404/403. The spec has story-level coverage in US-8, but measurable SCs only require same-group GET + archive 404 and a generic cross-group GET case. A cross-group archive/unarchive 404 test is not explicit.
  - Suggested fix: Add named multitenant tests for same-group GET isolation, cross-group GET isolation, same-group cross-household archive/unarchive 404, and cross-group archive/unarchive 404.

- **COMP-H-002 — `archived_by_user_id` invariant conflicts with user-deletion behavior.**
  - Location: `spec.md` FR-1 lines 141-148, FR-2 lines 154-162, EC-8 lines 493-497, NC-5 lines 525-527; `spec.json` FR-1 lines 114-122 / EC-8 lines 487-491.
  - Evidence: FR-1 requires `archived_at IS NULL ⇔ archived_by_user_id IS NULL`, but EC-8/NC-5 choose `ON DELETE SET NULL`, producing archived lists with `archived_at IS NOT NULL` and `archived_by_user_id IS NULL`. This contradiction can make implementation/tests inconsistent.
  - Suggested fix: Match input’s one-way invariant: if `archived_at IS NULL` then `archived_by_user_id IS NULL`; archived rows may have null `archived_by_user_id` after user deletion, or else choose a different delete policy.

- **COMP-H-003 — Frozen-scope clarification allows partial mutation on recipe routes.**
  - Location: `spec.md` FR-6 lines 220-222, NC-1 lines 504-508, SCN-2 lines 540-543.
  - Evidence: input §3 lists four frozen routes, but the feature intent is “archived list immutable.” The spec accepts a known partial-mutation-then-409 path for recipe add/remove. This is not a direct miss of the four listed routes, but it is a dangerous unresolved edge for archive immutability and should not be left as acceptable if coding can touch those routes.
  - Suggested fix: Require an early archived-list guard before recipe add/remove mutations, or explicitly out-scope them with a test proving no partial mutation occurs on the listed frozen routes.

## Requirement coverage

| Input / review requirement | Spec representation | Completeness verdict |
|---|---|---|
| Two nullable columns + migration, existing rows NULL | FR-1/FR-2, SC-9 | Covered, but invariant conflict in COMP-H-002 |
| POST archive, POST unarchive | FR-4, US-1/US-6 | Covered |
| GET default / `?archived=true` / `?archived=all` | FR-5, SC-5 | Behavior covered; default response shape fails COMP-C-001 |
| Archive requires all items checked, else 409 + i18n key | US-2, FR-11, EC-2/2b | Covered |
| Frozen PUT list / POST item / PUT item / DELETE item | FR-6, SC-2 | Covered, including bulk siblings |
| `checked` field update also forbidden | US-5 / FR-6 include any PUT item field | Covered |
| Multitenant three isolation rules | US-8, FR-12, SC-6/SC-7 | Partially covered; tests incomplete (COMP-H-001) |
| Event bus two event types | FR-10 | Covered |
| Event payload exact schema and no leak | FR-10 / SC-3 / SC-4 | No-leak covered; field names fail COMP-C-002 |
| Schema includes `archived_at` + `archived_by` user summary for archive queries | FR-9 | Covered |
| Default omit for compatibility | US-9 / FR-9 emit null fields | Missing; COMP-C-001 |
| Repository-layer centralization | FR-7/FR-8 and repository factory wiring | Covered, adapted to actual `repository_shopping_list.py` |
| Reuse `shopping_lists.py` service orchestration | FR-11 | Covered |
| i18n keys present | FR-13 / SC-8 | Keys covered for en-US only; all-locale input missing (COMP-C-003) |
| Unit tests ≥4 | SC-10 | Covered |
| Integration scenarios listed in input | SC-2/3/5/8/10/12 | Mostly covered |
| Multitenant 3 scenarios | SC-6/SC-7/SC-10 | Partially covered; COMP-H-001 |

## Summary

Refine once before coding. Preserve exact default response omission semantics, restore or explicitly adjudicate exact event payload field names, resolve all-locale i18n vs Crowdin policy, and make the multitenant test matrix fully executable. Also fix the `archived_by_user_id` invariant/delete-policy contradiction so the generated implementation has one coherent target.
