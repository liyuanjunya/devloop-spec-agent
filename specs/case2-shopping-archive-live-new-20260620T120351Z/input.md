# Case 2 — Shopping List 归档与历史回顾

> **难度**：中等偏高 · **业务直观度**：⭐⭐⭐⭐⭐ · **预期改动**：~15-20 个文件

---

## Spec for DevLoop System

> **以下是直接喂给你的 DevLoop 系统的需求文本，复制此节即可。**

### 业务背景

用户完成一次购物后，希望把当前的 shopping list "归档"：
- 记录这次买了什么、什么时候买的、谁结的账
- 主清单视图不再显示已归档的清单（保持界面清爽）
- 可以单独查看历史归档清单进行回顾

### 功能需求

#### 1. 数据模型

修改 `ShoppingList` 表：
- 新增 `archived_at TIMESTAMP NULL`（默认 NULL = 未归档）
- 新增 `archived_by_user_id UUID NULL`（外键 → users.id，archived_at 为 NULL 时此字段必须为 NULL）
- 数据迁移：所有现存 list 的 `archived_at` 默认 NULL（向后兼容）

#### 2. API 端点

| Method | Path | 行为 | 鉴权 |
|--------|------|------|------|
| `POST` | `/api/households/shopping/lists/{id}/archive` | 归档；要求所有 items 都已 `checked=true`，否则 409 + i18n "shopping-list.archive.unchecked-items" | household 内成员 |
| `POST` | `/api/households/shopping/lists/{id}/unarchive` | 取消归档 | household 内成员 |
| `GET` | `/api/households/shopping/lists` | 默认仅返回 `archived_at IS NULL` 的 list | household 内成员 |
| `GET` | `/api/households/shopping/lists?archived=true` | 仅返回已归档 | household 内成员 |
| `GET` | `/api/households/shopping/lists?archived=all` | 全部返回，附带 `archived_at` 字段 | household 内成员 |

#### 3. 归档后的不可变性

list 处于归档状态时（`archived_at IS NOT NULL`），以下行为必须返回 409 + i18n "shopping-list.archived.frozen":
- `PUT /api/households/shopping/lists/{id}` （更新 list metadata）
- `POST /api/households/shopping/items` （为归档 list 新增 item）
- `PUT /api/households/shopping/items/{id}` （修改归档 list 的 item）
- `DELETE /api/households/shopping/items/{id}` （删除归档 list 的 item）
- `PUT /api/households/shopping/items/{id}` 修改 checked 字段也禁止

例外：`unarchive` 接口本身允许在归档状态下调用。

#### 4. 多租户隔离

- 归档列表（`?archived=true`）只能被同一 household 的成员看到
- 同 group 内的其他 household 看不到对方的归档清单
- 跨 group 完全隔离

#### 5. 事件总线

归档/取消归档时通过 `mealie/services/event_bus_service/` 派发事件：
- 事件类型：`ShoppingListArchived` / `ShoppingListUnarchived`
- payload 包含：`list_id`, `list_name`, `household_id`, `archived_by_user_id`, `item_count`, `total_estimated_amount`（如有）
- payload 必须**不包含**任何其他 household / group 的数据

#### 6. Schema 与响应

- `ShoppingListSummary` / `ShoppingListOut` schemas 在归档查询时附加 `archived_at` 与 `archived_by`（user summary）
- 默认查询不返回这些字段（保持向后兼容）

#### 7. 实现约束

- 在 `mealie/repos/repository_shopping.py` 中**集中**实现归档过滤逻辑（不要在每个 controller 中手写过滤）
- 复用既有 `mealie/services/household_services/shopping_lists.py`（22.7KB）的业务编排，不要把归档逻辑分散到 controller
- alembic migration 必须向后兼容（数据回滚不丢失现存 list）
- 错误码与 i18n key 必须新增到 `lang/messages/` 所有现存语言文件中（至少 en-US）

#### 8. 测试要求

- `tests/unit_tests/`: archive/unarchive 业务函数的单元测试（至少 4 个）
- `tests/integration_tests/`: 
  - archive 成功 + list 不在默认查询中
  - archive 失败（有 unchecked items）
  - 归档后 PUT/POST/DELETE item 都返回 409
  - unarchive 后所有操作恢复
  - `?archived=true` / `?archived=all` query 行为
  - 事件总线 payload 校验
- `tests/multitenant_tests/`: 
  - 同 group 内其他 household 看不到对方归档 list
  - 跨 group 完全隔离
  - 跨 household 调用 archive 接口返回 404 / 403

---

## 三环节考察点（评估用，不喂给系统）

| 环节 | 关注点 |
|------|--------|
| **Spec** | 是否枚举出**所有**消费 shopping list 的下游接口（不漏 cookbook 联动、analytics、export 等）？是否识别多租户隔离需求？ |
| **Coding** | 是否在 repository 层集中过滤而非每处手写？是否复用 event_bus 抽象？是否覆盖 multitenant 场景？migration 是否向后兼容？ |
| **CR** | 是否指出"归档后的 list 在 export/backup 中如何处理"？"unarchive 时若 items 已被外部清理如何处理"？"event payload 是否泄露跨 household 数据"？"是否需要 admin 强制 unarchive"？ |

---

## 评估记录

| 维度 | 记录 |
|------|------|
| Spec 完整度（1-5） | |
| Coding 测试一次通过 | yes / no，轮次数：__ |
| Coding 是否破坏既有测试 | yes / no |
| 多 agent CR 提出的有效问题数 | |
| 人工 CR 补充发现的问题数 | |
| 备注 | |
