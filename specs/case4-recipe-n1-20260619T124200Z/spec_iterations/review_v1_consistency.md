# Consistency Review v1 — Case 4 Recipe List N+1 Performance Refactor

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION

## Summary

The spec is largely coherent around the selected loader-options refactor, response-field preservation, and the new query-count regression test. However, a few consistency defects should be corrected before implementation: the explore-endpoint self-concern cross-reference is wrong in both artifacts, one edge-case query-count calculation contradicts the loader strategy, and the perPage=-1 chunking ceiling is overstated.

## Findings

### C-001 — Explore-endpoint coverage references the wrong/nonexistent self-concern

- **Severity**: High
- **Scope**: FR ↔ self_concerns; needs_clarification ↔ self_concerns; spec.md vs spec.json
- **Locations**:
  - `spec.md`: FR-011 says explore coverage is captured as `self_concerns SC-003`; NC-002 repeats `SC-003`.
  - `spec.json`: FR-011 and NC-002 say `self_concerns SC-C`.
  - `self_concerns`: IDs are `SC-A`..`SC-D`; `SC-C` is query-count chunking, not explore coverage. `SC-003` is a success criterion, not a self-concern.
- **Issue**: Neither artifact points to a self-concern that actually captures optional explore-endpoint query-count coverage.
- **Recommendation**: Either add a new self-concern for optional explore endpoint coverage and reference that ID consistently, or change FR-011/NC-002 to reference SC-007 if the intended coverage is simply “shared fix/no duplication.”

### C-002 — EC-002 query-count arithmetic contradicts FR-007/FR-009

- **Severity**: Medium
- **Scope**: Edge cases ↔ FRs/ACs
- **Locations**:
  - `spec.md`: EC-002 says `tags=[]`, `recipe_category=[]`, `tools=[]` still yields “3 statements ... plus 1 for users plus parent + COUNT = 6.”
  - `spec.json`: `edge_cases[1].expected` has the same statement.
  - FR-007 says `RecipeModel.user` remains a 1:1 `joinedload`, not a separate cursor execute.
  - FR-009 says the minimum 6 includes the chained `Tool.households_with_tool` selectinload.
- **Issue**: For a recipe with no tools, the chained households query is elided, and the user loader is part of the parent SELECT. The stated count should be COUNT + parent-with-joined-user + category selectinload + tag selectinload + tools selectinload = typically 5, not 6.
- **Recommendation**: Rewrite EC-002 to say “typically 5; still within FR-009,” and reserve 6 for pages with at least one loaded tool that triggers the chained households selectinload.

### C-003 — perPage=-1 chunking ceiling is inconsistent with FR-009

- **Severity**: Medium
- **Scope**: Edge cases ↔ FRs; self_concerns ↔ FRs/defaults
- **Locations**:
  - FR-009 bounds `<= 10` only for `perPage <= 1000`.
  - EC-006 discusses `perPage=-1` (“load all rows”) and still says it is bounded by FR-009 absolute `<= 10` for “reasonable user limits.”
  - SC-C says four selectinload paths may split but describes only “up to 3 extra statements,” yielding “~9.”
- **Issue**: `perPage=-1` has no row limit, so the number of selectinload chunks can exceed the `<= 1000` case. Also, if all four selectinload paths split for 501-1000 IDs, the extra statements are +4 and the total can be ~10, not ~9.
- **Recommendation**: Scope EC-006/SC-C explicitly to `<=1000` loaded parents/child IDs, or state that perPage=-1 over larger libraries remains bounded by chunk count, not by the fixed `<=10` ceiling.

### C-004 — “byte-identical” conflicts with “modulo non-deterministic fields”

- **Severity**: Medium
- **Scope**: US ↔ SC; AC-internal
- **Locations**:
  - US-1 acceptance requires a JSON diff returning `{}`.
  - SC-002 says responses are byte-identical “modulo” `createdAt`, `updatedAt`, and random UUIDs.
- **Issue**: A byte-identical JSON diff cannot simultaneously ignore differing fields unless the comparison is normalized. If the same database rows are reused pre/post refactor, these values should not differ; if data is reseeded, the comparison is not byte-identical.
- **Recommendation**: Define the comparison mode: either same seeded rows with exact `{}` diff, or normalized diff that masks specified volatile fields. Align US-1 and SC-002 wording.

### C-005 — Regression-test request parameters are inconsistent/underspecified

- **Severity**: Low
- **Scope**: US ↔ FR ↔ self_concerns
- **Locations**:
  - US-4/SC-001 describe query counts for 10 recipes and 100 recipes.
  - FR-010 specifies seeding 10 then +90 and asserting `len(body["items"])` / `total`, but does not define the measured request `perPage` values.
  - SC-C says the regression test parameters are `perPage=50`, then `perPage=200`.
- **Issue**: SC-C introduces concrete request parameters not required by FR-010. They can work, but downstream implementers reading FR-010 alone may choose different values while still believing they satisfy the spec.
- **Recommendation**: Add the intended measured calls to FR-010, e.g. `perPage=50` after 10 rows and `perPage=200` after 100 rows, or remove the concrete values from SC-C.

## Self-concerns vs FRs / ACs

- **SC-A** is consistent with FR-001/FR-006/NC-005: it explains why `Tool.households_with_tool` is the concrete N+1 root and why no comments field should be added.
- **SC-B** is consistent as an out-of-scope follow-up, but it slightly tensions FR-011’s broad “every call site” wording. FR-011 should stay scoped to `RepositoryRecipes.page_all` / direct `RecipeSummary.loader_options()` consumers.
- **SC-C** identifies a real chunking caveat, but its arithmetic and `perPage=-1` implications need the correction in C-003.
- **SC-D** is consistent with FR-001 and SC-002: no schema field change means no generated TypeScript diff is expected.

## Edge cases vs FRs / ACs

- EC-001 aligns with FR-009.
- EC-002 conflicts with FR-007/FR-009 query-count arithmetic (C-002).
- EC-003 aligns with FR-006 and FR-009.
- EC-004 aligns with FR-003..FR-005; no spec contradiction found.
- EC-005 aligns with FR-012 and US-3.
- EC-006 needs the fixed ceiling/chunking scope from C-003.
- EC-007 aligns with FR-009 if the random-order case uses the relaxed `<=10` ceiling.
- EC-008 aligns with FR-013.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| FR-011 / NC-002 self-concern reference | References `self_concerns SC-003`. | References `self_concerns SC-C`. | Both are wrong in different ways: `SC-003` is a success criterion, while `SC-C` is chunking, not explore coverage (C-001). |
| SC-007 verification allowed occurrences | Allows `selectinload(Tool.households_with_tool)` in `recipe.py`, `recipe_tool.py`, and “any out-of-scope adjacent seam.” | Allows only `recipe.py` and `recipe_tool.py`, not explore routes. | JSON is stricter; md leaves ambiguous extra allowed locations. Align the allowed occurrence list. |
| EC-004 FK/cascade detail | Notes no explicit `ON DELETE CASCADE` clause is documented in secondary tables; normal flow cascades via SQLAlchemy session behavior. | Condenses to FK constraints and SQLAlchemy cascade in normal flow. | JSON drops the “no explicit ON DELETE CASCADE” nuance; likely non-blocking but less precise. |
| Title / selected approach wording | Markdown title includes “Case 4”; approach is split across Intent/Approach prose. | JSON title adds “on Mealie”; selected approach is a compact string. | Formatting/summary difference only; no semantic conflict. |

No other material spec.md/spec.json disagreements were found; most differences are condensation or structured representation.

## needs_clarification assessment

Existing NC items mostly resolve input-level ambiguity consistently. However:

1. NC-002 must stop referencing `SC-003`/`SC-C` unless a matching self-concern is added.
2. NC-003’s relaxed ceiling is consistent for normal bounded pages, but EC-006/SC-C must clarify how it applies to `perPage=-1` and chunking.
3. US-1/SC-002 should clarify exact-vs-normalized JSON diff semantics for volatile fields.
