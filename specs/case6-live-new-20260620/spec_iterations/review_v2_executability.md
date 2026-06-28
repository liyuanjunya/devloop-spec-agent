# Review v2 — Axis: Executability

**Reviewer**: case6-live-new-20260620-v2 / executability
**Spec under review**: `spec_iterations/spec_v2.json` (7 stories, 33 FRs, 22 SCs, 17 ECs, 5 NCs, 7 concerns)
**v1 axis findings**: E-H-001 (e.__cause__ unpinned), E-H-002 (model override under-specified), E-M-001/002/003

## Verification of v1 fixes

* **E-H-001 (e.__cause__ inspection)** — RESOLVED. FR-018 in v2 now pins the pre-condition: "`OpenAIService.get_response` at `mealie/services/openai/openai.py:308-309` is modified to raise `OpenAIError(...) from e` (explicit cause)". It then enumerates exactly how the orchestrator classifies each cause type into i18n key. Verdict: **resolved**.
* **E-H-002 (per-call model override)** — RESOLVED. FR-005 in v2 pins the API: "`OpenAIService.get_response` is extended with an optional `model_override: str | None = None` kwarg; when set, `_get_provider` uses `provider.model_copy(update={'model': model_override})` to build the per-call provider override without mutating the cached instance." `provider.timeout` and `provider.api_base` are explicitly out of scope. Verdict: **resolved**.
* **E-M-001 (prompt-template wording not pinned)** — NOT addressed. v2 FR-013 still doesn't include the literal text. Acceptable to defer to a follow-up commit. Verdict: **uncertain**.
* **E-M-002 (`_clock` semantics + datetime.utcnow deprecation)** — PARTIALLY RESOLVED. FR-011 in v2 says "`_clock: Callable[[], datetime] = staticmethod(lambda: datetime.now(UTC))` ... `datetime.now(UTC)` is used in place of the deprecated `datetime.utcnow`." Type pinning is clear. Verdict: **resolved**.
* **E-M-003 (handle_exceptions integration point)** — NOT addressed. FR-021 in v1 was left untouched. v2 doesn't say whether the new branches are inline or via a decorator. Acceptable to defer. Verdict: **uncertain**.

## New findings against v2

### E-M-004 [MEDIUM] FR-031 strip_metadata helper signature is implied but not pinned

**Location**: FR-031.

FR-031 says the helper "opens the image with Pillow, deletes `image.info['exif']`, `image.info['xmp']`, `image.info['icc_profile']`, and re-saves over the temp file with `save(..., exif=b'', icc_profile=None)`." Concrete enough for a code agent. But:

* `image.info` is a read-only dict on some Pillow versions; the spec should say `image.info.pop(...)` to be explicit
* The `save()` parameters `exif=b''` and `icc_profile=None` work for JPEG but may be silently ignored for WebP/PNG. The spec should either save format-conditionally or assert the original format is restored
* The "re-save over the temp file" implies an `os.replace` to be atomic; the spec doesn't say that

**Verdict**: confirmed_problem (mild).

### E-M-005 [MEDIUM] FR-026 record_success requires the orchestrator to know "the call succeeded" — but the success path is across `create_one` which has its own exception space

**Location**: FR-026.

FR-026 says "On successful return of `RecipeService.create_one`, the orchestrator calls `record_success`". If `create_one` raises (e.g. ingredient parsing fails, DB integrity error, etc.), record_success is correctly not called. But:

* The attempts deque has already been incremented at FR-011 reserve_attempt time
* The user has effectively been charged an attempt for a DB-side failure that is not really an "image upload" issue

This is a small UX bug rather than an executability gap. Acceptable but worth noting that "30 attempts/hour" actually bounds 30 attempts that pass FR-006/007/008/030/031, including any that fail at the DB layer.

**Verdict**: confirmed_problem (mild).

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 0 |
| Medium   | 2 |

## Final verdict

**Verdict: pass** (both v1 HIGHs resolved)
