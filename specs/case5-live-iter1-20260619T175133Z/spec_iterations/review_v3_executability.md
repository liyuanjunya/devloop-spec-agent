# Executability Review (v3)

## Verdict: NEEDS_REFINE

v3 fixes the major v2 CAS-ordering, table-name, FK, partial-update, and subscriber-schema gaps on paper. However, the spec is still not executable as written because its "single transaction"/rollback guarantees conflict with the existing shopping-list repository methods that commit internally, and its event-dispatch rollback/exactly-once contract is impossible with the proposed post-commit/after-commit dispatch options. There are also remaining run-now/i18n response contradictions.

---

## Scope checks

| Check | Result |
|---|---|
| All cited paths real? | ✅ Pass. Every `code_references[].path` in `spec_v3.json` exists under `C:\Users\v-liyuanjun\Downloads\mealie\`. |
| All line ranges accurate and cited symbols in range? | ⚠️ Mostly pass. A literal verifier found every cited symbol inside the combined cited ranges, but several ranges do not substantiate the stronger execution/transaction claims; see wrong/imprecise citations. |
| `spec.md` / `spec.json` code references identical for each FR? | ✅ Pass. Parsed all 29 FRs in markdown; each has a code-reference line corresponding to the JSON references, and the v3 build log reports roundtrip consistency. |
| TBD / `or equivalent` / `if needed` phrases? | ✅ Pass. No exact matches in `spec_v3.md` or `spec_v3.json`. |
| ≥3 options pattern in `self_concerns`? | ✅ Pass. Three self-concerns remain, each with one suggested resolution. |
| Scheduler task implementation seam concrete enough? | ✅ Pass. Module, callable, registration bucket, 5-minute interval, and enabled-household query are specified. |
| Pantry filter algorithm pin-pointed? | ✅ Pass. v3 pins filter-after-recursive-expansion and explicit `recipe_ingredients=` override. |
| `LastAutoSyncedAt` storage column concrete? | ⚠️ Partially. Column/CAS SQL is concrete, but rollback/idempotency guarantees are not executable with existing commit boundaries. |
| Concrete query for today's MealPlan in household tz? | ✅ Pass. `RepositoryMeals.get_today(tz=ZoneInfo(...))` maps to `datetime.now(tz).date()` and household-scoped `GroupMealPlan.date == today`. |

---

## Wrong/imprecise citations

1. **FR-011 / FR-012 transaction rollback claim** — `mealie/services/household_services/shopping_lists.py` L154-220 and L413-455 are cited for the side-effect seam, but those ranges do not substantiate "single DB transaction" or rollback of all side effects. They call repository methods that commit: `bulk_create_items` calls `create_many`/`update_many` at L215-216, `add_recipe_ingredients_to_list` calls `bulk_create_items` at L433 and `shopping_lists.update` at L454; the commit sites are in `repository_generic.py` L203, L225, and L243, which are not cited.
2. **FR-011 / FR-012 / FR-020 event rollback claim** — `event_bus_service.py` L60-96 proves dispatch is immediate (or queued to FastAPI `BackgroundTasks`) at L92-96, not transactionally coupled to the DB. FR-011 L192 proposes `session.commit()` followed by dispatch or an `after_commit` hook while also claiming exceptions during dispatch roll back the transaction; those cited event-bus lines do not support that.
3. **US-9 stale run-now response text** — spec lines 151 and 155 still require a no-meal-plan run-now response body containing the localized key/string, but FR-020 L219 and SC-026 L302-303 require HTTP 204 No Content with an empty body. The US citation/text is stale after the v3 rewrite.
4. **FR-022 event-payload i18n claim** — FR-022 L225 says the i18n keys surface "in the event payload," but FR-021 L222 defines `EventMealPlanAutoSyncedData` with only `household_id`, `shopping_list_id`, counts, and `operation`; `EventBusMessage` body handling lives at `event_types.py` L179-191 and is not cited or specified with those keys.
5. **FR-014 / FR-023 repository filtering proof is imprecise** — `repository_factory.py` L317-321 proves `RepositoryShoppingList` is constructed with `household_id`, and `shopping_list.py` L147-181 proves `ShoppingList.household_id` is an association proxy. The actual generic filtering behavior is in `repository_generic.py` L94-102 and L166-173, which are not cited, so the cited ranges alone do not prove "applies it as a WHERE clause on every query."
6. **Out-of-scope locale statement regressed** — Out of Scope line 366 says "Mealie currently ships only en-US.json," contradicting Assumption line 353 and repository reality (42 JSON locale files, including `af-ZA.json`, `de-DE.json`, `fr-FR.json`, `zh-CN.json`).
7. **Two-replica edge-case isolation-level wording** — edge case line 339 says "Postgres default REPEATABLE READ"; PostgreSQL's default isolation level is READ COMMITTED. The row-level UPDATE serialization point is still plausible, but the cited/prose default-isolation detail is wrong.

---

## Executability concerns

### Critical

- **EXEC-C-001 — The required single transaction cannot be achieved by reusing `add_recipe_ingredients_to_list` unchanged.** FR-011 requires the CAS update, `bulk_create_items`, recipe-reference update, and event dispatch to be in one transaction, with any exception rolling back the marker and item writes. But the mandated seam `add_recipe_ingredients_to_list` calls `bulk_create_items` (shopping_lists.py L433), and `bulk_create_items` calls repository `create_many`/`update_many` (L215-216), whose generic implementations commit immediately (`repository_generic.py` L203/L243); the list-level update also commits (`repository_generic.py` L225 via shopping_lists.py L454). A mid-pipeline exception can therefore leave the CAS/items committed despite FR-011/FR-012 saying they roll back. Specify refactoring/no-commit variants or an explicit lower-level transaction-safe implementation.
- **EXEC-C-002 — Event exactly-once + rollback semantics are impossible as specified.** FR-011 permits dispatch by `session.commit()` followed by `EventBusService.dispatch(...)` or an `after_commit` hook, then claims failures during steps 5-6 roll back the transaction and allow retry. Both proposed dispatch mechanisms run after the DB commit boundary; `EventBusService.dispatch` publishes immediately or queues a background task (`event_bus_service.py` L92-96). If dispatch fails after commit, the marker prevents retry and SC-013's exactly-one-dispatch-per-CAS-winner contract can be violated. If dispatch happens before commit, subscribers can observe an event for rolled-back DB writes. Use an outbox table or relax the rollback/exactly-once event guarantee.

### High

- **EXEC-H-001 — Run-now no-content contract still conflicts with US-9.** US-9's independent test and acceptance scenario require the no-meal-plan run-now response body to contain `auto-sync.no-meal-plan-today` (spec.md L151/L155), while FR-020 and SC-026 require HTTP 204 with no body (L219 and L302-303). An implementer cannot satisfy both tests. Update US-9 to assert logs/event message only, or change FR-020/SC-026 to return a body.
- **EXEC-H-002 — Localized event/message surface is underspecified.** FR-022 says the i18n keys appear in event payloads/logs, but FR-021's `EventMealPlanAutoSyncedData` payload has no message/i18n-key field and its dispatch call omits the `message=` argument. Existing `EventBusMessage.from_type(..., body='')` defaults an empty body to `generic` (`event_types.py` L179-191), so webhook/Apprise subscribers will not receive the specified `auto-sync.*` strings unless the spec explicitly passes `message=<key or localized text>` or adds a payload field.

### Medium

- **EXEC-M-001 — Locale out-of-scope text contradicts the corrected locale policy.** Lines 353 and FR-022 correctly say Mealie has 40+ locales and only `en-US.json` is editable, but Out of Scope line 366 reintroduces the v2 false statement that Mealie ships only en-US. Correct to "non-en-US locale edits are out of scope; Crowdin manages them."
- **EXEC-M-002 — PostgreSQL isolation-level wording is wrong.** The two-replica edge case should say Postgres default READ COMMITTED still serializes conflicting row UPDATEs, not "default REPEATABLE READ." This is not necessarily a design failure, but it is a misleading execution claim.
- **EXEC-M-003 — Shopping-list ownership citations should include the actual filter implementation.** FR-014/FR-023 should cite `RepositoryGeneric._filter_builder` and `get_one`/`page_all` filtering (`repository_generic.py` L94-102, L166-173, L328-331) in addition to `repository_factory.py` L317-321, so strict line-range verification proves the WHERE clause claim.

---

## Verified key citations

- `mealie/schema/_mealie/mealie_model.py` L45-53 verifies that `MealieModel` does not globally set `extra='forbid'`, supporting v3's schema-local fix.
- `mealie/db/models/household/events.py` L15-55, `mealie/schema/household/group_events.py` L13-55, and `event_bus_listeners.py` L76-83 verify the new subscriber ORM/schema seam required by FR-028.
- `mealie/services/household_services/shopping_lists.py` L45-128 verifies that `merge_items` sums quantities, so CAS-before-side-effects remains necessary.
- `mealie/repos/repository_meals.py` L11-21 verifies household-timezone "today" selection via `datetime.now(tz).date()` and household filtering.
- `mealie/services/scheduler/scheduler_registry.py` L8-49, `scheduler_service.py` L15-17/L77-81, and `app.py` L124-144 verify the minutely scheduler seam.
