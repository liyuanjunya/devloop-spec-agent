# Approach Candidates — Case-6 LLM Image-to-Recipe

Three strategies for wiring the OpenAI Vision call into Mealie. All three converge on the same controller (`POST /api/recipes/create/image` returning `Recipe`), the same security checklist, and the same `OpenAIRecipe → Recipe` mapper at `mealie/services/recipe/recipe_service.py:599-622`. They differ in **where the Vision call lives**, **how `OpenAIService` is extended**, and **how `OPENAI_IMAGE_MODEL` is applied**.

Scoring rubric (per dimension, 1-5; higher = better):
- **Bug-coverage**: how easily the design satisfies *all* 10 security constraints + the 6 user stories without regressing existing flows.
- **Blast radius**: how much existing, working code (audio transcription, URL scrape, ingredient parser) is touched / put at risk.
- **Consistency w/ existing arch**: alignment with the verified codebase reality — `OpenAIService` as single LLM surface (history §2), `RecipeService.create_one` as single creation entry (recipe_service.py:163-167), prompts as `.txt` (history #13), 3-layer pattern (`.github/copilot-instructions.md`).
- **Security**: ability to prevent the four documented leak paths (raw LLM text in HTTP, raw LLM text in logs, image bytes in logs, user-controlled filename on disk).
- **Future-proofing**: cost of adding multi-image, batched, or non-OpenAI vision providers later.

---

## Approach A — Reuse + extend (extend existing `OpenAIService` to support Vision; new prompt + new orchestrator)

### Shape

- **Modify** `OpenAIService` (`openai.py:108-309`) — but minimally: no new methods, since `get_response(prompt, message, *, response_schema, attachments, provider)` (lines 283-309) already accepts attachments and a `provider` override. The only change is to **add a helper** on `OpenAIService` for cloning the provider with a model override:
  ```python
  def get_image_provider_with_override(self) -> AIProviderOut | None:
      if not self.image_provider:
          return None
      settings = get_app_settings()
      if settings.OPENAI_IMAGE_MODEL:
          return self.image_provider.model_copy(update={"model": settings.OPENAI_IMAGE_MODEL})
      return self.image_provider
  ```
- **Modify** `mealie/services/openai/prompts/recipes/parse-recipe-image.txt` in place (per consolidated C7) — append the prompt-injection-guard paragraph.
- **Modify** `OpenAIRecipeService.build_recipe_from_images` (`recipe_service.py:624-658`) → rename `build_recipe_from_image(image: Path) -> Recipe` (singular), wrap the `get_response` call in `asyncio.wait_for(..., timeout=60.0)`, swallow `str(e)` from any exception and raise `OpenAIServiceError("recipe.image.openai-failed")` instead.
- **Modify** `RecipeService.create_from_images` (`recipe_service.py:335-356`) → rename `create_from_image(image: UploadFile) -> Recipe`, change signature to single file, **DELETE** the `data_service.write_image(f.read(), "webp")` call at lines 354-355 (privacy violation per spec §4).
- **Add** new module `mealie/services/openai/rate_limit.py` exporting `HourlyUserRateLimiter` singleton.
- **Modify** `RecipeController.create_recipe_from_image` (`recipe_crud_routes.py:309-335`) → switch to `image: UploadFile = File(...)` (single), enforce env-flag + per-group gate (both must be true → 503), enforce size/MIME/magic, call rate-limiter, delegate to `service.create_from_image`, return full `Recipe`.
- **Modify** `RecipeController.handle_exceptions` (`recipe_crud_routes.py:90-125`) → add `RateLimitError → 429`, `OpenAIServiceError → 422`, `OpenAINotEnabledException → 503`.
- **Modify** `mealie/core/settings/settings.py` (OpenAI block at 417-424) → add `OPENAI_ENABLE_IMAGE_RECIPE: bool = False` and `OPENAI_IMAGE_MODEL: str = "gpt-4o-mini"`.
- **Modify** `mealie/lang/messages/en-US.json` → add `recipe.image.{feature-disabled, too-large, unsupported-mime, rate-limited, parse-failed, openai-failed}`.
- **Add** `filetype==1.2.0` to `pyproject.toml:8-50` (pure-python; chosen over `python-magic` per consolidated C6).

### Scores

| Dimension | Score | Rationale |
|---|---|---|
| Bug-coverage | 5 | One orchestrator; all 10 security controls funnel through `create_from_image`. Each FR ↔ exactly one code site. |
| Blast radius | 4 | Touches `OpenAIService` (one tiny helper) and `OpenAIRecipeService` (in-place rewrite). Does NOT touch audio (`transcribe_audio`, `openai.py:311-330`) or URL-scrape (`RecipeScraperOpenAI`). |
| Consistency w/ existing arch | 5 | Exactly mirrors `transcribe_audio` (`openai.py:311-330`) + `RecipeScraperOpenAI` reuse pattern: single LLM surface, single recipe entry. Aligned with history §2 "OpenAI surface area is owned by one class". |
| Security | 5 | Single ingress for image input, single egress (raw exception → 422 + i18n) — easy to audit. `_get_provider` already raises `OpenAINotEnabledException` (line 157), which we map to 503. |
| Future-proofing | 4 | Adding multi-image again is just `image: list[UploadFile]` + a loop in orchestrator. Adding a Gemini/Claude provider would still go through `OpenAIService` (likely renamed `AIService` someday — fits the trajectory). |

**Subtotal: 23/25**

---

## Approach B — Parallel service (keep `OpenAIService` text-only; add `OpenAIVisionService`)

### Shape

- **Add** `mealie/services/openai/vision.py` containing `OpenAIVisionService` — a new class with its own `AsyncOpenAI` client, its own prompt loader, its own provider lookup.
- **Add** `mealie/services/openai/prompts/recipes/recipe-from-image-vision.txt` (sibling prompt).
- Orchestrator uses `OpenAIVisionService` exclusively for the image path; `OpenAIService` is unchanged.
- All other pieces (controller, settings, exceptions, i18n) identical to Approach A.

### Scores

| Dimension | Score | Rationale |
|---|---|---|
| Bug-coverage | 4 | Same FR coverage as A, but exception-translation bugs become *two* surfaces to keep in sync. |
| Blast radius | 5 | Zero changes to `OpenAIService`. Audio + URL-scrape paths absolutely untouched. |
| Consistency w/ existing arch | **1** | Directly contradicts input.md §3 实现约束 "必须**真正复用** OpenAIService, 不要新建并行的 client" AND history §2 ("OpenAI surface area is owned by one class — every feature re-uses `get_response(..., response_schema=…, attachments=[…])`"). |
| Security | 4 | Duplicated client construction means TWO places to enforce timeout, error sanitization, rate-limit; doubles the audit surface. |
| Future-proofing | 2 | Cements the wrong pattern; future devs would have to decide which client to extend for each new modality. |

**Subtotal: 16/25**

**Disqualifier**: violates the explicit spec constraint and the codebase's 2-year-old invariant.

---

## Approach C — Wrapper (orchestrator owns image preprocessing; calls a thin method on existing service)

### Shape

- Controller owns ALL preprocessing: reads bytes, validates size/MIME/magic, base64-encodes the JPEG itself.
- Orchestrator calls a new **thin** method `OpenAIService.image_to_recipe(image_data_uri: str, prompt: str) -> OpenAIRecipe` that takes the already-prepared base64 URI (no `OpenAILocalImage`, no temp file, no `PillowMinifier`).
- Effectively turns `OpenAIService` into a transport-only layer; image-handling lives in the route layer.

### Scores

| Dimension | Score | Rationale |
|---|---|---|
| Bug-coverage | 3 | Pushes image-handling into the route, which means controller code grows and becomes harder to unit-test in isolation. The 60s timeout is awkward to express in the controller. |
| Blast radius | 3 | Bypassing `OpenAILocalImage` means re-implementing `PillowMinifier.to_jpg` semantics (`openai.py:89-91`) — and the JPEG-conversion fix from PR #2585 (`2ae3427a`) lives inside `get_image_url`. Easy to regress the "PNG/WEBP → JPEG conversion" invariant the OpenAI Vision API expects. |
| Consistency w/ existing arch | 2 | Breaks the three-layer rule: controllers shouldn't own data-shape transformation. `routes/users/images.py:36` correctly delegates `to_webp` to `PillowMinifier` — Approach C would invert that. |
| Security | 3 | Controller becomes responsible for both HTTP validation AND data conversion — bigger attack surface; easier to forget to redact `image_data_uri` from logs. |
| Future-proofing | 2 | Hard to add a second consumer of "image → recipe" (e.g., a batch backfill task) without duplicating the prep code. |

**Subtotal: 13/25**

---

## Comparison summary

| Approach | Bug-cov | Blast | Consistency | Security | Future-proof | Total |
|---|---|---|---|---|---|---|
| **A — Reuse + extend** | 5 | 4 | **5** | **5** | 4 | **23/25** ✅ |
| B — Parallel service | 4 | **5** | 1 | 4 | 2 | 16/25 |
| C — Wrapper | 3 | 3 | 2 | 3 | 2 | 13/25 |

---

## Selection

**Approach A wins.**

Three independent gates land on the same answer:

1. **Hard input constraint**: input.md §3 实现约束 — "必须真正复用 OpenAIService, 不要新建并行的 client". This eliminates B by spec text.
2. **Architectural invariant** (history §2): `OpenAIService` is the sole LLM surface across ingredient parsing, URL scraping, image, and audio transcription. The intent.json `verified_codebase_facts.existing_openai_service` already notes that `get_response` *already* supports image attachments at lines 283-309 — there's nothing to fork.
3. **Audit surface**: A funnels all security controls through ONE service method and ONE controller; the 6 FRs around error-leak prevention each have exactly one code site to review.

The lone concession is Approach A scoring 4/5 on "Blast radius" (it modifies the shared `OpenAIService` instead of leaving it untouched), but the modification is a single non-behavior-changing helper method (`get_image_provider_with_override`) and an in-place body edit of `build_recipe_from_images` (which is already image-only).

See `approach/selected.md` for the full, code-level design contract.
