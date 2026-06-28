# Completeness Review (v1)

## Verdict: NEEDS_REFINE

The spec is strong on endpoint shape, feature flagging, OpenAIService reuse, temp-file handling, rate limiting, timeout, 3-layer flow, pydantic validation, and the required 413/415/422/429/503 test outcomes. However, it inverts the required prompt-template path and has an incomplete/contradictory answer for the §4 logging security row. Because the logging row is one of the mandatory §4 security controls, this review has a **critical** finding.

## Critical issues

- **COMP-C-001 — §4 logging control is not fully satisfied; raw LLM output can still be logged.**
  - Location: `spec.md` FR-19 / SC-8; `spec.json` FR-19 / SC-8.
  - Evidence: input §4 requires logs to never record image base64 or raw LLM response. The spec says existing `mealie/schema/openai/_base.py:33-35` raw-response DEBUG logging is "acceptable" because production is INFO+, but the requirement is not limited to production log level. The same spec also proposes failure logging with `exc_info=True` while caught OpenAI exceptions may carry upstream/raw content (`openai.py:308-309` is explicitly called a leak site). SC-8 then asks caplog at DEBUG to prove no raw LLM body appears, which contradicts the accepted DEBUG leak.
  - Required fix: Make this an explicit implementation requirement: remove/sanitize the existing raw-response DEBUG log for this path (or globally), never log exceptions whose message contains raw upstream/LLM content, and log only i18n key, user id, response length/token usage, and success/failure metadata.

## High issues

- **COMP-H-001 — Required prompt template path is explicitly inverted.**
  - Location: `spec.md` FR-13 and Out of scope; `spec.json` FR-13, `out_of_scope[5]`, `files_to_modify[1]`.
  - Evidence: input §2 and the reviewer scope require new jinja2 prompt template `mealie/services/openai/prompts/recipe_from_image.md`. The spec instead says "no new file" and hardens existing `mealie/services/openai/prompts/recipes/parse-recipe-image.txt`.
  - Required fix: Add `mealie/services/openai/prompts/recipe_from_image.md` as the required jinja2 prompt path, or mark this as a blocking product decision rather than silently moving it out of scope.

- **COMP-H-002 — Documentation/settings-site update from input §6 is missing.**
  - Location: no FR / SC / file action for `docs/`.
  - Evidence: input §6 requires registering env vars, updating the docs settings section, and OpenAPI generation. The spec covers settings (`FR-04`, `FR-05`) and partially covers generation (`Constraints`), but `files_to_modify` has no `docs/` path and no success criterion checks the docs settings page.
  - Required fix: Add an FR/SC and file action for the relevant `docs/` settings page documenting `OPENAI_ENABLE_IMAGE_RECIPE` and `OPENAI_IMAGE_MODEL`.

- **COMP-H-003 — Strict prompt JSON schema does not preserve the input's RecipeBase-shaped contract.**
  - Location: `spec.md` FR-13/FR-14; `spec.json` FR-13/FR-14.
  - Evidence: input §2 says the prompt must require strict JSON matching RecipeBase fields (`title`, `description`, `recipe_yield`, `recipe_ingredient[]`, `recipe_instructions[]`). The spec validates existing `OpenAIRecipe` (`name`, `ingredients`, `instructions`, `notes`) and maps it later. This may be a sound repository-specific adaptation, but the input's explicit schema shape is not preserved or documented as a deliberate deviation.
  - Required fix: Either require the new prompt + pydantic model to accept the RecipeBase-shaped JSON requested by input, or add a clear blocking decision/rationale that existing `OpenAIRecipe` is the canonical Mealie image schema and update acceptance criteria accordingly.

## Medium issues

- **COMP-M-001 — 422 test coverage is present but too implicit in the integration-test file description.**
  - Location: test plan summary and `spec.json.files_to_extend[0]`.
  - Evidence: SC-6/SC-7 require 422 cases, but the integration-test file description enumerates 413/415/503/401/429/temp-dir/log coverage and omits explicit route-level 422 cases for OpenAI failure, malformed JSON, and pydantic validation failure.
  - Suggested fix: Add explicit route integration scenarios for 422 parse failure and 422 OpenAI/timeout failure.

- **COMP-M-002 — The service-disabled precedence is stronger than the input and may mask 401.**
  - Location: SC-2.
  - Evidence: input requires auth and says disabled returns 503. SC-2 says without env var every request shape, including unauthenticated, returns 503. That is a deliberate security/product choice, but it conflicts with the usual authenticated-route expectation and with the input's unauthenticated 401 test.
  - Suggested fix: Clarify ordering: unauthenticated requests should return 401 before feature-gate evaluation, while authenticated requests return 503 when disabled; or explicitly justify the 503-before-auth behavior and adjust the 401 test expectation.

## Requirement coverage

| Input requirement | Spec representation | Completeness verdict |
|---|---|---|
| Endpoint `POST /api/recipes/create/image` | FR-01, US-1 | Covered |
| `multipart/form-data` single `image` | FR-02 | Covered |
| Authenticated user | FR-03; 401 in test plan | Mostly covered; see COMP-M-002 ordering ambiguity |
| `OPENAI_ENABLE_IMAGE_RECIPE` default false | FR-04, SC-2/SC-13 | Covered |
| Disabled returns 503 + `recipe.image.feature-disabled` | FR-04, FR-21, SC-2/SC-13 | Covered |
| Response is created Recipe with LLM title/ingredients/instructions | US-1, FR-01, SC-1 | Covered |
| Reuse/extend `OpenAIService` | FR-05, FR-13/14, constraints | Covered |
| `OPENAI_IMAGE_MODEL` default `gpt-4o-mini` | FR-05 | Covered |
| Prompt path `mealie/services/openai/prompts/recipe_from_image.md` jinja2 | Replaced by existing `.txt` prompt | Missing/inverted; see COMP-H-001 |
| Prompt demands strict RecipeBase-shaped JSON | FR-14 uses existing `OpenAIRecipe` instead | Weak/deviated; see COMP-H-003 |
| Prompt injection instruction | FR-17 | Covered |
| Business orchestrator `mealie/services/recipe/recipe_from_image.py` | Spec uses existing `RecipeService.create_from_image` / `OpenAIRecipeService` | Mostly covered by behavior, exact file path not followed |
| Validate upload | FR-06/07/08/09 | Covered |
| Call OpenAI Vision | FR-12/13/14 | Covered |
| Strict JSON parse + pydantic validation | FR-14, SC-7 | Covered |
| Convert to Recipe via existing creation service | FR-15, SC-10 | Covered |
| 3-layer controller/service/repo | FR-16 | Covered |
| Repo create through existing recipe creation path | FR-15/16 | Covered |
| File size ≤5 MB, 413 + `too-large` | FR-06, SC-3 | Covered |
| MIME whitelist jpeg/png/webp, 415 + `unsupported-mime` | FR-07, SC-4 | Covered |
| Actual-type detection, not header-only | FR-08, SC-4 | Covered |
| Temp path under configured tmp dir + UUID | FR-09 | Covered |
| Immediate delete / not assets | FR-10, SC-9 | Covered |
| Per-user hourly ≤10, 429 + `rate-limited` | FR-11, SC-5 | Covered |
| OpenAI timeout ≤60s | FR-12, SC-6 | Covered |
| OpenAI/API/JSON/pydantic failures → 422 i18n, no raw output to client | FR-14, FR-18, FR-21, SC-7 | Covered |
| No raw LLM output/image base64 in logs | FR-19, SC-8 | Incomplete/contradictory; see COMP-C-001 |
| All four required i18n keys | FR-20 includes four plus parse/openai failed | Covered |
| Tests for 413/415/422/429/503 | SC-3/4/5/6/7/13; test plan | Mostly covered; make route 422 tests explicit (COMP-M-001) |
| Docs settings update | Not present | Missing; see COMP-H-002 |
| OpenAPI auto-generation | Constraint mentions `task dev:generate`; no doc SC | Mostly covered |

## Summary

Refine once before coding. The main mandatory fix is to make the logging security control absolute and testable with no DEBUG/raw-response exception path. Then restore the required prompt template path, add docs settings coverage, clarify the RecipeBase-vs-OpenAIRecipe schema deviation, and make route-level 422 tests explicit.
