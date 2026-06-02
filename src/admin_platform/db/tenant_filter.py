"""租户隔离事件 —— fail-closed。上下文来自 session.info（见 ADR-E），不是 ContextVar。

session.info 三态::

    session.info["tenant_ctx"] = {"tenant_id": int, "platform": bool}   # 业务请求
    session.info["tenant_ctx"] = SYSTEM_CTX                              # 系统/登录/CLI（bypass）
    缺失                                                                 # 无上下文 → fail-closed 抛错

读 + 写**对称** fail-closed：

- 读：无上下文的 ORM SELECT 一律抛 ``TenantContextMissing``（**广义拦截，不区分是否租户表**）。
- 写：无上下文却 flush 含 ``TenantMixin`` 的对象（**即便显式带了 tenant_id**）一律抛错——
  否则裸 session 能绕过上下文写入跨租户数据。

为什么读路径"广义拦截"而不是"只拦 TenantMixin 表"：判断一条语句是否触及租户表无法可靠做到——
``ORMExecuteState.all_mappers`` 对 ``select(平台表).join(租户表)`` 只返回平台表、漏掉 join 进来的
租户表（已实测）。按它收窄拦截范围会让这类 join 在无上下文时漏过 → fail-open 跨租户泄漏。两害相权
取其轻：宁可广义拦截（无上下文的纯平台查询也须显式走 ``system_session()``）。HTTP 路径由
``get_session`` 必然带上下文，所以广义拦截在正常请求里零成本，只挡住"忘了设上下文"的 bug 和裸 session。

红线：本机制只保护 ORM **Session** 查询。raw SQL（``text()``）、``engine.connect()`` 直连
（如 ``/readyz`` 的 ``SELECT 1``）不经本事件 → 跨租户不被保护 → 见 Task 12 RLS 加固。
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria

from admin_platform.db.base import TenantMixin

TENANT_CTX_KEY = "tenant_ctx"
SYSTEM_CTX = object()  # 哨兵：显式 system，bypass 过滤与自动填充


class TenantContextMissing(RuntimeError):
    """业务查询命中 TenantMixin 但 session 无 tenant 上下文 —— 拒绝裸查询。"""


def install_tenant_filter(sync_session_cls) -> None:
    """把租户隔离事件注册到底层 *sync* Session 类（见 engine.py 的 sync_session_class）。

    ⚠️ async 关键点（SQLAlchemy 官方 asyncio 文档）：SessionEvents（do_orm_execute /
    before_flush）在 async 下**不能**注册到 ``async_sessionmaker`` 实例 —— 事件不会触发、
    租户过滤静默失效（比 fail-open 更危险：它"假装"在过滤）。必须注册到 ``async_sessionmaker``
    的 ``sync_session_class``（见 engine.py）。Task 3 的过滤测试同时充当"事件确实触发"的探针：
    若注册目标错了，test_tenant_context_filters 会因没过滤而返回跨租户行 → 失败。
    """

    @event.listens_for(sync_session_cls, "do_orm_execute")
    def _enforce(state):
        if not state.is_select:
            return
        ctx = state.session.info.get(TENANT_CTX_KEY)
        if ctx is SYSTEM_CTX:
            return  # 显式 system：bypass（调用方负责带 tenant_id，见登录 service）
        if ctx is None:
            # fail-closed：绝不放行无上下文的业务查询
            raise TenantContextMissing(
                "business query without tenant context; use get_session (HTTP) "
                "or system_session() (CLI/login) explicitly"
            )
        tid = ctx["tenant_id"]
        if ctx.get("platform"):
            return  # 平台超管 bypass
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantMixin,
                lambda cls: cls.tenant_id == tid,
                include_aliases=True,
            )
        )

    @event.listens_for(sync_session_cls, "before_flush")
    def _fill_tenant(session, flush_context, instances):
        ctx = session.info.get(TENANT_CTX_KEY)
        if ctx is SYSTEM_CTX or (isinstance(ctx, dict) and ctx.get("platform")):
            # 显式 system / 平台超管：bypass（写入须自带 tenant_id，不自动填）
            return
        # 写路径与读路径对称 fail-closed：无上下文却要写租户表 = 服务端 bug（用错 session）。
        # 即便对象显式带了 tenant_id 也拒绝，否则裸 session 能绕过上下文写入跨租户数据。
        tenant_writes = [
            obj
            for obj in (*session.new, *session.dirty, *session.deleted)
            if isinstance(obj, TenantMixin)
        ]
        if ctx is None:
            if tenant_writes:
                raise TenantContextMissing(
                    "tenant-scoped write without tenant context; use get_session (HTTP) "
                    "or system_session() (CLI/login) explicitly"
                )
            return  # 无租户对象的写入（纯平台表）放行
        tid = ctx["tenant_id"]
        for obj in session.new:
            if isinstance(obj, TenantMixin) and getattr(obj, "tenant_id", None) is None:
                obj.tenant_id = tid
