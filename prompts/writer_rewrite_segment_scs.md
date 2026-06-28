## Segment 4 of 5 — Success Criteria

You are rewriting **only the `success_criteria` section** in this call.

### Prior segments (already produced this iteration)

```json
{{prior_segments}}
```

Specifically, the `functional_requirements` segment above lists the FR ids
available — every `SuccessCriterion.related_requirements` entry MUST point
to one of those ids. Dangling FR references are rejected by the trace-matrix
validator.

### Produce ONLY this field

- `success_criteria` — list of `SuccessCriterion` items. Each SC has:
  - `id`: SC-001, SC-002, ...
  - `text`: user-facing description
  - `metric`: what is being measured (no soft language)
  - `threshold`: expected value/range (no soft language)
  - `technology_agnostic`: bool
  - `related_requirements`: list of FR ids from the prior segment

### Do NOT produce

- Any other top-level Spec field.

### Rewrite focus for this segment

1. Resolve every reviewer issue tagged with an SC id (SC-001, ...).
2. Every functional FR in the prior segment must be measurably verified by
   at least one SC. Walk the FR list and make sure each one has at least one
   SC pointing back at it.
3. Replace any soft thresholds ("fast", "responsive") with concrete
   numeric thresholds.

### Output

Respond with ONLY a JSON object matching the `SpecSegmentSCs` schema.
