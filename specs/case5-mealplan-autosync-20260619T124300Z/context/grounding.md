# Mealie — Spec Agent Grounding Material

> Purpose: 喂给 DevLoop 系统的 spec agent 作为检索语料，帮助它快速建立 mealie 项目的业务/技术认知。  
> Source: 基于 mealie commit `4a099c168ebb3d2d4d5247605872bac316dcbb79` 的源码与 `docs.mealie.io` 文档站

---

## 1. Mealie 是什么

**自托管的家庭食谱管理 + 餐计划 + 购物清单系统**。核心使用流程：
1. 用户导入食谱（粘贴 URL 自动抓取，或手动录入）
2. 用户安排一周餐计划（哪天吃哪个食谱）
3. 系统根据餐计划生成购物清单（合并食材）
4. 多个家庭可以共享食谱、互相协作

---

## 2. 核心业务实体（领域模型）

```
Recipe（食谱）─────────────────────────────────────
  ├── RecipeIngredient（食材：name、quantity、unit、food）
  ├── RecipeStep（步骤：text、image）
  ├── RecipeTag / RecipeCategory（标签 / 分类，多对多）
  ├── RecipeTool（所需器具，多对多）
  ├── RecipeAsset / RecipeImage（图片/附件）
  ├── RecipeComment（评论）
  ├── RecipeShareToken（分享链接）
  ├── RecipeNutrition（营养信息）
  └── RecipeTimer / RecipeNote / etc.

Household（家庭 — 协作单元，多个 user 共用）─────
  ├── User（用户：admin / user 角色）
  ├── MealPlan（餐计划 entry：date + entry_type[breakfast/lunch/dinner/side] + recipe_id 或 title）
  ├── MealPlanRule（规则：每周一晚餐固定吃 X）
  ├── ShoppingList（购物清单：name + items[]）
  │     ShoppingListItem（每一项：display + quantity + unit + food + checked + recipe_references[]）
  │     ShoppingListItemRecipeRef（item ← recipe ingredient 的反向链接）
  ├── Cookbook（食谱集合：按 tag/category/tool 过滤）
  ├── Notifier / Webhook（事件订阅）
  └── HouseholdPreferences（per-household 设置）

Group（多租户 — 多 Household 聚合）──────────────
  ├── Household（多个）
  ├── GroupPreferences
  ├── GroupReport（备份/导入/导出报告）
  └── GroupRecipeAction

Foods / Units / Categories / Tags / Tools（全局词典 — 跨 household 共享但 group 范围隔离）
```

### 多租户层级
```
Group  (顶层多租户)
  ↓
Household  (group 内的子单元；user/recipe/mealplan/shoppinglist 都属于 household)
  ↓
User
```

---

## 3. 项目目录结构

```
mealie/                          ← Python 源代码包
├── app.py                       ← FastAPI 应用工厂
├── main.py                      ← uvicorn 入口
├── alembic/                     ← 数据库迁移
│   └── versions/                ← migration 文件（追加这里）
├── core/                        ← 配置、依赖注入、settings、安全
│   ├── config.py
│   ├── dependencies/
│   ├── security/
│   └── settings/
├── db/                          ← SQLAlchemy ORM 模型
│   ├── models/
│   │   ├── recipe/
│   │   ├── household/
│   │   ├── group/
│   │   ├── users/
│   │   └── _model_base.py       ← SqlAlchemyBase
│   └── db_setup.py
├── repos/                       ← 数据访问层（repository 模式）
│   ├── repository_factory.py    ← AllRepositories — 一切 query 的入口
│   ├── repository_recipes.py
│   ├── repository_meals.py
│   ├── repository_shopping.py
│   ├── repository_users.py
│   └── _utils.py
├── schema/                      ← Pydantic v2 schemas（API 入参/出参）
│   ├── recipe/
│   ├── household/
│   ├── group/
│   ├── user/
│   └── _mealie/                 ← 基类
├── routes/                      ← FastAPI 路由（按业务垂直切分）
│   ├── _base/                   ← 通用基类（BaseUserController, BaseAdminController）
│   ├── admin/
│   ├── app/                     ← 应用元数据 (about / settings)
│   ├── auth/                    ← JWT/OAuth/LDAP
│   ├── comments/
│   ├── explore/                 ← 公开浏览（无需登录）
│   ├── groups/                  ← 多租户管理
│   ├── households/              ← ★ 家庭、meal plan、shopping list、cookbook 都在这
│   │   ├── controller_mealplan.py
│   │   ├── controller_mealplan_rules.py
│   │   ├── controller_shopping_lists.py
│   │   ├── controller_cookbooks.py
│   │   ├── controller_household_self_service.py
│   │   ├── controller_group_notifications.py
│   │   ├── controller_group_recipe_actions.py
│   │   ├── controller_invitations.py
│   │   └── controller_webhooks.py
│   ├── media/                   ← 静态资源（图片）
│   ├── organizers/              ← tags / categories
│   ├── parser/                  ← 食材文本解析
│   ├── recipe/                  ← 食谱 CRUD + 导入 + 分享 + 评论
│   ├── shared/, spa/, validators/, users/, unit_and_foods/
│   └── handlers.py              ← 全局异常处理
├── services/                    ← 业务服务层（编排 + 跨模块逻辑）
│   ├── _base_service/           ← BaseService 基类
│   ├── recipe/                  ← 食谱业务（导入、share、Yields scaling 等）
│   ├── household_services/
│   │   ├── household_service.py
│   │   └── shopping_lists.py    ← ★ shopping list 业务（与 meal plan 联动）
│   ├── group_services/
│   ├── user_services/
│   ├── scraper/                 ← URL 抓取（schema.org / OpenGraph）
│   ├── openai/                  ← ★ LLM 抽象（已有的 OpenAI client + prompts）
│   │   ├── openai.py            ← OpenAIService（同步/异步 client）
│   │   └── prompts/             ← prompt 模板
│   ├── parser_services/         ← "2 cups flour" → 结构化食材
│   ├── scheduler/               ← ★ 定时任务
│   │   ├── scheduler_service.py ← 启动入口
│   │   ├── scheduler_registry.py← 任务注册中心
│   │   ├── scheduled_func.py    ← @scheduled 装饰器
│   │   ├── runner.py            ← 任务执行器
│   │   └── tasks/               ← 现存任务的具体实现
│   ├── event_bus_service/       ← 事件总线（用于跨模块通知）
│   ├── analytics/, backups_v2/, exporter/, migrations/, email/, seeder/, urls/, query_filter/
├── middleware/
├── pkgs/                        ← 工具包（log、img 处理等）
├── lang/                        ← i18n 字符串
└── assets/

tests/
├── unit_tests/                  ← 快速、纯单元
├── integration_tests/           ← 走 HTTP 客户端 + DB
├── multitenant_tests/           ← ★ 验证 group/household 数据隔离
├── e2e/                         ← Playwright 浏览器端到端
├── fixtures/                    ← 共享 fixture 工厂
└── utils/                       ← 测试辅助工具
```

---

## 4. 三层调用约定（添加新功能时遵循）

```
HTTP request
  ↓
mealie/routes/<area>/controller_*.py   ← 路由、入参校验、调用 service
  ↓
mealie/services/<area>/*_service.py     ← 业务编排、跨 repo 协调、调用 event_bus
  ↓
mealie/repos/repository_*.py           ← 数据访问、SQL 优化（selectinload 等）
  ↓
mealie/db/models/*.py                  ← SQLAlchemy ORM 模型
```

**注意**：mealie 用 `repository_factory.AllRepositories` 作为一切 query 的统一入口（per-household 自动注入过滤器）。新增 query 时优先扩展现有 repository，而非绕过它。

---

## 5. 关键基础设施 / 横切关注

| 关注点 | 模块 | 使用方式 |
|--------|------|---------|
| 鉴权 | `core/dependencies/dependencies.py` | `Depends(get_current_user)` / `Depends(get_admin_user)` |
| Per-household 自动过滤 | `routes/_base/` 控制器基类 | 所有 query 默认带 `household_id` 过滤 |
| 多租户隔离测试 | `tests/multitenant_tests/` | 新增跨 household/group 功能必须加这里 |
| 事件总线 | `services/event_bus_service/` | `event_bus.dispatch(event_type, event_source, document_data)` |
| 定时任务 | `services/scheduler/` | `@scheduled(period_minutes=N)` 装饰器 + 在 `scheduler_registry.py` 注册 |
| i18n 字符串 | `lang/messages/` (yaml) | `t('errors.invalid_password')` 取代硬编码 |
| LLM 调用 | `services/openai/openai.py` | `OpenAIService(...).get_response(prompt, ...)` |
| URL 食谱抓取 | `services/scraper/` | `scraper.scrape(url) -> RecipeSchema` |
| 食材文本解析 | `services/parser_services/` | `parser.parse_ingredients(text)` |

---

## 6. 测试约定

- **fixtures**：`tests/fixtures/` 提供 `unique_user`, `random_household`, `recipe`, `shopping_list` 等工厂
- **conftest**：`tests/conftest.py` 启动测试 app + 隔离 DB
- **multitenant**：跨 household 的新功能必须在 `tests/multitenant_tests/` 加测试，验证：
  - household A 的 user 看不到 household B 的数据
  - 跨 household 的 ID 注入攻击被拦截
- **运行命令**：
  - `uv run pytest tests/unit_tests` — 最快
  - `uv run pytest tests/integration_tests` — 走 DB
  - `uv run pytest tests/` — 全套

---

## 7. 常用扩展模式（DevLoop case 经常涉及）

### A) 新增一张表 + CRUD
1. 在 `mealie/db/models/<area>/*.py` 加 SQLAlchemy 模型
2. `uv run alembic revision --autogenerate -m "add xxx"` → 检查生成的 migration
3. 在 `mealie/schema/<area>/*.py` 加 Pydantic schemas（Create / Read / Update / Pagination）
4. 在 `mealie/repos/repository_*.py` 加 repository（继承 `RepositoryGeneric`）
5. 在 `mealie/services/<area>/` 加 service（继承 `BaseService`）
6. 在 `mealie/routes/<area>/controller_*.py` 加 controller（继承 `BaseUserController` 等）
7. 在 `mealie/routes/__init__.py` 注册新 router
8. 写 `tests/integration_tests/...` 测试

### B) 给已有响应字段加字段
1. 修改 `mealie/schema/.../*.py` 中的 Pydantic Read schema
2. 修改对应 repository 的 query，确保新字段被一次性 fetch（避免 N+1）
3. 修改 controller 中可能的 transform
4. 更新 OpenAPI（自动）+ 测试

### C) 新增一个 scheduled task
1. 在 `mealie/services/scheduler/tasks/<name>.py` 写任务函数
2. 在 `mealie/services/scheduler/scheduler_registry.py` 注册（指明触发周期）
3. 写 unit + integration test（测试可以直接调用任务函数，无需起 scheduler）

### D) 调用 LLM
- 使用 `mealie/services/openai/openai.py` 中的 `OpenAIService`
- prompt 模板放在 `mealie/services/openai/prompts/`
- 测试时 mock `OpenAIService.get_response`

---

## 8. 已知 / 可观察的工程债（CR 阶段可能识别）

- 部分 list 接口的 N+1（特别是 recipe list 附带 tags/categories/tools）
- 多副本部署下的 scheduler 单例锁定（当前依赖单实例运行）
- shopping list 与 meal plan 联动逻辑（services/household_services/shopping_lists.py 22.7KB）较复杂，可能存在 unit 不一致时的累加 bug
- OpenAI 调用未限流（适合作为 case 6 中的 CR 发现点）
