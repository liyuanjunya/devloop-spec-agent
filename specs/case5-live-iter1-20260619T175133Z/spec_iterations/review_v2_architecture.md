## Verdict
REJECT
v2 resolves most tenant-isolation and event-shape gaps, but the idempotency/CAS architecture is still unsafe because duplicate workers perform shopping-list side effects before the daily marker claim is won. It also introduces high-risk migration and PATCH-marker hazards that must be refined before implementation.

## V1 issue resolution table
| v1 ID | Status | Evidence (file:line OR FR id in v2) |
|---|---|---|
| ARCH-C-1 | PARTIALLY_RESOLVED | v2 moves marker writes after successful work and no-op paths in FR-011 (`spec_v2.md:192`) and FR-012 (`spec_v2.md:195`), but FR-012 now performs the CAS after side effects and explicitly accepts the loser already applied duplicate work (`spec_v2.md:195`, `spec_v2.md:325`). Existing `bulk_create_items` merges by adding quantity (`shopping_lists.py:95-97`) and repository methods commit internally (`repository_generic.py:202-203`, `repository_generic.py:223-225`), so the idempotency architecture is still unsafe. |
| ARCH-C-2 | RESOLVED | PATCH-time and sync-time target-list ownership checks are explicit in FR-006 and FR-014 (`spec_v2.md:177`, `spec_v2.md:201`), with a cross-household 422 criterion in SC-016 (`spec_v2.md:276`). |
| ARCH-C-3 | RESOLVED | v2 replaces the group-scoped food flag with `household_pantry_staples(household_id, food_id)` in FR-002 (`spec_v2.md:165`), uses it unconditionally in FR-016 (`spec_v2.md:207`), and adds multitenant regression coverage in FR-027 (`spec_v2.md:240`). |
| ARCH-H-1 | RESOLVED | Dedicated event type and payload are specified in FR-021 with `household_id`, `shopping_list_id`, `added_item_count`, `skipped_pantry_count`, and `operation` (`spec_v2.md:222`), with SC-013 coverage (`spec_v2.md:270`). |
| ARCH-H-2 | RESOLVED | `auto_sync_run_time` is added to model/schema in FR-001/FR-003 (`spec_v2.md:162`, `spec_v2.md:168`) and the household-local 30-minute window is specified in FR-009 (`spec_v2.md:186`). |
| ARCH-M-1 | PARTIALLY_RESOLVED | v2 adds an all-optional PATCH schema and `exclude_unset` diff in FR-004/FR-006 (`spec_v2.md:171`, `spec_v2.md:177`), but FR-006 still writes the loaded read object via `repository.update`, risking full-field writeback of the server marker rather than a diff-only patch (`spec_v2.md:177`; `repository_generic.py:220-225`). |

## NEW issues in v2 (with severity)

### NEW-ARCH-C-1 (CRITICAL): CAS happens after non-idempotent shopping-list side effects
FR-012 says both replicas may execute steps 1-5 and only then the loser observes a 0-row marker update (`spec_v2.md:195`), and the edge case explicitly accepts duplicate work/events (`spec_v2.md:325`). That is not safe: `bulk_create_items` merges by summing quantities (`shopping_lists.py:95-97`) and creates/updates through repository methods that commit immediately (`repository_generic.py:202-203`, `repository_generic.py:223-225`), so the losing worker can double quantities or emit duplicate external events before discovering it lost the daily claim. Use a separate claim/lease/status row or acquire the conditional daily claim before side effects while preserving the “completion marker only after success” invariant.

### NEW-ARCH-H-1 (HIGH): Event subscriber migration targets the wrong table and omits model/schema updates
FR-024 says to alter `group_event_notifier_options` (`spec_v2.md:231`), but the actual table is `group_events_notifier_options` (`events.py:15-16`). The spec also does not require adding the new boolean to `GroupEventNotifierOptionsModel` and the Pydantic options schema, where event fields are kept in sync with `EventTypes` (`group_events.py:13-17`); migration-only changes would leave ORM/schema access broken or invisible.

### NEW-ARCH-H-2 (HIGH): PATCH can write back or clobber `last_auto_synced_at`
FR-006 loads the current preferences object, mutates it, then calls `self.repos.household_preferences.update(self.household_id, current)` (`spec_v2.md:177`). Existing `update()` serializes the whole model and commits all fields (`repository_generic.py:220-225`), so using `ReadHouseholdPreferences` (which v2 adds `last_auto_synced_at` to in FR-005, `spec_v2.md:174`) can overwrite a concurrent scheduler marker with a stale value. The route should patch only the validated diff dict and explicitly exclude server-owned fields.

### NEW-ARCH-M-1 (MEDIUM): PATCH rejection criterion relies on nonexistent global `extra='forbid'`
SC-018 says an undeclared `last_auto_synced_at` field is rejected because `MealieModel` has `ConfigDict(extra='forbid')` (`spec_v2.md:280`), but MealieModel currently sets only alias/populate config (`mealie_model.py:45-54`). Add `extra='forbid'` on the new partial schema (not necessarily globally), or change the criterion to “ignored” if that is the intended API contract.

### NEW-ARCH-M-2 (MEDIUM): run-now response shape is internally inconsistent
FR-020 first mandates the exact four-key shape `{added_count, skipped_pantry_count, target_list_id, run_at}`, but then says precondition failures also include a `detail` field (`spec_v2.md:219`). SC-012 asserts the key set is exactly those four keys (`spec_v2.md:268`), so either failure responses need a separate schema/status or `detail` must be included consistently in the response contract and tests.

## Summary
- Resolved: 4/6 v1 issues
- New critical: 1 | New high: 2 | New medium: 2
- Overall: improved but still blocking
