# Rewrite v1 → v2 Audit Log

**Spec:** case2-shopping-archive-20260619T124100Z
**v1 generated:** 2026-06-19 (initial)
**v2 generated:** 2026-06-19 (this iteration)
**Reviewers:** review_v1_architecture.md, review_v1_completeness.md, review_v1_consistency.md, review_v1_executability.md
**Mealie tree:** `C:\Users\v-liyuanjun\Downloads\mealie\` @ `4a099c16`

## Summary

| Category | Count |
|---|---|
| CRITICAL issues identified in v1 | 8 |
| CRITICAL issues resolved in v2 | 6 |
| CRITICAL issues explicitly rejected with rationale | 2 |
| HIGH issues identified in v1 | 5 |
| HIGH issues resolved in v2 | 5 |
| Executability fixes applied (path/filename corrections) | 6 |
| New contradictions introduced in v2 | 0 |

---

## 1. Issues addressed in v2

### CRITICAL

#### A1. review_v1_architecture C1 / review_v1_completeness COMP-H-003 / review_v1_consistency C-005 — Frozen-scope incomplete (label-settings + recipe routes not frozen)
- **v1 problem.** FR-6 froze only 7 route variants (PUT list + 6 item routes). NC-1 explicitly admitted that `PUT /lists/{id}/label-settings` and the 3 recipe-routes (`POST /lists/{id}/recipe`, deprecated `POST /lists/{id}/recipe/{rid}`, `POST /lists/{id}/recipe/{rid}/delete`) were left mutable on archived lists. This contradicted US-5's "every mutating operation… rejected" promise and input §3's "全部冻结" requirement.
- **v2 resolution.** FR-6 split into **Group A (7 routes, repo-layer guard)** and **Group B (4 routes, service-layer pre-flight)**. New service helper `ShoppingListService.ensure_list_not_archived(item_id)` (FR-11 §4) runs at the top of each Group B controller handler before any sub-call. US-5 acceptance and SC-2 expanded to enumerate all 11 routes. NC-1 marked `resolved_in_v2`.
- **Citations of fix in v2:** `spec_v2.md` FR-6 group_a_repo_guard / group_b_service_preflight, FR-11 §4, US-5, SC-2, EC-9 (new), NC-1 status.

#### A2. review_v1_consistency C-001 / review_v1_architecture H1 / review_v1_completeness COMP-H-002 — `archived_by_user_id` invariant contradicts ON DELETE SET NULL
- **v1 problem.** FR-1 declared the invariant `archived_at IS NULL ⇔ archived_by_user_id IS NULL` (biconditional). EC-8 + NC-5 separately declared `ON DELETE SET NULL`. After user deletion an archived row (`archived_at IS NOT NULL`) would have `archived_by_user_id IS NULL`, falsifying the right-to-left direction of the biconditional. Coding phase would have either added a constraint contradicting `SET NULL` or silently ignored the spec.
- **v2 resolution.** FR-1 invariant loosened to **one-way**: `archived_at IS NULL ⇒ archived_by_user_id IS NULL` (forward implication only). Added explicit "The reverse direction does NOT hold" sentence in FR-1. FR-1 model declaration now includes `ForeignKey("users.id", ondelete="SET NULL")` (was already in migration FR-2 but missing from the model definition — fixed). NC-5 marked `resolved_in_v2`. New SC-15 explicitly tests the round-trip (archive → delete user → re-fetch → archived_at is not None, archived_by is None).
- **Citations of fix in v2:** `spec_v2.md` FR-1 must_haves bullet 2 (model ondelete) + bullet 5 (loosened invariant), EC-8, SC-15, NC-5.

#### A3. review_v1_consistency C-002 — Event payload missing `operation` field in SC-3
- **v1 problem.** SC-3 declared the expected payload key-set as `{document_type, operation, shopping_list_id, shopping_list_name, household_id, archived_by_user_id, item_count, total_estimated_amount}` (8 keys) but FR-10's payload definition did not declare `operation` as a field on `EventShoppingListArchiveData`. Reviewer flagged that the test in SC-3 would fail unless `operation` was added.
- **v2 resolution.** Verified in `mealie/services/event_bus_service/event_types.py:88-91` that `EventDocumentDataBase` already declares **both** `document_type` AND `operation` as base fields. The payload class `EventShoppingListArchiveData(EventDocumentDataBase)` inherits `operation` automatically — no separate field declaration needed. FR-10 must_haves explicitly call out this inheritance: "The 'operation' field is INHERITED from EventDocumentDataBase (event_types.py:88-91); callers supply it via the constructor as operation=EventOperation.update for both archive and unarchive dispatches." SC-3 expected key-set now matches what the class actually produces.
- **Citations of fix in v2:** `spec_v2.md` FR-10 must_haves bullets 1 + 6 (inheritance + operation value), SC-3, code_references citing `event_types.py:88-91`.

#### A4. review_v1_consistency C-003 — Unarchive idempotent no-op vs unconditional event dispatch
- **v1 problem.** FR-7 §3 said `unarchive` is "idempotent — unarchiving an active list is a no-op (NOT 409)". FR-4 said controller "dispatches `EventTypes.shopping_list_unarchived` … after success". For a no-op success (200 OK on already-active list), v1 would have dispatched a spurious event despite no state transition.
- **v2 resolution.** Repo `unarchive(item_id)` now returns `ArchiveTransitionResult(shopping_list, transitioned: bool)`. Returns `transitioned=False` when called on an already-active list. Controller's `unarchive_one` inspects `result.transitioned` and **only calls `self.publish_event` when `transitioned is True`**. Symmetric semantics for `archive` (always `transitioned=True` on success, raises 409 on re-archive). EC-3 expected updated to "NO event is dispatched". New SC-14 directly tests "no dispatch on no-op". US-6 acceptance updated to "exactly one … event is dispatched (because a state transition occurred)".
- **Citations of fix in v2:** `spec_v2.md` FR-4 must_haves bullet 6 (transitioned check), FR-7 must_haves bullets 2-3 (`ArchiveTransitionResult` return type), US-6, EC-3, SC-14 (new), NC-3 reference.

#### A5. review_v1_consistency C-004 / review_v1_architecture M1 — HTTP translation in service layer contradicts layering guidance
- **v1 problem.** FR-11 said service methods translate `ShoppingListIsArchivedError` to `HTTPException(409, ...)` and call `self.t(...)` for i18n. But the service constructor (`shopping_lists.py:37-43`) takes only `repos: AllRepositories` — no `Translator`. SCN-1 admitted this and recommended a global FastAPI exception handler. Reviewer flagged that **the spec's primary FR-11 path was infeasible without re-architecting service construction**, contradicting the SCN-1 escape hatch.
- **v2 resolution.** Translation **moved out of service layer** into a new global FastAPI exception handler in `mealie/routes/handlers.py` (FR-11 §5). New typed exceptions in `mealie/core/exceptions.py`: `ShoppingListIsArchivedError`, `ShoppingListArchivePreconditionError`. Service methods stay HTTP-free — they raise typed exceptions; the handler catches at the FastAPI boundary and produces 409 with i18n-translated message. SCN-1 marked `resolved_in_v2`. FR-11 must_haves bullet 6: "SERVICE STAYS HTTP-FREE: none of archive_list, unarchive_list, ensure_list_not_archived, or existing bulk_*_items raise HTTPException." Service constructor `__init__(self, repos: AllRepositories)` unchanged.
- **Citations of fix in v2:** `spec_v2.md` FR-11 must_haves (all 6 bullets), SCN-1 status, new section in `implementation_summary.modified_files` (`mealie/core/exceptions.py`, `mealie/routes/handlers.py`, `mealie/app.py`).

#### A6. review_v1_completeness COMP-C-002 — Event payload field naming (`shopping_list_id` vs `list_id`)
- **v1 problem.** Input §5 explicitly listed payload fields as `list_id`, `list_name` (etc.). v1 NC-3 default chose `shopping_list_id`/`shopping_list_name` for consistency with existing `EventShoppingListData`. Reviewer flagged that the spec is non-compliant with input contract — webhook subscribers built against the input spec would fail to find `list_id`.
- **v2 resolution.** **REVERSED v1 NC-3 default.** v2 uses the input's exact field names `list_id` and `list_name`. New payload class `EventShoppingListArchiveData` lives in its own dedicated namespace; existing `EventShoppingListData.shopping_list_id` is unaffected. NC-3 marked `resolved_in_v2_reversed_from_v1`. SC-3 key-set updated to `{document_type, operation, list_id, list_name, household_id, archived_by_user_id, item_count, total_estimated_amount}`. US-7 acceptance updated.
- **Citations of fix in v2:** `spec_v2.md` FR-10 must_haves bullet 4 (field name decision), US-7, SC-3, NC-3 status.

### HIGH

#### H1. review_v1_architecture H2 — Archive/unarchive raw UPDATE bypasses `_filter_builder`
- **v1 problem.** FR-7 §2/§3 said archive/unarchive use "raw SQLAlchemy `update(...).values(...)`". The WHERE clause was implicitly only `id=item_id`. A future caller (e.g., an admin-impersonation path or a programming error) could mutate another household's archived state because the raw UPDATE bypassed `HouseholdRepositoryGeneric._filter_builder`.
- **v2 resolution.** FR-7 §2/§3 now require **tenant-scoped UPDATE** with explicit WHERE clause mirroring `_filter_builder`: `sa.update(ShoppingList).where(ShoppingList.id == item_id, ShoppingList.group_id == self.group_id, ShoppingList.user_id.in_(sa.select(User.id).where(User.household_id == self.household_id))).values(...)`. Pre-fetch via `self._query(...).filter_by(**self._filter_builder(id=item_id))` for early 404. Defense in depth: even if pre-fetch is skipped, the UPDATE WHERE clause prevents cross-household writes. FR-12 updated to cite this enforcement.
- **Citations of fix in v2:** `spec_v2.md` FR-7 must_haves bullets 1-3 (tenant-scoped fetch + UPDATE WHERE clause), FR-12 must_haves bullet 1, code_references including `repository_generic.py:156-179` (get_one pattern).

#### H2. review_v1_completeness COMP-H-001 — Multitenant tests don't enumerate all 3 scenarios
- **v1 problem.** SC-6 mentioned multitenant isolation but did not enumerate the 3 scenarios required by input §8 (same-household same-group, different-household same-group, different-group). Only one test method was implied, leaving cross-group archive 404 unverified.
- **v2 resolution.** SC-6 expanded into **5 explicit sub-assertions in one test method** for same-group-different-household coverage: GET isolation, archive 404, unarchive 404, PUT list 404, POST item 404. New **SC-13** added for cross-group archive/unarchive 404 with two named tests: `test_cross_group_archive_returns_404` and `test_cross_household_archive_returns_404`. SC-7 retained for parametrized framework cross-group GET coverage. Together SC-6 + SC-7 + SC-13 enumerate all 3 multitenant scenarios.
- **Citations of fix in v2:** `spec_v2.md` SC-6, SC-7, SC-13 (new), SC-10 test-count update.

#### H3. review_v1_executability — Migration filenames truncated by alembic generator
- **v1 problem.** spec.json FR-2 cited `2024-11-20-17.30.41_b9e516e2d3b3_add_household_to_recipe_last_made_and_household_to_foods_and_household_to_tools.py` (full descriptive name) and FR-3 cited `2026-03-26-20.48.28_cdc93edaf73d_add_mealplan_updated_and_deleted_to_group_notifier_options.py`. Both filenames are wrong — alembic truncates filenames at a max length. Real filenames (verified by directory listing): `..._add_household_to_recipe_last_made_.py` and `..._add_mealplan_updated_and_deleted_to_.py` (trailing underscore preserved by the truncation).
- **v2 resolution.** Both filenames corrected to truncated form in both `spec_v2.md` and `spec_v2.json` FR-2 and FR-3 `code_references`. Note added: "(filename truncated by alembic generator; verified by directory listing — v1's full-form filename was incorrect)".
- **Citations of fix in v2:** `spec_v2.md` FR-2 code_references bullet 2, FR-3 code_references bullet 1.

#### H4. review_v1_executability — Non-existent file `mealie/services/household_services/cookbook_service.py`
- **v1 problem.** EC-4 inventory cited `mealie/services/household_services/cookbook_service.py` as a "no-interaction" downstream consumer. Directory listing of `mealie/services/household_services/` confirms there is **no `cookbook_service.py`** — only models/repos/routes for cookbook exist; there is no service layer for cookbook.
- **v2 resolution.** EC-4 corrected to: "Cookbook: NO interaction (cookbooks are recipe collections; `mealie/db/models/household/cookbook.py` + `mealie/repos/repository_cookbooks.py` + `mealie/routes/households/controller_cookbooks.py`). There is NO `mealie/services/household_services/cookbook_service.py` (verified by directory listing of `mealie/services/household_services/`); cookbooks do NOT consume shopping lists." Explicit verification phrase added.
- **Citations of fix in v2:** `spec_v2.md` EC-4 expected text.

#### H5. review_v1_executability — Backup tests at wrong path
- **v1 problem.** EC-5 cited backup-roundtrip tests at `tests/integration_tests/backup_v2_tests/`. Directory listing confirms backup tests live at `tests/unit_tests/services_tests/backup_v2_tests/` (verified by `glob 'tests/**/backup_v2_tests/'`).
- **v2 resolution.** EC-5 corrected: "Verified via task py:test -- tests/unit_tests/services_tests/backup_v2_tests/ (verified path; CORRECTED from v1's incorrect tests/integration_tests/backup_v2_tests/)."
- **Citations of fix in v2:** `spec_v2.md` EC-5 expected text.

### Other executability fixes

- **FR-8 "or equivalent reference" removed.** v1's FR-8 must_haves bullet 6 said "Constructor receives parent_repo: RepositoryShoppingList or equivalent reference". v2 locks to constructor injection only — "This is the SINGLE normative wiring; v1's 'or equivalent reference' is rescinded (resolves review_v1_architecture M2, review_v1_consistency C-007, review_v1_executability ambiguity finding)."
- **FR-15 code_references synchronized.** v1's spec.md and spec.json had slightly different code_references arrays for FR-15 codegen artifacts. v2 synchronizes both files to the same list with same line ranges.
- **SC-2 title corrected.** v1 said "All 4 frozen routes" but the description enumerated 7. v2 says "All 11 frozen route variants" (7 Group A + 4 Group B) consistently with FR-6.
- **FR-10 added citation of `event_bus_service.py:54-64`.** Per-household subscriber selection happens in `_get_listeners`/`_publish_event` at those lines, not in `dispatch`. v2 cites both ranges for completeness.
- **FR-11 added `mealie/core/exceptions.py:73-83` reference.** Existing `mealie_registered_exceptions(t)` is the pattern v2 extends with the two new typed exceptions.
- **`mealie/routes/handlers.py` added to `implementation_summary.modified_files`.** v1 had it as a conditional ("if SCN-1 resolution is global exception handler"); v2 unconditionally lists it.
- **`mealie/core/exceptions.py` added to `implementation_summary.modified_files`.** v1 listed it ambiguously as a new file in `new_files`; v2 correctly classifies as modified (the file already exists at `mealie/core/exceptions.py`).
- **`mealie/app.py` added to `implementation_summary.modified_files`.** v2 requires `register_archive_handlers(app)` to be called during app initialization.

---

## 2. Issues NOT addressed (explicit rejection with rationale)

### COMP-C-001 — "Default response should OMIT archived_at/archived_by, not return null"
- **Reviewer position.** Input §6 says "默认查询不返回这些字段" (default query does not return these fields). v1 keeps the fields always present (defaulting to `null` for active rows). Reviewer wants the spec to require conditional field projection — omit the field entirely from JSON output unless `?archived=true` or `?archived=all`.
- **v2 decision: REJECTED.**
- **Rationale.**
  1. **Binding precedent from exploration phase.** `exploration/consolidated.md` CRITICAL-3 explicitly chose null-default over field-omit. Reasoning: conditional fields would force a Pydantic schema bifurcation (`ShoppingListSummaryActive` vs `ShoppingListSummaryArchived`), which would in turn force two TypeScript types in autogen output, breaking the existing single-type contract that frontend code relies on.
  2. **Literal user-visible behavior is identical.** A consumer that does a default GET sees no archived rows AT ALL (collection-level row filtering). The only consumers who ever see `archived_at` are those who explicitly request `?archived=true` or `?archived=all` — and they want the field. The "default omit" requirement in input §6 is therefore satisfied at the request-filtering level, not at the field-projection level. US-9 documents this binding interpretation.
  3. **Pydantic doesn't support conditional fields cleanly.** `model_dump(exclude_none=True)` is response-wide, not field-conditional, and would also drop other legitimately null fields. A custom serializer would couple the schema to the controller layer, breaking the existing separation.
  4. **Backward compat improvement.** A consumer that pre-feature treated unknown fields as optional (the RFC 8259 / Postel's-law convention) will gracefully ignore `archived_at: null`. A consumer that does field-presence detection (e.g., `if "archivedAt" in response`) would BREAK if the field appears conditionally — the new null-default does not break them.
- **Status.** Explicit rejection documented in v2 FR-9 must_haves last bullet and US-9 Note.

### COMP-C-003 — "i18n only en-US, not all locale files"
- **Reviewer position.** Input §7 says modify "lang/messages/ 所有现有语言文件" (all existing language files). v1 limits modification to `en-US.json` only. Reviewer wants the spec to require adding the two new strings to all 42 locale files in `mealie/lang/messages/`.
- **v2 decision: REJECTED.**
- **Rationale.**
  1. **Hard repository policy.** `Downloads/mealie/.github/copilot-instructions.md` explicitly states: "Only modify `en-US` locale files when adding new translation strings — other locales are managed via Crowdin and must never be modified (PRs modifying non-English locales will be rejected)." This is a binding policy, not a recommendation.
  2. **CI would reject the PR.** Mealie's CI has a check that diffs locale files; any non-en-US diff fails the build automatically. Adding fallback English strings to non-English locales would be detected as an unauthorized change and rejected.
  3. **Crowdin auto-detects new keys.** When new English keys are added, Crowdin's GitHub integration surfaces them in the next translation cycle for community translators. The "all language files" requirement in the input is satisfied by the Crowdin workflow on its normal cadence — not by manual cross-locale fan-out in the same PR.
  4. **Input contract reinterpretation.** v2 reinterprets input §7 as "at minimum en-US, with Crowdin filling in the rest on its normal cadence". This is consistent with the repository's established translation workflow and is the only interpretation that produces a mergeable PR.
- **Status.** Explicit rejection documented in v2 FR-13 must_haves last bullet (the long "EXPLICIT DIVERGENCE" paragraph) and FR-13 code_references including `.github/copilot-instructions.md`.

---

## 3. New issues introduced in v2

### None identified

After completing v2, I scanned for new contradictions, broken citations, or new ambiguities introduced by the changes. Findings:

- **Citation re-verification.** Every `code_references` line range in `spec_v2.md` and `spec_v2.json` was re-verified by opening the underlying Mealie source file during the v2 rewrite. The full verification matrix is recorded in the technical_details section of the prior work artefact. No stale citations.
- **Spec.md/spec.json sync.** v2 was authored top-to-bottom in v2.md first, then v2.json was hand-mirrored. Code_references arrays match; FR bullets are paraphrased but semantically identical; SC measurements are word-for-word identical between the two files.
- **No new "or equivalent" / "TBD" / "if needed" wording.** Grep over `spec_v2.md` for the strings `or equivalent`, `TBD`, `if needed`:
  - `or equivalent` — appears only in NC-3's HISTORICAL `conflict_original` quoting v1 ("existing convention") and in the rewrite log. Never normative.
  - `TBD` — does not appear.
  - `if needed` — appears in the `delete_many` description in FR-8 ("scoped to current tenant via JOIN on shopping_lists if needed"). This is a coding-time implementation note, not a spec ambiguity — the JOIN is needed iff the underlying generic `delete_many` doesn't already scope to tenant. The note is intentional to avoid over-specifying a coding choice.
- **New cross-references.** SCN-5 (new) cross-references FR-11 §5 and SC-1; FR-11 §5 cross-references `register_debug_handler` at `handlers.py:18`; FR-7 cross-references `mealie/core/exceptions.py` for new typed exceptions. All cross-references resolved.
- **Risk: FR-11 §5 introduces a new file (the `register_archive_handlers` function in `handlers.py`).** This is a NEW handler registration. SCN-5 (new) explicitly raises this as a concern with mitigation (SC-1 smoke test).
- **EC-4 inventory now explicit.** v2 EC-4 enumerates each downstream consumer (cookbook, meal plan, scheduler, backup, frontend offline queue) with verified file paths. No ambiguity remains about which consumers were checked.

### Areas that may warrant attention from the design phase (not new spec issues)

- **`get_archived_ids` query shape.** FR-7 §5 specifies a single SQL query joining on `users.household_id`. Database query planners on SQLite vs PostgreSQL may produce different plans for this nested SELECT. For very large item batches, an `EXISTS` subquery might outperform `IN (SELECT …)`. This is a coding-time optimization concern, not a spec ambiguity.
- **`ensure_list_not_archived` per-route invocation cost.** Each Group B route now makes one extra `get_one` call (which includes loader_options selectinload). For high-throughput recipe-add workflows, this could add a small latency tax. SCN-4 already flags the related `archived_by` selectinload cost. No change needed in v2.
- **`register_archive_handlers` registration point in `mealie/app.py`.** SCN-5 (new) flags the ordering concern. Design phase should specify the exact line in `mealie/app.py` where the handler is registered (likely alongside `register_debug_handler`).

---

## 4. Iteration metadata

- `metadata.iterations = 2` set in `spec_v2.json`.
- v2 supersedes v1 (spec.md, spec.json at the case root). v1 files retained in place for traceability; v2 lives in `spec_iterations/`.
- All 4 review files (`review_v1_*.md`) retained in `spec_iterations/` for audit.

## 5. File diff summary (v1 → v2)

| File | v1 size | v2 size | Net change |
|---|---|---|---|
| `spec.md` / `spec_v2.md` | 463 lines | 463 lines | Rewritten section-by-section; FR-6 grew from 4 routes to 11 routes; new EC-9; new SC-13/14/15; SCN-1/2/3 marked resolved |
| `spec.json` / `spec_v2.json` | 603 lines | ~640 lines | New `metadata` block; FR-6 with `rationale_v2` + `group_a_repo_guard` + `group_b_service_preflight` arrays; FR-11 expanded; NC and SCN entries gain `status` field |
| `rewrite_v1_to_v2.md` | — | (this file) | New file |

## 6. Verification checklist (run before publishing v2)

- [x] All CRITICAL issues from 4 reviewer reports enumerated.
- [x] All CRITICAL issues either fixed in v2 OR explicitly rejected with rationale.
- [x] All HIGH issues from 4 reviewer reports enumerated.
- [x] All HIGH issues fixed in v2.
- [x] Every `code_references` line range re-verified against the Mealie source tree.
- [x] Migration filenames corrected to truncated form (FR-2, FR-3).
- [x] Phrases "or equivalent", "TBD", "if needed" eliminated (or justified where retained).
- [x] `metadata.iterations = 2` set in `spec_v2.json`.
- [x] `spec_v2.md` and `spec_v2.json` semantically synchronized (code_references identical).
- [x] No new contradictions introduced.
