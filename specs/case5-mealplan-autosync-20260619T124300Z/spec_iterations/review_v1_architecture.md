# Architecture Review v1 — Case 5 Meal Plan Auto-Sync to Shopping List

## Verdict: REQUEST_CHANGES

**Decision rule:** APPROVE only with 0 Critical + 0 High. This review has **1 Critical, 0 High, 1 Medium**.

Review target: `C:\Users\v-liyuanjun\Downloads\mealie` on branch `devloop-baseline`. The case-5 implementation is not present in this checkout; the only uncommitted code changes are unrelated dependency edits in `pyproject.toml` and `uv.lock`.

## Findings

### C1 — Case-5 implementation is absent from the Mealie checkout
- **Severity:** Critical
- **Spec refs:** `spec.md:17-58`, `spec.md:77-83`; `spec.json` FR-1 through FR-20+.
- **Code refs / evidence:**
  - `git diff --name-only` shows only `pyproject.toml` and `uv.lock`; neither is part of this feature.
  - `mealie/services/scheduler/tasks/auto_sync_shopping.py` does not exist.
  - `mealie/services/scheduler/tasks/__init__.py:1-19` exports only existing tasks; no auto-sync task.
  - `mealie/app.py:134-136` registers only `tasks.post_group_webhooks` in the existing minutely scheduler bucket.
  - `mealie/db/models/household/preferences.py:16-44` has no auto-sync enable/target/run-time/last-synced/timezone fields.
  - `mealie/schema/household/household_preferences.py:10-41` has no matching API schema fields or validators.
  - `mealie/db/models/recipe/ingredient.py:153-192` and `mealie/schema/recipe/recipe_ingredient.py:92-115` have no `is_pantry_staple` field.
  - `mealie/routes/households/controller_household_self_service.py:54-62` has only GET/PUT preferences; no `POST /api/households/preferences/auto-sync-shopping/run-now`.
  - `mealie/services/event_bus_service/event_types.py:13-62` has no `meal_plan_auto_synced_to_shopping` event type or payload model.
- **Issue:** None of the required controller/service/repository, scheduler, persistence, event, pantry-staple, manual-trigger, idempotency, timezone, or multitenant behavior exists in the reviewed code. There is therefore no architecture seam to approve.
- **Required fix:** Implement the feature in the Mealie repo (or switch this review to the branch containing it) and rerun architecture review after the code is present.

### M1 — Current worktree contains unrelated dependency changes
- **Severity:** Medium
- **Code refs:** `pyproject.toml`, `uv.lock`.
- **Issue:** The only uncommitted changes remove/comment `python-ldap`, unrelated to meal-plan auto-sync. This can obscure review signal and should not be shipped with case-5 unless intentionally justified.
- **Recommended fix:** Revert or separate these dependency edits before submitting the case-5 implementation.

## Scope checklist

- 3-layer controller/service/repo adherence: **Fail / not implemented**.
- Scheduler integration: **Fail / not registered**. Existing Mealie scheduler uses `SchedulerRegistry.register_*` plus `repeat_every` (`scheduler_service.py:63-81`), not a discovered `@scheduled` decorator; no case-5 task is registered.
- Per-household timezone + `LastAutoSyncedAt` idempotency storage seam: **Fail / fields absent**.
- Consolidation function reuse from case-3: **Not implemented**, but the correct seam exists at `ShoppingListService.add_recipe_ingredients_to_list` and `bulk_create_items` (`shopping_lists.py:154-223`, `323-455`).
- Event bus dispatch payload with no cross-household leak: **Fail / event absent**.
- `HouseholdPreferences` + Food schema/migration patterns: **Fail / model and schema fields absent; migrations absent**.
- Multitenant scoping in scheduled task: **Fail / task absent**.
- Manual trigger admin-only permission check: **Fail / endpoint absent**.

## Summary

- Critical: 1
- High: 0
- Medium: 1
- Low: 0

**Approval gate:** Not approved. The implementation must be present and all Critical findings resolved before approval is possible.
