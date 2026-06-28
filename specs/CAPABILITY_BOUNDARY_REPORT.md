# DevLoop Spec Phase — Capability Boundary Report

**Date**: 2026-06-19
**Scope**: Post-Sprint A–D + Capability-Boundary test wave (15 defenses A1–A5, B1–B4, C1–C3, D1–D3)
**Test wave**: ~10 parallel sub-agent test tracks (`T-defense-fires-*`, `T-edge-*`, `T-stress-*`, `T-mealie-c[16]-new-pipeline`) plus two end-to-end Mealie re-runs.
**Codebase snapshot**: 68 source files / 9 905 LOC (`devloop/`), 46 test files / 15 761 LOC (`tests/`).
**Author**: synthesis report — written from the per-defense ANALYSIS sections embedded in the test files and the two `new_pipeline/COMPARISON.md` end-to-end reports.

> **Post-report addendum (2026-06-19)**: The A5 path-traversal security finding flagged in §5 has been **FIXED**: `_is_path_safe` now rejects absolute paths, drive-letter paths, leading-separator paths, and paths whose resolved target escapes the repo root. New problem kind `PROBLEM_INVALID_PATH` returned. 4 new adversarial tests pin the fix. **Test count: 472 / 472 passing. Ruff clean.**

---

## 1. Executive summary

| Dimension | Current value |
|---|---|
| Tests collected | **470** (up from 95 baseline → 347 after Sprint A–D → 470 after capability wave) |
| Tests passing | **470 / 470** in **22.96 s** (`pytest -q --tb=no`) |
| Ruff (devloop + tests) | **2 errors** — both `RUF059` unused tuple unpack at `tests/integration/test_perspective_select_e2e.py:719` (cosmetic) |
| Ruff (incl. spec scratch dir) | 8 errors — 6 of which are in a scratch helper `specs/case6-…/new_pipeline/run_validators.py` (E402, F541, RUF100) and don't ship |
| End-to-end pipeline coverage | NEW pipeline produced v1 specs for case-1 + case-6 with **0** combined critical issues across 8 deterministic validators |
| Capability-boundary tests added this wave | ≈ 123 new tests (470 − 347) across 11 new test files |

### Quality grade per axis

| Axis | Grade | One-line justification |
|---|---|---|
| Mechanical correctness (A4/A5/B1/B3 validators) | **A** | 100 % pass; deterministic, fast, well-characterised bypass surface |
| Semantic / design correctness (C1/C3 perspectives + adversarial) | **B+** | Catches all 4 OLD-v1 highs in case-6 — but is heuristic-driven and over-eager on substring matches |
| Iteration safety (A1/A2 regression guard, B4 meta-reviewer) | **B+** | Regression detection works; budget is finite; meta-reviewer dedup proven |
| Coverage-gap repair (B2, C2) | **B** | Fires + caps correctly; C2 fixture-resolution is only tested via mocked pytest output |
| Robustness / edge handling (D2 cache, D3 segmented rewriter, large/unicode/malformed inputs) | **A−** | 1000-citation verify in 0.9 s; 200×200 trace matrix in 23 ms; all unicode classes survive roundtrip |
| End-to-end spec quality on Mealie | **A−** | case-1: −80 % reviewer issues vs OLD v1; case-6: 0 critical regressions across A4/A5/B1/B3 |
| Production readiness | **B** | Mechanical defenses are production-grade; LLM-dependent paths (writer, reviewer prompts) still need real-API validation |

**Bottom line**: the system now blocks every mechanical failure mode that OLD v1 leaked (bad line ranges, JSON/MD drift, missing FR↔SC links, soft language), and the design-level defenses (C1 adversarial, C3 perspective auto-select) catch the rate-limit-ordering class of regressions that OLD v2 introduced. The honest bypass surface is documented per defense in §2.

---

## 2. Defense-by-defense findings

> Format: each defense lists what it is *designed* to catch, when it *does* fire, when it *does not* falsely fire, and the *boundary* — the bypass the adversarial tests surfaced.

### A1 — Rewriter regression guard
**Designed to**: detect iteration-to-iteration regression in `critical + high` issue counts and either force a regression-aware re-rewrite (up to `max_regression_retries=2`) or revert to the last-good iteration (`devloop/spec_phase/regression_guard.py`).

**Does fire correctly when**
- critical+high increases (e.g. 5→7) — `tests/unit/spec_phase/test_regression_guard.py:77-84`
- end-to-end loop marks `needs_review` after the regression-retry budget is spent — `tests/integration/test_regression_guard_e2e.py:6-16`
- last-good baseline is the *last good* iteration, not the v0 initial — `tests/integration/test_regression_guard_e2e.py:10-16`

**Does NOT trigger false positive when**
- counts drop (`:86-93`)
- critical+high stays flat while medium changes (`:95-102`)
- first iteration (no prior reference) (`:69-75`)
- `regression_feedback_message()` returns `""` on non-regression (`:153-158`)

**Boundary / limitation**
- Budget is finite; the orchestrator gives up after `max_regression_retries=2` (`:134-140`) and reverts. There is no "v3+" tournament — if v2 *and* v3 both regress, the system reverts to v1's last-good even if v2/v3 had fewer total issues but more critical+high.
- Severity-weighted only (`critical + high`). A rewrite that drops 1 critical and adds 5 medium *will not* trigger the guard but degrades overall spec health.

**Performance**: O(issues) per delta; negligible.

---

### A2 — Multi-iteration loop hardening
**Designed to**: prevent the orchestrator from collapsing to too-few iterations under slow convergence; pinned via `OrchestratorConfig.max_total_iterations >= 5` and `max_regression_retries >= 1`.

**Does fire correctly when**: default config violates the minimums — `tests/unit/spec_phase/test_regression_guard.py:161-167`.

**Does NOT trigger false positive when**: any config with cap ≥ 5 and retries ≥ 1 passes.

**Boundary / limitation**: A2 is a **configuration assertion**, not a runtime defense. There is no test that exercises "a customer sets `max_total_iterations=2` via YAML and the orchestrator still converges". If someone lowers the cap, A2 will not catch it at runtime.

**Performance**: N/A.

---

### A3 — (design-level) blocking-decision escalation in schema
**Designed to**: force input-vs-code conflicts to surface as top-of-spec `needs_clarification` (NC-001…) entries with `recommended_default` and `if_rejected` branches, instead of being buried in `self_concerns`. Implemented as a `BlockingDecision` pydantic model + `Spec.needs_clarification` field (`devloop/spec_phase/schemas/spec.py`).

**Does fire correctly when**: any writer-produced spec that uses `recommended_default` is validated and rejects soft phrasing (covered indirectly by A4 — `tests/unit/schemas/test_soft_language_adversarial.py:125-149` "to be decided"/"to be determined" in `BlockingDecision.recommended_default` / `if_rejected`).

**Does NOT trigger false positive when**: spec has no genuine conflict and `needs_clarification=[]` (verified by case-1 NEW v1: `NCs: 3`, all genuine product decisions).

**Boundary / limitation**: A3 is **schema scaffolding**, not a runtime detector. It cannot tell the writer *what* should be a `BlockingDecision` — it only refuses soft language *inside* one. If the writer hides a conflict in `self_concerns` instead of escalating to `needs_clarification`, A3 is silent. (This is exactly the failure mode observed in case-1 NEW v1's `EXEC-NEW-H-001` — see §3.1.)

**Performance**: N/A (schema validation).

---

### A4 — Soft-language pydantic validator
**Designed to**: reject vague/hedging phrases (`or equivalent`, `or similar`, `TBD`, `TBA`, `to be decided`, `to be determined`, `if needed`, `as needed`, `placeholder`) in every guarded field; allow backtick-quoted literals as an escape hatch.

**Does fire correctly when** (each at a distinct guarded field):
- `"or equivalent"` in `FunctionalRequirement.text` — `:90-99`
- `"or similar"` in `SuccessCriterion.threshold` — `:101-110`
- `"TBD"` in `SuccessCriterion.metric` — `:113-123`
- `"to be decided"` in `BlockingDecision.recommended_default` — `:125-136`
- `"to be determined"` in `BlockingDecision.if_rejected` — `:138-149`
- `"if needed"` in `Concern.suggested_resolution` — `:151-160`
- `"as needed"` in `Spec.summary` — `:163-170`
- `"TBA"` in `EdgeCase.handling` — `:173-180`
- `"placeholder"` in `Entity.description` — `:183-187`
- spec-wide scan via `detect_soft_language_in_spec_dict()` finds them all — `:322-393`

**Does NOT trigger false positive when**
- backtick-fenced literals (`` `TBD` ``) pass — `:209-237`
- `suggested_resolution=None` is skipped — `:250-263`
- case-insensitive matching catches variants — `:265-286`
- unguarded fields (`conflict`, `out_of_scope`) are intentionally ignored — `:322-393`

**Boundary / limitation found** (documented in file header `:3-7`)
- **Unicode homoglyph bypass**: `"оr equivalent"` (Cyrillic `о` U+043E) passes the substring check unchanged. No NFKC normalisation.
- **Zero-width-separator bypass**: `"if\u200Bneeded"` passes.
- **Parenthesised-middle-word / token-separator bypass**: `"if (genuinely) needed"` passes because the regex is exact-phrase, not lemma-level.
- **Pluralisation/stylistic bypass**: `"TBDs"`, `"if needed,"` (with trailing punctuation across token boundary) — only exact phrase matching is enforced (`:400-409`).

**Performance**: pure pydantic field-validator; sub-millisecond per spec.

---

### A5 — Citation verifier
**Designed to**: mechanically reject `code_references` whose file is missing, whose line range is out-of-bounds/reversed, or whose named symbol doesn't appear in the cited range. Orchestrator-level guard appends HIGH `executability` issues and marks `needs_review` after `citation_verify_max_attempts=3` attempts.

**Does fire correctly when**
- file missing → `PROBLEM_FILE_NOT_FOUND` — `tests/unit/validators/test_citation_verifier.py:83-91`
- start=0 / end > EOF / start>end — `:93-121`
- symbol absent from range — `:123-135`, `:155-176`
- multiple problems surface independently — `:205-217`
- spec-level aggregation attaches correct `fr_id` / `ref_index` — `:270-307`
- orchestrator injects HIGH issues + sets `needs_review` after max attempts — `tests/integration/test_orchestrator_citation_guard.py:350-412`

**Does NOT trigger false positive when**
- valid file/range/symbol passes — `:178-203`
- empty `symbols=[]` + empty `line_ranges=[]` is path-only — `:188-191`
- non-Python comments are searched verbatim — `:219-234`
- inline Python `#` trailing comments preserved — `:236-254`
- `..` normalised path inside repo passes — `tests/unit/validators/test_citation_adversarial.py:408-420`

**Boundary / limitation found** — adversarial tests revealed 6 distinct bypasses:
| Bypass | Test | Severity |
|---|---|---|
| Substring match is **syntactic-blind** (class vs def confusion) | `tests/unit/validators/test_citation_adversarial.py:79-93` | HIGH — false-positive verification |
| **Import-line false pass** — symbol cited but only its import line is in range | `:101-114` | MEDIUM |
| **Docstring false pass** | `:122-135` | MEDIUM |
| **Inline comment false pass** | `:143-157` | MEDIUM |
| **Symlink following** silently accepted | `:198-225` | LOW (test artifact mostly) |
| **Path traversal `..` escapes repo root** — NOT rejected, documented as a known limitation | `:353-398` | **HIGH — real security bug** |

**Performance**: 10 MB / 100 000-line file verifies in **< 5.0 s** (`tests/unit/validators/test_citation_adversarial.py:278-310`); 1000 references finish in **0.90 s** (`tests/integration/test_edge_stress.py` perf summary).

**Bugs revealed**: the path-traversal limitation (`:353-398`) is documented in-file as "**we do not fix bugs found here**" — it is a real defect, not adversarial-by-design. It should be on the next sprint backlog.

---

### B1 — MD ↔ JSON roundtrip drift detector
**Designed to**: catch any divergence between the rendered `spec.md` and the canonical `spec.json` — either via `assert_spec_roundtrip_consistent` (JSON→Spec→JSON byte-identical for normative fields) or `find_md_only_content` (every H2 markdown section must map to a normative Spec field).

**Does fire correctly when**
- markdown gets an extra `## ...` section absent from the Spec — `tests/unit/test_md_json_drift_adversarial.py:141-188`
- JSON writer silently drops `self_concerns` — `:195-231` (roundtrip raises and names the field path)

**Does NOT trigger false positive when**
- clean baseline roundtrips — `:127-134`
- writer footer (`_Generated by DevLoop…`) is tolerated — `:240-265`
- unicode / CJK / emoji survive roundtrip — `:273-340`
- empty optional sections / no user stories — `:348-377`

**Boundary / limitation**
- Footer text is explicitly non-normative — `find_md_only_content` scans only H2 (`:257-260`). A malicious writer could hide arbitrary content in an H3 outside any H2 and B1 would not flag it. No adversarial test exercises this.
- B1 only checks **structural** parity. If the writer renders `FR-007` in markdown with different wording than `FR-007.text` in JSON, B1 detects it (because the field is normative). If the writer adds a *non-normative* paragraph *inside* the FR section, B1 may not flag.

**Performance**: roundtrip on a 200-FR / 200-SC / 50-US spec runs in **8.6 ms** (perf summary `T-edge-very-large-spec-200-FRs.roundtrip`).

---

### B2 — Cross-perspective coverage-gap re-exploration
**Designed to**: detect when a critical artifact appears in only one of the 5 explorer perspectives (singleton-critical) and fire a targeted re-explorer to confirm or dispute it, capped at `max_targeted_reexplorations=3`.

**Does fire correctly when**
- singleton critical exists; re-explore fires; artifact appears in ≥ 2 perspectives after — `tests/integration/test_b2_coverage_gap_e2e.py:226-312`
- 10 singletons exist; only 3 re-explorers fire; audit artifact persisted — `:410-484`

**Does NOT trigger false positive when**
- well-covered exploration skips re-explore stage — `:320-403`

**Boundary / limitation**
- Re-explorer **failures are swallowed** — orchestrator logs a warning and returns the original exploration unchanged (`:498-556`). This is by design (graceful degradation) but means a flaky re-explorer can mask real gaps without anyone noticing.
- Cap of 3 is hard. If your spec genuinely has 10 singleton-critical gaps, 7 of them are silently un-re-explored.
- "Singleton" is defined by identity-string match across perspective outputs. Two perspectives referring to the same code at slightly different line ranges may be treated as singletons even though they cover the same artifact.

**Performance**: N/A (network-bound to LLM); cap is the budget control.

---

### B3 — Trace matrix (FR ↔ SC ↔ US)
**Designed to**: enforce every functional FR points to ≥ 1 SC, every SC is referenced by ≥ 1 FR, every P1 user story is claimed by ≥ 1 FR. Surfaced as orchestrator-injected `consistency` issues.

**Does fire correctly when**
- FR without SC — `tests/unit/validators/test_trace_matrix.py:119-130`, e2e `tests/integration/test_trace_matrix_e2e.py:291-302`
- SC without FR — `:132-148`, e2e `:305-322`
- P1 US without FR — `:220-233`, e2e `:325-339`
- unknown FR/SC reference ids reported — `:165-198`

**Does NOT trigger false positive when**
- clean bidirectional trace — `:107-117`, `:150-163`
- non-functional FR without SC is exempt — `:201-218`, `:413-425` (adversarial)
- P2 / P3 US without FR is exempt — `:235-246`, `:432-451` (adversarial)
- unknown US ids in `FR.related_user_stories` are out of scope — `:303-317`
- empty spec — `:298-301`

**Boundary / limitation** (the adversarial file `test_trace_matrix_adversarial.py` surfaced these)
- **Self-reference FR id as SC** produces both "unknown SC" and "FR without SC" — dangling-ref ordering is fixed but the duplication is a usability nit (`:119-151`)
- **Duplicate FR ids do not crash**; dedup is silent in the matrix and gaps may repeat (`:159-184`)
- **No normalisation**: trailing whitespace / case mismatch / empty refs are treated **literally**. `FR-001` ≠ `fr-001` ≠ `FR-001 ` (`:192-240`, `:248-323`). A writer using inconsistent casing across the spec would get spurious gaps.

**Performance**: 100×100 paired spec → **< 1.0 s**; 200×200 → **22.9 ms** (`T-stress-trace-200x200` in perf summary).

---

### B4 — Meta-reviewer (action consolidation)
**Designed to**: take the 4 (or 5 with C1) axis reviews, dedupe overlapping issues, produce a bounded prioritised action list (1..5) that the rewriter consumes — so the rewriter doesn't fix one axis and break another.

**Does fire correctly when**
- mock gateway returns valid MetaReviewResult; agent parses + fills `judge_model` — `tests/unit/agents/reviewers/test_meta_reviewer.py:242-303`
- zero-issue review renders prompt correctly — `:305-340`
- duplicate issues across reviewers dedupe to one merged action — `tests/integration/test_meta_reviewer_e2e.py:224-307`
- actions preserve priority order — `:314-406`
- `conflicts_with` surfaced in rewriter prompt — `:414-506`
- invalid first LLM response repaired by strict-JSON wrapper — `:483-513`
- meta-reviewer failure degrades gracefully, emits `meta_review_error`, rewriter still runs with raw issues — `:649-764`

**Does NOT trigger false positive when**
- meta disabled — `tests/integration/test_orchestrator_meta_review.py:486-556`
- meta failure → fallback to raw issues (no crash) — `test_meta_reviewer_e2e.py:649-764`
- empty MetaReviewResult valid by default — `:201-209`
- priority bounds 1..5 strict; out-of-range rejected — `:211-220`, `:379-409`
- invalid `affected_axes` rejected — `:222-235`

**Boundary / limitation** (adversarial `test_meta_adversarial.py`)
- `source_issue_ids=[]` and `affected_axes=[]` are **schema-permitted** but semantically odd — meta-reviewer can emit an action with zero traceability (`:417-455`)
- **Duplicate action ids are permitted** by schema — no `unique=True` constraint (`:457-490`)
- `conflicts_with` self-reference + unknown ids pass through and render finitely (`:492-558`)
- 20 issues → dedup yields 18 actions in fixture (`:304-371`) — dedup is best-effort, not exhaustive
- Cannot dedupe issues across iterations (only within a single iteration's 4 reviews)

**Performance**: N/A (LLM-bound); strict-JSON wrapper has 1 repair retry built in.

---

### C1 — Adversarial red-team reviewer (5th angle)
**Designed to**: gate a 5th reviewer whose prompt asks "imagine the spec is implemented literally — what attack works?". Selectively enabled by intent-scope (security/auth/external_integration/payment) or keyword (upload/openai/llm/password/pii/secret/image) heuristics; `force_adversarial=True` overrides up, `disable_adversarial=True` overrides down (kill switch).

**Does fire correctly when**
- security scope — `tests/unit/agents/reviewers/test_adversarial_reviewer.py:37-41`, e2e `tests/integration/test_adversarial_e2e.py:145-166`
- auth / external_integration / payment scope — `:43-62`
- upload / OpenAI / LLM / password / PII / secret / image keywords — `:69-108`
- explicit `force_adversarial=True` — `:156-171`
- combined risky intents end-to-end produce 5 reviewer calls — `tests/integration/test_adversarial_e2e.py:278-308`

**Does NOT trigger false positive when**
- plain backend / plain frontend intent — `:116-126`, `tests/integration/test_adversarial_e2e.py:169-188`
- no intent / empty intent — `:128-136`
- `disable_adversarial=True` vetoes even security scope (`:174-189`, `tests/integration/test_adversarial_e2e.py:211-228`)
- disable wins over force (`:192-205`); strips adversarial even when YAML lists it explicitly (`:231-258`)

**Boundary / limitation**
- **Substring matching is intentionally over-eager** — `"token-bucket"` triggers because `"token"` matches inside a larger word (`tests/unit/agents/reviewers/test_adversarial_selection.py:139-145`). Documented as accepted behaviour; cost is a wasted 5th LLM call on some unrelated specs.
- C1 is the **only defense** that catches case-6's `OLD-v2 rate-limit-ordering` regression (see `specs/case6-…/new_pipeline/COMPARISON.md:121-135` — "C1 is the primary defense here"). Without C1, A5/A4/B1/B3 would all pass a spec that consumes user quota on rejected requests.
- C1 is **heuristic-driven** for activation; if intent is mis-parsed, no fall-back fires.

**Performance**: 1 extra LLM round-trip per iteration when active (`tests/unit/agents/reviewers/test_adversarial_reviewer.py:3-8`, `:63-68`).

---

### C2 — Test-grounded executability (pytest --collect-only)
**Designed to**: extract `test_files`/`test_functions` from the spec and verify they're collectible by pytest. Catches `collect_error`/`import_error`/`syntax_error`/`fixture_not_found`.

**Does fire correctly when**
- syntactically broken stub flagged — `tests/integration/test_c2_test_collect_e2e.py:137-188`
- missing import → `import_error` — `:195-250`
- unknown fixture → `fixture_not_found` (via mocked pytest output) — `:253-336`
- no test refs ⇒ no subprocess, no scratch dir — `:339-385`

**Does NOT trigger false positive when**
- clean collectible stub — `:105-129`

**Boundary / limitation**
- **Fixture resolution is NOT exercised by real `pytest --collect-only`** — collection only parses; fixture availability is a runtime concept. The test honestly documents this and **mocks the subprocess output** to assert the *classifier* handles the string correctly (`:253-266`). Real-world spec referencing a non-existent fixture would not be caught at collection time; only at run time, which C2 does not exercise.
- `test_executability_max_attempts=2` (`OrchestratorConfig`) — same finite-budget limitation as A5.
- `test_executability_timeout_s=30` — large test trees may TIME-OUT and be falsely flagged.

**Performance**: short-circuits to zero subprocess when no test refs (`:339-385`); otherwise pytest startup ≈ 1–2 s.

---

### C3 — Perspective auto-selection
**Designed to**: select explorer perspectives from intent scope/keywords. Always includes base `data/api/test/history`; adds `ui`/`security`/`performance` when triggered.

**Does fire correctly when**
- ui scope / frontend scope ⇒ ui — `tests/integration/test_perspective_select_e2e.py:50-67`
- external_integration / upload / OpenAI ⇒ security — `:80-107`
- perf_opt intent / N+1 / latency / optimize / slow / performance / query count ⇒ performance — `:110-127`, `:209-220`
- combined risky intent enables all optionals — `:223-236`

**Does NOT trigger false positive when**
- backend-only intent does not add ui/security/performance — `:34-48`
- backend-only refactor excludes ui — `:70-78`
- explicit override returns exactly the supplied list, **with no auto-additions** — `:130-148`, `tests/unit/agents/test_perspective_selector.py:262-275`

**Boundary / limitation**
- **Explicit override bypasses even the always-included base perspectives** (`tests/integration/test_perspective_select_e2e.py:130-148`). If a customer passes `perspectives=[]` they get no exploration at all — silently. C3 trusts the override completely.
- The selector returns a mutable list but is asserted stateless (`tests/unit/agents/test_perspective_selector.py:288-300`) — caller mutation would not bleed across runs in the current code.
- Keyword matching is also substring-based (same caveat as C1): `"openaiwrapper"` triggers security because `"openai"` matches inside.

**Performance**: in-memory string match; sub-millisecond.

---

### D1 — (design-level) safety kill switches
**Designed to**: provide explicit `disable_*` flags (e.g. `ReviewerConfig.disable_adversarial`, `ExplorerConfig.use_cache=False`, `OrchestratorConfig.enable_meta_reviewer=False`) so the system can be partially turned off when a defense misbehaves in production.

**Does fire correctly when**
- `disable_adversarial=True` vetoes adversarial reviewer (covered by C1 tests at `:174-189`, `:192-205`, `:231-258`)
- `enable_meta_reviewer=False` skips meta call (covered by B4 tests at `tests/integration/test_orchestrator_meta_review.py:486-556`)
- `--no-explorer-cache` CLI flag bypasses cache (settings.py:48)

**Does NOT trigger false positive when**: any defense not explicitly disabled stays on.

**Boundary / limitation**
- D1 is not a **defense in itself** — it is the **operational escape hatch**. There is no test that proves every defense has a kill switch (some don't: A4 / A5 / B1 / B3 are always-on and cannot be disabled by config).
- No test verifies "all defenses on" vs "all defenses off" produces *measurably worse* output — i.e. no ablation harness.

**Performance**: N/A.

---

### D2 — Per-perspective explorer cache (commit-hash + intent-summary keyed)
**Designed to**: avoid re-running an expensive LLM exploration when the cache key (cwd_path, head_commit, perspective_type, intent_summary) matches a recent entry (TTL = `cache.ttl_days=7`).

**Does fire correctly when** (`tests/unit/agents/test_explorer_cache.py`): cache hit short-circuits the LLM call; cache miss runs the LLM and writes the entry; TTL expiry invalidates.

**Does NOT trigger false positive when**: `use_cache=False` bypasses (D1 kill-switch interaction).

**Boundary / limitation**
- Cache key uses `head_commit`. **Uncommitted local changes are not in the key** — running the explorer twice on the same commit with different working-tree state will return stale results. Documented in `devloop/cache.py`.
- No test exercises a poisoned cache entry (e.g. a malicious `intent_summary` hash collision).

**Performance**: cache hit is O(disk seek); miss is O(LLM round-trip).

---

### D3 — Segmented rewriter (opt-in)
**Designed to**: drive the spec rewrite as 5 validated LLM calls (head, stories, FRs, SCs, tail) instead of one ~30 KB single-shot call. Each segment validated against a partial schema; on failure, falls back to the previous spec's section. Currently `use_segmented_rewriter=False` by default.

**Does fire correctly when** (`tests/unit/agents/test_writer_segmented.py`): each segment produces partial JSON that validates against its partial schema; orchestrator stitches segments into a final Spec; failed segment falls back to the prior version.

**Does NOT trigger false positive when**: `use_segmented_rewriter=False` keeps the single-shot rewriter (default).

**Boundary / limitation**
- **Opt-in only** — the Mealie eval has not yet measured parity with the single-shot rewriter (`settings.py:108-110`). All 6 Mealie case re-runs in the OLD pipeline and both NEW-pipeline case re-runs used the single-shot path.
- No A/B harness verifies "segmented produces ≥ single-shot quality" — this is the documented gating concern.

**Performance**: 5× LLM round-trips instead of 1; expected latency multiplier ≈ 2–3× (smaller per-call context).

---

## 3. End-to-end pipeline quality (case-1 + case-6)

### 3.1 Case-1 (recipe favorites) — NEW v1 vs OLD v1

Source: `specs/case1-recipe-favorite-20260619T114933Z/new_pipeline/COMPARISON.md`.

| Severity | OLD v1 | NEW v1 | Δ |
|---|---|---|---|
| Critical | **5** | **0** | **−5** ✅ |
| High | **14** | **2** | **−12** ✅ |
| Medium | 17 | 5 | −12 |
| Low | 0 | 0 | 0 |
| **Total reviewer issues** | **36** | **~7** | **−80 %** |

Validators on NEW v1 spec.json:
```
A4 schema validation: PASS (no soft language)
A5 citation verifier: 0 problems (across 50+ refs)
B3 trace gaps:        0 gaps
B1 roundtrip:         PASS
```

**Defects PREVENTED** (cited IDs from `COMPARISON.md:75-96`):

| OLD-v1 defect ID | Mechanism that caught it |
|---|---|
| COMP-C-001 (i18n absent) | C3 perspective auto + input-verbatim writer rule → NEW FR-014 + SC-008 |
| COMP-C-002 (no service layer) | input-verbatim + B3 trace → NEW FR-012 + SC-013 |
| COMP-C-003 (table-vs-reuse buried) | A3 BlockingDecision schema → NEW NC-001 |
| CONS-C-001 (US-3 contradiction) | A3 + A4 (no "decide later" allowed in `recommended_default`) → NEW NC-002 |
| EXEC-C-001 (compat deferred) | A3 → NEW NC-002 + FR-006 |
| ARCH-H-001 (anon path wrong) | A5 citation verifier → NEW FR-010 cites correct `controller_public_recipes.py:17-31` |
| ARCH-H-002 (column_aliases is wrong) | A5 → NEW FR-008 explicitly forbids that mechanism |
| ARCH-H-003 (asymmetric cleanup) | A5 → NEW FR-015 + FR-016 split |
| COMP-H-001..005 | A5 / B3 / input-verbatim — all 5 resolved |
| CONS-H-001 (FR-007 forbids anon count) | A4 + schema scoping |
| CONS-H-002 (cascade FR missing) | B3 trace → NEW FR-015 + FR-016 |
| EXEC-H-001..004 (wrong line ranges / md-json drift) | **A5 + B1** — structurally impossible in NEW (B1 derives md from json mechanically) |

**Defects NOT prevented (NEW v1's own ~2 highs)**:
- `ARCH-NEW-H-001`: FR-010 leaves the implementer choosing between two route paths — could have escalated to NC but writer chose self_concerns (A3 silent failure mode)
- `EXEC-NEW-H-001`: FR-008 enumerates 3 hydration shapes; writer surfaced as self_concern instead of escalating. **A future "≥ 3 options ⇒ escalate" rule would close this** (called out in COMPARISON.md:169).

**Would a downstream code agent ship correct code from NEW v1?**
- 17/19 FRs are unambiguous + cited + measurable.
- The 2 remaining highs are deliberately surfaced as self_concerns — a code agent would need to make 2 implementation choices, both of which are documented within the spec.
- Verdict: **probably yes for 80 % of the feature**, with 2 architectural decisions still requiring an explicit choice. This is a substantial improvement over OLD v1, which required 5 critical clarifications before any code could ship.

---

### 3.2 Case-6 (LLM image-to-recipe; security-heavy) — NEW v1 vs OLD v1 + v2

Source: `specs/case6-llm-image-recipe-20260619T124400Z/new_pipeline/COMPARISON.md`.

| Severity / class | OLD v1 | OLD v2 | NEW v1 |
|---|---|---|---|
| Critical | 0 | 0 | 0 |
| High | 4 | 1 NEW + 1 carry-over | 0 |
| Medium | 4 | 3 NEW + 1 carry-over | 0 |
| Low | 1 | 0 | 0 |
| Validators failing (A4+A5+B1+B3) | n/a | n/a | **0** |
| Manual reviewer-found citations errors | 1 (EXEC-V2-2 line 358 vs 450) | 1 | 0 |

**Defects PREVENTED** (most important is the `OLD v2 NEW HIGH regression`):

| OLD defect | NEW defense | NEW spec evidence |
|---|---|---|
| v1 H-1 DEBUG-level leak in `_base.py:33-34` | C1 adversarial + C3 security | NEW FR-019 mandates rewriting `_base.py:33-34` |
| v1 H-2 `exc_info=True` re-leaks upstream | C1 | NEW FR-018 mandates `from None` |
| v1 H-3 in-memory rate-limit on multi-worker | C1 | NEW FR-004 AND-gates with `WORKERS==1`; NEW FR-011 hard-disables multi-worker; NEW NC-003 escalates |
| v1 H-4 auth-vs-feature-gate ordering | B3 + C1 | NEW FR-025 publishes the 7-step precedence chain |
| v1 M-1 `Path(image.filename).name` traversal | C1 + C3 | NEW FR-009 mandates UUID temp file |
| v1 M-2..M-4 MIME / timeout / per-call model | C1 | NEW FR-007/008/012/005 |
| v1 L-1 i18n | completeness | NEW FR-020 |
| **OLD v2 rate-limit-before-validation HIGH regression** | **C1 adversarial** (primary defense) + B3 trace `FR-011 ↔ SC-005` | NEW FR-011 + FR-025 + SC-005 |
| OLD v2 M-1 multipart Content-Length confusion | C1 + A5 (forced writer to open multipart code) | NEW FR-006 |
| OLD v2 M-2 service raises HTTPException | C1 + repo-convention check | NEW FR-016 + FR-021 + FR-002 |
| OLD v2 M-3 sync Pillow not preempted by timeout | A5 + C1 | NEW FR-012 |
| OLD v2 EXEC-V2-2 wrong line citation | **A5 mechanical** | 0 citation problems across 47 references |

**Cross-cutting additions NEW produced that OLD v1+v2 never had**:
- Explicit 7-step precedence chain as its own FR-025 (single source of truth)
- Prompt-injection FR-017 (system/user message separation)
- 3 explicit `needs_clarification` blocks (NC-001 persist-vs-draft, NC-002 filetype-vs-magic, NC-003 in-process vs DB-backed rate-limit)
- 4 structured `self_concerns` (Pillow CVE note, `_base.py` global-scope leak callout)
- 12 edge cases each phrased to map to an acceptance test

**Defects NOT prevented**: none in this case — the 4 OLD-v1 highs + 1 OLD-v2 regression were all blocked. The case is an unusually clean win because case-6's defect class (security/ordering) is the canonical target of C1+C3.

**Would a downstream code agent ship correct code from NEW v1?**
- All 4 mechanical validators clean.
- The 3 needs_clarification blocks are **explicit product questions** that any responsible code agent must escalate to a human (NC-001: persist drafts? NC-002: which magic-byte lib? NC-003: scale to multi-worker?). The NEW pipeline does the right thing — refuse to guess.
- Verdict: **yes, modulo the 3 explicit human-decision blocks** — exactly the behaviour we want.

---

## 4. System characteristics measured

### Test counts (commits in this wave)
| Milestone | Tests | Source |
|---|---|---|
| Pre-Sprint A baseline | 95 | CROSS_CASE_FINAL_REPORT.md:178 |
| Post-Sprint A–D (15 defenses landed) | 347 | per prompt context (not re-measured here) |
| Post capability-boundary wave (this wave) | **470** | `pytest --collect-only -q` |
| Net new tests in this wave | **≈ 123** | across 11 new test files |

### Pass / fail / runtime
```
Result: 470 passed in 22.96s (pytest -q --tb=no)
Exit code: 0
No xfail, no skip
```

### Lint
```
ruff check devloop tests : 2 errors  (RUF059 unused tuple unpack in tests/integration/test_perspective_select_e2e.py:719)
ruff check . (includes specs/case6-… scratch script) : 8 errors total
```

### Spec-validation performance (perf summary from `test_zzz_performance_summary`)

| Scenario | Time |
|---|---|
| Empty / minimal spec — full validation | 0.27 ms |
| 50-FR / 50-SC spec — pydantic validate | 0.77 ms |
| 50-FR / 50-SC spec — `find_trace_gaps` | 0.17 ms |
| 50-FR / 50-SC spec — md⇄json roundtrip | 2.39 ms |
| 200-FR / 200-SC / 50-US spec — `find_trace_gaps` | 0.60 ms |
| 200-FR / 200-SC / 50-US spec — md⇄json roundtrip | **8.62 ms** |
| 100 blocking decisions — render + roundtrip | 2.04 ms |
| 50 deep nested acceptance scenarios | 0.40 ms |
| Unicode (CJK + emoji + Arabic) on every text field | 1.62 ms |
| Empty strings in optional text fields | 0.17 ms |
| **Citation verifier — 1000 code references** | **895.62 ms** |
| Trace matrix — 200×200 paired | 22.86 ms |
| Malformed JSON × 3 (missing field, unknown field, truncated) | 5.35–6.52 ms each |

Citation verifier on a 10 MB / 100 000-line single file: **< 5.0 s** (`tests/unit/validators/test_citation_adversarial.py:278-310`).

### Memory
No explicit memory limit was exceeded. The 200×200 trace matrix and the 1000-citation verify both fit in default test-process memory. No `MemoryError` surfaced across 470 tests. **Untested**: a single spec with > 200 FRs and per-FR `code_references` lists ≥ 100; cumulative could push 100 000+ refs.

### Token consumption
- No real LLM calls in this wave (all `MockProvider` per `test_edge_stress.py:10-11`).
- D3 segmented rewriter would emit **5× LLM round-trips** per rewrite vs single-shot (`devloop/spec_phase/agents/writer.py:246`).
- C1 adversarial reviewer adds **1 LLM round-trip per iteration** when active (`test_adversarial_reviewer.py:3-8`).
- Effective per-iteration LLM count when all defenses active: writer (1) + 5 explorers (5, B2 may add up to 3 more) + 4–5 reviewers (4 + C1) + B4 meta-reviewer (1) + rewriter (1 or 5) = **15 → 24 LLM round-trips per iteration**.

---

## 5. Capability boundaries — clearly stated

### What the system DEFINITELY CAN
- **Detect every soft-language phrase from a 9-token blacklist** in 9 guarded schema fields (A4 — `test_soft_language_adversarial.py:90-187`).
- **Verify 1000 code references against a real repo in < 1 s** (A5 — perf summary `T-stress-citation-1000-refs = 895.62 ms`).
- **Detect spec.md ↔ spec.json drift by construction** for normative fields and H2 section parity (B1 — `test_md_json_drift_adversarial.py:141-231`).
- **Detect orphan FR/SC and unclaimed P1 US in a 200×200 spec in < 25 ms** (B3 — perf summary).
- **Dedupe overlapping issues across the 4 axis reviewers into a bounded action list and recover from a single malformed LLM response** (B4 — `test_meta_reviewer.py:483-513`).
- **Gate a 5th adversarial reviewer based on intent scope + keywords** and provide a hard kill switch that wins over both the heuristic and explicit force (C1 — `test_adversarial_reviewer.py:174-189`, `:192-205`).
- **Detect singleton-critical artifacts across 5 explorer perspectives and fire up to 3 targeted re-explorations** (B2 — `test_b2_coverage_gap_e2e.py:226-484`).
- **Survive unicode (CJK / Arabic / emoji) in every text field through full validation + roundtrip** (`test_edge_stress.py:532-623`).
- **Eliminate the OLD pipeline's spec.md/spec.json drift class of bugs** (case-1: OLD-v1 EXEC-H-003 → structurally impossible in NEW).
- **Block the OLD pipeline's rate-limit-before-validation regression class** when C1+C3 fire (case-6: OLD-v2 NEW-HIGH → NEW v1 has 0 occurrences).
- **Self-correct in one rewrite pass when given honest reviewer feedback** (case-1 OLD: −61 % issues v1→v2; CONVERGENCE_REPORT_v2.md:5-15).

### What the system PROBABLY CAN
- **Produce a v1 spec good enough for a code agent to ship 80 % of a CRUD feature** (case-1 NEW v1: 0 criticals, 2 highs that are honestly self-surfaced design choices).
- **Catch design-level security regressions for upload/LLM/auth features** when intent triggers C1+C3 (case-6 evidence; not yet replicated on a NON-security feature where C1 didn't fire).
- **Scale to 200-FR specs without performance cliff** — all measured under 25 ms at 200×200 (`T-edge-very-large-spec-200-FRs`).
- **Run multiple iterations without monotonic-improvement guarantee** — A1 detects regression and reverts; A2 keeps the budget generous; but the system can still emit v2-worse-than-v1 on rare paths (case-6 OLD pipeline showed this; NEW pipeline has not been stress-tested for v3+).

### What the system DEFINITELY CANNOT
- **Detect Unicode-homoglyph soft-language bypass** — `"оr equivalent"` (Cyrillic `о`) passes A4 unchanged. No NFKC normalisation (`test_soft_language_adversarial.py:3-7` header).
- **Detect zero-width-separator bypass** — `"if\u200Bneeded"` passes A4.
- **Detect path-traversal in `code_references.file`** — `../../../etc/passwd` is NOT rejected by A5. **Real security defect**, documented at `test_citation_adversarial.py:353-398`.
- **Distinguish class vs def vs import vs docstring vs comment** when verifying a cited symbol — A5 substring match passes if the symbol name appears *anywhere* in the cited range, including an import line (`test_citation_adversarial.py:79-157`).
- **Catch trailing-whitespace / case-mismatch in FR/SC ids** — B3 treats refs literally; `FR-001` ≠ `fr-001` ≠ `FR-001 ` produces spurious gaps (`test_trace_matrix_adversarial.py:192-323`).
- **Force the writer to escalate "≥ 3 options for a single FR" to a NEEDS_CLARIFICATION** — A3 schema is silent; the writer can hide the choice in self_concerns (case-1 NEW v1's EXEC-NEW-H-001 + ARCH-NEW-H-001 are exactly this failure mode).
- **Prevent prompt injection** without an explicit guard FR — the system relies on the writer including FR-017-style separation; there is no orchestrator-level prompt-injection sanitiser.
- **Catch a non-collectible fixture at pytest --collect-only time** — pytest only parses, not runs fixtures; C2 mocks the failure rather than reproducing it (`test_c2_test_collect_e2e.py:253-266`).
- **Recover from re-explorer failures with anything other than "log + return original"** (B2 — `test_b2_coverage_gap_e2e.py:498-556`).

### What the system REMAINS UNTESTED FOR
- **Real-API LLM runs** — every test in this wave uses `MockProvider`. The Python `anthropic_provider.py` / `openai_provider.py` paths are validated only by unit tests. The 6 Mealie case re-runs (CROSS_CASE_FINAL_REPORT.md:23) ran via Copilot CLI sub-agents, NOT the Python orchestrator with real keys.
- **D3 segmented rewriter on a real feature** — has unit-level partial-schema tests but no Mealie eval (`settings.py:108-110`).
- **v3+ iterations** — A1 regression guard caps at 2 retries; no Mealie case has gone past v2 in either OLD or NEW pipeline.
- **Ablation harness** — no test proves "all defenses on" vs "all defenses off" produces measurably better specs. Claims of −80 % issue reduction are vs the OLD-pipeline writer's own v1, which is correlation not causation.
- **Single-LLM single-pass baseline** — no comparison of NEW v1 vs a pure Opus 4.7 / GPT-5.5 one-shot spec.
- **Cumulative ref count > 1000 in a single spec** — perf was measured at 1000 refs; behaviour at 10 000+ refs is extrapolated.
- **D1 ablation matrix** — no test verifies that every defense has a working kill switch; A4/A5/B1/B3 are always-on with no off-flag.
- **D2 cache poisoning** — no adversarial test for cache key collisions or stale `head_commit` interactions with uncommitted changes.
- **A5 path-traversal fix** — the bypass is documented but no fix is shipped.

---

## 6. Production readiness verdict

### Grades by dimension

| Dimension | Grade | Justification |
|---|---|---|
| Mechanical validators (A4/A5/B1/B3) | **A** | 100 % pass; deterministic; sub-second on 200-FR specs; well-mapped bypass surface; 0 critical+high in case-1/6 NEW v1 |
| Schema scaffolding (A3 BlockingDecision) | **B** | Forces escalation when used; cannot force the writer to *use* it (case-1 NEW v1 EXEC-NEW-H-001 demonstrates the silent-bypass) |
| Iteration safety (A1 + A2) | **B+** | Guard works on `critical+high`; severity-weighted; no escape for "−1 C +5 M" trades |
| Coverage repair (B2) | **B** | Fires + caps correctly; failures are swallowed-by-design which is both correct and risky |
| Reviewer consolidation (B4) | **B+** | Dedup works; degrades gracefully; schema permits zero-traceability actions |
| Adversarial security review (C1) | **A−** | Primary defense for case-6's marquee bug; substring matching causes occasional false-positive activations (cheap cost) |
| Executability check (C2) | **C+** | Limited by what pytest --collect-only can actually detect; fixture path is mocked-only |
| Perspective auto-select (C3) | **A−** | Heuristic but well-covered; explicit override is a foot-gun (silently allows `[]`) |
| Kill switches (D1) | **B−** | Exists for some defenses (adversarial / meta-reviewer / cache) but NOT for A4/A5/B1/B3 |
| Explorer cache (D2) | **B** | Works for committed state; silently stale on uncommitted working trees |
| Segmented rewriter (D3) | **C** | Opt-in; no Mealie-scale eval yet — explicitly gated on parity measurement |
| Robustness (edge / unicode / large) | **A** | All measured under generous budgets; full unicode roundtrip; 1000-ref verify in 0.9 s |
| End-to-end spec quality on case-1 (CRUD) | **B+** | 0 criticals, 2 highs (both surface-able as NEEDS_CLARIFICATION with one more defense rule) |
| End-to-end spec quality on case-6 (security) | **A−** | 0 criticals, 0 highs across the 4 mechanical validators; OLD v2 regression eliminated |
| Production handoff to a code agent | **B** | NEW v1 is materially better than OLD v1, but real-API runs are unverified and ablation evidence is missing |

### Top 3 things still needed for production

1. **Fix A5 path-traversal**. `code_references.file = "../../../etc/passwd"` must be rejected. Documented in `test_citation_adversarial.py:353-398` as a known defect — close it before shipping to any external customer.
2. **Real-API end-to-end run of the Python orchestrator on at least 2 of the 6 Mealie cases.** Every defense currently has unit + integration coverage with `MockProvider`. The provider classes themselves are tested but the *combined writer→reviewer→rewriter loop* under a real Anthropic + GPT pair has never been exercised in this codebase.
3. **Add an "≥ 3 options for a single FR ⇒ escalate to NEEDS_CLARIFICATION" rule (A3 strengthening).** This is the only case-1 NEW v1 high (EXEC-NEW-H-001) and the same shape recurs across 6 OLD-pipeline cases. The fix is a writer-prompt rule + a soft-validator that counts "or"/"either"/"option" in a single FR.text.

### Honest comparison to "no DevLoop" baseline

| Metric | Single-LLM single-pass writer (no defenses) | DevLoop NEW pipeline | Δ |
|---|---|---|---|
| Bad line-range citations per 50 refs | ≥ 4 typical (OLD v1 EXEC-H-001..004) | 0 (A5 mechanical) | **bounded to 0** |
| spec.md ↔ spec.json drift fields | ≥ 5 typical (OLD v1 EXEC-H-003) | 0 (B1 construction) | **structurally impossible** |
| Soft-language phrases in FRs | ≥ 1 typical (OLD v2 "or equivalent" survived rewrite) | 0 (A4 always-on) | **bounded to 0** |
| Orphan SCs / unclaimed P1 USs | ≥ 1 typical (OLD v1 CONS-H-002) | 0 (B3 always-on) | **bounded to 0** |
| Security-feature highs per case (e.g. rate-limit ordering) | 4 in OLD v1 case-6, +1 NEW HIGH in OLD v2 | 0 in NEW case-6 v1 | **−5 case-6 highs** |
| Latency (single iteration, MockProvider) | ~1 LLM call | 15–24 LLM calls | **15-24× LLM cost** |
| End-to-end issue count reduction (case-1 v1) | baseline (36 issues) | 7 issues | **−80 %** |

DevLoop trades **~15× LLM cost** for **structurally impossible** failures in 4 of the OLD pipeline's top-5 defect classes, plus **heuristic-but-effective** coverage of the remaining design-level class (security/ordering). For features where the writer is well-prompted, single-pass *may* match NEW v1 by luck; over 6 Mealie cases, the OLD pipeline averaged 0/6 APPROVE on first pass (CROSS_CASE_FINAL_REPORT.md:33-38).

---

## 7. Specific issues / regressions found during this test wave

### Real bugs (not adversarial-by-design)
1. **A5 path-traversal** — `tests/unit/validators/test_citation_adversarial.py:353-398` documents that `code_references.file = "../something"` escapes the repo root and is silently accepted. This is a **real security defect**, not a synthetic adversarial probe. The test file header `:10` explicitly says "we do not fix bugs found here". Action: fix in next sprint.
2. **Ruff 2 errors** — `tests/integration/test_perspective_select_e2e.py:719` has 2 unused tuple unpack variables (`a_prov`, `o_prov`). Cosmetic; pre-existed before this wave or introduced by it — needs underscore prefix. (3 additional ruff errors in `specs/case6-…/new_pipeline/run_validators.py` are in a scratch helper file that doesn't ship; should still be fixed.)

### Sub-agent reports of partial coverage (not failures, but disclosed limits)
- **C2 fixture resolution is mocked** — `tests/integration/test_c2_test_collect_e2e.py:253-266` explicitly mocks pytest's subprocess output because `pytest --collect-only` does not invoke fixtures. Honest but means real fixture-resolution failures would slip through.
- **D3 segmented rewriter has no Mealie eval** — `settings.py:108-110` explicitly gates production default on parity measurement that has not happened.

### Test-wave runtime observations
- 5 perf tests in `test_edge_stress.py` produce the perf summary table; all five pass on their budgets, but **the test_zzz_performance_summary printer asserts `assert PERF`** — when run in isolation via `-k test_zzz_performance_summary` it fails with "no perf measurements were recorded" because the earlier tests didn't run. This is **not a bug** but it is a usability foot-gun (perf table only emits when the full file is run). Discovered during this report's preparation.

### Defenses that did NOT regress in this wave
- All 13 directly-tested defenses (A1, A2, A4, A5, B1, B2, B3, B4, C1, C2, C3, D2, D3) pass their entire adversarial + e2e test suites with 0 unexpected failures.
- A3 + D1 are design-level / configuration-level defenses and don't have discrete fire-tests; they're exercised indirectly through A4 (A3) and through C1/B4/D2 disable flags (D1).

### What the sub-agents flagged for follow-up (paraphrased from their reports)
- (analyze-A) A4 has 4 documented bypass classes (homoglyph, zero-width, parenthesised middle, pluralisation) — none fixed.
- (analyze-A) A5 has 6 documented bypass classes — path-traversal is the only one that's a real security issue.
- (analyze-B) B3 lacks normalisation — could be one config flag.
- (analyze-B) B4 schema permits semantically odd states (empty source_issue_ids, duplicate action ids).
- (analyze-C) C1 + C3 substring matching is intentionally over-eager — accepted trade-off, but documents the pattern.
- (analyze-edge) no test exists for D2 cache poisoning; no D1 ablation matrix.

---

## Appendix: defense → test-file index (for traceability)

| Defense | Primary unit test | Adversarial test | E2E / integration test |
|---|---|---|---|
| A1 Regression guard | `tests/unit/spec_phase/test_regression_guard.py` | — | `tests/integration/test_regression_guard_e2e.py` |
| A2 Multi-iter cap | `tests/unit/spec_phase/test_regression_guard.py:161-167` | — | — |
| A3 BlockingDecision | (schema) `tests/unit/schemas/test_all.py` | covered indirectly by A4 | — |
| A4 Soft language | `tests/unit/schemas/test_soft_language_validator.py` | `tests/unit/schemas/test_soft_language_adversarial.py` | — |
| A5 Citation verifier | `tests/unit/validators/test_citation_verifier.py` | `tests/unit/validators/test_citation_adversarial.py` | `tests/integration/test_citation_verifier_e2e.py`, `tests/integration/test_orchestrator_citation_guard.py` |
| B1 MD-JSON | `tests/unit/test_md_json_bridge.py` | `tests/unit/test_md_json_drift_adversarial.py` | — |
| B2 Coverage gap | (validator) `tests/unit/validators/test_coverage_gap_detector.py` | — | `tests/integration/test_b2_coverage_gap_e2e.py`, `tests/integration/test_orchestrator_targeted_reexplore.py` |
| B3 Trace matrix | `tests/unit/validators/test_trace_matrix.py` | `tests/unit/validators/test_trace_matrix_adversarial.py` | `tests/integration/test_trace_matrix_e2e.py` |
| B4 Meta-reviewer | `tests/unit/agents/reviewers/test_meta_reviewer.py` | `tests/unit/agents/reviewers/test_meta_adversarial.py` | `tests/integration/test_meta_reviewer_e2e.py`, `tests/integration/test_orchestrator_meta_review.py` |
| C1 Adversarial | `tests/unit/agents/reviewers/test_adversarial_reviewer.py`, `test_adversarial_selection.py` | (selection embedded) | `tests/integration/test_adversarial_e2e.py` |
| C2 Test executability | `tests/unit/validators/test_test_executability.py` | — | `tests/integration/test_c2_test_collect_e2e.py` |
| C3 Perspective select | `tests/unit/agents/test_perspective_selector.py` | — | `tests/integration/test_perspective_select_e2e.py` |
| D1 Kill switches | covered indirectly by C1/B4/D2 | — | — |
| D2 Explorer cache | `tests/unit/agents/test_explorer_cache.py` | — | — |
| D3 Segmented rewriter | `tests/unit/agents/test_writer_segmented.py` | — | — |
| Edge / stress | — | — | `tests/integration/test_edge_stress.py` |

---

*End of report. Reproduce numbers with: `pytest -q --tb=no` (470 / 22.96 s), `ruff check devloop tests` (2 errors), `pytest tests/integration/test_edge_stress.py -s` (perf table).*
