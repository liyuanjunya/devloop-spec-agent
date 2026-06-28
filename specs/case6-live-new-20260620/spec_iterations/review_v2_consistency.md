# Review v2 — Axis: Consistency

**Reviewer**: case6-live-new-20260620-v2 / consistency
**Spec under review**: `spec_iterations/spec_v2.json` (7 stories, 33 FRs, 22 SCs, 17 ECs, 5 NCs, 7 concerns)
**v1 axis findings**: Y-H-001 (rate-limit ownership), Y-H-002 (cleaner.clean unsourced), Y-M-001 (EC-04 error class), Y-M-002, Y-M-003, Y-M-004

## Verification of v1 fixes

* **Y-H-001 (rate-limit ownership)** — RESOLVED. FR-016 + FR-011 now consistently assign the limiter to the orchestrator. FR-025 ordering shows step 9 (orchestrator reserve_attempt) AFTER all input validation. Verdict: **resolved**.
* **Y-H-002 (cleaner.clean unsourced)** — RESOLVED. New FR-027 explicitly invokes `cleaner.clean(recipe_data, self.translator)` between `_convert_recipe` and `create_one`, with citation to the line-349 call site that proves the existing utility works on the same recipe_data shape. FR-017 in v2 now disclaims XSS sanitization and explicitly defers to FR-027 + Layer 3 (EXIF strip via FR-031). Verdict: **resolved**.
* **Y-M-001 (EC-04 error class)** — NOT explicitly addressed but FR-018 in v2 now lists `PIL.UnidentifiedImageError -> recipe.image.image-decode-failed` as a distinct branch. EC-04 still maps to openai-failed in the v1 text inherited into v2; recommend updating EC-04 in a follow-up. Verdict: **uncertain**.
* **Y-M-002 (orchestrator vs service terminology)** — NOT explicitly addressed but FR-016 in v2 now clarifies that "orchestrator" == "service" by saying "the orchestrator (service) owns ...". Verdict: **resolved**.
* **Y-M-003 (size-cap ordering contradiction)** — RESOLVED via Y-H-001 fix. Verdict: **resolved**.
* **Y-M-004 (translate_language API break)** — NOT addressed. Out-of-scope item still says deferred. Verdict: **uncertain**.

## New findings against v2

### Y-M-005 [MEDIUM] EC-04 (corrupted JPEG) still maps to `recipe.image.openai-failed` but FR-018 in v2 now distinguishes a separate `recipe.image.image-decode-failed` branch

**Location**: EC-04 (carried from v1) vs FR-018 (rewritten in v2).

The two are inconsistent now: FR-018 in v2 says PIL.UnidentifiedImageError maps to image-decode-failed, but EC-04 still says it maps to openai-failed. The handling description should be updated.

**Fix**: edit EC-04 to read "... raises `OpenAIServiceError('recipe.image.image-decode-failed') from None` ..." instead of openai-failed.

**Verdict**: confirmed_problem (mild). Spec carries over an obsolete handling note.

### Y-M-006 [MEDIUM] FR-025 step 7 (downsample) and step 8 (EXIF strip) run BEFORE the rate-limit at step 9, but downsampling can be expensive (decoding a large JPEG is non-trivial)

**Location**: FR-025 step ordering.

A 5 MiB JPEG decoding to 8192x8192 takes ~100ms of CPU on a typical server. If steps 7+8 run before the rate-limit check, an attacker who has been rate-limited can still trigger 100ms of CPU per attempt (within their 30/hour attempts quota). This is a small CPU-DoS amplifier. Alternative: run the rate-limit check FIRST (step 7) before the expensive normalization, then downsample/strip-EXIF only on accepted attempts.

This is a defensible design tradeoff (rate-limit-first means a malicious user could lock themselves out by hitting the cap with cheap requests then can't even submit large legit images), but the spec doesn't acknowledge the tradeoff.

**Verdict**: uncertain. Could be marked as a self-concern.

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 0 |
| Medium   | 2 |

## Final verdict

**Verdict: pass** (both v1 HIGHs resolved; remaining mediums are minor consistency-drift items from carried-over v1 text)
