# Meta-Review v3 — Case-5 LIVE RUN ITER 4

**Judge:** claude-opus-4.7 (meta + rewriter, iter 4)
**Inputs:** `review_v3_{architecture,completeness,executability,consistency}.md`, `spec_v3.md`, `spec_v3.json`, `meta_review_v2.{md,json}`, `rewrite_v2_to_v3.md`, `input.md`, Mealie source at `C:\Users\v-liyuanjun\Downloads\mealie\`.

## Verdict

v3 spec **CONVERGENCE FAILED — REWRITE REQUIRED**. Across four axes there are **3 critical + 3 high + 4 medium + 1 low** findings. Strong convergence: **6 of 7 critical+high findings stem from a single architectural impossibility** — v3 promised one rollbackable DB transaction over CAS marker + shopping-list writes + post-commit event dispatch, but the existing `RepositoryGeneric.create_many` / `update_many` / `update` commit internally, `bulk_create_items` delegates to them, and `EventBusService.dispatch` publishes externally. This is the **same architectural impossibility flagged by all 4 reviewers** under different IDs (NEW-ARCH-C-1, NEW-ARCH-H-1, EXEC-C-001, EXEC-C-002, C3-001, COMP-H-013).

The v4 resolution is the **outbox pattern with a no-commit refactor** — recommended explicitly by ARCH, COMP, CONS, and EXEC reviewers in nearly identical wording. The fix involves: (1) escalating the architecture choice as NC-004; (2) adding `commit: bool = True` kwargs on the existing committing seams (FR-030); (3) adding an `event_outbox` table + `dispatch_event_outbox` minutely task (FR-031); (4) rewriting FR-011 / FR-012 / FR-020 / FR-021 / FR-024 to mirror the new pattern; (5) updating SC-007 / SC-013 / SC-025 to assert outbox row counts; (6) adding SC-030 (commit=False suppression), SC-031 (dispatcher behavior), SC-032 (atomic 3-stage rollback). The remaining HIGH (US-9 contradiction + missing message_key) and MEDIUM/LOW items have one-paragraph fixes each.

## Recommended fix order

1. **META-V3-001** (CRITICAL — outbox pattern + no-commit refactor) — resolves 6 of 7 critical+high findings in one architectural change.
2. **META-V3-002** (HIGH — US-9 vs FR-020/SC-026 204 contract) — independent text fix in US-9.
3. **META-V3-003** (HIGH — message_key field on EventMealPlanAutoSyncedData) — small payload addition that unblocks FR-022 logging vs event-payload split.
4. **META-V3-004** (MEDIUM — locale OOS stale sentence) — 1-line text fix.
5. **META-V3-005** (MEDIUM — Postgres isolation level wording) — 1-line text fix.
6. **META-V3-006** (MEDIUM — FR-014/FR-023 filter implementation citations) — add 3 line ranges per FR.
7. **META-V3-007** (LOW — reciprocal SC↔FR links) — JSON metadata fix.

## Actions

| ID | Pri | Sev | Axes | Sources | Action |
|---|---|---|---|---|---|
| META-V3-001 | 1 | critical | arch, comp, cons, exec | NEW-ARCH-C-1, NEW-ARCH-H-1, EXEC-C-001, EXEC-C-002, C3-001, COMP-H-013 | (a) Escalate transactional architecture decision as **NC-004**: recommended_default = outbox pattern + no-commit refactor; if_rejected = partial-failure tolerance with `sync_attempt_id` idempotency + retry SC. (b) Add **FR-030**: `commit: bool = True` kwarg on `RepositoryGeneric.create_many` (`repository_generic.py:195-208`), `update` (`:210-226`), `update_many` (`:228-244`), `ShoppingListService.bulk_create_items` (`shopping_lists.py:154-220`), `ShoppingListService.add_recipe_ingredients_to_list` (`shopping_lists.py:413-445`). When `commit=False`, the methods stage writes via `session.add_all` / direct UPDATE but skip `self.session.commit()`. Existing callers keep `commit=True` default — zero behavior change. (c) Add **FR-031**: `event_outbox(id, group_id, household_id NULL, event_type, payload_json, created_at, dispatched_at NULL, attempts INT, last_error NULL)` table + `RepositoryEventOutbox` + `dispatch_event_outbox()` minutely scheduler task that polls undispatched rows, calls `EventBusService.dispatch(...)`, marks `dispatched_at` on success, increments `attempts` on failure (MAX_ATTEMPTS=5 dead-letter). (d) Rewrite **FR-011** to use outer `with session.begin():` block with CAS UPDATE → `bulk_create_items(commit=False)` → `event_outbox` INSERT → single atomic commit. (e) Rewrite **FR-012** to reflect outbox-aware rollback semantics. (f) Rewrite **FR-020** to mirror outbox pattern in force-mode. (g) Update **FR-024 step D** to create `event_outbox` table + indices. (h) Update **SC-007 / SC-013 / SC-025** to assert outbox row counts instead of (or in addition to) dispatch counts. (i) Add **SC-030** (`commit=False` suppresses internal commit), **SC-031** (dispatcher poll + retry behavior with `dispatched_at` / `attempts` semantics), **SC-032** (atomic 3-stage rollback: marker + items + outbox row all absent post-exception). |
| META-V3-002 | 2 | high | comp, cons, exec | COMP-H-013, C3-002, EXEC-H-001 | Rewrite **US-9** description / `independent_test` / AC1 / AC2 to align with FR-020 / SC-026 204-no-body contract: the run-now precondition-failure response is HTTP 204 with `Content-Length=0`; the i18n key surfaces in (a) server-side WARN logs and (b) the new `message_key` field on `EventMealPlanAutoSyncedData` (FR-021), NOT in the HTTP response body. Update AC3 to assert outbox-loser semantics: same-day re-run inserts zero outbox rows so subscribers receive zero additional events. |
| META-V3-003 | 2 | high | exec, cons | EXEC-H-002, C3-003 | Add `message_key: str | None = None` field to **EventMealPlanAutoSyncedData** (FR-021). The outbox dispatcher (FR-031) forwards via `EventBusService.dispatch(..., message=message_key or '')` so subscribers receive the key in `EventBusMessage.body`. Update **FR-022** to explicitly state the i18n keys surface in (a) logs and (b) the `message_key` payload field — NOT in HTTP response body. Update **Key Entities → EventMealPlanAutoSyncedData** to add the field. |
| META-V3-004 | 3 | medium | cons, exec | C3-004, EXEC-M-001 | Replace the stale Out-of-Scope sentence `Mealie currently ships only en-US.json` with `Internationalization changes for non-en-US locales. Mealie ships 40+ Crowdin-managed locale files at mealie/lang/messages/*.json; per .github/copilot-instructions.md Translations section only en-US.json is editable by repository contributors; PRs touching other locale files are rejected.` This aligns Out-of-Scope with FR-022 + Assumption #3. |
| META-V3-005 | 3 | medium | exec | EXEC-M-002 | Fix the two-replica edge case wording: PostgreSQL default isolation level is READ COMMITTED (not REPEATABLE READ). Add explicit note that READ COMMITTED still serializes concurrent UPDATEs on the same row via row-level write locks, so the CAS race semantics are unchanged. SQLite's per-statement lock wording is retained. |
| META-V3-006 | 3 | medium | exec | EXEC-M-003 | Add citations to `mealie/repos/repository_generic.py` for the actual filter implementation on FR-014 / FR-023: `_filter_builder` L94-102, `get_one` L156-179, `page_all` L315-355. Update FR-014 / FR-023 prose to reference `_filter_builder` so the household-scope claim is concretely verifiable. |
| META-V3-007 | 4 | low | cons | C3-005 | Add reciprocal SC↔FR links in `spec_v4.json`: `FR-020.related_success_criteria` += SC-026; `FR-022.related_success_criteria` += SC-026; `FR-021.related_success_criteria` += SC-027; `FR-024.related_success_criteria` += SC-027; `FR-001.related_success_criteria` += SC-028; `FR-023.related_success_criteria` += SC-029; also add `SC-029.related_requirements` += FR-029. |

## Cross-axis conflicts

| # | Type | Where | Resolution |
|---|---|---|---|
| 1 | Substantive convergence | All 4 axes flag the same "single rollbackable transaction" impossibility | **Merged in META-V3-001:** outbox pattern + no-commit refactor. Adopted as NC-004 recommended_default (with partial-failure tolerance as if_rejected). This is the same fix three of four reviewers (ARCH, CONS, EXEC) explicitly recommend, almost verbatim. |
| 2 | Latent | ARCH: "use outbox" vs EXEC: "weaken exactly-once guarantee" | **Resolved in META-V3-001 + NC-004:** outbox preserves exactly-once-per-CAS-winner (subscribers see one delivery per outbox row), while at-least-once on retry. NC-004's if_rejected path explicitly weakens the guarantee to at-least-once and adds idempotency markers; this is the documented alternative. |
| 3 | Latent | COMP: "US-9 needs response body" vs FR-020/SC-026: "204 no body" | **Merged in META-V3-002:** the input requirement 5 (204 / 0 added) wins. US-9 is rewritten to assert logs + `message_key` event field instead of response body. |
| 4 | Latent | C3-003 (no message_key) vs FR-022 (claims event payload carries key) | **Merged in META-V3-003:** add `message_key: str \| None = None` to EventMealPlanAutoSyncedData. Single small additive payload field resolves both reviews. |
| 5 | None substantive | — | All 4 axes converge on the same critical defect. No reviewer-vs-reviewer disagreement on whether to fix anything. |

## Severity rollup vs reviewer claims

| Reviewer | Reviewer-claimed counts | Folded into meta priority |
|---|---|---|
| Architecture | 1 critical + 1 high + 2 medium | 1 critical → META-V3-001. 1 high → META-V3-001. 2 medium (US-9 + locale OOS) → META-V3-002 + META-V3-004. |
| Completeness | 0 critical + 1 high + 0 medium | 1 high → META-V3-002. |
| Consistency | 1 blocking + 1 high + 2 medium + 1 low | 1 blocking → META-V3-001 (same root cause as ARCH critical). 1 high → META-V3-002. 1 medium (message_key) → META-V3-003. 1 medium (locale) → META-V3-004. 1 low → META-V3-007. |
| Executability | 2 critical + 2 high + 3 medium | 2 critical → META-V3-001. 1 high (US-9) → META-V3-002. 1 high (message_key) → META-V3-003. 1 medium (locale) → META-V3-004. 1 medium (Postgres isolation) → META-V3-005. 1 medium (filter citations) → META-V3-006. |

## V2→V3 regression check (already validated by A1; cross-confirmed here)

| v2 META action | v3 disposition | Regression risk |
|---|---|---|
| META-V2-001 (CAS BEFORE side effects) | Partially resolved — ORDERING correct, but the "single rollbackable transaction" claim is incompatible with internally-committing repo methods. | **Yes — this is the v3 critical that triggers META-V3-001.** v4 fully resolves via outbox + no-commit refactor. |
| META-V2-002 (subscriber table/model/schema) | Resolved (FR-024 step C correct; FR-028 ORM/schema added; SC-027 in place). | None. |
| META-V2-003 (extra='forbid' on partial schema) | Resolved (FR-004 + SC-018). | None. |
| META-V2-004 (PATCH column-set UPDATE) | Resolved (FR-006). | None. |
| META-V2-005 (run-now HTTP 204 contract) | Partially resolved — FR-020 / SC-026 correct, but US-9 still requires body on the same path. | **Partial — see META-V3-002.** |
| META-V2-006 (FK migration ondelete='SET NULL') | Resolved (FR-024 step A + SC-028). | None. |
| META-V2-007 (association CASCADE) | Resolved (FR-002 + FR-024 step B). | None. |
| META-V2-008 (cross-group multitenant) | Resolved (FR-029 + SC-029). | None. |
| META-V2-009 (FR-009 enumeration query) | Resolved. | None. |
| META-V2-010 (locale correction) | Resolved in FR-022 + Assumption #3, but Out-of-Scope text regressed. | **Partial — see META-V3-004.** |
| META-V2-011 (no-meal-plan re-trigger window) | Resolved. | None. |
| META-V2-012 (reciprocal JSON links) | Mostly resolved, four one-way edges remain. | **Partial — see META-V3-007.** |

## Summary

Four axes converge tightly on a single dominant architectural defect — **CAS + side effects + event dispatch cannot share a single rollbackable transaction** because the existing repo + service seams commit internally and the event bus publishes externally. The cleanest fix is the **outbox pattern** with a small no-commit refactor of the affected repo methods; this preserves exactly-once-per-CAS-winner delivery, makes the rollback claim trivially true (a single explicit `with session.begin():` block), and decouples external delivery latency from the auto-sync transaction.

The other 3 high blockers (US-9 vs 204 contract, missing `message_key` on event payload, stale locale OOS sentence) have one-paragraph fixes each. The 4 medium / 1 low items are mechanical polish.

Apply META-V3-001 through META-V3-007 in a single rewriter pass. Bump `metadata.iterations` to 4. Expect 0 critical + 0 high on all 4 axes for v4.
