# Admin Platform — P0 多租户认证地基 实施计划(v2,review 修订版)

> **执行方式(环境中立):** 本计划不依赖任何特定 agent 插件能力。按 Task 顺序执行,**每个 Task 末尾是一个 checkpoint gate**:跑该 Task 的「验收命令」+ 人工审 diff,通过才进下一个 Task。步骤用 `- [ ]` 跟踪。任何"建仓 / commit / 装依赖"动作都需操作者显式确认。
>
> **颗粒度:** 关键地基(租户隔离 / 上下文传播 / 认证签发)给完整代码与测试;重复 CRUD 给接口契约 + 验收点,由执行者对照底座 `python-web-service-template` 的 `domains/todo` 五层模式生成。
>
> **v2 修订来源:** 本版按一轮人工 review 修订,核心改动 = fail-closed 隔离 + session.info 上下文传播(回避 BaseHTTPMiddleware+ContextVar 跨 task 失效)+ P0 去 refresh/验证码 + CLI seed + git archive scaffold。详见末尾「修订记录」。

**Goal:** 用 `python-web-service-template` scaffold 出 `admin-platform` 新仓,落地**默认 fail-closed** 的多租户隔离 + 认证签发地基,跑通"两租户各自登录、数据相互隔离、平台超管跨租户可见、跨租户直取 404、无 tenant 上下文的业务查询直接报错"。

**Architecture:** SaaS 共享库多租户,业务表带 `tenant_id`;隔离用 SQLAlchemy `do_orm_execute` 事件 + `with_loader_criteria` 自动注入过滤,**租户上下文绑定在 `session.info`**(由 `get_session` 依赖从 `request.state` 注入,不走跨 task ContextVar)。缺上下文的业务查询 **fail-closed 抛错**;平台超管 / 系统任务走**显式 system context** bypass。认证在底座「只校验」的 `AuthMiddleware` 上补「签发端」(登录 → access token)。

**Tech Stack:** FastAPI · SQLAlchemy 2.x(async/asyncpg)· Alembic · PyJWT(底座已有)· **passlib[bcrypt](P0 唯一新增 runtime 依赖,走 intake)** · Pytest。继承底座工程约定(RFC 9457 错误、Request ID、分层红线、85% 覆盖率门槛)。

---

## 0. 在整体路线中的位置

```
P0 多租户认证地基   ← 本计划(唯一聚焦,可独立验收)
P1 RBAC + 登录增强   角色/菜单/按钮权限 + 动态菜单 + refresh token + 验证码(独立计划)
P2 审计日志         操作/登录日志(独立计划)
P3 字典/参数        运营可视化配置(独立计划)
P4 定时任务         APScheduler + 管理面板(独立计划)
P5 Excel/OSS        导入导出/文件(独立计划)
P6+ 前端           Vue3 + Element Plus 各模块(独立计划群)
```

本计划**只做 P0**。验证码、refresh token 已从 P0 下放到 **P1**(理由:避免 Pillow/captcha + token 存储表扰乱认证地基)。

---

## 1. 前置架构决策(已 review 定稿)

### ADR-A:多租户隔离 —— 应用层 fail-closed 注入(主)+ RLS 加固(P0.5 spike)

- **机制**:带 `TenantMixin` 的 model,查询经 `do_orm_execute` 自动追加 `WHERE tenant_id = :current`;写入经 `before_flush` 自动填 `tenant_id`。
- **fail-closed(硬规则)**:业务路径的 SELECT 命中 `TenantMixin`、但当前 session **既无 tenant context 又非 system** → **抛 `TenantContextMissing`**,绝不放行裸查询。(对比 v1 的 `tid is None: return` fail-open —— 已废弃。)
- **上下文来源**:`session.info["tenant_ctx"]`,**不是** ContextVar。原因见 ADR-E。
- **RLS**:Postgres 行级安全作为 **P0.5(Task 12)** 加固,spike 验证 asyncpg 连接池下 `SET LOCAL` 稳定后叠加,形成"应用层 + DB 层"双重防御(工程原则①「验证至每层」)。

### ADR-B:租户/超管模型 —— 单 user 表 + PLATFORM 哨兵租户

- 单 `user` 表带 `tenant_id`;平台超管属哨兵租户 `tenant.code = "PLATFORM"`,`user.is_platform_admin = true`。
- `tenant` 表是平台级表(**不带 `TenantMixin`**,不被过滤),由平台超管管理。
- data scope(部门级)P0 不做,`user` **不**预留 dept 字段(YAGNI,触发再加迁移)。

### ADR-C:Token —— P0 只发 access token

- **P0**:登录只签发 **access token**(JWT,TTL 折中 **2h**),claims = `sub`(user_id)、`tenant_id`、`is_platform`、`username`、`exp`、`iat`、`iss`、`aud`。
- **refresh token 下放 P1**,且 P1 必须:**落库存 `jti` + token hash + 可撤销**(不做无状态 refresh)。
- 签名复用底座 `auth_jwt_secret`/`auth_jwt_algorithm`。2h TTL 是"无 refresh 时的可用性折中",P1 上 refresh 后回收到 30min。

### ADR-D:scaffold —— git archive 导出干净快照

- **不用** `cp -R` 全量复制 + `rm -rf .git`(粗暴、带入 .venv/__pycache__、触碰破坏性删除纪律)。
- 改用 `git archive` 只导出底座的 tracked 文件(天然无 `.git`/`.venv`),再 `git init`。

### ADR-E:租户上下文传播 —— session.info,不走 ContextVar ★关键修正

- **背景**:底座中间件是 `BaseHTTPMiddleware`。Starlette 已知问题:`BaseHTTPMiddleware.dispatch` 里 `ContextVar.set()` 的值**不会传播到 endpoint**(endpoint 在另一个 anyio task)。若隔离过滤依赖 ContextVar,endpoint 的 session 读不到 → 隔离静默失效。
- **决策**:
  1. `AuthMiddleware` 解 token 后,把 `tenant_id`/`is_platform` 写入 **`request.state`**(request 对象跨 task 共享,可靠 —— 底座 `require_current_user` 已验证此路径)。
  2. `get_session` 依赖(与 endpoint 同 task)加 `request: Request` 参数,从 `request.state` 读 tenant,写入 **`session.info["tenant_ctx"]`**。
  3. `do_orm_execute` / `before_flush` 从 `session.info` 读(它们天然能拿到 session)。
- **不引入** `TenantMiddleware`。租户上下文的唯一注入点是 `get_session` 依赖 + 显式 system context。

---

## 2. 数据模型(P0 最小集)

仅 `tenant` + `user`。role/menu 在 P1。

```python
# src/admin_platform/db/base.py —— 在底座 Base 旁新增 TenantMixin
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

class TenantMixin:
    """带此 mixin 的 model 自动参与租户隔离(见 db/tenant_filter.py)。"""
    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
```

```python
# src/admin_platform/domains/tenant/models.py —— 平台级表,不带 TenantMixin
class Tenant(Base):
    __tablename__ = "tenant"
    id:         Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    code:       Mapped[str]      = mapped_column(String(64), unique=True)   # "PLATFORM" 为哨兵
    name:       Mapped[str]      = mapped_column(String(128))
    status:     Mapped[str]      = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

```python
# src/admin_platform/domains/user/models.py —— 带 TenantMixin
class User(Base, TenantMixin):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),)
    id:                Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    username:          Mapped[str]      = mapped_column(String(64))
    password_hash:     Mapped[str]      = mapped_column(String(255))
    nickname:          Mapped[str]      = mapped_column(String(64), default="")
    status:            Mapped[str]      = mapped_column(String(16), default="active")
    is_platform_admin: Mapped[bool]     = mapped_column(default=False)
    created_at:        Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

---

## 3. 文件结构(新增/修改)

```
src/admin_platform/
├── core/
│   ├── auth.py            修改:CurrentUser 加 tenant_id/is_platform;AuthMiddleware 把 claims 写 request.state
│   ├── config.py          修改:加 auth_access_token_ttl_seconds(去验证码字段,验证码→P1)
│   ├── security.py        新增:passlib 哈希 + JWT access token 签发/解码
│   └── errors.py          修改:加 TENANT_CONTEXT_MISSING / LOGIN_FAILED 错误码
├── db/
│   ├── base.py            修改:加 TenantMixin
│   ├── session.py         修改:get_session 加 request 注入 tenant→session.info;新增 system_session()
│   └── tenant_filter.py    新增:do_orm_execute(fail-closed 注入)+ before_flush(写入填充),读 session.info
├── domains/
│   ├── tenant/            新增:五层(平台超管管理租户)
│   └── user/             新增:五层(用户 CRUD,受租户隔离)
├── api/v1/
│   └── auth.py           新增:POST /auth/login(P0 仅此;refresh/captcha → P1)
├── cli.py                新增:create-platform-admin 一次性管理命令
└── main.py               修改:挂 auth/user/tenant 路由;中间件顺序保持底座(见 ADR-E,不加 TenantMiddleware)
migrations/versions/
└── xxxx_p0_tenant_user.py  新增:tenant + user 表
tests/
├── unit/test_security.py            新增:哈希/JWT 签发
├── unit/test_tenant_filter.py        新增:fail-closed + system bypass 单测
├── api/test_auth.py                 新增:登录成功/失败
└── integration/test_tenant_isolation.py  新增:★端到端隔离验收
```

---

## 4. 任务分解

### Task 1:scaffold admin-platform(git archive,无破坏性删除)

- [ ] **Step 1** 干净导出底座 tracked 文件到新仓位置(无 .git/.venv):
```bash
mkdir -p ~/PythonProjects/admin-platform
git -C ~/PythonProjects/python-web-service-template archive HEAD | tar -x -C ~/PythonProjects/admin-platform
```
- [ ] **Step 2** 按底座 README 的 sed-rename 流程,包名 `service_name` → `admin_platform`、`[tool.hatch.build] packages`、`[tool.fastapi] entrypoint`、`service_id` 默认值 → `admin-platform`(以 README 命令为准)。
- [ ] **Step 3** 合并本计划目录 `docs/specs/` 到新仓。`git init` + 首个 commit(**需操作者显式授权**)。
- [ ] **Step 4 验收** `cd ~/PythonProjects/admin-platform && make check` → 底座原有测试在改名后全绿。
- [ ] **Checkpoint** 审 diff(确认无残留 `service_name`)→ Commit `chore: scaffold admin-platform via git archive`

### Task 2:依赖 intake(passlib)+ config 扩展

- [ ] **Step 1 依赖 intake**:确认 `passlib[bcrypt]` 来源/维护状态(PyPI),记录到 `docs/operations/DEPENDENCY_UPGRADE.md` 的 intake 段;`uv add "passlib[bcrypt]"`(**需操作者确认装依赖**)。
- [ ] **Step 2** `config.py` 在 `auth_*` 段后加(**不加验证码字段**):
```python
    # Token 签发(P0:仅 access token;refresh 在 P1)。校验复用底座 auth_jwt_* 字段。
    auth_access_token_ttl_seconds: int = Field(default=7200, ge=60)  # 2h(无 refresh 时的可用性折中)
```
- [ ] **Step 3** 同步 `.env.example`(底座 `test_env_example_covers_all_settings_fields` 守门)。
- [ ] **Step 4 验收** `pytest tests/unit/test_config.py -v` PASS;`make audit`(底座 Errata #1 = `uvx pip-audit .`,**不是** `uv run pip-audit`——pip-audit 非 dev 依赖,`uv run` 会找不到)无新增高危。
- [ ] **Checkpoint** → Commit `feat(config): access token ttl + passlib intake`

### Task 3:租户隔离机制 ★地基核心(fail-closed + session.info)

- [ ] **Step 1 写失败测试** `tests/unit/test_tenant_filter.py`:
```python
import pytest
from admin_platform.db.tenant_filter import TENANT_CTX_KEY, SYSTEM_CTX, TenantContextMissing

# 用真实 session(integration fixture)或轻量 in-memory sqlite 验证行为:
async def test_business_query_without_context_raises(session_no_ctx):
    # session.info 无 tenant_ctx 且非 system → 查 User 抛 TenantContextMissing
    with pytest.raises(TenantContextMissing):
        await session_no_ctx.execute(select(User))

async def test_system_context_bypasses_filter(system_session, two_tenant_users):
    rows = (await system_session.execute(select(User))).scalars().all()
    assert len(rows) == 2  # 跨租户全见

async def test_tenant_context_filters(tenant_session_A, two_tenant_users):
    rows = (await tenant_session_A.execute(select(User))).scalars().all()
    assert {u.tenant_id for u in rows} == {A_ID}  # 只见 A
```
- [ ] **Step 2 跑测试确认失败**。
- [ ] **Step 3 实现 `db/tenant_filter.py`**:
```python
"""租户隔离事件 —— fail-closed。上下文来自 session.info(见 ADR-E),不是 ContextVar。

  session.info["tenant_ctx"] = {"tenant_id": int, "platform": bool}   # 业务请求
  session.info["tenant_ctx"] = SYSTEM_CTX                              # 系统/登录/CLI(bypass)
  缺失                                                                 # 业务路径 → fail-closed 抛错

红线:本机制只保护 ORM 查询。raw SQL(text())跨租户不被保护 → 见 Task 12 RLS 加固。
"""
from __future__ import annotations
from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria
from admin_platform.db.base import TenantMixin

TENANT_CTX_KEY = "tenant_ctx"
SYSTEM_CTX = object()  # 哨兵:显式 system,bypass 过滤与自动填充

class TenantContextMissing(RuntimeError):
    """业务查询命中 TenantMixin 但 session 无 tenant 上下文 —— 拒绝裸查询。"""

def install_tenant_filter(sync_session_cls) -> None:
    """注册到底层 *sync* Session 类(见 engine.py 的 sync_session_class)。

    ⚠️ async 关键点(SQLAlchemy 官方 asyncio 文档):SessionEvents(do_orm_execute /
    before_flush)在 async 下**不能**注册到 `async_sessionmaker` 实例 —— 事件不会触发、
    租户过滤静默失效(比 fail-open 更危险:它"假装"在过滤)。必须注册到 `async_sessionmaker`
    的 `sync_session_class`(见 engine.py)。Task 3 的过滤测试同时充当"事件确实触发"的探针:
    若注册目标错了,test_tenant_context_filters 会因没过滤而返回跨租户行 → 失败。
    """
    @event.listens_for(sync_session_cls, "do_orm_execute")
    def _enforce(state):
        if not state.is_select:
            return
        ctx = state.session.info.get(TENANT_CTX_KEY)
        if ctx is SYSTEM_CTX:
            return  # 显式 system:bypass(调用方负责带 tenant_id,见登录 service)
        if ctx is None:
            # fail-closed:绝不放行无上下文的业务查询
            raise TenantContextMissing(
                "business query without tenant context; use get_session (HTTP) "
                "or system_session() (CLI/login) explicitly"
            )
        tid = ctx["tenant_id"]
        if ctx.get("platform"):
            return  # 平台超管 bypass
        state.statement = state.statement.options(
            with_loader_criteria(TenantMixin, lambda cls: cls.tenant_id == tid, include_aliases=True)
        )

    @event.listens_for(sync_session_cls, "before_flush")
    def _fill_tenant(session, flush_context, instances):
        ctx = session.info.get(TENANT_CTX_KEY)
        if ctx is None or ctx is SYSTEM_CTX or ctx.get("platform"):
            return  # system/platform/无上下文:不自动填(system 写入须显式带 tenant_id)
        tid = ctx["tenant_id"]
        for obj in session.new:
            if isinstance(obj, TenantMixin) and getattr(obj, "tenant_id", None) is None:
                obj.tenant_id = tid
```
- [ ] **Step 4** `db/engine.py`:定义本 app 的 sync session 类作事件锚点,让 `async_sessionmaker` 用它,再把过滤注册到它(见上 ⚠️):
```python
from sqlalchemy.orm import Session
class AppSession(Session):  # async_sessionmaker 的 sync 基类 + 事件锚点(不污染全局 Session)
    pass
# get_sessionmaker() 改为:
#   async_sessionmaker(get_engine(), sync_session_class=AppSession, expire_on_commit=False, autoflush=False)
# 在 AppSession 定义后(模块加载时,一次性)调:
install_tenant_filter(AppSession)
```
> ✅ 已验证(2026-06-02 review):当前 SQLAlchemy 版本支持 `async_sessionmaker(..., sync_session_class=AppSession)`,且实例化后的 `.sync_session` 确为 `AppSession` 实例。Task 3/4 据此直接实现,#2 的事件注册目标**无需再 spike**。
- [ ] **Step 5** `core/errors.py` 加 `TENANT_CONTEXT_MISSING`(500,内部错,不暴露细节)→ 异常 handler 把 `TenantContextMissing` 映射为 500 ProblemDetail(生产不泄堆栈)。
- [ ] **Step 6 跑测试确认通过**。
- [ ] **Checkpoint** → Commit `feat(tenant): fail-closed isolation via session.info`

### Task 4:数据模型 + 迁移(无 lifespan auto-seed)

- [ ] **Step 1** 写 `Tenant`/`User` model(§2)+ `TenantMixin`。
- [ ] **Step 2** `make migration name=p0_tenant_user`(底座 `Makefile` 用 `name=` 变量,**不是** `m=`);`make check-db` 验漂移。
- [ ] **Step 3** **不在 lifespan 自动 seed**。哨兵租户 + 初始超管由 Task 9 的 CLI 创建。
- [ ] **Step 4 验收** `make migrate` 后 `psql` 确认两表 + 索引 + 唯一约束存在。
- [ ] **Checkpoint** → Commit `feat(model): tenant + user tables`

### Task 5:security —— 哈希 + access token 签发 ★地基核心

- [ ] **Step 1 写失败测试** `tests/unit/test_security.py`:
```python
from admin_platform.core.security import hash_password, verify_password, issue_access_token, decode_token

def test_password_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret" and verify_password("s3cret", h) and not verify_password("x", h)

def test_access_token_carries_tenant_claims():
    tok = issue_access_token(user_id=7, tenant_id=42, is_platform=False, username="alice")
    p = decode_token(tok)
    assert p["sub"] == "7" and p["tenant_id"] == 42 and p["is_platform"] is False
```
- [ ] **Step 2 跑测试确认失败**。
- [ ] **Step 3 实现 `core/security.py`**:passlib `CryptContext(schemes=["bcrypt"])`;`issue_access_token` 用 PyJWT encode,secret/alg 取底座 `get_auth_config()`,TTL 取 `auth_access_token_ttl_seconds`,`iss`/`aud` 按 config 填;`decode_token` 在底座 `_decode_and_validate` 的 `require` 列表里**增加 `tenant_id`**(令 tenant_id 成为必需 claim —— 缺失即 401,把 fail-closed 延伸到认证层,绝不放行"无租户归属"的合法签名 token);`is_platform` 为可选,缺失默认 `False`(fail-safe:缺失 → 当普通租户用户、受过滤,而非误判超管)。**P0 不实现 refresh**。
- [ ] **Step 4 跑测试确认通过**。
- [ ] **Checkpoint** → Commit `feat(security): bcrypt hashing + access token issuance`

### Task 6:登录 API(system session 查 user,无验证码/refresh)

- [ ] **Step 1** `POST /api/v1/auth/login` body=`{tenant_code, username, password}`:
  - service 用 **system session** 查询(见 Task 7 `system_session`):先按 `tenant_code` 查 `tenant`(平台级表,正常查),拿 `tenant_id`;再**显式** `select(User).where(User.tenant_id == tid, User.username == username)`(用户 review ③:system bypass 下必须带 tenant_id)。
  - `verify_password` 失败 / 用户不存在 / 租户 suspended → `AppError("admin.LOGIN_FAILED", status_code=401)`(分层:service 抛 AppError,不抛 HTTPException;不区分"用户不存在/密码错"以防枚举)。
  - 成功 → `issue_access_token(...)`,返回 `{access_token, token_type:"bearer", expires_in}`。
- [ ] **Step 2** `/api/v1/auth/login` 加入 `auth_public_paths`。
- [ ] **Step 3 验收** `pytest tests/api/test_auth.py -v`:成功拿 token、错密码 401、错租户 401。
- [ ] **Checkpoint** → Commit `feat(auth): login endpoint (access token only)`

### Task 7:session 注入 tenant 上下文(取代 v1 的 TenantMiddleware)

- [ ] **Step 1** `core/auth.py`:`CurrentUser` 加 `tenant_id: int | None`(optional 路径/未鉴权为 None)、`is_platform: bool`;`AuthMiddleware.dispatch` 鉴权成功分支 `request.state.tenant_id = payload["tenant_id"]`(decode 已 require tenant_id 必需,**直接取、不用 `.get()` 软取** —— 软取会让缺 claim 的 token 静默变 None,与 fail-closed 相悖)、`request.state.is_platform = payload.get("is_platform", False)`(可选,缺失默认非超管)。
- [ ] **Step 2** `db/session.py` 改 `get_session` —— 从 request.state 注入 session.info:
```python
from fastapi import Request
from admin_platform.db.tenant_filter import TENANT_CTX_KEY, SYSTEM_CTX

async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session, session.begin():
        tid = getattr(request.state, "tenant_id", None)
        if tid is not None:
            session.info[TENANT_CTX_KEY] = {
                "tenant_id": tid,
                "platform": getattr(request.state, "is_platform", False),
            }
        # 注:public 路径(如登录)无 tenant_id → 不设上下文。
        # 这类 handler 不得用 get_session 直查 TenantMixin(会 fail-closed),
        # 应走 system_session()(见登录 service)。
        yield session

@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """系统/登录/CLI 用:显式 bypass 租户过滤。调用方负责按 tenant_id 显式过滤。"""
    async with get_sessionmaker()() as session, session.begin():
        session.info[TENANT_CTX_KEY] = SYSTEM_CTX
        yield session
```
- [ ] **Step 3** `main.py` 中间件顺序**保持底座原样**(RequestID 最外 → CORS → Auth → Idempotency → handler),**不新增 TenantMiddleware**。
- [ ] **Step 4 验收** `pytest tests/api -v` 全绿;新增断言:带 token 的业务请求 session.info 有 tenant_ctx。
- [ ] **Checkpoint** → Commit `feat(tenant): inject context via get_session + system_session`

### Task 8:user 域 CRUD(受租户隔离)

> 执行者按底座 `domains/todo` 五层生成。契约:
> - `GET /api/v1/users`(分页 `UserPage`)、`POST`、`PATCH /{id}`、`DELETE /{id}`
> - **不手写 tenant 过滤** —— Task 3 事件自动注入;repository 写普通 query
> - 创建用户 `password_hash = hash_password(...)`;`tenant_id` 由 before_flush 自动填
> - 平台超管 token → bypass → 跨租户列出

- [ ] **Step 1** 生成五层;`make check` 绿。
- [ ] **Step 2** 单测:同租户内 username 唯一(409)。
- [ ] **Checkpoint** → Commit `feat(user): tenant-scoped user CRUD`

### Task 9:CLI —— 一次性创建平台超管(取代 lifespan seed)

- [ ] **Step 1** `src/admin_platform/cli.py`:`create-platform-admin --username U`:
  - 用 `system_session()`;若 `tenant.code="PLATFORM"` 不存在则创建哨兵租户。
  - 初始密码**从 env `ADMIN_BOOTSTRAP_PASSWORD` 读;未设置直接 `sys.exit(1)` 报错,绝不写默认口令**(用户 review ⑤)。
  - 若超管已存在 → 报错退出(幂等,不覆盖)。
- [ ] **Step 2 验收**:
```bash
ADMIN_BOOTSTRAP_PASSWORD=... uv run python -m admin_platform.cli create-platform-admin --username root
# 不带 env → 退出码非 0,stderr 提示缺密码,不创建任何记录
```
- [ ] **Checkpoint** → Commit `feat(cli): bootstrap platform admin (no default password)`

### Task 10:★端到端租户隔离验收(本计划验收闸门)

- [ ] **Step 1 写验收测试** `tests/integration/test_tenant_isolation.py`(`@pytest.mark.integration`):
```python
async def test_tenants_isolated(client, seed):  # seed: tenantA+alice, tenantB+bob, PLATFORM+root
    tA, tB, tP = await login(client,"A","alice"), await login(client,"B","bob"), await login(client,"PLATFORM","root")
    uA = (await get(client,"/api/v1/users",tA))["items"]
    uB = (await get(client,"/api/v1/users",tB))["items"]
    uP = (await get(client,"/api/v1/users",tP))["items"]
    assert {u["username"] for u in uA} == {"alice"}
    assert {u["username"] for u in uB} == {"bob"}
    assert {"alice","bob","root"} <= {u["username"] for u in uP}

async def test_cross_tenant_get_404(client, seed):
    tA = await login(client,"A","alice")
    assert (await client.get(f"/api/v1/users/{bob_id}", headers=bearer(tA))).status_code == 404

# fail-closed(无上下文业务查询抛错)由 Task 3 单测 test_business_query_without_context_raises
# 覆盖 —— 不在此引入生产 `_debug` 端点(避免在生产代码加测试专用端点,工程原则④)。
```
- [ ] **Step 2 跑** `pytest -m integration tests/integration/test_tenant_isolation.py -v` → PASS。
- [ ] **Checkpoint** → Commit `test(tenant): end-to-end isolation + fail-closed acceptance`

### Task 11:覆盖率 + 文档

- [ ] **Step 1** `make coverage` ≥ 85%。
- [ ] **Step 2** 新建 `docs/architecture/MULTI_TENANCY.md`:记录 ADR-A/B/C/E + 隔离机制 + **「raw SQL 不被保护」红线** + system_session 用法。
- [ ] **Step 3** 更新 `CLAUDE.md`/`doc/` 多租户约定(改代码同步改 doc,底座纪律)。
- [ ] **Checkpoint** → Commit `docs: multi-tenancy ADR + coverage gate`

### Task 12(P0.5 spike):RLS 加固

- [ ] spike:asyncpg 连接池 + `session.begin()` 内 `SET LOCAL app.tenant` 是否稳定隔离(连接复用不串)。验证 OK → 关键表加 RLS policy,形成应用层 + DB 层双防御;结论与取舍写入 `MULTI_TENANCY.md`。失败 → 记录原因,P0 维持应用层 fail-closed。

---

## 5. 验收(完成定义)

- [ ] `make check` 全绿、`pytest -m integration` 含隔离+fail-closed 测试通过、`make coverage` ≥ 85%。
- [ ] 租户 A/B 各自登录只见自己;平台超管跨租户可见;跨租户按 id 直取 404;**无上下文业务查询 fail-closed 抛错(Task 3 单测覆盖 + errors handler 映射 500,不泄数据)**。
- [ ] 初始超管仅经 CLI 创建,缺 `ADMIN_BOOTSTRAP_PASSWORD` 直接失败、无默认口令。
- [ ] `docs/architecture/MULTI_TENANCY.md` 记录隔离机制 + raw SQL 红线 + system_session 用法。

## 6. 风险与红线

- **raw SQL 绕过**:应用层只保护 ORM。`text()`/原生 SQL 跨租户不被保护 → Task 12 RLS 兜底;在此之前 code review 必查任何 `text(`。
- **public 端点误用 get_session 直查 TenantMixin**:会 fail-closed 抛 500(而非泄数据)——这是预期的安全行为;此类查询应走 `system_session()` 并显式带 tenant_id。
- **system_session 滥用**:bypass 全过滤,只允许登录/CLI/维护任务用,且必须显式带 `tenant_id` 过滤;code review 必查 `system_session(` 调用点。
- **底座 BaseHTTPMiddleware 长期债(KNOWN_DEVIATIONS #13)**:本计划已通过 session.info 回避其 ContextVar 传播问题;若底座未来迁 pure ASGI,本方案不受影响(不依赖 ContextVar)。
- **2h access token 无法撤销**:P0 已知限制;P1 上 refresh(落库 jti 可撤销)+ 把 access TTL 收回 30min。

## 7. 自检(spec coverage)

多租户隔离→Task3/7/10 ✓ | fail-closed(DB 查询层)→Task3 单测 ✓ | fail-closed(认证层 tenant_id 必需)→Task5/7 ✓ | 异步事件注册到 sync_session_class→Task3/4 ✓ | 上下文传播(session.info)→ADR-E/Task7 ✓ | 认证签发→Task5/6 ✓ | system context+登录查询→Task6/7 ✓ | CLI seed 无默认口令→Task9 ✓ | 依赖 intake→Task2 ✓ | 安全 scaffold→Task1 ✓ | 中间件顺序→Task7 Step3 ✓ | 验证码/refresh 下放 P1→§0/ADR-C ✓ | data scope 不做→ADR-B ✓ | 前端/RBAC/审计/字典/任务→不在本计划 ✓

---

## 修订记录

**v2(2026-06-02,人工 review 后):**
1. **ADR-A fail-closed**:废弃 v1 `tid is None: return` fail-open;业务查询缺上下文 → 抛 `TenantContextMissing`。
2. **ADR-E 新增**:上下文改走 `session.info`(经 get_session 从 request.state 注入),回避 `BaseHTTPMiddleware`+`ContextVar` 跨 task 传播失效;删除 v1 的 `TenantMiddleware` 与 `tenant_context.py` ContextVar 方案。
3. **ADR-C**:P0 去 refresh token(下放 P1 + 要求落库 jti 可撤销);access TTL 2h 折中。
4. **依赖/验证码**:passlib 走 intake;验证码(Pillow/captcha)下放 P1。
5. **CLI seed**:删除 lifespan auto-seed;改一次性 CLI,缺 `ADMIN_BOOTSTRAP_PASSWORD` 即失败,无默认口令。
6. **ADR-D scaffold**:`cp -R`+`rm -rf .git` → `git archive` 干净导出。
7. **中间件顺序**:修正为底座真实顺序(RequestID 最外层);本计划不再新增 TenantMiddleware。
8. **执行流程**:去掉 `superpowers:*` 指令,改环境中立的人工 checkpoint gate;计划从 `docs/superpowers/plans/` 移到 `docs/specs/`。
9. **登录查询**:system session + 显式 `(tenant_id, username)` 过滤(review ③)。

**v3(2026-06-02,二轮 review 后 —— 5 处事实性修正,均经底座/官方文档核实):**
1. **audit 命令**:`uv run pip-audit` → `make audit`(底座 `Makefile:34` Errata #1 = `uvx pip-audit .`;pip-audit 非 dev 依赖,`uv run` 找不到)。
2. **异步事件注册** ★:`do_orm_execute`/`before_flush` 从注册到 `async_sessionmaker` 改为注册到 **`sync_session_class`**(SQLAlchemy 官方 asyncio 文档:async 下注册到 async maker **事件不触发** → 过滤静默失效,比 fail-open 更隐蔽);`engine.py` 增 `AppSession(Session)` 作 sync 锚点;删死代码 `_query_touches_tenant_model`。
3. **migration 语法**:`make migration m=...` → `make migration name=...`(底座 `Makefile:40` 用 `name=`)。
4. **token 必需 claim**:`tenant_id` 加入 `decode` 的 `require` 列表(缺失即 401,把 fail-closed 延伸到认证层);`request.state.tenant_id = payload["tenant_id"]` 直取、不 `.get()` 软取;`is_platform` 缺失默认 `False`(fail-safe 方向,刻意保留软取)。
5. **删 `_debug/leak` 生产端点**:fail-closed 改由 Task 3 单测覆盖(不在生产代码加测试专用端点,工程原则④)。
