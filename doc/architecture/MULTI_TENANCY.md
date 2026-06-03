# 多租户隔离（MULTI_TENANCY）

> P0 认证地基的隔离机制正本。决策来源：[`docs/specs/2026-06-02-p0-multitenant-auth-foundation.md`](../../docs/specs/2026-06-02-p0-multitenant-auth-foundation.md)
> 的 ADR-A/B/C/E。本文是给开发者读的「机制怎么用、红线在哪」；逐 Task 实施细节看 spec。

## 0. 一句话

SaaS 共享库多租户：业务表带 `tenant_id`，**默认 fail-closed** —— 没有租户上下文的业务 ORM
查询直接抛错，绝不静默放行。隔离绑在 `session.info`（由 `get_session` 从 `request.state` 注入），
平台超管 / 系统任务走**显式** `system_session()` bypass。

## 1. ADR-A：应用层 fail-closed 隔离（主）+ RLS 加固（P0.5）

机制在 [`db/tenant_filter.py`](../../src/admin_platform/db/tenant_filter.py)，注册到
[`db/engine.py`](../../src/admin_platform/db/engine.py) 的 `AppSession`（见下「为什么注册到 sync 类」）。

**读路径**（`do_orm_execute` 事件）：

- `session.info["tenant_ctx"]` 三态：
  - `{"tenant_id": int, "platform": bool}` —— 业务请求，`with_loader_criteria` 自动追加
    `WHERE tenant_id = :current`（`platform=True` 时 bypass，平台超管跨租户可见）；
  - `SYSTEM_CTX`（哨兵对象）—— 系统/登录/CLI，bypass 全过滤，调用方自负显式过滤；
  - **缺失** —— 业务 ORM SELECT 直接抛 `TenantContextMissing`（fail-closed）。
- **广义拦截**（不按表收窄）：无上下文时**任何** ORM SELECT 都拦，连平台表也拦。原因：
  `select(平台表).join(租户表)` 时 `ORMExecuteState.all_mappers` 会漏掉 join 进来的租户表
  （实测假阴性），按表收窄会让这类 join 在无上下文时 fail-open 泄漏。代价为零：HTTP 路径
  `get_session` 必带上下文，无上下文的纯平台查询显式走 `system_session()`。

**写路径**（`before_flush` 事件，与读对称 fail-closed）：

- 有上下文 → `session.new` 里 `tenant_id is None` 的 `TenantMixin` 对象自动按当前租户填充；
- 无上下文却 flush 含 `TenantMixin` 的对象（**即便显式带了 tenant_id**）→ 抛 `TenantContextMissing`，
  堵住裸 session 绕过上下文写跨租户数据；纯平台表（无 `TenantMixin`）写放行。

**为什么注册到 sync_session_class**：async 下 `SessionEvents`（`do_orm_execute`/`before_flush`）
**不能**注册到 `async_sessionmaker` 实例——事件不触发、过滤静默失效（比 fail-open 更危险，它
"假装"在过滤）。必须注册到 `async_sessionmaker(sync_session_class=AppSession)` 的 `AppSession`。
`test_tenant_filter` 的过滤断言同时充当"事件确实触发"的探针：注册目标错了立即变红。

**RLS 加固（P0.5 / Task 12）**：见本文 §6。

## 2. ADR-B：租户/超管模型 —— 单 user 表 + PLATFORM 哨兵租户

- 单 [`users`](../../src/admin_platform/domains/user/models.py) 表带 `TenantMixin`（`tenant_id`）；
  唯一约束 `uq_users_tenant_username`（同租户内 username 唯一，跨租户可重名）。
- [`tenants`](../../src/admin_platform/domains/tenant/models.py) 是**平台级表**（**不**带 `TenantMixin`，
  不被过滤）——它是隔离边界的另一侧，由平台超管管理。
- 平台超管属哨兵租户 `tenants.code = "PLATFORM"` 且 `users.is_platform_admin = True`，由
  [`cli.py`](../../src/admin_platform/cli.py) 的 `create-platform-admin` 一次性创建（不在 lifespan auto-seed）。
- P0 不预留 dept / data-scope 字段（YAGNI，触发再加迁移）。

## 3. ADR-C：Token —— P0 只发 access token

- 登录只签 **access token**（JWT，TTL **2h**）。claims = `sub`(user_id) / `tenant_id` / `is_platform` /
  `username` / `exp` / `iat`（+ `iss`/`aud` 仅在 config 配置时）。见
  [`core/security.py`](../../src/admin_platform/core/security.py)。
- **`tenant_id` 是 decode 的必需 claim**（缺失即 401）+ 类型校验（`tenant_id` 正整数、`is_platform`
  必 bool）——PyJWT 的 `require` 只查存在不查类型，缺校验则 `tenant_id="42"` 绕过 ORM 过滤、
  `is_platform="false"` 字符串误判超管越权。把 fail-closed 延伸到认证层。
- refresh token / 验证码下放 P1（refresh 须落库 jti 可撤销）；P1 上 refresh 后 access TTL 收回 30min。

## 4. ADR-E：上下文传播 —— session.info，不走 ContextVar

- **背景**：底座中间件是 `BaseHTTPMiddleware`。Starlette 已知问题：`dispatch` 里 `ContextVar.set()`
  的值**不传播到 endpoint**（endpoint 在另一个 anyio task）。若隔离依赖 ContextVar，endpoint 的
  session 读不到 → 隔离静默失效。
- **决策**：[`core/auth.py`](../../src/admin_platform/core/auth.py) 的 `AuthMiddleware` 解 token 后把
  `tenant_id`/`is_platform` 写入 **`request.state`**（跨 task 可靠）；
  [`db/session.py`](../../src/admin_platform/db/session.py) 的 `get_session`（与 endpoint 同 task）从
  `request.state` 读、写入 `session.info["tenant_ctx"]`；`do_orm_execute`/`before_flush` 从
  `session.info` 读。**不引入** `TenantMiddleware`，唯一注入点是 `get_session` + 显式 `system_session`。

## 5. system_session 用法（bypass 的唯一合法口子）

```python
from admin_platform.db.session import system_session

async with system_session() as session:
    # SYSTEM_CTX：bypass 全租户过滤。调用方**必须**显式带 tenant_id 过滤。
    tenant = (await session.execute(select(Tenant).where(Tenant.code == code))).scalar_one_or_none()
    user = (await session.execute(
        select(User).where(User.tenant_id == tenant.id, User.username == username)  # 显式过滤！
    )).scalar_one_or_none()
```

- **只允许**登录（[`domains/auth/service.py`](../../src/admin_platform/domains/auth/service.py)）/ CLI
  （`cli.py`）/ 维护任务用；code review **必查**每个 `system_session(` 调用点是否显式带 `tenant_id`。
- 普通业务 handler 用 `get_session`（自动注入租户上下文），**不得**用 `system_session` 直查业务表。

## 6. 红线与已知边界

- **raw SQL 不被保护** ★：本机制只拦 ORM **Session** 查询。`text()` / 原生 SQL / `engine.connect()`
  直连（如 `/readyz` 的 `SELECT 1`）**不经** `do_orm_execute` 事件 → 跨租户不被保护。code review
  必查任何 `text(`。DB 层兜底靠 RLS（§7 / Task 12）。
- **public 端点误用 `get_session` 直查 `TenantMixin`** → fail-closed 抛 500（而非泄数据），是预期安全
  行为；这类查询应走 `system_session()` + 显式 tenant_id。
- **2h access token 无法撤销** —— P0 已知限制，P1 上 refresh（落库 jti 可撤销）。

## 7. 隔离正确性要点（经 Codex 安全 PK 收紧）

写 repository / 查询时**必须**遵守，否则隔离会被绕过：

| 要点 | 为什么 |
|---|---|
| **读用显式 `select(...).where(id==)` + execute，不用 `session.get`** | `session.get` 命中 identity map 时跳过 SQL、不触发 `do_orm_execute` → 过滤被绕过 |
| **写用 ORM unit-of-work（`add` / `session.delete(obj)`），不用 bulk `update()`/`delete()`** | bulk DML 是非 SELECT，`do_orm_execute` 早 return + `before_flush` 看不到逐对象 → A 租户可按 id 删 B 租户行 |
| **count 用 `select(func.count()).select_from(User)`（ORM 实体）** | 实体形式才被注入 `WHERE tenant_id=`；`select_from(User.__table__)` / raw SQL 绕过，数到跨租户全量 |

落地参照 [`domains/user/repository.py`](../../src/admin_platform/domains/user/repository.py)；端到端验收
见 [`tests/integration/test_tenant_isolation.py`](../../tests/integration/test_tenant_isolation.py)
+ `test_user_crud.py`（含跨租户删→404）；fail-closed 单测见
[`tests/unit/test_tenant_filter.py`](../../tests/unit/test_tenant_filter.py)。

## 8. 待办（follow-up，未做）

- **`before_flush` 校验 `obj.tenant_id == ctx["tenant_id"]`**：当前 `before_flush` 只对 `tenant_id is None`
  的 new 对象自动填充；若业务代码显式 `User(tenant_id=B)` 在 A 租户上下文下，不会被拦。schema 禁掉
  客户端设 `tenant_id` 是**必要但不充分**的防御。加这条校验可让"显式跨租户写"也 fail-closed——但它
  改的是 `tenant_filter.py` 隔离核心（基础设施红线），需单独评估 + 测试，不在 CRUD 任务里顺手改。
- **RLS（Task 12 / P0.5）**：见 spike 结论（本文档由 Task 12 补「RLS 是否落地」一节，或在 §6 标注维持
  应用层 fail-closed 的原因）。
