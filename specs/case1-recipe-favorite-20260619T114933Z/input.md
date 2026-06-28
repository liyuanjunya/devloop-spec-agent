# Case 1 — Recipe Favorite（食谱收藏）

> **难度**：基础到中等 · **业务直观度**：⭐⭐⭐⭐⭐ · **预期改动**：~8-12 个文件

---

## Spec for DevLoop System

> **以下是直接喂给你的 DevLoop 系统的需求文本，复制此节即可。**

### 业务背景

用户希望能收藏喜欢的食谱（类似"星标"），方便随时找到。这是一个用户级（不是 household 级）的功能。

### 功能需求

#### 1. 数据模型
新增 `user_favorite_recipe` 表：
- `user_id`（外键 → users.id，级联删除）
- `recipe_id`（外键 → recipes.id，级联删除）
- `created_at`（timestamp，默认 now）
- 复合唯一索引 `(user_id, recipe_id)` 保证一个用户对同一食谱只能收藏一次
- 单独索引 `user_id` 用于"我的收藏"列表查询

#### 2. API 端点

| Method | Path | 行为 | 鉴权 |
|--------|------|------|------|
| `POST` | `/api/users/self/favorites/{recipe_slug}` | 收藏指定食谱 | 已登录用户 |
| `DELETE` | `/api/users/self/favorites/{recipe_slug}` | 取消收藏 | 已登录用户 |
| `GET` | `/api/users/self/favorites?page=1&perPage=50` | 当前用户的所有收藏食谱（分页，复用 mealie 既有的 `PaginationQuery`） | 已登录用户 |

行为细节：
- POST 幂等：重复收藏返回 200 + 已存在记录，不报错
- DELETE 幂等：取消未收藏的食谱返回 200，不报错
- 跨 group / household 隔离：用户只能收藏自己 group 内可见的食谱（如 recipe 不可见则 404）
- 食谱被删除时：cascade 删除所有相关 favorite

#### 3. 响应字段扩展

`GET /api/recipes` 与 `GET /api/recipes/{slug}` 的响应：
- 对**已登录用户**额外返回 `favorited: bool`（是否被当前用户收藏）
- **公开**返回 `favorite_count: int`（总收藏数）
- 未登录用户：`favorited` 字段恒为 `false`

#### 4. 实现约束

- 必须遵循 mealie 三层模式：routes/users/ → services/user_services/ → repos/repository_users.py（或新建 `repository_favorites.py`）
- migration 文件名格式跟 mealie 既有 alembic versions 一致
- 错误信息使用 mealie 既有 i18n 体系（`lang/messages/*.yaml`），不写硬编码英文
- Pydantic schemas 在 `mealie/schema/user/user_favorites.py`
- `GET /api/recipes` list 必须避免 N+1 — 用 SQL JOIN / IN / EXISTS 一次性拉取 `favorited` 和 `favorite_count`，而非每条 recipe 单独查询

#### 5. 测试要求

- `tests/unit_tests/` 至少 3 个：repository 层的 add/remove/list
- `tests/integration_tests/` 至少 6 个：
  - 收藏、取消、再收藏（幂等）
  - 未登录访问 list recipes 时 `favorited` 恒 false
  - 跨 group 的 recipe 收藏返回 404
  - 收藏后 `favorite_count` 增加
  - 删除 recipe 后 cascade 清理 favorite
  - 分页正确
- `tests/multitenant_tests/` 至少 2 个：
  - household A 的用户无法看到 household B 的用户的收藏
  - 不同 group 的 recipe 互不可见

#### 6. 文档

更新 OpenAPI（FastAPI 自动生成即可，确保 docstring + response_model 完整）。

---

## 三环节考察点（评估用，不喂给系统）

| 环节 | 关注点 |
|------|--------|
| **Spec** | 是否识别"既要新建实体也要扩展已有 recipe 响应"双重需求？是否预判到 N+1？是否提到 multitenant？ |
| **Coding** | 是否复用三层模式？migration 是否带索引？是否处理跨 group 越权？是否真的 JOIN 而非 N+1？ |
| **CR** | 是否指出"未登录时 favorited 必须恒为 false"漏测？"DELETE 幂等性"？"用户级收藏数上限是否需要"？"删除 user 时是否级联清理"？ |

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
