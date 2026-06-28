# Test Perspective — case-6 LLM Image-to-Recipe (Mealie)

> Scope: discover what test scaffolding already exists in `C:\Users\v-liyuanjun\Downloads\mealie\tests\` that the case-6 work can/should reuse, plus the gaps that must be closed. All line numbers were verified by inspection on 2026-06-19.

---

## 0. TL;DR cross-check vs. spec

| Spec requirement | Already exists? | Notes |
|---|---|---|
| `POST /api/recipes/create/image` route | **Yes** | Implemented today as `create_recipe_from_image` in `recipe_crud_routes.py:309-335`. Accepts `list[UploadFile]` (multiple images), not a single `image` field. Returns slug, not full Recipe. |
| Mock OpenAI client | **Yes** | Canonical pattern: `monkeypatch.setattr(OpenAIService, "get_response", mock_get_response)` returning `OpenAIRecipe` / `OpenAIText`. |
| Test image fixture | **Yes** | `test_image_jpg` / `test_image_png` session-scoped (`tests/conftest.py:57-63`). |
| AI provider DB fixture | **Yes** | `setup_ai_providers` pattern using `AIProviderCreate` + `AIProviderSettingsUpdate` (see `test_recipe_create_from_image.py:19-32`). |
| Tests for 413 / 415 / 422 / 429 / 503 | **No** | Grep across `tests/` for `status_code == 413/415/429/503` returns zero hits. Only 422 appears (3 hits — all pydantic validation, not size/mime/rate). |
| Env-var toggling pattern | **Yes (in general)** | `monkeypatch.setenv(...)` is widely used for `LDAP_*`, `OIDC_*`, `SMTP_*`, `ALLOW_SIGNUP`. But there is **no precedent of toggling an OpenAI/AI feature via env var** — current code paths are DB-gated. |
| File upload security tests | **Partial** | `test_recipe_image_assets.py` covers path traversal, scriptable extensions, content-disposition. No size or magic-bytes precedent. |

The "current reality" of mealie has already drifted from the spec text: AI configuration was migrated to the DB in PR #7650 (commit `c3f87736`, May 23 2026), so the spec's `OPENAI_ENABLE_IMAGE_RECIPE` / `OPENAI_IMAGE_MODEL` env vars no longer match how the system gates the feature. Tests must therefore decide which side they validate. See §6 *Cross-perspective questions*.

---

## 1. Existing OpenAI integration tests — how they mock the client

### 1.1 `tests/unit_tests/services_tests/test_openai_service.py`
- **Path:** `tests\unit_tests\services_tests\test_openai_service.py`
- **Symbols:** `_make_mock_repos`, `_SettingsStub`, `settings_stub` (pytest fixture), `test_get_prompt_default_only`, `test_get_prompt_custom_dir_used`, `test_get_prompt_custom_empty_falls_back_to_default`, `test_get_prompt_raises_when_no_files`
- **Line ranges (verified):** entire file lines `1-85`. Fixture `settings_stub` lines `28-43`; tests `46-84`.
- **Importance:** ⭐⭐⭐⭐⭐ — only unit-level coverage of `OpenAIService` today. Sets the template for the case-6 unit tests of any new vision helper.
- **Reason / patterns to reuse:**
  - Uses `MagicMock()` to fabricate `provider_settings` + `repos` so `OpenAIService.__init__` is satisfied without touching the DB (lines `10-21`).
  - Patches `PROMPTS_DIR` and `get_app_settings` rather than the FS root, keeping tests hermetic (`37-42`).
  - Demonstrates the *prompt resolution order* (custom dir → default) — the case-6 `recipes/parse-recipe-image.txt` (or whatever the new prompt is named) inherits the same lookup logic, so unit tests for prompt content should follow this scaffolding.

### 1.2 `tests/unit_tests/services_tests/ingredient_parser/test_openai_parser.py`
- **Path:** `tests\unit_tests\services_tests\ingredient_parser\test_openai_parser.py`
- **Importance:** ⭐⭐⭐ — another reference for *how an async OpenAI call is mocked at the service layer*. Confirms `monkeypatch.setattr(OpenAIService, "get_response", ...)` is the project-wide idiom.

### 1.3 `tests/integration_tests/user_recipe_tests/test_recipe_create_from_openai.py`
- **Path:** `tests\integration_tests\user_recipe_tests\test_recipe_create_from_openai.py`
- **Symbols:** `openai_scraper_setup` (autouse fixture, lines `49-66`), `test_create_by_url_via_openai` (`69-95`), `test_create_by_html_or_json_via_openai` (`98-122`), `test_create_stream_via_openai_emits_progress` (`125-149`), `test_create_by_url_openai_returns_none` (`152-170`), `test_create_by_url_openai_openai_disabled` (`173-190`).
- **Line ranges (verified):** `1-190`.
- **Importance:** ⭐⭐⭐⭐⭐ — most directly analogous to the new test suite. Shows:
  1. **Provider DB setup** per test via `unique_user.repos.group_ai_providers.create(AIProviderCreate(...))` and `group_ai_provider_settings.update(...)` (lines `54-60`).
  2. **HTTP-layer mock** — replaces `recipe_scraper_module.DEFAULT_SCRAPER_STRATEGIES` and `safe_scrape_html` so no live network calls happen (lines `52, 65`).
  3. **"OpenAI disabled" path** at line `173-190` returns `400`, **not 503**. This is the existing convention the case-6 spec wants to change.
  4. **Async signature for mock** — every replacement is `async def mock_get_response(self, prompt, message, *args, **kwargs) -> OpenAIText | None`.

### 1.4 `tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py` (the *existing* image route test)
- **Path:** `tests\integration_tests\user_recipe_tests\test_recipe_create_from_image.py`
- **Symbols:** `setup_ai_providers` (autouse module fixture, `19-32`), `test_openai_create_recipe_from_image` (`35-75`).
- **Line ranges (verified):** `1-76`.
- **Importance:** ⭐⭐⭐⭐⭐ — the literal happy-path baseline. Demonstrates:
  - `files={"images": ("test_image_jpg.jpg", f, "image/jpeg")}` upload syntax (note `images` plural).
  - Extra form data `data={"extension": "jpg"}` (this is **unused** by the current route signature; vestige from the prior signature).
  - Asserts `status_code == 201`, then GETs the recipe, then GETs `media_recipes_recipe_id_images_file_name(recipe_id, "original.webp")` — so the test also locks in the side-effect that the uploaded image becomes the recipe cover.
- **Reason / patterns to reuse:** Every new negative-path test (413 / 415 / 422 / 429 / 503) should be added in this same file (or a sibling) using the same `unique_user` + `monkeypatch` plumbing.

### 1.5 `tests/integration_tests/user_recipe_tests/test_recipe_create_from_video.py`
- **Path:** `tests\integration_tests\user_recipe_tests\test_recipe_create_from_video.py`
- **Symbols:** `video_scraper_setup` autouse fixture (`29-50`), `_make_openai_recipe` (`20-26`).
- **Line ranges (verified):** lines `1-80` inspected.
- **Importance:** ⭐⭐⭐⭐ — proves the pattern of *mocking a non-OpenAI download* (`_download_audio`) alongside `OpenAIService.get_response`. The case-6 implementation may need similar dual mocks (e.g., mock a magic-bytes detector + mock the OpenAI call).

---

## 2. Existing file-upload tests — patterns to copy

### 2.1 `tests/integration_tests/user_recipe_tests/test_recipe_image_assets.py`
- **Path:** `tests\integration_tests\user_recipe_tests\test_recipe_image_assets.py`
- **Symbols & line ranges (verified):**
  - `test_recipe_assets_create` (`12-42`) — happy path, `files={"file": data.images_test_image_1.read_bytes()}`.
  - `test_recipe_asset_exploit` (`45-87`) — path traversal mitigation (huntr report). Asserts `400` and that the malicious file was not created on disk.
  - `test_recipe_asset_dangerous_extension_blocked` (`90-104`) — GHSA-gfwc-pjx4-mg9p. Iterates `("html", "svg", "js", "htm", "xhtml")` asserting `400`.
  - `test_recipe_asset_served_as_attachment` (`107-131`) — asserts `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
  - `test_recipe_image_upload` (`134-152`) — happy path for `PUT /api/recipes/{slug}/image`.
- **Importance:** ⭐⭐⭐⭐⭐ — these are the closest analogs to "MIME whitelist" and "size limit" tests the case-6 spec demands. Reuse:
  - Iteration-over-extensions/MIMEs idiom (`for ext in (...)`) for `test_image_unsupported_mime_returns_415`.
  - "Ensure file was not created" disk assertion idiom for *temp-file-cleanup* tests.

### 2.2 `tests/integration_tests/admin_tests/test_admin_backup.py`
- **Path:** `tests\integration_tests\admin_tests\test_admin_backup.py`
- **Importance:** ⭐⭐⭐ — only other example of `files={...}` upload with `archive: UploadFile = File(...)` server side. Shows admin-scoped upload tests but no size/MIME enforcement.

### 2.3 No magic-bytes / size-limit tests exist anywhere
- Grep `tests\` for `python-magic|filetype|magic.from_buffer|413|too-large` → **0 hits**.
- Grep `tests\` for `Content-Length|max_size|413` → **0 hits**.
- This is genuinely uncovered ground; case-6 must invent the pattern.

---

## 3. Existing recipe creation tests — for happy-path scaffolding

### 3.1 `tests/integration_tests/user_recipe_tests/test_recipe_crud.py`
- **Path:** `tests\integration_tests\user_recipe_tests\test_recipe_crud.py` (very large — 1600+ lines).
- **Importance:** ⭐⭐⭐⭐ — *the* reference for asserting on returned `Recipe` JSON (line `1613` does the only 422 assertion in the suite — pydantic field validation, not request body validation). Use as model for shape assertions once the image-create route returns the full `Recipe` (spec §1 expects parity with `POST /api/recipes`).

### 3.2 Helper module `tests/utils/api_routes/__init__.py`
- **Path:** `tests\utils\api_routes\__init__.py`
- **Symbols & line ranges (verified):**
  - `recipes_create_image = "/api/recipes/create/image"` — line `156` (already wired).
  - `recipes_create_url = "/api/recipes/create/url"` — line `158`.
  - `recipes_create_html_or_json = "/api/recipes/create/html-or-json"` — line `152`.
  - `recipes_create_zip = "/api/recipes/create/zip"` — line `164`.
  - `recipes_slug(slug)` — line `505`.
  - `media_recipes_recipe_id_images_file_name(recipe_id, file_name)` — line `445`.
- **Importance:** ⭐⭐⭐⭐⭐ — case-6 tests must use these constants; *do not hard-code URLs*. The file is auto-generated by `task dev:generate` (`dev/code-generation/main.py`), so any new route added must be regenerated rather than hand-edited.

---

## 4. Tests for 413 / 415 / 422 / 429 / 503 patterns

Direct search for these codes across `tests\`:

| Code | Occurrences | Where |
|------|-------------|-------|
| 413 | 0 | — none. |
| 415 | 0 | — none. |
| 422 | 3 | All pydantic field validation: `test_group_cookbooks.py:80`, `test_group_recipe_actions.py:233`, `test_recipe_crud.py:1613`, `test_group_seeder.py:11`. None gate on uploaded-file shape. |
| 429 | 0 | — none. No HTTP exception handler converts `mealie.core.exceptions.RateLimitError` into 429 today. |
| 503 | 0 | — none. The "feature disabled" idiom in mealie returns **400** (see `recipe_crud_routes.py:322-325` and `test_recipe_create_from_openai.py:173-190`). |

**Implication:** all five status-code expectations in the spec are *new* test patterns. The case-6 implementation will not just add tests — it will also have to *add the HTTP-exception machinery* (custom exception handlers, or explicit `raise HTTPException(status_code=…)` calls) for the route handler to actually produce 413/415/429/503. Today nothing in `mealie\routes\handlers.py` or `mealie\core\exceptions.py:73-83` (`mealie_registered_exceptions`) maps to those codes. `RateLimitError` is defined (`exceptions.py:57-62`) but is **only ever swallowed inside scrapers** (`mealie\services\scraper\scraper_strategies.py:552, 578`) — never propagated to the HTTP layer.

---

## 5. Env-var toggling in tests

### 5.1 Pattern: `monkeypatch.setenv("NAME", "value")`
Used widely; key examples (verified):
- `tests/integration_tests/user_tests/test_user_registration.py:16` — `monkeypatch.setenv("ALLOW_SIGNUP", "False")`.
- `tests/unit_tests/test_security.py:107-112` — LDAP envs.
- `tests/unit_tests/test_config.py:14-17, 41, 56-64, 168-169, 296, 368, 386` — broad `AppSettings` env testing.
- `tests/unit_tests/services_tests/test_email_service.py:28-49` — SMTP envs incl. `SMTP_HOST=""` to disable email.
- `tests/unit_tests/core/security/providers/test_openid_provider.py:50-205` — OIDC envs.

### 5.2 Pattern: monkeypatch the cached settings object
Used in `tests/unit_tests/services_tests/test_openai_service.py:42`:
```python
monkeypatch.setattr(openai_module, "get_app_settings", _fake_get_app_settings)
```
This avoids re-instantiating `AppSettings()` (which is a cached singleton — see `.github/copilot-instructions.md`: *"Never instantiate `AppSettings()` directly"*).

### 5.3 Session-global env in `tests/conftest.py`
Lines `19-22` use a module-level `MonkeyPatch` to set `PRODUCTION`, `TESTING`, `ALLOW_SIGNUP` **before** `mealie.app` is imported. **Critical:** any new env var that affects `AppSettings` field defaults must be set here (or via per-test `monkeypatch.setenv` + cache invalidation) before the app is initialised, otherwise the cached settings will already be wrong.

### 5.4 Missing today
- No test sets/clears an `OPENAI_*` env var. `OPENAI_CUSTOM_PROMPT_DIR` (the only remaining OpenAI env var per `settings.py:420`) is exercised only by patching `_SettingsStub.OPENAI_CUSTOM_PROMPT_DIR` directly — not via env.
- No fixture invalidates the `get_app_settings` LRU cache, so simply doing `monkeypatch.setenv(...)` after `mealie.app` is imported will not pick up. The case-6 tests must either patch `openai_module.get_app_settings` (as in §5.2) **or** call `get_app_settings.cache_clear()` after `setenv`.

---

## 6. Test scaffolding plan for case-6

> Listed as concrete TODO items in execution order. Verified file paths above.

### 6.1 New / updated test files

| File | Action | Notes |
|------|--------|-------|
| `tests/unit_tests/services/openai/test_vision.py` | **Create** | Mirror `test_openai_service.py` style. Use `MagicMock` repos + `monkeypatch.setattr(openai_module, "get_app_settings", ...)`. Cover: vision prompt loading, attachment construction (`OpenAILocalImage.get_image_url` already at `openai.py:84-94`), JSON parse-failure path through `OpenAIRecipe.parse_openai_response` (`_base.py:29-44`). |
| `tests/unit_tests/services/recipe/test_recipe_from_image.py` | **Create** | Service-layer orchestrator tests. Mock `OpenAIService.get_response` to return crafted `OpenAIRecipe` (happy), `None` (→ 422), and to raise `asyncio.TimeoutError` (→ 422). Use `recipe_ingredient_only` fixture style for inputs. |
| `tests/integration_tests/test_recipe_from_image_route.py` (or extend existing `test_recipe_create_from_image.py`) | **Extend existing** | Add: `test_image_too_large_returns_413`, `test_image_unsupported_mime_returns_415`, `test_image_mime_spoofed_returns_415` (Content-Type says jpeg, magic bytes say HTML), `test_feature_flag_disabled_returns_503`, `test_unauthenticated_returns_401`, `test_per_user_rate_limit_returns_429`, `test_temp_files_cleaned_on_success`, `test_temp_files_cleaned_on_failure`. |

> Adding to the existing file is preferable to creating a new sibling file, because the autouse `setup_ai_providers` fixture (`test_recipe_create_from_image.py:19-32`) already establishes the AI-provider DB state every other test depends on.

### 6.2 Reusable building blocks

```python
# canonical mock — async, *args/**kwargs so signature drift doesn't break it
async def mock_get_response(self, prompt: str, message: str, *args, **kwargs):
    return OpenAIRecipe(name=..., ingredients=[...], instructions=[...])

monkeypatch.setattr(OpenAIService, "get_response", mock_get_response)
```

```python
# canonical upload — multipart/form-data, single image
with open(test_image_jpg, "rb") as f:
    r = api_client.post(
        api_routes.recipes_create_image,
        files={"images": ("photo.jpg", f, "image/jpeg")},
        headers=unique_user.token,
    )
```

```python
# canonical temp-file cleanup probe — list app_dirs.TEMP_DIR before/after request
from mealie.core.config import get_app_dirs
before = set(get_app_dirs().TEMP_DIR.rglob("*"))
... # do request
after = set(get_app_dirs().TEMP_DIR.rglob("*"))
assert after == before, f"Leaked files: {after - before}"
```

### 6.3 Things the test plan must NOT do

- **Do not** depend on a real `OPENAI_API_KEY`. AI provider rows use `api_key="test-key"` (see `test_recipe_create_from_image.py:23` and `test_recipe_create_from_openai.py:55`). The fake key is harmless because `OpenAIService.get_response` is monkey-patched before any HTTP call.
- **Do not** add new locales — only `mealie/lang/messages/en-US.json` may be touched for any new i18n keys (`.github/copilot-instructions.md`: *"Only modify `en-US` locale files when adding new translation strings — other locales are managed via Crowdin and **must never be modified**"*).
- **Do not** hand-edit `tests/utils/api_routes/__init__.py`. If the route URL changes, regenerate via `task dev:generate` (`.github/copilot-instructions.md` §Code generation).
- **Do not** create a new image fixture; reuse `test_image_jpg`, `test_image_png` (`tests/conftest.py:57-63`) — and synthesise oversized / wrong-MIME bytes inline with `io.BytesIO`.

---

## 7. OpenAI mock strategy (consolidated)

| Layer | What to mock | How | Why |
|-------|--------------|-----|-----|
| **Outermost (integration)** | `OpenAIService.get_response` | `monkeypatch.setattr(OpenAIService, "get_response", mock_get_response)` returning `OpenAIRecipe` or raising. | Project convention. Avoids any network call and bypasses `AsyncOpenAI` construction. |
| **Middle (service unit)** | `OpenAIService` constructor | Inject a `MagicMock()` repos object (template at `test_openai_service.py:10-21`). | Avoids the DB; lets you test `build_recipe_from_images`-style orchestration with crafted responses. |
| **Innermost (raw client)** | `AsyncOpenAI.chat.completions.parse` | `monkeypatch.setattr(openai_module, "AsyncOpenAI", FakeClient)` returning a `ChatCompletion` with a `choices[0].message.content` string. | Use **only** for tests of `_get_raw_response` itself (currently uncovered). All other tests should mock at the `get_response` layer for stability against OpenAI SDK churn (note: openai package upgraded from v1 → v2.41.1 over the last year — see history perspective). |
| **Error injection** | `openai.RateLimitError`, `openai.APITimeoutError`, generic `Exception` | Inside the patched `get_response`, `raise openai.RateLimitError(...)`. | `openai.py:306-309` already catches `RateLimitError` and re-raises `exceptions.RateLimitError`. To exercise the 422 path the case-6 spec wants for "JSON parse / API failure", raise `Exception("bad json")` from the mock; the service wraps it via `Exception("OpenAI Request Failed. ...")` (line `308-309`). |
| **Vision-specific** | `OpenAILocalImage` | Not necessary to mock — its `get_image_url` *will* run `PillowMinifier.to_jpg` on the uploaded bytes. Either pass the existing JPEG/PNG fixtures, or `monkeypatch.setattr(OpenAILocalImage, "get_image_url", lambda self: "data:image/jpeg;base64,AAAA")`. | Pillow can fail on synthetic bytes used for size/MIME negative tests, polluting failure mode. Patch when the test isn't *about* image conversion. |

**Async caveat:** every replacement of `OpenAIService.get_response` must be `async def`. The route is `async` (`recipe_crud_routes.py:310`), so a sync mock will silently return a coroutine that never awaits and the test will hang/fail confusingly.

**Avoid:** patching `openai.AsyncOpenAI` directly at import time inside `mealie.services.openai.openai` — `OpenAIService.__init__` does **not** create a client (deferred to `get_client`), so the patch site that matters is the call-chain (`get_response → _get_raw_response → get_client → AsyncOpenAI(...)`). All four existing integration tests sidestep this by patching at `get_response` instead.

---

## 8. Cross-perspective questions

1. **Feature-flag mechanism — env var vs DB?** Spec demands `OPENAI_ENABLE_IMAGE_RECIPE` env, but the current implementation (post PR #7650, commit `c3f87736`) gates on `group_ai_provider_settings.image_provider_id`. Which wins? If both, in what precedence? *History should reveal the rationale behind the migration to DB-stored config.*
2. **HTTP status code drift.** Existing image route returns **400** when image provider is unset; spec wants **503**. Existing OpenAI-failure path returns **400** (or wraps in `Exception`); spec wants **422**. Are we changing the public contract of an existing route? If yes, who is the front-end caller, and will it cope with the new codes?
3. **`python-magic` dependency.** Not currently in `pyproject.toml` (verified line `41-43` shows `pillow-heif` and `openai` but no `python-magic` or `filetype`). Adding a binary-dependent lib (libmagic) has Docker base-image implications. *History should show whether magic-bytes detection was previously rejected.*
4. **Rate-limit primitive.** No per-user rate-limiter exists. Spec says "simple memory + DB counter". Is there a precedent we should follow (login-attempt counter? `SECURITY_MAX_LOGIN_ATTEMPTS` at `settings.py:215`)? *History should show whether any prior PR attempted throttling.*
5. **Image retention.** The existing `create_from_images` (`recipe_service.py:354-355`) deliberately keeps the first uploaded image and writes it as the cover with `data_service.write_image(f.read(), "webp")`. The spec says "delete after parse, do not store in assets". This is a contradiction — *did the original author intend cover persistence as a feature, and would removing it break an existing UI workflow?*
6. **Multiple-images endpoint signature.** Today: `images: list[UploadFile]`. Spec: `image: UploadFile` (single). If we honour the spec we break the existing `test_openai_create_recipe_from_image` test fixture (line `59`: `files={"images": (...)}`). Plan: bridge by accepting both for one release, or rev the endpoint?
7. **Where does the 60-second timeout come from?** Spec says ≤60s per call. Today (commit `96acc6fc`) "Remove explicit timeout from OpenAI image API Call" — the explicit timeout was *deleted* a year ago for image calls. Re-introducing it is a behaviour reversal. *History should explain why the explicit timeout was removed.*
