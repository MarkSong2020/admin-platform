"""FastAPI 依赖：per-request AsyncSession，自动提交。

事务策略（v0.4.11+）
--------------------
每个请求拿到一个 SQLAlchemy 事务，由 ``session.begin()`` 管理：

  * Handler 正常返回 → 依赖 teardown 时 COMMIT
  * Handler 抛错（AppError / HTTPException / 未捕获）→ ROLLBACK
  * Service 可以调 ``session.begin_nested()`` 开 SAVEPOINT 子事务
    （saga 流程里的部分提交），不影响外层请求事务

「一请求 = 一事务」由此成为安全默认。v0.4.11 之前的模板只调
``session.flush()``，依赖一个根本不存在的「service owns transaction」
握手 —— 结果是每次写都在 ``session.close()`` 时被静默回滚。集成测试
``tests/integration/test_transaction_commit.py`` 守这条永不回归。

注意点：
  * ``IdempotencyMiddleware`` 写它的响应 cache 是在本依赖 teardown
    commit **之前** —— commit 失败会在 Redis 里留下一条幻影
    「completed」记录。金额扣减类需要严格 at-most-once 的场景必须在
    同事务内加 DB-level idempotency 表 —— 详见
    ``doc/architecture/REQUEST_LIFECYCLE.md``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.engine import get_sessionmaker
from admin_platform.db.tenant_filter import SYSTEM_CTX, TENANT_CTX_KEY


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """每请求一个 AsyncSession，从 request.state 注入租户上下文到 session.info。

    上下文来源是 ``AuthMiddleware`` 写入 ``request.state`` 的 tenant_id/is_platform
    （见 ADR-E：走 request.state 而非 ContextVar，回避 BaseHTTPMiddleware 跨 task 传播
    失效）。public 路径（如登录）无 tenant_id → 不设上下文；这类 handler **不得**用
    ``get_session`` 直查 ``TenantMixin``（会 fail-closed 抛错），应走 ``system_session()``。
    """
    async with get_sessionmaker()() as session, session.begin():
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is not None:
            session.info[TENANT_CTX_KEY] = {
                "tenant_id": tenant_id,
                "platform": getattr(request.state, "is_platform", False),
            }
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """系统 / 登录 / CLI 用：显式 ``SYSTEM_CTX`` bypass 租户过滤。

    调用方负责按 ``tenant_id`` 显式过滤（如登录 service 先按 tenant_code 查租户、再
    ``where(User.tenant_id == tid)``）。bypass 全过滤的口子，code review 必查每个调用点。
    """
    async with get_sessionmaker()() as session, session.begin():
        session.info[TENANT_CTX_KEY] = SYSTEM_CTX
        yield session
