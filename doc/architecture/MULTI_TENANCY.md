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

**RLS 加固（P0.5）**：Task 12 spike 结论是 P0 不落地、留 P0.5，见本文 §9。

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
  必查任何 `text(`。DB 层兜底靠 RLS，但 Task 12 spike 结论是 P0 暂不上（见 §9）。
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
## 9. RLS（DB 层加固）—— Task 12 spike 结论：P0 不落地，留 P0.5

本地库实测 + Codex PK 的结论。**P0 维持应用层 fail-closed，不合入 RLS DDL**：

- **GUC 机制可行**：`get_session` 事务内 `SELECT set_config('app.current_tenant', :tid, true)` 是**事务级**、
  commit/rollback 自动重置；asyncpg 连接池复用连接**不串租户**（实测：事务内读到设定值、commit 后新事务
  读到空 `''`）。前提是所有租户 SQL 都在 `get_session` 的 `session.begin()` 根事务内（`engine.connect()`
  直连绕过，不受保护）。
- **当前 DB role 是 superuser → RLS 直接失效** ★：本地 compose 的 `app` 用户 `is_superuser=on` /
  `rolbypassrls=true`，**superuser 永远 bypass RLS**（连 `FORCE ROW LEVEL SECURITY` 也挡不住——实测建表
  + policy 后租户 1 / 2 / 无 setting 全见 3 行）。上 RLS 的**前置条件**是先 provision 一个**非 superuser、
  无 BYPASSRLS** 的应用专用 DB role + 配套 GRANT —— 属 ops/基础设施工作，超出 P0「认证地基」范围。
- **为什么 P0 不上**：`ENABLE ROW LEVEL SECURITY` 后无匹配 policy 默认拒绝，会让现有 login/CLI/raw SQL
  从"查得到"变空结果；且需先解决非 superuser role + `system_session` 拆 tenant-scoped/maintenance 两语义
  + 全 `TenantMixin` 表 policy，风险中高。而应用层 fail-closed 已提供隔离；RLS 的真实增量是补 raw SQL
  漏洞（§6），但当前租户查询路径**无** raw SQL（仅 `/readyz` 的平台级 `SELECT 1`），增量收益暂不紧迫。
- **P0.5 spike 清单**（留待）：① 建非 superuser 应用 role + GRANT；② `get_session` 注入处加
  `set_config('app.current_tenant', tid, true)` / `set_config('app.is_platform', ...)`；③ `users` 单表 policy
  `USING (current_setting('app.is_platform',true)='1' OR tenant_id = NULLIF(current_setting('app.current_tenant',true),'')::bigint)` + 同款 `WITH CHECK`（`current_setting(...,true)` 第二参必需：缺失返 NULL 而非报错
  → fail-closed）；④ 平台超管走 policy 内 `app.is_platform='1'` 例外（**不**给共享连接池 role 授 `BYPASSRLS`）；
  ⑤ 集成测试：连接池复用不串 + raw `text()` 被拦 + 无 setting 默认空 + 平台超管显式可见；通过后 P1 扩到全
  `TenantMixin` 表。
