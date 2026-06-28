# Executability Review v1 — Case-6 LLM image-to-recipe

## Verdict

**Needs revision before implementation.** The spec is mostly executable, but several citations are missing/wrong/imprecise, `spec.md` and `spec.json` code references are not identical for multiple FRs, and one logging/security assertion conflicts with the cited code and the proposed DEBUG-level test.

## Checks performed

- Opened `spec.md` and `spec.json`.
- Opened every concrete existing Mealie file cited in FR code references and test-plan/file lists.
- Verified cited line ranges against the symbols/assertions they are meant to support.
- Compared FR `code_references` in `spec.md` vs `spec.json`.
- Searched the spec folder for `TBD`, `or equivalent`, `if needed`, `TODO`, and Chinese equivalent wording.

## Path reality

### Missing or not-yet-real paths

- `mealie/services/openai/rate_limit.py` — cited in `spec.md` FR-11 and listed in `spec.json.files_to_add`; does not exist yet. This is fine as a planned new file, but it should not be described as a verified existing code reference.
- `tests/unit_tests/services/openai/test_vision.py` — listed as new; does not exist yet.
- `tests/unit_tests/services/recipe/test_recipe_from_image.py` — listed as new; does not exist yet.
- `copilot-instructions.md` — cited in `spec.md` FR-16/FR-20 without `.github/`; the real file is `.github/copilot-instructions.md`.

All other concrete existing cited paths I checked exist, including `mealie/routes/recipe/recipe_crud_routes.py`, `mealie/services/recipe/recipe_service.py`, `mealie/services/openai/openai.py`, `mealie/schema/openai/_base.py`, `mealie/schema/openai/recipe.py`, `mealie/core/settings/settings.py`, `mealie/core/dependencies/dependencies.py`, `mealie/lang/messages/en-US.json`, `pyproject.toml`, `tests/conftest.py`, and `tests/integration_tests/user_recipe_tests/test_recipe_create_from_image.py`.

## Wrong/imprecise citations

- **FR-03**: `mealie/routes/recipe/_base.py:37-56` shows `BaseRecipeController(BaseCrudController)` and service wiring, but it does **not** prove unauthenticated calls return 401 or show `Depends(get_current_user)`. Add the actual `UserAPIRouter`/base controller dependency line if that assertion must be verified.
- **FR-16**: `spec.md` cites `copilot-instructions.md` without a real path and without line range. Use `.github/copilot-instructions.md`, ideally the architecture section line range.
- **FR-19**: `mealie/services/openai/openai.py:328-330` is described as “audio fallback uses class-name only”, but line 329 includes both `{e.__class__.__name__}` **and** `{e}`. The citation does not support “class-name only”.
- **FR-19 / SC-8 conflict**: `mealie/schema/openai/_base.py:33-35` logs the raw OpenAI response at DEBUG on parse failure. SC-8 says run `caplog` at DEBUG and assert no mocked LLM response text appears in logs. As written, the cited existing code makes that test fail unless the implementation also removes/sanitizes this DEBUG log.
- **FR-20**: `spec.md` cites `copilot-instructions.md`; real path is `.github/copilot-instructions.md`. `spec.json` uses the real path but no line range. The relevant translation rule is at `.github/copilot-instructions.md:146`.
- **FR-22**: `mealie/routes/recipe/recipe_crud_routes.py:173-184` is not an event-emission citation. It is `POST /create/url`, returns `str`, and contains no `publish_event(EventTypes.recipe_created, ...)`. Use the actual helper/range that publishes the URL-scrape event, or remove this as an event-emission precedent.
- **FR-06 wording**: “during `shutil.copyfileobj` (chunked, abort on cumulative > cap)” is implementation-imprecise. `copyfileobj` does not by itself expose cumulative byte checks; the spec should require an explicit chunk loop or a bounded reader wrapper.
- **EC-03 / self_concerns**: cites `recipe_service.py:349` for `cleaner.clean`, which is accurate today, but after rewriting `create_from_images` the line number will change. This is acceptable as a current-state citation but fragile.

## Line-range verification summary

Accurate representative ranges verified:

- `recipe_crud_routes.py:309-335` contains the current `POST /create/image` endpoint.
- `recipe_crud_routes.py:450-470` contains `duplicate_one`, `status_code=201`, `response_model=Recipe`.
- `recipe.py:182-393` contains `class Recipe(RecipeSummary)`.
- `users/images.py:19-23` contains a single `UploadFile = File(...)` pattern; `26-39` contains `get_temporary_path`, UUID filename, and `shutil.copyfileobj`.
- `settings.py:417-424` is the OpenAI settings block; `432` is `UVICORN_WORKERS: int = 1`.
- `ai_providers.py:15-16` contains `model` and `timeout`; `127-130` contains `image_provider_enabled`.
- `openai.py:29-32`, `138-145`, `170-204`, `264-281`, `283-309`, and `328-330` all exist, subject to the FR-19 caveat above.
- `recipe_service.py:163-187`, `202-245`, `335-356`, and `598-658` all exist and contain the cited creation/conversion/image-flow code.
- `dependencies.py:190-198` contains `get_temporary_path` and `rmtree` in `finally`.
- `test_recipe_image_assets.py:90-104` contains the scriptable-extension/SVG rejection test.
- `en-US.json:8` contains `recipe-image-deleted`.

## `spec.md` vs `spec.json` `code_references`

They are **not identical** for these FRs:

- **FR-06**: `spec.md` additionally mentions grep over `tests/` and `mealie/`; `spec.json` only keeps the `users/images.py` range plus a prose no-pattern note.
- **FR-11**: `spec.md` references new `mealie/services/openai/rate_limit.py` and `pyproject.toml`; `spec.json` omits both from `code_references`.
- **FR-12**: `spec.json` includes `mealie/routes/recipe/recipe_crud_routes.py:1`; `spec.md` does not.
- **FR-16**: `spec.json` includes `recipe_service.py:335-356` and `598-658`; `spec.md` has them only as unbackticked prose and cites `copilot-instructions.md` instead.
- **FR-20**: `spec.md` uses `copilot-instructions.md`; `spec.json` uses `.github/copilot-instructions.md`.
- **FR-22**: `spec.json` includes URL and zip precedent ranges `173-184` and `295-307`; `spec.md` only has `328-333` backticked plus prose.

## TBD / “or equivalent” / “if needed” phrases

- No `TBD`, English `or equivalent`, or `if needed` found in `spec.md`/`spec.json`.
- Chinese equivalent wording remains in NC-002: “用 `python-magic` 或类似工具”. The recommended default (`filetype==1.2.0`) resolves it, but the ambiguous source phrase is still present in `spec.md` and `spec.json`.
- `TODO` appears only in exploration files, not in `spec.md`/`spec.json`.

## Security-control executability

Mostly concrete/testable:

- Feature flag, per-group gate, size cap, MIME whitelist, magic-byte sniff, UUID temp path, temp cleanup, timeout, i18n keys, HTTP status mapping, and no HTTP raw-LLM leakage have measurable expected behavior.

Needs tightening:

- Logging control must require sanitizing/removing `OpenAIBase._process_response` DEBUG raw-response logging; otherwise SC-8 is not executable.
- Prompt-injection mitigation is testable only as “guard text exists in prompt”, not as a guarantee of model behavior. State that explicitly.
- Rate limiter is concrete enough on storage (`dict[UUID, deque[datetime]]` + `asyncio.Lock`), but should specify pruning semantics, whether rejected attempts are recorded, clock injection for tests, and exact startup hook for the multi-worker WARN.
- Multi-worker undercount is accepted by the spec, but the security assertion should say the limit is per process unless DB-backed storage is chosen.

## Recommendation

Revise citations and sync `spec.md`/`spec.json` before implementation. The largest executability blocker is FR-19/SC-8: current DEBUG logging leaks raw LLM response, contradicting the proposed security test.
