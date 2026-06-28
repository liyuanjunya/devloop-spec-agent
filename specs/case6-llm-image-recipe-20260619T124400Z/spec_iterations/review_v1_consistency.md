# Consistency Review v1 — Case-6 LLM Image-to-Recipe

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION

## Summary

The spec is detailed and mostly aligned on the selected architecture, but it has several blocking consistency defects around request/error precedence, parse-failure classification, and logging secrecy. The markdown and JSON also diverge in implementation guidance and test commands. Resolve the High findings before implementation so agents do not pick incompatible behavior.

## Findings

### C-001 — Feature-disabled 503 contradicts unauthenticated 401

- **Severity**: High
- **Scope**: US ↔ FR ↔ SC contradiction
- **Locations**:
  - `spec.md`: US-2 says any call with `OPENAI_ENABLE_IMAGE_RECIPE` unset returns 503; SC-2 explicitly includes `unauth` returning 503.
  - `spec.md`: FR-03 says unauthenticated calls return 401 via existing auth dependency.
  - `spec.json`: `success_criteria[1]` says every request shape returns 503 without env var; `functional_requirements[2]` says unauthenticated calls return 401.
- **Issue**: An unauthenticated request cannot return both 401 and 503. Since the route is under authenticated routing, implementation agents need an explicit precedence rule.
- **Recommendation**: Choose one: either auth always runs first (`unauth -> 401` even when feature disabled), or the endpoint performs a pre-auth feature gate. Update US-2, FR-03, SC-2, and tests together.

### C-002 — Error precedence is underspecified for feature-off vs validation failures

- **Severity**: High
- **Scope**: US ↔ FR ↔ SC contradiction
- **Locations**:
  - US-2 / SC-2 require feature-off default to return 503 for every request shape.
  - US-3 / FR-06 / FR-07 / FR-08 require oversize and MIME spoofing to return 413/415.
- **Issue**: With the default feature flag off, an oversize or unsupported upload appears to be both 503 and 413/415 unless tests explicitly enable the feature. This affects validation order and whether security checks run when the feature is disabled.
- **Recommendation**: Add a global precedence rule, e.g. `auth -> feature gate -> size/header/magic/rate/OpenAI`, and state that 413/415/429 tests run with `OPENAI_ENABLE_IMAGE_RECIPE=true` and provider enabled.

### C-003 — Parse failures cannot be reliably distinguished if `get_response` owns strict parsing and catch-all wrapping

- **Severity**: High
- **Scope**: FR ↔ EC ↔ SC contradiction
- **Locations**:
  - FR-14 says reuse `OpenAIBase.parse_openai_response` inside `OpenAIService.get_response`; `ValidationError` / `JSONDecodeError` become `recipe.image.parse-failed`.
  - FR-18 says the existing `get_response` leak site is bypassed because the outer orchestrator catches exceptions.
  - EC-02 says `parse_openai_response` raises directly to the orchestrator.
  - SC-7 expects malformed JSON / pydantic validation to map to `parse-failed`, while generic OpenAI/network errors map to `openai-failed`.
- **Issue**: If parsing happens inside `get_response` and `get_response` catches all exceptions at `openai.py:308-309`, the orchestrator may only see a wrapped `OpenAIServiceError` and lose whether the root cause was parse vs network. FR-14 and EC-02 describe a control flow that conflicts with the referenced existing implementation.
- **Recommendation**: Specify the exact implementation: either modify `get_response` to preserve typed parse errors for this path, add a separate safe `get_response` variant/helper, or move image-recipe parsing outside the catch-all. Then align FR-14, FR-18, EC-02, and SC-7.

### C-004 — Logging requirements conflict with `exc_info=True` and DEBUG capture tests

- **Severity**: High
- **Scope**: US ↔ FR ↔ SC; self_concerns ↔ FRs
- **Locations**:
  - US-5 says server logs contain only the i18n key, user id, and parse response length; never response content.
  - FR-19 prescribes `logger.warning(..., exc_info=True)`.
  - FR-19 also calls the `_base.py:33-35` DEBUG raw-response log “acceptable” because production is INFO+.
  - SC-8 requires pytest `caplog` at DEBUG to prove no image bytes / LLM body in captured logs.
- **Issue**: `exc_info=True` can log exception messages and stack traces, contradicting “only” key/user/length. The DEBUG raw-response log being acceptable in FR-19 directly conflicts with SC-8’s DEBUG-level assertion.
- **Recommendation**: Remove raw-response DEBUG logging for this flow or lower SC-8 to INFO+ intentionally. If `exc_info=True` remains, explicitly sanitize/chainsuppress exceptions so stack traces cannot include upstream bodies or leaky messages.

### C-005 — SC-1 says “four LLM-extracted fields” but only three are required/measured

- **Severity**: Medium
- **Scope**: AC-internal; US ↔ SC
- **Locations**:
  - US-1 requires `name`, `recipe_ingredient[]`, and `recipe_instructions[]`.
  - SC-1 criterion says “all four LLM-extracted fields populated” but the measure checks only `name`, ingredients, and instructions.
  - `spec.json.success_criteria[0]` repeats “four” while measuring three.
- **Issue**: The fourth field is likely notes, but notes are not required by US-1 or the SC measure.
- **Recommendation**: Either change “four” to “three”, or explicitly require and test the fourth field (e.g. notes) everywhere.

### C-006 — Streaming size check references `shutil.copyfileobj`, but that API does not provide cumulative abort semantics by itself

- **Severity**: Medium
- **Scope**: FR-internal / implementation consistency
- **Locations**:
  - FR-06 says reject mid-stream “during `shutil.copyfileobj` (chunked, abort on cumulative > cap)”.
  - EC-07 repeats the same mid-stream `shutil.copyfileobj` abort expectation.
- **Issue**: Plain `shutil.copyfileobj` copies until EOF and does not expose cumulative byte checks unless wrapped in a custom limited reader/writer or replaced by an explicit chunk loop.
- **Recommendation**: Reword to “copy with an explicit chunk loop” or define the limited-reader helper that enforces the cumulative cap.

## Self-concerns vs FRs / ACs

- `SC-1` / `SC-self-1` is consistent with FR-08 and NC-002: the spec chooses `filetype` to avoid native `libmagic`.
- `SC-2` / `SC-self-2` is consistent with FR-11 and NC-003, but the accepted multi-worker undercount should be visible in acceptance criteria if reviewer signoff is required.
- `SC-3` / `SC-self-3` is consistent with FR-17 and EC-03: mitigation is prompt-level only, not output scanning.
- `SC-4` / `SC-self-4` is consistent with FR-12, but should be reflected in operational risk notes and timeout tests.
- `SC-5` / `SC-self-5` is consistent with FR-10 and out-of-scope front-end work; no contradiction.

## Edge cases vs FRs / ACs

- EC-01 aligns with FR-01/FR-14 and NC-001.
- EC-02 conflicts with FR-14/FR-18 as written because it assumes parse exceptions reach the orchestrator unwrapped.
- EC-03 aligns with FR-17, but relies on existing sanitizer/rendering behavior rather than a new FR.
- EC-04 generally aligns with `openai-failed`, though FR-14 is a weak source because corrupted image handling is not JSON parsing.
- EC-05 aligns with FR-11, aside from imprecise “count=11” wording when the FR says raise at `len >= 10`.
- EC-06 aligns with FR-12/FR-18.
- EC-07 has the same `shutil.copyfileobj` implementation inconsistency as C-006.
- EC-08 is semantically aligned with FR-10, but its markdown title differs from JSON and should be clarified.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| Selected approach | Lists only approach A/name and points to `approach/selected.md`. | Adds detailed rationale and scoring. | JSON has extra rationale not present in md; not contradictory. |
| FR-01 | Mentions breaking change to body/return shape “documented in commit message”. | Omits commit-message documentation. | JSON weakens a documentation requirement. |
| FR-21 | Says new branches are logged at WARN. | Omits WARN logging detail. | JSON loses log-level requirement. |
| EC-08 | Title says “First image already exists (legacy `data_service.write_image` writes were not deleted by this change)”. | Title says “Cover-image side-effect removed”. | Markdown title is ambiguous and can be read as preserving legacy writes; JSON is clearer. |
| Test commands | Uses one `task py:test -- ...` command plus `task py:check`. | Uses three `uv run pytest ...` commands plus `task py:check`. | Different authoritative test commands. Align one runner strategy. |
| Implementation file plan | Not present as a dedicated section in md. | Adds `files_to_modify`, `files_to_add`, `files_to_extend`, `files_explicitly_not_touched`, stakeholders. | JSON contains implementation commitments that md-only consumers will miss. |
| Self-concern IDs | `SC-1` through `SC-5`. | `SC-self-1` through `SC-self-5`. | Minor ID drift; cross-references should use one namespace. |

No other material md/json semantic disagreements were found; most remaining differences are condensation, formatting, or structured representation.

## needs_clarification assessment

The three existing clarification defaults are internally consistent with the chosen FRs:

1. NC-001 persist-immediately default aligns with US-1 and FR-15.
2. NC-002 `filetype==1.2.0` aligns with FR-08 and SC-11.
3. NC-003 in-process rate limiter aligns with FR-11 and self-concern 2.

Add clarifications or convert to hard FR text for:

1. Error precedence among auth, disabled feature, size/MIME validation, rate limiting, and OpenAI errors.
2. How parse failures remain distinguishable from generic OpenAI failures despite `get_response` catch-all wrapping.
3. Whether DEBUG logs and `exc_info=True` are allowed for this flow, and what exact log secrecy guarantee tests should enforce.
4. Whether SC-1 requires three or four LLM-extracted fields.
