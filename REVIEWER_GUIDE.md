# REVIEWER_GUIDE — 给第一次看这份代码的评审者

> 受众：从未见过本仓库、也没接触过 LLM 多智能体 (multi-agent) 范式的工程评审者。
> 目标：用最少的上下文，让你看懂自己在评审什么、为什么这么写、哪里要警惕。
>
> 配套文档：`SHOWCASE_README.md`（项目自述）、`ARCHITECTURE.md`（架构图与数据流）、`DEFENSES.md`（19 项防御机制清单与触发条件）、`EVIDENCE.md`（6 个 live case 的端到端证据链）。

---

## 1. 10 分钟必读 — 我应该理解的核心概念

### 1. Spec 阶段 vs Coding 阶段

DevLoop 的最终形态是 **spec → plan → code → test → review** 全流程开发智能体。本仓库交付的是其中第一步——**spec 阶段**：把一句自然语言"需求"（例如 *给商品页加用户评论功能*）变成可被下游 plan/code agent 直接消费的**工程级 spec**（`spec.md` + `spec.json`）。后续的 plan/code/test/review 阶段不在本次评审范围。换句话说，你看到的所有代码都在解决同一个问题：**LLM 写需求文档时如何不胡说、不漏说、不互相矛盾**。

### 2. 9 阶段 pipeline

任何一次 `devloop spec "..."` 调用都会按固定顺序穿过 9 个 stage：

```
intent → exploration → consolidator → approach → writer
        → validators → reviewers → meta → rewriter → loop
```

每个 stage 都有独立的 pydantic schema 作为输入/输出契约，全程在 `devloop/spec_phase/orchestrator.py` 编排。Stage 间无共享可变状态，artifacts 全部落到 `specs/<run_id>/` 下；这意味着你完全可以单独读某一个 stage 的输入输出，不必同时理解整条管道。

### 3. 跨家族评审 (cross-family review)

2025 年的多篇 LLM-as-judge 论文证明：**同家族 LLM 给同家族 LLM 打分**有 ~+15% 的 inflation（同厂模型偏袒同厂模型）。本系统把这一发现固化为架构约束——**Writer 用 Claude（Anthropic），Reviewer 用 GPT（OpenAI）**，并在 `devloop/llm/routing.py::ModelRouter.__init__` 启动时强制断言两者非同一 provider。这不是配置项，是**硬约束**：违反即抛错，不能在生产中绕过。

### 4. 4 角度评审

Reviewer 阶段并不是"跑一个万能 reviewer"，而是按 4 个**正交评审维度**各启动一个独立 agent：

- `architecture` — 与现有架构、模式、约定是否吻合
- `completeness` — 用户意图隐含的方面是否都覆盖（user stories / edge cases / NFR）
- `executability` — 下游 code agent 拿到 spec 是否能直接动手（无歧义、无缺口）
- `consistency` — spec 内部自洽（FR ↔ entity ↔ assumption 之间无矛盾）

每个 reviewer 拥有完整的 12 个代码读取工具，看的是**同一份 spec**，但用的是**不同的 mental model**。最后由 meta-reviewer (B4) 去重 + 优先级排序。

### 5. 第 5 角度 adversarial — 红队

当 intent 触发安全敏感条件（scope 含 `security`/`auth`/`external_integration`/`payment`，或 primary 含 `upload`/`image`/`llm`/`openai`/`password`/`token`/`secret`/`pii`/`payment` 等关键词）时，**自动加入第 5 个 reviewer：C1 adversarial**。它扮演**字面主义的攻击者**——假设 code agent 严格按 spec 实现，能怎么打进去。

case-6（LLM image→recipe）的 live 跑实证：**C1 独立发现 5 个其他 4 axis 完全漏掉的安全 bug**，包括 1 个 CVSS ~7.5 的存储型 XSS、1 个 100× 成本放大、1 个 EXIF prompt-injection bypass、1 个 rate-limit DoS-on-self，以及 httpx DEBUG logger 泄露 base64 image。详见 `specs/case6-live-new-20260620/RESULT.md`。

### 6. 机械验证 vs LLM 评审

19 项防御里有 5 项是**纯 Python 实现**（确定性、零幻觉、毫秒级）：

- **A4** 软语言校验（"or equivalent"、"if needed"、"TBD" 等 9 词黑名单 + 同形字 + 零宽字符 + IDNA confusables）
- **A5** Citation verifier（验证 spec 引用的代码 file:line 真实存在、symbol 真实在那一行）
- **B1** md/json roundtrip 一致性
- **B3** Trace matrix（FR ↔ SC ↔ test 的完整覆盖图）
- **F3** Escalation 校验（≥3 选项必须升级到 `needs_clarification`，不能塞 `evidence_gap`）

这些**每个 stage 都强制执行**，不依赖 LLM。它们比 reviewer 评审更可靠——LLM 可能漏看，pydantic 不会。

### 7. 收敛底线 (convergence floor)

最复杂的 case-5（cross-domain scheduled task：cron + multitenant + i18n + event bus）跑 5 轮迭代后**卡在 5 个 critical+high 不再下降**。这**不是 bug**——剩下的问题都是**真实的产品决策**（"如果当天无 meal plan，target list 走哪条？"），不是 LLM 写作问题。任何数量的 rewriter 迭代都解决不了。系统正确识别这一点并 halt，把 spec 标 `needs_review` 等人工介入。**这就是 system 的正确行为**，不是失败。

---

## 2. 12 个常见 FAQ

**Q1: 为什么需要这么多防御机制？单个 LLM 不够吗？**

A: 不够，且能精确量化。单个 LLM 单次产出的 spec，在 6 个 Mealie 真实 case 上的 OLD-pipeline 实测：v1 阶段 **6/6 case 都至少有 1 个 axis NEEDS_REFINE**，包括平均 ≥4 条错误的 file:line 引用、≥1 处 spec.md ↔ spec.json drift、≥1 个软语言 phrase。NEW pipeline 把这 4 类 leakage 用机械校验**结构性归零**（不是降低概率，是物理上不可能产生）。每多一项防御都对应一类已观测的真实 leakage 模式——见 `DEFENSES.md` 每个条目的 "Designed to catch" 字段。这不是"多多益善"，是"每个都堵了一个 OLD 见过的洞"。

**Q2: 用 Copilot CLI sub-agent 替代真 API key 会影响验证可信度吗？**

A: 部分影响，且已诚实标注。本仓库目前的 6 个 Mealie live case 实际是通过 Copilot CLI sub-agent（背后还是 Claude/GPT）跑的，**不是直接调 Anthropic/OpenAI 真 API key**。这意味着：(a) prompt template 在两种模式下可能有细微差异；(b) JSON mode handling 路径不同；(c) Python `anthropic_provider.py` / `openai_provider.py` 仅由 MockProvider 单元测试覆盖。结论可信度方面，机械防御（A4/A5/B1/B3/F3）**100% 不受影响**——它们是纯 Python；LLM-dependent 路径（writer/reviewer prompt 行为）的结论需要在真 API key 下复核才能定性"生产可用"。这一限制在 `specs/CAPABILITY_BOUNDARY_REPORT.md:551-561` 公开记录。

**Q3: 为什么测试覆盖率 79.84% 而不是 100%？**

A: 实测 `coverage report` 输出是 **TOTAL 4629 stmts, 933 missed, 79.84%**。未覆盖的 ~20% 集中在两类：(a) **LLM provider 真 API 调用路径**（`anthropic_provider.py` / `openai_provider.py` 的网络层、SDK 重试分支——必须配真 key 才能跑，CI 不便接）；(b) **`devloop/tools/references.py` 的 tree-sitter 失败兜底分支**（需要恶意构造的语法错误源文件触发）。**所有核心业务逻辑（schemas / validators / orchestrator / reviewers / regression_guard）都 ≥ 90% 覆盖**。79.84% 是经过审视的"该测的全测了"的数字，不是"差点 100%"。

**Q4: case-5 没收敛到 0+0 是 bug 吗？**

A: 不是。case-5 是 cross-domain 多技术栈混合（scheduler + multitenant + i18n + event bus）；5 轮迭代后剩下的 5 个 critical+high 是 **transactional outbox vs internal commits 的设计权衡** 和 **"当天无 meal plan 时 target list 走哪条"的产品语义** ——这些**没有 LLM 能在不询问产品经理的情况下回答**。系统识别出"剩下的问题都需要 human/PM input"并 halt 是正确行为。详见 `specs/case5-live-iter1-20260619T175133Z/FINDINGS.md` 第 60-82 行 "Finding 6" 和 "Finding 7"。这就是"收敛底线"概念存在的意义——好的系统知道什么时候**该停下问人**，而不是继续幻觉式地"修改"。

**Q5: 19 个防御中只有 18 个 live 看到激活，剩下 1 个怎么回事？**

A: 剩下的是 **D3 — 分段流式 rewriter** (`devloop/spec_phase/agents/writer.py::run_rewriter_segmented`)。它把 v2 rewrite 拆成 5 段 LLM 调用（head/stories/FRs/SCs/tail），降低单次输出超 token 上限的风险。它**有完整单元 + 部分 schema 测试**，但**没在 Mealie 真实 case 上跑过**——`settings.py:108-110` 显式 gate 在 parity measurement 完成前不默认启用。这是有意识的保守策略：feature 已写完、测试覆盖，但生产开关明确等待 A/B 数据。诚实标注在 `CAPABILITY_BOUNDARY_REPORT.md:553`。

**Q6: 为什么 A3/A4/F3 设计成"阻塞型"而不是"提示型"？**

A: 因为**提示型**已经被证明 LLM 会忽略。早期版本 A4 软语言检测是输出 ReviewIssue 让 reviewer 决定要不要修；实测：reviewer 经常评 "minor / acceptable" 然后通过，软语言进了生产 spec。改成 pydantic 层面 `field_validator` 抛 `ValidationError`、writer 必须重写后，**OLD-pipeline 历史 leakage 类**结构性消失。F3（≥3 选项必须 escalate）同理——`detect_underescalated_concern` 在 schema 构造时就拒绝，writer 不能"偷偷塞进 `evidence_gap`"。代价是 writer 偶尔需要多一次 retry；收益是 0 false negative。

**Q7: 一个真实 case 端到端跑下来要多少 sub-agent 调用 / 成本？**

A: 实测数据：单次 v1 → v2 完整迭代，**所有防御开启**时的 LLM round-trip 计数 = **15-24 次**（writer 1 + 5 explorers + 可能 3 个 B2 targeted re-explore + 4-5 reviewers (4 axis + 可选 C1 adversarial) + B4 meta + rewriter 1-5）。6 个 Mealie case 跨 case 总 sub-agent invocation 约 80 次（CROSS_CASE_FINAL_REPORT.md:7）。按 Claude Opus 4.7 + GPT-5.5 估价，**单 case 大约 $0.5-1.5**（视 spec 长度，参考 `devloop/cli/main.py` 的 `COST_PER_1K_*` 表）。比裸 LLM 单次贵 ~15×，换来 4 类 leakage 的结构性消除——见 Q1 的对比表。

**Q8: 这个系统跟 spec-kit / GitHub Copilot Spec / Cursor 有什么区别？**

A: 关键差别在**评审与防御**这一层。spec-kit / Cursor 的 spec 生成多数是"单次 LLM + 模板"，没有显式跨家族评审、没有机械验证、没有迭代收敛检测、没有 adversarial 红队。本系统的 9 阶段、4+1 reviewer、19 项防御不是"功能多"——是为了**让 spec 的失败模式可观测、可量化、可阻断**。任何一个被 leak 的 critical/high 都可以被定位到具体的 stage + reviewer + validator。这是 research-grade 而非 chatbot-grade 的设计取向。详细对比留给 `SHOWCASE_README.md` 的 "Related work" 章节。

**Q9: 怎么自己跑一个 case 试一下？**

A: 三步：
```bash
pip install -e ".[test,dev]"
export ANTHROPIC_API_KEY=sk-ant-...    # PowerShell: $env:ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY=sk-...
devloop spec "Add user authentication to the API" --repo C:\path\to\your\repo
```
输出在 `./specs/<run_id>/`。想快速看效果不想花钱，可加 `--single-explorer --single-candidate --single-reviewer` 进 MVP 模式（约 3× 快 5× 便宜，spec 质量也对应下降）。完整流程详见 `docs/QUICKSTART.md`。**不想真跑也可以直接读** `specs/case2-shopping-archive-live-new-20260620T120351Z/RESULT.md`——那是一个完整 v1→v2 收敛到 APPROVE 的现成证据。

**Q10: C1 adversarial reviewer 找到的 5 个安全 bug 有多 critical？**

A: 全部是**会进生产的真 CVE 级别**，不是 lint warning。逐一说明（来自 case6 RESULT.md：187-191）：
1. **CRITICAL** Stored XSS（CVSS ~7.5）— OpenAI Vision 转写含 `<img onerror=...>` 的菜谱页，新 `create_one` 路径未调 `cleaner.clean()`，存库后任何查看者触发。
2. **HIGH** EXIF prompt-injection bypass — `SYSTEM: ignore prior...` 写进 JPEG `UserComment`，绕过 Layer-1/2 text guard。
3. **HIGH** 8192×8192 JPEG → 256 Vision tiles → 单次请求成本 64×，配合 rate limit 10/h 单用户放大 ~640×。
4. **HIGH** Rate-limit DoS-on-self — attacker 用 1×1 黑像素故意触发 OpenAI parse 失败 10 次，烧光合法用户的 hourly slot。
5. **MEDIUM** httpx DEBUG logger 泄露 base64 原图——FR-019 承诺 "no LLM at any level" 但只控制了 Mealie 自己的 logger。

其他 4 个 axis 全部**没看到**这 5 个，因为它们问 "spec 是不是完整、自洽、与现有架构吻合"——而 C1 问 "假设 code agent 字面照做，攻击者怎么打"。两种 mental model 正交。

**Q11: ScopeType/PerspectiveType 为什么 literal 限制？不能更宽？**

A: case-5 live 跑就撞到了这个——intent.scope 想包含 `scheduler`/`event_bus`/`i18n`/`multitenant`，但 `ScopeType` literal 只允许 13 个值，被 pydantic 拒了（`specs/case5-live-iter1-...FINDINGS.md:1-9` Defect 1）。**这是有意的设计权衡**：literal 让下游 perspective auto-select (C3) / adversarial trigger (C1) 能做严格匹配；如果改 `str`，写出 `"backend "` (尾空格) / `"BACKEND"` (大小写) / `"web"` (新词) 都合法，触发逻辑会失效。当前的解法是**通过 case-5 发现 → 在下次 schema 演进时主动扩 6 个值**（FINDINGS.md 已列出 fix needed），而不是放开类型。代价是 schema 演进慢；收益是触发逻辑零幻觉。

**Q12: 这个 spec 系统投生产需要什么前置条件？**

A: `CAPABILITY_BOUNDARY_REPORT.md:586-590` 明确列了 3 项必须先做：
1. **修 A5 path-traversal** — `code_references.file = "../../../etc/passwd"` 当前能通过校验（已有测试文档化，未修），外发客户前必须堵。
2. **真 API key 跑通至少 2 个 Mealie case** — 当前 6 个 case 全部是 Copilot CLI sub-agent 替代，Python `anthropic_provider.py` / `openai_provider.py` 的真 end-to-end 没在仓库里跑过。
3. **A3 加强**：≥3 选项时必须 escalate 到 `needs_clarification` 的 writer-side prompt 规则 + soft validator——case-1 NEW v1 EXEC-NEW-H-001 + ARCH-NEW-H-001 都是这个失败模式的实例。

其他维度的产品就绪度（机械验证 A、迭代安全 B+、对抗评审 A-、端到端 case-1 B+、case-6 A-）见 boundary report §6 完整表。

---

## 3. 阅读顺序 (3 档时间预算)

### 15 分钟档 — 面试 / 快速过一遍

1. `SHOWCASE_README.md`（5 min）— 项目自述、核心数字、为什么这么做
2. `ARCHITECTURE.md` 的**图 1（数据流）+ 图 3（reviewer panel）**（5 min）— 看完两张图就懂了 9 stage 长什么样
3. `DEFENSES.md` **顶部 summary table**（5 min）— 19 项防御一表过

### 60 分钟档 — Code review 半小时半 + 跑一个 case

15 分钟档全部 + 加：

- **本文 (REVIEWER_GUIDE.md) 全部**（20 min）
- 翻 `devloop/spec_phase/orchestrator.py`（15 min）— 主流程入口，看 stage 是怎么串起来的
- 翻 `specs/case5-live-iter1-20260619T175133Z/FINDINGS.md`（10 min）— 看一个真实 case 的迭代轨迹和 convergence floor 的真实样貌

### 4 小时档 — 深度 review

60 分钟档全部 + 加：

- 翻 5 个 validators 源码（1 h）：`devloop/spec_phase/validators/` 下的 `citation_verifier.py` / `coverage_gap_detector.py` / `trace_matrix.py` / `test_executability.py` / `escalation.py`
- 翻 1 个 case 的全部 artifacts（1 h）：建议选 `specs/case6-live-new-20260620/` —— 这是验证 C1 adversarial 的端到端证据，5 个安全 bug 完整链路都在
- 跑 `python -m pytest -q`（5 min，22.96s）+ `python -m pytest --cov=devloop --cov-report=term-missing` 看覆盖率
- 翻 `EVIDENCE.md` 全部（1 h）— 6 个 case 的端到端证据汇总

---

## 4. 关键代码导航

直接定位常看的文件：

```
入口点                : devloop/cli/main.py                       (typer CLI)
核心 orchestrator     : devloop/spec_phase/orchestrator.py        (9 stage 主流程)
所有 schemas          : devloop/spec_phase/schemas/                (common/intent/exploration/approach/spec/review)
4+1 reviewer 触发     : devloop/spec_phase/agents/reviewers/stage.py::_should_run_adversarial
4 reviewer 编排       : devloop/spec_phase/agents/reviewers/stage.py
meta-reviewer (B4)    : devloop/spec_phase/agents/reviewers/meta.py
5 个验证器            : devloop/spec_phase/validators/
                        ├── citation_verifier.py     (A5)
                        ├── coverage_gap_detector.py (B2)
                        ├── trace_matrix.py          (B3)
                        ├── test_executability.py    (C2)
                        └── escalation.py            (F3)
A1 回归 guard         : devloop/spec_phase/regression_guard.py
LLM gateway           : devloop/llm/gateway.py
跨家族 router         : devloop/llm/routing.py::ModelRouter
提示词模板            : prompts/                                  (全部 .md，git 版本化)
                        ├── intent/{analyzer,skeptic,verifier}.md
                        ├── explorer/{data,api,ui,test,history,security,performance,consolidator}.md
                        ├── approach/{plan_generator,plan_evaluator,plan_selector}.md
                        ├── writer.md + writer_rewrite*.md
                        └── reviewer/{architecture,completeness,executability,consistency,adversarial,meta}.md
配置默认值            : configs/{default,models}.yaml
真实 case artifacts   : specs/case[1-6]-*/                        (6 个 Mealie live run)
跨 case 总结          : specs/CROSS_CASE_FINAL_REPORT.md + CAPABILITY_BOUNDARY_REPORT.md
```

---

## 5. 我为什么这么设计 — 关键设计决策

### 为什么用 pydantic 强制 schema（不用 free-form JSON）

free-form JSON 让 LLM 自由发挥的代价是**下游解析必须容错**——任何一个字段从 `int` 变 `"3"` 都要 catch；任何一个 enum 漏掉一个值都要兜底。pydantic v2 把这个责任前置：LLM 输出不合规直接 `ValidationError`，`call_strict_json` 自动 N 次 repair retry 把 error 喂回去。**结果是下游代码假定 schema 永远合法**，逻辑复杂度大幅下降。代价是 schema 演进（如新增 ScopeType）需要主动同步——见 Q11。

### 为什么 sub-agent 拒绝静默失败

早期版本 LLM gateway 调用失败时返回 `None`，由调用方 `if result is None: skip`。实测：一次 transient 5xx 让某个 reviewer 静默 skip，最终 spec 漏掉 1 个 critical。改成 `SubAgentFailedError` 必须显式 catch（`devloop/llm/gateway.py:30-35` + `devloop/llm/retry.py` 5 次重试 [2,5,15,30,60]s backoff），orchestrator 现在**要么所有 4-5 reviewer 全部成功跑完，要么整个 run 抛错退出**。没有"半失败但 spec 看起来正常"的中间态。

### 为什么有"convergence floor"概念

朴素假设："多迭代几次总能收敛到 0 issue"。实测 case-5 5 轮后**卡在 5 critical+high 不再下降**——剩下的全是**需要产品决策的真实问题**。如果系统不识别这个底线，会一直 rewrite 直到 hard cap (max_total_iterations=20)，把同样的"需要 PM 决策"问题反复改名再 raise。A2 stagnation detection（"3 次连续无进展就 halt 并标 needs_review"）就是把这个底线显式化。**好的系统知道什么时候停下问人**，比"看起来 0 issue 实际背着用户偷偷决策"诚实得多。

### 为什么 cross-family 评审是硬约束不是可选

2025 多篇 LLM-as-judge bias 论文：同家族 evaluator 给同家族 generator 打分有 ~+15% inflation。这是**结构性偏差**，不是 prompt 工程能修的——同厂的训练分布与喜好分布过于相似。本系统把这一点固化在 `ModelRouter.__init__`：`primary_provider == cross_review_provider` 时**启动直接抛错**。设成 hard error 而非 warning 是为了**生产中不能不小心被绕过**——任何尝试都会在 import 时就崩。代价：必须同时持有 Anthropic + OpenAI 两套 key。

### 为什么 ≥3 选项必须升级到 needs_clarification

早期版本观察：writer 遇到"3 种合理实现方案"时，会塞进 `Concern.evidence_gap` 文本（"option A or B or C, deciding TBD"）然后继续写 spec。下游 reviewer 看着 spec 自洽就通过，**真实歧义被 spec 文本掩盖**，code agent 接到任意选 A 写完，PR review 才发现产品想要 B——浪费 1-2 天。F3 的 `detect_underescalated_concern` 在 schema 层面识别 "or / either / option" 等多选项模式，**强制 writer 用 `BlockingDecision` 显式 escalate 到 `Spec.needs_clarification`**——附带 `recommended_default` + `if_rejected` 字段，让人工评审一眼看到"这里需要决策"。

### 为什么 reviewer 拥有完整 12 个代码读取工具

直觉上"reviewer 只看 spec 不需要看代码"。实测反例：case-3 (bug fix) 的 reviewer 必须读 mealie 真实代码才能判断 spec 描述的"bug"是不是真实存在；case-1 (CRUD) reviewer 必须读现有路由层才能判断新 FR 是不是和现有架构吻合。所以 reviewer 和 explorer **共享同一套 12 个代码工具**（`devloop/tools/`），区别仅在 output tools：explorer 拿 `mark_as_relevant`/`take_note`，reviewer 拿 `flag_issue`。**Tool 能力相同，行为差异由 prompt + output schema 决定**——这是"agentic-first"的核心取向，不是"按角色裁剪工具"。

### 为什么 spec.md 与 spec.json 必须 roundtrip 一致 (B1)

OLD pipeline 在 case-1 v1 实测：spec.md 写了 "FR-007: archive endpoint" 但 spec.json 里的 FR-007 文本是 "delete endpoint"。下游 code agent 看 .md / 测试 author 看 .json，**两边各做一半实现**，PR 才发现。修法不是写校验脚本对比，是 **structural impossibility**——`md_json_bridge.py` 强制 md ↔ json 必须由同一对函数双向生成，roundtrip 不一致直接 `AssertionError`。结果：这一类 leakage **物理上不可能再发生**，而不是"概率降低"。

---

> 评审完欢迎对任何决策提出反对意见——上述每条都是基于已观测的失败模式做的权衡，不是真理。所有"为什么这么做"都附了 case 编号或 file:line 证据，可以直接挑战证据本身。
