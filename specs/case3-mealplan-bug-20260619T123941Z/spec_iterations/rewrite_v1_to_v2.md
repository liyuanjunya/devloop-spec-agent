# Rewrite v1 → v2 Summary

**Date**: 2026-06-19
**Spec**: `case3-mealplan-bug-20260619T123941Z`
**v1 spec_id**: `case3-mealplan-bug-20260619T123941Z/spec-v1`
**v2 spec_id**: `case3-mealplan-bug-20260619T123941Z/spec-v2`
**Iterations**: 1 → 2

---

## Issues addressed

Every CRITICAL and HIGH issue from the 4 v1 reviewer reports is addressed below.

### CRITICAL — Architecture (REJECT verdict, 2 issues)

| Issue ID | Severity | Reviewer | v2 Resolution (FR / section) |
|---|---|---|---|
| **ARCH-C-001** | CRITICAL | architecture | **Spec v2 §"Baseline reality and bug-injection precondition"** (new section above Problem statement). v2 acknowledges that `can_merge` lines 45-71 and `merge_items` lines 73-128 in the checked-out Mealie baseline (`C:\Users\v-liyuanjun\Downloads\mealie\`) are already correct (verified line-by-line). The DevLoop case 3 workflow now explicitly relies on the operator applying `input.md:88-128` 附录 Variant A or B on an `inject-bug` branch before the case-3 working branch is cut. The "1-2 line fix" therefore restores the canonical implementation against the injected variant — not a speculative repair of correct code. Also surfaces this as `self_concerns.SCN-4` and as `needs_clarification.NC-001` (variant choice). |
| **ARCH-C-002** | CRITICAL | architecture | **SC-1 reworded** (spec.md success-criteria table row SC-1; spec.json `success_criteria[0]`) to: "test exit status on the **bug-injected branch** (precondition per `input.md:88-128`)". The pre-fix expected outcome is now anchored to the injected variant, not the canonical baseline. Verification commands table row "Pre-fix" matches. |

### HIGH — Architecture (1 issue)

| Issue ID | Severity | Reviewer | v2 Resolution (FR / section) |
|---|---|---|---|
| **ARCH-H-001** | HIGH | architecture | **Problem statement §"Frontend payload shape"** (new subsection) documents the verified pipeline: `planner.vue:243-256` (`weekRecipesWithScales`, scale=1 per occurrence) → `RecipeDialogAddToShoppingList.vue:340-394` (`consolidateRecipesIntoSections` accumulates duplicates into one section with `recipeScale`, lines 345-349) → `:434-461` (sends ONE `ShoppingListAddRecipeParamsBulk(recipeIncrementQuantity=N)` per unique recipe, line 457) → `group-shopping-lists.ts:32-34` (POST). **US-4 `test_multiple_occurrences_same_unit`** is now parametrized over BOTH axes: `occurrences=[2, 3]` × `payload_form=["per_occurrence", "consolidated"]` — the `consolidated` form mirrors the real frontend dialog payload (one entry with `recipe_increment_quantity=N`); the `per_occurrence` form exercises the bug-injection target (N entries with `recipe_increment_quantity=1`). FR-4 cites both code paths: `get_shopping_list_items_from_recipe:370-385` (scaling, line 373) and `add_recipe_ingredients_to_list:437-452` (list-level ref accumulator, line 443). New **EC-8** documents the equivalence. US-1 (primary repro) keeps the per-occurrence form because that is what the input.md bug-injection patch directly affects. |

### HIGH — Executability (1 issue)

| Issue ID | Severity | Reviewer | v2 Resolution (FR / section) |
|---|---|---|---|
| **EXEC-H-001** | HIGH | executability | **US-1 AC step 1** (spec.md US-1 acceptance criterion 1; spec.json `user_stories[0].acceptance_criteria[1]`) now reads "creates `food_tomato` and **`food_salt`**" (was `food_egg`). Everywhere `food_salt` is used consistently with the recipe ingredient list (US-1 step 3), the per-food assertions (US-1 step 7), and the `unit_tsp` unit definition. Marked inline as "v2 fix for EXEC-H-001 / C-001". |

### HIGH — Consistency (2 issues)

| Issue ID | Severity | Reviewer | v2 Resolution (FR / section) |
|---|---|---|---|
| **C-001** | HIGH | consistency | Same physical edit as EXEC-H-001: `food_egg` → `food_salt`. See row above. |
| **C-002** | HIGH | consistency | **US-3 AC1 and FR-3 reworded** to: "The ONLY **production-code** file modified is `mealie/services/household_services/shopping_lists.py`. The new test file `tests/integration_tests/user_household_tests/test_meal_plan_to_shopping_bug.py` is a required addition under `tests/` and is NOT counted against this constraint." Mirror change in **SC-6** ("Files modified in production code … files under `tests/` are explicitly NOT counted against this metric"). spec.md and spec.json both updated identically. |

---

## Issues NOT addressed

None of the CRITICAL or HIGH issues were rejected. All 6 are resolved in v2.

The following MEDIUM and LOW issues from v1 reviewers were ALSO addressed (over and above the quality bar) because they were quick to fold in:

| Issue ID | Severity | Reviewer | v2 Resolution |
|---|---|---|---|
| **COMP-M-001** | MEDIUM | completeness | Same `food_egg` / `food_salt` fix as EXEC-H-001 / C-001. |
| **COMP-M-002** | MEDIUM | completeness | **New FR-7** "Implementation constraints" explicitly enumerates: (1) no toggle / config / feature-flag workaround, (2) no broad mechanical edit (grep+sed sweep), (3) no parallel implementation — keep existing `RepositoryShoppingItem` / `ShoppingListItem` schemas. Backed by **new SC-8** with concrete audit measurements. |
| **C-003** | MEDIUM | consistency | **SC-3 updated** to "**8 collected pytest cases pass** (1 repro + 1 single + 4 parametrized [2 occurrences × 2 payload_forms] + 1 different-units + 1 same-name)". Note that v2 actually has 8 (not 6 as the v1 reviewer projected) because of the additional `payload_form` parametrization added for ARCH-H-001. Verification command row "Post-fix" updated to expect "8 passed". Collection arithmetic explained in a footnote under the SC table. |
| **C-004** | MEDIUM | consistency | **US-3 final AC** now explicitly lists all three regression files: `test_group_shopping_lists.py`, `test_group_shopping_list_items.py`, and `test_group_mealplan.py` — matching the broader FR-5 / SC-4 scope. |
| **C-005** | MEDIUM | consistency | **NC-001** added to `needs_clarification` (Variant A vs B operator choice), since v2's bug-injection precondition introduces the only remaining genuine ambiguity. `food_egg`/`food_salt` and pytest count are no longer ambiguities (resolved by direct edits, not clarifications). |
| **EXEC-M-001** | MEDIUM | executability | **FR-4 code_references widened**: added `mealie/schema/household/group_shopping_list.py:58-67` (where `ShoppingListItemBase` declares `food_id`, `unit_id` — inherited by `ShoppingListItemOut`). **FR-6 code_references widened**: replaced `mealie/schema/household/group_shopping_list.py:250-285` with `:245-254` (covers `ShoppingListUpdate.list_items` at line 247 + `ShoppingListOut` at line 250), then kept `:250-285` for the loader_options block. Both files updated identically. |
| **EXEC-M-002** | MEDIUM | executability | **SC-5 / SC-6 / verification commands** now provide BOTH pre-commit (`git diff --shortstat -- <path>` and `git diff --name-only -- mealie/`) and post-commit (`HEAD~`) variants. |
| **EXEC-L-001** | LOW | executability | Acknowledged as intentional; FR-3 narrative makes explicit that the function set is selected by which Variant (A vs B) the operator injected (referenced via NC-001). No reword needed beyond the new bug-injection precondition section. |

---

## New issues introduced (honest list)

### NI-1 — v2 increases pytest case count from 5 to 8
**Severity**: low / informational
**Description**: The added `payload_form` parametrization in `test_multiple_occurrences_same_unit` (to resolve ARCH-H-001) doubles that test's collected cases from 2 to 4, bringing the total from v1's projected 6 collected cases (counted incorrectly in v1 SC-3 as "5/5") to v2's 8 collected cases. The named-test count is still 5. SC-3 and the Post-fix verification command both name "8 passed" with footnote arithmetic.
**Why this is acceptable**: The cost is one extra test invocation × 2 occurrences; each individual case still runs in well under a second per Mealie's pytest profile. The coverage gain (frontend-equivalent payload path) is essential to resolve ARCH-H-001 and so cannot be deferred.

### NI-2 — Bug-injection precondition adds operator burden
**Severity**: low / informational
**Description**: v2 makes explicit that the operator must apply `input.md:88-128` 附录 Variant A or B before DevLoop can satisfy SC-1. v1 silently assumed the bug was already present. This adds one explicit setup step to the case-3 workflow (cut `inject-bug` branch, apply patch, cut working branch from there), documented in spec.md §"Baseline reality and bug-injection precondition" and in spec.json `baseline_reality`.
**Why this is acceptable**: The honesty is necessary — v1 was unsatisfiable without this step (per ARCH-C-001 / ARCH-C-002). The alternative would be to pretend the baseline is buggy (false) or to silently assume one of the two variants (would not survive consistency review).

### NI-3 — Spec is now ~50% longer (more sections, FR-7 added, EC-8 added, SC-8 added, NC-001 added)
**Severity**: low / informational
**Description**: v2 spec.md grew from ~24KB to ~38KB (~58% longer); spec.json grew from ~24KB to ~36KB. Most of the growth is in the new "Baseline reality" section, the verbose FR-7 + SC-8 constraints, the EC-8 consolidated-form documentation, and the NC-001 variant-clarification stanza.
**Why this is acceptable**: The growth is proportional to the resolved issues (6 H/C + 8 M/L = 14 issues). No redundancy added; each new paragraph cites verified code or addresses a specific reviewer concern.

### NI-4 — FR-3 narrative cites lines 86-92, 98-104, 106-107, 109-126 by sub-region
**Severity**: low / informational
**Description**: v2 FR-3 explicitly enumerates which sub-blocks of `merge_items` are untouched (was: a single "lines 73-128"). This is more precise but creates more line-range claims that future reviewers / agents must verify.
**Why this is acceptable**: All four ranges were re-verified against the source file during v2 authoring (`mealie/services/household_services/shopping_lists.py` lines 86-92 = `merge_quantity_and_unit` branch; 98-104 = note concatenation; 106-107 = extras update; 109-126 = recipe-reference merge). The added precision tightens the diff-confinement contract.

---

## Code reference re-verification

All `code_references` in v2 spec.md and spec.json were re-verified by opening the cited file at the cited line range in `C:\Users\v-liyuanjun\Downloads\mealie\` during v2 authoring. Summary:

| Citation | File | Lines | Verified? |
|---|---|---|---|
| FR-1 route | `mealie/routes/households/controller_shopping_lists.py` | 256-261 | ✅ `@router.post("/{item_id}/recipe", response_model=ShoppingListOut)` |
| FR-1 route helper | `tests/utils/api_routes/__init__.py` | 415-417 | ✅ `households_shopping_lists_item_id_recipe` |
| FR-1 list helper | `tests/utils/api_routes/__init__.py` | 405-407 | ✅ `households_shopping_lists_item_id` |
| FR-1 mealplan const | `tests/utils/api_routes/__init__.py` | 92 | ✅ `households_mealplans = "/api/households/mealplans"` |
| FR-1 unique_user | `tests/fixtures/fixture_users.py` | 179-226 | ✅ `_unique_user` (179) + `@fixture unique_user` (225) |
| FR-1 shopping_list | `tests/fixtures/fixture_shopping_lists.py` | 49-65 | ✅ `@pytest.fixture shopping_list` |
| FR-1 api_client | `tests/conftest.py` | 37-54 | ✅ `override_get_db` (37) + `@fixture api_client` (45) |
| FR-2 can_merge | `mealie/services/household_services/shopping_lists.py` | 45-71 | ✅ exact function range |
| FR-2 merge_items | `mealie/services/household_services/shopping_lists.py` | 73-128 | ✅ exact function range |
| FR-2 recipe_scale block | `mealie/services/household_services/shopping_lists.py` | 109-126 | ✅ recipe-reference accumulator |
| FR-2 input附录 | `input.md` | 88-138 | ✅ widened from 103-128 to cover the operator workflow narrative too |
| FR-3 bulk_create_items | `mealie/services/household_services/shopping_lists.py` | 154-223 | ✅ exact function range |
| FR-3 add_recipe_ingredients | `mealie/services/household_services/shopping_lists.py` | 413-455 | ✅ exact function range |
| FR-4 ItemBase food_id/unit_id | `mealie/schema/household/group_shopping_list.py` | 58-67 | ✅ NEW v2 — fields at 65, 67 (was missing in v1) |
| FR-4 ItemOut food/unit | `mealie/schema/household/group_shopping_list.py` | 106-120 | ✅ class at 106, food at 111, unit at 113 |
| FR-4 RecipeRefCreate | `mealie/schema/household/group_shopping_list.py` | 32-46 | ✅ class at 32, recipe_scale at 37 |
| FR-4 pattern test | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` | 663-739 | ✅ `test_shopping_lists_add_recipes_with_merge` |
| FR-4 scaling path (new) | `mealie/services/household_services/shopping_lists.py` | 370-385 | ✅ `ShoppingListItemCreate(...)` with `quantity = ingredient.quantity * scale` at line 373 |
| FR-4 list-level ref accumulator (new) | `mealie/services/household_services/shopping_lists.py` | 437-452 | ✅ `ref.recipe_quantity += recipe.recipe_increment_quantity` at line 443 |
| FR-5 add_recipe_with_merge | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` | 581-660 | ✅ exact test range |
| FR-5 add_recipes_with_merge | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` | 663-739 | ✅ exact test range |
| FR-5 add_nested_recipe | `tests/integration_tests/user_household_tests/test_group_shopping_lists.py` | 249-361 | ✅ exact test range |
| FR-5 standard-unit tests | `tests/integration_tests/user_household_tests/test_group_shopping_list_items.py` | 644-731 | ✅ three relevant tests in range |
| FR-6 assert_deserialize | `tests/utils/assertion_helpers.py` | 23-25 | ✅ exact helper |
| FR-6 jsonify | `tests/utils/jsonify.py` | 1-5 | ✅ exact module |
| FR-6 py:test | `Taskfile.yml` | 107-110 | ✅ `py:test` task |
| FR-6 py:check | `Taskfile.yml` | 122-128 | ✅ `py:check` task with deps `py:format py:lint py:mypy py:test` |
| FR-6 ShoppingListUpdate.list_items | `mealie/schema/household/group_shopping_list.py` | 245-254 | ✅ NEW v2 — `list_items` at 247 (was missing in v1) |
| FR-6 ShoppingListOut loader | `mealie/schema/household/group_shopping_list.py` | 250-285 | ✅ class at 250, loader_options through 285 |
| FR-7 create_many/update_many (new) | `mealie/services/household_services/shopping_lists.py` | 215-216 | ✅ persistence calls |
| FR-7 ShoppingListItem model (new) | `mealie/db/models/household/shopping_list.py` | 51-98 | ✅ model class range |
| FR-7 ItemBase/Create/Update/Out (new) | `mealie/schema/household/group_shopping_list.py` | 58-120 | ✅ all four classes |
| FR-7 input.md constraint origin (new) | `input.md` | 55-59 | ✅ "实现约束" section in original input |

All 33 citations re-verified. Two citations were widened for inheritance accuracy (FR-4 `:58-67` added; FR-6 `:245-254` added) per EXEC-M-001.

---

## Forbidden-phrase scan

v2 spec.md and spec.json scanned for `TBD`, `placeholder`, `or equivalent`, `if needed`, `TODO`, `FIXME`:

- `TBD`: 0 matches ✅
- `placeholder`: 0 matches ✅
- `or equivalent`: 0 matches ✅
- `if needed`: 0 matches ✅
- `TODO`: 0 matches ✅
- `FIXME`: 0 matches ✅

(One legitimate `if` appears in `quantity = ingredient.quantity * scale if ingredient.quantity else 0` which is a quoted code expression from `mealie/services/household_services/shopping_lists.py:373`, not a placeholder.)

---

## Metadata changes

| Field | v1 | v2 |
|---|---|---|
| `spec_id` | `…/spec-v1` | `…/spec-v2` |
| `iterations` | absent (implicit 1) | `2` |
| `baseline_reality` | absent | new field documenting precondition |
| `user_stories.count` | 4 | 4 (unchanged) |
| `functional_requirements.count` | 6 (FR-1..FR-6) | 7 (FR-7 added) |
| `success_criteria.count` | 7 (SC-1..SC-7) | 8 (SC-8 added) |
| `edge_cases.count` | 7 (EC-1..EC-7) | 8 (EC-8 added) |
| `self_concerns.count` | 3 (SCN-1..SCN-3) | 4 (SCN-4 added) |
| `out_of_scope.count` | 8 | 9 (added: do not modify operator's bug-injection patch) |
| `verification_commands.count` | 5 | 8 (added pre-commit variants + FR-7 audit) |
| `needs_clarification.count` | 0 (None) | 1 (NC-001 variant choice) |

---

## Quality bar check

| Criterion | Met? |
|---|---|
| All 2 CRITICAL issues resolved | ✅ ARCH-C-001 + ARCH-C-002 both resolved (not rejected) |
| At least 1 of 1 HIGH issues resolved | ✅ All 4 HIGH issues (ARCH-H-001, EXEC-H-001, C-001, C-002) resolved |
| spec.md and spec.json derived from same content | ✅ Both authored in parallel; each FR / SC / EC / SCN / NC has matching paragraphs in both files; counts match per JSON validation above |
| All citations VERIFIED by opening file | ✅ 33 citations re-verified in this rewrite; table above |
| No new contradictions | ✅ Internal scan: `food_salt` used consistently throughout; "production code" qualifier used consistently in SC-6 / US-3 AC / FR-3; pytest case count "8" used consistently in SC-3 + verification commands |
| Removed "or equivalent" / "TBD" / "if needed" | ✅ Zero matches in forbidden-phrase scan |
| metadata.iterations = 2 | ✅ `spec.json.iterations = 2`; `spec.md` Metadata section lists "Iterations: 2" |
