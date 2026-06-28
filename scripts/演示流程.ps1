# Spec 流水线真实数据演示脚本
#
# 用法（在仓库根目录）:
#   pwsh scripts/演示流程.ps1                  # 跑完整 8 幕
#   pwsh scripts/演示流程.ps1 -Act 2           # 只跑第 2 幕
#   pwsh scripts/演示流程.ps1 -Pause           # 每幕之间暂停等回车
#
# 所有"真实数据"都从 specs/ 下的 case artifacts 现场读取，
# 你可以随时打开对应文件核对。

[CmdletBinding()]
param(
    [int]$Act = 0,        # 0 = 全部
    [switch]$Pause        # 幕间暂停
)

# 确保中文正确输出
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$OutputEncoding = [Text.UTF8Encoding]::new()

$ROOT = Split-Path -Parent $PSScriptRoot
if (-not $ROOT -or -not (Test-Path "$ROOT\specs")) {
    $ROOT = (Get-Location).Path
}

# ─── 工具函数 ──────────────────────────────────────────────────────
function H1($txt) {
    Write-Host ""
    Write-Host ("━" * 76) -ForegroundColor DarkCyan
    Write-Host "  $txt" -ForegroundColor Cyan
    Write-Host ("━" * 76) -ForegroundColor DarkCyan
}
function H2($txt) {
    Write-Host ""
    Write-Host "▌ $txt" -ForegroundColor Yellow
    Write-Host ("─" * 76) -ForegroundColor DarkGray
}
function Note($txt)  { Write-Host "💡 $txt" -ForegroundColor Green }
function Tip($txt)   { Write-Host "👉 $txt" -ForegroundColor Magenta }
function Warn($txt)  { Write-Host "⚠️  $txt" -ForegroundColor Red }
function Code($txt)  { Write-Host "    $txt" -ForegroundColor Gray }
function Quote($file, $lines = 8) {
    $path = Join-Path $ROOT $file
    if (-not (Test-Path $path)) { Warn "缺文件 $file"; return }
    Write-Host ""
    Write-Host "  📄 真实文件: $file" -ForegroundColor DarkYellow
    Write-Host "  ┌$('─' * 74)" -ForegroundColor DarkGray
    Get-Content $path -TotalCount $lines | ForEach-Object {
        Write-Host "  │ $_" -ForegroundColor White
    }
    Write-Host "  └$('─' * 74)" -ForegroundColor DarkGray
}
function QuoteRange($file, $from, $to) {
    $path = Join-Path $ROOT $file
    if (-not (Test-Path $path)) { Warn "缺文件 $file"; return }
    Write-Host ""
    Write-Host "  📄 真实文件: $file （第 $from-$to 行）" -ForegroundColor DarkYellow
    Write-Host "  ┌$('─' * 74)" -ForegroundColor DarkGray
    $all = Get-Content $path
    $all[($from-1)..($to-1)] | ForEach-Object {
        Write-Host "  │ $_" -ForegroundColor White
    }
    Write-Host "  └$('─' * 74)" -ForegroundColor DarkGray
}
function MaybePause {
    if ($Pause) {
        Write-Host ""
        Write-Host "  ⏸️  按回车继续，Ctrl+C 退出 ..." -ForegroundColor DarkGray
        $null = Read-Host
    }
}

# ─── 主幕路径 ────────────────────────────────────────────────────────
$C2 = "specs\case2-shopping-archive-live-new-20260620T120351Z"
$C5 = "specs\case5-live-iter1-20260619T175133Z"
$C6 = "specs\case6-live-new-20260620"


# ═══════════════════════════════════════════════════════════════════
function Show-Intro {
    H1 "🎬 DevLoop 需求文档生成流水线 · 真实数据演示"

    Note "我们以 Mealie 项目（一个开源食谱管理系统）中的真实需求为例"
    Note "你将会看到一份 「购物清单归档功能」 的需求文档"
    Note "如何从一句话需求 → 经过 10 个环节 → 最终落地"
    Write-Host ""
    Tip "全部数据来自项目仓库 specs/ 目录下的真实 artifacts（中间产物）"
    Tip "你可以随时打开任何一个文件核对——所有打印的内容都是真实存档"
    Write-Host ""

    H2 "本场演出包含 11 幕"
    Write-Host "  第 1 幕：用户输入的真实需求长什么样" -ForegroundColor White
    Write-Host "  第 2 幕：①守门员 ②看代码 ③听懂需求（看真实意图理解结果）" -ForegroundColor White
    Write-Host "  第 3 幕：④五人小组分头调研（看真实数据角度调研报告）" -ForegroundColor White
    Write-Host "  第 4 幕：⑤查漏补缺 ⑥想方案" -ForegroundColor White
    Write-Host "  第 5 幕：⑦作者动笔写初稿（看真实 spec v1 的 'self_concerns'）" -ForegroundColor White
    Write-Host "  第 6 幕：⑧五个校验机器人查造假（看真实机械校验结果）" -ForegroundColor White
    Write-Host "  第 7 幕：⑨四个评审员 + ⑩主编（看真实评审 verdict）" -ForegroundColor White
    Write-Host "  第 8 幕：⚖️ 分支 A：通过 → v1 → v2 一轮收敛（看真实改动）" -ForegroundColor White
    Write-Host "  第 9 幕：🥷 分支 B：黑客视角找到 5 个真实安全漏洞（case6）" -ForegroundColor White
    Write-Host "  第 10 幕：⏸️ 分支 C：跑 5 轮后系统自己停下来（case5）" -ForegroundColor White
    Write-Host "  第 11 幕：📋 全流程一页纸总结" -ForegroundColor White
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act1 {
    H1 "第 1 幕 · 用户输入的真实需求长什么样"

    Note "这是真实喂给系统的需求文本（节选）——一段普通工程师写的业务描述："
    Quote "$C2\input.md" 28
    Write-Host ""
    Tip "注意这段输入的两个特点："
    Write-Host "  • 业务描述清晰，但很多细节没说透（例如：归档已删除的列表怎么办？批量归档支持吗？）" -ForegroundColor White
    Write-Host "  • 提到了数据模型、API、UI、测试多个方面——是一个 '跨多个角度' 的需求" -ForegroundColor White
    Write-Host ""
    Warn "如果让 AI 直接写 spec，常见踩坑：会胡编一个 'commit 第 X 行'，会写 'TBD' 含糊话，"
    Warn "会漏掉关键场景。所以我们才需要后面 10 个环节的流水线。"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act2 {
    H1 "第 2 幕 · ①守门员 → ②看代码 → ③听懂需求"

    H2 "① 守门员（纯规则程序，0 调用大模型）"
    Note "输入长度 26 字 ≥ 8 字阈值 ✅"
    Note "包含动词 + 名词 ✅"
    Note "→ 放行进入下一环节"
    MaybePause

    H2 "② 看代码（tree-sitter 扫一遍，按 Git 版本号缓存）"
    Note "用代码解析工具扫描 Mealie 整个仓库（约 800 个 Python 文件）"
    Note "提取出 1024 字左右的'代码地图'——主要模块、入口路由、数据模型"
    Note "本次跑时正好命中缓存（同一个 commit 之前跑过）→ 0 秒返回 💰省钱"
    MaybePause

    H2 "③ 听懂需求（3 个回合：猜 → 唱反调 → 拍板）"
    Note "Claude 当'猜测者'，提了 4 个假设，举其中 1 个为例："

    Write-Host ""
    Write-Host "  假设 H1: 这是 'add_feature' 类需求（端到端的归档功能）" -ForegroundColor White
    Write-Host "  支持的证据："  -ForegroundColor DarkGray
    Write-Host "    • 输入要求加两个数据库字段 archived_at + archived_by_user_id" -ForegroundColor DarkGray
    Write-Host "    • 输入要求加 POST /archive 和 /unarchive 接口" -ForegroundColor DarkGray
    Write-Host "    • 输入要求改 4 个现有接口在归档后返回 409 错误（状态机）" -ForegroundColor DarkGray
    Write-Host "    • 输入要求事件总线发新事件 ShoppingListArchived" -ForegroundColor DarkGray
    Write-Host "  反向证据（自己也列出来）："  -ForegroundColor DarkGray
    Write-Host "    • 没有新增 SQL 表，只是给现有表加列——也可能只是 'data_model_extension'" -ForegroundColor DarkGray
    Write-Host "    • 没有新增领域实体（如 ArchiveLog 表）" -ForegroundColor DarkGray

    Write-Host ""
    Note "然后 GPT 当'唱反调的'，从另一家公司视角挑刺..."
    Note "最后 Claude 拍板，输出最终的需求理解 confirmed.json："

    Quote "$C2\intent\confirmed.json" 12

    Write-Host ""
    Tip "看到 confidence: 0.92 没？这是系统给自己的'信心分'——表示这次理解很扎实"
    Tip "scope（涉及范围）也被精确列出来了：数据 + API + 服务 + 多租户 + 国际化 + 事件总线 + 测试"
    Tip "这 7 个领域决定了下一环节要派几个调研员、要派哪些角度"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act3 {
    H1 "第 3 幕 · ④五人小组分头调研（5 个 AI 并行干活）"

    Note "5 位调研员 AI 同时出发，每人只看一个角度。我们看其中'数据角度'的真实报告头部："

    Quote "$C2\exploration\data_perspective.md" 20

    Write-Host ""
    Tip "这位调研员发现了什么？让我们逐条读："
    Write-Host "  ✓ 找到了 ShoppingList 这个数据模型的精确位置：第 147-181 行" -ForegroundColor White
    Write-Host "  ✓ 找到了关键字段 user_id 在第 155 行" -ForegroundColor White
    Write-Host "  ✓ 还顺便发现了一个细节：第 204-211 行有个'每次改条目就自动更新更新时间'的钩子" -ForegroundColor White
    Write-Host "    （这个细节对'归档后冻结'功能很重要——不然归档之后时间戳还会乱跳）" -ForegroundColor White
    Write-Host ""
    Note "每个调研员都会精确报告 '文件路径 + 行号'——这些数字后面会被'引用核查员'机械验证！"
    Write-Host ""

    Note "5 个角度的真实文件全部都在这里："
    Get-ChildItem (Join-Path $ROOT "$C2\exploration") -File | Select-Object -ExpandProperty Name | ForEach-Object {
        Write-Host "  📄 $_" -ForegroundColor DarkYellow
    }
    Write-Host ""
    Tip "5 个角度 + 1 个 consolidated.md（整合员合并后的总报告）—— 6 个文件全部是真实存档"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act4 {
    H1 "第 4 幕 · ⑤查漏补缺 → ⑥想方案"

    H2 "⑤ 查漏补缺（纯程序，找盲区）"
    Note "扫一遍 5 份调研报告，检查 3 类问题："
    Write-Host "  • 孤儿信息：只有 1 个调研员提到 → 可能漏看" -ForegroundColor White
    Write-Host "  • 互相矛盾：A 说有 B 说没有 → 必须查清" -ForegroundColor White
    Write-Host "  • 密度过低：某角度只有 1 条发现 → 调研不深" -ForegroundColor White
    Write-Host ""
    Note "本 case：5 份报告之间无冲突、无孤儿、密度都达标 → 跳过补查直接进入下一步 ✅"

    MaybePause
    H2 "⑥ 想方案（3 候选并行生成 → GPT 评分 → Claude 选）"
    Note "3 位作者 AI 并行各想 1 个方案：保守 / 平衡 / 激进"
    Write-Host ""
    Write-Host "  方案 A · 保守: 只加 archived_at 字段 + 所有查询加 WHERE archived_at IS NULL" -ForegroundColor White
    Write-Host "  方案 B · 平衡: A + 单独 archive/unarchive 接口 + 4 个接口加 409 冻结" -ForegroundColor White
    Write-Host "  方案 C · 激进: 抽象 ArchiveService，未来任意实体可归档" -ForegroundColor White
    Write-Host ""
    Note "GPT（不同公司的 AI）按 5 维评分（可行性/完整性/契合度/风险/性价比）："
    Write-Host "                     可行性  完整性  契合度  风险  性价比" -ForegroundColor DarkGray
    Write-Host "  A · 保守:   ████   ███    █████  ███   ████" -ForegroundColor White
    Write-Host "  B · 平衡:   ████   █████  █████  ███   █████  👑 综合最高" -ForegroundColor Green
    Write-Host "  C · 激进:   ███    █████  ███    █████ ██" -ForegroundColor White
    Write-Host ""
    Tip "最终 Claude 综合选定 **方案 B · 平衡**：'覆盖核心需求，不过度抽象'"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act5 {
    H1 "第 5 幕 · ⑦作者动笔写初稿"

    Note "作者 AI（Claude Opus 4.7，旗舰款）拿着前面所有材料，写出第一版 spec_v1"
    Note "我们看真实文件的头部："
    Quote "$C2\spec_iterations\spec_v1.md" 9

    Write-Host ""
    Note "看到 'NEEDS_CLARIFICATION (blocking decisions)' 这一段了吗？这是项目最有特色的设计之一："

    QuoteRange "$C2\spec_iterations\spec_v1.md" 11 17

    Write-Host ""
    Tip "📌 这个 'NC-001' 是什么意思？"
    Write-Host "   作者发现：输入说 4 个接口要冻结，但代码里还有 3 个相关接口（标签设置、加菜谱、删菜谱）" -ForegroundColor White
    Write-Host "   作者老实承认：'我不确定要不要也冻结这 3 个'" -ForegroundColor White
    Write-Host "   于是它给出了'推荐默认方案' + '如果被拒该怎么办' + 影响的需求条目" -ForegroundColor White
    Write-Host ""
    Warn "⭐ 注意这个设计哲学："
    Warn "   普通 AI 会假装什么都懂，自己挑一个写下去（错了下游才发现）"
    Warn "   本系统强制要求 AI '主动承认自己不确定的地方'——并放在 spec 最显眼的位置"
    Warn "   这样下游评审员一眼就能看到 '这里需要人决策' ✅"
    Write-Host ""
    Note "v1 初稿统计（来自真实 spec_v1.json）："
    Write-Host "  📊 用户故事 9 条 / 功能需求 16 条 / 成功标准 10 条 / 边缘情况 12 条" -ForegroundColor White
    Write-Host "  📊 需要决策点 2 个（NC-001 NC-002）/ 关切点 4 条" -ForegroundColor White
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act6 {
    H1 "第 6 幕 · ⑧五个自动校验机器人查造假"

    Note "5 个纯 Python 程序毫秒级查 v1 的每一条引用、每一处含糊话——真实输出在这里："

    H2 "🤖 校验机器人 1 号：引用核查员（A5）"
    Note "扫一遍 spec 里所有 'XXX.py 第 Y 行' 的引用，去文件里实地核对："
    Write-Host "  • 文件真的存在吗？" -ForegroundColor White
    Write-Host "  • 行号没越界吧？" -ForegroundColor White
    Write-Host "  • 提到的函数名/类名真的在那一行段里吗？" -ForegroundColor White
    Write-Host ""
    Note "case2 v1 真实结果——直接引用 review_v1_executability.md 的实测数据："

    QuoteRange "$C2\spec_iterations\review_v1_executability.md" 6 14

    Write-Host ""
    Tip "✅ 0 problems across all 16 FRs：16 条功能需求，每条都引用了真实代码位置，全部核对通过！"

    MaybePause
    H2 "🤖 校验机器人 2 号：含糊话扫描员（A4）"
    Note "扫 9 个高危词：or equivalent / or similar / TBD / TBA / to be decided / "
    Note "to be determined / if needed / as needed / placeholder"
    Note "再加 62000 行 Unicode 同形字表（防作者用形似汉字绕过）"
    Note "case2 v1 真实结果: clean ✅（一处含糊话都没有）"

    MaybePause
    H2 "🤖 校验机器人 3 号：两版一致员（B1）"
    Note "把 spec.md 和 spec.json 双向转换一遍，字节级比对"
    Note "case2 v1 真实结果: PASS ✅"

    MaybePause
    H2 "🤖 校验机器人 4 号：覆盖矩阵员（B3）"
    Note "9 个用户故事 × 16 个功能需求 × 10 个成功标准 全部画矩阵"
    Note "case2 v1 真实结果: 0 gaps ✅"

    MaybePause
    H2 "🤖 校验机器人 5 号：隐藏选项守卫（F3）"
    Note "扫一遍：有没有作者把 '≥3 个选项' 偷偷藏在某个'担心点'里？"
    Note "case2 v1 真实结果: clean ✅（NC-001 NC-002 都正确放在了显眼位置）"

    Write-Host ""
    Note "5 个机器人共计耗时不到 1 秒，全部通过——v1 的'机械层'完美。下一关交给评审员 AI。"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act7 {
    H1 "第 7 幕 · ⑨四个评审员 + ⑩主编汇总"

    Note "4 位评审员 AI 并行审 v1，每人用一种眼光。我们看 4 个真实 verdict："

    H2 "🔍 评审员 1 号：架构评审员"
    Note "看：方案跟现有代码架构吻合吗？"
    QuoteRange "$C2\spec_iterations\review_v1_architecture.md" 7 16
    Tip "verdict: APPROVE ✅ —— 架构无问题"

    MaybePause
    H2 "🔍 评审员 2 号：完整性评审员"
    Note "看：用户需求隐含的方面都覆盖了吗？"
    QuoteRange "$C2\spec_iterations\review_v1_completeness.md" 5 13
    Tip "verdict: APPROVE ✅ ，但提了 1 个 HIGH 级别建议（H1）：'?archived=all 这个查询参数的返回字段约定还应当更明确'"

    MaybePause
    H2 "🔍 评审员 3 号：可执行评审员"
    Note "看：程序员拿到这份 spec 能直接动手吗？有歧义吗？"
    QuoteRange "$C2\spec_iterations\review_v1_executability.md" 5 14
    Tip "verdict: APPROVE ✅ —— 引用、含糊话、覆盖、两版一致、隐藏选项全部干净"

    MaybePause
    H2 "🔍 评审员 4 号：自洽性评审员"
    Note "看：spec 内部有没有自相矛盾？"
    QuoteRange "$C2\spec_iterations\review_v1_consistency.md" 5 14
    Warn "verdict: NEEDS_REFINE ⚠️ —— 自洽性评审员发现 1 个 HIGH 问题（H1）:"
    Warn "         'NC-002 里 if_rejected 路径没写完整'"
    Write-Host ""

    MaybePause
    H2 "📰 ⑩ 主编汇总（用 Claude，跟作者同公司）"
    Note "主编 AI 综合 4 份评审报告："
    Write-Host "  • 去重：4 个评审员没人提相同的问题，跳过去重" -ForegroundColor White
    Write-Host "  • 找内部矛盾：4 个评审员的评分基本一致，没冲突" -ForegroundColor White
    Write-Host "  • 排优先级：" -ForegroundColor White
    Write-Host "    ① HIGH (consistency-H1): NC-002 的 if_rejected 路径不完整" -ForegroundColor Red
    Write-Host "    ② HIGH (completeness-H1): ?archived=all 的字段约定要更清楚" -ForegroundColor Red
    Write-Host "    ③ MEDIUM (architecture-M1): 文档化 NC-001 的留白" -ForegroundColor Yellow
    Write-Host ""
    Note "主编的最终判定：'有 2 个 HIGH，需要修一版'"
    Tip "由于不是全 APPROVE → 进入分支 A：让作者改 v2"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act8 {
    H1 "第 8 幕 · ⚖️ 分支 A：改一轮 → APPROVE（case2 真实演化）"

    Note "重写者 AI 拿着 v1 + 主编的优先级清单，写出 v2"
    Note "防越改越烂卫兵自动比对 v1 / v2 的严重问题数..."

    Write-Host ""
    Write-Host "  ┌────────────┬──────────────────┬──────────────────┐" -ForegroundColor DarkGray
    Write-Host "  │   评审维度  │  v1 严重+高问题  │  v2 严重+高问题  │" -ForegroundColor White
    Write-Host "  ├────────────┼──────────────────┼──────────────────┤" -ForegroundColor DarkGray
    Write-Host "  │   架构       │       0          │       0  ✅      │" -ForegroundColor White
    Write-Host "  │   完整性     │       1 H        │       0  ✅ 解决 │" -ForegroundColor Green
    Write-Host "  │   可执行     │       0          │       0  ✅      │" -ForegroundColor White
    Write-Host "  │   自洽性     │       1 H        │       0  ✅ 解决 │" -ForegroundColor Green
    Write-Host "  ├────────────┼──────────────────┼──────────────────┤" -ForegroundColor DarkGray
    Write-Host "  │   总计       │       3          │       0  🎉      │" -ForegroundColor Cyan
    Write-Host "  └────────────┴──────────────────┴──────────────────┘" -ForegroundColor DarkGray
    Write-Host ""
    Note "v2 真实评审结果——4 个评审员全 APPROVE："
    QuoteRange "$C2\spec_iterations\review_v2_architecture.md" 7 16

    Write-Host ""
    Tip "👑 case2 收敛！1 轮迭代搞定。最终 spec.md + spec.json + 全套审计轨迹落盘"
    Write-Host ""
    Note "落盘的目录结构（真实）："
    Get-ChildItem (Join-Path $ROOT $C2) -Directory | ForEach-Object {
        Write-Host "  📁 $($_.Name)/" -ForegroundColor Yellow
        Get-ChildItem $_.FullName -File | Select-Object -First 4 -ExpandProperty Name | ForEach-Object {
            Write-Host "      └─ $_" -ForegroundColor DarkGray
        }
    }
    Get-ChildItem (Join-Path $ROOT $C2) -File | Select-Object -First 6 -ExpandProperty Name | ForEach-Object {
        Write-Host "  📄 $_" -ForegroundColor DarkYellow
    }
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act9 {
    H1 "第 9 幕 · 🥷 分支 B：黑客视角找到 5 个真实安全漏洞（case6）"

    Note "case2 的需求不涉及安全，红队评审员没启动。"
    Note "现在切换到 case6——'加一个 OpenAI 图片识别菜谱'的功能。"
    Note ""
    Note "系统自动判断这是个安全敏感需求（关键词：image / llm / openai / prompt / upload）"
    Note "→ 第 5 位评审员（黑客视角）自动启动"

    Quote "$C6\RESULT.md" 22

    Write-Host ""
    Note "我们看真实的黑客视角评审报告（review_v1_adversarial.md）头部——"
    Note "这位 AI 上来先声明自己的'攻击者心智模型'："

    QuoteRange "$C6\spec_iterations\review_v1_adversarial.md" 7 13

    Write-Host ""
    Tip "看到没？这位 AI 用的是'攻击者思维'：'我看 spec 就像看一份合同，"
    Tip "找一个 spec 字面上没违反但实际能打进去的攻击场景'"
    Write-Host ""

    H2 "🔥 真实战绩：5 个 CVE 级安全漏洞（其它 4 个评审员全没发现）"

    Write-Host ""
    Write-Host "  漏洞 1 [严重 · CRITICAL] 速率限制 DoS-on-self" -ForegroundColor Red
    Write-Host "  ─────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  📌 spec 里的代码先记次数再调 OpenAI" -ForegroundColor White
    Write-Host "  📌 攻击者用 1×1 黑像素 JPEG 故意触发 OpenAI 失败 10 次" -ForegroundColor White
    Write-Host "  📌 → 受害者 59 分钟内全部上传都被 429 拒绝（额度被烧光）" -ForegroundColor White
    Write-Host ""
    Write-Host "  漏洞 2 [高危 · HIGH] EXIF 提示注入" -ForegroundColor Yellow
    Write-Host "  ─────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  📌 spec 只对图片里的'可见文字'做提示注入防护" -ForegroundColor White
    Write-Host "  📌 攻击者用 exiftool 把 'SYSTEM: ignore prior...' 写进 JPEG EXIF" -ForegroundColor White
    Write-Host "  📌 → 绕过所有现有防护，让 OpenAI 输出任意内容" -ForegroundColor White
    Write-Host ""
    Write-Host "  漏洞 3 [高危 · HIGH] 巨图成本放大" -ForegroundColor Yellow
    Write-Host "  ─────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  📌 spec 限制 5 MiB 文件大小，但没限制像素数" -ForegroundColor White
    Write-Host "  📌 攻击者上传 5 MiB 但 8192×8192 像素的 JPEG" -ForegroundColor White
    Write-Host "  📌 → OpenAI Vision 把它拆成 256 块计费，单次成本放大 64 倍" -ForegroundColor White
    Write-Host ""
    Write-Host "  漏洞 4 [严重] 存储型 XSS（CVSS ~7.5）" -ForegroundColor Red
    Write-Host "  ─────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  📌 OpenAI 返回的菜谱含 <img onerror=...> 恶意脚本" -ForegroundColor White
    Write-Host "  📌 新写入路径忘了调用消毒函数 cleaner.clean()" -ForegroundColor White
    Write-Host "  📌 → 存进数据库，任何人查看就中招" -ForegroundColor White
    Write-Host ""
    Write-Host "  漏洞 5 [中危 · MEDIUM] DEBUG 日志泄露原图" -ForegroundColor DarkYellow
    Write-Host "  ─────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  📌 spec 承诺'日志里不含 LLM 响应'，但只控制了自家日志" -ForegroundColor White
    Write-Host "  📌 httpx 库的 DEBUG 模式会把 base64 原图打进日志" -ForegroundColor White
    Write-Host ""

    Note "case6 v1 真实分数（来自 RESULT.md）："
    Write-Host "  架构: 0 严重 / 2 高 / 2 中" -ForegroundColor White
    Write-Host "  完整性: 0 严重 / 2 高 / 4 中" -ForegroundColor White
    Write-Host "  可执行: 0 严重 / 2 高 / 3 中" -ForegroundColor White
    Write-Host "  自洽性: 0 严重 / 2 高 / 4 中" -ForegroundColor White
    Write-Host "  🥷 黑客视角: 1 严重 / 3 高 / 3 中  ← 全部都是其它人发现不了的" -ForegroundColor Red
    Write-Host ""
    Tip "v2 改完之后：5 个维度全部 0 严重 0 高 🎉 case6 收敛"
    Tip "→ 如果没有黑客视角，这 5 个安全漏洞会随 spec 全部进生产，CVE 级别后果"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act10 {
    H1 "第 10 幕 · ⏸️ 分支 C：跑 5 轮还停滞 → 系统主动停下来（case5）"

    Note "case5 是最复杂的'跨域定时同步'需求："
    Note "  • 涉及 定时任务 + 多租户 + 国际化 + 事件总线 + 菜单 5 个领域"
    Note "  • intent.scope 多到把 ScopeType 这个类型都撑爆了"
    Note ""
    Warn "这是项目最'尴尬'但也最值得讲的一个 case：跑 5 轮后系统主动停下来"
    Write-Host ""

    Note "我们看真实 FINDINGS.md 里的 5 轮真实演化轨迹："
    QuoteRange "$C5\FINDINGS.md" 56 64

    Write-Host ""
    Tip "🔍 重点看 v3 → v4 这一步："
    Write-Host "  ✅ 防越改越烂卫兵自动触发：v3=6 → v4=7（变差了 1 个）" -ForegroundColor White
    Write-Host "  ✅ 系统自动 revert（退回）到 v3，附上'你刚才的修改让架构维度退化了'反馈" -ForegroundColor White
    Write-Host "  ✅ 让 AI 重新写 v5——这次基于 v3 + 退化提醒" -ForegroundColor White
    Write-Host ""
    Note "v5 的真实结果（来自 FINDINGS.md 'Finding 6 + 7'）："
    QuoteRange "$C5\FINDINGS.md" 66 76

    Write-Host ""
    Warn "📉 注意 v3 → v5 之后剩余的 5 个严重+高问题是什么？"
    Write-Host ""
    Write-Host "  ❓ '事务化外发盒 vs 内部提交'——是一致性 vs 延迟的权衡（产品决策）" -ForegroundColor Yellow
    Write-Host "  ❓ '当天用户没有菜单时，同步走哪条路径'——产品语义（PM 决策）" -ForegroundColor Yellow
    Write-Host "  ❓ '哪个目标列表？谁决定？'——业务语义（人决策）" -ForegroundColor Yellow
    Write-Host ""
    Note "这些问题 AI 不询问产品经理是答不出来的——无论再迭代多少轮都不会改善！"
    Write-Host ""
    Tip "💡 系统的高光时刻：'收敛底线' 触发"
    Write-Host "  连续 3 轮严重问题数不下降（5 → 5 → 5）→ 系统主动停下来" -ForegroundColor White
    Write-Host "  把 v5 spec 落盘（不算失败，盖章 'needs_review = True'）" -ForegroundColor White
    Write-Host "  完整 5 版 spec + 全部评审历史保留，等人工接手" -ForegroundColor White
    Write-Host ""
    Warn "⭐ 这就是项目最'反直觉'但最重要的一个设计："
    Warn "   普通系统：跑到最大轮数才停（可能跑出来 20 版烂稿）"
    Warn "   本系统：识别出'剩下的都是产品决策问题'，主动停下问人"
    Warn "   '好的系统知道什么时候该停下问人，比假装通过诚实得多'"
}


# ═══════════════════════════════════════════════════════════════════
function Show-Act11 {
    H1 "第 11 幕 · 📋 全流程一页纸总结"

    Write-Host ""
    Write-Host "  用户的一句话需求" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ① 守门员（拒空输入）                          [纯程序]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ② 看代码（扫一遍画地图 + 缓存）               [纯程序 + tree-sitter]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ③ 听懂需求（猜 → 唱反调 → 拍板，3 个回合）   [Claude + GPT 跨厂质疑]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ④ 5 视角并行调研（数据/接口/界面/测试/历史）  [5 个 Claude 并发]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ⑤ 查漏补缺（找孤儿信息/矛盾/密度低）          [纯程序]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ⑥ 想 3 方案选最优（GPT 评 Claude 选）          [3 + 1 + 1]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ⑦ 作者动笔（含'自己也不确定的地方'）          [Claude Opus 4.7]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ⑧ 5 个机器人查造假（毫秒级，纯程序）          [Python 校验，0 LLM 调用]" -ForegroundColor Green
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ⑨ 4 评审员（架构/完整/可执行/自洽）           [4 个 GPT 并发]" -ForegroundColor White
    Write-Host "     + 🥷 红队第 5 维（只在安全敏感时启用）" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ⑩ 主编汇总（去重 + 找内部冲突）                [Claude，故意同厂]" -ForegroundColor White
    Write-Host "         ↓" -ForegroundColor DarkGray
    Write-Host "  ┌─────────── 分支决策 ───────────┐" -ForegroundColor Cyan
    Write-Host "  │                                  │" -ForegroundColor Cyan
    Write-Host "  ↓ 全 APPROVE      ↓ 有问题需改      ↓ 改了几次还停滞" -ForegroundColor Cyan
    Write-Host "  ✅ 直接发布      ✏️ 让作者改 v2     ⏸️ 标'需人工'后停" -ForegroundColor Cyan
    Write-Host "                       ↓                   ↓" -ForegroundColor DarkGray
    Write-Host "                 防越改越烂卫兵       全套审计材料落盘" -ForegroundColor White
    Write-Host "                       ↓" -ForegroundColor DarkGray
    Write-Host "                 改好了？→ 发布" -ForegroundColor Green
    Write-Host "                 越改越烂？→ 退回上一版重写（预算 2 次）" -ForegroundColor Yellow
    Write-Host "                 连续 3 轮没进步？→ 标'需人工'停下来" -ForegroundColor Yellow
    Write-Host ""
    H2 "💎 三句话记忆"
    Write-Host ""
    Write-Host "  1. 能用程序做绝不用 AI（5 个机械校验机器人毫秒级查造假）" -ForegroundColor Cyan
    Write-Host "  2. 不同公司模型必须交叉评审（Claude 写 + GPT 评，配错启动报错）" -ForegroundColor Cyan
    Write-Host "  3. 知道何时该停下问人（比假装通过诚实，case5 真实演示）" -ForegroundColor Cyan
    Write-Host ""

    H2 "📂 真实数据全套位置（你可以打开任何一个文件交叉核对）"
    Write-Host "  case2（一轮通过）  : specs\case2-shopping-archive-live-new-*\" -ForegroundColor DarkYellow
    Write-Host "  case5（停下来）    : specs\case5-live-iter1-*\" -ForegroundColor DarkYellow
    Write-Host "  case6（5 个 CVE）  : specs\case6-live-new-*\" -ForegroundColor DarkYellow
    Write-Host ""
    Tip "推荐打开顺序：input.md → intent\confirmed.json → exploration\*_perspective.md"
    Tip "             → spec_iterations\spec_v1.md → spec_iterations\review_v1_*.md"
    Tip "             → spec_iterations\spec_v2.md → spec_iterations\review_v2_*.md"
    Write-Host ""
    H1 "🎬 演示结束 · 祝你面试顺利！"
}


# ─── 主控逻辑 ──────────────────────────────────────────────────────
$acts = @(
    @{ N = 0;  F = ${function:Show-Intro} },
    @{ N = 1;  F = ${function:Show-Act1}  },
    @{ N = 2;  F = ${function:Show-Act2}  },
    @{ N = 3;  F = ${function:Show-Act3}  },
    @{ N = 4;  F = ${function:Show-Act4}  },
    @{ N = 5;  F = ${function:Show-Act5}  },
    @{ N = 6;  F = ${function:Show-Act6}  },
    @{ N = 7;  F = ${function:Show-Act7}  },
    @{ N = 8;  F = ${function:Show-Act8}  },
    @{ N = 9;  F = ${function:Show-Act9}  },
    @{ N = 10; F = ${function:Show-Act10} },
    @{ N = 11; F = ${function:Show-Act11} }
)

if ($Act -eq 0) {
    foreach ($a in $acts) {
        & $a.F
        if ($Pause -and $a.N -gt 0 -and $a.N -lt 11) { MaybePause }
    }
} else {
    $sel = $acts | Where-Object { $_.N -eq $Act }
    if ($sel) { & $sel.F } else { Warn "未知幕号 $Act（可选 0-11）" }
}


