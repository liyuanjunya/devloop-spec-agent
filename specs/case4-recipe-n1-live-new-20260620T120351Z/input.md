# Case 4 — Recipe List 性能重构（N+1 消除）

> **难度**：中等偏高 · **业务直观度**：⭐⭐⭐⭐ · **预期改动**：~3-6 个文件

---

## Spec for DevLoop System

> **以下是直接喂给你的 DevLoop 系统的需求文本，复制此节即可。**

### 业务背景

mealie 的"All Recipes"页面（`GET /api/recipes`）在用户食谱较多（>100）时出现明显延迟。根因是当前实现对每条 recipe 单独发起若干次额外查询拉取关联数据（tags / categories / tools / 最近评论数 / image 元数据），导致 N+1 查询问题。

### 任务要求

#### 1. 性能优化目标

**保持响应字段 100% 不变**的前提下，把 `GET /api/recipes` 的 query 次数从 O(N) 降到 O(1)（即不随 recipe 数量增加）。

- 重写 `mealie/repos/repository_recipes.py` 中负责 list recipes 的方法（或 `mealie/services/recipe/` 中相应实现），用 SQLAlchemy `selectinload` / `joinedload` / 聚合子查询批量化
- 涉及响应字段（必须保持原样输出）：
  - `id, slug, name, description, image, slug_image`
  - `tags[]`, `recipe_category[]`, `tools[]`（多对多关系）
  - `total_time, prep_time, perform_time, rating`
  - 任何当前响应中存在但本 spec 未列出的字段（必须保持）

#### 2. 保持现有测试通过

- `tests/unit_tests/test_recipe*.py` 全部通过
- `tests/integration_tests/test_recipe*.py` 全部通过
- `tests/multitenant_tests/` 中涉及 recipe 的测试全部通过
- **API 响应 JSON 字段、顺序、内容、分页行为零变化**

#### 3. 新增性能测试

新增 `tests/integration_tests/test_recipe_list_query_count.py`：

```python
# 伪代码示意
@pytest.mark.asyncio
async def test_recipe_list_query_count_constant(test_client, household_with_recipes):
    """N+1 regression test: query count should not grow with recipe count."""
    queries = []
    
    @event.listens_for(engine, "before_cursor_execute")
    def on_query(*args, **kwargs):
        queries.append(args)
    
    # 1) 10 recipes
    seed_recipes(10)
    queries.clear()
    response = test_client.get("/api/recipes?perPage=50")
    count_small = len(queries)
    
    # 2) 100 recipes
    seed_recipes(90)  # already have 10
    queries.clear()
    response = test_client.get("/api/recipes?perPage=200")
    count_large = len(queries)
    
    # 关键断言：query 数不随 recipe 数线性增长
    assert count_large <= count_small + 3, (
        f"N+1 regression: {count_small} queries for 10 recipes, "
        f"{count_large} queries for 100 recipes"
    )
    # 上限：所有 list recipes 调用都应该 ≤ 5 个 query（recipes + tags + categories + tools + count）
    assert count_large <= 5
```

#### 4. PR Description 必须包含

- before/after query 次数对比（用 pytest 输出的 queries 数）
- before/after 的 EXPLAIN ANALYZE 截图或文本（针对 100 recipes 的场景）
- 是否新增了任何索引（如有需在 alembic migration 中说明）

#### 5. 实现约束

- **禁止引入应用层缓存**（Redis / in-memory cache）— 必须通过 SQL 层面优化
- 必须保持 mealie 既有的**分页正确性**：`limit` / `offset` / `total` / `total_pages` 完全一致
- 必须保持 mealie 既有的**multitenant 过滤**：`household_id` filter 必须仍生效，不能因 JOIN 而泄露其他 household 的 recipe
- 不允许"延迟加载"trick（如 lazy='dynamic' → list 转换），因为这只是把 query 隐藏到响应序列化阶段

---

## 三环节考察点（评估用，不喂给系统）

| 环节 | 关注点 |
|------|--------|
| **Spec** | 是否明确"行为不变 + 性能提升 + 可量化测试"三重约束？是否要求 PR 描述写 before/after 数据？ |
| **Coding** | 是否真的用 `selectinload`/`joinedload`/子查询？是否处理 `comments_count` 这类聚合？是否破坏分页 ordering？是否避免 JOIN + limit 的笛卡尔积？ |
| **CR** | 是否识别"selectinload 在 multitenant 过滤的隔离性"？"joinedload + limit 笛卡尔积坑"？"COUNT 子查询的索引"？是否提示加 partial index？ |

---

## 评估记录

| 维度 | 记录 |
|------|------|
| Spec 完整度（1-5） | |
| Before query count（100 recipes） | |
| After query count（100 recipes） | |
| 既有测试是否全通过 | yes / no |
| 新增性能测试是否通过 | yes / no |
| 多 agent CR 提出的有效问题数 | |
| 人工 CR 补充发现的问题数 | |
| 备注 | |
