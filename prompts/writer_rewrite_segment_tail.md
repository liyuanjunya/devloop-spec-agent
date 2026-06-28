## Segment 5 of 5 — Tail (entities, edge cases, assumptions, out_of_scope, self_concerns)

You are rewriting **only the tail of the spec** in this call. This is the
last segment — every prior segment's content is now fixed.

### Prior segments (already produced this iteration)

```json
{{prior_segments}}
```

### Produce ONLY these fields

- `key_entities` — list of `Entity` items with `name`, `description`,
  `fields`, `references` to existing entities.
- `edge_cases` — list of `{description, handling}` items.
- `assumptions` — list of plain strings (one assumption per item).
- `out_of_scope` — list of plain strings (one non-goal per item).
- `self_concerns` — MANDATORY: list of `Concern` items capturing residual
  uncertainty. Each `Concern` has `location`, `concern`, `evidence_gap`,
  and optional `suggested_resolution`. Surface NEW concerns introduced by
  this rewrite — do not drop concerns that reviewers verified as
  `confirmed_problem`.

### Do NOT produce

- `metadata`, `summary`, `needs_clarification`, `user_stories`,
  `functional_requirements`, `success_criteria` — those were already
  produced by prior segments.

### Rewrite focus for this segment

1. Resolve every reviewer issue tagged with a `Key Entity`, edge case,
   assumption, or `self_concern` location.
2. If a reviewer flagged an FR or SC as `confirmed_problem` in their
   concern-verdicts and you couldn't fully fix it in the prior segment,
   record a follow-up `Concern` here.
3. Use `self_concerns` for residual implementation uncertainty only —
   blocking design conflicts must live in the head segment's
   `needs_clarification`, never here.

### Output

Respond with ONLY a JSON object matching the `SpecSegmentTail` schema.
