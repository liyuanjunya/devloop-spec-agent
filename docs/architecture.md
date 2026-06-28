# DevLoop Spec Phase — Architecture

This document describes the implementation as it actually exists in `devloop/spec_phase/`.

## High-level data flow

```
User input ──► Stage 0: preflight (deterministic) ──► reject if too vague
                  │
                  ▼
              Stage 1: RepoSkeleton (tree-sitter + PageRank-free
                                     summarization, sqlite-cached
                                     by git commit hash)
                  │
                  ▼
              Stage 2: Intent
                ├─ analyzer (Claude)  ─► hypotheses[]
                ├─ skeptic (GPT)      ─► challenges[] + new_hypotheses[]
                └─ verifier (Claude)  ─► ConfirmedIntent
                  │
                  ▼
              Stage 3: Exploration (5 perspectives in parallel)
                ├─ data explorer    ─┐
                ├─ api explorer       │
                ├─ ui explorer        ├─► 5× Perspective ──► consolidator (Claude) ─► ConsolidatedExploration
                ├─ test explorer      │
                └─ history explorer ─┘
                  │
                  ▼
              Stage 4: Approach (3 candidate plans + cross-eval + select)
                ├─ generator × 3 (Claude, parallel) ─► CandidatePlan × 3
                ├─ evaluator (GPT, cross-company)   ─► ApproachEvaluation
                └─ selector (Claude)                ─► SelectedApproach
                  │
                  ▼
              Stage 5: Writer (Claude) ─► Spec with mandatory self_concerns
                  │
                  ▼
              Stage 6-8: Review-rewrite loop (quality-driven, not iteration-count)
                ├─ 4 reviewers in parallel (architecture/completeness/executability/consistency)
                │  Each has full 12-tool code access. Verdict per reviewer + self_concerns_verdicts.
                │
                ├─ if all pass ─► finalize
                ├─ if no progress for N rewrites ─► needs_review tag
                ├─ if max_total_iterations hit  ─► needs_review tag
                └─ otherwise ─► rewriter (Claude) ─► back to reviewers
                  │
                  ▼
              Stage 9: Persist
                spec.md / spec.json / intent/ / exploration/ / approach/ /
                spec_iterations/ / review.json / trace.jsonl
```

## Package layout

```
devloop/
  __init__.py
  cache.py                              # SQLite cache backend
  cli/
    main.py                             # typer CLI entrypoint
  config/
    settings.py                         # pydantic-settings + YAML
  eval/
    runner.py                           # golden-set eval harness
  llm/
    types.py                            # Message, ToolSpec, LLMResponse...
    providers/
      base.py                           # BaseProvider abstract
      anthropic_provider.py             # Claude
      openai_provider.py                # GPT
    routing.py                          # ModelRouter with cross-company enforcement
    gateway.py                          # LLMGateway (single entry for LLM calls)
    json_helpers.py                     # call_strict_json + call_react_with_tools
    trace.py                            # TraceWriter (JSONL)
    trace_analyzer.py                   # Summary stats from trace.jsonl
  spec_phase/
    preflight.py                        # Stage 0
    md_json_bridge.py                   # Spec ↔ markdown + json
    prompts_loader.py                   # 3-layer override loader
    orchestrator.py                     # Stage 0-9 driver
    repo_skeleton/
      scanner.py                        # tree-sitter symbol extraction
      compressor.py                     # token-budgeted compression
      builder.py                        # cache-aware builder
    schemas/
      common.py, intent.py, exploration.py,
      approach.py, spec.py, review.py   # All pydantic v2 contracts
    agents/
      context.py                        # SpecContext (per-run state)
      intent/stage.py                   # analyzer / skeptic / verifier
      explorer/stage.py                 # 5 explorers + consolidator
      approach/stage.py                 # generator x3 + evaluator + selector
      writer.py                         # write + rewrite
      reviewers/stage.py                # 4 reviewers + verdict aggregation
  tools/
    base.py                             # BaseTool + ToolContext + AgentScratchpad
    registry.py                         # ToolRegistry (role-based visibility, budget)
    code_search.py                      # ripgrep with Python fallback
    file_read.py                        # bounded line_range
    references.py                       # find_references / find_callees
    navigation.py                       # find_similar_files / list_directory
    project_understanding.py            # read_tests/docs/configs/migrations
    git_tools.py                        # git_log / git_blame
    output_tools.py                     # mark_as_relevant / take_note / flag_issue
    _paths.py                           # path safety (no escape)
prompts/
  intent/{analyzer,skeptic,verifier}.md
  explorer/{_base,data,api,ui,test,history,consolidator}.md
  approach/{plan_generator,plan_evaluator,plan_selector}.md
  writer.md, writer_rewrite.md
  reviewer/{_base,architecture,completeness,executability,consistency}.md
configs/
  default.yaml, models.yaml
tests/
  unit/...           # 76 tests, all passing
  integration/...    # Full pipeline test with MockProvider
  fixtures/sample_repo/    # FastAPI+SQLAlchemy demo project
eval/
  golden_set/*.json
```

## Key design choices

### 1. Cross-company review is enforced at the router

`ModelRouter.__init__` raises if `primary_provider == cross_review_provider`. This makes accidental same-family review a startup-time error, not a quality regression in production.

### 2. Agentic-first

Explorers and Reviewers have full tool access; their behavior is shaped by prompts and *output tools*, not by tool-count restrictions. The Explorer receives `mark_as_relevant` + `take_note`; the Reviewer receives `flag_issue` — but both share the same 12 code-reading tools.

### 3. Quality-driven loop termination

The review-rewrite loop terminates on three conditions, in priority order:
1. All reviewers verdict = `pass`
2. No progress for `N` consecutive rewrites (default 3) — pressure must strictly decrease
3. Hard cap `max_total_iterations` (default 20) — runaway protection

When (2) or (3) fires, the spec is tagged `needs_review=True`.

### 4. Mandatory writer self-reflection

The writer schema requires `self_concerns: list[Concern]`. Reviewers must then issue per-concern verdicts (`resolved | confirmed_problem | uncertain`). This forces both sides to engage explicitly with uncertainty.

### 5. Cache by git commit hash

Both the RepoSkeleton and every cacheable tool call key on `git rev-parse HEAD`. Re-running on the same commit is fast; switching branches transparently invalidates.

### 6. JSON strictness

All non-ReAct LLM responses go through `call_strict_json` which:
1. Sends the pydantic JSON schema to the LLM
2. Extracts JSON from the response (tolerant of markdown fences)
3. Validates with pydantic
4. Up to N repair retries with error messages fed back

### 7. Strict path safety in tools

`_paths.resolve_repo_path` raises `PathOutsideRepoError` on any escape — covered by tests.

### 8. Provider-agnostic tool format

`ToolSpec` is a single canonical schema. Anthropic's `{name, description, input_schema}` and OpenAI's `{type, function: {...}}` are produced inside each provider, never at the agent layer.

## Testing strategy

| Layer | Style | Coverage |
|---|---|---|
| Schemas | Direct pydantic validation tests | All 22 schemas |
| Tools | Each tool tested against a fixture repo | 12/12 code tools, 3/3 output tools |
| LLM helpers | JSON extraction, routing | All branches |
| RepoSkeleton | Real tree-sitter scan of fixture | scan/compress/builder |
| Cache | SQLite roundtrip, TTL, invalidation | full surface |
| Preflight | Chinese + English + edge cases | all rules |
| Prompts loader | Override chain, missing prompts, real prompt list | all real prompts must load |
| md/json bridge | Render + roundtrip | Spec full surface |
| Orchestrator | Mock LLM, full 9-stage pipeline, both providers exercised | end-to-end |

Running:

```bash
pytest tests --tb=short
```

Currently: **76 passed, 0 failed**.
