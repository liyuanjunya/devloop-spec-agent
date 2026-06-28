# Executability Review (v2)

## Verdict: NEEDS_REFINE

Spec v2 is materially more executable than v1: the flawed `mp.recipe.recipe_ingredient` seam is fixed by an explicit full-recipe re-fetch, `last_auto_synced_at` is server-only, the target-list fallback is now concrete, `added_count` semantics are pinned, and migration ordering is specified. However, under the requested **strict line-range verification**, v2 still fails because five explicit `code_references` omit line ranges. There is also one small identifier typo in FR-20 that a coding agent would likely infer, but should be corrected.

---

## Scope checks

| Check | Result |
|---|---|
| All cited Mealie paths real? | ✅ Pass. Every cited existing path under `C:\Users\v-liyuanjun\Downloads\mealie\` exists. |
| All explicit line ranges in bounds? | ✅ Pass. Every `path:start-end` range in `spec_v2.json` is within the current file length. |
| Every `code_reference` has a strict line range? | ❌ Fail. Five references are file-only. See below. |
| `spec_v2.md` / `spec_v2.json` `code_references` identical per FR? | ✅ Pass. Ordered lists match for all 28 FRs. |
| V1 critical scheduler/pantry seam resolved? | ✅ Pass. FR-17 now cites `ReadPlanEntry.recipe: RecipeSummary`, `RecipeSummary`, full `Recipe.recipe_ingredient`, and the existing shopping-list service seam. |
| TBD / `or equivalent` / `if needed` phrases? | ✅ Pass for those exact ambiguity phrases. |

---

## Strict line-range failures

These references are present in both markdown and JSON without `:line` or `:start-end`:

1. **FR-1** — `mealie/db/models/_model_base.py` has no line range. Suggested split refs: `mealie/db/models/_model_base.py:8-9`, `mealie/db/models/_model_base.py:18-23`, `mealie/db/models/_model_base.py:36-48`.
2. **FR-9** — `mealie/schema/household/household_preferences.py` has no line range. Suggested range: `mealie/schema/household/household_preferences.py:10-40`.
3. **FR-9** — `mealie/schema/_mealie/mealie_model.py` has no line range. Suggested range for `MealieModel`: `mealie/schema/_mealie/mealie_model.py:45-53` (or `45-90` if datetime behavior is intended context).
4. **FR-22** — `mealie/schema/response/pagination.py` has no line range. Suggested range: `mealie/schema/response/pagination.py:12-49`.
5. **FR-25** — `.github/copilot-instructions.md` has no line range. Suggested range for the en-US/Crowdin rule: `.github/copilot-instructions.md:202-204` or `.github/copilot-instructions.md:217-224`.

---

## Remaining executability concerns

### High

- **EXEC-H-001 — Strict line-range contract is still not met.** The spec explicitly says line ranges are verified, but the five references above are file-only. This is enough to fail the requested strict verification even though the paths exist.

### Low

- **EXEC-L-001 — FR-20 uses `skipped_pantry` once, but the result field/counter is `skipped_pantry_count`.** The affected text is in spec v2 line 74 / JSON FR-20 step 8: `added_count + skipped_pantry > 0`. Rename to `skipped_pantry_count` to avoid a coding-agent fork.

---

## Verified v1 fixes

- Full-recipe loading is now concrete: `repository_meals.py:11-22`, `new_meal.py:62-65`, `recipe.py:116-183`, and `shopping_lists.py:323-455` support FR-17.
- Default target list is now the oldest household-scoped list, supported by `repository_factory.py:317-321` and `repository_generic.py:94-102`.
- `last_auto_synced_at` is no longer accepted by `UpdateHouseholdPreferences`; FR-7/FR-10/SCN-3 are consistent.
- Migration chain is concrete and current head `2187537c52b8` was verified as the only Alembic head.
