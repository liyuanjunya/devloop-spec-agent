## Segment 3 of 5 — Functional Requirements

You are rewriting **only the `functional_requirements` section** in this
call.

### Prior segments (already produced this iteration)

```json
{{prior_segments}}
```

The `user_stories` segment above lists the exact `id`s available — every
`FunctionalRequirement.related_user_stories` entry must point to one of
those ids. Dangling references will be rejected.

### Produce ONLY this field

- `functional_requirements` — list of `FunctionalRequirement` items. Each FR
  has:
  - `id`: FR-001, FR-002, ...
  - `text`: the requirement, in concrete terms (no soft language)
  - `requirement_type`: `functional` | `non_functional`
  - `related_user_stories`: list of US ids from the prior segment
  - `related_success_criteria`: list of SC ids (will be validated against
    segment 4; populate with the ids you intend to assign there)
  - `code_references`: required for functional FRs, optional for
    non-functional. Each ref must point to a real artifact in the
    consolidated exploration.
  - `testable`: bool

### Do NOT produce

- Any other top-level Spec field.

### Rewrite focus for this segment

1. Resolve every reviewer issue tagged with an FR id (FR-001, ...).
2. Re-verify `code_references` line ranges actually contain the cited
   symbol; prefer entire-function ranges over truncated ones.
3. Replace soft language with one committed choice; if you can't choose,
   the head segment owns blocking decisions — surface a `self_concern` in
   the tail segment instead.

### Output

Respond with ONLY a JSON object matching the `SpecSegmentFRs` schema.
