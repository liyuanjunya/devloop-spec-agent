# Architecture review v1 — Case 6 Mealie LLM image-to-recipe

## Verdict

**REQUEST CHANGES** — 0 Critical, 4 High, 4 Medium, 1 Low.

The spec is directionally strong: it reuses Mealie's existing `OpenAIService` image attachment path, keeps the repository/service/controller intent, avoids `python-magic` native dependency by selecting a pure-Python equivalent, and correctly identifies `get_temporary_path()` as the cleanup primitive. However, the current spec has several blocking architectural contradictions/security gaps that should be fixed before implementation.

## Critical issues

None.

## High issues

### H-1 — Raw LLM response can still be logged at DEBUG, contradicting the security requirement and SC-8

The spec says no raw LLM response should be logged and SC-8 explicitly tests with `caplog` at DEBUG that no mocked LLM response appears. But the chosen reuse path calls `OpenAIService.get_response()`, which calls `response_schema.parse_openai_response(response_text)` (`mealie/services/openai/openai.py:300-305`). On parse failure, `OpenAIBase._process_response()` logs the raw response at DEBUG: `logger.debug(f"Failed to parse OpenAI response as {cls}. Response: {response}")` (`mealie/schema/openai/_base.py:30-35`).

FR-19 incorrectly declares this acceptable because production log level is INFO+, while its own success criterion requires DEBUG log capture to be clean. Fix by changing the reusable OpenAI parse logging to log only class name / response length / error category, or by adding a safe parse path used by this feature.

### H-2 — `exc_info=True` can re-leak sanitized upstream errors through exception chains

FR-18 requires HTTP errors not to interpolate `str(e)`, which is good. But FR-19 then proposes `logger.warning(..., exc_info=True)`. Existing `OpenAIService.get_response()` wraps arbitrary exceptions as `Exception(f"OpenAI Request Failed. {e.__class__.__name__}: {e}")` (`mealie/services/openai/openai.py:306-309`). If the orchestrator raises `OpenAIServiceError(...) from e` and logs with `exc_info=True`, server logs can include the chained upstream exception message, model/provider errors, or parser details.

This violates the spec's own log-safety requirement (input.md security table: do not log raw LLM output). The architecture should require `from None` for sanitized user-facing exceptions or log without traceback for expected OpenAI/parse failures, with only sanitized fields.

### H-3 — In-memory rate limit does not satisfy the stated per-user/hour contract in supported multi-worker deployments

FR-11 specifies a process-local `dict[UUID, deque[datetime]]` guarded by `asyncio.Lock`, with only a WARN when `UVICORN_WORKERS > 1`. Mealie exposes `UVICORN_WORKERS` and computes workers from it (`mealie/core/settings/settings.py:427-437`). A per-process limiter allows up to `10 * workers` calls/hour/user, so the external API protection is not actually per-user/hour in a configured multi-worker deployment.

The input allows simple memory + DB counting and does not require Redis; it does not waive correctness for multiple workers. Use a DB-backed counter/table/repository seam, or explicitly constrain the feature to one worker and fail closed when workers > 1. A startup warning is not sufficient for a security/rate-limit acceptance gate.

### H-4 — Auth/feature-disabled acceptance criteria are internally inconsistent and likely impossible with current routing

FR-03 relies on `UserAPIRouter` authentication (`mealie/routes/recipe/recipe_crud_routes.py:85`), while SC-2 says that with the env var unset, "every request shape" including unauthenticated requests returns 503. Existing FastAPI dependency authentication will run before the route body, so unauthenticated requests should remain 401. This also conflicts with the original input test requirement to verify unauthenticated returns 401.

Resolve the precedence contract: recommended behavior is 401 for unauthenticated requests, then 503 for authenticated requests when the feature is disabled.

## Medium issues

### M-1 — Controller/service ownership is inconsistent around upload validation and temp-file lifecycle

The spec says the controller validates input and delegates while `RecipeService.create_from_image` orchestrates (FR-16), but `files_to_modify` assigns size/MIME/magic/rate-limit/temp-path work to the route and also rewrites `RecipeService.create_from_image` to use `get_temporary_path()` and UUID filenames. Current Mealie already has the temp cleanup primitive (`get_temporary_path()` creates a UUID dir and `rmtree`s it in `finally`, `mealie/core/dependencies/dependencies.py:190-198`) and the legacy service writes uploaded files in the service (`mealie/services/recipe/recipe_service.py:335-355`).

Choose one owner. Prefer: controller handles HTTP-only checks (auth, form field presence, Content-Length precheck), service owns streaming, magic sniffing, temp path, OpenAI call, and cleanup.

### M-2 — Magic-byte detection needs an explicit `None`/unknown-type path

FR-08 says `filetype.guess(temp_file).mime` must be whitelisted. `filetype.guess(...)` can return `None` for unknown or malformed files; the spec should require treating `None` as HTTP 415 `recipe.image.unsupported-mime`, not allowing an AttributeError to fall into generic 500/422 handling.

### M-3 — OpenAI image model env override is not aligned with Mealie's existing provider-as-configuration model

Existing `OpenAIService` selects a per-group `image_provider` via `_get_provider()` when an `OpenAIImageBase` attachment is present (`mealie/services/openai/openai.py:147-168`), and the provider's model is stored on `AIProviderOut.model` (`mealie/schema/group/ai_providers.py:11-16`). Adding global `OPENAI_IMAGE_MODEL` in `AppSettings` (`mealie/core/settings/settings.py:417-424` currently only has `OPENAI_CUSTOM_PROMPT_DIR`) is requested by input, but it creates a global override that can surprise group admins.

This is acceptable only if documented as an explicit server-wide override and tested to avoid mutating the provider object (`model_copy` is the right direction).

### M-4 — Prompt-injection mitigation is acceptable as a first layer but should be scoped honestly

The existing `OpenAIService` already separates system and user messages (`mealie/services/openai/openai.py:264-281`), and appending a guard to `parse-recipe-image.txt` (`mealie/services/openai/prompts/recipes/parse-recipe-image.txt:1-6`) is architecturally sound. But the spec should avoid implying this prevents malicious text from appearing in recipe fields. It should explicitly define the security goal as "do not let image text alter model instructions or tool behavior"; output content is still untrusted recipe data and relies on existing recipe sanitization/rendering.

## Self-concerns verdict

- **SC-1 python-magic**: Accepted. `filetype` is a realistic "or similar" alternative; repo search found no existing `python-magic`/`filetype` dependency, so avoiding native libmagic is prudent.
- **SC-2 in-process rate limit**: Not accepted as written. Per-process warning does not satisfy the advertised per-user/hour limit when `UVICORN_WORKERS > 1`.
- **SC-3 prompt-injection textual only**: Accepted if wording is tightened per M-4.
- **SC-4 60s timeout**: Accepted because input mandates ≤60s; note that `OpenAILocalImage.get_image_url()` does synchronous Pillow/base64 work before the OpenAI await (`mealie/services/openai/openai.py:84-94`, `294-300`), so tests should cover wall-clock behavior.
- **SC-5 cover image removal**: Accepted. Privacy requirement forbids persisting the upload; current persistence at `recipe_service.py:354-355` must be removed.

## Summary (Critical/High/Medium/Low counts)

- Critical: 0
- High: 4
- Medium: 4
- Low: 1

**Approval gate:** Not approved until all High issues are resolved.
