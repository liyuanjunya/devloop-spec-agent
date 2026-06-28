# Architecture Review v2 — Case 5 Meal Plan Auto-Sync to Shopping List

## Verdict: REQUEST_CHANGES

**Decision rule:** APPROVE only with 0 Critical + 0 High. This review has **0 Critical, 3 High, 0 Medium, 0 Low**.

Review target:
- Spec v2: `spec_iterations/spec_v2.md` + `spec_v2.json`
- Rewrite trace: `spec_iterations/rewrite_v1_to_v2.md`
- Mealie reference checkout: `C:\Users\v-liyuanjun\Downloads\mealie`

## v1 issue disposition

| v1 issue | v2 disposition | Rationale |
|---|---|---|
| C1 — Case-5 implementation is absent from the Mealie checkout | **FALSE_POSITIVE_V1** | Acknowledged: this was a spec review gate for a **new feature**, not an implementation review. Requiring the feature code to already exist was the wrong mental model. Do not carry this forward. |
| M1 — Current worktree contains unrelated dependency changes | **FALSE_POSITIVE_V1** | This was unrelated local worktree state, not a spec architecture defect. Do not carry this forward. |

## Findings

### H1 — Scheduler CAS marker is committed before the sync work, so failures can suppress retries for the rest of the day

- **Severity:** High
- **Spec refs:** `spec_v2.md:73-75`, `spec_v2.md:121-133`, `spec_v2.md:139-145`
- **Code refs / evidence:**
  - `spec_v2.md:74` requires scheduler step 6 to run `UPDATE household_preferences SET last_auto_synced_at = :now ...` and `session.commit()` immediately, before step 8 performs shopping-list writes and event dispatch.
  - `mealie/repos/repository_generic.py:195-203` shows `create_many()` commits during list-item creation; `repository_generic.py:228+` / `update_many()` similarly participates in repository-managed commits.
  - `mealie/services/household_services/shopping_lists.py:426-455` performs item creation/update and then list-level recipe-reference update after the CAS marker would already be committed.
- **Issue:** The spec claims exception paths do not update `last_auto_synced_at`, but the scheduler path has already committed the marker before the actual sync. If `add_recipe_ingredients_to_list`, list-reference update, or event dispatch fails after the CAS commit, the household is marked synced and future scheduler ticks skip until the next household-local day even though the shopping list may not have been updated. This violates the once-per-day idempotency guarantee by turning a failed run into a durable success marker.
- **Required fix:** Make marker durability align with successful sync durability. Acceptable designs include: keep the CAS update and sync work in one transaction that rolls back together on failure; introduce a separate claim/in-progress field and only set `last_auto_synced_at` after successful work; or explicitly document and test a retry-safe finalization flow. Update EC/matrix wording to cover scheduler exceptions, not only manual-trigger exceptions.

### H2 — Persisted target-list IDs are not revalidated in the scheduler helper before writing list items

- **Severity:** High
- **Spec refs:** `spec_v2.md:59-60`, `spec_v2.md:74`, `spec_v2.md:81`, `spec_v2.md:167-174`
- **Code refs / evidence:**
  - `spec_v2.md:59` validates `auto_sync_target_shopping_list_id` only in the `PUT /preferences` route.
  - `spec_v2.md:81` defines household-scoped fallback only when the preference value is `None`; it does not require the helper to verify a non-null configured ID against the current household.
  - `mealie/repos/repository_generic.py:156-174` shows `get_one()` can enforce household scope when used, but the spec does not require using it for configured IDs during scheduler execution.
  - `mealie/db/models/household/shopping_list.py:51-60` shows `ShoppingListItem` stores `shopping_list_id`; `group_id`/`household_id` are association proxies, not independent columns preventing a bad cross-household FK at insert time.
  - `mealie/repos/repository_generic.py:195-203` shows `create_many()` constructs models from supplied data and commits; it does not validate that the referenced shopping list belongs to the repository household.
- **Issue:** The privileged scheduler must not trust persisted configuration. A stale/corrupt/imported `auto_sync_target_shopping_list_id` could point at another household's shopping list. Because shopping-list item creation is keyed by `shopping_list_id`, a cross-household target can become a cross-tenant write unless the helper revalidates the configured target with the household-scoped `repos.group_shopping_lists.get_one(target_list_id)` before passing it to `ShoppingListService`.
- **Required fix:** In `_sync_one_household`/service target resolution, always resolve **both** configured and fallback target IDs through the household-scoped shopping-list repository. If the configured ID is absent under that household, treat it like EC-2 (or clear/fallback per an explicitly documented policy) and do not write `last_auto_synced_at`.

### H3 — Core auto-sync business logic is specified inside a scheduler task and called directly by the controller

- **Severity:** High
- **Spec refs:** `spec_v2.md:60`, `spec_v2.md:67`, `spec_v2.md:172-174`
- **Code refs / evidence:**
  - `spec_v2.md:60` requires the run-now route to call `_sync_one_household(...)` from the scheduler task module.
  - `spec_v2.md:67` places `_sync_one_household` in `mealie/services/scheduler/tasks/auto_sync_shopping.py`.
  - `spec_v2.md:172-174` repeats the Mealie architectural constraint that routes follow Repository-Service-Controller and delegate business logic to services.
  - `mealie/routes/households/controller_household_self_service.py:21-23` shows the existing controller pattern: expose a domain service via `self.service`.
  - `mealie/services/scheduler/tasks/delete_old_checked_shopping_list_items.py:54-75` is a scheduler task precedent, but it is not a controller-facing service API.
- **Issue:** The spec creates a controller → scheduler-task dependency and puts the reusable domain operation in an internal task module. That contradicts the stated repository-service-controller constraint and makes the manual endpoint depend on scheduler plumbing instead of a stable service abstraction.
- **Required fix:** Move the reusable sync operation into a domain service, e.g. `MealPlanAutoSyncService` under `mealie/services/household_services/` or another appropriate service package. The scheduler task should only handle session/group/household iteration and call the service; the run-now route should call the same service through the controller service layer.

## Scope checklist

- 3-layer controller/service/repo adherence: **Fail** — H3.
- Scheduler integration: **Mostly specified**, but retry/transaction semantics fail — H1.
- Per-household timezone + `last_auto_synced_at` idempotency seam: **Needs changes** — H1.
- Consolidation reuse: **Pass** — FR-17 correctly uses `ShoppingListService.add_recipe_ingredients_to_list` / `bulk_create_items`.
- Event bus dispatch payload with no cross-household fan-out: **Pass** for explicit `household_id`; durability still affected by H1.
- HouseholdPreferences + Food schema/migration patterns: **Pass at spec level**.
- Multitenant scoping in scheduled task: **Needs changes** — H2.
- Manual trigger permission check: **Pass at spec level**.

## Summary

Spec v2 correctly rejects the v1 implementation-absence false positive and fixes several genuine v1 spec problems. However, it still has three blocking architectural issues: the CAS marker can be committed before failed sync work, scheduler target IDs are not defensively revalidated under household scope, and the route is coupled directly to scheduler-task internals instead of a domain service.

**Approval gate:** Not approved until all High findings are resolved.
