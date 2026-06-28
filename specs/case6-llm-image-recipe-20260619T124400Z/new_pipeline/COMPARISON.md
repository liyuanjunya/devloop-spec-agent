# Case-6 NEW Pipeline vs OLD Pipeline Comparison

**Subject feature**: Mealie — LLM image-to-recipe (security-heavy)
**OLD pipeline**: pre-defense devloop runs that produced `spec.md` (v1) and `spec_iterations/spec_v2.md` (v2)
**NEW pipeline**: this run, with all 15 P0–P3 defenses active (A4 pydantic + soft-language, A5 citation verifier, B1 JSON/MD roundtrip, B3 trace matrix, C1 adversarial reviewer rubric, C3 security perspective auto-activation)
**NEW spec**: `new_pipeline/spec.json` + `new_pipeline/spec.md`

---

## 1. Validator summary (this NEW run)

| Validator                                     | Result                                                    |
| --------------------------------------------- | --------------------------------------------------------- |
| **A4** — pydantic `Spec.model_validate` + soft-language regex (`or equivalent`, `TBD`, `if needed`, `placeholder`, …) | **PASS** — schema_version 1.0, 6 stories, 25 FRs, 15 SCs, 12 edge cases, 3 needs_clarification, 4 self_concerns |
| **A5** — `verify_spec_citations` against `C:\Users\v-liyuanjun\Downloads\mealie` | **PASS** — 0 problems across 47 citations (every cited file exists, every range in-bounds, every named symbol found inside its cited range) |
| **B3** — `find_trace_gaps` (FR↔SC↔US)         | **PASS** — every functional FR points to ≥1 SC, every SC is referenced by ≥1 FR, every P1 user story is claimed by ≥1 FR |
| **B1** — `assert_spec_roundtrip_consistent` + `find_md_only_content` | **PASS** — JSON → Spec → JSON is byte-identical for normative fields, and every rendered H2 section maps to a normative Spec field |

**Total problems across all 4 validators: 0.**

Reproduce with `python new_pipeline/run_validators.py` from the devloop repo root.

---

## 2. OLD v1 architecture findings (0 Critical / 4 High / 4 Medium / 1 Low) — what NEW prevents

`spec_iterations/review_v1_architecture.md`

| # | Sev | OLD v1 finding | NEW defense that prevents it | Where in NEW spec |
| - | --- | -------------- | ---------------------------- | ----------------- |
| H-1 | High | DEBUG-level leak: `mealie/schema/openai/_base.py:33-34` logs the full raw LLM response on parse failure. OLD v1 said "no raw LLM in error responses" but never forbade DEBUG. | **C1 adversarial rubric** flags "log redaction at error level only" as a known anti-pattern, and **C3 security perspective** treats logging as a primary attack surface. | **FR-019** explicitly: "No raw LLM response in logs at ANY level including DEBUG" + the FR mandates rewriting `_base.py:33-34` to `logger.debug("…response length=%d chars", len(response or ""))`. Cited at `mealie/schema/openai/_base.py:29-36` (verified by A5). |
| H-2 | High | `exc_info=True` on the failure logger re-leaks the wrapped upstream exception text through the traceback even after the HTTP body is scrubbed. | **C1 adversarial rubric** ("imagine the spec is implemented literally — what attack works?") plus enforcing the cause-chain severance. | **FR-018** mandates `OpenAIServiceError(<i18n-key>) from None` (suppresses both `__cause__` AND `__context__`) and **FR-019** mandates the failure log line drop `exc_info=True`. |
| H-3 | High | In-memory rate-limiter silently under-counts when `WORKERS > 1` because each uvicorn worker keeps its own dict. OLD v1 said "use in-memory" without an AND-gate against `WORKERS == 1`. | **C1 adversarial** ("rate-limit silently under-counts on multi-worker"). | **FR-004** AND-composes the feature gate with `settings.WORKERS == 1`, and **FR-011** explicitly states "Multi-worker deployments are hard-disabled at startup". **NC-003** documents the "use DB-backed instead?" alternative as a needs-clarification block. |
| H-4 | High | Auth precedence inconsistent: OLD v1 FR-03 said 401 for missing auth but SC-2 said "every request returns 503 when feature off" — contradicts itself because feature-off check happens before auth check in FR-25's ordering. | **B3 trace matrix** + **C1 adversarial ordering check** ("what is the exact order of checks?"). | **FR-025** publishes the explicit 7-step ordering `auth → feature_gate → header_MIME → size_chunked → magic_byte → rate_limit → OpenAI` and **FR-003** binds the controller to `BaseUserController` (auth-first via FastAPI dependency injection). SC-002 wording is now consistent (`503 ONLY when feature off AND auth has succeeded`). |
| M-1 | Med | OLD v1 didn't say where the temp file lives, opening the door to `Path(image.filename).name` traversal. | **C1 adversarial** ("user-controlled filename → traversal") + **C3 security**. | **FR-009** mandates UUID-named temp file `temp_path / uuid4().hex` (NOT `Path(image.filename).name`) inside `get_temporary_path()`, cited to `mealie/core/dependencies/dependencies.py:190-199`. |
| M-2 | Med | OLD v1 said "MIME whitelist" but did not specify WHERE the check runs or what mismatch means. | **C1 adversarial** ("attacker sends JPEG-claimed but is PNG", "SVG with embedded script"). | **FR-007** (header whitelist `image/jpeg, image/png, image/webp`, SVG explicitly banned with GHSA citation) + **FR-008** (magic-byte sniff via `filetype.guess`, REQUIRES `result.mime == header.value`). |
| M-3 | Med | OLD v1 said "timeout" but did not bound the asyncio scope. | **C1 adversarial** ("sync Pillow work outside `await` is not preempted"). | **FR-012** explicitly notes "the 60s timeout covers only the awaited portion; SC-006 verifies the timeout fires when `get_response` itself sleeps". |
| M-4 | Med | OLD v1 did not specify how `OpenAIService` is told which model to use for the image route vs. the existing URL-scrape route. | **C1 adversarial** ("global mutation of DB row"). | **FR-005** mandates `provider.model_copy(update={"model": settings.OPENAI_IMAGE_MODEL})` and explicitly "The DB-stored `AIProviderOut` row is never mutated". |
| L-1 | Low | OLD v1 missing i18n keys; English strings embedded. | Generic completeness check. | **FR-020** lists the 6 exact i18n keys to add to `en-US.json` (en-US-only per Mealie Crowdin policy). |

---

## 3. OLD v2 REGRESSIONS — the critical case-6 failure mode

OLD v2 was the iteration that **introduced new defects while trying to address v1**.
`spec_iterations/review_v2_architecture.md` + `review_v2_executability.md`

### 3.1 NEW HIGH regression: rate-limit-before-validation (the marquee case-6 bug)

**OLD v2 FR-25** ordered checks: `feature_gate → rate_limit → size → MIME → magic → OpenAI`.
**But OLD v2 US-4/FR-11/SC-5** said: "only successful requests consume quota; rejected requests do NOT count".

This is a self-contradiction: a 413 (too large) or 415 (bad MIME) request would consume quota under the v2 ordering, contradicting v2's own success criteria. An attacker uploads 10× over-cap junk files and burns the user's hourly quota without ever calling OpenAI.

| What NEW does | Where |
| ------------- | ----- |
| **FR-011** opens with "Per-user-per-hour rate-limit ordered AFTER all input validation" and reiterates "Rejected attempts at FR-006/007/008 do NOT consume quota because the limiter is never called for them." | `functional_requirements[10].text` in `spec.json` |
| **FR-025** publishes the explicit precedence chain `auth → feature_gate → header_MIME → size_chunked → magic_byte → rate_limit → OpenAI` (7 steps, rate-limit at step 6 — AFTER every input validator). | `functional_requirements[24].text` |
| **SC-005** "After 10 successful calls in 1h, the 11th call returns 429. After 10 oversize uploads in 1h, the 11th oversize call still returns 413 and 1 valid call within the same window still succeeds." | `success_criteria[4]` |

**Defense responsible**: **C1 adversarial reviewer** (the rubric explicitly names "rate-limit before size check — consumes quota for rejected requests" as a known anti-pattern), reinforced by **B3 trace matrix** which makes the FR-011 ↔ SC-005 link explicit. The NEW writer would also have been guarded by the **C3 security perspective** (DoS via wasted quota).

### 3.2 OLD v2 M-1: `Content-Length` applied to whole multipart body

OLD v2 said the controller pre-checks `request.headers["Content-Length"] > 5_242_880` for fast-fail. But for `multipart/form-data` `Content-Length` includes boundary and part-header overhead, so a 5.0 MiB file inside a small form would be ~5.0 MiB + ~200 B and false-rejected.

| NEW defense | Where |
| ----------- | ----- |
| **FR-006** explicitly: "The controller does NOT pre-check `Content-Length` because for `multipart/form-data` it includes boundary and part-header overhead and would false-reject valid files near the cap." The cap is enforced via the cumulative chunked-read loop instead. | `functional_requirements[5].text` |

**Defense responsible**: **C1 adversarial** ("what's the difference between `Content-Length` of a body vs. a multipart envelope?") and the **A5 citation verifier** forces the spec author to look at real multipart handling code rather than write speculative pseudo-checks.

### 3.3 OLD v2 M-2: Service raises `HTTPException` directly

OLD v2 had the service layer raising `HTTPException(413, "too large")`, leaking the transport (HTTP) into the domain layer (service). This breaks Mealie's Repository-Service-Controller separation and makes the service untestable without FastAPI.

| NEW defense | Where |
| ----------- | ----- |
| **FR-016** mandates "service never raises `HTTPException` directly; service raises domain exceptions (`FileTooLargeError`, `UnsupportedMediaTypeError`, `RateLimitError`, `OpenAIServiceError`) and the controller's `handle_exceptions` maps to HTTP status codes". **FR-021** publishes the 5-branch translation table. | `functional_requirements[15]` + `[20]` |
| **FR-002** lists the four NEW exception classes to add to `mealie/core/exceptions.py` (the file currently has 2 of them; this FR specifies adding `FileTooLargeError` and `UnsupportedMediaTypeError`). | `functional_requirements[1]` |

**Defense responsible**: **C1 adversarial** + repository convention check (Repository-Service-Controller is in `.github/copilot-instructions.md`).

### 3.4 OLD v2 M-3: Timeout doesn't cover sync Pillow work

OLD v2 said `asyncio.wait_for(get_response(...), 60.0)` but `OpenAILocalImage.get_image_url` runs synchronous Pillow `Image.open → resize → save → b64encode` BEFORE the awaited HTTP call, so the timeout cannot preempt it.

| NEW defense | Where |
| ----------- | ----- |
| **FR-012** explicitly: "because `OpenAILocalImage.get_image_url` does synchronous Pillow/base64 work BEFORE the awaited OpenAI call, the 60s timeout covers only the awaited portion; the orchestrator's SC-006 acceptance test verifies the timeout fires when `get_response` itself sleeps, which is the only point asyncio can preempt." Citation `mealie/services/openai/openai.py:84-95` (verified by A5). | `functional_requirements[11].text` |

**Defense responsible**: **A5 citation verifier** (the NEW writer was forced to look at `OpenAILocalImage.get_image_url` line numbers and observed it's sync) + **C1 adversarial** ("what if the operation isn't actually awaited?").

### 3.5 OLD v2 EXEC-V2-2: FR-01 cited line 358 for `duplicate_one`; actual line is 450

OLD v2's executability reviewer caught this manually. In the NEW pipeline this is a **mechanical** failure:

| NEW defense | Where |
| ----------- | ----- |
| **A5 citation verifier** rejects `symbols=["duplicate_one"]` with `line_ranges=[[358, 360]]` automatically (the verifier strips comment lines and searches for `def duplicate_one` inside the cited ranges). NEW FR-001 cites the correct line 451. The NEW run produced 0 citation problems across 47 references. | `verify_spec_citations` in `devloop/spec_phase/validators/citation_verifier.py` |

**Defense responsible**: **A5** — this is the canonical example of a defense that converts a manual review finding into a build-time error.

---

## 4. Cross-cutting NEW additions not present in either OLD v1 or v2

These are improvements the NEW pipeline produced that neither OLD iteration even attempted:

| Improvement | Where | Why OLD missed it |
| ----------- | ----- | ----------------- |
| Explicit precedence chain in **FR-025** (7-step ordering, single source of truth) | `functional_requirements[24]` | OLD didn't have a "publish the ordering as its own FR" convention; ordering was scattered across FRs and contradictory. |
| **Prompt-injection guard** with system/user message separation in **FR-017** | `functional_requirements[16]` | OLD v1/v2 only said "use image_url"; never mentioned ignoring image-borne text instructions. C1 adversarial flagged this. |
| `from None` mandate to sever cause/context chains in **FR-018** | `functional_requirements[17]` | OLD v2 had `from e` which re-leaks the upstream message. |
| 3 explicit **NEEDS_CLARIFICATION** blocks for genuine product decisions: NC-001 (persist vs. draft), NC-002 (filetype vs. python-magic), NC-003 (in-process vs. DB-backed rate-limit) | `needs_clarification[]` | OLD v1 had only 3 NCs and they were vague; OLD v2 added 2 more but missed NC-003. |
| 4 **self_concerns** including a Pillow CVE note and an `_base.py` global-scope leak callout | `self_concerns[]` | OLD didn't have a structured concern field. |
| **12 edge cases** including EC-008 (`exc_info=True` re-leak), EC-010 (worker drop mid-request loses in-memory counter), EC-011 (parse-failure DEBUG leak via global `_base.py` path) — all phrased to map directly to an acceptance test | `edge_cases[]` | OLD v1 had 8 ECs and missed the global DEBUG path. |

---

## 5. Defenses that would NOT have caught each OLD defect

It's important to be honest about what the new pipeline does and does not catch:

| OLD defect | Defense that catches it | Defense that does NOT and why |
| ---------- | ----------------------- | ----------------------------- |
| v1 H-1 DEBUG leak | C1 adversarial + C3 security | A5 citation verifier cannot — it only checks code refs are valid, not that the design ignores a known leak path. |
| v1 H-3 multi-worker | C1 adversarial | A5 cannot — `WORKERS` is just a setting, not a code-correctness issue. |
| v2 rate-limit ordering regression | C1 adversarial + B3 trace matrix | A5 cannot — both orderings cite valid code; A4 cannot — both orderings parse cleanly; B1 roundtrip cannot — both round-trip; B3 only catches it if you trace FR-011→SC-005 and see the contradiction in the text, which is partial coverage. **C1 is the primary defense here.** |
| v2 EXEC-V2-2 wrong line citation | A5 (mechanical) | C1 may catch it via "did the reviewer actually open the file?" but A5 is the cheap deterministic check. |
| NC-001 persist-vs-draft | None — this is a genuine product question | All validators are silent because the spec correctly flags it as a clarification need rather than guessing. The NEW pipeline's contribution is the **`needs_clarification` schema field** that lets the writer escalate rather than fabricate. |
| Multipart `Content-Length` (v2 M-1) | C1 adversarial + writer's prior exposure to multipart spec | A5 cannot — both "do pre-check" and "don't pre-check" cite valid headers reference. |
| Service raises `HTTPException` (v2 M-2) | C1 adversarial + repo-convention check (Repository-Service-Controller is in copilot-instructions.md) | A5 cannot — `HTTPException` is a real symbol. |

**Net assessment**: A4/A5/B1/B3 catch the mechanical errors (bad citations, soft language, broken trace, lost data in roundtrip). C1 (adversarial) + C3 (security perspective) catch the **design-level security regressions** that case-6 specifically tests for. Without C1+C3 this case-6 NEW spec would still likely have repeated the v2 rate-limit-ordering regression.

---

## 6. Quality bar — explicit checklist from task brief

| Requirement | Status | Evidence |
| ----------- | ------ | -------- |
| spec.json passes all 4 validators (A4, A5, B1, B3) with 0 problems | ✅ | `python new_pipeline/run_validators.py` reports `TOTAL PROBLEMS ACROSS ALL VALIDATORS: 0` |
| Includes explicit rate-limit-AFTER-validation FR | ✅ | **FR-011** opens with the ordering, **FR-025** publishes the 7-step chain |
| Includes magic-byte check ordered correctly | ✅ | **FR-008** ("runs AFTER size FR-006 and header FR-007 and BEFORE the rate-limit FR-011") |
| Includes prompt-injection FR with system/user separation | ✅ | **FR-017** mandates separate system message + image-instruction-ignore guard |
| Includes log-redaction FR forbidding raw LLM at ANY log level | ✅ | **FR-019** "at ANY level including DEBUG" + the FR also rewrites the global `_base.py:33-34` leak |
| At least 1 needs_clarification block for genuinely ambiguous items | ✅ | 3 blocks: NC-001, NC-002, NC-003 |

---

## 7. Verdict

The NEW pipeline produced a v1 that, in a single pass, avoids:

- All 4 OLD v1 HIGH findings (H-1 through H-4)
- All 4 OLD v1 MEDIUM findings (M-1 through M-4)
- The 1 OLD v1 LOW finding (L-1 i18n)
- The OLD v2 NEW-HIGH regression (rate-limit ordering)
- The OLD v2 MEDIUM regressions (M-1 multipart Content-Length, M-2 service HTTPException, M-3 sync timeout coverage)
- The OLD v2 executability finding (wrong line citation EXEC-V2-2)

…all while passing 4 mechanical validators with 0 problems and surfacing 3 genuine clarification needs to the human instead of guessing.

The OLD pipeline took 2 iterations and still shipped a v2 with a NEW HIGH regression. The NEW pipeline shipped a v1 with no equivalent regression. The deltas attributable to specific defenses are tabulated in §2–§5 above.
