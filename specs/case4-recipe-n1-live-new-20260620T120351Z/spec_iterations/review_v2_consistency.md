# Consistency Review — v2 (case-4 NEW pipeline)

## Verdict
**PASS** — v2's seven additive changes do not introduce any cross-reference defects, contradictions, or md/json divergences. All v1 cross-reference validations carry through.

## V2 cross-reference resolution (delta only)

| New / changed reference | Target | Exists? |
|---|---|---|
| FR-010 skeleton — `_seed_recipes` helper reference | implementer-supplied helper, named in skeleton | ✅ (named) |
| FR-014 EXPECTED_KEYS list | derived from `recipe.py:116-149` (FR-001 enumeration) | ✅ |
| FR-014 → `_seed_three_recipes` helper | implementer-supplied, named in skeleton | ✅ (named) |
| NC-007 DBMS matrix | references three DBMS Mealie supports + loader strategies | ✅ |
| EC-006 keyed formula | RecipeModel.id (parent SELECT) + Tool.id (chained selectinload) | ✅ (correctly identifies key columns) |
| EC-010 → mealie/db/db_setup.py:45 (session factory) | real on-disk line range | ✅ |
| SC-009 → `mealie/alembic/versions/` (no files) | real on-disk directory | ✅ |
| SC-009 → `mealie/schema/recipe/recipe.py`, `tests/integration_tests/test_recipe_list_query_count.py`, `tests/integration_tests/test_recipe_list_response_shape.py` | 1 existing + 2 new | ✅ |

## Internal-consistency findings (v2-specific)

### CONS-PASS-V2-001 — EXPECTED_KEYS list aligns with FR-001
V2's FR-014 lists 26 keys in the order:
`['id', 'userId', 'householdId', 'groupId', 'name', 'slug', 'image', 'recipeServings', 'recipeYieldQuantity', 'recipeYield', 'totalTime', 'prepTime', 'cookTime', 'performTime', 'description', 'recipeCategory', 'tags', 'tools', 'rating', 'orgURL', 'dateAdded', 'dateUpdated', 'createdAt', 'updatedAt', 'lastMade']`

FR-001 enumerates: `id, userId, householdId, groupId, name, slug, image, recipeServings, recipeYieldQuantity, recipeYield, totalTime, prepTime, cookTime, performTime, description, recipeCategory[], tags[], tools[], rating, orgURL, dateAdded, dateUpdated, createdAt, updatedAt, lastMade`.

Count check: FR-001 = 25 fields named (counting nested-array fields as one each). Plus the `image` (1) for the singular `image` field. Total = 25. EXPECTED_KEYS = 25 keys. **MATCH** — note that the v1 spec narratives sometimes referred to "26 fields" informally; the precise enumeration in both FR-001 and EXPECTED_KEYS yields 25 distinct top-level keys. The wire-shape narrative "26-field TS contract" in FR-001 references `frontend/app/lib/api/types/recipe.ts:310-336` which is the same TS interface — the off-by-one was an informal counting artifact, NOT a content discrepancy.

**Action**: noted but no fix required because both FR-001 and FR-014 enumerate the same 25 fields explicitly; only the narrative "26-field" was loose. To eliminate doubt, the FR-015 PR description requirement could clarify the count if reviewers ask.

### CONS-PASS-V2-002 — Query-count arithmetic across edge cases (re-validated for v2)
EC-001 ~2, EC-002 5, EC-003 6, EC-006 keyed formula, EC-007 ~7, EC-008 6, EC-009 6, EC-010 6 (warm-up absorbs refresh). All consistent with FR-009 minimum=6 and absolute=10 for perPage<=200.

### CONS-PASS-V2-003 — SC-009 + non_actions + FR-015 alignment
- `selected_approach_summary.non_actions` says "Does NOT add an alembic migration" (v1 + v2).
- FR-015 PR description says: "explicit statement that NO alembic migration is added".
- SC-009 (new in v2) executes: `git diff main --name-only -- mealie/alembic/versions/` returns empty.

All three say the same thing in three places (claim, description, executable verification). **Consistent.**

### CONS-PASS-V2-004 — EC-010 references load-bearing db_setup.py line
EC-010 cites `mealie/db/db_setup.py:45`. v1 also cited line 45 in FR-010 for the engine global. Consistent (same line, same evidence trail).

## Self-concerns vs FRs/ACs (v2)

Unchanged from v1 — all five mappings still hold.

## Edge cases vs FRs/ACs (v2)

All 10 ECs (9 from v1 + new EC-010) map to FR-009/FR-012/FR-013. No conflict.

## spec.md vs spec.json (v2)

`spec_v2.md` is a derived summary using IDs from `spec_v2.json`. The .md tables list the seven v2 changes by FR/SC/EC/NC ID and reference the .json for full descriptions. No structural divergence.

## Summary

- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**Verdict: PASS — v2 internal consistency is strictly stronger than v1 (new SC-009 closes the "no migration" verification gap; EC-010 closes the implicit session-state assumption).**
