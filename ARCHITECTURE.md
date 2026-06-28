# DevLoop Spec Phase — Architecture

> 配套文档：`SHOWCASE_README.md`（产品视角、效果数字）、`docs/architecture.md`（早期速写）。
> 本文档聚焦**结构与约束**——为什么是这 9 个 stage、为什么是这 19 道防御、各组件之间的不变式（invariants）是什么。
> 所有 Mermaid 图均按可渲染语法书写。

---

## Section 1 · 系统全景图（图 1）

```mermaid
flowchart TD
    U[User Input + repo_path]:::ext --> S0

    subgraph DET[Deterministic Pre-LLM]
        S0[Stage 0<br/>Preflight<br/>规则拒绝过空输入]
        S1[Stage 1<br/>Repo Skeleton Scan<br/>tree-sitter + commit-hash cache]
    end
    S0 -->|ok| S1
    S0 -.->|reject| EXIT_PRE[fail_preflight]:::halt

    subgraph S2g[Stage 2 · Deep Intent · Claude]
        S2A[analyzer<br/>hypotheses]
        S2K[skeptic<br/>challenges · GPT cross]
        S2V[verifier<br/>ConfirmedIntent]
        S2A --> S2K --> S2V
    end
    S1 --> S2A

    S2V --> C3[C3 perspective_selector<br/>intent-driven, Python]
    C3 --> S3

    subgraph S3g[Stage 3 · 5-Perspective Exploration · parallel · Claude]
        E1[data]:::expl
        E2[api]:::expl
        E3[ui]:::expl
        E4[test]:::expl
        E5[history / sec / perf]:::expl
    end
    S3[fanout] --> E1 & E2 & E3 & E4 & E5
    E1 & E2 & E3 & E4 & E5 --> B2[B2 coverage_gap_detector<br/>Python deterministic]
    B2 -->|gaps found| RE[targeted re-explore<br/>≤ N parallel · conditional]:::cond
    B2 -->|no gap| CONS
    RE --> CONS[consolidator<br/>Claude]

    CONS --> S4
    subgraph S4g[Stage 4 · 3-Candidate Approach · Claude / GPT]
        P1[plan_gen #1]
        P2[plan_gen #2]
        P3[plan_gen #3]
        EV[plan_evaluator<br/>GPT cross]
        SEL[plan_selector<br/>Claude]
        P1 & P2 & P3 --> EV --> SEL
    end
    S4[fanout] --> P1 & P2 & P3

    SEL --> S5[Stage 5 · Writer<br/>opus-4.7<br/>spec + self_concerns]
    S5 --> S55

    subgraph S55g[Stage 5.5 · Deterministic Validators · Python in-process]
        V_A4[A4 soft-language]
        V_A5[A5 citation_verifier]
        V_B1[B1 md/json roundtrip]
        V_B3[B3 trace_matrix]
        V_F3[F3 escalation backup]
        V_C2[C2 test-executability]
    end
    S55[fanout] --> V_A4 & V_A5 & V_B1 & V_B3 & V_F3 & V_C2
    V_A4 & V_A5 & V_B1 & V_B3 & V_F3 & V_C2 --> S6

    subgraph S6g[Stage 6 · 4-Axis Reviewers · gpt-5.5 · parallel]
        R1[architecture]:::rv
        R2[completeness]:::rv
        R3[executability]:::rv
        R4[consistency]:::rv
        RC1[C1 adversarial<br/>conditional 5th axis]:::cond
    end
    S6[fanout] --> R1 & R2 & R3 & R4 & RC1
    R1 & R2 & R3 & R4 & RC1 --> S65[Stage 6.5<br/>B4 meta-reviewer<br/>Claude]

    S65 --> DEC{all_pass?}
    DEC -->|yes| S9
    DEC -->|no| S7[Stage 7 · Rewriter<br/>opus-4.7<br/>D3 segmented opt-in]
    S7 --> S75[Stage 7.5<br/>A1 regression guard]
    S75 -->|improved/stagnant<br/>& within budget| S8{Stage 8<br/>loop guard}
    S75 -->|regression + budget left| REVERT[revert to last good<br/>regression-aware rewrite]:::cond
    REVERT --> S6
    S8 -->|continue| S55
    S8 -->|max_iter OR no-progress×3 OR regression budget exhausted| S9NR[needs_review=True]:::halt
    S9NR --> S9

    S9[Stage 9 · Persist<br/>spec.md / spec.json / trace.jsonl /<br/>spec_iterations/ / meta_review_v*.json]:::done

    classDef ext fill:#eef,stroke:#557
    classDef halt fill:#fee,stroke:#a33
    classDef done fill:#efe,stroke:#393
    classDef expl fill:#fef,stroke:#739
    classDef rv fill:#ffd,stroke:#a90
    classDef cond fill:#fde,stroke:#a36,stroke-dasharray:4 3
```

**模型分配**（参考 `configs/models.yaml`）：

| Role | Provider · Model | 备注 |
|---|---|---|
| writer / rewriter / self-reflect | anthropic · **claude-opus-4-7** | "primary" 侧 |
| explorer × 5 / consolidator / plan-gen / plan-selector / verifier / analyzer / meta-reviewer | anthropic · claude-opus-4-7 | "primary" 侧 |
| 4 axis reviewers / adversarial / skeptic / plan_evaluator | openai · **gpt-5.5** | "cross_review" 侧 |
| preflight / skeleton / validators / perspective_selector / A1 guard | — | 纯 Python，无 LLM |

---

## Section 2 · 评审约束架构（图 2）

> **核心不变式**：`writer.family ≠ reviewer.family`。在 `ModelRouter.__init__` 处启动期断言（`devloop/llm/routing.py:32`），不通过 review 流程发现，做不到"绕过"。
> 设计动机：抵抗 LLM-as-judge self-preference / cohort bias（2024–2025 论文反复证实——同家族评审会系统性高估同家族输出）。

```mermaid
flowchart LR
    subgraph PRI[Primary family · Claude · 创作侧]
        WR[Writer / Rewriter<br/>opus-4.7]
        SR[Self-reflector<br/>self_concerns]
        WR --> SR
    end

    SR --> SPEC[(spec.json + spec.md<br/>含 self_concerns)]
    SPEC --> VALS[Stage 5.5<br/>deterministic validators<br/>Python, family-neutral]

    subgraph CR[Cross-review family · GPT · 评审侧]
        RV1[architecture]
        RV2[completeness]
        RV3[executability]
        RV4[consistency]
        ADV[C1 adversarial<br/>red-team, conditional]
    end
    VALS --> RV1 & RV2 & RV3 & RV4 & ADV

    RV1 & RV2 & RV3 & RV4 & ADV --> CONS[(ConsolidatedReview<br/>+ per-concern verdicts)]
    CONS --> META[B4 Meta-reviewer<br/>Claude · 跨家族再聚合]
    META --> MRR[(MetaReviewResult<br/>prioritized actions +<br/>cross_axis_conflicts)]
    MRR -->|feedback| WR

    classDef inv fill:#fef0c1,stroke:#a80,stroke-width:2px
    SPEC:::inv
    CONS:::inv
    MRR:::inv
```

注意 meta-reviewer 故意选择 **Claude（与 writer 同家族）**：评审-of-评审场景下，conflict-detection 的关注点不是"评得对不对"，而是"4 路 GPT 是否互相矛盾"——同家族 meta 反而能更准识别这些 GPT 侧的盲区。这个非对称是**有意为之**，不是 router 的疏漏。

---

## Section 3 · 19 防御机制定位图（图 3）

按生效阶段聚类。所有 A/B/C/D/F 编号对应 `docs/` 与 commit 日志中的 Sprint 编号。

```mermaid
flowchart TB
    subgraph L_SCHEMA[Schema / 运行时层 · 无关 stage]
        F1[F1 Unicode normalization<br/>62K-row homoglyph table<br/>spec_phase/_homoglyph_table.py]
        F2[F2 boundary checks<br/>pydantic v2 constraints]
        F3S[F3 schema escalation<br/>Concern.evidence_gap validator]
        F4[F4 LLM retry · jitter · backoff<br/>llm/retry.py · halt-loud-no-skip]
        A4[A4 soft-language validator<br/>schemas/spec.py reject 'should/maybe/TBD']
        D1[D1 cost / token trace<br/>llm/trace.py · TraceWriter 全 stage]
    end

    subgraph L_S3[Stage 3 / 3.5 · Exploration]
        C3[C3 perspective auto-select<br/>intent.scope → perspectives]
        D2[D2 explorer cache<br/>per-perspective + commit-hash]
        B2[B2 coverage_gap_detector<br/>singleton / sparse / conflict]
    end

    subgraph L_S55[Stage 5.5 · Post-write validators · in-process Python]
        B1[B1 md/json roundtrip<br/>assert_spec_roundtrip_consistent]
        A5[A5 citation_verifier<br/>line_range + symbol on-disk match]
        B3[B3 trace_matrix<br/>FR ↔ SC ↔ US gap detection]
        C2[C2 test-executability<br/>pytest --collect-only on stubs]
        F3R[F3-A3 escalation backup<br/>≥3 options → BlockingDecision]
    end

    subgraph L_S6[Stage 6 · Reviewers]
        A3[A3 intent-conditional reviewer<br/>scope drives angle selection]
        C1[C1 adversarial 5th axis<br/>conditional on security/auth/llm/upload]
    end

    subgraph L_S65[Stage 6.5]
        B4[B4 meta-reviewer<br/>dedupe + cross-axis conflict]
    end

    subgraph L_S7[Stage 7 / 7.5]
        D3[D3 segmented rewriter<br/>5 per-section calls · opt-in]
        A1[A1 regression guard<br/>critical+high monotone · revert + retry]
    end

    subgraph L_S68[Stage 6-8 enclosing]
        A2[A2 multi-iteration loop<br/>quality-driven, not iter-count]
    end

    L_SCHEMA --- L_S3 --- L_S55 --- L_S6 --- L_S65 --- L_S7 --- L_S68

    classDef sch fill:#e8e8ff,stroke:#449
    classDef s3 fill:#fef0ff,stroke:#739
    classDef s55 fill:#fff5e0,stroke:#a73
    classDef s6 fill:#ffffd0,stroke:#a90
    classDef s65 fill:#e0f8e0,stroke:#393
    classDef s7 fill:#ffe0d0,stroke:#a55
    classDef s68 fill:#dde,stroke:#557
    class F1,F2,F3S,F4,A4,D1 sch
    class C3,D2,B2 s3
    class B1,A5,B3,C2,F3R s55
    class A3,C1 s6
    class B4 s65
    class D3,A1 s7
    class A2 s68
```

**为什么分这些层**：schema/运行时层的防御是**结构性**的（任何写法都绕不开），而 stage 内的防御是**针对性**的（只在该 stage 的失败模式上加力）。19 道防御从不重复——每道都对应一个曾在 case1–case6 真实失败案例中被复现的 bug 类。

---

## Section 4 · A1 + A2 回归循环（图 4）

> **关键观察**：纯"迭代到收敛"的反馈循环在 LLM 重写中**不收敛**——重写常常修一个、坏俩个（case-6 v2 复现过）。
> 因此 loop 用 *issue-pressure delta* 而非 *iteration count* 做主信号，并对回归（critical+high 严格增加）启用 revert + 回归感知重写的预算。

```mermaid
stateDiagram-v2
    [*] --> Review_vN: writer 输出 v0 / rewriter 输出 vN

    Review_vN --> Counts: IssueCounts.from_review<br/>(critical, high, medium, low)
    Counts --> Compare: vs IssueCounts(v_{N-1})

    Compare --> AllPass: review.all_pass == True
    Compare --> Improved: Δ(crit+high) < 0
    Compare --> Stagnant: Δ(crit+high) == 0
    Compare --> Regressed: Δ(crit+high) > 0

    AllPass --> [*]: converged ✓<br/>finalize, no needs_review

    Improved --> Snapshot: 保存 spec_snapshots[N]<br/>last_good_iteration = N
    Snapshot --> Rewrite: rewriter_fn(spec, review, meta_review)
    Rewrite --> Review_vN: next iteration

    Stagnant --> StagnantWindow: append to issue_history
    StagnantWindow --> NoProgress: 连续 no_progress_threshold (=3)<br/>非递减且 > 0
    StagnantWindow --> Rewrite: 否则继续重写
    NoProgress --> NeedsReview: spec.metadata.needs_review = True
    NeedsReview --> [*]: halt loud, persist as-is

    Regressed --> CheckBudget: regression_retries_used <<br/>max_regression_retries (=2)?
    CheckBudget --> RevertAndForce: yes → revert to spec_snapshots[last_good]<br/>+ regression_feedback_message()
    CheckBudget --> RevertFinal: no → 预算耗尽<br/>revert + needs_review
    RevertAndForce --> Rewrite: 重新写, retries_used++<br/>**不消耗** no_progress_threshold
    RevertFinal --> [*]: halt loud

    Rewrite --> MaxIter: iteration == max_total_iterations (=20)?
    MaxIter --> NeedsReview: yes → 强制 needs_review
```

设计要点：
1. **回归不烧 no-progress 预算**——回归是另一个失败模式，独立计数（`max_regression_retries`，默认 2）。
2. **last_good 只在 improved 时更新**，确保 revert 永远回到"严格更好"的状态。
3. **needs_review 不是 fail**——spec 仍然落盘，trace 完整，只是告诉下游人工 review，区别于 preflight 的 hard fail。

---

## Section 5 · 一次完整的请求流程（图 5）

以 case2（shopping-archive，非安全/非 LLM 类）为例。adversarial 不触发；C2 触发；A1 一次 revert。

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant O as SpecOrchestrator
    participant P as preflight / skeleton<br/>(Python)
    participant I as intent_agent<br/>(Claude × 3)
    participant PS as perspective_selector<br/>(Python)
    participant EX as 4 explorers<br/>(Claude · parallel)
    participant CO as consolidator<br/>(Claude)
    participant AP as approach<br/>(3 plans + GPT eval + Claude select)
    participant W as writer<br/>(opus-4.7)
    participant V as validators<br/>(B1/A5/B3/C2/F3 · Python)
    participant R as 4 reviewers<br/>(gpt-5.5 · parallel)
    participant M as meta-reviewer<br/>(Claude)
    participant RW as rewriter<br/>(opus-4.7)
    participant A1 as A1 regression guard<br/>(Python)

    U->>O: run(user_input, repo_path)
    O->>P: preflight + skeleton scan (cache by HEAD)
    P-->>O: RepoSkeleton

    O->>I: analyzer → skeptic → verifier (3 rounds)
    I-->>O: ConfirmedIntent { primary, scope, hypotheses }

    O->>PS: select_perspectives(intent)
    PS-->>O: ['data','api','test','history']  ← 'ui' 被裁掉

    par 4 explorers in parallel
        O->>EX: data
        O->>EX: api
        O->>EX: test
        O->>EX: history
    end
    EX-->>O: 4× Perspective
    O->>O: B2 detect_coverage_gaps → 无 → 跳过 re-explore
    O->>CO: consolidate
    CO-->>O: ConsolidatedExploration

    O->>AP: 3 plan_generators (parallel) → evaluator → selector
    AP-->>O: SelectedApproach
    O->>W: write spec
    W-->>O: Spec v0 (含 self_concerns)

    Note over O,V: ── Stage 5.5 / 6 / 6.5 / 7 / 7.5 ──
    loop iteration 1..max_iter
        O->>V: roundtrip / citations / trace / pytest --collect-only / escalation
        V-->>O: 注入 HIGH executability issues (若有)
        par 4 reviewers (+ adversarial if triggered)
            O->>R: architecture / completeness / executability / consistency
        end
        R-->>O: ConsolidatedReview
        O->>M: meta-reviewer
        M-->>O: MetaReviewResult
        O->>A1: observe(IssueCounts)
        alt all_pass
            O->>O: break, finalize ✓
        else regression & budget left
            O->>RW: rewrite from spec_snapshots[last_good]<br/>+ regression_feedback
        else normal
            O->>RW: rewrite(spec, review, meta_review)
        end
        RW-->>O: Spec vN
    end

    O->>O: Stage 9 · persist spec.md/json, review.json, trace.jsonl
    O-->>U: SpecRunResult(ok=True, spec, workspace)
```

---

## Section 6 · 关键设计决策

### 6.1 为什么必须跨家族评审
2024–2025 多篇论文（Self-Preference in LLM Judges、Verbosity Bias、Cohort Bias）显示同家族 judge 对同家族 candidate 的平均评分高 5–18%。在 writer→reviewer→rewriter 闭环里这种偏置**复利放大**——每轮重写都被"友善"评审通过，最终 spec 在跨家族复核时大面积 fail。
**强制点**：`ModelRouter.__init__` 启动期 `raise ValueError`，配置错误立刻爆炸，不能"先跑通看看"。

### 6.2 为什么是 5 个 perspective（不是 3、不是 7）
架构维度（data/api/ui）+ 生产维度（test/history）覆盖任意 web 服务的"信息平面"。security/performance/domain 通过 C3 在 intent 触发时按需替换 ui，避免恒定 5 路浪费 token。实证：case1–case6 每个 case 的 `consolidated.json` 中 ≥4 perspective 都提供过独占信息（即 B2 singleton 检测的来源）。

### 6.3 为什么是 4 个 axis reviewer
正交性：architecture（外部一致）/ completeness（覆盖）/ executability（下游可消费）/ consistency（内部自洽）——4 维在 issue 分布上几乎不重叠（meta-reviewer 平均合并率 < 30%）。adversarial 是**条件第 5 路**——只对 security/auth/llm/upload/payment 等高风险表面触发，避免普通 CRUD spec 被红队过度打分。

### 6.4 为什么"block，不要 hint"
A3 / A4 / F3 都不是给 LLM 加 prompt"请不要这样写"——而是 **pydantic schema 直接拒绝**：
- **A4 软语言**：`should/maybe/TBD` 在 FR/AC 字段是 `ValueError`，不是提示
- **F3 escalation**：≥3 选项的 `Concern.evidence_gap` 在构造时即拒绝，必须升级为 `BlockingDecision`
- **A3 intent-conditional**：reviewer 在 scope 不匹配时 verdict=pass 直接跳过，不靠 prompt 暗示

经验：LLM 对"硬性拒绝 + error message"的修正率 ≈ 100%；对"prompt 软提示"历史观测仅 60–75%。

### 6.5 为什么"halt loud，don't skip silent"
F4 重试栈对所有 transient error（429/500/timeout）jitter + 指数退避；但**永不**静默吞 schema 错误或 `PathOutsideRepoError`——后者一定 raise 并产生 trace event。原因：silent skip 在迭代式系统中是最难调试的故障类——下游看到 spec "看起来正常"，但其实某个 validator 因 import 失败被跳过了。宁可 fail loud。

---

## Section 7 · 代码模块结构

```
devloop/
├── cache.py                       # SQLite cache · TTL + commit-hash key
├── cli/main.py                    # typer 入口 (spec / eval / cost)
├── config/settings.py             # pydantic-settings + YAML loader
├── eval/runner.py                 # golden-set harness
├── llm/                           # LLM gateway 层
│   ├── gateway.py                 # 单一入口 · run counter / cost aggregation
│   ├── routing.py                 # ModelRouter — 跨家族 invariant 在 __init__
│   ├── retry.py                   # F4 jitter+backoff · halt-loud-no-skip
│   ├── trace.py                   # D1 TraceWriter (JSONL · per-stage)
│   ├── trace_analyzer.py          # cost / latency 汇总
│   ├── json_helpers.py            # call_strict_json + call_react_with_tools
│   ├── types.py                   # Message · ToolSpec · LLMResponse
│   └── providers/                 # anthropic_provider / openai_provider / base
├── spec_phase/                    # 9-stage 主体
│   ├── orchestrator.py            # ⭐ 1470 行 9-stage 驱动
│   ├── preflight.py               # Stage 0
│   ├── prompts_loader.py          # 3-layer override (override > local > default)
│   ├── md_json_bridge.py          # B1 spec ↔ markdown ↔ json
│   ├── _homoglyph_table.py        # F1 62K-row Unicode normalization
│   ├── regression_guard.py        # A1 IssueCounts / RegressionGuardState
│   ├── repo_skeleton/             # scanner (tree-sitter) · compressor · builder
│   ├── schemas/                   # pydantic v2 契约 (intent · exploration ·
│   │                              #   approach · spec[含 A4+F3] · review)
│   ├── validators/                # ⭐ Stage 5.5 in-process Python:
│   │   ├── citation_verifier.py   #   A5 path/line/symbol 对盘验证
│   │   ├── trace_matrix.py        #   B3 FR↔SC↔US gap
│   │   ├── coverage_gap_detector.py  # B2 singleton/sparse/conflict
│   │   ├── test_executability.py  #   C2 pytest --collect-only
│   │   └── escalation.py          #   F3-A3 ≥3-option backup
│   └── agents/
│       ├── context.py             # SpecContext (per-run state)
│       ├── writer.py              # writer / rewriter / D3 segmented rewriter
│       ├── intent/stage.py        # Stage 2 analyzer+skeptic+verifier
│       ├── explorer/              # Stage 3:
│       │   ├── stage.py           #   fanout + targeted re-explore
│       │   ├── perspective_selector.py  # C3 intent-driven select
│       │   └── cache.py           #   D2 per-perspective cache
│       ├── approach/stage.py      # Stage 4 plan×3 + evaluator + selector
│       └── reviewers/             # Stage 6+6.5: stage.py (4-axis + C1) · meta.py (B4)
└── tools/                         # LLM-facing 工具集（统一 ToolSpec）
    ├── base.py · registry.py · _paths.py   # 基类 / 注册 / 路径安全
    ├── code_search · file_read · references · navigation
    ├── project_understanding · git_tools
    ├── output_tools.py            # mark_as_relevant / take_note / flag_issue
    └── cost_summary.py            # 每次 run 的 token / latency 汇总

tests/
├── conftest.py · fixtures/                # mock_provider + sample_repo (FastAPI+SQLA)
├── unit/                                   # 76 tests
│   ├── schemas/                            # A4 soft-language adversarial + fuzz
│   ├── validators/                         # A5/B2/B3/C2/F3 each 100% branch
│   ├── agents/reviewers/                   # adversarial / meta / intent-conditioning
│   ├── llm/                                # routing 跨家族断言 · F4 retry
│   └── tools/                              # 12 code tools + 3 output + cost
└── integration/                            # 全链路 mock + 真 LLM e2e
    ├── test_orchestrator_mock.py           # 9-stage full pipeline (MockProvider)
    ├── test_regression_guard_e2e.py        # A1 revert + budget
    ├── test_orchestrator_meta_review.py    # B4 端到端
    ├── test_orchestrator_citation_guard.py # A5 端到端
    ├── test_orchestrator_targeted_reexplore.py  # B2 端到端
    ├── test_b2_coverage_gap_e2e.py · test_c2_test_collect_e2e.py
    ├── test_citation_verifier_e2e.py · test_escalation_e2e.py
    ├── test_perspective_select_e2e.py · test_trace_matrix_e2e.py
    ├── test_adversarial_e2e.py · test_meta_reviewer_e2e.py
    ├── test_review_loop.py                 # A2 终止条件三路
    └── test_edge_stress.py                 # F1/F2 Unicode/boundary

prompts/ · configs/                # 3-layer overrideable prompts · YAML config
├── prompts/{intent,explorer,approach,reviewer}/*.md
├── prompts/writer{,_rewrite,_rewrite_segment_*}.md   # D3 segmented rewriter
├── configs/default.yaml                              # orchestrator / cache / paths
└── configs/models.yaml                               # 跨家族 routes + stage_defaults
```

---

### 附录 · 与 `docs/architecture.md` 的关系

`docs/architecture.md` 是早期写作（Sprint A 完成时），描述 Stage 0–9 的 happy path。本文档（`ARCHITECTURE.md`）补足三块前者未覆盖的内容：

1. **19 道防御机制的全图**（Sprint A/B/C/D/F 完成后的全貌）
2. **不变式的 enforcement 点**（cross-family、A4 schema reject、F3 escalation reject 等）
3. **失败模式的回路设计**（A1 + A2 状态机，回归不烧 no-progress 预算）

数据指标、case 对比、ROI 折线等 → 见 `SHOWCASE_README.md` 与 `specs/CROSS_CASE_*.md`。
