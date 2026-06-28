# Case 5 — Meal Plan 自动联动 Shopping List

> **难度**：中等偏高 · **业务直观度**：⭐⭐⭐⭐⭐ · **预期改动**：~12-18 个文件

---

## Spec for DevLoop System

> **以下是直接喂给你的 DevLoop 系统的需求文本，复制此节即可。**

### 业务背景

很多家庭希望 mealie 能"自动"管理一周购物：每天根据今天 meal plan 中安排的食谱，自动把所需食材合并加入家庭主 shopping list，省去手动同步的麻烦。

### 功能需求

#### 1. 新增 Household 配置

在 `HouseholdPreferences`（或对应配置 entity）新增字段：
- `auto_sync_meal_plan_to_shopping: bool`（默认 `false`，向后兼容）
- `auto_sync_target_shopping_list_id: UUID | null`（指定目标 shopping list；如为 null 自动用 household 的第一个 active 主 list）
- `auto_sync_run_time: str`（24h 制 HH:MM，默认 `"00:00"`，per-household 可配置，作为 household 时区下的"今天开始时间"）

配套：
- 新增 `PATCH /api/households/preferences` 字段支持
- 配置存储到现有 household preferences 表（alembic migration 加列）

#### 2. 定时任务实现

在 `mealie/services/scheduler/tasks/auto_sync_shopping.py` 新增定时任务：

行为规范：
- **触发频率**：每 30 分钟跑一次（用 mealie 既有的 `@scheduled` 装饰器）
- **过滤条件**：
  - 只处理 `auto_sync_meal_plan_to_shopping = true` 的 household
  - 只在 household 时区下的 `auto_sync_run_time` 时刻所在的 30 分钟窗口内触发（避免每 30 分钟都重复同步）
  - 同一 household 每天最多触发 1 次同步（用 `LastAutoSyncedAt` 记录，跨进程幂等）

执行步骤：
1. 取该 household 今天（按 household 时区）所有 `MealPlan` entries（含 `recipe_id` 不为 null 的 entry）
2. 对每个 entry 关联的 recipe，拉取其 ingredient list
3. 用 mealie 既有 `consolidate_ingredients`（合并函数，复用 case-3 中可能被修复的逻辑）按 `(food_id, unit_id)` 合并
4. 过滤掉"通用食材"：如果 `food.is_pantry_staple = true` 则跳过（此字段如不存在则一并新增到 `foods` 表，default false）
5. 把合并后的 items 追加到目标 shopping list（标记 `recipe_references` 关联回 meal plan / recipe）
6. 追加策略：如目标 list 已有同 (food_id, unit_id) item 且未 checked，累加 quantity；否则新增 item
7. 派发事件 `MealPlanAutoSyncedToShopping`（event_bus），payload 含 household_id、shopping_list_id、added_item_count、skipped_pantry_count

#### 3. 手动触发接口

新增 `POST /api/households/preferences/auto-sync-shopping/run-now`:
- 立即对当前 household 执行一次同步（绕过 `LastAutoSyncedAt` 限制，但仍更新它）
- 鉴权：household 内 admin 角色
- 返回结果：`{ added_count, skipped_pantry_count, target_list_id, run_at }`

#### 4. 跨域配套

- `Food` 模型新增 `is_pantry_staple: bool`（默认 false） → migration + schema + repo + admin/foods routes（允许管理员标记）
- i18n: 新增错误码 `auto-sync.no-meal-plan-today`, `auto-sync.no-target-list`, `auto-sync.already-synced-today`

#### 5. 测试要求

- `tests/unit_tests/services/scheduler/test_auto_sync.py`：单元覆盖
  - 合并逻辑正确
  - pantry staple 过滤
  - 时区窗口判断
  - LastAutoSyncedAt 幂等
- `tests/integration_tests/`:
  - 手动触发接口 happy path
  - 配置未开启时定时任务跳过
  - 当天无 meal plan 时返回 204 / 0 added
  - pantry staples 不被同步
- `tests/multitenant_tests/`:
  - **关键**：household A 的 meal plan **绝不**写入 household B 的 shopping list
  - 跨 group 完全隔离
  - 跨 household 的 food pantry-staple 标记不互相影响

### 实现约束

- 必须复用 `mealie/services/scheduler/` 既有抽象（不要新建并行 scheduler）
- 必须复用 `mealie/services/household_services/shopping_lists.py` 中合并/添加 item 的现有函数
- 必须复用 `mealie/services/event_bus_service/` 派发事件
- 多副本部署考虑：用数据库行级锁（`SELECT ... FOR UPDATE SKIP LOCKED`）或 `LastAutoSyncedAt` CAS 保证同一 household 同一天只被一个 worker 处理
- 时区：必须使用 household 配置的时区（如未配置取 group default 或 server default UTC），**禁止**使用 `datetime.now()` without timezone

---

## 三环节考察点（评估用，不喂给系统）

| 环节 | 关注点 |
|------|--------|
| **Spec** | 是否拆解出 6 个子需求（配置 / 调度 / 聚合 / 事件 / 手动触发 / 多租户）？是否预判多副本并发与时区？ |
| **Coding** | scheduler 并发安全（多副本部署）？事件幂等性？是否复用 parser_services 处理食材？是否处理"meal plan 凌晨被修改"的边界？ |
| **CR** | 是否指出"多副本时如何避免重复执行"？"用户在午夜修改 meal plan 的窗口冲突"？"跨时区如何处理'今天'的定义"？"pantry_staple 标记跨 household 是否合理"？ |

---

## 评估记录

| 维度 | 记录 |
|------|------|
| Spec 完整度（1-5） | |
| 6 个子需求是否全覆盖（__ / 6） | |
| Coding 测试一次通过 | yes / no，轮次数：__ |
| Coding 是否破坏既有测试 | yes / no |
| 多 agent CR 提出的有效问题数 | |
| 人工 CR 补充发现的问题数（重点：并发/时区/幂等） | |
| 备注 | |
