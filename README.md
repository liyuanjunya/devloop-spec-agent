# DevLoop — Spec Phase

An effect-first, production-grade implementation of the **spec phase** for a full-pipeline development agent.

## What this is

Given a natural-language feature description and a target code repository, DevLoop's spec phase produces a high-quality, code-grounded specification (`spec.md` + `spec.json`) that a downstream plan/code agent can directly act on.

It is designed around 9 stages with multi-agent collaboration:

1. **Input pre-flight** — reject vague input early
2. **Repo skeleton** — tree-sitter scan + cache (commit-hash keyed)
3. **Deep intent understanding** — multi-hypothesis + skeptic challenge + skeleton-verified convergence
4. **5-perspective parallel exploration** — Data / API / UI / Test / History explorers + a consolidator
5. **3-candidate plan brainstorm** — conservative / balanced / aggressive + evaluator + selector
6. **Spec writing + self-reflection** — explicit `self_concerns` field
7. **4-angle independent review** — architecture / completeness / executability / consistency
8. **Iterative rewrite-review loop** — quality-threshold driven, not iteration-count driven
9. **Persist** — full trace to `specs/{run_id}/`

## Models

- **Writer / Explorer / Approach**: Claude Opus 4.7
- **Skeptic / Plan Evaluator / Reviewer**: GPT-5.5 (cross-company)

Cross-company review is mandatory to avoid the ~15% same-family self-evaluation bias documented in 2025–2026 LLM-as-judge research.

## Install

```bash
pip install -e ".[test,dev]"
```

## Run (CLI)

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...

devloop spec "给商品页加用户评论功能" --repo /path/to/your/project
```

Outputs to `specs/{run_id}/spec.md` and `specs/{run_id}/spec.json`.

## Layout

```
devloop/
  spec_phase/      # 9 stages: agents, schemas, prompts, orchestrator
  llm/             # Multi-provider gateway (Anthropic + OpenAI)
  tools/           # 13 code tools + 3 output tools
  config/          # pydantic-settings
  cli/             # typer entry
prompts/           # All prompts as .md files (git-versioned)
configs/           # YAML defaults
tests/             # unit / integration / e2e
eval/              # Eval harness + golden set
```

## License

MIT
