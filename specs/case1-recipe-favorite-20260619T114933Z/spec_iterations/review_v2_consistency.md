# Consistency Review (v2)

## Verdict: NEEDS_REFINE

Spec v2 resolves the substantive v1 consistency contradictions: `/api/users/self/favorites` now consistently means paginated `RecipeSummary`, anonymous public recipe reads consistently return `favorited=false` with real `favorite_count`, and `users_to_recipes` cleanup is now captured by US-6/FR-009/SC-007. I found no new US ↔ FR ↔ SC contradiction in the markdown itself. The remaining blocker is spec.md vs spec.json drift: the JSON omits multiple markdown sections and truncates self-concerns/code-reference symbols, so downstream JSON-only implementers would miss constraints.

## Critical issues

(none in the markdown spec)

## High issues

- **CONS-H-001**: `spec_v2.json` is not a complete field-by-field representation of `spec_v2.md`.
  - The markdown contains normative implementation constraints in Existing-code findings, Key Entities, Edge Cases, Assumptions, and Out of Scope. The JSON omits those sections entirely.
  - This is especially relevant because v1 already had JSON drift around Edge Cases. v2 fixes the markdown edge-case wording, but the JSON still drops all edge cases.
  - Impact: agents consuming only `spec_v2.json` may miss visibility/count rules, generated-type restrictions, frontend out-of-scope limits, and the “do not code if NC-001 is rejected until the spec is revised” guard.
  - Suggested action: extend the JSON schema/export to include these markdown sections or mark them explicitly non-normative in the markdown.

## Medium issues

(none)

## V1 consistency issue resolution check

- **CONS-C-001** (`/api/users/self/favorites` dual contract): **Resolved.** US-3 AC1/AC4, NC-002, FR-003, FR-004, SC-003, and Assumption #3 all choose recipe-list semantics at `/api/users/self/favorites` and move rating summaries to a ratings-namespaced route.
- **CONS-H-001** (anonymous `favorite_count` default): **Resolved.** US-4 AC3, FR-007, SC-005, Assumption #4, and the anonymous edge case all say anonymous readers get `favorited=false` and real `favorite_count`.
- **CONS-H-002** (missing cleanup/cascade FR): **Resolved.** FR-009 now requires FK cascade migration, `RepositoryUsers.delete` cleanup, and recipe-delete regression preservation.
- **CONS-M-001** (anonymous visibility semantics): **Resolved in markdown.** FR-007 scopes anonymous reads to public explore routes; the edge case says private/hidden recipe counts are bounded by the endpoint visibility model.
- **CONS-M-002** (SC-004 no-regression wording): **Resolved.** SC-004 now measures no N+1 with bounded query count and separately allows ≤10% p95 regression only when a benchmark baseline exists.
- **CONS-M-003** (US-3 AC3 md/json drift): **Resolved.** Both markdown and JSON include “unless also favorited by the current user and visible in the current group.”
- **CONS-M-004** (edge-case md/json drift): **Not resolved.** The specific edge case is present in markdown, but JSON omits the entire edge_cases section.

## NEW contradictions

(none found)

## spec.md vs spec.json diff

### Metadata

- `spec_v2.md` has `Status: Draft v2 — needs blocking decisions recorded`; `spec_v2.json` has no `status` field. `metadata.needs_review=true` is related but not equivalent because it loses the “blocking decisions recorded” wording.
- `spec_v2.json` has `metadata.writer_model="copilot-cli-spec-rewriter"`; `spec_v2.md` has no corresponding field.
- `feature_id`, title, schema version, iterations, and summary match semantically.

### Markdown sections absent from JSON

- `Existing-code findings` is present in markdown and absent from JSON.
- `Key Entities` is present in markdown and absent from JSON.
- `Edge Cases` is present in markdown and absent from JSON.
- `Assumptions` is present in markdown and absent from JSON.
- `Out of Scope` is present in markdown and absent from JSON.

### User stories

- US-1 through US-6 ids, priorities, titles, descriptions, independent tests, and acceptance criteria match semantically.
- JSON preserves markdown line-break trailing spaces in descriptions/independent tests; this is formatting drift only.

### Functional requirements

- FR-001 through FR-012 text, requirement type, related story ids, paths, and line ranges match semantically.
- Code-reference symbol extraction has formatting drift:
  - FR-001: JSON symbols `user_id` index / `recipe_id` index have missing opening backticks; migration symbols have missing closing backticks.
  - FR-002: JSON symbol `users` and `user_ratings` repositories has a missing opening backtick.
  - FR-006: JSON symbol `exceptions.no-entry-found` has a missing closing backtick.
  - FR-007: JSON symbols `UserAPIRouter` and `BaseUserController` have missing opening backticks.
  - FR-008: JSON symbols `page_all`, `orderBy use of column_aliases`, and `favorited_by` have missing opening/closing backticks.
  - FR-009: JSON symbol `ondelete` has a missing closing backtick.

### Success criteria

- SC-001 through SC-008 text, metric, and threshold match semantically.

### Self-concerns

- Markdown self-concerns include IDs plus explanatory evidence-gap text; JSON keeps only abbreviated strings.
- JSON self-concern 1 drops the original-input/new-table context and the “must accept storage reuse before implementation skips requested new table” wording.
- JSON self-concern 2 drops the exact `errors.no-entry-found` vs `exceptions.no-entry-found` branch and the “add that key explicitly before coding” condition.
- JSON self-concern 3 drops the allowed implementation alternatives and the serialization-correctness constraint.

## Self-concerns verdicts

- **NC-001/FR-001 storage reuse:** Consistent. It does not contradict FR-001 because both require a recorded decision and make reuse the default unless rejected.
- **FR-006 i18n key:** Consistent. FR-006 explicitly allows either adding `errors.no-entry-found` or obtaining approval to use `exceptions.no-entry-found`.
- **FR-008 hydration design choice:** Consistent. Leaving column-property vs batched assignment to implementation does not contradict the no-N+1 requirement.

## Summary

Markdown v2 is internally consistent and resolves the v1 consistency blockers. The only refinement needed is publication consistency: `spec_v2.json` must either include all normative markdown sections and full self-concern text or clearly declare itself a partial projection.
