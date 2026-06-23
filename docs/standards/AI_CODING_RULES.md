# AI 协作规则

> 给 Claude / Codex / Cursor / Cline 等 AI agent 在本仓做业务功能开发时的工作流约束与边界。
>
> **不重复**的内容请回到源头：
> - 全局分层规则总论 → 开发规范文档 「Web 服务（FastAPI 主栈）」
> - 跨语言协同约定 → 跨语言协同 ADR
> - 项目阶段 / 工作流约束 → 本仓 `AGENTS.md`（`CLAUDE.md` 通过 `@AGENTS.md` 导入它）
> - 生成器 CLI 与模板细节 → [CODE_GENERATOR.md](./CODE_GENERATOR.md)
>
> 本文只讲：**做业务功能时按什么流程走、改哪些文件、不能改哪些文件、提交前怎么自检**。

## 0. 注释 / docstring 语言规则（v0.5.1 加，红线）

**所有 docstring、inline comments、模块 docstring 默认用简体中文**。

保留**英文原貌**的例外（限于以下三类，避免破坏契约）：
- **代码 identifier**：类名 / 函数名 / 变量名 / 模块路径（``admin_platform.core.errors`` 不翻译）
- **错误码字面量**：``user.NOT_FOUND`` / ``framework.IDEMPOTENT_RETRY_IN_FLIGHT`` 等字符串值
- **三方框架专有名词与文献引用**：``BaseHTTPMiddleware`` / ``selectinload`` / ``RFC 9457`` / ``ADR 0001 §1`` 等

**触发条件**：v0.5.1 翻译了当时新加 / 修改的代码；v0.5.2 清扫了 `scripts/new_module.py` generator 模板 + `core/*` + `db/*` + `api/v1/health.py` 等基础设施债。**至此模板内代码 docstring 一致简体中文**，后续任何**新写**或**修改**的注释 / docstring 都按本规则走，**不再有例外**。

**根因（写给未来的 AI agent）**：v0.5.0 之前所有代码 docstring 都是英文，让我把"跟随既有风格"凌驾于"全局 CLAUDE.md 默认简体中文"。**这个优先级是错的**：用户的全局规则优先于仓库历史风格。看到既有英文 docstring 不是免责理由，是欠债痕迹。

## 1. 决策树：要做什么类型的改动？

```
新功能 / bug fix 进来时，先分类：

├─ 新增业务域（如 orders / users / products）
│   → §2「新增 domain 流程」（必走 generator，不要手抄模板）
│
├─ 已有 domain 加端点 / 字段
│   → §3「扩展已有 domain」（按层改）
│
├─ 改基础设施（core / db / main.py / config / middleware）
│   → §4「碰基础设施前的红线」（先停下来评估）
│
├─ 改 Makefile / pyproject.toml / Dockerfile / CI workflow
│   → §5「构建与发布层改动」（对照 7 条 Errata）
│
└─ 仅改 docs / 注释 / typo
    → 直接改，跳过本文（但 docs/ drift 视为 bug）
```

## 2. 新增 domain 流程（硬性）

**第一步永远是跑 generator**：

```bash
make new-module name=order dry-run=1    # 先 dry-run 看文件清单
make new-module name=order              # 真生成（无 ORM）
make new-module name=product with-model=1   # 含 ORM
```

完整 generator CLI / 模板细节 → [CODE_GENERATOR.md](./CODE_GENERATOR.md)。

生成完成后，AI **必须**按生成器输出的「Next steps」执行：

1. **注册路由**到 `src/<service>/main.py` `create_app()`
2. **（仅 `--with-model`）注册 ORM 到 Alembic**——加 import 到 `migrations/env.py` + `alembic revision --autogenerate -m "add <plural> table"` + **人工 review** migration 文件 + `alembic upgrade head`
3. **POST 端点默认带 `@idempotent` 装饰器**（v0.4.6 起 generator 默认套）—— 如该端点是天然幂等的（如 content-addressed upload）或你不想要客户端去重，**显式删除**装饰器；不要静默保留不带 Idempotency-Key 调用的路径

```python
# api.py 生成出来默认长这样
from service_name.core.idempotency import idempotent

@router.post("", operation_id="orders_create", response_model=OrderRead, status_code=201)
@idempotent           # 默认套；要 opt-out 时显式删
async def create_order(payload: OrderCreate, svc: ServiceDep) -> OrderRead:
    return await svc.create(payload)
```

调用方需传 `Idempotency-Key: <opaque>` header；同 key + 同 body 返 cached + `Idempotent-Replayed: true` header。Redis 故障时降级为不缓存（不阻塞请求）。

**禁止**：
- 跳过 generator 自己写 `domains/<name>/`——会偏离命名、丢类型、漏 tests
- 让 generator 改 `main.py` 或 `migrations/env.py`——必须人工 review
- 在没跑 `make check` 之前 commit

## 3. 扩展已有 domain：改哪些层

| 改动类型 | 改这些 | **不要**改这些 |
|---|---|---|
| 加字段 | `schemas.py` + `models.py`（若有）+ migration | `api.py` 入参解析（让 schema 自动校验）|
| 加端点 | `api.py` + `service.py`（必要时 `repository.py`） | `core/*`（端点级逻辑不属于基础设施） |
| 改业务规则 | `service.py` | `api.py`（router 不应该有 if/else 业务分支） |
| 改查询 | `repository.py` | `service.py`（业务层不写 SQL） |
| 改返回结构 | `schemas.py` + `service.py` 映射 | 直接把 ORM 对象抛给 router |
| 改分页行为 | `repository.py` (`list_paginated` / `count`) + `service.py` (`total_pages` 算法) | `api.py` 的 `PageQ` / `SizeQ` Annotated 类型 |

**分层硬约束**（违反必须立即修，不要拖到下一个 PR）：

- `api/` **禁止**直接 import `models.py` / `repository.py`——只能从 `service.py` 拿
- `service/` **禁止**引入 `fastapi.Request` / `fastapi.Response`——错误用 `AppError` 抛出
- `repository/` **禁止**抛 `HTTPException`——只返回 `None` 或 raise 仓储级异常
- `schemas/` **禁止**混入 SQLAlchemy session——纯 Pydantic
- `models/` **禁止**放序列化逻辑（`to_dict` / `__json__`）——给 `schemas` 干

**异常约定**：业务异常一律用 `core.errors.AppError(code, title, *, detail=None, status_code=400, errors=None)`。错误码格式见 [NAMING_CONVENTIONS.md](./NAMING_CONVENTIONS.md)。字段映射规则见 [../architecture/ERROR_RESPONSE.md](../architecture/ERROR_RESPONSE.md)。

## 4. 碰基础设施前的红线

`src/<service>/{core,db,main.py}` 是模板自身的契约层，AI **不要主动重构**。如果业务逼着你改这里，先评估是否能在 domain 层解决；确实要改时遵循：

| 文件 | 允许改 | 禁止改 |
|---|---|---|
| `core/config.py` | 加新字段（带默认值、类型注解、`Field(description=...)`） | 改 `Settings` 的 `model_config` / 加载优先级（Errata #4 已固化）|
| `core/errors.py` | 加新 `AppError` 子类 / 加 `_HTTP_STATUS_CODES` 条目 | 改全局 handler 的响应结构 / `ProblemDetail` 字段（影响所有调用方）|
| `core/idempotency.py` | 加新 `IdempotencyStore` 实现（如 InMemory + Redis 双轨）| 改 `@idempotent` 装饰器语义 / cache key 算法 |
| `core/logging.py` | 加新 logger 配置项 / 加 `_EXTRA_FIELDS` 字段 | 把日志格式从 JSON 改回 plain text |
| `core/middleware.py` | 加业务中间件（在已有中间件之后注册）| 改 CORS 默认拒绝策略 / Request ID 中间件 / 中间件入栈顺序（见 [../architecture/REQUEST_LIFECYCLE.md](../architecture/REQUEST_LIFECYCLE.md)）|
| `db/base.py` | 加新 mixin / 公共列 | 改 `lazy='raise'` 默认（Errata #7 已固化）|
| `db/engine.py` / `db/session.py` | — | **任何修改**都需要人工 review；会影响所有 domain |
| `main.py` | 注册路由 / 加 lifespan 钩子 / 加新 middleware | 改 `create_app()` 签名 / 改异常 handler 注册顺序 / 改 `_custom_openapi` 内 `_PROBLEM_STATUS_CODES` 列表 |
| `api/v1/health.py` | 加 startup probe 自定义检查（`app.state.startup_complete`）| 改 `/healthz` `/readyz` `/startupz` 路径名 |

**触发了红线就停下来问**，不要自作主张改完再说。

## 5. 构建与发布层改动

`Makefile` / `pyproject.toml` / `Dockerfile` / `.github/workflows/ci.yml` 的改动会反向影响所有下游服务。AI 改这些之前必须：

1. 对照 `CLAUDE.md` §「7 条 Errata 固化位置」表，确认不破坏已固化决策
2. 改完跑 `make check && make audit` 验证未触发回归
3. 改 Dockerfile / CI 时，跑 `make docker-build` 本地验证镜像还能起来
4. PR 描述里**显式说明**改了哪个 Errata 字段

**禁止**：
- 切换包管理器（uv → pip / poetry）——已定型
- 把 `pyright` 改成 `mypy`，或加同类工具（Errata #2）
- 把 testcontainers 引进来（Errata #6 选 docker compose）
- 删 `redis[hiredis]` 依赖（Idempotency-Key middleware 依赖它）

## 6. AI 容易踩的坑（按真实出错频次）

1. **隐式 lazy load**：写 `obj.related_things` 时如果没在查询里 `selectinload`，会抛 `InvalidRequestError`（Errata #7 `lazy='raise'`）。修法：repository 里加 `select(X).options(selectinload(X.related_things))`。
2. **跨任务复用 AsyncSession**：`asyncio.gather(svc.do_a(), svc.do_b())` 共享同一个 session 会炸。要么串行，要么各自拿独立 session。
3. **Pydantic v1 写法残留**：禁止 `.dict()` / `class Config:` / `@validator`。用 `.model_dump()` / `model_config = ConfigDict(...)` / `@field_validator`。
4. **在 router 内构造 ORM 对象**：永远走 `schemas → service → repository`，不要 `api.py` 里 `from models import X; X(...)`。
5. **直接抛 `HTTPException`**：用 `AppError`（见 §3 异常约定）。
6. **`print` 替代 logging**：日志走 `logging.getLogger(__name__)`；测试可 `print`，生产代码不行。
7. **`requests` / `urllib`**：HTTP 客户端统一 `httpx`（async 友好，已是 dev 依赖）。
8. **静默 opt-out `@idempotent`**：Generator v0.4.6 起 POST 端点默认带装饰器。如果你删掉装饰器但**没**把这个决定写进 PR 描述 / commit message，reviewer 会以为是疏漏。要 opt-out 就在 commit message 里说清楚"该端点天然幂等 / 不需要客户端去重，因此移除"。
9. **`@idempotent` 标的路由调用方不传 `Idempotency-Key`**：middleware 会 log warning 但放行——不报错。生产调用方要养成传 header 的习惯。
10. **`/readyz` debug=True 时打印异常 `str(e)`**：会泄露 DSN 密码。一律 `type(e).__name__`，参考 `health.py:38`。

## 7. 提交前自检清单

AI 在声称「功能做完」前**必须**自己跑过下列命令并确认全绿：

```bash
make check          # ruff format + ruff check + pyright + pytest（排除 integration）
make coverage       # 覆盖率门槛 85%（fail_under per pyproject）；CI fast lane 强制，提交前先自己过
# 若改了 db / migration / models：
make check-db       # schema drift 检测；生产 / 共享库迁移仍需单独授权
# 若改了 Dockerfile：
make docker-build
# 若改了 scripts/new_module.py 或它的模板：
make smoke-generator  # E2E：跑一遍 new-module + make check，验证模板"开箱即过 check"
```

**不要**：
- 在没跑过的情况下声称「测试通过」——按全局约定（CLAUDE.md「事实准确性」），无法执行测试时必须明说原因
- `--no-verify` skip 任何 pre-commit hook
- 静默忽略 ruff / pyright 报错——要么修，要么在 PR 描述里写明原因

## 8. 改完了同步 docs/

代码改动**必须同步**改对应文档，否则视为未完成：

| 改了什么代码 | 同步改 |
|---|---|
| `core/*.py` | `docs/architecture/<对应主题>.md` |
| `scripts/new_module.py` 模板 | `docs/standards/CODE_GENERATOR.md` |
| 加表 / 改列（`domains/*/models.py`） | `make schema-doc` 重生 `docs/architecture/DATA_MODEL.md`（生成物，勿手改） |
| 加新 Settings 字段 | `docs/architecture/REQUEST_LIFECYCLE.md` 配置表 |
| 新加 Make target | `docs/PROJECT_OVERVIEW.md` 快速命令段 |
| 解决某项 known deviation | `docs/tech-debt/KNOWN_DEVIATIONS.md` 划除该项 |
| ADR Open Q 决议 | `docs/tech-debt/OPEN_QUESTIONS.md` 划除该项 |

drift 是 bug——见 [INDEX.md](../INDEX.md) "文档维护原则"。

## 9. 当本规则与 generator 冲突时

`CODE_GENERATOR.md` 是**生成器自身**的契约（CLI 行为、模板内容）。本规则是**使用者**的契约。两者冲突时：

- 生成器输出的代码不符合本规则 → 修生成器模板，不要让 AI/人事后修补
- 本规则没覆盖的边界 → 先读 开发规范文档「Web 服务」段，仍无解时在 PR 里提出来，**不要默选**

## 10. 不在本规则范围

- 业务建模与领域设计（看具体项目的 PRD）
- 性能调优（看 开发规范文档 §5 与 开发规范文档 §性能）
- 安全细节（看 开发规范文档 §安全基线）
- Java/Python 跨语言协同（看 ADR 跨语言协同 ADR，本仓 stub 在 [../reference/CROSS_LANGUAGE_ADR.md](../reference/CROSS_LANGUAGE_ADR.md)）
