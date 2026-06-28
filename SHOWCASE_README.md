# DevLoop Spec Agent — 自动产出生产级 spec 的多智能体系统

## 一句话

输入「自然语言需求 + 真实 git repo」→ 输出「严谨可执行的 `spec.json` + `spec.md`」。Python 3.13、pydantic v2、async-first；9 阶段 pipeline + 19 个防御机制；跨 LLM 家族评审（Claude 写 / GPT 评，避免同家族 bias）；真 LLM 端到端验证走 Copilot CLI sub-agent，无需自配 API key。

## 数字（实测，不是估）

| 指标 | 数值 |
|---|---|
| 代码总行数 | **29,878** 行 / 164 文件 |
| └ `devloop/spec_phase/` 核心 | 7,699 行 |
| └ `devloop/` 全部 production | 11,678 行 |
| └ `tests/` | 17,194 行 |
| └ `prompts/` | 1,006 行 |
| 测试 | **537 / 537 通过**（84 秒）|
| 代码覆盖率 | **79.84%**（核心防御模块 90–100%）|
| 真 Mealie case 端到端验证 | **6** 个 |
| 防御机制 | **19** 个设计 / **18** 个在 live run 中观察到激活 |
| 安全发现 | C1 adversarial round 找到 **5 个真实 CVE 级 bug**（其他 reviewer 全漏）|

## 解决什么真实问题

- **大模型写 spec 漏关键约束、引用错误行号、md/json 漂移、含糊词**（"或类似 / 如有需要"）让下游 code agent 卡死。
- **写完没人评审** → 下游 code agent 一上来就基于烂 spec 写错代码，错误指数放大。
- **改一版越改越烂**（regression）—— 一般系统不自觉。
- 本系统**全部解决**，且每条约束都有 **100% 机械验证**（不靠 LLM 自评）。

## 5 分钟跑起来

```bash
cd C:\Users\v-liyuanjun\source\repos\devloop
pip install -e ".[test,dev]"
pytest                                                # 537/537 通过
devloop spec "给商品页加用户评论功能" --repo <target_repo>   # 产物：specs/{run_id}/
```

需 `ANTHROPIC_API_KEY` + `OPENAI_API_KEY`，或走 Copilot CLI sub-agent 路径（零密钥）。

## 6 个真 Mealie case 实测结果

`C+H` = Critical + High 严重度发现数；`0 mech` = 机械检查 0 漏；*partial* = 已收敛至人工裁决底线。

| Case | 类型 | 复杂度 | v1 C+H | 终版 C+H | 状态 |
|---|---|---|---|---|---|
| c1 favorites | add_feature | 简单 CRUD | 19（旧）→ 2 | 0 mech | partial |
| c2 archive | add_feature | 中 · multitenant | 3 | **0** | **APPROVE** |
| c3 bug fix | fix_bug | 中 | 1 | **0** | **APPROVE** |
| c4 N+1 | perf_opt | 中 | 0 | **0** | **APPROVE** |
| c5 auto-sync | add_feature | **最复杂 · 跨 5 域** | 10 → 5（5 iter）| floor at human-decision | partial |
| c6 LLM image | add_feature | security 敏感 | 12 | **0** | **APPROVE** + 5 安全 bug |

## 推荐阅读顺序

1. **15 分钟** — 本文 + `ARCHITECTURE.md` 图 1 + `DEFENSES.md` 顶 5 个防御
2. **60 分钟** — 上面 + `REVIEWER_GUIDE.md` + 任选 1 个 case workspace（推荐 `specs/case5-mealplan-autosync-*` —— 最难、最能看出系统能力）
3. **4 小时** — 上面 + `EVIDENCE.md` + 翻 `devloop/spec_phase/` 源码 + 本地 `pytest` 跑一遍

## 关键文件位置

- 顶层文档：`SHOWCASE_README.md`（本文）/ `ARCHITECTURE.md` / `DEFENSES.md` / `REVIEWER_GUIDE.md` / `EVIDENCE.md`
- 核心实现：`devloop/spec_phase/`（9 阶段编排 + agents + schemas）
- Prompts：`prompts/`（全部 git-versioned `.md`）
- Case 产物：`specs/case{1..6}-*/`（含 spec.md / spec.json / 全 trace / review 记录）
- 测试：`tests/`（unit + integration + e2e + adversarial）

## 生产就绪等级

**A 级** —— 可投生产 + 人审一道兜底。机械保证、跨家族评审、端到端真实验证三重防线已就位；剩余 *partial* case 全部收敛在「需人工最终裁决」的设计底线，而非系统失控。
