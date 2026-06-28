# Architecture review v2 — Case 6 Mealie LLM image-to-recipe

## Verdict

**REQUEST CHANGES** — 0 Critical, 1 High, 3 Medium, 0 Low.

v2 resolves the v1 blocking architecture/security issues around DEBUG log leakage, exception-chain leakage, multi-worker rate-limit honesty, and auth-vs-feature-gate precedence. However, v2 introduces one new blocking internal contradiction: the rate limiter is specified to append before size/MIME/magic/OpenAI success, while the user story/FR/SC require rejected attempts not to consume quota and the 11th *successful* request to be the first 429.

## v1 issue disposition

### High issues

#### H-1 — Raw LLM response can still be logged at DEBUG

**RESOLVED.** v2 adds FR-23 requiring the global `OpenAIBase._process_response` DEBUG log at `mealie/schema/openai/_base.py:33-35` to be changed from raw response content to schema name + response length only (`spec_v2.md:53-55`, `spec_v2.json:242-246`). SC-8 is updated to be executable at DEBUG and explicitly depends on FR-23 (`spec_v2.md:71-72`).

#### H-2 — `exc_info=True` can re-leak sanitized upstream errors through exception chains

**RESOLVED.** v2 explicitly requires `OpenAIServiceError(<i18n-key>) from None` and forbids interpolation of `str(e)`/class names into the sanitized exception (`spec_v2.md:49`). FR-19 explicitly says the warning log is emitted without `exc_info=True` (`spec_v2.md:50`), and SCN-6 documents the debugging trade-off (`spec_v2.md:118`).

#### H-3 — In-memory rate limit does not satisfy per-user/hour in multi-worker deployments

**RESOLVED.** v2 makes the in-process limiter honest by hard-disabling the feature when `settings.WORKERS > 1` (`spec_v2.md:42`, `spec_v2.json:139-145`). SC-13 and EC-10 require 503 behavior under `UVICORN_WORKERS=2` (`spec_v2.md:77`, `spec_v2.md:95`). This is an acceptable architectural trade-off versus adding DB-backed rate-limit storage in this iteration.

#### H-4 — Auth/feature-disabled acceptance criteria are internally inconsistent

**RESOLVED.** v2 rewrites US-2 and SC-2 to cover authenticated requests only, and adds SC-2b for unauthenticated 401 (`spec_v2.md:18`, `spec_v2.md:65-66`). FR-25 defines explicit precedence with FastAPI auth before feature gate (`spec_v2.md:56`). This matches `BaseUserController.user: PrivateUser = Depends(get_current_user)` in Mealie (`mealie/routes/_base/base_controllers.py:132-139`).

### Medium issues

#### M-1 — Controller/service ownership inconsistent around upload validation and temp lifecycle

**RESOLVED for the original concern.** FR-16 now gives a concrete split: controller owns HTTP-only concerns; service owns chunked write, magic sniff, temp lifecycle, OpenAI orchestration, cleanup, and `create_one` (`spec_v2.md:47`). See new M-2 below for a remaining exception-translation layering concern, but the original ownership ambiguity is materially fixed.

#### M-2 — Magic-byte detection needs explicit `None`/unknown path

**RESOLVED.** FR-08 now explicitly treats `filetype.guess(temp_file) is None` as HTTP 415 `recipe.image.unsupported-mime` (`spec_v2.md:39`), and EC-09 repeats this edge case (`spec_v2.md:94`).

#### M-3 — OpenAI image model env override not aligned with provider-as-configuration model

**RESOLVED.** FR-05 documents `OPENAI_IMAGE_MODEL` as a deliberate server-wide per-call override and requires `provider.model_copy(update={...})` so the DB provider is not mutated (`spec_v2.md:36`). The test plan includes a no-mutation unit test (`spec_v2.md:145`).

#### M-4 — Prompt-injection mitigation should be scoped honestly

**RESOLVED.** FR-17 now states the narrow security goal: prevent image text from changing model role/tool/system behavior, not guarantee safe recipe content (`spec_v2.md:48`). EC-03 and SCN-3 repeat that output remains untrusted recipe data handled by existing cleaning/rendering (`spec_v2.md:88`, `spec_v2.md:115`).

### Low issue

**NOT ASSESSABLE FROM v1 ARTIFACT.** The v1 architecture review summary counted 1 Low issue (`review_v1_architecture.md:5`, `:69-74`) but the file contains no named Low section or actionable Low item. No v2 approval decision depends on this missing Low because the current review has a new High issue.

## New issues in v2

### H-1 — Rate-limit ordering/counting contradicts the successful-request contract and makes SC-5 impossible

US-4 says the 11th **successful** request is rate-limited and that only requests passing earlier checks are recorded (`spec_v2.md:20`). FR-11 repeats that rejected attempts are not counted and defines `check_and_record` as appending immediately when below the limit (`spec_v2.md:42`, `spec_v2.json:139-140`). But FR-25 orders the controller checks as feature gate → **rate limit** → size pre-check → MIME header → magic sniff → OpenAI (`spec_v2.md:56`, `spec_v2.json:256-257`).

That means an over-size, unsupported-MIME, magic-mismatch, timeout, or parse-failed request can consume quota before it is rejected, directly contradicting FR-11 and SC-5's assertion that a 413 path does not consume quota (`spec_v2.md:69`). It also changes observable precedence: an already quota-exhausted user sending a 6 MB JPEG gets 429 instead of the specified 413.

Fix by moving quota reservation until after all local validation (size/header/magic) and immediately before the OpenAI call. If the contract truly requires only successful 201 calls to count, make the limiter a reserve/commit/rollback primitive: reserve under lock before OpenAI for concurrency protection, commit after `create_one` succeeds, and roll back on 413/415/422/500 paths. Alternatively, explicitly change US-4/FR-11/SC-5 to say all OpenAI-attempting requests count, but that would be a product/security contract change.

### M-1 — `Content-Length` pre-check applies a file-size cap to the entire multipart body

FR-06 says reject pre-stream when `request.headers.get("content-length") > 5_242_880` (`spec_v2.md:37`). For `multipart/form-data`, `Content-Length` is the whole request body including boundaries and part headers, not just the uploaded image bytes. A valid image at or just below the 5 MiB file cap can be falsely rejected because multipart overhead pushes the request body over 5 MiB. Keep the streaming per-file cap as authoritative; if a pre-check is retained, allow multipart overhead or document the cap as total request-body size.

### M-2 — Service-side upload validation is still specified to raise HTTP exceptions directly

FR-16 says the service owns mid-stream size and magic validation (`spec_v2.md:47`), while FR-21 says `FileTooLargeError`/`UnsupportedMediaTypeError` from FR-06/FR-08 are raised as `HTTPException(413|415, …)` directly and bypass controller exception translation (`spec_v2.md:52`). That leaks HTTP transport concerns into the service layer and is inconsistent with the stated controller responsibility for translating exceptions. Prefer domain exceptions (`ImageTooLargeError`, `UnsupportedImageMediaTypeError`) raised by the service and mapped by the controller.

### M-3 — Timeout acceptance test does not cover synchronous image preprocessing inside `get_response`

FR-12 wraps `OpenAIService.get_response(...)` in `asyncio.wait_for(..., timeout=60.0)` (`spec_v2.md:43`). In Mealie, `OpenAILocalImage.get_image_url()` synchronously minifies and base64-encodes the image before the awaited OpenAI call (`mealie/services/openai/openai.py:84-94`, `:294-300`). `asyncio.wait_for` cannot preempt CPU-bound synchronous work until the coroutine yields. SC-6 only mocks `get_response` sleeping (`spec_v2.md:70`), so it does not verify the real wall-clock path. Add a test/seam covering slow image preprocessing, or clarify that the 60s timeout applies only after local image preprocessing completes.

## Approval gate

Not approved: the new rate-limit ordering/counting issue is High. Approval requires **0 Critical + 0 High**.
