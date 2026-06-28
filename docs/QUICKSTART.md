# Quickstart

5-minute guide to your first spec.

## 1. Install

```bash
git clone <repo>
cd devloop
python -m venv .venv && source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[test,dev]"
```

Required tools on PATH:
- `git` (any recent version)
- `rg` (ripgrep) — optional but recommended; falls back to pure-Python search

## 2. Configure API keys

DevLoop requires both Anthropic and OpenAI keys because the design enforces
cross-company review (writer = Claude, reviewer = GPT).

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

Or create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

## 3. Configure models (optional)

Edit `configs/default.yaml`:

```yaml
llm:
  primary_model: claude-opus-4-7
  cross_review_model: gpt-5.5
  primary_provider: anthropic
  cross_review_provider: openai
```

Replace with the actual model IDs your provider exposes (e.g.
`claude-3-5-sonnet-20241022`, `gpt-4o-2024-08-06`, etc.).

## 4. Run your first spec

```bash
devloop spec "给商品页加用户评论功能" --repo C:\path\to\your\project
```

Or in English:

```bash
devloop spec "Add user authentication to the API" --repo /path/to/repo
```

The CLI prints a panel with:
- Selected models and modes
- Workspace path (e.g. `./specs/20260617T191234Z-add-user-auth-a1b2c3/`)
- Output files: `spec.md` (human-readable) + `spec.json` (machine-readable)
- Token totals and estimated cost
- Iteration count
- "Needs review" flag if the multi-reviewer loop couldn't converge

## 5. Inspect outputs

```
specs/<run_id>/
├── spec.md                  # The final spec, human-readable
├── spec.json                # Same, machine-consumable
├── review.json              # Verdicts from all reviewers
├── trace.jsonl              # Per-call telemetry
├── intent/
│   ├── initial_hypotheses.json
│   ├── skeptic_round_1.json
│   ├── verifier_round_1.json
│   └── confirmed.json
├── exploration/
│   ├── data_perspective.json
│   ├── api_perspective.json
│   ├── ui_perspective.json
│   ├── test_perspective.json
│   ├── history_perspective.json
│   └── consolidated.json
├── approach/
│   ├── candidate_conservative.json
│   ├── candidate_balanced.json
│   ├── candidate_aggressive.json
│   ├── evaluation.json
│   └── selected.json
└── spec_iterations/
    ├── spec_v1.md / spec_v1.json
    ├── review_v1_architecture.json
    ├── review_v1_completeness.json
    ├── review_v1_executability.json
    ├── review_v1_consistency.json
    └── ... (one per rewrite)
```

## 6. Analyze a past run

```bash
devloop analyze-trace ./specs/<run_id>/
```

Prints a Markdown summary: per-stage counts, tool usage, model usage, cache hit
rate, total latency.

## 7. MVP modes (faster / cheaper iteration)

Skip multi-view explorers / multi-candidate plans / multi-reviewer when you're
just testing prompts:

```bash
devloop spec "..." \
  --repo ./my-project \
  --single-explorer \
  --single-candidate \
  --single-reviewer
```

This uses 1 explorer + 1 candidate plan + 1 reviewer instead of 5/3/4 —
typically ~3× faster and ~5× cheaper, at the cost of lower spec quality.

## Common issues

| Problem | Cause | Fix |
|---|---|---|
| `Preflight failed: Input is too short` | Description < 8 chars | Describe the feature in a sentence |
| `Cross-company review violated` | Both primary and cross_review point to same provider | Edit `configs/default.yaml` so they differ |
| `ANTHROPIC_API_KEY required` | Missing env var | `export ANTHROPIC_API_KEY=...` |
| `tree-sitter` parser panics | Mixing parsers across threads | Already fixed in v0.1.0 (thread-local cache) |
| Spec references nonexistent paths | Writer hallucinated; lenient prompt | Reviewer should catch — check `review.json` |

## Next steps

- [Configuration reference](./CONFIGURATION.md)
- [Architecture deep dive](./architecture.md)
