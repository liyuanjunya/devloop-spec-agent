# Review v2 — Axis: Architecture

**Reviewer**: case6-live-new-20260620-v2 / architecture
**Spec under review**: `spec_iterations/spec_v2.json` (7 stories, 33 FRs, 22 SCs, 17 ECs, 5 NCs, 7 concerns)
**Validators baseline**: A4/A5/B1/B3 = 0 problems
**v1 axis findings**: A-H-001 (controller/orchestrator), A-H-002 (URL-scrape regression), A-M-001, A-M-002

## Verification of v1 fixes

* **A-H-001 (controller/orchestrator rate-limit ownership)** — RESOLVED. FR-016 now says "The controller does NOT call the rate-limiter — it delegates immediately to `OpenAIRecipeService.create_from_image(image)` after the Content-Type check passes." FR-011 confirms "the orchestrator calls `await get_rate_limiter().reserve_attempt(user.id)` IMMEDIATELY BEFORE the OpenAI call". Both FRs now agree the orchestrator owns the limiter. Verdict: **resolved**.
* **A-H-002 (URL-scrape regression coverage for FR-019)** — RESOLVED. New FR-033 mandates two regression tests (`test_url_scrape_debug_redaction.py` + `test_base_debug_redaction.py`) and pins SC-021 to assert the URL-scrape parse-failure DEBUG log emits the length sentinel and not the raw body. Verdict: **resolved**.
* **A-M-001 (singleton bypasses factory)** — NOT addressed. The rate-limiter is still a module-level singleton. Acceptable for v2 since the spec acknowledges it; a follow-up PR can switch to `app.state` once the basic functionality lands. Verdict: **uncertain** (downgraded to LOW from MEDIUM since v2 has a working test surface).
* **A-M-002 (handle_exceptions isinstance order)** — NOT addressed. v2 doesn't pin the isinstance order in FR-021. Verdict: **uncertain**.

## New findings against v2

### A-M-003 [MEDIUM] FR-028's ASGI middleware mount point is unspecified

**Location**: FR-028.

FR-028 says the middleware "is mounted at app startup" and references `mealie/app.py`. Mealie's actual app-factory wiring (per repository convention) usually goes through `mealie/main.py` or `mealie/app.py`. The spec doesn't say:

* whether the middleware applies globally or only to `/api/recipes/create/image`
* whether it is added before or after the existing CORS / auth middleware (order matters for return code and access logging)
* the exact `app.add_middleware(MaxBodySizeMiddleware, max_bytes=...)` call site

A code agent will pick one and the security review will need to re-verify.

**Verdict**: confirmed_problem (mild). Should be ironed out in implementation review, not blocking for spec sign-off.

### A-M-004 [MEDIUM] FR-029 / FR-031 add a new helper module without specifying where it lives in the package hierarchy

**Location**: FR-029, FR-031.

Both FRs cite `mealie.services.openai.image_normalize.<helper>` as the home. The spec doesn't say:

* whether `image_normalize.py` is a new file (likely yes) or a logical grouping
* whether the helpers are class-based or free functions
* whether they should reuse `PillowMinifier` from `mealie/services/openai/openai.py:84-94` or stand alone

This is a small architectural decision but worth pinning so the reviewer knows what code shape to expect.

**Verdict**: confirmed_problem (mild).

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 0 |
| Medium   | 2 |

## Final verdict

**Verdict: pass** (both v1 HIGH findings resolved; remaining mediums are implementation-detail level)
