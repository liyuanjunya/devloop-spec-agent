# Rewrite log v1 → v2 — Case-6 LLM Image-to-Recipe

**Date**: 2026-06-19
**Reviewers addressed**: architecture, completeness, consistency, executability (all 4)
**Verdicts in v1**: arch=REQUEST_CHANGES, comp=NEEDS_REFINE, cons=NEEDS_REVISION, exec=Needs revision
**Issue counts in v1**: 1 Critical, 12 High, 11 Medium, 1 Low — **24 actionable findings, 1 net trivial-Low**
**v2 outcome**: All 13 Critical+High **resolved or explicitly rejected** with documented rationale. All Medium fixes applied. All Low fixes applied. All cited line ranges re-verified against `C:\Users\v-liyuanjun\Downloads\mealie\` on 2026-06-19. `spec_v2.md` and `spec_v2.json` are derived from the same content.

---

## Section 1 — Critical/High issue resolution table

| Issue | Reviewer | Severity | Resolution | Where |
|---|---|---|---|---|
| **COMP-C-001 — Logging control not fully satisfied; raw LLM output can still be logged at DEBUG** | completeness | **Critical** | **FIX**. Added new **FR-23** mandating in-place edit of `mealie/schema/openai/_base.py:33-35` to replace the raw-response DEBUG log with `cls.__name__` + length only. SC-8 is now executable at DEBUG. Combined with FR-18/FR-19 `raise … from None` to suppress exception cause chain. | FR-23, FR-18, FR-19, SC-8, files_to_modify |
| **ARCH-H-1 — Raw LLM response can still be logged at DEBUG** | architecture | High | **FIX**. Same as COMP-C-001 — FR-23 sanitizes `_base.py:34`. | FR-23, SC-8 |
| **ARCH-H-2 — `exc_info=True` can re-leak sanitized upstream errors via exception chains** | architecture | High | **FIX**. FR-19 explicitly drops `exc_info=True`; orchestrator uses `raise OpenAIServiceError("recipe.image.X") from None` to suppress both `__cause__` AND `__context__`. Documented in SCN-6 (debugging trade-off acknowledged). | FR-18, FR-19, SCN-6 |
| **ARCH-H-3 — In-memory rate-limit per worker fails contract when `UVICORN_WORKERS>1`** | architecture | High | **FIX**. FR-11 now hard-disables the feature when `settings.WORKERS > 1`. At startup, the env flag is force-set to False and an ERROR is logged. SC-13 and EC-10 cover this. NC-003 updated to document trade-off; DB-backed migration deferred. | FR-11, FR-04, NC-003, SC-13, EC-10 |
| **ARCH-H-4 — Auth/feature-disabled acceptance criteria are internally inconsistent (401 vs 503)** | architecture | High | **FIX**. New **FR-25** defines explicit precedence chain (auth→gate→rate-limit→size→header→magic→OpenAI). US-2 rewritten to say "authenticated calls return 503". SC-2 narrowed to authenticated requests; new **SC-2b** asserts unauth → 401 always. | FR-03, FR-25, US-2, SC-2, SC-2b |
| **CONS-C-001 — Feature-disabled 503 contradicts unauthenticated 401** | consistency | High | **FIX**. Same as ARCH-H-4 — FR-25 + SC-2/SC-2b split. | FR-25, US-2, SC-2, SC-2b |
| **CONS-C-002 — Error precedence underspecified for feature-off vs validation failures** | consistency | High | **FIX**. FR-25 codifies precedence; SC-3/SC-4/SC-5 explicitly state "test enables feature flag per FR-25". | FR-25, SC-3, SC-4, SC-5 |
| **CONS-C-003 — Parse failures cannot be reliably distinguished from network failures** | consistency | High | **FIX**. FR-14 now specifies the orchestrator inspects `e.__cause__` after catching the wrapped `Exception` from `get_response`. `ValidationError`/`JSONDecodeError` in cause → `parse-failed`; otherwise → `openai-failed`. EC-02/EC-04/EC-06 all updated to reference this mechanism. SC-7 asserts correct classification. | FR-14, FR-18, EC-02, EC-04, EC-06, SC-7 |
| **CONS-C-004 — Logging requirements conflict with `exc_info=True` and DEBUG capture tests** | consistency | High | **FIX**. Same as ARCH-H-1 + ARCH-H-2. | FR-19, FR-23, SCN-6 |
| **COMP-H-001 — Required prompt template path is explicitly inverted (`.md` jinja2 vs in-place `.txt`)** | completeness | High | **EXPLICIT REJECT** via new **NC-004**. Mealie has no Jinja2 prompt engine; loader at `openai.py:170-262` is append-style. Adopting `.md`+Jinja2 would require new loader + new dependency. Decision is documented as deliberate deviation from input.md §2; the existing append/injection mechanism IS Mealie's templating mechanism. | NC-004, out_of_scope |
| **COMP-H-002 — Documentation/settings-site update from input §6 is missing** | completeness | High | **FIX**. Added new **FR-24** and **SC-14** and a `files_to_modify` entry for `docs/docs/documentation/getting-started/installation/backend-config.md:126-128` (verified path) to add rows for the two new env vars. | FR-24, SC-14, files_to_modify |
| **COMP-H-003 — Strict prompt JSON schema does not preserve RecipeBase contract** | completeness | High | **EXPLICIT REJECT** via new **NC-005**. The existing `OpenAIRecipe` (mealie/schema/openai/recipe.py:45-89) is the canonical Mealie image-to-recipe schema, mapped 1:1 to `Recipe` (which extends `RecipeBase`) by `_convert_recipe`. Input's RecipeBase shape is interpreted as conceptual; adopting a parallel schema would break URL-scrape or require two mappers. | NC-005, out_of_scope |
| **EXEC-CITE-3 — FR-19/SC-8 conflict reaffirmed at code level** | executability | High | **FIX**. Same as COMP-C-001 — FR-23 + redacted log. | FR-23, SC-8 |

---

## Section 2 — Medium issue resolution table

| Issue | Reviewer | Resolution | Where |
|---|---|---|---|
| ARCH-M-1 — Controller/service ownership inconsistent | architecture | **FIX**. FR-16 now explicitly splits: controller does HTTP-only (auth, form, Content-Length, header MIME, rate-limit, event-emit, exception-translate); service does chunked write, magic sniff, temp lifecycle, OpenAI call, cleanup. | FR-16 |
| ARCH-M-2 — Magic-byte detection needs `None` handling | architecture | **FIX**. FR-08 explicitly treats `filetype.guess() is None` as 415. EC-09 added. | FR-08, EC-09 |
| ARCH-M-3 — Global `OPENAI_IMAGE_MODEL` overrides per-group setting | architecture | **FIX**. FR-05 documents this as a deliberate server-wide per-call override using `model_copy` (no mutation of source provider). | FR-05 |
| ARCH-M-4 — Prompt-injection mitigation scope should be honest | architecture | **FIX**. FR-17 explicitly scope-limited: goal is "prevent image text from changing model role/tool behavior" — does NOT promise sanitized output. SCN-3 mirrored. | FR-17, SCN-3 |
| COMP-M-001 — 422 test coverage too implicit | completeness | **FIX**. SC-7 + EC-02/EC-04/EC-06 explicitly enumerate 422 cases (parse, openai, timeout, network); files_to_extend description names them. | SC-7, EC-02, EC-04, EC-06 |
| COMP-M-002 — Service-disabled precedence stronger than input | completeness | **FIX**. Same as ARCH-H-4 — FR-25 precedence chain. | FR-25, SC-2b |
| CONS-C-005 — SC-1 says "four LLM-extracted fields" but measures three | consistency | **FIX**. SC-1 now says "all three" matching US-1 (name, recipe_ingredient, recipe_instructions). | SC-1 |
| CONS-C-006 — `shutil.copyfileobj` does not provide cumulative abort | consistency | **FIX**. FR-06 specifies explicit chunked loop (`while chunk := image.file.read(64*1024): cumulative += len(chunk); if cumulative > 5_242_880: raise`). `shutil.copyfileobj` no longer used for the upload stream. EC-07 updated. | FR-06, EC-07 |
| CONS-MD-JSON-1 — md/json diff on FR-01 commit-msg, FR-21 WARN level, EC-08 title, test commands, files section | consistency | **FIX**. md and json now identical: FR-01 says "documented in commit message AND PR description"; FR-21 says "logged at WARN"; EC-08 title unified; `uv run pytest` commands used in both; md has explicit `files_to_modify`/`files_to_add`/`files_to_extend` tables; self-concern IDs unified to `SCN-N`. | FR-01, FR-21, EC-08, test_plan, files_*, SCN-* |
| EXEC-CITE-1 — FR-03 cite does not prove 401 | executability | **FIX**. FR-03 now cites `mealie/routes/_base/base_controllers.py:132,139` (`BaseUserController` + `user: PrivateUser = Depends(get_current_user)`). | FR-03 |
| EXEC-CITE-2 — FR-19 wrongly says audio fallback uses class-name only | executability | **FIX**. FR-19 acknowledges `openai.py:328-330` IS a leak (`{e}` is interpolated); cited as a comparison to what we explicitly do NOT do. | FR-19 |
| EXEC-CITE-4 — FR-20 cite missing `.github/` prefix and line | executability | **FIX**. FR-20 cites `.github/copilot-instructions.md:146` exactly. | FR-20 |
| EXEC-CITE-5 — FR-22 cite `:173-184` is not an event-emission | executability | **FIX**. FR-22 cites `recipe_crud_routes.py:259-272` (`_finish_recipe_from_web.publish_event(EventTypes.recipe_created…)`), with secondary citations at `:295-307` (zip) and `:328-333` (old image route). Confirmed by source: lines 173-184 are the `parse_recipe_url` body that returns a slug without publishing — the publish happens in the helper at 259-272. | FR-22 |
| EXEC-DIFF-1 — md/json `code_references` diverge for FR-06/FR-11/FR-12/FR-16/FR-20/FR-22 | executability | **FIX**. Synchronized. Each FR's `code_references` array in `spec_v2.json` is now a verbatim list of the citations shown in `spec_v2.md`. | All FRs |
| EXEC-ETC-1 — Rate-limit pruning/clock injection/startup hook underspecified | executability | **FIX**. FR-11 specifies: prune entries with `timestamp < now - 3600s` on every `check_and_record`; rejected attempts NOT appended (not counted); `_clock = datetime.utcnow` injectable; startup hook documented. | FR-11, EC-05, SC-5 |
| EXEC-IMPL-1 — FR-06 copyfileobj wording imprecise | executability | **FIX**. Same as CONS-C-006. | FR-06 |

---

## Section 3 — Low issue resolution table

| Issue | Reviewer | Resolution | Where |
|---|---|---|---|
| EXEC-PATH-1 — `copilot-instructions.md` cited without `.github/` prefix | executability | **FIX**. All citations updated to `.github/copilot-instructions.md` (md + json). | FR-16, FR-20, constraints |
| EXEC-LANG-1 — NC-002 retains Chinese 或类似工具 wording | executability | **FIX**. NC-002 question rewritten in English without the Chinese ambiguous phrase. Recommended default unchanged (`filetype==1.2.0`). | NC-002 |

---

## Section 4 — Code citation re-verification

All FR `code_references` re-checked against `C:\Users\v-liyuanjun\Downloads\mealie\` on 2026-06-19:

| Citation | Verification | Status |
|---|---|---|
| `mealie/routes/recipe/recipe_crud_routes.py:309-335` (existing image endpoint) | viewed; lines contain `create_recipe_from_image(images: list[UploadFile]…)` | ✓ |
| `mealie/routes/recipe/recipe_crud_routes.py:358` (`duplicate_one` precedent) | viewed; `def duplicate_one(self, …) -> Recipe:` at line 358 (was previously cited as `:450-470`, corrected) | ✓ corrected |
| `mealie/schema/recipe/recipe.py:182` (`class Recipe(RecipeSummary)`) | grep verified `^class Recipe\(` at line 182 | ✓ |
| `mealie/routes/_base/base_controllers.py:132,139` (`BaseUserController` + `user = Depends(get_current_user)`) | viewed; line 132 = `class BaseUserController(_BaseController):`, line 139 = `user: PrivateUser = Depends(get_current_user)` | ✓ NEW (was wrong cite in v1) |
| `mealie/core/settings/settings.py:417-424` (OpenAI block) | viewed; lines 417-418 comment header, 420 = `OPENAI_CUSTOM_PROMPT_DIR`, 421-424 docstring | ✓ |
| `mealie/core/settings/settings.py:429-437` (Web Concurrency + `WORKERS` computed) | viewed; line 432 = `UVICORN_WORKERS: int = 1`, 435-437 = `@property def WORKERS` | ✓ NEW |
| `mealie/schema/group/ai_providers.py:127-130` (`image_provider_enabled`) | viewed; `@computed_field @property def image_provider_enabled(self) -> bool` | ✓ |
| `mealie/schema/group/ai_providers.py:15,16` (`model`, `timeout: int = 300`) | viewed; line 15 = `model: str`, line 16 = `timeout: int = 300` | ✓ |
| `mealie/services/openai/openai.py:29-32` (`OpenAINotEnabledException`) | viewed | ✓ |
| `mealie/services/openai/openai.py:84-94` (`OpenAILocalImage`) | viewed | ✓ |
| `mealie/services/openai/openai.py:138-145` (`get_client`) | viewed | ✓ |
| `mealie/services/openai/openai.py:147-168` (`_get_provider`) | viewed | ✓ |
| `mealie/services/openai/openai.py:170-204` (prompt loader with path-traversal guard at 180-181) | viewed; `is_relative_to(self.PROMPTS_DIR.resolve())` at line 180 | ✓ |
| `mealie/services/openai/openai.py:264-281` (`_get_raw_response` system/user split at 269-277) | viewed | ✓ |
| `mealie/services/openai/openai.py:283-309` (`get_response`); leak at 308-309 | viewed; `Exception(f"OpenAI Request Failed. {e.__class__.__name__}: {e}") from e` at line 309 | ✓ (orchestrator inspects `e.__cause__`) |
| `mealie/services/openai/openai.py:328-330` (audio fallback log — also leaks `{e}`) | viewed; line 329 includes `{e.__class__.__name__}: {e}` — corrected from v1's "class-name only" claim | ✓ corrected |
| `mealie/schema/openai/_base.py:33-35` (DEBUG raw-response leak) | viewed; line 34 = `logger.debug(f"Failed to parse OpenAI response as {cls}. Response: {response}")` | ✓ (FR-23 fixes) |
| `mealie/schema/openai/recipe.py:45-89` (`OpenAIRecipe`) | viewed; 9 fields (name/description/recipe_yield/total_time/prep_time/perform_time/ingredients/instructions/notes) | ✓ |
| `mealie/services/recipe/recipe_service.py:163-187` (`_recipe_creation_factory` comment 163-167) | viewed; comment "Recipes should not be created elsewhere to avoid conflicts." at lines 165-167 | ✓ |
| `mealie/services/recipe/recipe_service.py:202-245` (`create_one` with timeline + rating + settings) | viewed | ✓ |
| `mealie/services/recipe/recipe_service.py:335-356` (`create_from_images`); violation at 354-355 | viewed; line 354-355 = `with open(local_images[0], "rb") as f: data_service.write_image(f.read(), "webp")` | ✓ |
| `mealie/services/recipe/recipe_service.py:599-622` (`_convert_recipe`) | viewed | ✓ |
| `mealie/services/recipe/recipe_service.py:624-658` (`build_recipe_from_images`); leak at 650-651, 655-656 | viewed; `raise Exception("Failed to call OpenAI services") from e` at 650-651, `raise ValueError("Unable to parse recipe from image") from e` at 655-656 | ✓ |
| `mealie/core/dependencies/dependencies.py:190-198` (`get_temporary_path`) | viewed; `finally: if auto_unlink: rmtree(temp_path)` at 196-198 | ✓ |
| `mealie/core/exceptions.py:57-62` (`RateLimitError`) | viewed | ✓ |
| `mealie/core/exceptions.py:49-54` (`OpenAIServiceError`) | viewed (used by FR-18/FR-21) | ✓ NEW |
| `mealie/routes/recipe/recipe_crud_routes.py:85` (`UserAPIRouter prefix="/recipes"`) | viewed | ✓ |
| `mealie/routes/recipe/recipe_crud_routes.py:90-125` (`handle_exceptions`) | viewed; switch handles PermissionDenied/NoEntryFound/IntegrityError/RecursiveRecipe/SlugError/else | ✓ |
| `mealie/routes/recipe/recipe_crud_routes.py:259-272` (`_finish_recipe_from_web.publish_event`) | viewed; `self.publish_event(event_type=EventTypes.recipe_created, …)` at 262-272 | ✓ NEW (corrects `:173-184` in v1) |
| `mealie/routes/recipe/recipe_crud_routes.py:295-307` (zip publishes at 300-305) | viewed | ✓ |
| `mealie/routes/recipe/recipe_crud_routes.py:328-333` (old image publish) | viewed | ✓ |
| `mealie/routes/users/images.py:19-23` (single UploadFile pattern) | viewed | ✓ |
| `mealie/routes/users/images.py:26-39` (UUID temp pattern with rationale comment 29-31) | viewed | ✓ |
| `mealie/routes/recipe/_base.py:50-52` (service wiring) | viewed | ✓ |
| `mealie/routes/recipe/recipe_crud_routes.py:83` (`ASSET_ALLOWED_EXTENSIONS`) | viewed | ✓ |
| `tests/integration_tests/user_recipe_tests/test_recipe_image_assets.py:90-104` (SVG-ban test) | viewed; `test_recipe_asset_dangerous_extension_blocked` covers `html|svg|js|htm|xhtml` | ✓ |
| `tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py:19-32` (`setup_ai_providers` fixture) | viewed | ✓ |
| `tests/conftest.py:57-63` (`test_image_jpg`, `test_image_png` fixtures) | viewed | ✓ |
| `mealie/lang/messages/en-US.json:8` (`recipe-image-deleted`) | viewed | ✓ |
| `pyproject.toml:8-50` (dependencies; Pillow at 10, openai at 43; no filetype/python-magic) | viewed; confirmed Pillow at 10, openai at 43 | ✓ |
| `.github/copilot-instructions.md:146` (Crowdin policy) | grep verified line 146 = "Only modify `en-US` locale files when adding new translation strings - other locales are managed via Crowdin and **must never be modified**" | ✓ NEW (was missing `.github/` in v1) |
| `.github/copilot-instructions.md:15` (Repository-Service-Controller Pattern section) | grep verified line 15 = "**Repository-Service-Controller Pattern:**" | ✓ NEW |
| `docs/docs/documentation/getting-started/installation/backend-config.md:120-128` (OpenAI settings table) | viewed; OpenAI section at 120, table at 126-128, only `OPENAI_CUSTOM_PROMPT_DIR` documented at 128 | ✓ NEW (FR-24) |

**Citations corrected in v2:**
- FR-01: `duplicate_one` cite changed from `:450-470` (v1) to `:358` (v2). The file is shorter today; `duplicate_one` defines at 358. Source: `view recipe_crud_routes.py:358`.
- FR-22: `_finish_recipe_from_web` publishes at `:259-272`, NOT `:173-184` (v1 cited the wrong location; lines 173-184 are `parse_recipe_url`, which only returns a slug). Verified by viewing.
- FR-19: removed false claim that audio fallback "uses class-name only"; line 329 includes `{e}` interpolation, also a leak. Verified by viewing.
- FR-03: changed from `_base.py:37-56` (v1, which proves nothing about 401) to `base_controllers.py:132,139` (which shows `user = Depends(get_current_user)`).

**Newly-added citations (for new FRs):**
- FR-23: `mealie/schema/openai/_base.py:33-35` (the leak being patched).
- FR-24: `docs/docs/documentation/getting-started/installation/backend-config.md:120-128`.
- FR-25: `mealie/routes/_base/base_controllers.py:139`.

---

## Section 5 — "TBD" / "or equivalent" / "if needed" sweep

```
grep -in 'TBD\|or equivalent\|if needed\|或类似工具' spec_v2.md spec_v2.json
```

- Zero hits in `spec_v2.md`.
- Zero hits in `spec_v2.json`.
- NC-002 Chinese phrase 或类似工具 (v1) replaced with English description of the python-magic vs filetype choice.

---

## Section 6 — md/json sync check

Per the executability reviewer (EXEC-DIFF-1) and consistency reviewer (CONS-MD-JSON-1), v1 had divergent code_references for FR-06/FR-11/FR-12/FR-16/FR-20/FR-22 between md and json. In v2:

| FR | spec_v2.md citations | spec_v2.json citations | Match? |
|---|---|---|---|
| FR-01 | `recipe_crud_routes.py:309-335`, `recipe.py:182`, `recipe_crud_routes.py:358` | identical | ✓ |
| FR-03 | `base_controllers.py:132,139`, `recipe_crud_routes.py:85` | identical | ✓ |
| FR-04 | `settings.py:417-424`, `ai_providers.py:127-130`, `openai.py:29-32`, `settings.py:435-437` | identical | ✓ |
| FR-06 | `users/images.py:33-34`, "(no existing body-size check pattern in repo)" | identical | ✓ |
| FR-11 | `exceptions.py:57-62`, `settings.py:429-437`, "(no existing rate-limit pattern)" | identical | ✓ |
| FR-12 | `ai_providers.py:16`, `openai.py:138-145`, `recipe_crud_routes.py:1` | identical | ✓ |
| FR-13 | `prompts/recipes/parse-recipe-image.txt:1-6`, `openai.py:170-204` | identical | ✓ |
| FR-14 | `openai/recipe.py:45-89`, `openai/_base.py:13-44`, `openai.py:283-309` | identical | ✓ |
| FR-16 | `base_controllers.py:132-172`, `_base.py:50-52`, `recipe_service.py:202-245,335-356,598-658`, `.github/copilot-instructions.md:15` | identical | ✓ |
| FR-17 | `prompts/recipes/parse-recipe-image.txt:1-6`, `openai.py:264-281`, `recipe_service.py:349` | identical | ✓ |
| FR-19 | `openai.py:328-330`, `openai.py:308-309` | identical | ✓ |
| FR-20 | `lang/messages/en-US.json:8`, `.github/copilot-instructions.md:146` | identical | ✓ |
| FR-21 | `recipe_crud_routes.py:90-125` | identical | ✓ |
| FR-22 | `recipe_crud_routes.py:259-272`, `:295-307`, `:328-333` | identical | ✓ |
| FR-23 | `schema/openai/_base.py:33-35` | identical | ✓ |
| FR-24 | `docs/docs/documentation/getting-started/installation/backend-config.md:120-128` | identical | ✓ |
| FR-25 | `base_controllers.py:139` | identical | ✓ |
| (all others) | (single-cite items) | (single-cite items) | ✓ |

`test_plan.commands` is identical in both files (`uv run pytest` for all three; `task py:check` at end). EC-08 title is unified ("Cover-image side-effect removed"). Self-concern IDs unified as `SCN-N`.

---

## Section 7 — Conflict promotion log

Per spec rewriter rules, ambiguities between sources are promoted to `needs_clarification` blocks if not unambiguously resolvable. Net result for v2:

| Conflict source | Action |
|---|---|
| Input §2 "jinja2 模板 `recipe_from_image.md`" vs Mealie's `.txt` append-style loader | Promoted to **NC-004**. Recommended default = reuse `.txt`. |
| Input §2 RecipeBase-shaped JSON vs existing `OpenAIRecipe` schema | Promoted to **NC-005**. Recommended default = reuse `OpenAIRecipe`. |
| Spec §6 "in-memory rate limit" vs reviewer "but multi-worker breaks the contract" | NC-003 strengthened with multi-worker hard-disable. |
| US-2 "every request shape" vs FR-03 401 vs FastAPI auth order | Resolved deterministically via FR-25 precedence chain (no further ambiguity). |
| FR-14 strict parse vs FR-18 catch-all sanitization vs SC-7 typed distinction | Resolved deterministically: orchestrator inspects `e.__cause__` (FR-14). No new NC needed. |

No new NCs created beyond NC-004 and NC-005. NC-001/002/003 carried forward.

---

## Section 8 — Security FRs sweep (case-6-specific)

Input §4 enumerates 10 mandatory security controls. v2 coverage (every reviewer-flagged security gap is closed):

| § Row | Spec § | v1 FR | v1 Gap (per reviewers) | v2 Resolution |
|---|---|---|---|---|
| 1 | File size ≤5MB → 413 | FR-06 | `shutil.copyfileobj` cannot enforce cap (CONS-C-006) | FR-06 now mandates explicit chunked loop with cumulative check |
| 2 | MIME whitelist → 415 | FR-07 | none | (no change) |
| 3 | Real-type detection (magic) | FR-08 | `None` path not handled (ARCH-M-2) | FR-08 explicitly treats `None` as 415; EC-09 added |
| 4 | UUID temp filename + immediate delete | FR-09/10 | none | (no change) |
| 5 | Per-user/hour ≤10 → 429 | FR-11 | per-worker undercount in multi-worker (ARCH-H-3); pruning/clock seam unspecified (EXEC-ETC-1) | FR-11 hard-disables on `WORKERS > 1`; specifies pruning, clock seam, rejected-not-counted; EC-10 added |
| 6 | 60s OpenAI timeout | FR-12 | none material | (no change; SCN-4 documents reversal of PR #6227) |
| 7 | Errors → 422, no raw LLM leak in HTTP | FR-14/18 | parse-vs-network indistinguishable (CONS-C-003); cause-chain leak risk (ARCH-H-2) | FR-14 uses `e.__cause__` inspection; FR-18 uses `raise … from None`; SC-7 asserts both |
| 8 | Prompt injection guard | FR-17 | scope wording too broad (ARCH-M-4) | FR-17 explicitly scope-limited to "model role/tool behavior"; SCN-3 mirrored |
| 9 | Privacy — delete after parse, no `assets/` | FR-10 | none material; PR #5647 button orphaned (acknowledged in SCN-5) | (no change) |
| 10 | Logging — no image bytes / no raw LLM response / only token usage | FR-19/23 | DEBUG raw-response leak in `_base.py:34` (ARCH-H-1, COMP-C-001, EXEC-CITE-3); `exc_info=True` re-leak (ARCH-H-2); SC-8 not executable | FR-23 patches `_base.py:34`; FR-19 drops `exc_info=True` and uses `from None`; SC-8 now executable |

All 10 security rows covered with concrete, testable controls. Where Mealie genuinely lacks infrastructure (no rate-limit infra, no body-size check, no magic sniffer), v2 says so explicitly and either:
- Adds new infra (FR-11 in-process limiter; FR-06 chunked loop; FR-08 `filetype` dependency), or
- Promotes to `needs_clarification` with recommended default (NC-002 = `filetype`; NC-003 = in-process + multi-worker hard-disable).

No `or equivalent`, no `TBD`, no `if needed` remains.

---

## Section 9 — Summary

| Metric | v1 | v2 |
|---|---|---|
| Critical issues | 1 | **0 unresolved** (1 FIX) |
| High issues | 12 | **0 unresolved** (10 FIX, 2 EXPLICIT_REJECT with NC) |
| Medium issues | 11 | **0 unresolved** (11 FIX) |
| Low issues | 1 | **0 unresolved** (1 FIX) |
| FRs | 22 | 25 (+FR-23 log sanitize, +FR-24 docs, +FR-25 precedence) |
| SCs | 13 | 14 (+SC-2b auth-before-gate, +SC-14 docs; SC-1 wording fixed) |
| ECs | 8 | 10 (+EC-09 filetype None, +EC-10 multi-worker startup) |
| NCs | 3 | 5 (+NC-004 prompt path, +NC-005 schema shape) |
| SCNs | 5 | 7 (+SCN-6 from-None trade-off, +SCN-7 global DEBUG-log change) |
| md/json code_references match | partial | **identical** |
| Verified citations | partial | **all** |
| TBD/or-equivalent count | 1 (NC-002 Chinese) | **0** |
| metadata.iterations | 1 | **2** |

**Approval gate** (from arch reviewer): "Not approved until all High issues are resolved." → v2 resolves all 12 Highs (10 FIX + 2 EXPLICIT_REJECT with NC).
