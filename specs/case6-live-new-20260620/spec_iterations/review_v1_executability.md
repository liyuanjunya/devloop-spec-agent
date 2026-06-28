# Review v1 — Axis: Executability

**Reviewer**: case6-live-new-20260620-v1 / executability
**Spec under review**: `spec.json` v1 (6 stories, 25 FRs, 15 SCs, 12 ECs, 3 NCs, 4 concerns)
**Intent type**: `add_feature` · **Scope**: backend, api, external_integration, security, test

## Mental model

Executability asks: can a literal-minded code agent ship this spec **without further clarification**? Every cited symbol, line range, and library API must resolve; every "the orchestrator does X" must have a concrete entry point; every "extend Y" must name Y.

## Findings

### E-H-001 [HIGH] FR-018's `e.__cause__` inspection relies on an `OpenAIService` behavior that is not specified

**Location**: FR-018.

FR-018 says: _"The orchestrator catches every non-RateLimitError exception from `get_response` and re-raises `OpenAIServiceError(<i18n-key-literal>) from None`"_, and the adjacent edge cases (EC-02, EC-04, EC-06) say _"orchestrator inspects `e.__cause__`, sees `ValidationError`, raises ..."_.

This works only if `OpenAIService.get_response` raises with `from e` (explicit cause). The existing code at `mealie/services/openai/openai.py:308-309` is:

```py
raise OpenAIError(f"OpenAI Request Failed. {e.__class__.__name__}: {e}")
```

There is **no `from e`** — meaning the cause chain is **implicit** (`__context__`, not `__cause__`). The orchestrator inspecting `e.__cause__` will see `None` and fall through to the "unknown error" branch for ALL of EC-02, EC-04, EC-06, and SC-007's parse-failure path — producing the wrong i18n key (and possibly leaking the wrapped str).

A code agent implementing the spec literally will write:

```py
except Exception as e:
    if isinstance(e.__cause__, ValidationError):
        raise OpenAIServiceError("recipe.image.parse-failed") from None
    ...
```

…and silently misclassify every failure. The spec needs to either (a) require a small edit to `openai.py:308-309` to use `raise OpenAIError(...) from e`, or (b) tell the orchestrator to inspect `e.__context__` (or to string-match `e.__class__.__name__` inside the wrapped exception's message), or (c) raise typed sub-exceptions per failure category.

**Verdict**: confirmed_problem.

### E-H-002 [HIGH] FR-005's per-call model override mechanism is under-specified

**Location**: FR-005.

FR-005 says: _"the orchestrator builds a per-call provider override via `provider.model_copy(update={"model": settings.OPENAI_IMAGE_MODEL})` and passes it as ..."_ — and the sentence is truncated in the spec text. The actual override path needs to specify:

1. Which method on `OpenAIService` accepts the per-call override (current `get_response` at line 283-309 does not take a `provider=` kwarg)
2. Whether the override applies only to the model name or also to `provider.timeout` and `provider.api_base`
3. Whether `_get_provider` (line 147-168) must be modified or whether the override is injected upstream

Without these, a code agent must either guess (likely picking the wrong layer) or add a kwarg to `get_response` that diverges from the rest of the codebase.

**Verdict**: confirmed_problem.

### E-M-001 [MEDIUM] FR-013's prompt-loading path is asserted but the location of the appended paragraph is not pinned

**Location**: FR-013.

FR-013 says the existing `parse-recipe-image.txt` is "loaded by the existing dotted-name lookup `openai_service.get_prompt("recipes.parse-recipe-image")`" and a "new paragraph is appended" with prompt-injection guidance. The spec does not say:

* where in the file the new paragraph goes (top, bottom, after a marker)
* whether the existing 6 lines stay verbatim or get reworded
* what the literal text of the new paragraph is

This is the difference between "I can implement this" and "I have to invent the exact wording". Recommend specifying the literal text or pointing to an attachment.

**Verdict**: confirmed_problem (mild).

### E-M-002 [MEDIUM] HourlyUserRateLimiter's `_clock` seam needs an explicit FR or its semantics will drift

**Location**: FR-011 + assumption #4.

Assumption #4 says `_clock` is a Callable returning `datetime`. FR-011 says it is `staticmethod(datetime.utcnow)`. These two are consistent only if the assumption is read closely. A code agent could implement `_clock` as the `datetime.utcnow` value (already-called) rather than the callable. Add an explicit FR pinning the type and a unit test asserting monkeypatching works.

Also: `datetime.utcnow()` is deprecated in Python 3.12 in favor of `datetime.now(UTC)`. Spec should pick the forward-compatible form.

**Verdict**: confirmed_problem (mild).

### E-M-003 [MEDIUM] FR-021's `handle_exceptions` extension doesn't show the integration point

**Location**: FR-021.

FR-021 says "extend `RecipeController.handle_exceptions` with FIVE new branches in this order". Mealie's `handle_exceptions` lives at `mealie/routes/recipe/recipe_crud_routes.py:90-125`. The spec doesn't say:

* whether the new branches go inline in that file or in a new mixin
* whether `handle_exceptions` becomes a decorator that wraps `create_recipe_from_image`, or whether the controller's method body wraps a try/except itself
* the existing branches it must NOT alter

Recommend adding a diff-style hint in the FR or a code-reference snippet.

**Verdict**: confirmed_problem (mild).

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 2    |
| Medium   | 3    |

## Final verdict

**Verdict: needs_refine**

E-H-001 is a real risk of shipping silently-wrong code — every OpenAI failure would be misclassified, and the spec's i18n / no-leak promises would silently fail in production. E-H-002 leaves the model-override mechanism ambiguous enough that a code agent will invent its own API.
