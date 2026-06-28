# Consistency Review v1 — Case-5 Meal Plan Auto-Sync

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION

## Summary

The spec is well structured and `spec.md` and `spec.json` are mostly semantically aligned. However, implementation is not deterministic yet. The main blockers are: target-list fallback is not clearly household-scoped despite the multitenant story, the server-owned `last_auto_synced_at` field is simultaneously exposed for PUT updates and forbidden by a self-concern, and the CAS/update order conflicts with edge-case retry behavior. Resolve the High findings before coding.

## Findings

### C-001 — Default target-list resolution can violate same-group household isolation

- **Severity**: High
- **Scope**: US ↔ FR ↔ SC contradiction
- **Locations**:
  - US-7 requires household A's auto-sync to never write household B's shopping list.
  - FR-10 validates configured `auto_sync_target_shopping_list_id` against `self.household_id`.
  - FR-22 resolves a missing target with `repos.group_shopping_lists.page_all(... order_by="created_at" ...)` but does not state a `household_id` filter.
  - SC-5 requires same-group and cross-group isolation.
- **Issue**: The configured-list path is household-validated, but the fallback path is only described as `group_shopping_lists` with oldest-created ordering. In a same-group multi-household setup, this can be read as selecting another household's oldest list.
- **Recommendation**: Amend FR-22/SC-7 to explicitly filter fallback lists by the current `household_id` and assert the same-group case.

### C-002 — `last_auto_synced_at` is both client-updatable and server-only

- **Severity**: High
- **Scope**: self_concerns ↔ FRs; US ↔ FR contradiction
- **Locations**:
  - US-1 lets admins configure `auto_sync_meal_plan_to_shopping`, target list, run time, and timezone; it does not mention setting the sync marker.
  - FR-7 adds `last_auto_synced_at` to `UpdateHouseholdPreferences`.
  - FR-10 says the existing PUT accepts the 5 new fields via that body.
  - SCN-3 says the PUT route should **not** touch `last_auto_synced_at` and should exclude it before update.
- **Issue**: Implementers cannot both accept/write the marker through preferences PUT and guarantee it is server-owned for CAS correctness.
- **Recommendation**: Remove `last_auto_synced_at` from the update schema or state that the route ignores/excludes it. Keep it only on save/read/internal models if needed.

### C-003 — CAS marker timing conflicts with “no target list retries next tick”

- **Severity**: High
- **Scope**: FR ↔ EC contradiction
- **Locations**:
  - FR-20 says the scheduled path executes the CAS `UPDATE household_preferences SET last_auto_synced_at = :now_utc ...` before any write work and commits immediately.
  - EC-2 says when there is no target list, the scheduler returns early and **does NOT update** `last_auto_synced_at`, so it retries on the next valid tick.
- **Issue**: If the CAS runs before target-list resolution, EC-2 is impossible. If target-list resolution runs before CAS, FR-20's sequencing must say so.
- **Recommendation**: Specify ordering: validate enabled/window, resolve target list, then CAS only when there is sync work worth marking; or explicitly change EC-2 to accept marking no-target runs.

### C-004 — Event payload “only” fields contradict base document fields

- **Severity**: Medium
- **Scope**: FR ↔ SC contradiction
- **Locations**:
  - FR-23 defines `EventMealPlanAutoSyncedData(EventDocumentDataBase)` with `document_type` and `operation` plus the four business fields.
  - SC-4 says the dispatched payload contains only `household_id`, `shopping_list_id`, `added_item_count`, and `skipped_pantry_count`.
- **Issue**: An `EventDocumentDataBase` payload cannot contain only the four listed fields if it also carries `document_type` and `operation`.
- **Recommendation**: Reword SC-4 to say “no recipe titles, meal-plan IDs, or per-item details beyond the standard event metadata.”

### C-005 — “first active main list” is not the same as “oldest shopping list”

- **Severity**: Medium
- **Scope**: FR-internal; FR ↔ SC contradiction
- **Locations**:
  - Feature summary and FR-22 say fallback is the “first active main” shopping list.
  - FR-22/SC-7 implement the rule as `order_by="created_at" asc` / “oldest shopping list”.
  - NC-2 says archived/active status may come from case-2 and is not available today.
- **Issue**: “active” and “main” imply filters/fields that the concrete rule does not define. Implementers may add unsupported filters or ignore intended archive behavior.
- **Recommendation**: Rename the fallback to “oldest household shopping list” for case-5, or add exact active/main predicates and tests.

### C-006 — Manual-trigger marker update is ambiguous for empty/no-op runs

- **Severity**: Medium
- **Scope**: needs_clarification ↔ FRs/defaults; Edge cases ↔ FRs
- **Locations**:
  - Feature summary says run-now bypasses the daily limit but still updates `last_auto_synced_at`.
  - FR-21 updates the marker “after success”.
  - NC-1 default says always update on success, framed as paths that complete `add_recipe_ingredients_to_list`.
  - EC-1 has no meal plan, skips `add_recipe_ingredients_to_list`, but still says manual returns 200 zeros.
  - EC-2 no-target returns 200 zeros but should not update the scheduled marker.
- **Issue**: “Success” is unclear for no-meal-plan and no-target manual runs. The default can be read as always update, only update when add-list runs, or update all 200 responses.
- **Recommendation**: Add an explicit table for manual marker updates: successful add, empty meal plan, no target, invalid/deleted target.

### C-007 — EC-6 requires response/i18n documentation that no FR can satisfy

- **Severity**: Medium
- **Scope**: Edge cases ↔ FRs/ACs
- **Locations**:
  - EC-6 says pantry-staple flagging is “Documented in the i18n message and route response”.
  - FR-9 `AutoSyncRunResult` has only `added_count`, `skipped_pantry_count`, `target_list_id`, and `run_at`.
  - FR-25 i18n keys do not include a pantry-forward-looking message.
- **Issue**: There is no response field or i18n key that could carry this documentation.
- **Recommendation**: Either remove that sentence from EC-6, add a response/message field, or add a concrete i18n/help text requirement.

### C-008 — Constraint mentions group-default timezone, but FRs only define UTC fallback

- **Severity**: Low
- **Scope**: FR ↔ constraints/defaults
- **Locations**:
  - FR-16 says `ZoneInfo(prefs.timezone)` falls back to `ZoneInfo("UTC")` on None or invalid.
  - Constraint says timezone fallback is “household-configured timezone (fallback group default or server default UTC)”.
- **Issue**: No FR defines where a group default timezone comes from or when it should precede UTC.
- **Recommendation**: Remove “group default” from the constraint or add a concrete FR for resolving it.

### C-009 — CAS parameter names drift between FR-20 and SC-11

- **Severity**: Low
- **Scope**: AC-internal / FR ↔ SC
- **Locations**:
  - FR-20 uses `:now_utc`, `:pref_id`, and `:today_start_utc`.
  - SC-11 says bound parameters are `:now`, `:id`, and `:today_start`.
- **Issue**: This is likely cosmetic, but exact SQL assertions could make it observable.
- **Recommendation**: Use one parameter naming convention in both places or state that only bound-parameter usage matters.

## Self-concerns vs FRs / ACs

- **SCN-1** aligns with FR-17/FR-26 and is a valid mitigation for the reused consolidation seam.
- **SCN-2** aligns with FR-7/FR-16; no contradiction, but dependency guidance should remain conditional as written.
- **SCN-3** directly conflicts with FR-7/FR-10 because the spec exposes `last_auto_synced_at` in the PUT body while the concern requires excluding it. This is captured in C-002.

## Edge cases vs FRs / ACs

- **EC-1** aligns with FR-20 for scheduled empty plans, but manual marker behavior is ambiguous because no add-list call occurs (C-006).
- **EC-2** conflicts with FR-20 unless target resolution is specified before CAS (C-003).
- **EC-3** aligns with FR-1's FK `ondelete=SET NULL`, assuming the DB actually enforces the FK.
- **EC-4** aligns with FR-17's recipe filtering intent, though FR-17 should explicitly mention `mp.recipe is None` if tests rely on it.
- **EC-5** aligns with the CAS local-day calculation.
- **EC-6** conflicts with the response/i18n FRs as written (C-007).
- **EC-7** aligns with FR-20.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| Title | `Case 5 — Meal Plan → Shopping List Auto-Sync (Mealie)` | `Meal Plan auto-sync to Shopping List (Mealie)` | Cosmetic capitalization/wording drift only. |
| Intro | States `spec.json` has the “same content” and that code references are verified against `C:\Users\v-liyuanjun\Downloads\mealie\`. | Does not carry this intro/provenance statement. | JSON omits provenance; not a behavioral contradiction. |
| Selected approach | Not a standalone field; approach appears through summary/constraints. | Adds `selected_approach: hybrid_polling_with_shared_helper`. | JSON has extra structured metadata; not contradictory. |
| Code references | Markdown often combines ranges and line prose in one table cell. | JSON splits references into arrays and normalizes some `Lxx` mentions into separate entries. | No material semantic difference found. |
| FR/US/SC/EC/NC/SCN content | Full prose sections. | Structured arrays with matching IDs and substantially identical text. | No material field-by-field content mismatch found beyond formatting/escaping. |
| Constraints | Multi-line bullets, including sub-bullets for repo conventions. | Same constraints compressed into strings. | Same semantics; markdown is easier to read. |

No material `spec.md` vs `spec.json` behavioral disagreement was found. The consistency defects above exist in both representations.

## needs_clarification assessment

- **NC-1** is not blocking, but the default needs sharper wording for no-op manual runs (C-006).
- **NC-2** is acceptable as a cross-case note, but FR-22 should stop saying “active main” until an active/archive field exists (C-005).
- **NC-3** is marked blocking and should be resolved before implementation. Its default is coherent with FR-3/FR-8, but because it is a material product model decision, leaving `blocking: true` means the spec cannot be PASS.

## Recommended resolution order

1. Make target-list fallback explicitly household-scoped.
2. Make `last_auto_synced_at` server-owned and remove/ignore it from PUT.
3. Define CAS ordering around no-target and empty-plan runs.
4. Resolve blocking NC-3 or mark it non-blocking after decision.
5. Clean up the Medium/Low wording drifts before handing to implementation.
