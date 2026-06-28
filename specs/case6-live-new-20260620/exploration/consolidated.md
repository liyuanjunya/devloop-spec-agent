# Consolidated Exploration — Case-6 LLM Image-to-Recipe

> Sources merged: `data_perspective.md`, `api_perspective.md`, `test_perspective.md`, `history_perspective.md`. All line ranges re-verified against `C:\Users\v-liyuanjun\Downloads\mealie\` on 2026-06-19.

---

## 1. Agreed facts (no conflicts across the four perspectives)

| Topic | Verified citation | Agreement |
|---|---|---|
| `OpenAIService` already supports image attachments via `OpenAILocalImage` (base64 JPEG data-URI). | `mealie/services/openai/openai.py:84-94` (`OpenAILocalImage`), `108-145` (init+client), `147-168` (`_get_provider`), `264-281` (`_get_raw_response` with `response_format=`), `283-309` (`get_response`) | data §1, api §1, test §1.4, history §2 |
| Image-provider gate is per-group DB-backed today (`image_provider_enabled` computed property). | `mealie/schema/group/ai_providers.py:117-130`; `AIProviderCreate.timeout: int = 300` at line 16 | data §5, api §5, test §1.4, history #1 |
| Existing endpoint shape is **multi-image**, returns slug, returns 400 on disable. | `mealie/routes/recipe/recipe_crud_routes.py:309-335` | data §3, api §2, test §1.4, history #4 |
| Existing orchestrator persists first image as `original.webp` cover. | `mealie/services/recipe/recipe_service.py:335-356` (`create_from_images`) — `data_service.write_image(f.read(), "webp")` at lines 354-355 | data §3, api §2 (R3), history R3 |
| `RecipeService.create_one` is the canonical recipe-creation entry; comment at lines 163-167 says "Recipes should not be created elsewhere to avoid conflicts." | `mealie/services/recipe/recipe_service.py:163-187` (factory), `202-245` (`create_one`) | data §3, api Reuse map row §3 |
| `OpenAIRecipe → Recipe` mapper already exists; ingredient text → `RecipeIngredient.note` (not parsed into qty/unit/food). | `mealie/services/recipe/recipe_service.py:599-622` (`OpenAIRecipeService._convert_recipe`) | data §1+§2, api §2 |
| Canonical safe-upload pattern: `get_temporary_path()` context manager + `uuid4()` filename ignoring user-supplied name. | `mealie/routes/users/images.py:19-44` (the gold-standard), `mealie/core/dependencies/dependencies.py:190-198` (helper) | data §4, api §3, test §2.1, history §3 |
| Pydantic v2 strict parse for LLM output via `OpenAIBase.parse_openai_response`. | `mealie/schema/openai/_base.py:13-44` | data §1, api §6, test §1.1 |
| Prompts are **plain `.txt`** under `mealie/services/openai/prompts/{general,recipes}/`, dotted-name lookup with path-traversal guard. | `mealie/services/openai/openai.py:109` (`PROMPTS_DIR`), `170-204` (loader with `.is_relative_to(PROMPTS_DIR.resolve())` at lines 180-181); `mealie/services/openai/prompts/recipes/parse-recipe-image.txt:1-6` | api §6, history #13, history Implicit conventions |
| `OpenAIService.get_response` catch-all leaks `str(e)` of the upstream exception. | `mealie/services/openai/openai.py:308-309` (`f"OpenAI Request Failed. {e.__class__.__name__}: {e}"`) | api §1, api Sec table, history R8 |
| `OpenAIBase._process_response` **DEBUG-logs the full raw OpenAI response** on parse failure. | `mealie/schema/openai/_base.py:33-35` (`logger.debug(f"Failed to parse OpenAI response as {cls}. Response: {response}")`) | data §1, api Sec table |
| `mealie.core.exceptions.RateLimitError` exists but is **never** translated to HTTP 429. | `mealie/core/exceptions.py:57-62`; controller `handle_exceptions` switch has no 429 branch (`mealie/routes/recipe/recipe_crud_routes.py:90-125`) | api §4, test §4, history R2 |
| No body-size limit, no MIME magic-sniff, and no per-user rate-limiter exist anywhere. | repo-wide grep: pyproject.toml has Pillow (`pyproject.toml:10`) + openai (line 43) but no `python-magic` or `filetype`; routes have no size/magic checks | api §4, test §2.3, history R5 |
| Only `OPENAI_CUSTOM_PROMPT_DIR` survives in `AppSettings`. Other `OPENAI_*` env vars were migrated to DB rows by PR #7650. | `mealie/core/settings/settings.py:418-424`; history #1 (`c3f87736`) | data §5, history #1 |
| `system`/`user` message separation is already structurally correct in `_get_raw_response`. | `mealie/services/openai/openai.py:264-281` | api §6 |
| Only `en-US` locale file may be modified; others are Crowdin-managed. | `.github/copilot-instructions.md` (Translations + Common Gotchas sections) | test §5/§6.3, history R10 |

---

## 2. Conflicts and resolution

| # | Topic | Spec / `input.md` says | Codebase / history says | Resolution (carried into `spec.md`) |
|---|---|---|---|---|
| C1 | **Feature gate** | Env-var `OPENAI_ENABLE_IMAGE_RECIPE` (default false) → 503 | Per-group DB row `image_provider_enabled` → 400 (`recipe_crud_routes.py:320-325`); env-vars were deliberately deprecated by PR #7650 | **Layer both**: env var is a server-wide kill-switch; existing per-group setting is preserved. Both must be true; either falsy → 503. (Input §1 demands env var; we cannot drop it. History #1 (`c3f87736`) deprecated other env vars but `OPENAI_CUSTOM_PROMPT_DIR` survived — same compromise.) |
| C2 | **Endpoint signature** | `image` (singular) — `multipart/form-data` field name `image` | Today: `images: list[UploadFile]` (plural) — set by PR #5590 `95fa0af2`; front-end migrated. | **Accept single `image` per spec; remove multi-image path.** Existing test (`tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py:50-75`) must be ported. Front-end change is out-of-scope (intent §scope.out_of_scope). |
| C3 | **Response body** | Full `Recipe` object (matches `POST /api/recipes`) | `POST /api/recipes/create/image` returns `recipe.slug: str` (line 335); `POST /api/recipes` also returns slug (line 426-448). Only `duplicate_one` (line 450-470) returns full `Recipe`. | **Return full `Recipe`** with `response_model=Recipe` (spec text enumerates title/ingredients/instructions, impossible from slug). Precedent: `duplicate_one`. |
| C4 | **Image retention** | Delete immediately after parse; do NOT put in `assets/` | Current `create_from_images` writes first image as `original.webp` cover (line 354-355). PR #5647 (`4b69e5b3`) added a UI button to select cover. | **Drop cover-persistence** per spec §4 隐私. User can attach a cover later via existing `PUT /api/recipes/{slug}/image` (`recipe_crud_routes.py:635`). Documented as breaking change in spec edge case. |
| C5 | **60s timeout** | ≤60s per call | PR #6227 (`96acc6fc` 2025-09-23) explicitly **removed** the timeout for vision because legitimate large-image calls exceed it. | **Wrap with `asyncio.wait_for(timeout=60)`** at orchestrator only (do not lower the provider-level default 300 of `AIProviderCreate.timeout`); document risk that some legitimate calls may now 422. Spec is explicit; no negotiation room. |
| C6 | **`python-magic`** | "用 `python-magic` 或类似工具检测真实类型" | `python-magic` not in `pyproject.toml`; needs `libmagic` system lib. History `ca9f66ee` (Remove OCR) shows the project rejects native deps. | **Use `filetype` (pure-python) instead** — spec text says "或类似工具" (or similar). Document in NC-002 (see §5). |
| C7 | **`.md` jinja2 prompt template** | "新增 prompt 模板 `mealie/services/openai/prompts/recipe_from_image.md` (jinja2 模板)" | Mealie convention is `.txt` (NOT `.md`), with a custom append-style data-injection composer (NOT Jinja2). | **Use existing convention**: harden in-place `mealie/services/openai/prompts/recipes/parse-recipe-image.txt` (no new file, no Jinja2). Reuses customisation hook from PR #6588 (history #14). |
| C8 | **"严格 JSON 解析 → pydantic"** | New custom parsing | `OpenAIBase.parse_openai_response` already does strict mode (`_base.py:37-44`); structured outputs migration (PR #6964 `570d6f14`) made this universal. | **Reuse existing parser**; orchestrator only catches & swallows the exception (no `str(e)` leak). |
| C9 | **i18n key family** | `recipe.image.feature-disabled / too-large / unsupported-mime / rate-limited` | en-US has only `recipe-image-deleted` (`mealie/lang/messages/en-US.json:8`); none of the spec keys exist. | **Add all 6 keys** (the 4 above + `recipe.image.parse-failed` + `recipe.image.openai-failed` for the 422 branch) to `mealie/lang/messages/en-US.json` only. |
| C10 | **`OPENAI_IMAGE_MODEL` overrides provider model?** | "模型可通过 `OPENAI_IMAGE_MODEL` 环境变量配置, 默认 `gpt-4o-mini`" | Today each `AIProvider` row has its own `model` field (`schema/group/ai_providers.py:15`). | **Env var, when non-empty, overrides `provider.model` only for the image-recipe code path** via `provider.model_copy(update={"model": settings.OPENAI_IMAGE_MODEL})` before passing to `get_response(..., provider=...)`. (Default `"gpt-4o-mini"` per spec.) |

---

## 3. Existing OpenAIService capabilities (what we DO NOT need to add)

| Capability | Surface | Path + line | Notes for re-use |
|---|---|---|---|
| Async OpenAI client per-provider | `OpenAIService.get_client(provider)` | `openai.py:138-145` | Reads `provider.timeout` (default 300s, `ai_providers.py:16`). Keep — we'll layer `asyncio.wait_for(60)` on top. |
| Automatic provider selection based on attachment kind | `OpenAIService._get_provider(attachments)` | `openai.py:147-168` | Raises `OpenAINotEnabledException("No image provider set")` when image provider missing. We translate to 503. |
| Image attachment (base64 JPEG data-URI) | `OpenAILocalImage(filename, path)` | `openai.py:84-94` | Calls `PillowMinifier.to_jpg` internally — **PNG/WEBP get converted to JPEG**. Spec's MIME whitelist of jpeg/png/webp is therefore safe. |
| Structured outputs (`response_format=Schema`) | `OpenAIService._get_raw_response(prompt, content, response_schema, provider)` | `openai.py:264-281` | Uses `client.chat.completions.parse(..., response_format=response_schema)`. System+user message separation is already in place (lines 269-277). |
| Full request/response orchestration | `OpenAIService.get_response(prompt, message, *, response_schema, attachments, provider)` | `openai.py:283-309` | Returns `T \| None` (None on empty choices, line 301-302). Catches `RateLimitError` → re-raises `exceptions.RateLimitError` (306-307); catches all else → leaks `str(e)` (308-309) — orchestrator must wrap. |
| Strict pydantic v2 parse with null-byte scrub | `OpenAIBase.parse_openai_response` | `_base.py:37-44` | Calls `_process_response` which `model_validate_json` (line 32) and on failure DEBUG-logs the raw body (lines 33-35). This is a **secondary leakage point** — fix at log level (see §6.5 of API perspective). |
| Prompt loading with custom-dir override + path-traversal guard | `OpenAIService.get_prompt(name)`, `_get_prompt_file_candidates`, `_load_prompt_from_file` | `openai.py:170-262` | `is_relative_to(PROMPTS_DIR.resolve())` at lines 180-181 already prevents escape. Append-style data injection at 232-262. Reuse as-is. |
| `OpenAIRecipe` → `Recipe` mapper | `OpenAIRecipeService._convert_recipe` | `recipe_service.py:599-622` | No changes — proven mapping logic. |
| Existing image-orchestration entry-point | `OpenAIRecipeService.build_recipe_from_images(images, translate_language)` | `recipe_service.py:624-658` | **Modify in-place** to `build_recipe_from_image(image)` (singular), add `asyncio.wait_for(60)`, sanitize exception messages, retain `_convert_recipe` call (line 654). |
| Per-group image gate | `AIProviderSettingsOut.image_provider_enabled` | `ai_providers.py:127-130` | Reuse — env var is the **additional** AND gate, never a replacement. |
| Canonical `system`/`user` message split | Inside `_get_raw_response` | `openai.py:264-281` | Already prompt-injection-resistant structurally. We only need to add the textual guard inside the prompt body. |

---

## 4. Security pattern reuse map (each row of input.md §4)

| Spec §4 row | Existing pattern? | Path + line | Reuse / Build verdict | Spec FR ID |
|---|---|---|---|---|
| File size ≤ 5 MB → 413 + `recipe.image.too-large` | **None** — no body-size enforcement anywhere | n/a | **Build new**: stream `image.file` in chunks into temp file, abort at 5 MiB + 1; pre-check `request.headers.get("content-length")` as a fast-fail | FR-05 |
| MIME whitelist `image/jpeg|png|webp` → 415 + `recipe.image.unsupported-mime` | Extension-only check | `recipe_crud_routes.py:660-668` (`upload_recipe_asset`) | **Build new**: Content-Type whitelist; reject if not in `{"image/jpeg","image/png","image/webp"}` | FR-06 |
| Real type detection via magic bytes (not Content-Type alone) | **None** (Pillow `.verify()` is the nearest, but is run inside `OpenAILocalImage` only) | n/a | **Build new** with `filetype` (pure-python; see C6 above) | FR-07 |
| Temp storage in `tmp_dir` + UUID filename + immediate delete via try/finally | `get_temporary_path()` context manager (UUID dir + `rmtree` in finally) + `uuid4()` filename idiom | `core/dependencies/dependencies.py:190-198`; `routes/users/images.py:26-39` | **Reuse both verbatim**: wrap orchestrator body in `with get_temporary_path() as temp_path:`; write upload to `temp_path / uuid4().hex` | FR-08, FR-09 |
| Per-user 10/hr → 429 + `recipe.image.rate-limited` | **None** — `RateLimitError` exists but is never HTTP-mapped | `core/exceptions.py:57-62` | **Build new**: `HourlyUserRateLimiter` in-process singleton (`dict[UUID, deque[datetime]]` + `asyncio.Lock`); evict entries older than 1h on touch; raise `exceptions.RateLimitError` when len ≥ 10. Map to 429 in `handle_exceptions` | FR-10 |
| 60s OpenAI timeout | Per-provider `timeout=300` default | `schema/group/ai_providers.py:16` | **Build new** wrapper: `asyncio.wait_for(get_response(...), timeout=60.0)` at orchestrator only (do not change provider default — would regress audio/scrape) | FR-11 |
| OpenAI error / JSON parse / pydantic failure → 422 with **no raw LLM leak** | `get_response` catch-all interpolates `str(e)` → leaks (`openai.py:308-309`); `_base.py:33-35` DEBUG-logs raw response on parse failure | `openai.py:308-309`; `_base.py:33-35` | **Build new**: in orchestrator, wrap all calls in try/except; convert ANY exception to `exceptions.OpenAIServiceError("recipe.image.openai-failed")` (or `recipe.image.parse-failed`) with **no** `str(e)` interpolation; log at WARN with `exc_info=True` but redact LLM body. Map to 422 in `handle_exceptions`. The `_base.py:33-35` DEBUG-log is acceptable only if app log level is INFO or higher in production — document. | FR-15, FR-17, FR-18 |
| Prompt-injection guard in prompt + `system`/`user` separation | Structural split already in place; prompt body has NO guard text | `openai.py:269-277` (structural); `prompts/recipes/parse-recipe-image.txt:1-6` (no guard) | **Reuse structure**; **add a new paragraph** to the existing `.txt` (no new file per C7) stating that text inside images is data, not instructions; instruct LLM to ignore in-image system/jailbreak prompts and to emit a recipe named "Unknown" if no recipe content found | FR-16 |
| Privacy — delete upload after parse, never put in `assets/` | `get_temporary_path()` `rmtree` in finally already deletes; `RecipeDataService.write_image` is the **violation point** at `recipe_service.py:354-355` | `core/dependencies/dependencies.py:196-198`; `recipe_service.py:354-355` | **Reuse** temp helper; **REMOVE** the `data_service.write_image` call (and the now-unused `RecipeDataService` instantiation at line 352) | FR-09, FR-19 |
| Logging — no image bytes/base64, no raw LLM response, only token usage + success/failure | None (today the catch-all leaks via the exception message; `_base.py:34` DEBUG-logs raw body) | `openai.py:308-309`; `_base.py:33-35` | **Build new** logging contract in orchestrator: `logger.info(f"recipe-from-image ok user={user.id} tokens={resp.usage.total_tokens}")` on success; `logger.warning("recipe-from-image failed user=%s reason=%s", user.id, error_key, exc_info=True)` on failure. NEVER `logger.debug(image_bytes)`, NEVER `logger.debug(response.content)` | FR-20 |

---

## 5. Cross-perspective open items rolled into BlockingDecisions

| ID | Topic | Cross-source | Carried into spec as |
|---|---|---|---|
| NC-001 | Should the LLM-generated recipe be **persisted immediately** (current behavior) or **returned as a draft** for the user to review before saving (spec text says "用户审核并保存")? | data §3 (current calls `create_one`), api §2 (response shape), test §1.4 (existing test asserts 201 + GET shows recipe) | **needs_clarification** — recommended default: persist immediately and return full `Recipe`, mirroring today's `POST /api/recipes/create/url` (`recipe_crud_routes.py:173-184`) which also creates immediately. The "review/save" loop is the front-end edit flow on the resulting Recipe page. |
| NC-002 | `python-magic` (libmagic native) vs pure-python `filetype` (vs Pillow `Image.open().verify()`) | api §3+§6 questions, data §6 question, test §6 question, history R5 | **needs_clarification** — recommended default: `filetype==1.2.0` (pure-python, single file, ~30KB; no native deps). Pillow `.verify()` is a deeper integrity check we additionally run via `OpenAILocalImage` for free. Spec text says "或类似工具" giving us latitude. |
| NC-003 | Rate-limit storage layer: in-process `defaultdict` vs DB-backed table | api §4 (Recommendation A), data §3 question, test §6 question | **needs_clarification** — recommended default: in-process `asyncio.Lock`-guarded `dict` (per spec §6 "简单的内存 + DB 计数, 不要求 Redis"); log a startup warning when `settings.UVICORN_WORKERS > 1` (default 1, `settings.py:432`). DB-backed migration deferred. |

---

## 6. Self-concerns (carried into spec)

- **SC-1**: `python-magic` OS dep (libmagic) — Mealie's official Docker image (`docker/Dockerfile`) does not install `libmagic1`. Switching to `filetype` pure-python avoids the operational risk; we adopt that per NC-002.
- **SC-2**: Rate-limit storage layer is per-process — multi-worker (`UVICORN_WORKERS > 1`) deployments will under-count by a factor of N. Per spec §6 ("简单的内存 + DB 计数, 不要求 Redis"), MVP is in-process; mitigation = startup warning.
- **SC-3**: Prompt-injection mitigation is textual only (no model-side guarantee). A determined adversarial image can still produce malicious recipe fields (e.g., XSS in `description`). Existing `cleaner.clean(recipe_data, self.translator)` call at `recipe_service.py:349` already runs on the converted recipe; we keep that to scrub HTML/script. Defense-in-depth.
- **SC-4** (added by history): Re-introducing the 60s timeout reverses PR #6227 (`96acc6fc`); some legitimate large-image vision calls historically exceeded 60s. Mitigation: spec text mandates ≤60s — risk is documented in spec edge case EC-006 and as constraint.
- **SC-5** (added by history): Replacing `images: list[UploadFile]` with `image: UploadFile` is a public-API break of the existing `POST /api/recipes/create/image`. Front-end (`RecipePageParseDialog.vue`) currently sends `images` (plural). The PR will need front-end coordination; this case is backend-only per intent `scope.out_of_scope`.
