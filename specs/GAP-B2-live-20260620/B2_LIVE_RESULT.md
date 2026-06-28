# B2 Live Activation Result

**Date:** 2026-06-20
**Workspace:** `specs/GAP-B2-live-20260620/`
**Validator under test:** `devloop.spec_phase.validators.coverage_gap_detector.detect_coverage_gaps`
**Schema fed in:** `ConsolidatedExploration`

## Synthetic input

Hand-crafted `synthetic_exploration.json` containing:

- **5 perspectives** (`data`, `api`, `test`, `history`, `ui`), each with 3 `relevant_artifacts`
- **1 singleton critical**: `mealie/services/scheduler/__init__.py:1-10`
  (symbols `SchedulerService`, `register_daily_task`) marked `importance="critical"`
  only inside the `api` perspective. Every other perspective lists only `relevant` artifacts.
- **1 unresolved conflict**: between `api` and `data` perspectives — "api perspective claims
  RecipeOut.last_made is populated by the controller from a join, but the data perspective
  reports the column does not exist on the Recipe ORM model — disagreement on whether the
  field is computed or persisted." `resolution_suggestion` left empty.
- No `sparse_perspective` expected (all 5 perspectives have ≥ `SPARSE_SIBLING_THRESHOLD = 3` artifacts).

## Harness output (verbatim)

```
GAPS DETECTED: 2
  - kind=singleton_critical  detail=Critical artifact 'mealie/services/scheduler/__init__.py' (symbols=['SchedulerService', 'register_daily_task']) was surf
    question=Confirm or refute that 'mealie/services/scheduler/__init__.py' is critical to this feature. Only the 'api' perspective flagged it; verify by opening the file and checking how it actually interacts wit
    primary_perspective=api
  - kind=unresolved_conflict  detail=Unresolved conflict between perspectives [api, data]: api perspective claims RecipeOut.last_made is populated by the con
    question=Break this tie between the [api, data] perspectives: api perspective claims RecipeOut.last_made is populated by the controller from a join, but the data perspective reports the column does not exist o
    primary_perspective=None
```

## Gap-by-gap analysis

### Gap 1: `singleton_critical` ✅

- **Detected path:** `mealie/services/scheduler/__init__.py`
- **Only flagging perspective:** `api`
- **`primary_perspective` populated:** `api` (correct — used by orchestrator to pick a *different*
  perspective for the targeted re-explorer)
- **Re-explore question:** concrete, names the path, explains the singleton context, asks the
  re-explorer to confirm/refute by opening the file. ✅

### Gap 2: `unresolved_conflict` ✅

- **Perspectives involved:** `[api, data]`
- **Resolution suggestion was empty** → correctly flagged.
- **Description length:** comfortably above `MIN_CONFLICT_DESCRIPTION_LEN = 10`.
- **`primary_perspective`:** `None` (correct — conflict is multi-perspective).
- **Re-explore question:** carries the full description and instructs the re-explorer to open
  the files and produce a concrete tie-breaking answer. ✅

### Gap 3: `sparse_perspective` — none detected ✅

All five perspectives carry ≥ 3 artifacts, so no perspective is flagged as sparse. This is the
intentional design (silent on populated explorations) and matches expectations.

## Stable ordering

Output ordering observed: `singleton_critical` → `unresolved_conflict`. Matches the docstring
contract that gaps are returned in `singleton_critical → unresolved_conflict → sparse_perspective`
order.

## Verdict

🟢 **B2 FIRED CORRECTLY**

The coverage-gap detector activated on a realistic adversarial input shape and produced
**both** expected gap kinds (singleton_critical + unresolved_conflict) with usable re-explore
questions, correct `primary_perspective` hints, and the documented stable ordering. No
unexpected gaps, no missed gaps, no schema mismatches.
