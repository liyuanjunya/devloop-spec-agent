# Review v1 — Consistency axis

Cross-checked bidirectional links (US ↔ FR ↔ SC), edge cases vs FRs,
NCs vs related_requirements, and out_of_scope vs FR text.

## Verdict
NEEDS_REFINE

## Critical issues
None.

## High issues

### H1. NC-002 `if_rejected` path is incomplete

NC-002 ("total_estimated_amount on archive event payload has no
source") gives a sensible recommended default (include the field,
default None). The `if_rejected` clause says "If reviewer prefers to
drop the field entirely... remove `total_estimated_amount` from
EventShoppingListArchiveData and from FR-009." But SC-006's threshold
enumerates the 8 payload keys EXPLICITLY including
`total_estimated_amount` (see "JSON key set equals the 8 listed names
with no extras"). If the reviewer goes with "if_rejected", SC-006's
key set drops to 7 and the existing threshold becomes wrong. The
`if_rejected` text should also instruct: "update SC-006 to enumerate 7
keys (drop `total_estimated_amount`)." Severity High because the
inconsistency would cause the v2 rewrite (or any future fix) to leave
SC-006 stale.

### H2. NC-001 `related_requirements` is incomplete

NC-001 names `FR-007, FR-008, SC-004` as related, but the
`recommended_default` text also affects which routes appear in FR-010
(controller endpoints don't add the three additional ones) and FR-016
(test coverage doesn't include the three additional routes). The
omission is minor at the prose level but the `related_requirements`
field is consumed mechanically by trace-matrix and downstream code. The
list should include `FR-010, FR-016` so a follow-up rewriter knows what
to touch if NC-001 flips. Severity High because the field is the
machine-readable contract.

## Medium issues

### M1. Edge case "Cross-household call" references mixins.py:79-83 but no FR cites it

The edge case "Cross-household call: user in household B targets a
list id belonging to household A" cites
`mealie/routes/_base/mixins.py:79-83` for the 404 precedent. No FR
includes a code_reference to that file, so a reader following just the
FR list will miss the source of the 404 contract. Recommend either
adding mixins.py to FR-006 or FR-008's code_references, OR demoting the
mixins.py reference to a non-binding mention. Severity Medium because
the edge-case prose is still readable.

### M2. US-5 acceptance condition for items uses "checked" without disambiguation

US-5 scenario 2 says "an item belonging to an archived list" and the
mutation "POSTs /api/households/shopping/items, PUTs /items/{id}, or
DELETEs /items/{id}". The POST case applies to creating an item INSIDE
an archived list, not to an existing item. The current prose conflates
these. Recommend splitting into two scenarios: one for creation
(`POST /items` with `shopping_list_id` pointing to an archived list)
and one for update/delete (operating on an existing item whose parent
is archived). Severity Medium — implementers will figure it out from
FR-008 but the scenario reads ambiguously.

### M3. SC-006 threshold says "exactly 1 event per call" — is "call" the controller call or the dispatch call?

The metric "number of dispatched events" combined with "exactly 1 event
per call" is unambiguous in the simple case but ambiguous when the
`EventBusService.dispatch` loop at `event_bus_service.py:82-96`
splits across multiple households (the household_id-None branch). Since
archive/unarchive ALWAYS pass a concrete household_id (FR-015), the
dispatch loop iterates exactly once — so "1 event per call" is
correct. Recommend clarifying the SC text to say "exactly 1 event
delivered to exactly 1 household per call." Severity Medium — the
contract is already correct, only the wording could be tightened.

## Strengths

- All 4 trace-matrix rules pass (find_trace_gaps returns 0):
  - Every functional FR has at least one SC linked.
  - Every SC reaches at least one FR.
  - All cross-references resolve.
  - Every P1 US is named by at least one FR.
- Edge cases align with FRs:
  - Nullable `checked` → FR-009's archive precondition.
  - Idempotent re-archive → FR-006 archive() helper.
  - Empty list → FR-009 item_count = 0.
  - Cross-household → FR-015 (household_id pass-through) +
    `_filter_builder` enforcement.
  - Concurrent archive → atomic UPDATE in FR-006.
  - Subscriber outage → BackgroundTasks in FR-015.
  - Single-item GET → FR-011 collection-only filter.
  - Backup/restore → assumption #2 + edge-case prose.
- `assumptions[3]` correctly chains the migration off the verified head
  (`2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers`).
- `out_of_scope[1]` (admin force-unarchive) and `out_of_scope[4]`
  (unarchive item-state) match the input rubric verbatim — these are
  the items the input itself called out for CR discussion.

## Summary

- Critical: 0 | High: 2 | Medium: 3
