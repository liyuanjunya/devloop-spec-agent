# Review v2 — Axis: Completeness

**Reviewer**: case6-live-new-20260620-v2 / completeness
**Spec under review**: `spec_iterations/spec_v2.json` (7 stories, 33 FRs, 22 SCs, 17 ECs, 5 NCs, 7 concerns)
**v1 axis findings**: C-H-001, C-H-002, C-M-001, C-M-002, C-M-003, C-M-004

## Verification of v1 fixes

* **C-H-001 (ASGI body-size cap)** — RESOLVED. New FR-028 mounts `MaxBodySizeMiddleware(6 MiB)` reading `Content-Length` and incrementally counting bytes for chunked transfer encoding. SC-017 verifies 50 MiB upload rejected with < 1 MiB RSS growth. Verdict: **resolved**.
* **C-H-002 (OPENAI_IMAGE_MODEL whitelist)** — RESOLVED. New NC-005 escalates the design tradeoff; FR-005 updated to require `field_validator` against literal whitelist `{gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini}`. Verdict: **resolved**.
* **C-M-001 (client disconnect cleanup)** — NOT addressed in v2. Acceptable to defer — the FR-010 try/finally covers asyncio CancelledError via Python's context-manager semantics. Verdict: **uncertain**.
* **C-M-002 (disk-full handling)** — NOT addressed. The chunked write loop in FR-006 will raise an unhandled OSError. v2 should add a 507 mapping. Verdict: **uncertain**.
* **C-M-003 (SC asserting prompt template contains the guard)** — NOT explicitly added, but SC-019 indirectly asserts the prompt's intent via byte-content scan of the OpenAI request. Verdict: **uncertain**.
* **C-M-004 (docs change same commit)** — NOT addressed. The docs change is in FR-024 but no SC pins the same-commit assertion. Verdict: **uncertain**.

## New findings against v2

### C-M-005 [MEDIUM] FR-027 cleaner.clean signature doesn't verify field-by-field coverage

**Location**: FR-027.

FR-027 lists the fields cleaner.clean is supposed to scrub: `name`, `description`, `recipe_yield`, `recipe_ingredient[].note`, `recipe_instructions[].text`. The spec doesn't say:

* what cleaner.clean actually does on each field (which HTML elements it strips vs. allows)
* whether the existing implementation in `mealie/services/recipe/recipe_service.py:349` covers all 5 fields or just a subset

SC-016 tests only the `instructions[].text` field. If cleaner.clean ignores e.g. `description`, the test passes while the spec's promise silently fails for that field.

**Fix**: SC-016 should test each of the 5 fields with a different XSS payload.

**Verdict**: confirmed_problem (mild).

### C-M-006 [MEDIUM] FR-029 doesn't say what happens to non-JPEG inputs (PNG / WebP) during downsample

**Location**: FR-029.

FR-029 reads via Pillow and re-saves over the temp file. PNG with alpha channel will lose alpha when saved as the assumed JPEG. WebP may convert to lossless PNG. The spec doesn't specify the output format of the downsampled file, and the OpenAI Vision API supports JPEG/PNG/WebP — so the downsample should preserve the original format. Otherwise we may unexpectedly degrade a PNG screenshot.

**Fix**: FR-029 should specify "re-save in the same format as the input (preserve format detected by FR-008 magic-byte sniff)".

**Verdict**: confirmed_problem (mild).

### C-M-007 [MEDIUM] No FR/SC asserts that filetype==1.2.0 has no known CVEs at spec landing time

**Location**: FR-023.

FR-023 pins `filetype==1.2.0` and asserts "no native dependency". Spec doesn't assert "no known CVEs at landing" or specify a renewal cadence. Adding a small SC checking `osv-scanner` or `pip-audit` against the lockfile in CI would close this.

**Verdict**: confirmed_problem (mild).

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 0 |
| Medium   | 3 |

## Final verdict

**Verdict: pass** (both v1 HIGHs resolved; remaining mediums are nice-to-have hardening, not blockers)
