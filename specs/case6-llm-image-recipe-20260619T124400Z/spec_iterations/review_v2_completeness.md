# Completeness Review (v2)

## Verdict: NEEDS_REFINE

Spec v2 materially improves v1: the raw DEBUG LLM-response leak is now covered by FR-23/SC-8, docs coverage is added via FR-24/SC-14, auth-vs-feature precedence is explicit in FR-25, and the prompt-path / schema-shape deviations are no longer silent because NC-004 and NC-005 document the trade-offs. The remaining completeness blocker is the rate-limit recording order: v2 promises that invalid/rejected uploads do not consume quota, but the implementation sequence still records before size and MIME validation.

## Critical issues

None.

## High issues

- **COMP-H-004 — Rate-limit recording order contradicts the “rejected attempts are not counted” contract.**
  - Location: `spec_v2.md` US-4 / FR-11 / FR-16 / FR-25 / SC-5; `spec_v2.json` same entries.
  - Evidence: US-4 says only requests that pass auth, gate, size, and MIME are recorded; FR-11 says `check_and_record` appends immediately on success and rejected attempts are not counted; SC-5 requires a 413 mid-loop not to consume quota. But FR-16 assigns the controller the rate-limit check before size/header checks, and FR-25 orders checks as auth → feature gate → **rate limit** → size → MIME → magic → OpenAI. If the required `check_and_record` is executed at FR-25 step 3, later 413/415 failures will already have consumed quota, violating US-4/FR-11/SC-5 and weakening the input’s “OpenAI call” rate-limit semantics.
  - Required fix: Move quota recording until after all local validation that can reject the request (size pre-check, stream cap, header MIME, magic sniff) and immediately before the OpenAI call, or split the limiter into `check_quota` (non-mutating early peek) plus `record_openai_attempt` (mutating after validation). Update FR-16, FR-25, and SC-5 so a coder has one unambiguous sequence.

## Medium issues

- **COMP-M-003 — Parse-failure tests should specify wrapped vs direct validation errors.**
  - Location: `spec_v2.md` FR-14 / SC-7; `spec_v2.json` FR-14 / SC-7.
  - Evidence: FR-14 classifies parse failures by inspecting `e.__cause__` on the generic exception wrapped by `OpenAIService.get_response`. SC-7 also mentions mocks that directly raise `pydantic.ValidationError` / `asyncio.TimeoutError`; direct exceptions do not necessarily have the same `__cause__` shape as the real `get_response` wrapper.
  - Suggested fix: State that tests must cover both the real wrapped `get_response` path and any direct service-level exception path, or make the orchestrator classify `isinstance(e, ValidationError | JSONDecodeError)` as well as `isinstance(e.__cause__, ...)`.

## v1 issue resolution check

| v1 issue | v2 status |
|---|---|
| COMP-C-001 logging control | Resolved by FR-23 + FR-19 + SC-8 |
| COMP-H-001 required prompt template path | Explicitly documented as NC-004 / out-of-scope deviation; acceptable if product accepts the default |
| COMP-H-002 docs/settings update | Resolved by FR-24 + SC-14 + files_to_modify |
| COMP-H-003 RecipeBase-shaped schema | Explicitly documented as NC-005 / out-of-scope deviation; acceptable if product accepts the default |
| COMP-M-001 route-level 422 coverage | Mostly resolved by SC-6/SC-7 and test-file descriptions; see COMP-M-003 for precision |
| COMP-M-002 401 vs 503 precedence | Resolved by FR-25 + SC-2/SC-2b |

## Requirement coverage delta

| Input requirement area | v2 completeness verdict |
|---|---|
| Endpoint, auth, feature gate, response model | Covered |
| Upload validation: size, MIME, real type, temp UUID, deletion | Covered, but quota-order conflict must be fixed so rejected uploads do not count |
| OpenAIService reuse, model env var, timeout | Covered |
| Strict parsing, pydantic validation, 422/i18n/no raw HTTP leak | Covered; test precision suggested |
| Prompt injection and prompt template | Deliberate deviation recorded in NC-004 |
| Logging privacy | Covered |
| i18n keys | Covered |
| Required tests for 413/415/422/429/503/401/temp/logs | Covered after resolving quota-order ambiguity |
| Docs/settings/OpenAPI-related config | Docs covered; OpenAPI generation remains in constraints/test-plan practice |

## Summary

Refine once more before coding. The fix is small but important: make the rate limiter count OpenAI attempts only after local upload validation succeeds, or explicitly split non-mutating quota checks from mutating records. After that, the v2 spec is complete enough for implementation.
