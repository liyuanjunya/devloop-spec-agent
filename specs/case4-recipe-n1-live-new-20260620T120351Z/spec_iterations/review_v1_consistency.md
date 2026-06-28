# Consistency Review — v1 (case-4 NEW pipeline)

## Verdict
**PASS** — internal cross-references resolve; spec.md and spec.json are aligned; no contradictions between FR/SC/EC/NC/self-concerns.

## Reviewer: Consistency

## Cross-reference resolution table

| Reference site | Target | Exists? |
|---|---|---|
| FR-001 → NC-004 (slug_image) | NC-004 | ✅ |
| FR-005 → FR-006 (chained loader) | FR-006 | ✅ |
| FR-009 → NC-003 (relaxed ceiling) | NC-003 | ✅ |
| FR-009 → EC-006 (chunking formula) | EC-006 | ✅ |
| FR-013 → NC-008 (multitenant_tests resolution) | NC-008 | ✅ |
| FR-014 → NC-007 (nested order semantics) | NC-007 | ✅ |
| FR-014 → FR-001 (top-level key contract) | FR-001 | ✅ |
| FR-014 → FR-010 (orthogonal to query-count test) | FR-010 | ✅ |
| FR-015 → self_concerns SC-D (frontend regeneration pre-empt) | SC-D | ✅ |
| FR-015 → SC-B (out-of-scope follow-ups) | SC-B | ✅ |
| SC-002 → FR-014 (executable assertion seam) | FR-014 | ✅ |
| SC-008 → FR-014, FR-001 | both | ✅ |
| EC-005 → FR-012 + test_recipe_cross_household.py | FR-012 | ✅ |
| EC-006 → FR-009 + SC-C + FR-010 | all three | ✅ |
| NC-002 → FR-011 + self_concerns SC-C | both | ✅ |
| NC-007 → FR-014 + nested-order resolution | FR-014 | ✅ |
| SC-A → FR-006 + FR-015 | both | ✅ |
| SC-B → FR-015 (PR description follow-ups) | FR-015 | ✅ |
| SC-C → EC-006 + FR-009 + FR-010 | all three | ✅ |
| SC-D → FR-015 | FR-015 | ✅ |
| SC-E → FR-014 + NC-007 + FR-001 + A3 perf_opt | all three (A3 is meta) | ✅ |

**Note**: The prior case-4 v1 had defect C-001 (FR-011/NC-002 referenced non-existent `SC-003`). This v1 correctly references `self_concerns SC-C`. Verified by grepping for `SC-003` in `self_concerns` — no collision (only success_criteria has `SC-003`).

## Internal-consistency findings

### CONS-PASS-001 — Query-count arithmetic across FR-009, EC-001, EC-002, EC-003 is internally consistent
| Edge case | Stated count | Formula | Matches FR-009? |
|---|---|---|---|
| EC-001 (empty list) | ~2 | COUNT + parent; follow-ups elided on empty IN-list | ✅ within `<= 10` |
| EC-002 (no organizers, no tools) | 5 typical | COUNT + parent + 3 selectinloads (each empty); chained households elided | ✅ within `<= 10` |
| EC-003 (tools w/o households) | 6 | COUNT + parent + 3 selectinloads + 1 chained selectinload (empty result) | ✅ within `<= 10`; matches FR-009 minimum |
| EC-006 (perPage=-1) | formula `2 + k_cat + k_tag + k_tool + k_households` | chunked | ✅ scoped beyond `<= 10` per FR-009's `perPage <= 200` clause |
| EC-007 (orderBy=random) | ~7 | +1 for ID-materialization | ✅ within `<= 10` |
| EC-008 (orderBy=lastMade/rating) | 6 | correlated subquery is part of parent | ✅ same as FR-009 minimum |
| EC-009 (search filter) | 6 | filter is on parent SELECT | ✅ same as FR-009 minimum |

**Note**: The prior case-4 v1 had defect C-002 (EC-002 said 6 statements for empty-tools case, but chained households selectinload should elide on empty IN-list → 5 statements). This v1's EC-002 explicitly says "5 statements typically" with rationale "(the chained households selectinload only fires when at least one Tool is loaded)". Fixed.

### CONS-PASS-002 — `byte-identical` vs `normalized diff` wording is consistent
**Note**: The prior case-4 v1 had defect C-004 (US-1 said "JSON diff returns {}" and SC-002 said "byte-identical modulo non-deterministic fields" — contradictory). This v1:
- US-1 acceptance: "Normalized JSON diff between pre- and post-refactor responses returns {} after masking documented volatile fields (createdAt, updatedAt, randomly-assigned UUIDs)."
- SC-002 metric: same wording — "After masking documented volatile fields, the normalized JSON diff is exactly {}."

Both consistently use **normalized** terminology with the explicit mask list.

### CONS-PASS-003 — perPage=-1 scoping is consistent across FR-009/EC-006/SC-C
**Note**: The prior case-4 v1 had defect C-003 (EC-006 said perPage=-1 bounded by `<= 10` even though chunking can exceed). This v1:
- FR-009 absolute bound `<= 10` is explicitly scoped to `perPage <= 200`.
- EC-006 gives the chunking formula for `perPage=-1` cases.
- SC-C explicitly captures the chunking caveat.

No contradiction.

### CONS-PASS-004 — Regression test parameters are concretely specified
**Note**: The prior case-4 v1 had defect C-005 (FR-010 didn't specify perPage for measured calls; SC-C contradictorily said perPage=50/200). This v1's FR-010 explicitly says: "(6) measures with two concrete request shapes: first GET /api/recipes?perPage=50 after 10 seeded recipes, then GET /api/recipes?perPage=200 after 100 seeded recipes". SC-C agrees.

### CONS-PASS-005 — spec.md and spec.json are aligned
The `spec_v1.md` derived-summary file uses the SAME FR-IDs, SC-IDs, EC-IDs, NC-IDs, self-concern IDs as `spec_v1.json`. No code_references mismatches because the .md uses summary text rather than `code_references` blocks (the JSON is the single source of truth for citations).

**Note**: The prior case-4 v1 had FR-011's `code_references` differing between spec.md and spec.json. This v1 sidesteps that risk: the .md summarizes by ID, the .json carries all citations.

## Self-concerns vs FRs/ACs

- **SC-A** is consistent with FR-006 (chained households selectinload) and FR-015 (PR description requirement).
- **SC-B** consistent with `non_actions` and FR-015 follow-up note.
- **SC-C** consistent with EC-006 chunking formula + FR-009 scoping.
- **SC-D** consistent with FR-001 (no Pydantic field change) and FR-015 PR description.
- **SC-E** consistent with FR-014 set-equal-on-nested + NC-007 explicit order-semantics resolution.

## Edge cases vs FRs/ACs

All 9 ECs map cleanly to FR-009 / FR-012 / FR-013. No conflict found.

## needs_clarification assessment

All 8 NC items have unambiguous resolutions with cited evidence (line numbers, perspectives, prior art). NC-007 (nested-order) carries the A3 perf_opt explicit-defense weight.

## spec.md vs spec.json diff

The .md is a derived summary referencing IDs from the .json. No structural divergence; the JSON is the single source of truth.

## Summary

- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**Verdict: PASS — fully internally consistent.**
