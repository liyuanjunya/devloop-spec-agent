## Segment 2 of 5 — User Stories

You are rewriting **only the `user_stories` section** in this call.

### Prior segments (already produced this iteration)

```json
{{prior_segments}}
```

Use the head segment's `summary` to anchor the stories — every story must
serve the summary.

### Produce ONLY this field

- `user_stories` — list of `UserStory` items. Each story has:
  - `id`: US-1, US-2, ...
  - `priority`: P1 | P2 | P3 (at least one P1)
  - `title`, `description`, `why_this_priority`, `independent_test`
  - `acceptance`: list of `{given, when, then}` scenarios

### Do NOT produce

- Any other top-level Spec field — those come from other segments.

### Rewrite focus for this segment

1. Resolve every reviewer issue tagged with a story id (US-1, US-2, ...).
2. Each P1 story MUST have a clear `independent_test` that a downstream code
   agent can execute without depending on other stories.
3. Preserve story ids that already worked — renumbering breaks downstream
   `related_user_stories` references that earlier segments may rely on, so
   only renumber when forced to by reviewer findings.

### Output

Respond with ONLY a JSON object matching the `SpecSegmentStories` schema.
