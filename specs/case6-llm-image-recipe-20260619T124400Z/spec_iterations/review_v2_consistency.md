# Consistency Review v2 — Case-6 LLM Image-to-Recipe

**Reviewer**: Consistency  
**Result**: NEEDS_REVISION

## Summary

Spec v2 resolves the major v1 contradictions around auth-vs-feature precedence, feature-off validation precedence, `shutil.copyfileobj`, raw DEBUG response logging, and the "four fields" wording. However, one new blocking consistency defect remains: the rate-limit check is ordered before size/MIME/magic validation while the stories, FRs, and tests require rejected validation attempts not to consume quota. There are also medium-severity reference and test-shape inconsistencies that should be cleaned up before implementation.

## Findings

### C2-001 — Rate-limit ordering contradicts "rejected attempts do not consume quota"

- **Severity**: High
- **Scope**: US ↔ FR ↔ SC contradiction
- **Locations**:
  - `spec_v2.md`: US-4 says only requests that pass auth, gate, size, and MIME are recorded; rejected attempts do not consume quota.
  - `spec_v2.md`: FR-11 says `check_and_record` appends when under quota and rejected attempts are not counted.
  - `spec_v2.md`: FR-25 orders checks as feature gate → **rate limit** → size pre-check → MIME header → magic sniff.
  - `spec_v2.md`: SC-5 requires a 413 mid-loop not to decrement remaining quota.
  - `spec_v2.json`: same semantic ordering appears in `functional_requirements[24]`, while `user_stories[3]`, `functional_requirements[10]`, and `success_criteria[4]` preserve the non-counting requirement.
- **Issue**: If `check_and_record` runs before size/MIME/magic validation and appends immediately, later 413/415 failures consume quota. This directly contradicts US-4, FR-11, and SC-5. The mid-stream 413 and magic-sniff 415 happen in the service after the controller rate-limit call, so this is not just a wording issue.
- **Recommendation**: Choose one consistent model:
  1. Move rate-limit recording after all validation checks that should not consume quota, while still checking quota before the OpenAI call; or
  2. Split the limiter into `check()` before OpenAI and `record_success()` after successful creation; or
  3. Keep FR-25 order and explicitly state that validation failures after the rate-limit step do consume quota, then update US-4/FR-11/SC-5.

### C2-002 — User-story acceptance gates reference missing AC IDs

- **Severity**: Medium
- **Scope**: US ↔ SC traceability
- **Locations**:
  - `spec_v2.md`: user story table column is "Acceptance gate (cross-ref to AC)" and references `AC-01`, `AC-02`, etc.
  - `spec_v2.md`: measurable criteria are named `SC-1` through `SC-14`, not `AC-*`.
  - `spec_v2.json`: `user_stories[*].acceptance` uses `AC-*`, while `success_criteria[*].id` uses `SC-*`.
- **Issue**: Implementers and test agents cannot mechanically trace user stories to success criteria because the referenced AC IDs do not exist.
- **Recommendation**: Rename the acceptance references to the actual `SC-*` IDs, or add an explicit AC↔SC mapping table.

### C2-003 — Log content contract is stricter/different than the FR-level log lines

- **Severity**: Medium
- **Scope**: US ↔ FR ↔ SC inconsistency
- **Locations**:
  - US-5 says corresponding logs at any level contain only the i18n key, user id, and response length.
  - FR-19 success log includes `tokens`; failure log includes `user` and `reason`, but not response length.
  - FR-23 DEBUG parse log includes `cls.__name__` and response length, but not user id or i18n key.
  - SC-8 only tests absence of image bytes/base64/LLM substrings, not the "only key/user/length" allowlist.
- **Issue**: The secrecy goal is now much safer than v1, but the exact positive log contract is inconsistent. A literal implementation of US-5 would reject FR-19's token log and FR-23's class-name log, while SC-8 would pass them.
- **Recommendation**: Reword US-5 to the actual intended allowlist per log site, or tighten FR-19/FR-23/SC-8 so they all enforce the same fields.

### C2-004 — Parse-failure tests describe direct exceptions but implementation classifies wrapped causes

- **Severity**: Medium
- **Scope**: SC ↔ FR testability inconsistency
- **Locations**:
  - FR-14 says parse-vs-openai classification is based on `e.__cause__` from `get_response`'s catch-all wrapper.
  - SC-7 says "mock raises pydantic `ValidationError`" and expects `parse-failed`.
  - Files-to-add unit-test description is clearer: "`ValidationError` via `__cause__` → 422 `parse-failed`."
- **Issue**: If a test monkeypatches `get_response` to directly raise `ValidationError`, `e.__cause__` is `None`, so the FR-14 algorithm classifies it as `openai-failed`. Only a wrapped `Exception(...) from ValidationError` matches the intended path.
- **Recommendation**: Update SC-7 to require malformed JSON through the real parser or a wrapped exception with `__cause__` set to `ValidationError` / `JSONDecodeError`.

## Self-concerns vs FRs / ACs

- `SCN-1` aligns with FR-08 and NC-002: pure-python `filetype` avoids native `libmagic`.
- `SCN-2` aligns with FR-11/FR-25 on multi-worker hard-disable, but the rate-limit placement conflict in C2-001 must be fixed.
- `SCN-3` aligns with FR-17: prompt-injection mitigation is deliberately narrow and output content scanning is out of scope.
- `SCN-4` aligns with FR-12/EC-06: the 60-second timeout risk is documented.
- `SCN-5` aligns with FR-10/EC-08: cover image persistence is intentionally removed.
- `SCN-6` and `SCN-7` resolve the v1 logging conflict, subject to the positive log-field mismatch in C2-003.

## Edge cases vs FRs / ACs

- EC-01 through EC-04 generally align with FR-14/FR-18 once SC-7's direct-vs-wrapped exception wording is fixed.
- EC-05 aligns with FR-11 for single-worker concurrency, but depends on resolving C2-001 so validation failures do not consume quota unexpectedly.
- EC-06 aligns with FR-12/FR-18.
- EC-07 aligns with FR-06 and fixes the v1 `shutil.copyfileobj` issue.
- EC-08 aligns with FR-10 and the files-to-extend plan.
- EC-09 aligns with FR-08.
- EC-10 aligns with FR-11/FR-04.

## spec.md vs spec.json diff

| Field | spec.md | spec.json | Disagreement |
|---|---|---|---|
| Selected approach | Lists only approach A/name and points to `approach/selected.md`. | Adds rationale text. | JSON has extra rationale; not contradictory. |
| US acceptance references | Uses `AC-01`, `AC-02`, etc. | Also uses `AC-*`. | Both diverge from the actual `SC-*` IDs; see C2-002. |
| US-4 detail | Explicitly names earlier checks: auth, gate, size, MIME. | Says "earlier checks" without listing them. | JSON is less explicit, but both conflict with FR-25's rate-before-size/MIME order. |
| FR-05 | Notes group admins remain free to set `image_provider.model` for other image paths. | Omits that detail. | JSON slightly weakens admin-model-scope explanation; not material. |
| SC-8 measure | Runs happy path and all SC-7 failure paths under DEBUG capture. | Omits "happy path AND all failure paths" wording. | JSON weakens test coverage for log capture. |
| SC-13 criterion | Criterion title says per-group=false; measure also covers `WORKERS > 1`. | Criterion says per-group=false OR `WORKERS > 1`. | Markdown title is narrower than its own measure and JSON; minor clarity issue. |
| Files-to-modify docs row | Says briefly document FR-11 multi-worker hard-disable. | Says document multi-worker hard-disable plus 10/user/hour. | Markdown file plan weakens FR-24's docs requirement. |
| Constraints | No dedicated constraints section. | Has `constraints` list with uv, Crowdin, Translator, three-layer, etc. | JSON-only implementation constraints may be missed by md-only agents. |

No other material md/json semantic disagreements were found; most remaining differences are condensation or structured representation.

## needs_clarification assessment

Existing NC defaults are internally coherent:

1. NC-001 persist-immediately aligns with FR-15 and EC-01.
2. NC-002 `filetype==1.2.0` aligns with FR-08 and SC-11.
3. NC-003 in-process limiter plus multi-worker hard-disable aligns with FR-11, subject to C2-001.
4. NC-004 existing `.txt` prompt slot aligns with FR-13.
5. NC-005 `OpenAIRecipe` reuse aligns with FR-14/FR-15.

Add or revise clarification text for:

1. Whether rate limiting records before validation, after validation, or only after successful creation.
2. Whether the log contract is a strict field allowlist or only a no-secret/no-body leakage guarantee.
3. Whether user-story acceptance references should use `SC-*` IDs or a separate AC namespace.
