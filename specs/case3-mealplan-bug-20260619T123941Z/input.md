# Case 3 — Bug 修复全流程：Meal Plan → Shopping List 数量累加

> **难度**：中等 · **业务直观度**：⭐⭐⭐⭐⭐ · **预期改动**：~3-5 个文件

---

## Spec for DevLoop System

> **以下是直接喂给你的 DevLoop 系统的需求文本，复制此节即可。**

### Bug 报告

**产品场景**：用户在 mealie 的 meal plan 中安排周一晚餐"番茄炒蛋"，周三午餐也安排"番茄炒蛋"，然后点击"Add Meal Plan to Shopping List"将本周餐计划转为购物清单。

**预期行为**：shopping list 中"番茄"和"鸡蛋"的数量应该是单份食谱所需量的 **2 倍**（因为出现两次）。例如食谱要 2 个番茄，shopping list 应该出现 4 个番茄。

**实际行为**：shopping list 中要么只出现 1 份食材的量（合并错误，少算了一倍），要么出现两条独立的"番茄 2 个"+"番茄 2 个"行（未合并），具体取决于实现的哪一步出错。

### 任务要求

请按以下严格顺序完成：

#### 步骤 1：复现
- 在 `tests/integration_tests/` 下新增一个测试文件（如 `test_meal_plan_to_shopping_bug.py`）
- 测试场景：
  - 创建一个食谱 A，包含食材"番茄"(quantity=2, unit=个) 和"盐"(quantity=1, unit=小勺)
  - 创建本周 meal plan：周一 dinner = 食谱 A，周三 lunch = 食谱 A
  - 调用相应接口将 meal plan 添加到 shopping list
  - 断言 shopping list 中"番茄"的累计 quantity = 4（而非 2，也不是出现两行）
- 这个测试在修复前必须 **FAIL**

#### 步骤 2：根因定位
- 阅读 `mealie/services/household_services/shopping_lists.py`（约 22.7KB）
- 重点关注合并逻辑：通常在"add recipe ingredients to shopping list"路径上
- 写出根因分析（PR description 中），至少回答：
  - bug 在哪个函数？
  - 是因为合并 key 错误，还是因为 quantity 被覆盖而非累加？
  - 涉及哪些边界情况（不同 unit 应不应该合并？不同 food 但同名应不应该合并？）

#### 步骤 3：最小修复
- **只修改导致 bug 的最小代码范围**（理想 1-3 个函数，几十行）
- **不要重构周边代码**
- 修复后步骤 1 的测试必须 **PASS**

#### 步骤 4：回归测试
新增 4 组测试（在步骤 1 的测试文件中追加）：

| 测试名 | 场景 | 预期 |
|--------|------|------|
| `test_single_occurrence` | 食谱只出现 1 次 | 食材数量 = 食谱原量 |
| `test_multiple_occurrences_same_unit` | 同食谱出现 N 次，同 unit | 食材数量 = 原量 × N |
| `test_multiple_occurrences_different_units` | 同 food 不同 unit（如"番茄 2 个" + "番茄 100g"） | **不合并**，出现两行 |
| `test_different_food_same_name` | 不同 food_id 但 display name 相同 | **不合并**（按 food_id 区分） |

### 实现约束

- 不允许通过新增"开关 / 配置"来"绕开"bug — 必须是真正的修复
- 不允许全文 grep + sed 类的大范围改动
- 必须遵循 mealie 既有的 `RepositoryShoppingItem` / `ShoppingListItem` schema，不要新建并行实现

---

## 三环节考察点（评估用，不喂给系统）

| 环节 | 关注点 |
|------|--------|
| **Spec** | 是否把流程分四步立项（复现→根因→修复→回归）？是否要求 PR description 写根因分析？ |
| **Coding** | 修复是否真的最小？是否覆盖"同 food 不同 unit 不合并"边界？是否处理浮点精度？ |
| **CR** | 是否指出修复对已有 shopping list 编辑场景的影响？是否提出回归测试是否需要覆盖"recipe scale factor"场景？是否担心未来 unit conversion 引入新合并维度？ |

---

## 评估记录

| 维度 | 记录 |
|------|------|
| Spec 完整度（1-5） | |
| 是否成功复现 | yes / no |
| 根因定位准确度（1-5） | |
| 修复是否最小 | yes / no |
| 4 组回归测试是否全过 | __ / 4 |
| 多 agent CR 提出的有效问题数 | |
| 人工 CR 补充发现的问题数 | |
| 备注 | |

---

## 附录：Bug 注入 Patch（若真实代码无此 bug）

如果你在 baseline commit 上跑 plan 中的复现测试发现 mealie 当前并无此 bug，使用以下 patch 在自己的 fork 上人工注入一个等价 bug，确保 Case 3 流程可重复验证。

> **使用方法**：在 baseline commit 后，新建一个 `inject-bug` 分支，应用此 patch，再从 `inject-bug` 分支拉出 case-3 工作分支让 DevLoop 系统去修。

### Patch 示意（伪代码 — 实际行号需参照真实代码）

```diff
# File: mealie/services/household_services/shopping_lists.py
# Function: 负责把 recipe ingredient 添加到 shopping list 的合并逻辑
#
# 真实代码中合并 key 应该是 (food_id, unit_id)，并且 quantity 应该累加。
# 注入 bug：把累加改为覆盖（最常见的此类 bug 表现）。

 def consolidate_ingredients(existing_items, new_items):
     merged = {}
     for item in existing_items + new_items:
         key = (item.food_id, item.unit_id)
         if key in merged:
-            merged[key].quantity += item.quantity     # 正确：累加
+            merged[key].quantity = item.quantity       # BUG: 覆盖最新值，等于丢失累加
         else:
             merged[key] = item
     return list(merged.values())
```

或者另一种更隐蔽的等价 bug 注入（合并 key 漏掉 food_id）：

```diff
 def consolidate_ingredients(existing_items, new_items):
     merged = {}
     for item in existing_items + new_items:
-        key = (item.food_id, item.unit_id)             # 正确：按 food + unit 合并
+        key = (item.display, item.unit_id)             # BUG: 用 display string 当 key — 不同 food 同名会被错误合并；同 food 不同 display 不会合并
         if key in merged:
             merged[key].quantity += item.quantity
         else:
             merged[key] = item
     return list(merged.values())
```

### 注入后验证

1. 跑复现测试：必须 FAIL
2. 跑现有 mealie 测试：可能有 1-2 个其他测试也开始 FAIL（这是 bug 的合理副作用，DevLoop 系统的 CR agent 应能识别）

### 适用真实情况

- 如果你打算用此 case 测 spec/CR 阶段的"流程严谨度"，bug 注入是更可控的；
- 如果你打算同时测系统的"无 ground truth 时仍能定位真实 bug"的能力，建议先**不要**注入，让系统直接处理真实 mealie 中可能存在的相关问题（如有），然后对比结果。
