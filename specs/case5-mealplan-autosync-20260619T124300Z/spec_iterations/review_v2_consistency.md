# Consistency Review v2 — Case-5 Meal Plan Auto-Sync

**Reviewer**: Consistency  
**Result**: PASS

## Summary

Spec v2 resolves the v1 consistency blockers. The user stories, functional requirements, success criteria, edge cases, needs-clarification decisions, self-concerns, and constraints are now mutually consistent enough for implementation. In particular, the v1 High issues around household-scoped target fallback, server-only `last_auto_synced_at`, and CAS/no-target ordering are resolved in FR-7/FR-10, FR-20, FR-22, SC-7, EC-1, and EC-2.

## Findings

No blocking or non-blocking consistency findings.

## Self-concerns vs FRs / ACs

- **SCN-1** aligns with FR-17 and FR-26(a): the spec consistently reuses `ShoppingListService.add_recipe_ingredients_to_list` / `bulk_create_items` today and defers any future case-3 extracted `consolidate_ingredients` seam to a follow-up.
- **SCN-2** aligns with FR-7, FR-16, and the constraints: timezone validation uses `ZoneInfo`, runtime resolution falls back directly to UTC, and naive `datetime.now()` is forbidden.
- **SCN-3** is resolved: FR-7 excludes `last_auto_synced_at` from update input, FR-10 says the route never sees it, and FR-20 writes it only through raw CAS/manual updates.

## Edge cases vs FRs / ACs

- **EC-1 / EC-2** now match FR-20's ordered pipeline: no-target returns before CAS, while empty meal plans mark scheduled runs after CAS and manual runs per the matrix.
- **EC-3** is consistent with FR-1's `ondelete="SET NULL"` and FR-22 fallback behaviour.
- **EC-4** is consistent with FR-17's full-recipe re-fetch and silent skip.
- **EC-5 / EC-7** are consistent with FR-16 / FR-20 local-day CAS derivation.
- **EC-6** no longer claims unsupported i18n/response behaviour.
- **EC-8** is intentionally documented and tied to NC-4, so the top-level-only pantry filtering limitation is not contradictory.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| Title | `Case 5 — Meal Plan → Shopping List Auto-Sync (Mealie) — Spec v2` | `Meal Plan auto-sync to Shopping List (Mealie)` | Cosmetic wording/capitalization only. |
| Intro/provenance | Includes human-readable provenance and says both files share canonical content. | Omits the prose intro. | Non-behavioral metadata omission. |
| Selected approach | Expressed through prose/constraints. | Has `selected_approach: hybrid_polling_with_shared_helper`. | Extra structured metadata only. |
| Naming reconciliations | Markdown table. | `naming_reconciliations[]`. | Same semantics. |
| FR/SC/EC/NC/SCN content | Markdown sections/tables. | Structured arrays with matching IDs and equivalent text. | No material semantic mismatch found. |
| Code references | Table cells with verified references. | `code_references[]` arrays. | References appear normalized and aligned per FR; no behavioral disagreement found. |
| Constraints | Bullet list with sub-bullets. | Compressed strings in `constraints[]`. | Same semantics. |

No material `spec.md` vs `spec.json` behavioral disagreement was found. Any differences are formatting or metadata representation differences.

## needs_clarification assessment

All `needs_clarification` entries are non-blocking and have explicit v2 decisions:

- **NC-1**: resolved by the manual marker matrix.
- **NC-2**: cross-case archived-list behaviour is explicitly deferred.
- **NC-3**: pantry-staple scope decided as per-Food/group-shared, with tests covering cross-group isolation and same-group sharing.
- **NC-4**: recursive sub-recipe pantry filtering explicitly deferred and mirrored by EC-8.

## Recommended resolution order

No consistency revisions required before coding. Proceed to implementation.
