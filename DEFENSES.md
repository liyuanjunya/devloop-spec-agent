# DEFENSES — 19 个防御机制详解

**Audience**: 已读 `SHOWCASE_README.md` + `ARCHITECTURE.md` 的 reviewer，关心每个防御做什么 + 是否真激活验证过。

**Source data**:
- `specs/CAPABILITY_BOUNDARY_REPORT.md` (51 KB) — 最详细证据
- `specs/STRICT_AUDIT_REPORT.md` — 防御激活地图
- `specs/GAP_CLOSURE_REPORT.md` — 3 个 live activation gap 闭合证据
- `devloop/spec_phase/{validators,agents,schemas}/` + `devloop/llm/retry.py` — 实现

**Defense taxonomy**:
- **Mechanical** (A4/A5/B1/B3) — 100% 确定性，schema/算法层强制，不依赖 LLM。
- **Iteration safety** (A1/A2) — 多轮收敛 + 回退。
- **Reviewer choreography** (A3/B4/C1/C3) — 决定何时跑哪个 reviewer + 合并结果。
- **Coverage repair** (B2/C2) — 探索盲区 + 测试可执行性检查。
- **Engineering** (D1/D2/D3) — 成本 trace + 缓存 + opt-in 分段。
- **Hardening (v7)** (F1–F4) — Unicode/复数/逃逸/重试加固。

---

## Summary table

| Defense | Sprint | Live activation | Code coverage | Notes |
|---|---|---|---|---|
| A1 Rewriter regression guard | A | ✅ case-5 v3→v4 真触发 | 97.7% | revert v4→v3 + retry feedback |
| A2 Multi-iter convergence loop | A | ✅ case-5 5 iter | — | config assertion (`max_total_iterations≥5`) |
| A3 Intent-conditional reviewer | A | ✅ case-3 fix_bug + case-4 perf_opt | — | 5 intent_type 各自 mental model |
| A4 Soft-language schema validator | A | ✅ 所有 case 0 hit | 100% schema | 9 token blacklist + Unicode-aware regex |
| A5 Citation auto-verifier | A | ✅ case-5 wrong line 被拒 | 100% validator | 1000 refs / 0.9s |
| B1 md/json roundtrip assertion | B | ✅ 所有 case PASS | 95% | structurally impossible drift |
| B2 Coverage gap detector | B | ✅ GAP-B2-live (singleton+conflict 2 gap) | 100% | cap = 3 re-explore |
| B3 FR↔SC↔test trace matrix | B | ✅ 所有 case 0 gap | 100% | 200×200 / 23 ms |
| B4 Meta-reviewer | B | ✅ case-5 5 轮全用 | 100% | dedup + cross-axis conflict |
| C1 Adversarial red-team | C | ✅ case-6 v1+v2 真触发 + 找 5 CVE | — | intent scope/keyword auto-gate |
| C2 Test-grounded executability | C | ✅ GAP-C2-live (3 stub 分类正确) | 100% | pytest --collect-only |
| C3 Perspective auto-select | C | ✅ case-4 perf_opt → +performance | 100% | always-include + 3 conditional |
| D1 Per-stage cost+latency trace | D | ✅ infrastructure ready | — | `devloop cost-summary` CLI |
| D2 Explorer result cache | D | ✅ infrastructure ready (live 禁用) | — | SHA-256 keyed (commit + intent) |
| D3 Segmented rewriter (opt-in) | D | infra only (默认关闭) | — | 5× LLM calls vs 1, 需 A/B |
| F1 Unicode 同形字 | v7 | ✅ schema 始终激活 | 100% | confusables 全表 + NFKC |
| F2 复数/分隔符/零宽 | v7 | ✅ schema 始终激活 + hypothesis fuzz | 100% | regex `_SEP` class + 500 example/case |
| F3 A3 BLOCKING escalation | v7 | ✅ schema 始终激活 | 100% | `Concern.evidence_gap` field_validator |
| F4 Sub-agent strict retry | v7 | ✅ infrastructure ready | 100% | 5 attempts / `[2,5,15,30,60]s` |

**Activation summary**: 18 / 19 defenses observed firing in live runs. The only one not firing in live is D3 (opt-in by design; needs Mealie-scale A/B parity measurement before flipping default).

---

## Sprint A — 原始 5 个

### A1 — Rewriter regression guard

**Designed to**: 检测 rewrite 让 spec 变差时 (critical+high 增加) 自动 revert + retry，避免 "改一版越改越烂" 的死亡螺旋。

**Implementation**: `devloop/spec_phase/regression_guard.py` (97.7% covered).

Core types: `IssueCounts.from_review()` aggregates per-severity counts from a `ConsolidatedReview`; `IterationDelta.is_regression` returns true iff `curr.critical_plus_high > prev.critical_plus_high`; `RegressionGuardState.last_good_spec_iteration` tracks the most recent non-regressing iter for revert.

**When fires**:
- ✅ critical+high 增加（case-5 真实序列: v1=10 → v2=7 → v3=6 → **v4=7** ← A1 触发 → revert→v3 + regression feedback → v5=5）
- ✅ orchestrator marks `needs_review` after `max_regression_retries=2` exhausted

**Does NOT false-fire when**:
- ✅ critical+high 减少（improvement，`is_improved=True`，更新 `last_good_spec_iteration`）
- ✅ stagnant (same count, `is_stagnant=True` but `is_regression=False`)
- ✅ first iteration（`prev=None`，`is_regression=False` 短路）
- ✅ medium-only churn（critical+high 不变即放行，severity-weighted by design）

**Live evidence**: case-5 v4 真实回归被捕获并恢复（详见 `specs/case5-live-iter1-20260619T175133Z/FINDINGS.md:45-60`，Finding 5 "A1 design is validated by real LLM run"）。Architecture axis v3→v4 由 1C+1H 退化为 2C+1H，rewriter 在修其它 axis 时引入新 critical —— 正是 case-6 v2 motivating pattern 的复刻。

**Tests**: `tests/unit/spec_phase/test_regression_guard.py:77-167`（15 个单元用例覆盖所有 delta 模式）+ `tests/integration/test_regression_guard_e2e.py:6-16, 134-140`（end-to-end revert + retry budget）。

**Boundary / limitation**:
- 只看 TOTAL critical+high，不看 per-axis — 单 axis 退步（completeness +1H/+1M while architecture −3C/−1H 整体仍 −46%）被忽略。case-5 v1→v2 的 completeness 退化就是这种情况（FINDINGS.md:39-43）。Known improvement candidate。
- Severity-weighted only。"−1 critical / +5 medium" 这种交易不触发，但确实让 spec 整体变差。
- Budget 是有限的 (`max_regression_retries=2`)。若 v2 *和* v3 都退步，系统 revert 到 v1 last-good，即使 v2/v3 总 issue 更少。

---

### A2 — Multi-iteration loop hardening

**Designed to**: 防止编排器在慢收敛场景下提前退出。pin 在 `OrchestratorConfig.max_total_iterations >= 5` + `max_regression_retries >= 1`。

**Implementation**: `devloop/config/settings.py:OrchestratorConfig` defaults + `tests/unit/spec_phase/test_regression_guard.py:161-167` 强制断言。

**When fires**: A2 是 **configuration assertion**, 不是 runtime detector — 默认 config 一旦违反最小值，测试就 fail。

**Does NOT false-fire when**: 任何 cap ≥ 5 / retries ≥ 1 的 config 通过。

**Live evidence**: case-5 真实跑了 5 iter（v1 → v5），FINDINGS.md:68-86 完整记录每个 iter 的 C+H 演化。

**Boundary / limitation**:
- A2 是断言而非 runtime 防御。如果用户在 YAML 里把 `max_total_iterations` 调到 2，A2 不会在 runtime 阻止。
- 无 "v3+ tournament" 机制：如果 v2 + v3 都退步，无法在 3 个候选间挑最好的。

---

### A3 — Intent-conditional reviewer (schema scaffolding)

**Designed to**: 让 reviewer 按 intent_type 切换 mental model — `add_feature` 不该被骂 "新代码不存在"; `fix_bug` 必须命名 buggy 函数; `perf_opt` 必须有量化目标。同时通过 `BlockingDecision` schema 强制把 input-vs-code 冲突顶到 spec 顶部的 `needs_clarification` 而不是埋进 `self_concerns`。

**Implementation**:
- `devloop/spec_phase/agents/reviewers/stage.py::_intent_specific_guidance()` (lines 101-171) — 5 个 intent_type 各自渲染独立的 reviewer guidance block。
- `devloop/spec_phase/schemas/spec.py::BlockingDecision` (lines 419-447) — 必填 `recommended_default` + `if_rejected`，且都受 A4 soft-language 检查。

**When fires**:
- ✅ `intent_type="fix_bug"` → reviewer prompt 强制 "DO verify the spec accurately names the buggy function" — case-3 验证。
- ✅ `intent_type="perf_opt"` → reviewer prompt 强制 "DO verify the spec quantifies the target with a concrete threshold" — case-4 验证。
- ✅ `intent_type="add_feature"` → reviewer prompt 禁止 "X function does not exist" 类反馈（避免新功能被误判）— case-1/2/6 验证。

**Does NOT false-fire when**: 任何 intent_type 都有针对性的 mental model；无 intent fallback 到 general 模式。

**Boundary / limitation**:
- A3 是 **schema scaffolding**, 不能强制 writer *用* `BlockingDecision`。case-1 NEW v1 `EXEC-NEW-H-001` 就是 writer 把 3 个 hydration 选项藏进 `self_concerns` 而不升级 — A3 此时沉默。F3 (v7) 部分关闭这个口子（detect ≥3 options in evidence_gap 并 reject）。

---

### A4 — Soft-language pydantic validator

**Designed to**: 拒绝 9 个 hedging phrase (`or equivalent`, `or similar`, `TBD`, `TBA`, `to be decided`, `to be determined`, `if needed`, `as needed`, `placeholder`) 出现在 9 个 guarded field。Schema 层强制 — prompt-only defense 经 5 个 case 验证不可靠。

**Implementation**: `devloop/spec_phase/schemas/spec.py:69-203`。`_FORBIDDEN_PHRASES_RE` regex + `validate_no_soft_language()` helper 挂在每个 guarded field 的 `@field_validator` 上。Escape hatch: 反引号 fenced literal (`` `TBD` ``) 通过 `_strip_code_blocks()` 剥离。

**Guarded fields** (9 个，对应 pydantic validator):
- `FunctionalRequirement.text`
- `SuccessCriterion.metric` / `.threshold`
- `BlockingDecision.recommended_default` / `.if_rejected`
- `Concern.suggested_resolution`
- `Spec.summary`
- `EdgeCase.handling`
- `Entity.description`

**When fires**: `tests/unit/schemas/test_soft_language_adversarial.py:90-187` 各 phrase 在各 field 至少一个 case；end-to-end via `detect_soft_language_in_spec_dict()` in writer (`writer.py:30-90`).

**Does NOT false-fire when**:
- ✅ 反引号 literal 通过（`:209-237`）
- ✅ `suggested_resolution=None` 跳过（`:250-263`）
- ✅ 非 guarded field (`conflict`, `out_of_scope`) by-design 忽略

**Live evidence**: 6 case × 平均 2.5 iter = 12.5 spec versions, **0/12.5 A4 fail** (STRICT_AUDIT_REPORT.md:132).

**Boundary / limitation** (原始 sprint A 版本):
- Unicode homoglyph bypass — **F1 关闭**
- 零宽分隔符 / 复数 / 括号 bypass — **F2 关闭**

详见 F1/F2 段落。

---

### A5 — Citation verifier

**Designed to**: 机械拒绝 `FunctionalRequirement.code_references` 中文件不存在 / line range 越界 / 符号不在指定行段的引用。Orchestrator 把 problem 转 HIGH `executability` ReviewIssue 喂下一轮 review；超过 `citation_verify_max_attempts=3` 标 `needs_review`。

**Implementation**: `devloop/spec_phase/validators/citation_verifier.py` (100% covered). 5 个 problem kind: `file_not_found`, `range_out_of_bounds`, `symbols_missing`, `no_line_ranges_with_symbols`, `invalid_path` (路径遍历)。

**When fires**:
- 文件不存在 → `PROBLEM_FILE_NOT_FOUND` (`test_citation_verifier.py:83-91`)
- `start=0` / `end > EOF` / `start > end` (`:93-121`)
- 符号在 cited range 找不到 (`:123-135, 155-176`)
- 路径 `../../../etc/passwd` → `PROBLEM_INVALID_PATH` (`_is_path_safe` 检查) — **post-CAPABILITY_BOUNDARY fix**, 4 adversarial test 加在 `test_citation_adversarial.py:353-398`

**Does NOT false-fire when**:
- ✅ 合法 path/range/symbol (`:178-203`)
- ✅ 空 `symbols=[]` + 空 `line_ranges=[]` 当作 path-only check (`:188-191`)
- ✅ Python `#` 注释行从 searchable 移除 (`_strip_comment_lines`) — 防止 symbol 只在注释里被误判通过

**Live evidence**: 6 case × 平均 2.5 iter, **0/12.5 A5 fail**. case-5 中 writer 一开始引用了 wrong line range, A5 拒绝后 writer 在 v2 修正 (FINDINGS.md 提到 "writer 修正后 0")。

**Performance**: 10 MB / 100k-line file < 5.0s; 1000 references in **0.90s** (`test_edge_stress.py` perf summary).

**Boundary / limitation**:
- Symbol 匹配是 **syntactic-blind** substring — 不区分 class/def/import/docstring/comment（文档化 in `test_citation_adversarial.py:79-157`，6 个 bypass case）。
- Symlink following 静默接受 (LOW severity test artifact)。
- Path traversal **已修** (`_is_path_safe`) 但原始 capability boundary 报告中是 HIGH severity 安全 bug。

---

## Sprint B — 4 个质量倍增

### B1 — md/json roundtrip drift assertion

**Designed to**: 捕获 rendered `spec.md` 和 canonical `spec.json` 之间的语义/结构漂移。两条断言: `assert_spec_roundtrip_consistent` (JSON→Spec→JSON 字段级 byte-equal) + `find_md_only_content` (每个 H2 必须 map 到 normative Spec 字段)。

**Implementation**: `devloop/spec_phase/md_json_bridge.py` (95% covered). `_KNOWN_H2_SECTIONS` 是 H2 heading → Spec attribute 的字典（10 个 section）。`_find_first_dict_diff()` 递归比较 dict/list 并报告第一个差异 field path。

**When fires**:
- ✅ markdown 多出 `## ...` 在 Spec 没对应 (`test_md_json_drift_adversarial.py:141-188`)
- ✅ JSON writer 丢字段 (e.g. `self_concerns`) → roundtrip raise + 报字段路径 (`:195-231`)

**Does NOT false-fire when**:
- ✅ 干净 spec roundtrip (`:127-134`)
- ✅ `_Generated by DevLoop…` footer 容忍（footer 是 non-normative）(`:240-265`)
- ✅ Unicode / CJK / emoji 完整 roundtrip (`:273-340`)
- ✅ 空 optional sections / 无 user stories (`:348-377`)

**Live evidence**: 12.5 spec versions, **0 drift**. 这一类 OLD pipeline 的 EXEC-H-003 (line range 在 .md 和 .json 不一致) 在 NEW pipeline **结构性不可能** —— .md 是从 .json 机械生成的。

**Performance**: 200 FR / 200 SC / 50 US spec roundtrip in **8.62 ms**.

**Boundary / limitation**:
- Footer 是显式 non-normative。如果 writer 把内容塞进 H3 不在任何 H2 下，B1 不报。
- 只检 **structural** parity。如果 writer 在 FR section 里加 non-normative 段落，B1 可能漏。

---

### B2 — Cross-perspective coverage-gap detector

**Designed to**: 当 5 个 explorer perspective 中只有 1 个 perspective 把某 critical artifact 标 critical (singleton critical) / 存在未解决的 Conflict / 存在 sparse perspective (其他都有 ≥3 artifact 它却 0)，自动 fire 一次 targeted re-explorer。Cap = `max_targeted_reexplorations=3`。

**Implementation**: `devloop/spec_phase/validators/coverage_gap_detector.py` (100% covered). 3 个 gap kind: `singleton_critical`, `unresolved_conflict`, `sparse_perspective`. 每个 gap 携带 `suggested_re_explore_question` + 可选 `primary_perspective` (orchestrator 用来选 *不同* perspective re-explore)。

**When fires**:
- ✅ singleton critical 存在 → re-explore 后 artifact 在 ≥2 perspective 出现 (`test_b2_coverage_gap_e2e.py:226-312`)
- ✅ 10 singleton → 只 fire 3 re-explorer; audit artifact 持久化 (`:410-484`)
- ✅ **GAP-B2-live 真实运行**: 合成 5 perspective + 1 singleton critical (SchedulerService 只被 api 提及) + 1 unresolved conflict → detector 真返回 2 gaps, primary_perspective 正确指向 'api' (singleton) 和 None (conflict，让 re-explorer 看两边)

**Does NOT false-fire when**:
- ✅ 全覆盖 exploration 跳过 re-explore (`:320-403`)
- ✅ 所有 perspective 都空 → 不报 sparse (那是 "nothing to find" case 而非失败)

**Live evidence**: `specs/GAP-B2-live-20260620/B2_LIVE_RESULT.md` + GAP_CLOSURE_REPORT.md:12-25. 之前 STRICT_AUDIT 标 ⚠️ "未观察激活"，现在 ✅ 真触发 + 2 gap 检出。

**Boundary / limitation**:
- Re-explorer **失败被吞** —— orchestrator 记 warning + 返回原 exploration（graceful degradation by design）但 flaky re-explorer 可能掩盖真 gap (`:498-556`)。
- Cap=3 是 hard。10 个 singleton-critical gap 中 7 个静默未补。
- "Singleton" 通过 identity-string 匹配 artifact path；两个 perspective 引用同代码但行号略不同会被误判为各自 singleton。

---

### B3 — FR ↔ SC ↔ US trace matrix

**Designed to**: 强制 "每个 functional FR 至少 ≥1 SC 验证 / 每个 SC 至少被 ≥1 FR 引用 / 每个 P1 user story 至少被 ≥1 FR claimed"。Orchestrator 把 gap 转 HIGH `executability` issue。

**Implementation**: `devloop/spec_phase/validators/trace_matrix.py` (100% covered). 5 个 gap kind: `fr_without_sc`, `sc_without_fr`, `sc_references_unknown_fr`, `fr_references_unknown_sc`, `us_without_fr`. 双向边: `FR.related_success_criteria` 或 `SC.related_requirements` 任一方向建立即认为 connected。

**When fires**:
- FR without SC (`test_trace_matrix.py:119-130`, e2e `:291-302`)
- SC without FR (`:132-148`, e2e `:305-322`)
- P1 US without FR (`:220-233`, e2e `:325-339`)
- 未知 FR/SC id 引用 (`:165-198`)

**Does NOT false-fire when**:
- ✅ 干净双向 trace (`:107-117, 150-163`)
- ✅ Non-functional FR 无 SC 豁免 (`:201-218`)
- ✅ P2/P3 US 无 FR 豁免 (`:235-246`)
- ✅ 空 spec (`:298-301`)

**Live evidence**: 12.5 spec versions, **0 gap** 在终版。

**Performance**: 100×100 paired spec < 1.0s; 200×200 in **22.86 ms**.

**Boundary / limitation**:
- **无 normalization** — `FR-001` ≠ `fr-001` ≠ `FR-001 ` 文字处理 (`test_trace_matrix_adversarial.py:192-323`)。Writer 用 inconsistent casing 会产 spurious gap。
- 重复 FR id 不 crash 但 dedup 静默。
- Self-reference (FR id 当 SC id) 同时产 "unknown SC" + "FR without SC" 两 gap，可用性 nit。

---

### B4 — Meta-reviewer (action consolidation)

**Designed to**: 接 4 (或 5 with C1) axis review，dedupe overlapping issue，按 severity+impact 排出一个有界 (1..5 priority) 的 action list 给 rewriter。这样 rewriter 不会 "修一个 axis 破另一个" (即 case-6 v2 的原始 motivating pattern)。

**Implementation**: `devloop/spec_phase/agents/reviewers/meta.py` (100% covered). 走 `call_strict_json` (`devloop/llm/json_helpers.py`) 带 1 次 repair retry。返回 `MetaReviewResult { actions, cross_axis_conflicts }`，rewriter 收到时按 ID 顺序执行。

**When fires**:
- ✅ 4 axis review → 合并 dedup action list (`test_meta_reviewer.py:242-303`)
- ✅ 跨 reviewer 重复 issue dedup 为 1 merged action (`test_meta_reviewer_e2e.py:224-307`)
- ✅ `conflicts_with` 字段在 rewriter prompt 中显式提示 (`:414-506`)
- ✅ 第一次 LLM response invalid 被 strict-JSON wrapper 修复 (`:483-513`)
- ✅ meta-reviewer 失败 graceful degrade（emit `meta_review_error`，rewriter 仍跑 raw issues）(`:649-764`)

**Does NOT false-fire when**:
- ✅ `enable_meta_reviewer=False` 跳过 (`test_orchestrator_meta_review.py:486-556`)
- ✅ 空 MetaReviewResult 有效 (`:201-209`)
- ✅ priority 1..5 严格 (`:211-220, 379-409`)
- ✅ 无效 `affected_axes` reject (`:222-235`)

**Live evidence**: case-5 5 轮都用了 meta-reviewer (`spec_iterations/meta_review_v{1,2,3}.{json,md}`)。case-6 v1+v2 也用了 meta + adversarial 联动。

**Boundary / limitation**:
- `source_issue_ids=[]` + `affected_axes=[]` 是 schema-permitted 但语义可疑 — meta 可 emit 无 traceability action。
- Schema 不强制 action id 唯一。
- 跨 iteration 无法 dedup（仅一轮内 4 review）。

---

## Sprint C — 3 个覆盖深度

### C1 — Adversarial red-team reviewer (5th angle)

**Designed to**: 第 5 个 reviewer，prompt 让它 "想象 spec 被字面实现 — 哪种攻击成功？"。按 intent.scope (security/auth/external_integration/payment) 或 intent.primary keyword (upload/openai/llm/password/pii/secret/image/file/prompt/token) 自动启用; `force_adversarial=True` 手动上, `disable_adversarial=True` kill switch 总是赢。

**Implementation**: `devloop/spec_phase/agents/reviewers/stage.py:_should_run_adversarial` (lines 77-98) + `_ADVERSARIAL_SCOPE_TRIGGERS` / `_ADVERSARIAL_PRIMARY_KEYWORDS` frozenset。Gating 在 `run_review_stage` line 327-347 (precedence: disable > force > heuristic)。

**When fires**:
- ✅ security scope 触发 (`test_adversarial_reviewer.py:37-41`)
- ✅ auth / external_integration / payment scope (`:43-62`)
- ✅ upload / openai / llm / password / pii / secret / image keyword (`:69-108`)
- ✅ explicit `force_adversarial=True` (`:156-171`)
- ✅ **case-6 live run**: `intent.scope=['external_integration','security']` + `primary` 含 'image','llm','openai','prompt','upload' → both signals fire (GAP_CLOSURE_REPORT.md:46-54)

**Does NOT false-fire when**:
- ✅ plain backend / frontend intent (`:116-126`)
- ✅ 空 intent (`:128-136`)
- ✅ `disable_adversarial=True` 否决甚至 security scope (`:174-189`)
- ✅ disable 赢 force (`:192-205`)

**Live evidence — 5 个 CVE 级安全 bug**（其他 4 reviewer 全漏，详见 GAP_CLOSURE_REPORT.md:78-87）:

| # | ID | 严重度 | 攻击 |
|---|---|---|---|
| 1 | X-C-001 | CRITICAL | Rate-limit DoS-on-self — 攻击者用故意失败的 OpenAI 请求耗光用户 10/hr 额度 |
| 2 | X-H-001 | HIGH | EXIF prompt-injection — JPEG `UserComment` 藏 "SYSTEM: ignore prior instructions" |
| 3 | X-H-002 | HIGH | Image-dim 成本放大 64× — 8192×8192 = 256 tile vs 1024×1024 = 4 tile |
| 4 | X-H-003 | HIGH | Stored XSS via LLM output — Vision 转录 `<img src=x onerror=...>` 没被 cleaner.clean 处理 |
| 5 | X-H-004 | HIGH | 时间/资源旁路 — OpenAI 响应时间推断后端状态 |

v2 全部关掉: FR-031 (EXIF strip), FR-029 (LANCZOS 2048×2048 downsample), NC-004 + 双层 counter (30 attempts/hr + 10 successes/hr), 新 sanitize 路径。**case-6 1C+11H → 0C+0H 完全收敛**。

**Boundary / limitation**:
- Substring 匹配 over-eager — `"token-bucket"` 触发因为 `"token"` 是 substring (`test_adversarial_selection.py:139-145`)。成本 = 偶尔多 1 个无关 spec 的 LLM call。
- C1 是 case-6 OLD-v2 rate-limit-ordering 回归类的 **唯一** primary defense — 没 C1 时 A5/A4/B1/B3 全过但 spec 真的 ship rate-limit-before-validation bug。
- 启用是 heuristic-driven — intent 解析错 → 无 fallback。

---

### C2 — Test-grounded executability (pytest --collect-only)

**Designed to**: 从 spec 抽取 `tests/.../*.py[::func]` 引用 → 生成 pytest stub → 真起 `pytest --collect-only` 验证可收集。Catch: `no_such_file` / `collect_error` / `fixture_not_found` / `import_error`.

**Implementation**: `devloop/spec_phase/validators/test_executability.py` (100% covered). `_TEST_REF_RE` 提取引用; `generate_stub_test_file` 生成 minimal stub; `_run_pytest_collect_only` subprocess + `_classify_error` 分类失败原因。

**When fires**:
- ✅ syntactically broken stub → `import_error` (`test_c2_test_collect_e2e.py:137-188`)
- ✅ 缺 import → `import_error` (`:195-250`)
- ✅ 未知 fixture → `fixture_not_found` (mocked pytest output) (`:253-336`)
- ✅ 无 test refs → 不起 subprocess, 不建 scratch dir (`:339-385`)
- ✅ **GAP-C2-live 真实运行** (`specs/GAP-C2-live-20260620/C2_LIVE_RESULT.md`): 3 stub (好/broken_import/no_func) → 真起 pytest subprocess → 正确分类 `import_error` + `collect_error` (errmsg 精准: "pytest collected ... but the spec-named test function 'test_missing' was not present")

**Does NOT false-fire when**:
- ✅ 干净 collectible stub (`:105-129`)

**Live evidence**: GAP_CLOSURE_REPORT.md:27-40。之前 ⚠️ "只在单测验证"，现在 ✅ 真起 subprocess + 准确分类。Bonus: in-tree scratch 会被 `pyproject.toml` 的 `addopts=-v` 污染输出，production 用 out-of-tree tmpdir 不影响（低优先级 follow-up: 加 `--override-ini=addopts=` 兜底）。

**Boundary / limitation**:
- **Fixture resolution 不被 `pytest --collect-only` 真执行** — collection 只 parse。Real-world spec 引用一个 runtime-不存在 fixture 不被 catch。测试老实地 mock 这一段 (`:253-266`)。
- `test_executability_timeout_s=30` — 大测试树会 timeout 误报。

---

### C3 — Perspective auto-selection

**Designed to**: 按 intent 选 explorer perspective。always include base: `data/api/test/history`; 按 scope/keyword 加 `ui`/`security`/`performance`。

**Implementation**: `devloop/spec_phase/agents/explorer/perspective_selector.py` (100% covered). 简单确定性逻辑: scope 集合交 + primary lowercase substring。

**When fires**:
- ✅ scope 含 `ui`/`frontend` → +ui (`test_perspective_select_e2e.py:50-67`)
- ✅ scope 含 `security`/`auth`/`external_integration` 或 primary 含 `upload/image/file/prompt/llm/openai/password/token/secret/rate-limit` → +security (`:80-107`)
- ✅ `intent_type=="perf_opt"` 或 primary 含 `n+1/performance/latency/optimize/slow/query count` → +performance (`:110-127`)

**Does NOT false-fire when**:
- ✅ backend-only intent 不加任何 optional (`:34-48`)
- ✅ explicit override 返回 verbatim，**不加 auto** (`:130-148`)

**Live evidence**: case-4 `intent_type=perf_opt` → 自动加 performance perspective。case-6 security scope → 加 security。

**Boundary / limitation**:
- **explicit override 绕过 base** — `perspectives=[]` 会静默没有 exploration (`:130-148`)。C3 完全信任 override。
- Keyword 是 substring — `"openaiwrapper"` 触发 security 因为 `"openai"` 是 substring。

---

## Sprint D — 3 个工程化

### D1 — Per-stage cost + latency trace

**Designed to**: 解析 `trace.jsonl` 输出 per-stage + per-model cost & latency summary。CLI 命令 `devloop cost-summary <trace.jsonl>` + 每次 `devloop spec` 结束自动打印 "top 3 stage by cost"。

**Implementation**: `devloop/tools/cost_summary.py`. `RunCostSummary` dataclass 含 `per_stage: list[StageCost]` + `per_model: dict[str, StageCost]`。pricing 表硬编码（须随模型 release 更新）。

**Stage 字段优先级**: 事件 `current_stage` (orchestrator level, e.g. `writer`/`review_iter_1`) → 否则 fine-grained `stage` field (e.g. `review.architecture`) → 否则 `UNKNOWN_STAGE`。

**When fires**: 任何带 `usage` 字段（input/output tokens）的 trace event 都计入。

**Does NOT false-fire when**: 无 LLM call 的 stage 不出现在 summary。

**Live evidence**: D1 是 infrastructure，per-stage cost 在所有 6 case 的 trace 里可查。

**Boundary / limitation**:
- Pricing 表手维护; unknown model 记 warning + cost=0（不 crash）。
- 不分 prompt vs completion token cost ratio 之外的细节。

---

### D2 — Per-perspective explorer cache

**Designed to**: 避免在同 repo + 同 intent 上重跑昂贵 LLM exploration。缓存 key = SHA-256 of `(cwd_path, head_commit, perspective_type, intent_summary)` where `intent_summary = intent.primary[:200]`。TTL = `cache.ttl_days=7` (in `devloop/cache.py`)。

**Implementation**: `devloop/spec_phase/agents/explorer/cache.py`. `compute_perspective_cache_key()` + `get_cached_perspective()` / `set_cached_perspective()`. 反序列化失败当 miss 处理（不 crash）。

**When fires**: cache hit → 短路 LLM call; miss → 跑 LLM + 写 entry; TTL expiry → invalidate.

**Does NOT false-fire when**: `use_cache=False` 或 `--no-explorer-cache` CLI flag 绕过 (D1 kill-switch interaction)。

**Live evidence**: infrastructure。Live LLM run 时禁用了 cache 以确保观察真实 explorer 行为。

**Boundary / limitation**:
- Key 用 `head_commit`。**uncommitted local change 不在 key** — 在同 commit 但 working tree 不同时返回 stale (in `devloop/cache.py` 已文档化)。
- 无 cache 投毒 adversarial test (e.g. malicious `intent_summary` 制造 hash collision)。

---

### D3 — Segmented rewriter (opt-in)

**Designed to**: 把 rewrite 拆成 5 个验证过的 LLM call (head / stories / FRs / SCs / tail) 而非一次 ~30KB single-shot。每段 partial schema validate; segment 失败时 fall back 到 previous spec 对应字段（graceful degradation）。默认 `use_segmented_rewriter=False`。

**Implementation**: `devloop/spec_phase/agents/writer.py:run_rewriter_segmented` (lines 328-467). `_SEGMENT_ORDER = ("head","stories","frs","scs","tail")` 固定（head 先因为有 metadata + summary；stories 在 FRs 前因为 FR 引用 US id；FR 在 SC 前因为 SC 引用 FR id）。

**When fires**: `tests/unit/agents/test_writer_segmented.py` 每个 segment 单独 validate; orchestrator 拼接成最终 Spec; 失败 segment 用 previous_spec 兜底。

**Does NOT false-fire when**: `use_segmented_rewriter=False` (默认) 用单次 rewriter。

**Live evidence**: infrastructure only。Mealie eval 还未跑 segmented vs single-shot parity 实验（`settings.py:108-110` 文档化 gating concern）。

**Boundary / limitation**:
- **Opt-in only** — 没 Mealie 端到端 measurement。所有 6 case 都走 single-shot 路径。
- 期望 latency multiplier ≈ 2-3× (5× LLM call 但每个 context 更小)。
- 无 A/B harness 证明 segmented ≥ single-shot 质量 — 这是文档化的 gating concern。

---

## v7 — 4 个后期加固

### F1 — Unicode 同形字 (IDNA confusables 全表)

**Designed to**: 关闭 A4 的 Unicode-homoglyph bypass。`"оr equivalent"` (Cyrillic `о` U+043E) / `"placeh𝐨lder"` (Math Bold) / Fullwidth `"ｐｌａｃｅｈｏｌｄｅｒ"` 全部正常化为 ASCII 后再过 regex。

**Implementation**: `devloop/spec_phase/_homoglyph_table.py` (vendored 62 KB table, generated by `scripts/generate_homoglyph_table.py` from `confusable-homoglyphs` package which mirrors https://www.unicode.org/Public/security/latest/confusables.txt). 应用在 `devloop/spec_phase/schemas/spec.py:_normalize_for_match` (lines 102-131):
1. NFKC normalize (collapse compatibility forms — Fullwidth Latin, Math Alphanumeric Symbols, ligature)
2. Per-char `HOMOGLYPH_TO_ASCII.get(ch, ch)` 折叠 (Cyrillic / Greek / Coptic / Armenian / IPA / Cherokee)
3. 剥离 Cf (Format) chars (ZWSP / ZWNJ / bidi overrides)

**Whitelist**: CJK / Hiragana / Katakana / Hangul / Arabic / Hebrew / Devanagari **不在表内** — 合法多语言 spec 文本不受影响。

**When fires**: schema 层始终激活 — `find_forbidden_phrase` 调两遍 normalize (`_normalize_for_match` Cf-strip + `_normalize_for_match_spaced` Cf→space) 各跑 regex。

**Does NOT false-fire when**: CJK / 阿拉伯 / 日文 等 whitelisted scripts 原样通过。

**Tests**: `tests/unit/schemas/test_soft_language_adversarial.py:1-7` header + Cyrillic/Greek/Math/Fullwidth 各 case 在 adversarial 文件内。

**Boundary**: 表是 confusables.txt 子集（仅含会折成 ASCII letter `a-z/A-Z` 的字符）— 若未来新增 Unicode block 出现 letter homoglyph，须重跑 generator 刷新表。

---

### F2 — 复数/分隔符/零宽 (extended regex + hypothesis fuzz)

**Designed to**: 关闭 `TBDs`, `if-needed`, `as_needed`, `if·needed`, `if(needed)`, `or\u200Bequivalent` 等 boundary-mutation bypass。Regex 用 `_SEP` permissive separator class + 可选 plural + 可选括号包裹。

**Implementation**: `devloop/spec_phase/schemas/spec.py:55-89`:

```python
_SEP = r"[\s\-_.\u00b7\u200b\u200c\u200d\u200e\u200f]"
_NW  = r"(?![A-Za-z])"   # 尾边界：禁止 mid-word 续接

_FORBIDDEN_PHRASES_RE = re.compile(
    rf"\bor{_SEP}+\(?{_SEP}*equivalent(?:s|es)?{_NW}(?:{_SEP}*\))?"
    rf"|\bor{_SEP}+\(?{_SEP}*similar(?:s|es)?{_NW}(?:{_SEP}*\))?"
    rf"|\bTBD\b(?![-_]\w)"                       # 排除 TBD-1234 ticket ref
    rf"|\bTBA\b(?![-_]\w)"
    rf"|\bto{_SEP}+be{_SEP}+(?:decided|determined)\b"
    rf"|\bif(?:{_SEP}+|{_SEP}*\({_SEP}*)needed{_NW}(?:{_SEP}*\))?"
    rf"|\bas(?:{_SEP}+|{_SEP}*\({_SEP}*)needed{_NW}(?:{_SEP}*\))?"
    rf"|\bplaceholders?\b",
    re.IGNORECASE,
)
```

**False-positive guards**:
- `TBD-1234` / `TBA-1234` ticket reference 不触发（negative lookahead `(?![-_]\w)`）
- `if-statement` / `or-pattern` 不触发（第二个词不在 phrase list）
- `ifneeded` / `asneeded` 要求至少一个 separator 或左括号

**Hypothesis fuzz**: `tests/unit/schemas/test_soft_language_fuzz.py` 每条 canonical phrase 跑 ~500 example 在 CI ~3-4s 内。Strategy 在 9 个 canonical phrase 上随机插入分隔符 + 复数 + 括号 mutation。

**Live evidence**: schema 始终激活。6 case × 2.5 iter = 12.5 spec versions, 0 hit。

**Boundary**: 仍以 phrase-list 为基础 — 同义短语 (e.g. "or alike", "perhaps later") 不在列表内。

---

### F3 — A3 BLOCKING escalation (pydantic field_validator)

**Designed to**: 强制 "≥3 选项不该埋 self_concerns 应升级 BlockingDecision"。在 `Concern.evidence_gap` field 上加 pydantic `@field_validator` 检测多选项语言 (英文 + 中文)，命中则 reject 并要求改成 `Spec.needs_clarification` (BlockingDecision)。

**Implementation**:
- 检测器: `devloop/spec_phase/schemas/spec.py:detect_underescalated_concern` (lines 243-293)。3 类 regex pattern:
  - 英文: `r"\b(?P<n>\d+|three|four|...|several|multiple|N)\s+(option|alternative|approach|...)s?\b"` (要求 n ≥ 3)
  - 中文: `r"(?P<n>\d+|三|四|...|几|多|若干)\s*(种|个|项|条)?\s*(选项|备选|方案|候选|...)"`
  - Alt form: `r"\boption(?:s)?\s+\d+[\s,]+(?:and\s+)?\d+[\s,]+(?:and\s+)?\d+\b"`
- Validator: `Concern._no_underescalation` (lines 398-409) 抛 ValueError 带 actionable fix。
- Higher-level scan: `devloop/spec_phase/validators/escalation.py:find_underescalated_concerns` — 给 orchestrator 用，spec 级遍历每个 `self_concerns[i]` 报 `EscalationProblem`。

**False-positive guards**:
- "Option to" (preposition) 不匹配（要求 plural with count）
- "for several reasons" 不匹配（reasons 不在 keyword set）
- "two options" 不匹配（n 必须 ≥ 3）

**Live evidence**: schema 始终激活。case-1 NEW v1 `EXEC-NEW-H-001` 类型 (3 hydration shape 藏 self_concerns) 是 F3 motivating case — F3 关闭这类 silent bypass。

**Boundary**: 仍是 detection 而非语义理解 — writer 把 3 个 option 用纯 prose 描述 (e.g. "我们可以走 SQL view，或者用 service layer 包一层，或者改 ORM 模型") 而不用 'options'/'alternatives'/'方案' 等触发词时 F3 不报。

---

### F4 — Sub-agent strict retry (halt-and-loud)

**Designed to**: 5 attempts，exponential backoff `[2, 5, 15, 30, 60]s`，最终失败 raise `SubAgentFailedError` (NEVER silent skip)。关闭 "sub-agent fail → 静默 None → 后续 stage 拿到 garbage" 失败模式。

**Implementation**: `devloop/llm/retry.py` (100% covered). `retry_with_backoff(call, max_attempts=5, backoff_s=DEFAULT_BACKOFF_S, ...)`. 关键不变量: 要么返回值要么 raise — 没有第三条 "silently None" 路径。`SubAgentFailedError._format_message` 含每次 attempt 的 error_type + waited_s。

**When fires**:
- ✅ Transient exception 在 `retryable_exceptions` tuple 里 → 等 backoff 再试
- ✅ `is_retryable_result` callback 返回 True → 当失败重试
- ✅ 全部 attempts exhausted → log ERROR + raise SubAgentFailedError(attempts, last_exception)

**Does NOT false-fire when**:
- ✅ 非 retryable exception 立刻 propagate (不重试)
- ✅ 第一次成功直接返回

**Live evidence**: infrastructure ready, 在 `call_strict_json` / `call_react_with_tools` 中被 LLM gateway 调用。

**Boundary**:
- Backoff schedule 是 hard-coded default — 调用方可传 custom 但通常不传。
- 5 attempts × backoff sum (2+5+15+30+60 = 112s) 是 worst-case waiting 上限。如果 model 真挂了一段时间，最多额外延迟 ~2 min 再 halt。

---

## 4 个已知的设计改进 (future work, 不是 bug)

These are **design-level improvements** documented across STRICT_AUDIT_REPORT.md:170-175 and FINDINGS.md — they don't block production but should be on the next sprint backlog:

### 1. ScopeType literal 扩展

**Where**: `devloop/spec_phase/schemas/common.py:48`

**Current**: `ScopeType` only allows `backend/frontend/data_model/api/infra/ui/test/docs/security/auth/external_integration/performance/payment`.

**Gap**: case-5 (cross-domain feature) has `intent.scope=['scheduler','event_bus','i18n','multitenant']` which fails Stage 3 perspective select. Real features touching cron / eventing / locale / tenancy can't be typed correctly — forces writer to flatten everything to 'backend'.

**Fix**: extend ScopeType with `scheduler / event_bus / i18n / multitenant / observability / migration`.

### 2. PerspectiveType 扩展

**Where**: `devloop/spec_phase/schemas/common.py:49`

**Current**: 7 perspectives (`data/api/ui/test/history/security/performance`).

**Gap**: case-5 是 cron-driven multi-tenant work，缺 dedicated `scheduler` / `multitenant` perspective。`data + api + test` 覆盖大部分但 timing / idempotency / CAS / tenant isolation 关切不会被独立 surface。

**Fix**: add `scheduler / multitenant` to PerspectiveType + 配套 prompt 模板。

### 3. A1 per-axis regression detection

**Where**: `devloop/spec_phase/regression_guard.py:32-33` (currently only `critical_plus_high`)

**Current**: A1 看的是 TOTAL critical+high, 不细分到 axis。

**Gap**: case-5 v1→v2 总体 -46% C+H 但 completeness axis 退步 (0/0/0 → 1/1/1)。架构整体改善遮蔽了单 axis 退化，A1 沉默 (FINDINGS.md:39-43, Finding 4)。

**Fix**: 给 `IterationDelta` 加 `delta_by_axis: dict[ReviewerType, int]` + alert 任意 axis +≥ 2 critical+high 即使总体改善。

### 4. Reviewer verdict format 强制

**Where**: `devloop/spec_phase/agents/reviewers/stage.py:194-216` (regex-based `_extract_verdict`)

**Current**: Reviewer 用 free-form text 结尾 `VERDICT: pass | fail | needs_refine`; missing → default `needs_refine`.

**Gap**: case-5 v1 的 consistency / executability reviewer 用了非标准 verdict 格式 (FINDINGS.md:24)，解析脆弱。

**Fix**: prompt 强制 `## VERDICT\n<verdict>` block + Pydantic-validated 输出结构, fall back 现有 regex 仅做兼容。

---

## 引用与交叉链接

- 端到端证据 + per-case 收敛: `specs/CROSS_CASE_FINAL_REPORT.md` + `specs/case{2,3,4,5}-*/ITERATIVE_IMPROVEMENT_REPORT.md`
- Live activation gap closure: `specs/GAP_CLOSURE_REPORT.md` + `specs/GAP-{B2,C2}-live-20260620/`
- v1 → vN 收敛报告: `specs/ITERATIVE_IMPROVEMENT_REPORT.md`
- 详细 boundary 测试: `tests/unit/{schemas,validators,agents}/test_*_adversarial.py`
- Hypothesis fuzz: `tests/unit/schemas/test_soft_language_fuzz.py`
- 完整 audit (4458 lines covered / 79.84%): `pytest --cov=devloop --cov-report=term-missing`
