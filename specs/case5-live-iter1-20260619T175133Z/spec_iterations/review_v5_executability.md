# Executability Review (v5)

## Verdict: NEEDS_REFINE

v5 fixes the v3 run-now/i18n contradictions and its cited code ranges are mechanically valid. However, it is not fully executable as written because the edge-case section reintroduces concrete rollback and retry guarantees after FR-011/FR-012/FR-020/FR-021 deliberately defer those semantics to NC-004. I found 0 critical and 1 high issue, so this review cannot approve.

---

## Scope checks

| Check | Result |
|---|---|
| All cited paths real? | ✅ Pass. Parsed all 57 `functional_requirements[].code_references`; every path exists under `C:\Users\v-liyuanjun\Downloads\mealie`. |
| All line ranges accurate and cited symbols in range? | ✅ Pass. All referenced ranges are within file bounds and every cited symbol appears inside at least one cited range for that reference. |
| `spec.md` / `spec.json` counts sane? | ✅ Pass. JSON contains 29 FRs, 29 SCs, 4 NCs, 9 user stories, 11 edge cases, 10 assumptions, 6 out-of-scope items, and 4 self-concerns. |
| TBD / `or equivalent` / `if needed` / stale isolation wording? | ✅ Pass. No matches for `TBD`, `or equivalent`, `if needed`, or `REPEATABLE READ` in `spec_v5.json`. |
| v3 US-9 204/no-body contradiction fixed? | ✅ Pass. US-9 now requires HTTP 204 with zero response bytes and logs-only i18n keys (spec_v5.md L155-167); FR-020 and SC-026 agree (L230, L313-314). |
| v3 event-message contradiction fixed? | ✅ Mostly pass. FR-021/FR-022 now state no-op paths do not dispatch events and success payload has `message_key=None` (L233-237), matching US-9 (L157-167). |
| v3 locale/isolation/citation issues fixed? | ✅ Pass. Locale scope is Crowdin-managed non-en-US only (L364, L378); PostgreSQL default is READ COMMITTED (L350); FR-014/FR-023 cite `_filter_builder`, `get_one`, and `page_all` (L212-214, L239-240). |

---

## Wrong/imprecise citations

1. **FR-008 scheduler startup citation is incomplete (medium).** FR-008 says the new task must be registered during app startup (spec_v5.md L194-195), but its code references cite only `scheduler_registry.py` and `scheduler_service.py`. The actual startup registration seam is `mealie/app.py` L124-144, where existing tasks are registered with `SchedulerRegistry.register_daily`, `register_minutely`, and `register_hourly`. This does not block implementation, but strict line-range verification of the startup claim needs `mealie/app.py:124-144`.

---

## Executability concerns

### Critical

None.

### High

- **EXEC-H-001 — Edge cases reintroduce rollback/safe-retry guarantees that FR-011/FR-012/FR-020 intentionally defer to NC-004.** FR-011 says the exact rollback semantics for side-effect and dispatch failures are deferred to NC-004, and until NC-004 is resolved the FR specifies only ordering plus CAS-loser short-circuit (spec_v5.md L203). FR-012 likewise says failures during `bulk_create_items` or dispatch roll back the CAS only under PATH A; under PATH B/C the CAS commits immediately and recovery is weaker (L206). FR-020 also defers force-mode rollback to NC-004 (L230). But the edge-case section still states that a recursive expansion failure propagates out of an FR-011 transaction context that **rolls back** the CAS and partial item writes, leaving `last_auto_synced_at` untouched (L352), and that force-mode callers can **safely retry** after mid-transaction exceptions under both PATH A and PATH B/C (L357). Those statements are false under the existing code paths (`RepositoryGeneric.create_many`, `update_many`, and `update` commit internally at `repository_generic.py` L195-244; `add_recipe_ingredients_to_list` calls `bulk_create_items` and then `shopping_lists.update` at `shopping_lists.py` L433-455) unless PATH A or PATH B's extra `sync_attempt_id` machinery is chosen and fully specified. Under PATH C, a force-mode retry after item writes can merge quantities again because `merge_items` sums quantities (shopping_lists.py L73-128, especially L96), so it is not intrinsically safe. Update the edge cases to be NC-004-neutral, or split their expected behavior by PATH A/B/C without making unconditional rollback/safe-retry claims.

### Medium

- **EXEC-M-001 — NC-004 remains a real implementation gate.** The escalation is appropriate, but NC-004 explicitly says human/PM sign-off is needed before the auto-sync FRs can commit to one durability path (spec_v5.md L42-50). If this spec is handed directly to an implementation agent, the agent must either assume the recommended default PATH A or pause for the decision. That is acceptable only if the workflow treats NC-004 as a pre-implementation blocking decision rather than executable feature text.
- **EXEC-M-002 — Startup registration proof should cite `mealie/app.py`.** Add `mealie/app.py` L124-144 to FR-008 so the registration instructions point to the real startup hook, not only the registry and scheduler internals.

---

## Verified key citations

- `mealie/repos/repository_generic.py` L94-102, L156-179, and L315-355 verify the v5 household-scoped filtering citations used by FR-014/FR-023.
- `mealie/repos/repository_generic.py` L195-244 verifies the internal commits that motivate NC-004.
- `mealie/services/household_services/shopping_lists.py` L154-220 and L413-455 verify the existing shopping-list side-effect seam and commit-calling path.
- `mealie/services/event_bus_service/event_bus_service.py` L66-96 verifies dispatch is immediate/background-task publishing, not DB-transactional.
- `mealie/services/event_bus_service/event_types.py` L179-191 verifies empty event message bodies become `generic`, supporting v5's choice not to promise no-op i18n in event payloads.
- `mealie/repos/repository_meals.py` L11-21 verifies household-timezone `get_today(tz=...)` behavior.
