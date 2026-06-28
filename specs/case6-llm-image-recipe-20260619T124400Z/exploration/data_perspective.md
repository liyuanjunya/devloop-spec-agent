# Data Perspective — Case 6 LLM Image → Recipe

Scope: schemas, persistence layout, and configuration that constrain the data-shape contract between OpenAI's response and Mealie's `Recipe` record. All line ranges below were re-verified against the working copy at `C:\Users\v-liyuanjun\Downloads\mealie\`.

---

## 1. LLM-output contract (`OpenAIRecipe` pydantic v2 schema)

| Field | Path | Symbols | Line range (verified) | Importance | Why it matters |
|-------|------|---------|------------------------|------------|----------------|
| The structured-output target the LLM JSON MUST conform to | `mealie/schema/openai/recipe.py` | `OpenAIRecipe`, `OpenAIRecipeIngredient`, `OpenAIRecipeInstruction`, `OpenAIRecipeNotes` | 6-89 | ★★★ critical | Spec §2 says the LLM must return JSON matching mealie's `RecipeBase`. This schema is already the strict-mode target passed to `client.chat.completions.parse(..., response_format=OpenAIRecipe)` (see API perspective). Reusing it satisfies "真正复用 OpenAIService". Field-by-field surface: `name: str` (required), `description: str \| None`, `recipe_yield: str \| None`, `total_time/prep_time/perform_time: str \| None`, `ingredients: list[OpenAIRecipeIngredient]`, `instructions: list[OpenAIRecipeInstruction]`, `notes: list[OpenAIRecipeNotes]`. |
| Base class with strict-mode parsing + null-byte scrub | `mealie/schema/openai/_base.py` | `OpenAIBase.parse_openai_response`, `_preprocess_response`, `_process_response`, `RE_NULLS` | 13-44 | ★★★ critical | `parse_openai_response` is the choke point that converts LLM text → typed object. On any pydantic failure it logs only at DEBUG and re-raises (line 33-35) — the **call site is what determines whether the raw text reaches the client**. Spec §4 forbids leaking raw LLM body, so our orchestrator must catch the exception, swallow `str(e)` (which contains LLM text fragments), and surface a generic 422 + i18n key. |

---

## 2. Target persistence schema (`Recipe` Pydantic + ORM relationships)

| Field | Path | Symbols | Line range (verified) | Importance | Why it matters |
|-------|------|---------|------------------------|------------|----------------|
| The Pydantic schema the saved recipe must match | `mealie/schema/recipe/recipe.py` | `Recipe`, `RecipeSummary`, `create_recipe_slug` | 40-58 (slug helper), 116-175 (RecipeSummary class body), 182-393 (Recipe + validators + loader_options) | ★★★ critical | `Recipe` is what the new endpoint must return (spec §1 says "响应格式与现有 POST /api/recipes 一致"). Note that `RecipeSummary` carries `user_id/household_id/group_id` with `default_factory=uuid4` (lines 120-122) — these get **overwritten** by `RecipeService._recipe_creation_factory` (recipe_service.py:163-187). Our orchestrator must NOT bypass that factory or we'll persist a recipe with a random group. |
| Per-ingredient sub-schema with quantity/unit/food normalization | `mealie/schema/recipe/recipe_ingredient.py` | `RecipeIngredient`, `RecipeIngredientBase`, `RecipeIngredient.validate_quantity` | 191-323 (Base), 330-357 (RecipeIngredient), 345-357 (quantity validator) | ★★ high | `OpenAIRecipe.ingredients` is `list[OpenAIRecipeIngredient]` with only `title` + `text`. The mapper at `recipe_service.py:611-615` converts them to `RecipeIngredient(title=..., note=ingredient.text)` — meaning the LLM-extracted text lands in `note`, NOT parsed into `quantity/unit/food`. That is **intentional** (the dedicated parser-service is separate) and the new endpoint must keep this behavior so we don't double-parse and corrupt quantities. |
| Per-step sub-schema | `mealie/schema/recipe/recipe_step.py` | `RecipeStep`, `IngredientReferences` | 8-14 (refs), 17-23 (step) | ★ medium | `OpenAIRecipeInstruction.text` → `RecipeStep.text`; `title` → `RecipeStep.title`. `RecipeStep.id` defaults to `uuid4` (line 18) and `ingredient_references` defaults to `[]`. No surprises. |
| The `OpenAIRecipe → Recipe` mapper (already exists) | `mealie/services/recipe/recipe_service.py` | `OpenAIRecipeService._convert_recipe` | 599-622 | ★★★ critical | Verified the existing conversion: name → name, description → description, recipe_yield → recipe_yield, total_time/prep_time/perform_time pass-through, ingredients → `RecipeIngredient(title=..., note=ingredient.text)` filtered by `if ingredient.text`, instructions → `RecipeStep(title=..., text=instruction.text)` filtered by `if instruction.text`, notes → `RecipeNote(title=note.title or "", text=note.text)` filtered by `if note.text`. **Reuse as-is** — no changes needed to the mapper logic; only the orchestration around it needs hardening. |

---

## 3. Recipe-creation service (DB write path)

| Field | Path | Symbols | Line range (verified) | Importance | Why it matters |
|-------|------|---------|------------------------|------------|----------------|
| The single creation entry point for recipes — must reuse | `mealie/services/recipe/recipe_service.py` | `RecipeService.create_one`, `_recipe_creation_factory` | 202-245 (create_one), 163-187 (factory) | ★★★ critical | Comment at line 163-167 is explicit: "The main creation point for recipes. The factor method returns an instance of the Recipe Schema class with the appropriate defaults set. **Recipes should not be created elsewhere to avoid conflicts.**" So our orchestrator must call `RecipeService.create_one(recipe)` after `_convert_recipe(openai_recipe)`. `create_one` also: (a) injects per-household RecipeSettings (208-218), (b) creates a user-rating row if rating present (225-233), (c) emits a timeline event (236-244). |
| The existing image-orchestration service (will be refactored) | `mealie/services/recipe/recipe_service.py` | `OpenAIRecipeService.build_recipe_from_images`, `RecipeService.create_from_images` | 598-658 (OpenAI service), 335-356 (caller in RecipeService) | ★★★ critical | Today it: (1) constructs `OpenAILocalImage` per file, (2) calls `openai_service.get_response(prompt, message, response_schema=OpenAIRecipe, attachments=...)` (line 641-646), (3) on any exception wraps with generic message (line 650-651), (4) converts result (654). The caller (`create_from_images`, 335-356) writes the **first** image into the recipe's assets directory via `data_service.write_image(..., "webp")` (line 354-355) — **this violates spec §4 隐私** which requires immediate delete and forbids `assets/` persistence. The new flow must **drop** that `write_image` step. |

---

## 4. File / asset storage layout (`tmp_dir`, `assets/`, `data_dir`)

| Field | Path | Symbols | Line range (verified) | Importance | Why it matters |
|-------|------|---------|------------------------|------------|----------------|
| Where temp uploads, recipe data, and assets live | `mealie/core/settings/directories.py` | `AppDirectories` | 4-37 | ★★★ critical | Defines: `DATA_DIR`, `BACKUP_DIR`, `USER_DIR`, `RECIPE_DATA_DIR` (used by `Recipe.directory_from_id`, recipe.py:202-204), `TEMPLATE_DIR`, `GROUPS_DIR`. Lines 14-17 are key: `_TEMP_DIR = data_dir.joinpath(".temp")` exposed via `TEMP_DIR` property (line 24-25). Note the dunder comment "# Deprecated" at line 14 — `TEMP_DIR` is the **only** sanctioned scratch location today. `ensure_directories` (27-37) **does NOT** create `_TEMP_DIR` on startup, so callers using `get_temporary_path()` must rely on it being created lazily inside the helper (it is — see next row). |
| UUID-based temp-dir context manager that handles cleanup | `mealie/core/dependencies/dependencies.py` | `get_temporary_path`, `get_temporary_zip_path` | 180-198 (both helpers) | ★★★ critical | `get_temporary_path()` (191-198) creates `TEMP_DIR/{uuid4().hex}/`, yields it, and `rmtree(temp_path)` in `finally` if `auto_unlink=True` (default). This satisfies spec §4 "临时存储路径必须在 mealie 配置的 tmp_dir 下" + "处理完立即删除". **However**, the directory is UUID, but the FILE inside it still inherits the user's filename if the caller uses `image.filename`. We must use `uuid4().hex` (no extension trust) when writing the actual upload file. |
| Persistent recipe asset / image directories | `mealie/services/recipe/recipe_data_service.py` | `RecipeDataService.__init__`, `write_image`, `delete_image`, `dir_data/dir_image/dir_assets` | 57-77 (init + dir setup), 85-109 (write_image — which calls `Minifier.minify` and atomically unlinks corrupt output), 111-117 (delete_image) | ★★★ critical | This is the API the **legacy** flow uses at recipe_service.py:354 (`data_service.write_image(f.read(), "webp")`). Spec §4 隐私 explicitly says the uploaded image MUST NOT land in `assets/` — so the new orchestrator **must not** instantiate `RecipeDataService` for the uploaded image. The created recipe will have no associated image until the user uploads one via the existing `PUT /api/recipes/{slug}/image` route (recipe_crud_routes.py:635). |

---

## 5. Application configuration / settings module (where `OPENAI_*` env vars get parsed)

| Field | Path | Symbols | Line range (verified) | Importance | Why it matters |
|-------|------|---------|------------------------|------------|----------------|
| Where ALL `OPENAI_*` env vars are declared | `mealie/core/settings/settings.py` | `AppSettings.OPENAI_CUSTOM_PROMPT_DIR`, `AppSettings` class body, `app_settings_constructor` | 123-449 (class body), 417-424 (the entire current OpenAI block — just one setting), 451-477 (constructor) | ★★★ critical | Verified: today the OpenAI section is **only** `OPENAI_CUSTOM_PROMPT_DIR: str \| None = None`. Adding `OPENAI_ENABLE_IMAGE_RECIPE: bool = False` and `OPENAI_IMAGE_MODEL: str = "gpt-4o-mini"` must go in this section (around line 424). Pattern reference: the existing `LDAP_AUTH_ENABLED: bool = False` (325) + `LDAP_FEATURE` computed property (339-357) shows the **idiomatic Mealie pattern**: a raw bool env var + a `FeatureDetails` computed property used elsewhere (e.g. `LDAP_FEATURE.enabled`). We should add an analogous `OPENAI_IMAGE_RECIPE_FEATURE` property that ANDs the env var with per-group `image_provider_enabled` check so callers have one place to ask "is this feature actually usable for this request?". |
| Per-group AI provider configuration (already-existing image-provider gate) | `mealie/schema/group/ai_providers.py` | `AIProviderCreate`, `AIProviderOut`, `AIProviderSettingsOut`, `AIProviderSettingsOut.image_provider_enabled` | 11-37 (Create with `timeout: int = 300`, line 16), 47-64 (Out), 100-139 (SettingsOut with `image_provider_enabled` property at 128-130) | ★★ high | The per-group setting `image_provider_enabled` returns `self.ai_enabled and self.image_provider_id is not None` (lines 128-130). Today this is the ONLY gate. The new env var must compose with it (logical AND). Also note `AIProviderCreate.timeout: int = 300` (line 16) — default OpenAI timeout is **300 s**, but spec §4 mandates ≤60 s for image-recipe specifically. We CANNOT lower the provider-level timeout without affecting other AI flows; instead the orchestrator must wrap the call in `asyncio.wait_for(..., timeout=60.0)`. |
| Constructor wiring | `mealie/core/settings/settings.py` | `app_settings_constructor` | 451-477 | ★ medium | No changes needed here — `pydantic_settings.BaseSettings` auto-picks up new fields from env. But verify with `task py:check` that the OpenAPI export at `mealie/app.py` includes the new fields. |

---

## Pydantic schema that LLM JSON must conform to

**`mealie/schema/openai/recipe.py:45-89`** — `OpenAIRecipe`:

```python
class OpenAIRecipe(OpenAIBase):
    name: str                                     # required
    description: str | None = None
    recipe_yield: str | None = None
    total_time: str | None = None
    prep_time: str | None = None
    perform_time: str | None = None
    ingredients: list[OpenAIRecipeIngredient]     # each: {title?, text}
    instructions: list[OpenAIRecipeInstruction]   # each: {title?, text}
    notes: list[OpenAIRecipeNotes]                # each: {title?, text}
```

Passed to OpenAI as `response_format=OpenAIRecipe` (verified at `mealie/services/openai/openai.py:280`). This forces strict-schema decoding on the OpenAI side; on the Mealie side `OpenAIBase.parse_openai_response` (`_base.py:37-44`) re-validates with `model_validate_json` (line 32). Any deviation → `ValidationError`.

**Mapping (already implemented at `recipe_service.py:599-622`):**

| OpenAIRecipe → | Recipe (Mealie persistence schema) |
|---|---|
| `name` | `name` (also feeds `slug` via `create_recipe_slug`) |
| `description` | `description` |
| `recipe_yield` | `recipe_yield` |
| `total_time / prep_time / perform_time` | same names |
| `ingredients[].text` | `recipe_ingredient[].note` (NOT parsed into qty/unit/food — left to parser-service) |
| `ingredients[].title` | `recipe_ingredient[].title` |
| `instructions[].text` | `recipe_instructions[].text` |
| `instructions[].title` | `recipe_instructions[].title` |
| `notes[].text` | `notes[].text` |
| `notes[].title` | `notes[].title` (defaults to "") |

Fields **not** populated by the LLM and left to `RecipeService._recipe_creation_factory` defaults: `user_id`, `household_id`, `group_id`, `id`, `slug` (auto-derived), `tags`, `recipe_category`, `tools`, `assets` (empty), `settings` (household preferences), timeline event.

---

## Storage paths used today

| Purpose | Path | How accessed | Used by |
|---------|------|--------------|---------|
| Scratch temp uploads | `<DATA_DIR>/.temp/<uuid>/` | `get_temporary_path()` ctx mgr (`dependencies.py:191-198`) → `app_dirs.TEMP_DIR.joinpath(uuid4().hex)` | All upload endpoints (recipe zip, recipe image, user image, OpenAI debug) |
| Permanent recipe data root | `<DATA_DIR>/recipes/<recipe_id>/` | `Recipe.directory_from_id(id)` (`schema/recipe/recipe.py:202-204`) → `app_dirs.RECIPE_DATA_DIR.joinpath(str(recipe_id))` | All recipe-bound assets |
| Recipe images | `<DATA_DIR>/recipes/<recipe_id>/images/original.{ext}` | `RecipeDataService.write_image` (`recipe_data_service.py:85-109`) | `POST /{slug}/image`, legacy `create/image` flow |
| Recipe assets (PDFs, etc.) | `<DATA_DIR>/recipes/<recipe_id>/assets/` | `Recipe.asset_dir_from_id` (`schema/recipe/recipe.py:206-208`) | `POST /{slug}/assets` |
| Backups | `<DATA_DIR>/backups/` | `app_dirs.BACKUP_DIR` | Admin backup routes |

**Implication for new feature:** the new orchestrator **must** use `get_temporary_path()` for the upload buffer, write to `<temp_path>/<uuid4().hex>` (NOT the original filename), and **never** call `RecipeDataService.write_image` for the upload — even though the legacy flow does (`recipe_service.py:354-355`). That call is the violation point of spec §4 隐私.

---

## Cross-perspective questions

1. **API perspective**: Does `OpenAIService.get_response` need a new `timeout` kwarg, or should the 60s bound be applied at the orchestrator level via `asyncio.wait_for`? The provider's `timeout` field (currently 300 s default per `schema/group/ai_providers.py:16`) is shared across audio/scrape/image — narrowing the global default would break those flows. We propose **orchestrator-level `asyncio.wait_for`** so other AI flows keep their existing budget; API perspective should confirm there's no DSL inside `OpenAIService` that swallows `asyncio.CancelledError`.

2. **API perspective**: The `OpenAIRecipe` schema doesn't model rating/category/tags. If the LLM returns `description: "5-star rated, vegetarian"` should the orchestrator try to extract those via a downstream NLP call, or hand off to the user via the UI review step? **We propose: do not infer.** The spec language is "用户审核并保存" (user reviews and saves), so the post-create UX is review-then-save; tags/categories should be entered manually post-create.

3. **API perspective**: Does `OPENAI_IMAGE_MODEL` env var **override** the `provider.model` from `repos.group_ai_providers.get_one(...)`, or is it a fallback when no provider is configured? Spec §2 implies override. We propose: `OPENAI_IMAGE_MODEL`, when non-empty, overrides `provider.model` **only for the image-recipe code path** (other OpenAI flows continue to use provider.model). The cleanest way is to clone the `AIProviderOut` instance with `.model_copy(update={"model": settings.OPENAI_IMAGE_MODEL})` before passing to `get_response(..., provider=...)`.

4. **API perspective**: Where should the per-user-per-hour rate-limit state live? Options: (a) module-level `defaultdict(deque)` in a new `mealie/services/rate_limit/` module — fast but per-process (breaks if `UVICORN_WORKERS > 1`, `settings.py:432`). (b) New DB table `recipe_image_rate_limit(user_id, bucket_start_ts, count)` — survives restarts/workers but adds a migration. Spec §6 explicitly permits "简单的内存 + DB 计数". We propose (a) for MVP with a TODO + log warning when `UVICORN_WORKERS > 1`; flagging here because the rate-limit logic is API-side but the persistence (if chosen) is data-side and would need a `mealie/db/models/` model + alembic migration following the `.github/copilot-instructions.md` "task py:migrate" workflow.

5. **API perspective**: `RecipeService.create_one` (`recipe_service.py:202-245`) emits a `RECIPE_CREATED_EVENT_SUBJECT` timeline event and a `recipe_created` event-bus message via the caller (`recipe_crud_routes.py:328-333`). Should the AI-generated recipe be flagged in the timeline subject (e.g. `recipe.recipe-created-from-image`) so consumers can distinguish AI- from manual-creation? Worth a quick API-side decision.

6. **API perspective**: The existing `OpenAIRecipeService.build_recipe_from_images` (`recipe_service.py:624-658`) currently raises bare `Exception("Failed to call OpenAI services")` from `__cause__` — when re-raised through HTTPException, the `__cause__` chain can leak `e.__class__.__name__` and the OpenAI error message to logs. We need a contract: the orchestrator must catch and **swallow** the cause from the HTTP response body (only the i18n key surfaces) while preserving it in the server log. Please confirm the API perspective will own the controller-level translation of these into 422.
