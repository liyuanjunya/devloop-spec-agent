# C2 Live Activation Result

**Date:** 2026-06-20
**Workspace:** `specs/GAP-C2-live-20260620/`
**Validator under test:** `devloop.spec_phase.validators.test_executability.verify_spec_test_executability`
**Schema fed in:** `Spec`

## Synthetic input

`spec.json` containing three minimal user stories. Each `UserStory.independent_test`
references a distinct test file/function, plus the acceptance `given` clauses
mention the file paths again so the extractor sees both `(path, func)` and
`(path, None)` references:

| Story | `independent_test` reference          | Expected outcome             |
|-------|---------------------------------------|------------------------------|
| US-1  | `tests/test_gap_c2_ok.py::test_baseline`        | clean, no problem        |
| US-2  | `tests/test_gap_c2_brokenimport.py::test_x`     | `import_error`           |
| US-3  | `tests/test_gap_c2_nofunc.py::test_missing`     | `collect_error` (missing func) |

Stub files written into `scratch/tests/`:
- `test_gap_c2_ok.py` — defines `test_baseline` cleanly
- `test_gap_c2_brokenimport.py` — top-level `from nonexistent_module import nope`
- `test_gap_c2_nofunc.py` — defines `test_present` instead of the spec-named `test_missing`

## Extraction (deterministic, identical in both runs)

```
EXTRACTED:
  ('tests/test_gap_c2_ok.py',           'test_baseline')
  ('tests/test_gap_c2_ok.py',           None)
  ('tests/test_gap_c2_brokenimport.py', 'test_x')
  ('tests/test_gap_c2_brokenimport.py', None)
  ('tests/test_gap_c2_nofunc.py',       'test_missing')
  ('tests/test_gap_c2_nofunc.py',       None)
```

The `(path, None)` rows come from the file-only mentions in each story's `given`
clause ("the stub file `tests/test_gap_c2_ok.py` exists ..."). The regex
`\btests[\\/][\w\\/\-.]*?test_[\w\-.]+\.py(?:::([A-Za-z_]\w*))?` correctly
captures both shapes and the extractor deduplicates on `(path, func)` tuples.

## Run 1 — `scratch_dir = ws/'scratch'` (in-tree)

Output: **6 problems**, every reference flagged as `import_error`.

This surfaced a **pre-existing limitation worth recording, not a bug in C2 logic**:
when `scratch_dir` lives inside a project that ships a `pyproject.toml` with
`[tool.pytest.ini_options].addopts = ["-v"]` (devloop does), pytest walks up
from `--rootdir` and adopts that configfile. The injected `-v` overrides the
`-q` the validator passes, switching pytest into tree-style output
(`<Function test_baseline>`) instead of node-id-per-line output
(`tests/test_x.py::test_baseline`). The validator's `_NODE_ID_RE` no longer
matches anything, so `_parse_collected_node_ids` returns an empty set and
every reference appears uncollected — each gets classified `import_error`
because the combined stdout/stderr does contain a real `ModuleNotFoundError`
from the broken stub.

In production this never bites because the default `scratch_dir=None` invokes
`tempfile.TemporaryDirectory(prefix="devloop_testexec_")` under `%TEMP%`,
which is outside every project tree.

## Run 2 — out-of-tree scratch (mirrors production)

Re-ran via `run_c2_outoftree.py` using a `tempfile.TemporaryDirectory(...)` so
pytest does not adopt the devloop project's configfile. Same `Spec` JSON,
same stub contents.

Output: **3 problems**, exactly the right shape.

```
PROBLEMS: 3
  - tests/test_gap_c2_brokenimport.py::test_x  kind=import_error
  - tests/test_gap_c2_brokenimport.py::None    kind=import_error
  - tests/test_gap_c2_nofunc.py::test_missing  kind=collect_error
        "pytest collected tests/test_gap_c2_nofunc.py but the spec-named
         test function 'test_missing' was not present. Update the spec to
         use the actual function name or add the missing test to the file."
```

### Per-reference verification

| Reference                                          | Expected         | Got               | OK? |
|----------------------------------------------------|------------------|-------------------|-----|
| `tests/test_gap_c2_ok.py::test_baseline`           | clean            | not in problems   | ✅ |
| `tests/test_gap_c2_ok.py` (file-only)              | clean            | not in problems   | ✅ |
| `tests/test_gap_c2_brokenimport.py::test_x`        | `import_error`   | `import_error`    | ✅ |
| `tests/test_gap_c2_brokenimport.py` (file-only)    | `import_error`   | `import_error`    | ✅ |
| `tests/test_gap_c2_nofunc.py::test_missing`        | `collect_error`  | `collect_error`   | ✅ |
| `tests/test_gap_c2_nofunc.py` (file-only)          | clean (file collected) | not in problems | ✅ |

The classification of the `collect_error` is **especially good**: it correctly
distinguishes "file imported but the named function wasn't there" from "file
itself blew up" (which would be `import_error`). The detail message tells the
rewriter exactly what to fix.

## Verdict

🟢 **C2 FIRED CORRECTLY**

Run 2 (production-equivalent conditions) produced exactly the two failure
kinds the test was designed to elicit — `import_error` for the unresolvable
top-level import, `collect_error` with a "spec-named test function not
present" message for the rename mismatch — and left the healthy stub
silently passing. Run 1 (in-tree scratch) over-flagged in an expected way
that exposes a real but narrowly-scoped configfile-discovery limitation,
documented here so the team is aware.

## Suggested follow-up (not part of this task)

Pass `--override-ini=addopts=` (and optionally `-c`/`--no-header`) inside
`_run_pytest_collect_only` so the validator is robust against ambient project
configfiles even when callers wire `scratch_dir` to an in-tree location for
debugging. Today the implicit "always use a temp dir" production path hides
this, so it's a latent / low-priority hardening.
