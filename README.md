# DevLoop Spec Agent · 多智能体软件需求规格自动生成系统

> 把一句话需求 + 一个真实的 git 代码仓库，变成可被下游 plan / code agent 直接消费的工程级 spec（`spec.md` 给人看 + `spec.json` 给机器读）。
> 9 阶段流水线 · 19 道防御机制 · 跨家族 LLM 评审 · 收敛底线 · 红队第 5 维。

[![tests](https://img.shields.io/badge/tests-537%2F537%20passed-brightgreen)](./EVIDENCE.md) [![coverage](https://img.shields.io/badge/coverage-79.84%25-green)](./EVIDENCE.md) [![defenses](https://img.shields.io/badge/defenses-18%2F19%20live--activated-blue)](./DEFENSES.md) [![python](https://img.shields.io/badge/python-3.11%2B-blue)](./pyproject.toml) [![license](https://img.shields.io/badge/license-MIT-lightgrey)](./pyproject.toml)

> 📘 **面试 / 第一次接触者请直接看** [`面试讲解指南.md`](./面试讲解指南.md)（41 KB，11 节循序渐进，含 12 个高频追问 Q&A）

---

## 目录

- [一句话讲清楚](#一句话讲清楚)
- [为什么需要这个系统](#为什么需要这个系统)
- [整体架构：9 阶段 + 4 类 agent + 5 个机械校验器](#整体架构9-阶段--4-类-agent--5-个机械校验器)
- [五大核心设计决策](#五大核心设计决策)
- [19 道防御机制速查表](#19-道防御机制速查表)
- [📊 代码与测试统计（实测）](#-代码与测试统计实测)
- [6 个真实 Mealie case 实战数据](#6-个真实-mealie-case-实战数据)
- [安装与运行](#安装与运行)
- [项目结构](#项目结构)
- [模型分工与成本](#模型分工与成本)
- [文档地图](#文档地图)
- [开发与贡献](#开发与贡献)
- [License](#license)

---

## 一句话讲清楚

> 输入「自然语言需求 + 真实 git 仓库」→ 输出「严谨、带行号引用、内部一致、且通过跨家族 LLM 评审的工程级 spec」。

这是一个**多智能体（multi-agent）系统**，专门解决 **AI 写软件需求文档时不靠谱**这个问题。它不只是「一次 LLM 调用 + 模板」——它把 spec 生成拆成 9 个阶段，每个阶段都有独立的 [pydantic v2](https://docs.pydantic.dev/) schema 强约束，全程被 19 道防御机制保护，并由 **Claude 写作 + GPT 评审**的跨家族不变式（startup-time `raise`）守住质量底线。

---

## 为什么需要这个系统

### 表面问题：让 LLM 直接写 spec 不行吗？

**实测过**：用 Claude Opus 4.7 单次直接出 spec，放到 6 个 [Mealie](https://github.com/mealie-recipes/mealie) 真实功能（购物清单归档、收藏夹、菜单 N+1 优化、跨域定时同步、LLM 图片识别等）上，**6/6 都至少有 1 个评审维度判 NEEDS_REFINE**。平均每份初版 spec：

| 失败模式 | 频次 | 后果 |
|---|---|---|
| `file:line` 引用错误（指向不存在的行/函数） | ≥ 4 处 / spec | 下游 code agent 跳去看找不到，瞎猜或放弃 |
| 软语言（"或类似"、"如有需要"、"TBD"） | ≥ 1 处 / spec | code agent 无法决策，多半选错 |
| md/json 漂移（人看的与机器读的对不上） | ≥ 1 处 / spec | PR 评审看 md，自动测试读 json，两边各做一半 |
| 漏关键场景（如「删除评论」漏了） | 不定 | 上线才发现 |
| 越改越烂（rewriter 引入新 bug） | 30% | 修一个坏俩个，迭代发散 |
| 同厂模型自评虚高（论文证实 +5~18%） | 系统性 | 反复"通过"实际跨家族复核全栽 |
| 隐藏式多选项（"option A or B or C, TBD"） | 不定 | 没人决策直接 code，浪费 1–2 天 |

这些 bug **单看都不致命**，叠在一起就让「AI 自动开发流水线」**没法用**——下一棒（plan/code/test agent）基于烂 spec 工作，错误是**指数放大**的。所以 spec 阶段质量是**整条流水线的瓶颈**。

### 为什么 prompt 工程解决不了

直觉解法：在 prompt 加一句「不要写 TBD、不要瞎引用行号」。**实测**：修正率只有 **60–75%**——LLM 经常忽略 prompt 禁令。

本项目的核心工程哲学：**block, don't hint**——把约束**从「提示」升级为「硬约束」**（pydantic `ValidationError` 直接拒收），修正率立刻 ≈ **100%**（你结构上写不出来不合规的 spec）。

---

## 整体架构：9 阶段 + 4 类 agent + 5 个机械校验器

```
┌──────────────────────────────────────────────────────────────┐
│  用户输入：自然语言需求 (≥8 字符) + repo 路径                │
└──────────────────────────────────────────────────────────────┘
                        ↓
  Stage 0 · Preflight        (Python 规则，0 LLM)
                        ↓
  Stage 1 · Repo Skeleton    (tree-sitter 扫码 → 1024 token 摘要，commit-hash 缓存)
                        ↓
  Stage 2 · 意图理解         (Claude analyzer ←→ GPT skeptic ←→ Claude verifier，3 轮收敛)
                        ↓     输出 ConfirmedIntent（含 primary / scope / hypotheses）
  Stage 3 · 5 视角并行探索   (data / api / ui / test / history 并行 · Claude × 5)
                        ↓     ↑ C3 按 intent 自动选视角 · B2 自动检测覆盖盲区
                              ↑ B2 若发现 gap → 定向重探 ≤3 次
  Stage 3.5 · 巩固整合       (consolidator · Claude)
                        ↓
  Stage 4 · 3 候选方案脑暴   (conservative / balanced / aggressive · Claude × 3)
                        ↓     ↑ GPT plan_evaluator 跨厂评分 → Claude plan_selector 选最优
  Stage 5 · 写作器           (writer · Claude Opus 4.7，含 self_concerns 字段)
                        ↓
  Stage 5.5 · 5 个机械校验器 (纯 Python，毫秒级，0 LLM、0 token、0 幻觉)
                        ↓     A5 citation / B1 md-json roundtrip / B3 trace matrix
                              C2 pytest --collect-only / F3 escalation
  Stage 6 · 4 + 1 维评审     (architecture / completeness / executability / consistency · GPT × 4)
                        ↓     ↑ C1 红队第 5 维（安全敏感时条件触发）
  Stage 6.5 · 元评审 B4      (Claude · 去重 + 跨视角冲突识别)
                        ↓
            ┌──── 所有维度 PASS? ────┐
            ↓ NO                     ↓ YES
  Stage 7 · 重写器          ┌─→ Stage 9 · 落盘
            ↓               │   spec.md / spec.json / review.json / trace.jsonl
  Stage 7.5 · A1 回归守卫   │   intent/ / exploration/ / approach/ / spec_iterations/
            ↓               │
   ┌── 改善？回归？停滞？───┤
   │                        │
   ├─ 改善 → 回 5.5         │
   ├─ 回归 → revert 到 last_good + 回归感知 prompt（预算 2 次）
   └─ 连续 3 轮停滞 → halt + needs_review（仍落盘）
```

**关键不变式**：
| 不变式 | 在哪里强制 | 违反后果 |
|---|---|---|
| writer 与 reviewer 必须不同厂 | `devloop/llm/routing.py::ModelRouter.__init__` | 启动期 `ValueError`，程序起不来 |
| FR / SC / 描述类字段不得含 9 个软语言 phrase | `devloop/spec_phase/schemas/spec.py` field_validator | pydantic `ValidationError`，writer 必须重写 |
| 任何 `code_reference` 必须文件存在 + 行号在范围 + symbol 在指定行段 | `validators/citation_verifier.py` | 注入 HIGH executability issue 进下轮 review |
| spec.md 与 spec.json roundtrip 字节级一致 | `spec_phase/md_json_bridge.py` | `AssertionError`，writer 必须重写 |
| `Concern.evidence_gap` 不得含 ≥3 个选项 | `schemas/spec.py::detect_underescalated_concern` | 强制升级到 `Spec.needs_clarification.BlockingDecision` |

---

## 五大核心设计决策

每一点都是基于已观测的真实失败模式做的工程选择，不是想当然。

### 1. 跨家族评审是**硬约束**而非配置

* **问题**：[2024–2025 LLM-as-judge bias 论文](https://arxiv.org/search/?searchtype=all&query=llm+judge+bias) 反复证实，同家族 LLM 评同家族输出，分数虚高 5–18%。writer→reviewer→rewriter 闭环里这种偏置**复利放大**——每轮都被"友善"通过，最终跨家族复核全栽。
* **做法**：`ModelRouter.__init__` 启动期 `raise ValueError`，不能在生产被悄悄绕过。
* **代价**：必须同时持有 Anthropic + OpenAI 两套 key。

### 2. 机械校验**完全替代** LLM 自评的 4 类失败

| 防御 | 用 Python 替代了什么 LLM 自评 | 性能 |
|---|---|---|
| **A4 软语言** | "请帮我看看有没有 TBD" | regex + 9 词黑名单 + 62K 行 Unicode 同形字表 + 零宽字符，**结构上写不出来** |
| **A5 行号引用** | "请验证 file:line 真实存在" | 1000 条引用 / **0.9 秒**，LLM 永远做不到这吞吐 |
| **B1 md/json 漂移** | "请对比 .md 和 .json" | spec.md 由 .json 机械生成，roundtrip 不一致即 `AssertionError`，**物理上不可能漂移** |
| **B3 trace matrix** | "请检查 FR ↔ SC ↔ test 覆盖" | 200 × 200 矩阵 / **23 ms**，0 漏 |

**机械校验 = 0 概率漏看 + 0 token 成本 + 毫秒级延迟**——能机械就别 LLM。

### 3. 收敛底线（convergence floor）

* **问题**：朴素「迭代到收敛」假设错的——case5（跨域定时同步：cron + multitenant + i18n + event bus）跑 5 轮卡在 5 个 critical+high 不再下降。剩下的是**产品决策问题**（如 transactional outbox 选型、"当天无 meal plan 时 target list 走哪条"），LLM 不询问 PM 答不出来。
* **做法**：连续 3 轮 stagnant 即 halt + `needs_review`，spec 仍落盘，trace 完整。
* **价值**：好的系统知道**什么时候该停下问人**，比伪装通过诚实。

### 4. 红队第 5 维（C1 adversarial）

* **问题**：4 个常规 reviewer 问的是「spec 是否良好」，但安全攻击者问的是**完全不同的问题**——「假设 code agent 严格按 spec 实现，能怎么打进去？」
* **做法**：intent.scope 含 `security`/`auth`/`upload`/`payment`/`llm` 等关键词时，自动加入第 5 维 adversarial reviewer。
* **战绩**：case6（LLM 图片识别）独立发现 **5 个其它 reviewer 全漏的 CVE 级 bug**，包括 CRITICAL 存储型 XSS（CVSS ~7.5）、EXIF prompt-injection 绕过、Vision 64× 成本放大、rate-limit DoS-on-self、httpx DEBUG 日志泄露 base64 原图。

### 5. 回归感知重写（A1 + revert）

* **问题**：纯迭代在 LLM 重写里**不收敛**——经常「修一个坏俩个」。case6 v2 真实复现过：架构维度从 1C+1H 退化成 2C+1H。
* **做法**：A1 状态机比较 `IterationDelta.critical_plus_high`：
  * 改善 → 更新 `last_good_iteration`
  * 回归 → `revert` 到 last_good + 回归感知 prompt（预算 2 次）
  * 停滞 → 累计；连续 3 轮 → halt
* **关键设计点**：回归不烧 no-progress 预算；`last_good` 只在 improved 时更新，确保 revert 永远更好。

---

## 19 道防御机制速查表

| 编号 | 名称 | 类型 | 实现位置 | live 激活 |
|:---:|---|---|---|:---:|
| **A1** | Rewriter 回归守卫（revert + budget） | iteration safety | `regression_guard.py` | ✅ case5 v3→v4 真触发 |
| **A2** | 多轮收敛循环（≥5 iter 保底） | iteration safety | `config/settings.py` | ✅ case5 跑 5 轮 |
| **A3** | Intent-conditional reviewer | reviewer choreo | `agents/reviewers/stage.py` | ✅ case3/4 |
| **A4** | 软语言 schema 校验（9 词黑名单 + Unicode） | mechanical | `schemas/spec.py` | ✅ 0/12.5 漏 |
| **A5** | Citation 自动校验（file/line/symbol） | mechanical | `validators/citation_verifier.py` | ✅ case5 真拒绝 |
| **B1** | md/json roundtrip 字节级一致 | mechanical | `md_json_bridge.py` | ✅ 0 漂移 |
| **B2** | 覆盖盲区检测 + 定向重探 | coverage repair | `validators/coverage_gap_detector.py` | ✅ GAP-B2-live |
| **B3** | FR↔SC↔test trace matrix | mechanical | `validators/trace_matrix.py` | ✅ 0 漏 |
| **B4** | Meta-reviewer（去重 + 跨维冲突） | reviewer choreo | `agents/reviewers/meta.py` | ✅ case5 5 轮全用 |
| **C1** | Adversarial 红队第 5 维 | reviewer choreo | `agents/reviewers/stage.py` | ✅ case6 找 5 CVE |
| **C2** | Test-grounded 可执行性（pytest --collect-only） | coverage repair | `validators/test_executability.py` | ✅ GAP-C2-live |
| **C3** | Perspective 自动选择 | reviewer choreo | `agents/explorer/perspective_selector.py` | ✅ case4 perf_opt |
| **D1** | Per-stage 成本 / 延迟 trace | engineering | `llm/trace.py` | ✅ 已就绪 |
| **D2** | Explorer 结果缓存（commit-hash key） | engineering | `agents/explorer/cache.py` | ✅ 已就绪 |
| **D3** | 分段流式 rewriter（5 段 / opt-in） | engineering | `agents/writer.py` | infra（默认关闭） |
| **F1** | Unicode 同形字归一（62K 行 confusables） | hardening | `_homoglyph_table.py` | ✅ schema 始终 |
| **F2** | 复数 / 分隔符 / 零宽字符 | hardening | `schemas/spec.py` | ✅ schema 始终 |
| **F3** | ≥3 选项强制 escalation | hardening | `schemas/spec.py` field_validator | ✅ schema 始终 |
| **F4** | Sub-agent strict retry（jitter + backoff） | hardening | `llm/retry.py` | ✅ 已就绪 |

**激活率**：18 / 19 在真实 case 里被触发；D3 是 opt-in，等 A/B 数据再启用。

详情见 [`DEFENSES.md`](./DEFENSES.md)（每条含「设计意图 / 实现位置 / live 触发证据 / 边界与限制」）。

---

## 📊 代码与测试统计（实测）

> **测量时间**：2026-06-28，本地实测命令：
> ```powershell
> Get-ChildItem <path> -Recurse -Include *.py | Get-Content | Measure-Object -Line
> ```
> 测试与覆盖率数字引用自 [`EVIDENCE.md`](./EVIDENCE.md)（含可复现命令与历史 snapshot）。

### 代码规模

| 范围 | 文件数 | 代码行数（含空行 + 注释） |
|---|---:|---:|
| **核心 spec 模块** (`devloop/spec_phase/`) | **39** | **7,699** |
| **全部生产代码** (`devloop/`，含 cli/config/eval/llm/spec_phase/tools) | **71** | **11,697** |
| **测试代码** (`tests/`，含 unit/integration/fixtures) | **63** | **17,194** |
| **提示词模板** (`prompts/`，全部 git 版本化 `.md`) | **30** | **1,006** |
| **case artifacts** (`specs/`，6 个 Mealie live run 全 trace) | **333** | — |
| **配置 + Makefile + pyproject** | 7 | ~150 |
| **顶层文档** (README + 5 份架构/防御文档 + 面试指南) | 8 | ~3,500 |
| **合计（仓库全部追踪文件）** | **520** | — |
| 总代码行（py + md + yaml + toml + cfg + ini） | — | **72,967** |

**测试 / 生产比率**：`17,194 / 11,697 ≈ 1.47×`——业界普遍认为 1.0–1.5× 是「健康」，2.0× 以上是「测试驱动开发文化扎实」。

### 测试与覆盖率（引自 `EVIDENCE.md`，可复现）

| 指标 | 数值 | 复现命令 |
|---|---:|---|
| **总测试数** | **537 全过 / 0 失败 / 0 跳过 / 0 xfail** | `pytest -q --tb=no` |
| 单元测试 | **461** | `pytest tests/unit --collect-only -q` |
| 集成测试 | **76** | `pytest tests/integration --collect-only -q` |
| 总耗时（含 fixture setup） | **84.79 ~ 89.91 秒** | 同上 |
| 行覆盖率（v7 基线） | **79.84 %** | `pytest --cov=devloop --cov-report=term-missing` |
| 100 % 覆盖文件数 | **32** | 同上 |
| 99 % 覆盖文件 | **1**（`spec.py`） | 同上 |

### 防御层覆盖率（按模块）

| 模块 / 防御编号 | 覆盖率 |
|---|---:|
| `validators/`（A5 / B2 / B3 / C2 / F3） | **100 %** |
| `agents/reviewers/meta.py`（B4） | **100 %** |
| `agents/explorer/perspective_selector.py`（C3） | **100 %** |
| `llm/retry.py`（F4） | **100 %** |
| `schemas/`（A3 / A4 / F1 / F2 / F3 全部 pydantic 模型） | **99–100 %** |
| `regression_guard.py`（A1） | **97.7 %** |
| `md_json_bridge.py`（B1） | **95 %** |
| `orchestrator.py`（主调度） | **83 %**（剩余 17% 为错误处理分支） |
| `llm/providers/anthropic_provider.py` & `openai_provider.py` | **25 %**（mock-only，故意未测真 HTTP） |
| `tools/references.py`（tree-sitter LSP） | **38.5 %** |
| `repo_skeleton/scanner.py`（tree-sitter 扫码） | **58.8 %** |

> **未覆盖 ~20% 的明细**（来自 `EVIDENCE.md`）：
> 1. ≈ 115 行 LLM provider HTTP client（不连真 key，**故意未测**）
> 2. 外部工具调用（git / ripgrep / tree-sitter）需要真实环境
> 3. `orchestrator.py` 的边缘失败路径

**结论**：所有核心业务逻辑（schemas / validators / orchestrator / reviewers / regression_guard）都 ≥ 90% 覆盖；剩余 20% 集中在「不便 CI 跑」的边缘路径，与产品决策一致——**79.84% 是审视过的「该测的全测了」**，不是「差点 100%」。

---

## 6 个真实 Mealie case 实战数据

> 来自 [`specs/CROSS_CASE_FINAL_REPORT.md`](./specs/CROSS_CASE_FINAL_REPORT.md)，可逐 case 翻 artifacts 验证。
> 输入源代码：[Mealie](https://github.com/mealie-recipes/mealie) @ commit `4a099c16`
> `C+H` = critical + high 严重度发现数；`0 mech` = 机械校验 0 漏；*partial* = 已触发收敛底线，剩余问题需 PM 决策。

| Case | 类型 | 复杂度 | v1 C+H | 终版 C+H | 状态 |
|---|---|---|:---:|:---:|---|
| **c1 收藏夹** | add_feature | 简单 CRUD | 19（旧 pipeline）→ 2 | 0 mech | partial |
| **c2 购物归档** | add_feature | 中 · multitenant | 3 | **0** | **APPROVE** |
| **c3 菜单 bug 修复** | fix_bug | 中 | 1 | **0** | **APPROVE** |
| **c4 recipe N+1 优化** | perf_opt | 中 | 0 | **0** | **APPROVE** |
| **c5 跨域定时同步** | add_feature | **最复杂 · 跨 5 域** | 10 → 5（5 iter）| floor at human-decision | partial（**正确行为**）|
| **c6 LLM 图片识别菜谱** | add_feature · 安全敏感 | 12 | **0** | **APPROVE** + **5 CVE-grade bug** |

**关键观察**：
* **4 / 6 完美收敛**到 0 issue（APPROVE）
* **2 / 6 触发收敛底线**——系统识别"剩余问题需 PM 决策"并 halt，**不伪装通过**
* **C1 红队在 c6 找到 5 个安全 bug**，全部被其它 4 维度漏掉（详见 [`specs/case6-live-new-20260620/RESULT.md`](./specs/case6-live-new-20260620/RESULT.md)）

**单次端到端调用统计**（实测，所有防御开启）：
* LLM round-trip 次数：**15–24 次** / iteration
* 单 case 成本：**$0.5–1.5**（Claude Opus 4.7 + GPT-5.5 估价）
* 比裸 LLM 单次贵 ~15×，换来 4 类 leakage 的**结构性消除**

---

## 安装与运行

### 先决条件

| 工具 | 版本 | 必需 / 可选 |
|---|---|---|
| Python | ≥ 3.11 | 必需 |
| Git | 任意 | 必需 |
| ripgrep (`rg`) | 任意 | 可选（不装则退化为纯 Python 搜索） |
| Anthropic API Key | — | 必需（writer 侧） |
| OpenAI API Key | — | 必需（reviewer 侧，跨家族不变式强制） |

### 安装

```bash
git clone https://github.com/liyuanjunya/devloop-spec-agent.git
cd devloop-spec-agent
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -e ".[test,dev]"
```

### 配置 API Key

```bash
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:OPENAI_API_KEY    = "sk-..."

# Linux / macOS
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

或在仓库根目录创建 `.env` 文件：

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

### 跑测试套件

```bash
pytest                    # 537 / 537 通过 · 约 85 秒
pytest --cov=devloop --cov-report=term-missing      # 看 79.84% 覆盖率细分
```

### 跑一份完整 spec

```bash
# 中文需求
devloop spec "给购物清单加归档功能，已归档的不出现在主列表，但可以恢复" \
  --repo C:\path\to\some\repo

# 英文需求
devloop spec "Add user authentication to the API" --repo /path/to/repo
```

输出在 `./specs/<run_id>/`，包含：

```
specs/<run_id>/
├── spec.md                          # 最终 spec（人看）
├── spec.json                        # 同样内容（机器读）
├── review.json                      # 4+1 reviewer 合并 verdict
├── trace.jsonl                      # 每次 LLM / 工具调用全量 telemetry
├── intent/                          # Stage 2: analyzer / skeptic / verifier
├── exploration/                     # Stage 3: 5 视角 + consolidator
├── approach/                        # Stage 4: 3 候选 + evaluator + selector
└── spec_iterations/
    ├── spec_v1.md / spec_v1.json    # 每一版 spec
    └── review_v1_*.json             # 每一版每个维度的 review
```

### MVP 模式（快速 prototype）

如果只想看效果不想花钱，加 `--single-*` 标志进入 MVP 模式（约 3× 快 5× 便宜，spec 质量对应下降）：

```bash
devloop spec "..." --repo ./my-project \
  --single-explorer --single-candidate --single-reviewer
```

### 分析已有 run

```bash
devloop analyze-trace ./specs/<run_id>/         # 按 stage 聚合 cost / latency
devloop cost-summary  ./specs/<run_id>/         # 按模型 / 按 stage 出 token / 美元
```

### 不想自己跑？

直接看 case artifacts：

```bash
# 看一个完整 v1→v2 收敛到 APPROVE 的案例
cat specs/case2-shopping-archive-live-new-20260620T120351Z/spec.md

# 看 C1 红队找到的 5 个安全 bug
cat specs/case6-live-new-20260620/RESULT.md

# 看 case5 触发收敛底线的真实轨迹
cat specs/case5-live-iter1-20260619T175133Z/FINDINGS.md
```

---

## 项目结构

```
devloop-spec-agent/
├── README.md                        # 本文件
├── 面试讲解指南.md                  # ⭐ 41 KB 面试演练手册（中文）
├── SHOWCASE_README.md               # 产品自述 + 关键数字
├── ARCHITECTURE.md                  # 5 张 Mermaid 架构图 + 不变式证明
├── DEFENSES.md                      # 19 防御逐条详解 + live 触发证据
├── REVIEWER_GUIDE.md                # 给第一次拿到代码的工程评审者
├── EVIDENCE.md                      # 每个数字可复现的命令与文件:行号
├── pyproject.toml · Makefile · .gitignore
│
├── devloop/                         # ⭐ 生产代码 (71 文件 / 11,697 行)
│   ├── __init__.py · cache.py
│   ├── cli/main.py                  # typer 入口：spec / analyze-trace / cost-summary
│   ├── config/settings.py           # pydantic-settings + YAML loader
│   ├── eval/runner.py               # golden-set 评测脚手架
│   ├── llm/                         # LLM gateway
│   │   ├── gateway.py               # 单一入口 + 全局计数
│   │   ├── routing.py               # ⭐ ModelRouter（跨家族 invariant 在 __init__）
│   │   ├── retry.py                 # F4: jitter + backoff + 5 attempts
│   │   ├── trace.py                 # D1: TraceWriter (JSONL · per-stage)
│   │   ├── trace_analyzer.py        # cost / latency 汇总
│   │   ├── json_helpers.py          # call_strict_json + repair retry
│   │   ├── types.py                 # Message · ToolSpec · LLMResponse
│   │   └── providers/               # anthropic / openai / base
│   ├── spec_phase/                  # ⭐ 9 阶段主体 (39 文件 / 7,699 行)
│   │   ├── orchestrator.py          # ⭐ 1,470 行 9-stage 调度主循环
│   │   ├── preflight.py             # Stage 0
│   │   ├── prompts_loader.py        # 3 层 override (override > local > default)
│   │   ├── md_json_bridge.py        # B1: spec ↔ markdown ↔ json
│   │   ├── _homoglyph_table.py      # F1: 62K 行 Unicode 同形字表
│   │   ├── regression_guard.py      # A1: IterationDelta / RegressionGuardState
│   │   ├── repo_skeleton/           # tree-sitter 扫码 + 压缩 + 构建
│   │   ├── schemas/                 # ⭐ pydantic v2 契约
│   │   │   ├── intent.py · exploration.py · approach.py
│   │   │   ├── spec.py              # 含 A4 软语言 + F1/F2/F3 防御
│   │   │   ├── review.py · common.py
│   │   ├── validators/              # ⭐ Stage 5.5 in-process Python
│   │   │   ├── citation_verifier.py     # A5
│   │   │   ├── trace_matrix.py          # B3
│   │   │   ├── coverage_gap_detector.py # B2
│   │   │   ├── test_executability.py    # C2
│   │   │   └── escalation.py            # F3-A3
│   │   └── agents/
│   │       ├── context.py           # SpecContext (per-run state)
│   │       ├── writer.py            # writer / rewriter / D3 分段重写
│   │       ├── intent/stage.py      # Stage 2: analyzer + skeptic + verifier
│   │       ├── explorer/            # Stage 3:
│   │       │   ├── stage.py         #   fanout + 定向重探
│   │       │   ├── perspective_selector.py  # C3
│   │       │   └── cache.py         #   D2
│   │       ├── approach/stage.py    # Stage 4: 3 plan + evaluator + selector
│   │       └── reviewers/
│   │           ├── stage.py         # Stage 6: 4 axis + C1 adversarial 触发
│   │           └── meta.py          # Stage 6.5: B4
│   └── tools/                       # LLM-facing 工具集 (统一 ToolSpec)
│       ├── base.py · registry.py · _paths.py  # 基类 / 注册 / 路径安全
│       ├── code_search.py · file_read.py · references.py · navigation.py
│       ├── project_understanding.py · git_tools.py
│       ├── output_tools.py          # mark_as_relevant / take_note / flag_issue
│       └── cost_summary.py
│
├── prompts/                         # ⭐ 全部提示词，git 版本化 (30 文件 / 1,006 行)
│   ├── intent/{analyzer,skeptic,verifier}.md
│   ├── explorer/
│   │   ├── _base.md · consolidator.md · targeted.md
│   │   └── {data,api,ui,test,history,security,performance}.md
│   ├── approach/{plan_generator,plan_evaluator,plan_selector}.md
│   ├── writer.md · writer_rewrite.md
│   ├── writer_rewrite_segment_{head,stories,frs,scs,tail}.md
│   └── reviewer/
│       ├── _base.md · meta.md
│       └── {architecture,completeness,executability,consistency,adversarial}.md
│
├── configs/                         # YAML 默认配置
│   ├── default.yaml                 # orchestrator / cache / paths
│   └── models.yaml                  # 跨家族 routes + stage_defaults
│
├── tests/                           # ⭐ 测试 (63 文件 / 17,194 行)
│   ├── conftest.py · fixtures/      # mock_provider + sample_repo (FastAPI+SQLA)
│   ├── unit/                        # 461 单元测试
│   │   ├── schemas/                 # A4 adversarial + F1/F2 hypothesis fuzz
│   │   ├── validators/              # 每个 validator 100% 分支
│   │   ├── agents/reviewers/        # adversarial / meta / intent-conditioning
│   │   ├── llm/                     # routing 跨家族断言 · F4 retry
│   │   └── tools/                   # 12 code tools + 3 output + cost
│   └── integration/                 # 76 集成测试
│       ├── test_orchestrator_mock.py            # 9-stage 全链路
│       ├── test_regression_guard_e2e.py         # A1 revert + budget
│       ├── test_orchestrator_meta_review.py     # B4 端到端
│       ├── test_orchestrator_citation_guard.py  # A5 端到端
│       ├── test_b2_coverage_gap_e2e.py · test_c2_test_collect_e2e.py
│       ├── test_adversarial_e2e.py · test_meta_reviewer_e2e.py
│       ├── test_review_loop.py                  # A2 终止条件三路
│       └── test_edge_stress.py                  # F1/F2 Unicode/boundary
│
├── specs/                           # ⭐ 6 个 Mealie live run 全 artifacts (333 文件)
│   ├── case1-recipe-favorite-*
│   ├── case2-shopping-archive-*
│   ├── case3-mealplan-bug-*
│   ├── case4-recipe-n1-*
│   ├── case5-mealplan-autosync-* · case5-live-iter1-*
│   ├── case6-llm-image-recipe-* · case6-live-new-*
│   ├── GAP-B2-live-* · GAP-C2-live-*       # 防御 live 触发证据
│   └── CROSS_CASE_*.md / CAPABILITY_BOUNDARY_REPORT.md / STRICT_AUDIT_REPORT.md
│
├── docs/
│   ├── architecture.md              # 早期速写（保留）
│   ├── CONFIGURATION.md             # 配置项参考
│   └── QUICKSTART.md                # 5 分钟上手
│
├── eval/                            # 评测 harness + golden set
└── scripts/
    └── generate_homoglyph_table.py  # F1 同形字表生成器
```

---

## 模型分工与成本

### 角色 → 模型映射

> 跨家族不变式由 `devloop/llm/routing.py::ModelRouter` 在启动时断言（违反即崩）。

| 角色 | 模型 | 厂 | 占成本比 |
|---|---|---|---:|
| writer / rewriter / self-reflect | **Claude Opus 4.7** | Anthropic | ~40% |
| explorer × 5 / consolidator | Claude Opus 4.7 | Anthropic | ~25% |
| plan-generator × 3 / plan-selector / intent-analyzer / verifier / meta-reviewer | Claude Opus 4.7 | Anthropic | ~10% |
| **skeptic / plan-evaluator / 4 axis reviewers / C1 adversarial** | **GPT-5.5** | OpenAI | ~25% |
| preflight / skeleton / 5 validators / perspective-selector / A1 guard | — | 纯 Python，0 LLM | 0% |

### 价格估算（参考 `devloop/cli/main.py`）

| 模型 | 输入 / 1K token | 输出 / 1K token |
|---|---:|---:|
| `claude-opus-4-7` | $0.015 | $0.075 |
| `gpt-5.5` | $0.010 | $0.040 |
| `claude-sonnet-4-6` | $0.003 | $0.015 |
| `gpt-5.4` | $0.005 | $0.020 |

**单 case 实测**：6 个 Mealie case 跨 case 总 sub-agent 调用约 **80 次**，单 case **$0.5–1.5**（视 spec 长度）。

---

## 文档地图

| 文档 | 用途 | 适合谁 | 篇幅 |
|---|---|---|---|
| [`README.md`](./README.md) | 项目门面 + 数据总览 | 所有人 | ~25 KB |
| ⭐ [`面试讲解指南.md`](./面试讲解指南.md) | **面试演练手册**（电梯演讲 / 案例走查 / Q&A） | 面试者 | ~41 KB |
| [`SHOWCASE_README.md`](./SHOWCASE_README.md) | 产品自述 + 关键数字 | Hiring manager / 决策者 | ~4 KB |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 5 张 Mermaid 架构图 + 不变式证明 | 架构师 | ~22 KB |
| [`DEFENSES.md`](./DEFENSES.md) | 19 防御逐条 + live 触发证据 + 边界 | 工程评审 | ~38 KB |
| [`REVIEWER_GUIDE.md`](./REVIEWER_GUIDE.md) | 给第一次拿到代码的工程评审者 | code reviewer | ~22 KB |
| [`EVIDENCE.md`](./EVIDENCE.md) | 每个数字可复现的命令与文件:行号 | skeptical reviewer | ~31 KB |
| [`docs/QUICKSTART.md`](./docs/QUICKSTART.md) | 5 分钟上手 | 新用户 | ~3 KB |
| [`docs/CONFIGURATION.md`](./docs/CONFIGURATION.md) | 配置项参考 | 调优用户 | — |
| [`docs/architecture.md`](./docs/architecture.md) | 早期架构速写（保留参考） | — | — |
| [`specs/CROSS_CASE_FINAL_REPORT.md`](./specs/CROSS_CASE_FINAL_REPORT.md) | 6 case 横向对比 | 评估者 | — |
| [`specs/CAPABILITY_BOUNDARY_REPORT.md`](./specs/CAPABILITY_BOUNDARY_REPORT.md) | 能力边界 + 已知缺陷 | 投产前必读 | ~51 KB |

**推荐阅读顺序**：

* **15 分钟（面试 / 快速过）**：本 README → `面试讲解指南.md` § 1–4
* **60 分钟（决策评估）**：上面 + `ARCHITECTURE.md` 图 1+3 + `DEFENSES.md` 顶部 summary table
* **4 小时（深度评审）**：上面 + `EVIDENCE.md` + 翻 `devloop/spec_phase/orchestrator.py` + 跑一个 case + 看 `specs/case5-live-iter1-*/FINDINGS.md`

---

## 开发与贡献

### 本地开发循环

```bash
# 跑全部测试
pytest

# 只跑某个防御的测试
pytest tests/unit/validators/test_citation_verifier.py -v
pytest tests/integration/test_regression_guard_e2e.py -v

# Lint + 类型检查
ruff check devloop tests
ruff format devloop tests
mypy devloop

# 生成覆盖率报告
pytest --cov=devloop --cov-report=html
# 报告在 htmlcov/index.html
```

### 三层 prompt override

提示词查找顺序：
1. `prompts/override/...`（不存在则跳过）
2. `prompts/...`（默认）

修改任何 prompt 都不需要改 Python 代码——`prompts_loader.py` 自动重载。

### 新增一个防御机制的步骤

1. 在 `devloop/spec_phase/validators/` 加一个 Python 模块（或在 `schemas/` 加 pydantic validator）
2. 在 `orchestrator.py` 找合适的 stage 注入（Stage 5.5 之后、Stage 6 之前是机械校验黄金位置）
3. 加 unit test（`tests/unit/validators/`）+ integration test（`tests/integration/test_<defense>_e2e.py`）
4. 在 `DEFENSES.md` 加一节，含「设计意图 / 实现位置 / 何时触发 / 何时不触发 / 边界与限制」
5. （可选）跑至少 1 个真实 case 收集 live 触发证据，写入 `specs/`

---

## License

[MIT](https://opensource.org/licenses/MIT)

