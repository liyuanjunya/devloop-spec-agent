# Consistency Review v1 — Case-5 LIVE RUN

**Reviewer:** Consistency Reviewer  
**Inputs:** `spec.md`, `spec.json`  
**Verdict:** **REVISE** — several internal contradictions would lead implementation and tests to choose incompatible behavior.

## Summary

The markdown and JSON are mostly aligned representations, but the spec is not internally consistent. The blocking issues are marker/CAS timing, run-now versus daily idempotency, pantry filtering through an API that is specified to fetch all ingredients, and client exposure of the server-owned sync marker.

## Findings

### C-001 — Daily idempotency threshold conflicts between FR-008 and FR-010
**Severity:** Blocking  
**Scope:** US ↔ FR ↔ SC contradictions; AC-internal contradictions

- FR-008 exits when `last_auto_synced_at` is later than `(household_local_today - 30 minutes)`.
- FR-010's CAS allows sync when `last_auto_synced_at IS NULL OR last_auto_synced_at < :today_local_midnight_utc`.
- US-2/SC-003 require one sync per household-local day.

**Issue:** A household synced at 23:45 yesterday is later than today's midnight minus 30 minutes, so FR-008 would skip today, while FR-010 would allow today.  
**Recommendation:** Use one local-day boundary rule. If the 30-minute window is about when the scheduler may run, express it as a current-time window, not as the previous marker cutoff.

### C-002 — CAS ordering contradicts no-op edge cases
**Severity:** Blocking  
**Scope:** FR ↔ Edge cases; US ↔ FR

- FR-010 updates `last_auto_synced_at` before reading meal plans and aborts if rowcount is zero.
- Edge cases for no meal plan, missing list, and deleted list say the task skips without bumping `last_auto_synced_at`.
- US-2 AC1 says the marker is set when ingredients are merged.

**Issue:** If the CAS runs before meal/list resolution, no-op runs still consume the daily sync marker.  
**Recommendation:** Specify ordering: resolve target and meal work first, then perform CAS immediately before appending, or revise the edge cases to accept marker updates on no-op runs.

### C-003 — Run-now cannot satisfy US-3 if it uses the same daily-gated function
**Severity:** Blocking  
**Scope:** US ↔ FR contradiction

- US-3 says admins can sync immediately after editing today's meal plan.
- FR-014 invokes the same `sync_meal_plan_to_shopping_lists` function.
- FR-010 makes that function abort after the household already synced today.

**Issue:** A run-now after an earlier scheduled sync would no-op, contradicting the manual refresh scenario.  
**Recommendation:** Define a `force`/manual mode that bypasses or deliberately reinterprets daily idempotency, and state marker behavior for manual runs.

### C-004 — Pantry filter is impossible as specified through `recipe_ingredients=None`
**Severity:** Blocking  
**Scope:** US ↔ FR ↔ SC contradictions; Edge cases vs FRs/ACs

- FR-011 calls `add_recipe_ingredients_to_list(... recipe_ingredients=None)` for each meal-plan recipe.
- FR-012 says the recipe-ingredient list passed to that method is pre-filtered to omit pantry staples.
- US-4/SC-004 require pantry staples to be absent from appended items.

**Issue:** Passing `None` delegates ingredient lookup to the existing helper, leaving no pre-filtered list to pass.  
**Recommendation:** Either build and pass explicit filtered `recipe_ingredients`, or introduce a helper seam that fetches, filters, then bulk-creates items.

### C-005 — `last_auto_synced_at` is both server-owned and client-patchable
**Severity:** Blocking  
**Scope:** US ↔ FR contradiction; needs_clarification vs FR/defaults

- FR-001/FR-003 add `last_auto_synced_at` to the preference schema.
- FR-005 exposes partial PATCH semantics for that schema.
- SC-001 requires PATCH/GET exact match for all five new fields.
- FR-010 relies on `last_auto_synced_at` for idempotency/CAS correctness.

**Issue:** Clients can clear or set the server marker, breaking the daily sync guarantee. NC-003 explicitly treats nullable fields, including this marker, as clearable by default.  
**Recommendation:** Remove `last_auto_synced_at` from client update schemas, or state that PUT/PATCH ignores it while read models expose it.

### C-006 — Configured target-list ownership is not guaranteed
**Severity:** High  
**Scope:** US ↔ FR ↔ SC contradictions

- US-6/SC-006 require household B's rows to remain unchanged after household A syncs.
- FR-011 writes to `auto_sync_target_shopping_list_id`.
- FR-017 asserts household-scoped repositories enforce isolation.
- FR-019 scopes only the null fallback list, not a configured ID.

**Issue:** The spec never requires PATCH or sync-time validation that a configured target list belongs to the current household.  
**Recommendation:** Add an explicit ownership check for configured IDs and include same-group wrong-household coverage in SC-006/FR-021.

### C-007 — i18n key names and localized outcomes drift
**Severity:** Medium  
**Scope:** AC-internal contradictions; FR ↔ SC

- Summary/US-9/SC-011 use `mealplan.auto_sync.*` / `mealplan_auto_sync` naming.
- FR-016 and edge cases use `mealplan.auto-sync.*` hyphenated keys.
- US-9 tests `no_active_meal_plan`; SC-007 tests `target_shopping_list_not_found`; deleted-target edge cases only log/skip.

**Issue:** Implementers cannot know the exact key path or which run-now failures must return localized responses.  
**Recommendation:** Pick one key convention and add SCs for all API-visible localized results.

### C-008 — Blocking NC-001 default conflicts with household-facing pantry language
**Severity:** Medium  
**Scope:** needs_clarification BlockingDecisions vs FRs/defaults; US ↔ FR

- NC-001 recommends the default group-scoped `IngredientFoodModel.is_pantry_staple` column.
- US-4/US-7 describe a household member marking foods for their own pantry.
- Out of scope says cross-household pantry-staple sharing semantics are escalated.

**Issue:** The recommended default creates cross-household sharing while the user story language implies household-local preference.  
**Recommendation:** Resolve NC-001 before coding, or rewrite US-4/US-7 to explicitly say pantry staples are group-scoped in this iteration.

### C-009 — FR ↔ SC bidirectional links differ in JSON and are absent in markdown
**Severity:** Low  
**Scope:** FR ↔ SC bidirectional; spec.md vs spec.json

- `spec.json` FR-020 lists SC-001, SC-002, SC-003, and SC-008, but those SCs do not list FR-020 back.
- `spec.md` FR entries list related user stories only; related success criteria exist only in JSON.

**Recommendation:** Either make FR-020 a test-coverage NFR referenced by the relevant SCs, or remove its SC links. Add equivalent FR↔SC links to markdown if field parity is required.

## Self-concerns vs FRs / ACs

- FR-008 self-concern is directionally aligned with SC-002, but it exposes that the latency SLA is not validated under load.
- FR-020 self-concern aligns with SC-008 but suggests FR-020's single-zone test set is insufficient for DST confidence.
- FR-010 self-concern weakens FR-010's claim that the CAS works on SQLite and PostgreSQL; add the proposed concurrency test if SC-003/SC-006 remain hard success criteria.

## Edge cases vs FRs / ACs

- No-meal-plan and missing/deleted-list edge cases conflict with FR-010's pre-work marker update (C-002).
- Note-only ingredient handling aligns with FR-012 only if C-004 is resolved by passing explicit filtered ingredients.
- Concurrent replicas align with FR-010 conceptually, but the self-concern says the SQLite concurrency premise has not been verified.
- Toggle-off mid-run is coherent, assuming the marker is server-owned (C-005).

## spec.md vs spec.json diff

| Field / section | Difference | Impact |
|---|---|---|
| Metadata | `spec.md` has title/status header; `spec.json` has `schema_version`, `metadata`, tool/LLM counts. | Expected representation difference. |
| Summary | Text is semantically the same, including the `mealplan.auto_sync.*` wording. | Same i18n drift exists in both. |
| Needs clarification | Same NC-001..NC-003 content, with JSON using `related_requirements` arrays. | No material mismatch. |
| User stories | Same US-1..US-9 content and acceptance scenarios. | No material mismatch found. |
| Functional requirements | Same FR-001..FR-022 prose. JSON additionally carries `related_success_criteria`, `requirement_type`, `testable`, and structured code references. | JSON has extra relationship fields; see C-009. |
| Success criteria | Same SC-001..SC-012 text/metrics/thresholds. JSON additionally carries `related_requirements`. | No prose mismatch; reciprocal links need cleanup. |
| Key entities / edge cases / assumptions / out of scope / self-concerns | Same semantics, JSON split into structured fields. | No behavioral mismatch found. |

## US ↔ FR.related_user_stories bidirectional check

No dangling user-story IDs were found, and every US is referenced by at least one FR. Semantic coverage issues remain for US-3 (manual run-now should relate to and override FR-010) and US-6 (configured target ownership is missing), captured in C-003 and C-006.

## FR ↔ SC bidirectional check

All SCs have at least one FR and all FRs have at least one SC in `spec.json`. The only reciprocal mismatch found is FR-020's links to SC-001/002/003/008 not being listed back by those SCs (C-009).

## Recommended resolution order

1. Fix marker threshold and CAS ordering (C-001/C-002).
2. Define manual run-now idempotency behavior (C-003).
3. Resolve pantry filtering implementation seam (C-004).
4. Make `last_auto_synced_at` server-owned (C-005).
5. Add target-list ownership validation and settle i18n key names.
