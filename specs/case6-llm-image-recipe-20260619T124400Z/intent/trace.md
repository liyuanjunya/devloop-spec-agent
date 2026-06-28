# Intent Trace — Case 6 LLM Image → Recipe

## 1. How I classified `intent_type` = `add_feature`

The request explicitly creates a new HTTP endpoint (`POST /api/recipes/create/image`), new env vars (`OPENAI_ENABLE_IMAGE_RECIPE`, `OPENAI_IMAGE_MODEL`), and a new business flow (Vision-API photo → structured Recipe). Per `input.md §1 新接口` and `§2 实现策略`. Even though some scaffolding already exists in the repo (see §3 below), the **contract being asked for is new** and is treated as a feature add.

## 2. Why aspects `security` + `external_integration` (and `refactor_existing` as a tertiary)

### security (heavy)
`input.md §4 安全约束` is an explicit, numbered, **mandatory** 10-row table — not "consider", but "必须实现, 不是可选". Items include:

| # | Constraint | Where it shows up in input.md |
|---|------------|-------------------------------|
| 1 | ≤ 5 MB → 413 + `recipe.image.too-large` | §4 文件大小 |
| 2 | MIME whitelist (jpeg/png/webp) → 415 + `recipe.image.unsupported-mime` | §4 MIME 类型白名单 |
| 3 | Real-type detection via python-magic (not Content-Type header trust) | §4 文件类型实际检测 |
| 4 | tmp_dir + UUID filename + immediate delete | §4 临时存储路径 |
| 5 | ≤ 10/user/hour → 429 + `recipe.image.rate-limited` | §4 OpenAI 调用限流 |
| 6 | ≤ 60 s OpenAI timeout | §4 OpenAI 调用超时 |
| 7 | OpenAI/JSON/pydantic failure → 422 + i18n; never leak raw LLM | §4 错误处理 |
| 8 | Prompt-injection defense in template; system/user separation | §4 Prompt injection 防护 |
| 9 | try/finally delete; do NOT persist into `assets/` | §4 隐私 |
| 10 | Don't log image bytes/base64 or raw LLM body | §4 日志 |

Plus `input.md §7 CR 关注点` re-states 8 attack vectors. So `security` is co-equal with the feature itself.

### external_integration
The whole point of the feature is calling OpenAI's Vision API. `input.md §2 实现策略` mandates **reuse** of `mealie/services/openai/openai.py`'s `OpenAIService` rather than instantiating a new client. Verified existence of that abstraction:

- `mealie/services/openai/openai.py:108-145` — `OpenAIService.__init__` loads per-group providers from `repos.group_ai_provider_settings.get_one(...)` and `_get_provider` (lines 147-168) routes to `image_provider` if any attachment is an `OpenAIImageBase`.
- `mealie/services/openai/openai.py:84-94` — `OpenAILocalImage` already base64-encodes a local file via `PillowMinifier.to_jpg` and wraps it as a `data:image/jpeg;base64,...` URL.
- `mealie/services/openai/openai.py:283-309` — `get_response(...)` is the call site we'll wrap with a 60 s `asyncio.wait_for` and stricter exception handling.

### refactor_existing (tertiary)
Walking the route tree to verify the endpoint is new, I found `mealie/routes/recipe/recipe_crud_routes.py:309-335` **already implements** `POST /api/recipes/create/image`, but with materially different semantics:

| Aspect | Existing (lines 309-335 + service:335-356) | Spec asks for |
|--------|--------------------------------------------|---------------|
| Body | `images: list[UploadFile]` (multi) | `image: UploadFile` (single) |
| Response | `return recipe.slug` (str) | full `Recipe` object |
| Feature gate | per-group `ai_provider_settings.image_provider_enabled` → 400 | env-var `OPENAI_ENABLE_IMAGE_RECIPE` → 503 |
| Size cap | none | 5 MB → 413 |
| MIME check | none | jpeg/png/webp + magic-sniff → 415 |
| Temp filename | `Path(image.filename).name` (user-controlled, only basename'd) at `recipe_service.py:340` | UUID, never user-supplied |
| Rate limit | none | per-user/h ≤ 10 → 429 |
| Timeout | provider default 300 s | hard 60 s |
| Prompt-injection guard | none in `parse-recipe-image.txt:1-6` | explicit guard required |
| Image lifecycle | written to recipe assets via `data_service.write_image(...)` at `recipe_service.py:354-355` | immediate delete; **must NOT** persist to `assets/` |

So this is partly a refactor — but because the contract on the wire changes (single vs list, body shape) and the security envelope is brand-new, classifying as `add_feature` (primary) + `refactor_existing` (tertiary) is the most honest framing. Calling it pure refactor would understate the new contract; calling it pure feature would hide that real code needs to be untangled.

## 3. Why I verified each claim from `mealie/services/openai/`

I opened:
- `mealie/services/openai/__init__.py` — confirms `OpenAIService`, `OpenAILocalImage`, `OpenAIImageExternal`, `OpenAINotEnabledException`, `OpenAIDataInjection` are the public surface.
- `mealie/services/openai/openai.py` — full read, 347 lines. Image input is already first-class; the gap is the safety envelope, not the LLM plumbing.
- `mealie/services/openai/prompts/` — directory listing shows `recipes/parse-recipe-image.txt` already exists (6 lines). The spec says "新增 prompt 模板 recipe_from_image.md" but the established convention is `.txt` under `recipes/` (`OpenAIService._get_prompt_file_candidates` at `openai.py:170-204` uses dot notation + `.txt` extension). I interpret the spec's `.md` filename as illustrative; harden the existing `.txt` file instead, matching the convention.

## 4. Why I added `OPENAI_IMAGE_MODEL` to scope

`input.md §2` says "模型可通过 `OPENAI_IMAGE_MODEL` 环境变量配置, 默认 `gpt-4o-mini`". The current `OpenAIService` reads model from `provider.model` (`openai.py:279`), which is per-group, per-provider record (`schema/group/ai_providers.py:15`). The env var needs to **override** the provider's `model` when set, only for the image-recipe code path. This is a small but easy-to-miss requirement and warrants its own AC.

## 5. Assumptions I made (and would flag in spec review)

1. **python-magic vs filetype** — the spec literally names `python-magic`, but on Windows it requires `python-magic-bin` and on Linux `libmagic1`. The `pyproject.toml:8-50` has neither today. I'm proposing `filetype` (pure-python) as a safer cross-platform default and noting the trade-off. The repository convention (per `.github/copilot-instructions.md`) is "always use uv" for adding deps.
2. **Coexistence vs replacement** of the existing `POST /api/recipes/create/image` — I'm proposing a replace-in-place, porting `tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py:35-76` to the new contract. The old multi-image variant is undocumented and the new spec is explicit about single image.
3. **In-memory rate limit** — fine for default single-worker deployments, but breaks under `UVICORN_WORKERS > 1` (see `mealie/core/settings/settings.py:432`). Acceptable for MVP per spec §6 and §6 implementation constraint, but documented as a known limitation in the design doc.
4. **Keep per-group `image_provider_enabled` AND add env var** — both must be true (logical AND). The env var is a global kill switch; the per-group setting is an admin opt-in. Disabling either disables the route (env-off returns 503 with the new i18n key; per-group-off returns the existing 503/400 with the existing key, preserved for backward compatibility).

## 6. Files I read to write this intent (audit trail)

- `mealie/services/openai/openai.py` (all)
- `mealie/services/openai/__init__.py`, `prompts/recipes/parse-recipe-image.txt`, `prompts/recipes/scrape-recipe.txt`, `prompts/recipes/parse-recipe-ingredients.txt`, `prompts/general/transcribe-audio.txt`
- `mealie/schema/openai/recipe.py`, `_base.py`, `general.py`
- `mealie/schema/recipe/recipe.py`, `recipe_ingredient.py`, `recipe_step.py`
- `mealie/services/recipe/recipe_service.py` (selected ranges: 1-100, 100-200, 200-460, 580-660)
- `mealie/services/recipe/recipe_data_service.py` (all)
- `mealie/routes/recipe/recipe_crud_routes.py` (selected: 1-200, 290-345, 650-700)
- `mealie/routes/recipe/_base.py`
- `mealie/routes/_base/base_controllers.py`
- `mealie/routes/handlers.py`
- `mealie/routes/admin/admin_debug.py`, `mealie/routes/admin/admin_backups.py`, `mealie/routes/users/images.py`, `mealie/routes/groups/controller_group_ai_providers.py`
- `mealie/core/settings/settings.py`, `mealie/core/settings/directories.py`, `mealie/core/dependencies/dependencies.py`, `mealie/core/exceptions.py`
- `mealie/schema/group/ai_providers.py`
- `mealie/pkgs/img/minify.py`
- `mealie/lang/messages/en-US.json` (header + recipe section, grepped for image/openai/rate/disabled keys)
- `pyproject.toml`
- `tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py` (existing test for the legacy endpoint)
- `tests/utils/api_routes/__init__.py:156-157` (existing route constant)
