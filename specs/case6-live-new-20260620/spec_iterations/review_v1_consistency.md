# Review v1 — Axis: Consistency

**Reviewer**: case6-live-new-20260620-v1 / consistency
**Spec under review**: `spec.json` v1 (6 stories, 25 FRs, 15 SCs, 12 ECs, 3 NCs, 4 concerns)
**Intent type**: `add_feature` · **Scope**: backend, api, external_integration, security, test

## Mental model

Internal-consistency means: every FR is congruent with every other FR; every SC is congruent with the FR it verifies; every EC handles a situation that some FR creates; assumptions, entities, and out-of-scope items don't contradict the FRs.

## Findings

### Y-H-001 [HIGH] FR-016 vs FR-011 directly contradict on the owner of the rate-limit call

**Location**: FR-016 (controller "owns ... rate-limit reservation call") vs FR-011 ("the orchestrator calls `await get_rate_limiter().check_and_record(user.id)`").

A code agent following FR-016 puts the rate-limit in the **controller**, before `await self.service.create_from_image(...)`. A code agent following FR-011 puts it inside the service, after the magic-byte sniff. The two specs cannot both ship.

Worse: the placement matters for the v2 trap the spec claims to fix. Controller-side rate-limit runs before FR-006/008 even execute (because both are service-side), reintroducing the rate-limit-before-MIME bug that the spec text explicitly calls out as "the bug fixed from the old v2 spec".

Also see: Architecture A-H-001 (same finding from architecture lens).

**Verdict**: confirmed_problem.

### Y-H-002 [HIGH] FR-017's claim that `cleaner.clean` sanitizes the LLM-generated recipe is not grounded in the new flow's code path

**Location**: FR-017 (last sentence: "the existing `cleaner.clean(recipe_data, self.translator)` HTML/script sanitizer runs before persistence").

The cited `cleaner.clean` call lives at `mealie/services/recipe/recipe_service.py:349` — inside `RecipeService.create_from_images` (the OLD multi-image flow that this spec **replaces**). FR-015 explicitly says the new flow calls `RecipeService.create_one(recipe_data)` after `_convert_recipe`. Neither `create_one` (lines 202-245) nor `_convert_recipe` (lines 599-622, per the exploration) is documented as calling `cleaner.clean`.

So the spec asserts a sanitizer guarantee that the spec's own implementation plan does not actually invoke. This is an internal contradiction: FR-015 (flow) vs FR-017 (security claim).

Either:

* add an explicit FR requiring `cleaner.clean(recipe_data, self.translator)` to run inside `_convert_recipe` or between `_convert_recipe` and `create_one`, or
* delete the misleading sanitizer claim from FR-017 and explicitly raise the residual risk in a NEW NeedsClarification.

**Verdict**: confirmed_problem.

### Y-M-001 [MEDIUM] EC-04 vs FR-018's error-classification scheme: corrupted JPEG path maps to `recipe.image.openai-failed`, not `recipe.image.parse-failed`

**Location**: EC-04 ("File magic-byte check passes but the JPEG is corrupted ... raises `OpenAIServiceError('recipe.image.openai-failed')`") vs FR-018's scheme.

A corrupted JPEG that fails inside `OpenAILocalImage.get_image_url` is a **client-side data-quality** problem, not an **upstream OpenAI** problem. Mapping it to `recipe.image.openai-failed` will confuse users (who'll think OpenAI is down) and complicates SRE dashboards (every corrupted upload looks like an OpenAI outage). Recommend introducing `recipe.image.image-decode-failed` as a separate i18n key (and a new branch in handle_exceptions).

**Verdict**: confirmed_problem (mild).

### Y-M-002 [MEDIUM] FR-009 wraps "the orchestrator body" in `get_temporary_path`, but FR-006 says "the service writes the upload to a temp file" — sequence is ambiguous

**Location**: FR-006 + FR-009.

FR-009 says the **orchestrator** opens the temp_dir via the context manager. FR-006 says the **service** writes the upload to a temp file. If the orchestrator IS the service (consistent terminology elsewhere), this is fine — but the spec uses both terms interchangeably without defining whether they're synonyms or two layers. A code agent will guess.

**Verdict**: confirmed_problem (mild).

### Y-M-003 [MEDIUM] FR-006 says size cap "runs BEFORE the rate-limit (FR-011)" — FR-011 itself agrees, but the orchestrator owns FR-006 while FR-016 says controller owns FR-011 — therefore the size cap can never run before the rate-limit

**Location**: FR-006 + FR-011 + FR-016.

Compounds Y-H-001: if the controller runs rate-limit (per FR-016) BEFORE delegating to the service that runs the chunked write (per FR-006), then FR-006's ordering claim ("BEFORE the rate-limit") is violated by the controller layout in FR-016. The three FRs cannot all be true.

**Verdict**: confirmed_problem.

### Y-M-004 [MEDIUM] Out-of-scope item "old `translate_language` query parameter is removed" creates an unannounced public-API break

**Location**: FR-002 + out_of_scope item.

FR-002 says `translate_language: str | None` is removed; the out-of-scope list says "Translation of the recipe to another language ... deferred to a separate feature". An existing API contract being removed is the kind of breaking change that needs to land in a deprecation notice, in CHANGELOG, and in versioned API behavior — none of which are FRs.

**Verdict**: confirmed_problem (mild). Could be deferred but should at least be a NeedsClarification.

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 2    |
| Medium   | 4    |

## Final verdict

**Verdict: needs_refine**

Y-H-001 (rate-limit ownership) and Y-H-002 (unsourced sanitizer guarantee) both ship code that contradicts the spec's own promises. The 4 medium issues are downstream symptoms of the same two confusions.
