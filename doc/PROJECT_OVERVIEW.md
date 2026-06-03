# 项目概览

> **这是什么**：多租户 admin 平台应用（`v0.0.1`，P0 多租户认证地基开发中）。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。
>
> **为何存在**：在团队脚手架的工程 baseline（错误响应 shape / Request ID / Idempotency-Key / 健康检查 / 分页 envelope / OpenAPI 契约）之上，长出 SaaS 多租户的 fail-closed 隔离 + JWT 认证，目标 RBAC / 审计 / admin 业务域。

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

## 现状（v0.0.1 — P0 多租户认证地基）

- **应用版本**：`v0.0.1`（`pyproject.toml [project].version`）。P0 进度：Task 1 scaffold / Task 2 argon2 密码哈希依赖 + access token TTL / Task 3 fail-closed 租户隔离 ✓；下一步 Task 4 数据模型 + 迁移。完整计划 → [`../docs/specs/2026-06-02-p0-multitenant-auth-foundation.md`](../docs/specs/2026-06-02-p0-multitenant-auth-foundation.md)
- **多租户隔离**（Task 3）：`TenantMixin` 业务表 + `session.info` 上下文；`do_orm_execute` 读广义 fail-closed、`before_flush` 写对称 fail-closed；`SYSTEM_CTX` / 平台超管 bypass。机制说明见 `db/tenant_filter.py`
- **测试**：`make check` 202 ✓（unit + api，ruff + pyright + pytest）/ `make coverage` 门槛 85%
- **Python**：3.14（`.python-version` 锁定，`requires-python = ">=3.14"`），uv 包管理
- **核心栈**：FastAPI + SQLAlchemy 2.x async + Alembic + Redis（idempotency in-flight lock + cache-replay）+ asyncpg + argon2-cffi（密码哈希）+ PyJWT
- **脚手架 lineage**：generator、`.github/workflows/ci.yml`、`tech-debt/KNOWN_DEVIATIONS.md` 继承自模板 v0.5.3。示例域 `domains/todo`/`domains/tag` 已删除（admin 平台不需要，建 domain 用 `make new-module`）。模板演进史 → [../CHANGELOG.md](../CHANGELOG.md)

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
make schema-doc                    # 从 ORM models 重生 doc/architecture/DATA_MODEL.md（无需 DB）
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
→ [CODE_GENERATOR](./standards/CODE_GENERATOR.md) domain 五层骨架解读
→ [CHANGELOG](../CHANGELOG.md) 脚手架 lineage 演进（模板 v0.1 → v0.5.3）
