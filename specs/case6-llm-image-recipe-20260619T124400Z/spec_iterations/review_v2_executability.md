# Executability Review v2 — Case-6 LLM image-to-recipe

## Verdict

**Needs one more revision before implementation.** v2 fixes the major v1 logging/citation problems, but it is not fully executable because the mandated rate-limit ordering makes SC-5 impossible, and at least one strict line citation is wrong.

## Checks performed

- Opened `spec_v2.md`, `spec_v2.json`, `review_v1_executability.md`, and `rewrite_v1_to_v2.md`.
- Re-verified concrete Mealie line ranges under `C:\Users\v-liyuanjun\Downloads\mealie\`.
- Searched `spec_v2.*` for `TBD`, `or equivalent`, `if needed`, `或类似工具`, and `TODO`.
- Compared material `spec_v2.md` vs `spec_v2.json` references and checked planned-new-file reality.

## Blocking executability issues

### EXEC-V2-1 — Rate-limit ordering contradicts rejected-attempt semantics

`spec_v2.md:20` says only requests that pass auth, gate, size, and MIME are recorded, and rejected attempts do not consume quota. `spec_v2.md:42` / `spec_v2.md:144` define `check_and_record` as appending when quota remains. But `spec_v2.md:56` and `spec_v2.md:133` require the controller to run rate-limit before size pre-check and MIME header validation. Therefore a 413/415 request would already have been appended, contradicting `spec_v2.md:69` and `spec_v2.md:152`, which require a 413 mid-loop not to consume quota.

**Fix:** split the limiter into `check` + `record_success`, or move `check_and_record` after all validation and define exactly whether OpenAI/parse failures count. As written, SC-5 is not implementable.

### EXEC-V2-2 — FR-01 duplicate endpoint citation is wrong

`spec_v2.md:32` and `spec_v2.json:58-62` cite `mealie/routes/recipe/recipe_crud_routes.py:358` as `duplicate_one` / `response_model=Recipe`. In the verified repo, `recipe_crud_routes.py:358` is `UUID(search_query.cookbook)`, not `duplicate_one`. The actual duplicate endpoint is `recipe_crud_routes.py:450-451` (`@router.post(... response_model=Recipe)` and `def duplicate_one`).

**Fix:** change the citation to `mealie/routes/recipe/recipe_crud_routes.py:450-451` or `450-456`.

## Additional findings

- **md/json reference drift remains.** Material examples: `spec_v2.md:34` includes `mealie/core/dependencies/dependencies.py` with no line range, while `spec_v2.json:73-78` omits it; `spec_v2.md:39` includes a “no existing magic-bytes pattern” note omitted from `spec_v2.json:116-120`; `spec_v2.md:54` includes `SC-8` as a reference while `spec_v2.json:242-246` does not; `spec_v2.md:56` references `approach/selected.md` with no line and JSON omits it.
- **FR-16 citation is imprecise.** `spec_v2.md:47` cites `base_controllers.py:132-172` as “BaseUserController + BaseCrudController”; verified `BaseCrudController` starts at `base_controllers.py:192`, while `BaseRecipeController` inherits it at `routes/recipe/_base.py:37`.
- **User-story AC links are undefined.** `spec_v2.md:17-22` and `spec_v2.json:16-52` reference `AC-01`…`AC-12`, but v2 defines SCs, not ACs. Either define ACs or point user stories to SC IDs.

## Line-range verification summary

Accurate ranges verified: auth dependency at `base_controllers.py:132-139`; `BaseCrudController` at `base_controllers.py:192`; route/service wiring at `routes/recipe/_base.py:37,50-52`; existing image endpoint at `recipe_crud_routes.py:309-335`; event precedents at `recipe_crud_routes.py:259-272`, `295-307`, `328-333`; OpenAI leak/wrapper ranges at `openai.py:283-309`, `328-330`, `_base.py:33-35`; temp cleanup at `dependencies.py:190-198`; recipe service ranges at `recipe_service.py:335-356`, `598-658`; docs/env/i18n ranges at the cited files.

No `TBD`, `or equivalent`, `if needed`, `或类似工具`, or `TODO` remains in `spec_v2.md`/`spec_v2.json`. Planned new files (`rate_limit.py`, two unit-test files) do not yet exist, as expected.
