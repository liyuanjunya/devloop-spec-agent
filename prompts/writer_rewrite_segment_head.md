## Segment 1 of 5 — Head (metadata + summary + needs_clarification)

You are rewriting **only the head of the spec** in this call. The full
rewrite is split into 5 segments so each can be validated independently;
later segments will see what you produce here as context.

### Produce ONLY these fields

- `metadata` — preserve `feature_id` and `title` from the previous spec; the
  orchestrator will overwrite `writer_model`, `reviewer_model`, and
  `iterations` after validation, so use the previous values as placeholders
  (do not invent new ones).
- `summary` — one paragraph describing what is being built and why.
- `needs_clarification` — list of `BlockingDecision` items for genuine
  blocking conflicts between user input and existing code. Promote anything
  the reviewers flagged as a blocking conflict (do not bury it in
  `self_concerns`).

### Do NOT produce

- `user_stories`, `functional_requirements`, `success_criteria`,
  `key_entities`, `edge_cases`, `assumptions`, `out_of_scope`,
  `self_concerns` — those come from later segments.

### Rewrite focus for this segment

1. If reviewers flagged the `summary` as vague or wrong, fix it now.
2. If reviewers identified a blocking conflict (user wants X but code has Y),
   promote it to a `BlockingDecision` in `needs_clarification`.
3. Replace any soft language ("or equivalent", "TBD", "if needed", ...) with
   a single committed choice — or, for genuine blockers, a `BlockingDecision`.

### Output

Respond with ONLY a JSON object matching the `SpecSegmentHead` schema.
