# Configuration

DevLoop reads configuration from three layers, in increasing priority:

1. **`configs/default.yaml`** — committed defaults
2. **`configs/local.yaml`** — developer-specific overrides (gitignored)
3. **Environment variables** — `DEVLOOP__SECTION__KEY=value`
4. **Constructor kwargs** — for tests

## Full reference

```yaml
llm:
  primary_model: claude-opus-4-7
  cross_review_model: gpt-5.5
  primary_provider: anthropic       # anthropic | openai
  cross_review_provider: openai     # MUST differ from primary_provider
  max_retries: 3                    # Per LLM call (exponential backoff)
  timeout_seconds: 120
  max_tokens_default: 8192

explorer:
  max_tool_calls_soft: 50           # Warning threshold
  max_tool_calls_hard: 100          # Hard cutoff per explorer
  parallel: true                    # asyncio.gather across 5 perspectives
  perspectives:
    - data
    - api
    - ui
    - test
    - history

reviewer:
  max_tool_calls_soft: 30
  max_tool_calls_hard: 80
  parallel: true                    # 4 reviewers in parallel
  angles:
    - architecture
    - completeness
    - executability
    - consistency

orchestrator:
  max_total_iterations: 20          # Review-rewrite loop hard cap
  no_progress_threshold: 3          # Stuck-detection window
  enable_multi_view_explorer: true  # false = MVP single explorer
  enable_multi_candidate_approach: true
  enable_multi_reviewer: true

cache:
  backend: sqlite
  ttl_days: 7                       # Cache entries expire after this many days

paths:
  workspace_root: ./specs
  prompts_dir: ./prompts
  cache_dir: ./.cache/devloop

repo_skeleton:
  target_tokens: 1024               # Compressed skeleton budget
  max_files_per_module: 5
  excluded_dirs:
    - node_modules
    - .git
    - .venv
    - __pycache__
    - dist
    - build
  supported_languages:
    - python
    - javascript
    - typescript
    - go
    - rust
    - java

tools:
  file_read_max_lines: 200          # Per single call
  file_read_max_bytes: 262144       # 256 KiB hard cap
  subprocess_max_bytes: 5242880     # 5 MiB cap on rg/git output
  project_understanding_max_snippet_chars: 8000
  git_command_timeout_s: 15
  rg_command_timeout_s: 30
```

## Environment variable overrides

Every nested config key maps to `DEVLOOP__<SECTION>__<KEY>`:

```bash
export DEVLOOP__LLM__PRIMARY_MODEL="claude-3-5-sonnet-20241022"
export DEVLOOP__EXPLORER__MAX_TOOL_CALLS_HARD=200
export DEVLOOP__ORCHESTRATOR__MAX_TOTAL_ITERATIONS=10
```

API keys are always read from these specific env vars (never from YAML, to
prevent committing secrets):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

## Model routing

The `configs/models.yaml` file specifies which side (`primary` or
`cross_review`) each role uses:

```yaml
stage_defaults:
  intent_analyzer: primary       # writer-side
  intent_skeptic: cross_review   # MUST be cross-company
  intent_verifier: primary
  explorer: primary
  consolidator: primary
  plan_generator: primary
  plan_evaluator: cross_review   # MUST be cross-company
  plan_selector: primary
  writer: primary
  reviewer: cross_review         # MUST be cross-company
```

The router enforces a startup-time check: `primary_provider` and
`cross_review_provider` **must be different** companies. Otherwise the
"cross-family review" property of v7 is violated.

## Recipe: cheap iteration

For prompt-tuning loops where you want fast/cheap runs:

```yaml
orchestrator:
  enable_multi_view_explorer: false
  enable_multi_candidate_approach: false
  enable_multi_reviewer: false
  max_total_iterations: 5

explorer:
  max_tool_calls_hard: 20

reviewer:
  max_tool_calls_hard: 15
```

## Recipe: maximum quality

For production runs where quality > everything:

```yaml
orchestrator:
  enable_multi_view_explorer: true
  enable_multi_candidate_approach: true
  enable_multi_reviewer: true
  max_total_iterations: 30        # More room for convergence

explorer:
  max_tool_calls_hard: 150        # Let it explore deeply

reviewer:
  max_tool_calls_hard: 120
```

## Tuning the prompt-cache threshold

In `devloop/llm/providers/anthropic_provider.py`, `_PROMPT_CACHE_THRESHOLD = 2000`
controls when a system prompt gets `cache_control: ephemeral`. Lower it for
shorter prompts (less savings, more requests cached); raise it for stricter
caching.
