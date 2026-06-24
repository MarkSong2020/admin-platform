# 架构巡览（ARCHITECTURE_TOUR）

> **受众**：想读代码学架构的人。本文是「带着地图读源码」的导览——每节给一句结论 + 真实文件指针，深挖请跟链接到正本文档。
> **结论先行**：本仓是单租户后台脚手架应用（对标 RuoYi / 若依），核心是「一条可预测的请求链路 + 五层强约束业务模块 + 一组 RuoYi 风格能力域」。读懂 `main.py` 的 `create_app()` 和任意一个 `domains/<x>/` 五件套，就掌握了八成。

---

## 0. 从哪进入

| 你想看 | 入口文件 |
|---|---|
| 应用如何装配（中间件 / 路由 / 生命周期） | [`src/admin_platform/main.py`](../../src/admin_platform/main.py) `create_app()` |
| 一个业务域长什么样 | `src/admin_platform/domains/user/`（已完整五层，纳入 import-linter C1） |
| 基础设施（错误 / 日志 / 鉴权 / 幂等 / 配置） | `src/admin_platform/core/` |
| 表结构速览 | [`../architecture/DATA_MODEL.md`](../architecture/DATA_MODEL.md)（生成物，勿手改） |
| 一页项目概览 | [`../PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md) |

---

## 1. 请求生命周期与中间件链

**结论**：一个 HTTP 请求从外到内穿过 4 个中间件，命中路由后进入「api → service → repository」三步，异常统一被 4 个 handler 翻译成 `ProblemDetail`（RFC 9457）响应，再反向出栈记一条 access log。

### 1.1 中间件入站顺序（以 `main.py` `create_app()` 为真相源）

Starlette 语义：**后 `add_middleware` 的包在外层、请求入站时先执行**。`main.py` 按 Idempotency → Auth → CORS → RequestID 的顺序 `add_middleware`（部分受配置开关 gating），因此真实**入站顺序**是：

```
客户端
  │
  ▼  RequestIDMiddleware        （最外层，always）   core/middleware.py
  ▼  CORSMiddleware             （if cors_allow_origins 非空）
  ▼  AuthMiddleware             （if auth_enabled）    core/auth.py
  ▼  IdempotencyMiddleware      （if idempotency_enabled）  core/idempotency.py
  ▼  路由 handler → api.py → service.py → repository.py
  ▼  register_exception_handlers（AppError → ProblemDetail）  core/errors.py
  │
  响应反向出栈：access log 单条 / 回写 X-Request-ID / 幂等缓存（仅 2xx）
```

> 顺序与 gating 在 [`main.py`](../../src/admin_platform/main.py) `create_app()` 的中间件注释块（约 188–224 行）有逐行说明。**改顺序前必读** [`../architecture/REQUEST_LIFECYCLE.md`](../architecture/REQUEST_LIFECYCLE.md)。

各中间件职责：

- **`RequestIDMiddleware`**（[`core/middleware.py`](../../src/admin_platform/core/middleware.py)）：解析 W3C `traceparent` / 校验 `X-Request-ID`（32-char hex），注入 `request.state.request_id` + ContextVar，请求结束出一条 access log（含 `request_id` / `trace_id` / `method` / `path` / `status_code` / `duration_ms`）。详见 [`../architecture/OBSERVABILITY.md`](../architecture/OBSERVABILITY.md)。
- **`CORSMiddleware`**（FastAPI 内置）：仅当 `cors_allow_origins` 非空时注册，白名单加载、截获 preflight（preflight 拒绝是 transport-level，不走 `ProblemDetail` shape）。
- **`AuthMiddleware`**（[`core/auth.py`](../../src/admin_platform/core/auth.py)）：JWT Bearer 鉴权。`auth_enabled=True` 时，非公开路径必须带 `Authorization: Bearer <token>`，校验通过后把 `user_id` / `token_sub` / `token_scope` 写入 `request.state`；公开路径（health / auth 端点等，`is_public_path` 前缀匹配）放行。
- **`IdempotencyMiddleware`**（[`core/idempotency.py`](../../src/admin_platform/core/idempotency.py)）：仅对 `POST` + 标了 `@idempotent` + 带 `Idempotency-Key` 的请求生效；Redis `SET NX` 抢 in-flight 锁 + 2xx 后 cache-replay。强 at-most-once 边界（金额扣减 / 订单创建）见 [`../architecture/REQUEST_LIFECYCLE.md`](../architecture/REQUEST_LIFECYCLE.md)「强 at-most-once 边界」段。

### 1.2 异常处理链

命中路由后抛出的异常由 `register_exception_handlers`（[`core/errors.py`](../../src/admin_platform/core/errors.py)）统一翻译成 8 字段 `ProblemDetail`：

| handler | 触发 | `type` 输出 |
|---|---|---|
| `_app_error` | `AppError` | `exc.code`（业务定，`{service}.{ERROR_CODE}`） |
| `_http_error` | `StarletteHTTPException`（404 / 405 等） | `framework.{NAME}` |
| `_validation_error` | `RequestValidationError`（Pydantic 入参） | `framework.VALIDATION_FAILED`（422） |
| `_unhandled_error` | 其他所有 `Exception` | `framework.INTERNAL_ERROR`（500） |

字段语义见 [`../architecture/ERROR_RESPONSE.md`](../architecture/ERROR_RESPONSE.md)。

### 1.3 启动 / 关闭（lifespan）

`main.py` 的 `lifespan` 负责：`configure_logging()` → `init_observability()` → 注册审计 sink（`configure_audit_sink`）→ 用 `AsyncExitStack` 保证 DB pool / Redis / 调度器 LIFO 干净释放。生产可设 `APP_STARTUP_EAGER_CONNECT=true` 让 `_eager_probe_dependencies`（`SELECT 1` + `redis.ping()`）在 startup 阶段 fail-fast；登录防护或调度器启用时也强制探测。

---

## 2. 五层分层

**结论**：每个业务域固定 5 层，跨层 import 由 `make check` 的 import-linter（契约 C1–C8）机检，CI 红线；语义边界（api 不写业务逻辑等）由 code review 兜。

```
HTTP request
  ▼  api.py        路由 + 入参 + 状态码      ← 禁止业务判断、禁止 import repository/models
  ▼  service.py    业务用例 + 事务边界        ← AppError 在这里抛；禁止 fastapi.Request / HTTPException
  ▼  repository.py 数据访问（async session） ← SQL 在这里；禁止抛业务异常
     schemas.py    Pydantic DTO（含分页 envelope {Name}Page）
     models.py     SQLAlchemy 2.x typed mapping（仅 --with-model 时）
```

- 事务物理边界在 `db/session.py` `get_session`（`async with session.begin()` 包裹整个 request：正常 COMMIT / 抛异常 ROLLBACK）；DI 组合根在 `domains/<x>/deps.py`，不在 `api.py`（保证 api 不直接 import repository）。
- 新增业务模块**必走 `make new-module`**，不要手抄已有 domain（见 [`../standards/CODE_GENERATOR.md`](../standards/CODE_GENERATOR.md)）。

→ 完整职责矩阵、禁止项、DTO 三件套、为什么是 5 层：[`../architecture/LAYERED_DESIGN.md`](../architecture/LAYERED_DESIGN.md)

---

## 3. 核心能力巡览

每块给一句话定位 + 入口目录 + 设计正本（spec）。spec 总览见 [`../archive/specs/INDEX.md`](../archive/specs/INDEX.md)。

### 3.1 认证地基（P0）

JWT 签发 / 校验（PyJWT）+ Argon2 密码哈希（argon2-cffi）+ user 五层 CRUD + CLI 建超管。鉴权中间件 [`core/auth.py`](../../src/admin_platform/core/auth.py)，密码与 token 工具 [`core/security.py`](../../src/admin_platform/core/security.py)。

### 3.2 RBAC：部门 / 角色 / 菜单 / 岗位 + 数据权限 + getInfo / getRouters（P1）

RuoYi 风格 RBAC：`domains/dept`（部门树）/ `domains/role`（角色 + 菜单·部门数据权限绑定）/ `domains/menu`（菜单树，M/C/F 类型）/ `domains/post`（岗位）；绑定子资源在 `domains/rbac_binding`。两个前端契约端点在 [`api/v1/rbac.py`](../../src/admin_platform/api/v1/rbac.py)：

- `GET /api/v1/auth/user-info`（getInfo）：当前用户 + 角色 code + 权限标识（超管合成 `["superadmin"]` / `["*:*:*"]`）。
- `GET /api/v1/menus/routers`（getRouters）：用户可见菜单树 → 若依 RouterVO 动态路由 payload（停用账号返回空树）。

> 权限 / 菜单 Provider 在组合根经 `dependency_overrides` 注入（`DbPermissionProvider` / `DbMenuProvider`），避免 core → domains 耦合。正本 [`../archive/specs/2026-06-05-p1.0-rbac-mechanism.md`](../archive/specs/2026-06-05-p1.0-rbac-mechanism.md)；登录增强（refresh 轮换 / 验证码 / 限流）[`../archive/specs/2026-06-09-p1.4-login-enhancement.md`](../archive/specs/2026-06-09-p1.4-login-enhancement.md)；安全加固与审计织入 [`../archive/specs/2026-06-09-p1.5-rbac-binding-audit.md`](../archive/specs/2026-06-09-p1.5-rbac-binding-audit.md)。

### 3.3 审计持久化（P2）

`audit_events` 表（成功审计在事务内原子写、失败缓冲独立 flush）+ `login_logs`，由 `audit/sink.py` 的 `DbAuditSink` 落库（`audit_persistence_enabled=false` 时退化为仅 logger）。中间件补 IP / UA；监控查询 API 在 `domains/monitor`（operlog / logininfor 只读查询）。正本 [`../archive/specs/2026-06-09-p2-audit-persistence.md`](../archive/specs/2026-06-09-p2-audit-persistence.md)。

### 3.4 字典 / 参数 / 通知（P3 运营配置）

`domains/dict`（类型 + 数据双资源，数据 FK → `dict_types.id` 且 RESTRICT、单默认值生成列唯一索引）/ `domains/config`（参数热更新走读穿 DB、内置项禁删可切换）/ `domains/notice`（通知公告，不渲染 raw HTML）。正本 [`../archive/specs/2026-06-09-p3-operational-config.md`](../archive/specs/2026-06-09-p3-operational-config.md)。

### 3.5 服务 / 缓存监控 + 在线用户（P4a / P4b）

`domains/monitor`：服务监控（psutil 取 CPU / 内存 / 磁盘 / 进程）+ 缓存监控（Redis `INFO` 白名单 + 不可达时降级）+ 在线用户（由活动 refresh token family 派生，强制下线 audited、仅撤 refresh）。正本 [`../archive/specs/2026-06-10-p4-monitoring-tasks.md`](../archive/specs/2026-06-10-p4-monitoring-tasks.md)。

### 3.6 定时任务（P4c，APScheduler）

`domains/scheduled_task`：`AsyncIOScheduler` + **DB leader election + DB execution claim 双层防多 worker 重复执行**（MySQL GET_LOCK 迁移在阶段 3 落地）+ **handler registry 白名单防 RCE**（管理员只能选预注册的 `handler_key`，不能传任意调用串）+ 手动触发 + 执行日志。调度器在 lifespan 由 `SchedulerController` 启停，`scheduler_enabled` 默认 `False`（CRUD / 手动触发不依赖调度器）。同 spec [`../archive/specs/2026-06-10-p4-monitoring-tasks.md`](../archive/specs/2026-06-10-p4-monitoring-tasks.md) §4。

### 3.7 文件管理（P5，对标 RuoYi sys_oss）

`domains/file` 五层 + `storage.py`（`StorageBackend` 抽象 + `LocalFileStorage`，零新依赖）。5 端点 `/api/v1/files`：list / query / upload（multipart 流式）/ download（`StreamingResponse` 流式）/ remove（软删 + commit 后 `BackgroundTasks` 物理删）。安全模型 defense-in-depth：扩展名白名单 + 魔数头校验 + 边写边累计 size/sha256 + `object_key=uuid4` 分桶 + 路径穿越守卫 + Content-Disposition 注入防御 + `X-Content-Type-Options: nosniff`。正本 [`../archive/specs/2026-06-11-p5-file-management.md`](../archive/specs/2026-06-11-p5-file-management.md)。

### 3.8 Excel 导入导出（P5）

通用机制 `src/admin_platform/excel/`（reader / writer / schemas，零 domain 知识的顶层叶子模块，受 import-linter C10 契约约束——禁 import fastapi / sqlalchemy / domains / core）。第一版绑定岗位：`POST /api/v1/posts/import`（一步全有全无 + 全量错误、始终 200 + summary）+ `GET /api/v1/posts/export`（含 formula injection 防御）。新依赖 openpyxl 3.1.5。正本 [`../archive/specs/2026-06-11-p5-excel-import-export.md`](../archive/specs/2026-06-11-p5-excel-import-export.md)。

---

## 4. 历史 / 已废弃方向（读旧代码或旧 commit 时会撞到）

**多租户已废弃**：本仓 P0 曾是 SaaS 共享库多租户设计（`tenant_filter` / `TenantMixin` / `tenants` 表 / `session.info` 租户上下文 / `system_session` bypass）。2026-06-05 决策**回归单租户**对标 RuoYi 本体，P0.9 已拆除全部多租户机制，数据权限改走 RuoYi 风格 dept 部门（见 §3.2）。

> [`../architecture/MULTI_TENANCY.md`](../architecture/MULTI_TENANCY.md) 标注为历史/废弃文档，**不反映现行架构**，仅作决策留痕。背景见 [`../archive/specs/2026-06-04-ruoyi-parity-roadmap.md`](../archive/specs/2026-06-04-ruoyi-parity-roadmap.md) §3「单租户回归重构」。

---

## 5. 设计决策索引

所有阶段决策（P0 → P6）的 spec 总览：[`../archive/specs/INDEX.md`](../archive/specs/INDEX.md)。对标 RuoYi 的整体路线图：[`../archive/specs/2026-06-04-ruoyi-parity-roadmap.md`](../archive/specs/2026-06-04-ruoyi-parity-roadmap.md)。

| 阶段 | spec |
|---|---|
| 对标路线图 | [`2026-06-04-ruoyi-parity-roadmap.md`](../archive/specs/2026-06-04-ruoyi-parity-roadmap.md) |
| P0 多租户认证地基（已废弃方向） | [`2026-06-02-p0-multitenant-auth-foundation.md`](../archive/specs/2026-06-02-p0-multitenant-auth-foundation.md) |
| P1.0 RBAC 机制 | [`2026-06-05-p1.0-rbac-mechanism.md`](../archive/specs/2026-06-05-p1.0-rbac-mechanism.md) |
| P1.4 登录增强 | [`2026-06-09-p1.4-login-enhancement.md`](../archive/specs/2026-06-09-p1.4-login-enhancement.md) |
| P1.5 RBAC 绑定 + 审计织入 | [`2026-06-09-p1.5-rbac-binding-audit.md`](../archive/specs/2026-06-09-p1.5-rbac-binding-audit.md) |
| P2 审计持久化 | [`2026-06-09-p2-audit-persistence.md`](../archive/specs/2026-06-09-p2-audit-persistence.md) |
| P3 运营配置 | [`2026-06-09-p3-operational-config.md`](../archive/specs/2026-06-09-p3-operational-config.md) |
| P4 监控 / 定时任务 | [`2026-06-10-p4-monitoring-tasks.md`](../archive/specs/2026-06-10-p4-monitoring-tasks.md) |
| P5 文件管理 | [`2026-06-11-p5-file-management.md`](../archive/specs/2026-06-11-p5-file-management.md) |
| P5 Excel 导入导出 | [`2026-06-11-p5-excel-import-export.md`](../archive/specs/2026-06-11-p5-excel-import-export.md) |
| P6 前端设计 | [`2026-06-11-p6-frontend-design.md`](../archive/specs/2026-06-11-p6-frontend-design.md) |

---

## 相关文档

- 请求生命周期 / 中间件链细节 → [`../architecture/REQUEST_LIFECYCLE.md`](../architecture/REQUEST_LIFECYCLE.md)
- 五层职责矩阵 → [`../architecture/LAYERED_DESIGN.md`](../architecture/LAYERED_DESIGN.md)
- 数据模型速览 → [`../architecture/DATA_MODEL.md`](../architecture/DATA_MODEL.md)
- 可观测性（日志 / Request ID / Trace） → [`../architecture/OBSERVABILITY.md`](../architecture/OBSERVABILITY.md)
- 错误响应（ProblemDetail / AppError） → [`../architecture/ERROR_RESPONSE.md`](../architecture/ERROR_RESPONSE.md)
- 术语表 → [`../architecture/GLOSSARY.md`](../architecture/GLOSSARY.md)
- 编码规范汇总 → [`../STANDARDS.md`](../STANDARDS.md)
- 上手指南 → [`./GETTING_STARTED.md`](./GETTING_STARTED.md)
- 当脚手架二次开发 → [`./USE_AS_SCAFFOLD.md`](./USE_AS_SCAFFOLD.md)
