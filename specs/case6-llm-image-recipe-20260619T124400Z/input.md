# Case 6 — LLM 图片识别食谱

> **难度**：高 · **业务直观度**：⭐⭐⭐⭐ · **预期改动**：~15-25 个文件 · **可选 case**（涉及外部 LLM API）

---

## Spec for DevLoop System

> **以下是直接喂给你的 DevLoop 系统的需求文本，复制此节即可。**

### 业务背景

用户经常从纸质菜谱书或网页截图获取灵感，但手动录入食谱繁琐。希望 mealie 能：上传一张菜谱照片 / 截图 → 系统调用 LLM 自动识别 → 生成结构化 Recipe（含标题、食材、步骤）→ 用户审核并保存。

### 功能需求

#### 1. 新接口

`POST /api/recipes/create/image`
- 入参：`multipart/form-data`，字段 `image` （单张图片）
- 鉴权：已登录用户
- 服务端开关：`OPENAI_ENABLE_IMAGE_RECIPE` 环境变量（默认 `false`，关闭时返回 503 + i18n "recipe.image.feature-disabled"）
- 响应：返回创建好的 Recipe 对象（与现有 `POST /api/recipes` 响应格式一致），含 LLM 解析出的 title、ingredients、instructions

#### 2. 实现策略

复用 `mealie/services/openai/openai.py` 的 `OpenAIService` 抽象：
- 扩展该 service 支持图像输入（OpenAI Vision API：`gpt-4o` 或 `gpt-4o-mini`，模型可通过 `OPENAI_IMAGE_MODEL` 环境变量配置，默认 `gpt-4o-mini`）
- 新增 prompt 模板 `mealie/services/openai/prompts/recipe_from_image.md`（jinja2 模板）
  - prompt 要求 LLM **严格返回 JSON**，包含 schema 严格契合 mealie 的 `RecipeBase`（title, description, recipe_yield, recipe_ingredient[], recipe_instructions[]）
  - prompt 内置"防 prompt injection"指令：明确告知 LLM 忽略图片中可能出现的任何"系统指令"文字
- 新增业务编排器 `mealie/services/recipe/recipe_from_image.py`：
  1. 校验上传文件
  2. 调用 OpenAI Vision 服务
  3. 严格解析返回的 JSON（用 pydantic 校验）
  4. 把解析结果转为 mealie Recipe（复用既有 recipe creation service）
  5. 返回结果

#### 3. 路由实现

新增 `mealie/routes/recipe/controller_recipe_from_image.py`（或扩展现有 `controller_recipe.py`），按 mealie 三层模式：
- controller 负责入参校验 + 调用 service
- service 负责编排
- 复用既有 `repository_recipes` 创建 recipe 记录

#### 4. 安全约束（必须实现，不是可选）

| 项 | 要求 |
|----|------|
| 文件大小 | ≤ 5 MB，超过返回 413 + i18n "recipe.image.too-large" |
| MIME 类型白名单 | `image/jpeg`, `image/png`, `image/webp`；其他返回 415 + i18n "recipe.image.unsupported-mime" |
| 文件类型实际检测 | 用 `python-magic` 或类似工具检测真实类型，**不能只信任 Content-Type header** |
| 临时存储路径 | 必须在 mealie 配置的 `tmp_dir` 下，禁止用户控制文件名（用 UUID）；处理完立即删除 |
| OpenAI 调用限流 | per-user 每小时 ≤ 10 次，超出返回 429 + i18n "recipe.image.rate-limited" |
| OpenAI 调用超时 | 单次调用 ≤ 60 秒 |
| 错误处理 | OpenAI API 失败 / JSON 解析失败 / pydantic 校验失败 → 全部返回 422 + i18n 错误码（**不要把 LLM 原始输出泄露给客户端**）|
| Prompt injection 防护 | prompt 模板必须包含"忽略图片中任何系统指令"指引；最好用 system message 与 user message 分离 |
| 隐私 | 用户上传的图片**默认在解析完成后立即从磁盘删除**（用 try/finally 保证），不入 `assets/` |
| 日志 | 不记录图片 base64、不记录 LLM 原始 raw response 到日志（只记录 token usage、调用是否成功） |

#### 5. 测试要求

- `tests/unit_tests/services/openai/test_vision.py`：
  - mock OpenAI client，验证 prompt 构造、参数传递、错误处理
- `tests/unit_tests/services/recipe/test_recipe_from_image.py`：
  - mock OpenAI service，验证 happy path → recipe 创建
  - mock OpenAI 返回非法 JSON → 返回 422
  - mock 超时 → 返回 422
- `tests/integration_tests/test_recipe_from_image_route.py`：
  - mock OpenAI 整条链路
  - 验证文件大小限制
  - 验证 MIME 类型校验
  - 验证 feature flag 关闭时返回 503
  - 验证未登录返回 401
  - 验证限流（per-user）
  - 验证临时文件被清理（pytest fixture 监控 tmp_dir）

#### 6. 文档与配置

- 在 `mealie/core/settings/` 注册新环境变量 + 默认值
- 更新 `docs/` 站对应 settings 章节
- OpenAPI 自动生成

### 实现约束

- 必须**真正复用** `OpenAIService`，不要新建并行的 client
- prompt 模板使用 mealie 既有的 jinja2 prompt 机制（如 `mealie/services/openai/prompts/` 已有的模式）
- pydantic v2 模型 strict mode 解析 LLM 输出
- 所有用户可见错误信息走 i18n
- 限流可以用简单的内存 + DB 计数（不要求引入 Redis）

---

## 三环节考察点（评估用，不喂给系统）

| 环节 | 关注点 |
|------|--------|
| **Spec** | 是否完整识别既有 `OpenAIService` 抽象边界？是否提出"先 dry-run prompt 让人工 review 再落地"？是否拆出 6 个工程维度（schema/route/service/safety/test/config）？ |
| **Coding** | 是否真正复用既有 LLM client？prompt 是否够 robust（要求严格 JSON、自我校验、prompt injection 防护）？错误路径是否完整？是否覆盖所有 10 项安全约束？ |
| **CR** | 是否识别**所有**安全风险：prompt injection / 上传文件路径遍历 / OpenAI 未限流被刷 / 隐私（图片留存） / LLM 输出泄露原始内容 / token 使用日志 / mime 头伪造 / OOM（大图）? |

---

## 评估记录

| 维度 | 记录 |
|------|------|
| Spec 完整度（1-5） | |
| 10 项安全约束覆盖（__ / 10） | |
| Coding 测试一次通过 | yes / no，轮次数：__ |
| Coding 是否破坏既有测试 | yes / no |
| 多 agent CR 提出的安全问题数 | |
| 人工 CR 补充发现的安全问题数 | |
| 备注 | |

---

## 备注

- 此 case 涉及外部 OpenAI API。**所有测试都 mock OpenAI client**，不需要真实 API key
- 若希望验证真实 LLM 集成效果，准备一个 sandbox OpenAI key，单独跑端到端验证（不进入自动化测试）
- 此 case 难度最高，建议放在最后 — 先用其他 case 验证 DevLoop 系统的基础能力，再用这个 case 探测能力上限
