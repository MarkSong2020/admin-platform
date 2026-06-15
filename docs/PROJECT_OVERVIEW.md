# 项目概览

> **这是什么**：单租户后台管理脚手架应用（`v0.0.1`，对标 RuoYi / 若依）。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。
>
> **为何存在**：在团队脚手架的工程 baseline（错误响应 shape / Request ID / Idempotency-Key / 健康检查 / 分页 envelope / OpenAPI 契约）之上，长出 RuoYi 风格的 RBAC / 审计 / 字典 / 前端，做成对标若依的 Python 后台脚手架。

## 一页讲清

```
┌────────────────── HTTP 入站（外层 → 内层）──────────────────┐
│                                                          │
│   RequestIDMiddleware  (X-Request-ID + W3C traceparent)  │
│     ──► CORS middleware       (whitelist)                │
│     ──► AuthMiddleware        (JWT，auth_enabled 时)      │
│     ──► IdempotencyMiddleware (Redis cache, @idempotent) │
│     ──► [routes]                                         │
│     ──► register_exception_handlers                      │
│           (AppError → ProblemDetail RFC 9457)            │
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

## 现状（v0.0.1 — P0–P4 全落地 + P5 文件管理 / Excel 导入导出落地，对标 RuoYi）

- **应用版本**：`v0.0.1`（`pyproject.toml [project].version`）。进度：JWT 认证 + Argon2 + user 五层 CRUD + CLI 建超管 ✓；P0.9 单租户回归 ✓；P1 RBAC（部门/角色/菜单/岗位 + RuoYi 数据权限 + getInfo/getRouters + audit_event.v1）✓；P1.4 登录增强（refresh 轮换/验证码/限流）✓；P1.5 安全加固 ✓；P2 审计持久化（audit_events + login_logs + IP/UA + operlog/logininfor 查询）✓；P3 字典·参数·通知 ✓；P4a–P4c 服务/缓存监控 + 在线用户 + 定时任务（APScheduler + PG leader election + DB claim + handler registry 白名单）✓；P5 文件管理（对标 RuoYi sys_oss：`domains/file/` 五层 + `storage.py` StorageBackend 抽象/LocalFileStorage，零新依赖；扩展名白名单 + 魔数校验 + 流式上传下载 + 软删 + commit 后物理删；6 权限点 `system:file:*`）✓；P5 Excel 导入导出（对标 RuoYi 导入导出：通用 `admin_platform/excel/` reader/writer/schemas 零 domain 知识 + import-linter C10 叶子契约；post 绑定 import/export 2 端点 + formula injection 防御 + 一步全有全无 + 全量错误 + 2 权限点 `system:post:{import,export}`；openpyxl 3.1.5，无新迁移）✓。**P5 范围重新圈定（2026-06-11 拍板 + Codex PK）**：砍 RuoYi 在线 codegen + introspection 逆向（AI 时代过时），保留 `make new-module` CLI（agent 生成的「确定性护栏」，非 codegen）。下一步 P6 Vue 前端（P5 工具全落地）。对标路线图 → [`specs/2026-06-04-ruoyi-parity-roadmap.md`](specs/2026-06-04-ruoyi-parity-roadmap.md)
- **方向变更（2026-06-05）**：原 SaaS 多租户定位已废弃，回归单租户对标 RuoYi 本体。多租户机制（`TenantMixin` / `tenant_filter` / `tenants` 表）已拆除，背景见 [`architecture/MULTI_TENANCY.md`](./architecture/MULTI_TENANCY.md) 废弃说明
- **测试**：`make check` 650 ✓（fast lane：unit + api，ruff + pyright + pytest，不含 integration）/ `make test-integration` 208 ✓（需本地 DB + Redis）/ `make coverage` 门槛 85%（v0.0.1 起已接入 CI fast lane 强制）
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
make coverage                      # pytest --cov（fail_under 85%；CI fast lane 强制）
make new-module name=order         # 生成 5 层业务模块
make new-module name=product with-model=1   # 含 ORM model
make smoke-generator               # 改 generator 后 E2E 烟测（new-module + check + cleanup）
make compose-up && make migrate    # 起 PostgreSQL + 应用 Alembic 迁移（当前 head 0019）
make schema-doc                    # 从 ORM models 重生 docs/architecture/DATA_MODEL.md（无需 DB）
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
