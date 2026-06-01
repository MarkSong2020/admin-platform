# 项目概览

> **这是什么**：团队 Python Web 服务的脚手架模板。克隆 → 改名 → 跑 → 加业务，30 分钟出可用服务。
>
> **为何存在**：把团队仓 ADR `0001-cross-language-conventions.md` 中 Python 侧应当实现的所有契约**一次性 baseline 化**，让新建服务不必每次重复实现错误响应 shape / Request ID / Idempotency-Key / 健康检查 / 分页 envelope / OpenAPI 契约。

## 一页讲清

```
┌─────────────────────── HTTP 入站 ───────────────────────┐
│                                                          │
│   CORS middleware ──► IdempotencyMiddleware              │
│      (whitelist)        (Redis cache, @idempotent only)  │
│                                                          │
│             ──► RequestIDMiddleware                      │
│                   (X-Request-ID + W3C traceparent)       │
│                                                          │
│             ──► [routes]                                 │
│                                                          │
│             ──► register_exception_handlers              │
│                   (AppError → ProblemDetail RFC 9457)    │
│                                                          │
└──────────────────────────────────────────────────────────┘

  │
  ▼  你的业务模块（make new-module name=order [--with-model]）

  src/<service>/domains/order/
  ├── schemas.py    Pydantic DTO + OrderPage (分页 envelope)
  ├── service.py    业务用例（事务边界、抛 AppError）
  ├── repository.py 数据访问（async session）
  ├── api.py        FastAPI router (Annotated[Service, Depends])
  └── models.py     SQLAlchemy 2.x typed mapping （含 --with-model 时）
```

## 现状（v0.5.3）

- **模板里程碑**：v0.5.3 — 完整演进 → [../CHANGELOG.md](../CHANGELOG.md)。`pyproject.toml [project].version` 是业务实例初始版本号（与模板版本不同源）；v0.5.0 起里程碑 vs audit-build 分离，详见 CHANGELOG 头部「版本号语义」段
- **2 个 example domain**（v0.5.0 / v0.5.1）：`domains/todo/` 单 domain 教科书蓝本 + `domains/tag/` 多对多关联（`lazy="raise"` + `selectinload` + N+1 守门 + 跨域 `ON DELETE CASCADE`）→ 详见 [`architecture/EXAMPLE_DOMAIN.md`](./architecture/EXAMPLE_DOMAIN.md)
- **代码 docstring 一致简体中文**（v0.5.2）：generator 模板 + core/db/health ~2100 行翻译；后续 `make new-module` 生成出来的 domain 代码直接中文（AI_CODING_RULES.md §0 固化）
- **测试**：`make check` 189 ✓（unit + api，ruff + pyright + pytest）/ `make test-integration` 29 selected ✓（本地 db-only：24 passed / 5 redis skipped；CI strict Redis 模式应全跑）/ `make coverage` 门槛 85%（`fail_under = 85`，实测 ~87.19%）
- **Python**：3.14（`.python-version` 锁定，`requires-python = ">=3.14"`），uv 包管理
- **核心栈**：FastAPI + SQLAlchemy 2.x async + Alembic + Redis（idempotency in-flight lock + cache-replay）+ asyncpg
- **CI 平台**：`.github/workflows/ci.yml` 是参考资产（可直接 fork 跑）；真实 CI 平台由业务团队按 ADR 决议自选，见 [operations/CI_MIGRATION.md](./operations/CI_MIGRATION.md)
- **KNOWN_DEVIATIONS**：#1-#6 / #9 / #10 已关；剩 #7 / #11 / #12 / #13 / #14 按各自「触发条件」等待，不主动重写（[tech-debt/KNOWN_DEVIATIONS.md](./tech-debt/KNOWN_DEVIATIONS.md)）

## 已落地的契约（对应 ADR 0001 章节）

| ADR | 实现位置 | 守门测试 |
|---|---|---|
| §1 ProblemDetail RFC 9457 8 字段 shape | `core/errors.py` `ProblemDetail` + `_payload` | `tests/unit/test_openapi_contract.py` |
| §2 HTTP 状态码 + §3 `framework.{REASON}` 显式映射 | `core/errors.py` `_HTTP_STATUS_CODES`（16 项） | `tests/api/test_health.py::test_404_returns_unified_error_shape` |
| §4 X-Request-ID 32-char hex + W3C `traceparent` 解析 | `core/middleware.py` `_resolve_ids` | `tests/api/test_access_log.py`（含 hex 格式 + traceparent 5 测试） |
| §6 三轨健康检查 `/healthz` `/readyz` `/startupz` | `api/v1/health.py` | `tests/api/test_health.py` |
| §7.5 分页 envelope `{Name}Page` | generator 模板 `TEMPLATE_SCHEMAS` + `TEMPLATE_SERVICE` + `TEMPLATE_API_*` | 生成模块自带 |
| §8 OpenAPI 命名 `{plural}_{action}` + 422 schema → ProblemDetail | generator 模板 + `main.py` `_custom_openapi` | `tests/unit/test_openapi_contract.py` 3 项守门 |
| §9 JSON log 毫秒+Z + level=WARN 4-char | `core/logging.py` `_adr_timestamp` + `addLevelName` | `tests/unit/test_logging.py` 4 项 |
| §10 配置 `APP_*` env_prefix | `core/config.py` | `tests/unit/test_config.py` |
| §11 Idempotency-Key middleware + SET NX in-flight lock + cache replay（v0.4.9） | `core/idempotency.py` | `tests/unit/test_idempotency.py` 15 项 |

## 快速命令

```bash
make init                          # uv sync --all-extras --dev
make dev                           # http://127.0.0.1:8000/healthz
make check                         # ruff format + ruff check + pyright + pytest (no integration)
make new-module name=order         # 生成 5 层业务模块
make new-module name=product with-model=1   # 含 ORM model
make smoke-generator               # 改 generator 后 E2E 烟测（new-module + check + cleanup）
make compose-up && make migrate    # 起 PostgreSQL + 应用 baseline migration
make test-integration              # 集成测试（需 docker）
```

完整命令清单：`make help`

## 不在范围内（避免范围膨胀）

- 前端 / SDK 自动生成 / Sentry / OTel Collector / K8s manifests / Helm chart
- 内部 RPC（gRPC / Thrift）—— 团队不用
- 业务专属 channels / 风控 / 合规等垂直域代码

## 维护者

- Baseline + ADR：team-backend
- Java 协同仓：`spring-boot-scaffold`（独立维护，参照同一 ADR）
- 跨语言 ADR：`~/IdeaProjects/team-engineering-adr/`（**正本**，本仓为引用）

## 下一步看哪

→ [INDEX.md](./INDEX.md) 按角色找入口
→ [架构详情](./architecture/EXAMPLE_DOMAIN.md) 蓝本 domain 解读
→ [CHANGELOG](../CHANGELOG.md) 完整版本演进（v0.1 → v0.5.3）
