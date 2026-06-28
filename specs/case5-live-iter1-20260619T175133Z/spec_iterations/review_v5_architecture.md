## Verdict
REJECT

v5 correctly fixes the main v3/v4 architecture regressions by moving the CAS/items/event durability choice into NC-004 instead of over-specifying an impossible transaction. However, one stale edge-case requirement still re-introduces a rollback guarantee that v5 otherwise explicitly defers to NC-004. Because this creates a new HIGH architectural contradiction, v5 cannot be approved under the 0 critical + 0 high rule.

## V3 issue resolution

| v3 issue | Status in v5 | Evidence |
|---|---|---|
| NEW-ARCH-C-1 / ARCH-C-1: single rollbackable transaction incompatible with internally committing shopping-list repos | RESOLVED BY ESCALATION | NC-004 explicitly states that `RepositoryGeneric.create_many` / `update_many` / `update` commit internally and that `ShoppingListService.bulk_create_items` / `add_recipe_ingredients_to_list` delegate to those seams (`spec_v5.md:42-50`). FR-011 and FR-012 now defer rollback semantics to NC-004 rather than promising one transaction (`spec_v5.md:203-207`). Existing code confirms the internal commits (`repository_generic.py:195-244`, `shopping_lists.py:215-216`, `shopping_lists.py:433-454`). |
| NEW-ARCH-H-1: event dispatch specified as both post-commit and rollbackable | RESOLVED BY ESCALATION | NC-004 documents that `EventBusService.dispatch` publishes immediately and is not transactionally coupled to the DB (`spec_v5.md:44`; `event_bus_service.py:66-96`). FR-021 limits normal-operation dispatch to the success path and defers retry/exactly-once semantics to NC-004 (`spec_v5.md:233-234`). |
| NEW-ARCH-M-1: run-now / US-9 contradicted 204 No Content | RESOLVED | US-9 now requires HTTP 204 with zero body bytes and logs-only i18n on no-meal-plan paths (`spec_v5.md:155-167`). FR-020 and SC-026 match this contract (`spec_v5.md:230`, `spec_v5.md:313-314`). |
| NEW-ARCH-M-2: locale scope inconsistent | RESOLVED | FR-022, assumptions, and out-of-scope all state only `en-US.json` is editable and other locales are Crowdin-managed (`spec_v5.md:236-238`, `spec_v5.md:364`, `spec_v5.md:378`). |

## New issues in v5

### NEW-ARCH-H-1 (HIGH): Stale sub-recipe-cycle edge case reintroduces the deferred rollback guarantee

The edge case for recursive sub-recipe cycles says a `RecursionError` propagates out of the FR-011 transaction context and "ROLLS BACK the CAS UPDATE alongside any partial item writes," leaving `last_auto_synced_at` untouched (`spec_v5.md:352`). That contradicts FR-012 and NC-004, which say rollback behavior is path-dependent: PATH A can roll back atomically, but PATH B/C commits the CAS immediately and leaves the marker set after later failures (`spec_v5.md:206`, `spec_v5.md:357`).

This is not just wording: it gives implementers/test authors a concrete failure-case requirement that is impossible under two of NC-004's three valid outcomes and partially revives the v3 architecture defect. Fix by rewriting this edge case to say the recursion-failure marker/item rollback semantics are governed by NC-004, matching the force-mode edge case wording at `spec_v5.md:357`.

## Summary

- Critical: 0
- High: 1
- Medium: 0
- v3 critical/high issues: substantially resolved by NC-004 escalation
- Approval blocker: one stale rollback guarantee remains outside the NC-004 boundary
