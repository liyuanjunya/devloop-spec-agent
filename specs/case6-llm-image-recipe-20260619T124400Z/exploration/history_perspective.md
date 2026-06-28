# History Perspective — case-6 LLM Image-to-Recipe (Mealie)

> Scope: extract the historical context of `mealie/services/openai/`, `mealie/routes/recipe/`, and `mealie/services/recipe/recipe_service.py` so case-6 implementation does not regress against past fixes. All commit metadata was pulled via `git --no-pager log` against `C:\Users\v-liyuanjun\Downloads\mealie\` on 2026-06-19. Repo HEAD reflects the post-PR-#7650 reality (in-app AI provider config landed May 2026).

---

## 1. Top 15 commits + impact

Selected to span: the original OpenAI feature, image-specific evolution, structured-outputs refactor, the security overhauls, and the in-app AI provider migration. All hashes are short SHAs as returned by `git log --oneline`.

| # | SHA | Date | Title | Impact for case-6 |
|---|-----|------|-------|--------------------|
| 1 | `c3f87736` | 2026-05-23 | feat: In-app AI Provider Configuration (#7650) | **Massively reshapes the contract.** Moved `OPENAI_*` env vars (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `OPENAI_REQUEST_TIMEOUT`, …) into DB-backed `group_ai_providers` table; added per-purpose `image_provider_id`/`audio_provider_id`/`default_provider_id`; deleted `docker/entry.sh` env wiring; added Alembic `2187537c52b8_add_table_for_ai_providers.py`. Only `OPENAI_CUSTOM_PROMPT_DIR` survives. Any spec asking for "set env var to enable image" is now anachronistic. |
| 2 | `570d6f14` | 2026-01-31 | feat: Migrate OpenAI implementation to use structured outputs (#6964) | Switched from regex/JSON-parsing of free-text responses to `client.chat.completions.parse(response_format=…)`. Net **-273/+124** LOC across the OpenAI schema/services. `OpenAIRecipe` schema (`mealie/schema/openai/recipe.py`) became the single source of truth; mutated `parse-recipe-image.txt` prompt. New code MUST use this `response_schema=` path — do not call the raw chat completion API. |
| 3 | `8a15f400` | 2024-08-17 | feat: Import + Translate recipe images with OpenAI (#3974) | **The genesis of the image route** (`POST /api/recipes/create/image`). Established `OpenAIRecipeService.build_recipe_from_images`, the JPEG base64 data-URI strategy (`openai.py:OpenAILocalImage.get_image_url`), the optional `translateLanguage` query param, and the "first uploaded image becomes recipe cover" behaviour (`recipe_service.py:354-355`). |
| 4 | `95fa0af2` | 2025-06-28 | feat: create recipe from multiple images (#5590) | Changed the route signature from single `image: UploadFile` to `images: list[UploadFile] = File(...)`. **This breaks the case-6 spec's single-`image` field assumption.** Front-end (`RecipePageParseDialog.vue`, `pages/g/[groupSlug]/r/create.vue`) was updated to multi-upload. Reverting to single-file would be a UX regression. |
| 5 | `4b69e5b3` | 2025-08-11 | feat: Button to select recipe cover image when creating recipe from multiple images (#5647) | Cements the "uploaded image is retained as recipe cover" UX — spec's *"delete after parse, do not store"* requirement directly contradicts this feature. Removing cover-persistence would break the UI button shipped in this PR. |
| 6 | `bd296c3e` | 2026-04-15 | fix: path traversal vulnerabilities in migration image imports and media routes (#7474) | **Hard requirement.** Touched 16 files including `mealie/services/openai/openai.py` (added `is_relative_to(PROMPTS_DIR.resolve())` check in `_get_prompt_file_candidates` lines `179-194`), `mealie/services/recipe/recipe_service.py` (use `safe_filename = Path(image.filename).name` at line `340`), and added `mealie/services/migrations/utils/migration_helpers.py` containing the canonical `is_path_within_directory` helper. Any new code that touches `image.filename` MUST normalise via `Path(...).name` and verify with `is_relative_to(...)`. |
| 7 | `eddb0c30` | 2026-05-14 | fix: block scriptable asset extensions and force Content-Disposition: attachment (GHSA-gfwc-pjx4-mg9p) | Defines the project-wide stance: uploaded files served from `/api/media/...` must (a) be MIME-checked at write, (b) blocked if extension is in `(html, svg, js, htm, xhtml)`, (c) served with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`. Sibling test: `test_recipe_image_assets.py:90-131`. **Case-6 must NOT accept image/svg+xml** even if the spec only lists jpeg/png/webp — SVG is the obvious gap and this commit shows it's specifically banned. |
| 8 | `742b498c` | 2026-05-14 | fix: enforce ownership check on recipe deletion (GHSA-x5v9-9jvh-7c7q) | Re-emphasises that **every** recipe-mutating route must verify household/group ownership. The new image route must apply the same checks (mealie's repository factory does this transparently — but only if you go through `repos.recipes` rather than raw SQLAlchemy). |
| 9 | `6f03010f` | 2025-12-18 | fix: Security Patches (#6743) | Updated `bulk_actions.py`, `utility_routes.py`, `recipe_bulk_service.py` — pattern of "validate before delegating to a bulk operation". Relevant if case-6 ever batches multi-image into multiple LLM calls. |
| 10 | `96acc6fc` | 2025-09-23 | fix: Remove explicit timeout from OpenAI image API Call (#6227) | **Direct conflict with spec.** Spec demands "≤60 s per call"; this commit *deleted* the explicit timeout that previously existed because vision calls legitimately exceed it. Re-introducing the timeout will regress against the reasoning of this PR. Original timeout source: PR #3808 (`3e1adfa6` "feat: Make OpenAI Request Timeout Configurable"). |
| 11 | `2ae3427a` | 2025-08-05 | fix: correct JPEG media type in get_image_url to prevent API errors (#5897) | Confirms `OpenAILocalImage.get_image_url` returns `data:image/jpeg;base64,…` regardless of source format (relies on Pillow conversion). Implication: even PNG/WEBP uploads end up as JPEG when sent to OpenAI — so any prompt that mentions "preserve transparency" is moot. |
| 12 | `a3f474e0` | 2024-08-30 | feat: Change OpenAI Image Format to JPG (#4117) | Established the JPG-conversion convention referenced by commit #11. Removes WebP/HEIC quirks at the OpenAI boundary. |
| 13 | `fdd17182` | 2026-05-10 | fix: Update OpenAI recipe parse prompt to return the same number of ingredients as given (#7604) | Demonstrates the project's "prompt is the contract" stance — changes to prompts ship as `fix:` PRs. Case-6's new prompt (`recipes/recipe-from-image.txt` or similar) must be reviewable & diff-able in the same way (plain `.txt`, not in code). |
| 14 | `c7ae67e7` | 2025-11-?? | feat: Customizable OpenAI prompts (#5146) (#6588) | Introduced `OPENAI_CUSTOM_PROMPT_DIR` and the dual-lookup logic in `OpenAIService._get_prompt_file_candidates` (`openai.py:170-204`). Case-6 prompt MUST be filed under `mealie/services/openai/prompts/recipes/` to participate in user override. |
| 15 | `1344f167` | 2026-02-?? | feat: Add social media video import (YouTube, TikTok, Instagram) (#6764) | Created the precedent for `RecipeScraperOpenAITranscription` (audio-via-OpenAI flow). Shares the "download → temp dir → mock-aware service call" pattern that case-6 (image-upload → temp dir → service call) should mirror; relevant test scaffolding at `test_recipe_create_from_video.py`. |

> Excluded from the table but flagged: ~30 `chore(deps): update dependency openai to v…` commits between Aug 2025 and Jun 2026, indicating OpenAI SDK is on a renovate-managed automated upgrade cadence. Current pin: `openai==2.41.1` (`pyproject.toml:43`). Case-6 must use the new SDK's structured-output API surface (`chat.completions.parse(response_format=…)`), not the deprecated v1 helpers.

---

## 2. OpenAI integration history (timeline)

```
2024-08-13  5c57b3dd  feat: OpenAI Ingredient Parsing (#3581)                 ← Mealie's first LLM integration
2024-08-13  4afb7673  feat: Open AI Recipe Scraper (#3690)                    ← URL-scrape via OpenAI
2024-08-17  8a15f400  feat: Import + Translate recipe images with OpenAI      ← Vision Day 1; route /create/image born
2024-08-30  a3f474e0  feat: Change OpenAI Image Format to JPG (#4117)
2024-09-?? ea1f727a   feat: OpenAI Custom Headers/Params and Debug Page       ← /admin/debug/openai endpoint
2024-12-?? 3e1adfa6   feat: Make OpenAI Request Timeout Configurable          ← introduces OPENAI_REQUEST_TIMEOUT
2025-04-?? 323a8100   fix: Remove Temperature from OpenAI Integration (#6023) ← OpenAI deprecated temperature for some models
2025-06-28 95fa0af2   feat: create recipe from multiple images (#5590)        ← single-image → list[UploadFile]
2025-08-05 2ae3427a   fix: correct JPEG media type in get_image_url (#5897)
2025-08-11 4b69e5b3   feat: Select recipe cover image from multiple images
2025-09-23 96acc6fc   fix: Remove explicit timeout from OpenAI image API Call (#6227)
2025-09-23 a9090bc2   feat: Manually calculate OpenAI Parsing Confidence (#6141)
2025-11-?? c7ae67e7   feat: Customizable OpenAI prompts (#5146) (#6588)       ← OPENAI_CUSTOM_PROMPT_DIR
2026-01-31 570d6f14   feat: Migrate OpenAI implementation to use structured outputs (#6964)
                       └─ deletes ~150 LOC of regex/JSON-clean logic; OpenAIBase + response_format=Schema
2026-02-?? 1344f167   feat: Add social media video import (YouTube, TikTok, Instagram) (#6764)
                       └─ OpenAILocalAudio + RecipeScraperOpenAITranscription
2026-04-15 bd296c3e   fix: path traversal vulnerabilities (#7474)             ← prompt-path & filename normalisation
2026-05-10 fdd17182   fix: Update OpenAI recipe parse prompt (#7604)
2026-05-23 c3f87736   feat: In-app AI Provider Configuration (#7650)          ← env vars → DB; new schema/migration
                       └─ pivotal: removes OPENAI_API_KEY/OPENAI_MODEL/etc., adds AIProvider DB model
```

### Key architectural truths the timeline reveals
- **OpenAI surface area is owned by one class** — `OpenAIService` at `mealie/services/openai/openai.py`. Every feature (ingredients, URL scrape, image, video transcription, debug) re-uses `get_response(prompt, message, response_schema=…, attachments=[…])`. The case-6 spec's requirement to *"genuinely reuse OpenAIService"* aligns with this 2-year-old invariant — do not fork.
- **Image attachments are first-class today** — `OpenAILocalImage` at `openai.py:84-94`. The case-6 implementation should construct it the same way the existing route does (`recipe_service.py:631`) and avoid inventing a parallel image-handling primitive.
- **Provider selection is automatic when attachments are present** — `_get_provider()` at `openai.py:147-168` raises `OpenAINotEnabledException("No image provider set")` if `image_provider_id` is unset and an image attachment is included. This is the *only* current mechanism that gates the image feature. Spec's `OPENAI_ENABLE_IMAGE_RECIPE` env var would have to be **layered on top** of (or replace) this DB check.
- **Prompts are flat `.txt`** under `mealie/services/openai/prompts/{general,recipes}/`. They are loaded by dotted name (e.g. `recipes.parse-recipe-image`). New case-6 prompt should follow `recipes.<new-name>.txt`. The user-customisability mechanism (PR #6588) automatically picks up the new file under `$OPENAI_CUSTOM_PROMPT_DIR/recipes/<name>.txt`.

### Key behavioural deltas (anti-regression list)
1. `OpenAIService.get_response` returns **`None`** on empty choices — callers must check (`recipe_service.py:647-648`).
2. `openai.RateLimitError` is caught and **re-raised as `mealie.core.exceptions.RateLimitError`** (`openai.py:306-309`, also `325-326` for audio). Nothing maps `RateLimitError` to an HTTP status.
3. Prompt file path is resolved with `.is_relative_to(PROMPTS_DIR.resolve())` (`openai.py:180-181`) — a path-traversal mitigation from PR #7474.
4. `OpenAILocalImage.get_image_url` *writes a `<filename>-min-original.jpg`* in the same directory as the source (`openai.py:90`). If case-6 places uploads in a temp dir and the temp dir is read-only or auto-cleaned mid-call, this side effect breaks. Use `get_temporary_path()` from `mealie/core/dependencies/dependencies.py:191`.

---

## 3. File-upload security patterns history

| Date | SHA | Lesson |
|------|-----|--------|
| 2023 | `7222abe2` | "security: arbitrary file download by authenticated user (#2867)" — established that **all** file-serving routes must check ownership *and* canonicalise paths. |
| 2026-04-15 | `bd296c3e` | Path traversal in migration image imports + media routes (#7474). Fix: `Path(filename).name` everywhere a user supplies a name; `is_relative_to(parent)` to assert the resolved path stays inside the intended directory. Helper: `mealie/services/migrations/utils/migration_helpers.py::is_path_within_directory`. **Reuse, don't reinvent.** |
| 2026-05-14 | `eddb0c30` | GHSA-gfwc-pjx4-mg9p — scriptable asset extensions blocked (`html`, `svg`, `js`, `htm`, `xhtml`); responses forced `Content-Disposition: attachment` + `X-Content-Type-Options: nosniff`. **Case-6 should explicitly reject SVG even though it's an "image".** |
| 2026-05-14 | `742b498c` | GHSA-x5v9-9jvh-7c7q — ownership check on delete. Reinforces: do not trust front-end-passed IDs; always verify against the current user's household/group via repository scoping. |
| 2025-12-18 | `6f03010f` | "fix: Security Patches" — bulk-action validation patterns. Implies case-6, if it batches images, should follow the same per-item validation idiom. |
| 2025-08-?? | `108ac40b` | "fix: Update admin_backups.py to handle API backup file uploads correctly" — shows the project's reliance on `UploadFile.file` (the underlying SpooledTemporaryFile) rather than `.read()` to stream large uploads. |
| 2024-12-?? (legacy) | `ca9f66ee` | "feat: Remove OCR Support" — historical context: OCR was deprecated **because** of operational pain (libtesseract). Adding `python-magic` (libmagic dependency) re-creates that operational-burden category. Expect maintainer pushback. |

### Implicit conventions you cannot read from git alone but the code makes obvious
- `UploadFile.filename` is **always** normalised to `Path(filename).name` before use in path construction (`recipe_service.py:340`, `admin_debug.py:29`).
- Temp dirs are obtained via `get_temporary_path()` (UUID-named subdir under `app_dirs.TEMP_DIR`, auto-`rmtree` on context exit — see `dependencies.py:190-198`). **Do not use Python's `tempfile.TemporaryDirectory()` directly** — the project standard is the UUID-under-app-tempdir pattern.
- MIME detection currently **does not** use magic bytes anywhere — only `content-type` header inspection in `recipe_data_service.py:161-165` (`"image" not in content_type` → `NotAnImageError`). Magic-bytes detection would be a *new* security primitive, not a copy of existing code.
- Pillow already validates JPEG/PNG/WEBP indirectly through `PillowMinifier.to_jpg` (called by `OpenAILocalImage.get_image_url`) — a malformed image would raise `PIL.UnidentifiedImageError`. This is an *available* (if weaker) defence already in the codepath.

---

## 4. Risk hotspots for case-6

Ranked by where I expect implementation bugs / CR findings.

### R1 — Feature flag semantics (high)
The spec and the running code disagree on **what enables the feature**. Two parallel gates may end up coexisting:
- Spec: `OPENAI_ENABLE_IMAGE_RECIPE` env var (default false) → 503 + i18n on disabled.
- Today: `group_ai_provider_settings.image_provider_id is not None and image_provider_enabled is True` → 400 + plain message.

If case-6 only adds the env-var check without removing/re-wiring the DB check, "feature enabled" requires *both* to be true → confusing UX. Coordinate with reviewers before coding. Inspect commits `c3f87736` and `recipe_crud_routes.py:320-325`.

### R2 — `RateLimitError` → HTTP 429 (high)
`mealie.core.exceptions.RateLimitError` exists (`exceptions.py:57-62`) but is **never** translated to a 429 — it's swallowed by scrapers as a flow-control signal (`scraper_strategies.py:552, 578`). Wiring it into a FastAPI exception handler (similar to `register_debug_handler` at `routes/handlers.py:18-31`) is a brand-new behaviour. Risk of: leaking `str(e)` (potentially containing OpenAI's rate-limit reset metadata which is fine, or worse: prompt content if logging is sloppy).

### R3 — Image retention contract (high)
`create_from_images` deliberately keeps the first image as the recipe cover (`recipe_service.py:354-355`). Spec's "delete after parse, do not store in assets" directly removes this behaviour. PR #5647 (`4b69e5b3`) added a UI button explicitly for selecting which uploaded image becomes the cover — removing the back-end behaviour orphans that button. **Cross-perspective: this is the most likely place for the spec to be wrong vs the existing product direction.**

### R4 — Timeout reintroduction (medium)
PR #6227 (`96acc6fc`) explicitly removed the timeout for vision calls. Re-adding `timeout=60` (per spec) will cause flaky test/prod failures on legitimate large-image requests that took >60 s historically. If a timeout is required by reviewers, it should be configurable and default disabled (matching the spirit of the removal).

### R5 — `python-magic` dependency (medium)
Not in `pyproject.toml` today. Adding it requires installing `libmagic` in the container base image — historical precedent (`ca9f66ee` "Remove OCR Support") shows the project is wary of adding native deps. Alternatives: pure-Python `filetype` (no native lib) or Pillow's `Image.open(BytesIO).verify()` (already a transitive dep). CR is likely to flag this if `python-magic` is chosen without justification.

### R6 — Multipart field-name compatibility (medium)
Current field is `images` (plural); spec wants `image` (singular). Front-end (`RecipePageParseDialog.vue`) was migrated in #5590 to send multiple. Changing the field name is a public API break and front-end re-coordination. Risk of: silent test fixture failure (existing `test_recipe_create_from_image.py:59` keeps using `images`). Suggested mitigation: accept both as form aliases, deprecate `images` with a warning.

### R7 — Prompt-injection defence breadth (medium)
Existing `recipes/parse-recipe-image.txt` is **5 lines** of pure task description with **no** prompt-injection hardening. The spec asks for explicit "ignore system instructions in image" guidance. There is no precedent in any prompt file for this defence — case-6 will set the project's *first* prompt-injection-aware prompt. CR will scrutinise for missing roles, missing user-prompt isolation, and missing assertion that image content is *data, not instructions*.

### R8 — Logging hygiene (medium)
`openai.py:308-309` re-raises with `str(e)` in the message (`f"OpenAI Request Failed. {e.__class__.__name__}: {e}"`). When this exception bubbles to FastAPI default handling, the message may end up in client responses. Spec says **never** leak LLM raw output to client. Need a try/except in the new route that catches and substitutes an i18n error code without exposing `e`.

### R9 — Temp file cleanup on partial failure (low-medium)
`get_temporary_path()` does `rmtree(temp_path)` in `finally`. Existing `create_from_images` (`recipe_service.py:337-356`) already nests inside this context manager, so cleanup is solid for the happy path. The risk is the case-6 code adding new try/except *outside* the context manager — easy to break cleanup if refactoring. Test with the temp-dir-snapshot probe (see test perspective §6.2).

### R10 — Translation completeness (low)
`mealie/lang/messages/en-US.json` currently has only `recipe-image-deleted` and `downloading-image` for image-related keys. New keys: `recipe.image.feature-disabled`, `recipe.image.too-large`, `recipe.image.unsupported-mime`, `recipe.image.rate-limited`, `recipe.image.parse-failed`. Per `.github/copilot-instructions.md`, only the `en-US` file may be touched — other locales are managed by Crowdin. CR will reject any change to other locale files.

---

## 5. Cross-perspective questions

1. **Should case-6 *replace* or *augment* the existing `/api/recipes/create/image` route?** If replace, the rename (`images` → `image`), status-code change (400 → 503/422/429), and removal of cover-persistence are all breaking. If augment, we end up with two near-duplicate routes — which the test suite would have to disambiguate.
2. **Is the in-app AI Provider Configuration (PR #7650) the source of truth for "image provider", or are we adding a parallel env var?** If parallel, what's the precedence (env overrides DB? DB overrides env?). The history shows a deliberate move *away* from env vars — case-6 swimming upstream needs justification.
3. **Do we keep the `translate_language` query parameter** that PR #3974 added? The spec doesn't mention it; ignoring it silently removes a documented feature.
4. **Magic-bytes vs Pillow-verify** for MIME validation. Pillow is already required (the OpenAILocalImage path runs `PillowMinifier.to_jpg`). Is `Image.open(...).verify()` an acceptable substitute for `python-magic` to avoid adding a native dependency? History (PR removing OCR) suggests yes.
5. **Per-user rate-limit storage** — memory dict (lost on restart, doesn't scale across workers), DB table (new Alembic migration, follow PR #7650 pattern), or new in-memory cache keyed by user_id? PR `c3f87736` shows the team is comfortable adding Alembic migrations for new tables. Memory-only may be rejected for multi-worker deployments (mealie supports gunicorn workers per `docker/entry.sh`).
6. **How should we surface the OpenAI provider timeout?** Currently set per-provider in the DB (`provider.timeout`, see `openai.py:142`). Reintroducing a hard-coded 60 s timeout in the route — as the spec demands — would conflict with admin-configured values. Better to: respect `provider.timeout` and document its default.
7. **Should we add an integration test that the image is NOT persisted in `assets/`?** This directly tests the case-6 privacy requirement and is *not* covered by any existing test (because the existing behaviour is the opposite — it IS persisted as cover). New test would assert `(recipe.asset_dir).iterdir()` is empty after the create call.
8. **Coordinate with PR #7625 (`742b498c`):** any new route must enforce household ownership. Confirm with reviewers that going through `repos.recipes.create_one(...)` (already in `RecipeService.create_one`) is sufficient — the repository factory scopes by group/household per the architecture doc.
9. **Frontend impact** — `frontend/app/pages/g/[groupSlug]/r/create.vue` and `RecipePageParseDialog.vue` were both modified by PR #5590 to use `images` (plural). Any case-6 change to the field name forces frontend changes; case-6 spec only mentions backend. Out of scope to fix here, but the test perspective must flag it for the eventual PR description.
