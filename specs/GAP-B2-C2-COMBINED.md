# GAP B2 + C2 Live Activation — Combined Summary

**Date:** 2026-06-20
**Goal:** Drive the two defenses (B2 coverage-gap detector, C2 test-grounded
executability) with realistic adversarial fixtures so we can observe them
firing end-to-end rather than only via unit/integration tests.

| Defense | Workspace | Validator | Verdict |
|---------|-----------|-----------|---------|
| **B2** — Coverage gap detector | `specs/GAP-B2-live-20260620/` | `devloop.spec_phase.validators.coverage_gap_detector.detect_coverage_gaps` | 🟢 **FIRED** |
| **C2** — Test-grounded executability | `specs/GAP-C2-live-20260620/` | `devloop.spec_phase.validators.test_executability.verify_spec_test_executability` | 🟢 **FIRED** |

## B2 summary

Hand-crafted `ConsolidatedExploration` JSON with five perspectives — one
`critical` artifact (`mealie/services/scheduler/__init__.py`) flagged only by
the `api` perspective, plus one `Conflict` (api vs data on
`RecipeOut.last_made`) with an empty `resolution_suggestion`. Loaded via
`ConsolidatedExploration.model_validate` and fed straight into
`detect_coverage_gaps`.

Output: **2 gaps**, in the documented stable order:

1. `singleton_critical` — names the artifact path, lists symbols
   (`SchedulerService`, `register_daily_task`), pins `primary_perspective="api"`
   so the orchestrator picks a *different* perspective for the targeted
   re-explorer, and emits a concrete confirm/refute re-explore prompt.
2. `unresolved_conflict` — copies the conflict description into the
   re-explore prompt with `primary_perspective=None` (correct — the conflict
   spans two perspectives), and tells the re-explorer to open the files and
   produce a tie-breaking answer.

No `sparse_perspective` gap (all five perspectives have ≥
`SPARSE_SIBLING_THRESHOLD = 3` artifacts), matching expectations.

Full evidence: `specs/GAP-B2-live-20260620/B2_LIVE_RESULT.md`.

## C2 summary

Hand-crafted `Spec` JSON with three user stories, each `independent_test`
pointing at a different fixture stub: a healthy `test_baseline`, a
`from nonexistent_module import nope` broken-import file, and a file
whose only function is `test_present` while the spec names `test_missing`.

`extract_test_references(spec)` correctly pulled all three function-specific
references plus three file-only mentions from the acceptance `given` clauses.

Running `verify_spec_test_executability` with an **out-of-tree** scratch
directory (the production code path — default `scratch_dir=None` uses
`tempfile.TemporaryDirectory(prefix="devloop_testexec_")`) produced exactly
the expected outcome:

- `test_gap_c2_brokenimport.py::test_x` → `import_error` ✅
- `test_gap_c2_brokenimport.py` (file-only) → `import_error` ✅
- `test_gap_c2_nofunc.py::test_missing` → `collect_error` ✅
  with the precise message *"pytest collected … but the spec-named test
  function 'test_missing' was not present. Update the spec to use the actual
  function name or add the missing test to the file."*
- `test_gap_c2_ok.py::test_baseline` and its file-only sibling → **not in
  problems list** ✅ (the validator correctly stays silent on healthy refs)
- `test_gap_c2_nofunc.py` file-only ref → **not in problems list** ✅
  (file *did* collect, only the function-specific ref is flagged)

Classification is sharp: import failure vs missing function are distinguished
correctly, which is exactly what the downstream rewriter needs to fix the
right thing.

Full evidence: `specs/GAP-C2-live-20260620/C2_LIVE_RESULT.md`.

## Unexpected behavior worth recording

**Pre-existing, narrowly-scoped configfile-discovery limitation in C2** —
not a logic bug, but a real corner case the team should be aware of.

When `scratch_dir` is placed *inside* the devloop project tree (e.g.
`specs/GAP-C2-live-20260620/scratch`), pytest walks up from `--rootdir` and
discovers `devloop/pyproject.toml`, which carries
`[tool.pytest.ini_options].addopts = ["-v"]`. The injected `-v` overrides
the `-q` the validator passes, switching `--collect-only` from
node-id-per-line output (parseable by `_NODE_ID_RE`) into tree-style
output (`<Function test_baseline>`, unparseable). Result: every reference
appears uncollected and is over-flagged as `import_error` from the broken
stub's `ModuleNotFoundError` leaking into the combined stdout/stderr.

In production this never bites because the default `scratch_dir=None`
uses a `%TEMP%` directory outside every project. The fix, if anyone wants
to harden it: add `--override-ini=addopts=` (and maybe `-c`/explicit
configfile suppression) to `_run_pytest_collect_only`. Captured in the
C2 result writeup as a low-priority follow-up.

No unexpected behavior for B2 — it fired exactly per its docstring contract
on the first attempt.

## Reproduction

```powershell
cd C:\Users\v-liyuanjun\source\repos\devloop
python specs\GAP-B2-live-20260620\run_b2.py
python specs\GAP-C2-live-20260620\run_c2.py            # in-tree (6 problems, configfile leak)
python specs\GAP-C2-live-20260620\run_c2_outoftree.py  # production-equiv (3 problems, correct)
```

## SQL todo bookkeeping

```sql
UPDATE todos SET status = 'done'
WHERE id IN ('GAP-B2-live-activation','GAP-C2-live-activation');
```
