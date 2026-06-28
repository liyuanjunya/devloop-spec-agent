# Consistency Review v2 — Case 4 Recipe List N+1 Performance Refactor

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION

## Summary

v2 resolves the v1 consistency blockers around the explore-endpoint self-concern reference, EC-002 empty-tools arithmetic, perPage=-1 fixed ceilings, and response-normalization wording. Remaining issues are narrower: the spec still states an unqualified “minimum is 6” despite edge cases with 2 or 5 statements, the SC-C/EC-006 “worst-case” examples undercount high distinct-tool cardinality, and one benchmark criterion mixes 50- and 100-recipe cases. There is also one material `spec.md` vs `spec.json` omission in FR-014.

## Findings

### C2-001 — Unqualified “minimum is 6” contradicts EC-001/EC-002

- **Severity**: Medium
- **Scope**: FR-009 / NC-003 ↔ edge cases
- **Locations**:
  - `spec_v2.md`: FR-009 says “post-refactor minimum is 6” and NC-003 says the minimum is “provably 6”.
  - `spec_v2.json`: same wording in `functional_requirements[8].description` and `needs_clarification[2].resolution`.
  - `spec_v2.md` / `spec_v2.json`: EC-001 says an empty recipe list is 2 statements; EC-002 says a single recipe with no tools is 5 statements.
- **Issue**: The formula is correct, but the prose minimum is only true for a non-empty page that loads at least one `Tool` row. As written, it contradicts the edge cases added to fix v1.
- **Recommendation**: Qualify the minimum everywhere as “minimum for the FR-010 seeded non-empty case / any non-empty page with at least one loaded tool.” Keep EC-001=2 and EC-002=5.

### C2-002 — SC-C / EC-006 “worst-case” examples undercount distinct-tool chunking

- **Severity**: Medium
- **Scope**: self_concerns ↔ edge cases ↔ FR-009 formula
- **Locations**:
  - `spec_v2.md`: SC-C says a 1,000-recipe page could yield ~3,000 distinct Tool IDs (6 chained chunks), then says EC-006 enumerates worst-case counts of 9 and 13.
  - `spec_v2.md`: EC-006 labels 1,000 recipes / 300 tools = 9 and 1,500 recipes / 600 tools = 13 as worst-case bookkeeping.
  - `spec_v2.json`: same content in `self_concerns[2]` and `edge_cases[5]`.
- **Issue**: Under the FR-010-style “3 unique tools per recipe” upper bound, 1,000 recipes could have 3,000 distinct tools, producing `2 + 2+2+2 + 6 = 14` statements. 1,500 recipes with 4,500 distinct tools would produce `2 + 3+3+3 + 9 = 20`. The formula is still correct, but the examples are not worst cases.
- **Recommendation**: Either rename EC-006’s 9/13 counts as bounded examples with fixed tool cardinality, or update the worst-case examples to use the same distinct-tool assumption as SC-C.

### C2-003 — SC-004 mixes 50-recipe and 100-recipe benchmark wording

- **Severity**: Low
- **Scope**: success criteria internal consistency
- **Locations**:
  - `spec_v2.md`: SC-004 requires before/after query count for 100 recipes, but its example table says `before: ~92 queries (50 recipes), after: 6 queries` for the 100-recipe case.
  - `spec_v2.json`: same mismatch in `success_criteria[3].metric` / `.verification`.
- **Issue**: The verification example can be read as comparing a 50-recipe “before” run to a 100-recipe “after” run.
- **Recommendation**: Make both sides the same scale, or explicitly say the example is illustrative and the required table must include the 100-recipe before/after pair.

## Self-concerns vs FRs / ACs

- **SC-A** remains consistent with FR-001/FR-006/NC-005.
- **SC-B** is consistently marked out of scope and does not conflict with FR-011.
- **SC-C** captures the right risk, but its mitigation/examples conflict with its own high-cardinality statement-count note (C2-002).
- **SC-D** remains consistent with FR-001 and SC-002.
- **SC-E** correctly resolves v1 C-001: FR-011 and NC-002 now reference `SC-E` consistently.

## Edge cases vs FRs / ACs

- EC-001 and EC-002 are internally plausible, but they expose the unqualified FR-009/NC-003 “minimum is 6” contradiction (C2-001).
- EC-003 through EC-005 align with the loader strategy and tenancy requirements.
- EC-006 is directionally aligned with formula-bound chunking, but its “worst-case” wording conflicts with SC-C and FR-009 when distinct Tool count is high (C2-002).
- EC-007 and EC-008 remain consistent with FR-009/FR-013 when treated as outside the FR-010 measured path.

## spec.md vs spec.json diff

| Field | spec_v2.md | spec_v2.json | Disagreement |
|---|---|---|---|
| FR-014 baseline capture | Includes an implementation instruction to capture the pre-refactor response from `main` once and persist sorted JSON to a fixture file or recompute via a baseline helper. | Omits this instruction from `functional_requirements[13].description`. | Material omission: a JSON-only implementer sees the assertion shape but not the required baseline-capture protocol. |
| FR-015 verification commands | Lists five exact Windows PowerShell `uv run pytest ...` commands and says all five must exit 0. | Says “listed uv run pytest commands” but does not include the concrete commands. | Minor precision loss; not a semantic blocker if FR-015’s file list is followed. |
| FR-013 repository_generic line range | Uses `407-430,432-450`. | Uses `407-450`. | Formatting/range condensation only; no semantic conflict. |
| Titles / “NEW” annotations | Markdown titles include more “NEW / addresses …” prose. | JSON titles are shorter. | Formatting difference only. |

No other material `spec_v2.md` / `spec_v2.json` disagreements were found; most differences are condensation for machine-readable form.

## needs_clarification assessment

- NC-002 is fixed relative to v1 and points to `SC-E` consistently.
- NC-003 needs the same qualification as FR-009: “minimum 6” applies to the FR-010 seeded non-empty-with-tools case, not to empty or no-tool pages.
- NC-007 resolves the byte-identical-vs-normalized comparison conflict for US-1/SC-002, though the top-level intent still uses “byte-identical” informally. This is acceptable if FR-014/SC-002 remain canonical.
