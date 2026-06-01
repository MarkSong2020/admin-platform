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

from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.engine import get_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session, session.begin():
        yield session
