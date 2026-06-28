# Review v1 — Axis: Architecture

**Reviewer**: case6-live-new-20260620-v1 / architecture
**Spec under review**: `spec.json` v1 (6 stories, 25 FRs, 15 SCs, 12 ECs, 3 NCs, 4 concerns)
**Intent type**: `add_feature` · **Scope**: backend, api, external_integration, security, test
**Validators baseline**: A4/A5/B1/B3 = 0 problems

## Mental model

`add_feature` for a new HTTP endpoint that reuses three existing pillars:
1. `OpenAIService` (`mealie/services/openai/openai.py:108-309`) as the vision client
2. `OpenAIRecipe` (`mealie/schema/openai/_base.py:13-44`) as the strict response schema
3. `RecipeService.create_one` (`mealie/services/recipe/recipe_service.py:202-245`) as the persistence entry

Mealie's documented architecture (per `.github/copilot-instructions.md`) is a **three-layer pattern**: controller → service → repository, with `handle_exceptions` in the controller mapping domain errors to HTTP. The architecture review must check that the spec actually preserves these boundaries.

## Findings

### A-H-001 [HIGH] Controller/service ownership of the rate-limit call is contradictory across FRs

**Location**: FR-016 vs FR-011.

- **FR-016** explicitly says: _"the controller `RecipeController.create_recipe_from_image` owns HTTP-only concerns: form-field presence, Content-Type header check (FR-007), **the rate-limit reservation call right before delegation (FR-011)**, public..."_
- **FR-011** explicitly says: _"The **orchestrator** calls `await get_rate_limiter().check_and_record(user.id)` IMMEDIATELY BEFORE the OpenAI call and AFTER FR-006 (size), FR-007 (Content-Type header), FR-008 (magic-byte sniff), and FR-009 (file written to UUID temp path) have all passed."_

These contradict on the owner. If the controller owns rate-limit (FR-016), then it runs BEFORE the service is even invoked — which means BEFORE the chunked-write size check (FR-006), BEFORE the magic-byte sniff (FR-008), and BEFORE the file is on disk (FR-009). That contradicts FR-011's explicit ordering claim "AFTER FR-006/007/008/009".

A downstream code agent reading the spec literally will pick one of two implementations:
1. Implements rate-limit in the controller → loses the "AFTER all input validation" property → reintroduces the **v2 trap** the spec claims to fix.
2. Implements rate-limit in the orchestrator → contradicts FR-016's ownership table, leaving the controller's responsibility for FR-011 unimplemented.

**Verdict**: confirmed_problem. The architecture cannot ship with this contradiction.

### A-H-002 [HIGH] FR-019 mutates a globally-shared file used by URL-scrape and audio flows without specifying behavior preservation tests for them

**Location**: FR-019 (DEBUG-log scrub at `mealie/schema/openai/_base.py:33-34`).

The spec replaces the per-class DEBUG log inside `OpenAIBase._process_response` — a file used by:

* the new image-to-recipe flow (this spec)
* the existing URL-scrape flow (`mealie/services/recipe/recipe_service.py` create-from-url path)
* the existing audio-to-recipe flow (if/when added)

The self-concern at FR-019 acknowledges _"net positive ... but"_ and stops there. Architecture review requires:

* an explicit FR or SC asserting the URL-scrape regression tests still pass after the patch;
* a callout that operators relying on the old DEBUG dump for production triage of URL-scrape failures will lose that observability.

Without these, the spec ships a global behavior change behind a feature-specific FR — which is an architectural smell that a future maintainer of the URL flow will be blindsided by.

**Verdict**: confirmed_problem.

### A-M-001 [MEDIUM] `HourlyUserRateLimiter` as a module-level singleton bypasses Mealie's service factory pattern

**Location**: FR-011 (`mealie/services/openai/rate_limit.py` singleton).

Mealie's three-layer pattern wires services via factories (per `RecipeService.factory` at `mealie/services/recipe/recipe_service.py:163-187`). A module-level singleton:

* is invisible to the existing dependency-injection wiring;
* is hard to mock in tests without monkeypatching the import (the `_clock` seam helps for time, not for the limiter itself);
* makes the per-process counter implicit rather than explicitly owned by an `app.state`-rooted service.

**Verdict**: confirmed_problem (mild). Recommended fix: instantiate the limiter on `app.state` at startup and inject it via FastAPI `Depends`. Falls naturally out of the FR-004 startup hook that already runs.

### A-M-002 [MEDIUM] `RecipeController.handle_exceptions` extension order is not normative

**Location**: FR-021.

FR-021 lists five new branches in an order, but Mealie's existing `handle_exceptions` (`recipe_crud_routes.py:90-125`) uses an `isinstance` chain. If `RateLimitError` is added BEFORE `OpenAIServiceError` and a future maintainer makes `RateLimitError` a subclass of `OpenAIServiceError`, the wrong branch fires. FR-021 doesn't pin the relative isinstance order, leaving a subtle refactor hazard.

**Verdict**: uncertain. Could be ignored if the existing chain is `if/elif` on concrete classes only.

## Score

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 2    |
| Medium   | 2    |

## Final verdict

**Verdict: needs_refine**

The two HIGH issues (controller-vs-orchestrator rate-limit ownership and the missing URL/audio regression coverage for FR-019) both rise to "could land buggy code on direct read" — must be fixed before v2 ships.
