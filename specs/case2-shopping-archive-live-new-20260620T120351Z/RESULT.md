# case-2 new pipeline result (Shopping List Archive)

Live run of the NEW pipeline (all 19 v7 defenses) against case-2.
Workspace: `specs/case2-shopping-archive-live-new-20260620T120351Z/`
Source tree: `C:\Users\v-liyuanjun\Downloads\mealie\` (commit `4a099c16`).

## v1: C/H counts per axis

| Axis           | Critical | High | Medium | Verdict       |
|----------------|----------|------|--------|---------------|
| Architecture   | 0        | 0    | 2      | APPROVE       |
| Completeness   | 0        | 1    | 3      | NEEDS_REFINE  |
| Executability  | 0        | 0    | 2      | APPROVE       |
| Consistency    | 0        | 2    | 3      | NEEDS_REFINE  |
| **Total**      | **0**    | **3**| **10** | **NEEDS_REFINE** |

Validators on v1: A4+F3 PASS · A5 0 problems · B3 0 gaps · B1 PASS
(after one one-off-by-one citation fix loop).

v1 stats:
- 9 user stories (≥8 ✓)
- 16 functional requirements (≥15 ✓)
- 10 success criteria (≥8 ✓)
- 8 edge cases (≥6 ✓)
- 2 NEEDS_CLARIFICATION blocking decisions (≥2 ✓)
- 6 key entities (1 new + 5 extended), 5 assumptions, 6 out_of_scope,
  3 self_concerns
- `intent_type = add_feature` (correctly set in inputs)

The 3 high issues from v1:
- **Completeness H1**: SC-008 implicit field-shape contract for
  `?archived=all` — a test author could miss that `archived_at` /
  `archived_by` must always be present (null on active, populated on
  archived).
- **Consistency H1**: NC-002 if_rejected forgot to instruct that SC-006
  / FR-005 / key_entities also change if `total_estimated_amount` is
  dropped.
- **Consistency H2**: NC-001 related_requirements was missing FR-010
  and FR-016 — a downstream rewriter would miss part of the work if
  the reviewer flipped to "freeze all 7 routes".

## v2: C/H counts per axis

| Axis           | Critical | High | Medium | Verdict |
|----------------|----------|------|--------|---------|
| Architecture   | 0        | 0    | 2      | APPROVE |
| Completeness   | 0        | 0    | 3      | APPROVE |
| Executability  | 0        | 0    | 2      | APPROVE |
| Consistency    | 0        | 0    | 3      | APPROVE |
| **Total**      | **0**    | **0**| **10** | **APPROVE** |

Validators on v2: A4+F3 PASS · A5 0 problems · B3 0 gaps · B1 PASS.

v2 corrections applied (surgical edits only — no FR/US restructuring):
1. SC-008 text + metric + threshold rewritten to pin the per-row
   `archived_at` / `archived_by` JSON shape for each of the three
   query modes.
2. NC-001 `related_requirements` widened to
   `["FR-007", "FR-008", "FR-010", "FR-016", "SC-004"]`.
3. NC-002 `if_rejected` extended to enumerate every spec field that
   has to change if the reviewer drops the field.

## Δ (v1 → v2)

| Metric                    | v1 | v2 | Δ      |
|---------------------------|----|----|--------|
| Critical                  | 0  | 0  | 0      |
| High                      | 3  | 0  | **−3** |
| Medium                    | 10 | 10 | 0      |
| Axes verdict APPROVE      | 2  | 4  | **+2** |
| Axes verdict NEEDS_REFINE | 2  | 0  | **−2** |
| Mechanical validator pass | 4/4| 4/4| 0      |

All 3 Highs closed. Medium count is steady — by design: v2 was scoped
to fix the High items only (per the task time-box) so the surfaced
Mediums (e.g. SC-001 trivial-true half, mixins.py citation, bulk-route
enumeration in SC-004) remain documented in v2 reviews for a future
iteration.

## Final verdict

**APPROVE.** The spec is ready for the Stage 6 coding gauntlet.

Key quality signals:
- Both iterations pass all 4 mechanical validators (A4 soft-language,
  A5 citation verifier, B3 trace matrix, B1 md↔json roundtrip) without
  exceptions.
- Both iterations satisfy the F3 under-escalation guard (no
  `Concern.evidence_gap` enumerates ≥3 implementation options).
- v2 closes every High issue surfaced by the four-axis self-review.
- The 16 FRs trace bidirectionally to 10 SCs and 9 US (B3 gaps = 0).
- Every code reference in the spec points to a real file + line range
  in the Mealie source tree (A5 problems = 0). After the initial pass,
  6 off-by-one ranges were tightened from spec-fence (`end == n+1`) to
  actual file length (`end == n`); no symbol assertions failed.
- The spec correctly identifies the hidden second migration (event
  notifier options per `event_types.py` lines 14-22), the scheduler
  silent-failure (delete_old_checked_shopping_list_items.py), and the
  three unfrozen routes (NC-001) that the input does not enumerate.

## Mark SQL done

```sql
UPDATE todos SET status = 'done' WHERE id = 'LIVE-c2-new-pipeline';
```

(applied below)
