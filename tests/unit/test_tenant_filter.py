"""Task 3 租户隔离机制单测 —— 证明事件真实触发，不"假装"过滤。

用 sync in-memory SQLite + ``AppSession`` 验证三件事（跑在 ``make check`` 内，不需 docker）：

1. 业务查询无租户上下文 → fail-closed 抛 ``TenantContextMissing``
2. 租户上下文 → ``with_loader_criteria`` 只见本租户行（两租户数据为证）
3. ``SYSTEM_CTX`` / 平台超管 → bypass，跨租户全见

外加一条防回归断言：production 的 ``async_sessionmaker`` 底层 sync session 必须是
``AppSession``（事件锚点）。若事件被错注册到 ``async_sessionmaker`` 实例，过滤会静默失效——
但此处第 1/2 条会因"没抛错 / 返回跨租户行"而**变红**，正是 codex review 要求的"不误绿"防线。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from admin_platform.db.base import TenantMixin
from admin_platform.db.engine import AppSession, get_sessionmaker
from admin_platform.db.tenant_filter import (
    SYSTEM_CTX,
    TENANT_CTX_KEY,
    TenantContextMissing,
)

A_ID = 1
B_ID = 2


class _ProbeBase(DeclarativeBase):
    """测试专用 declarative base —— 与生产 ``db.base.Base`` 隔离，
    probe 表不进真实 ``Base.metadata``（不污染 Alembic autogenerate / 漂移检测）。"""


class _FilterProbe(_ProbeBase, TenantMixin):
    """只为验证隔离机制的最小 model。继承 ``TenantMixin`` 使其落入
    ``with_loader_criteria(TenantMixin, ...)`` 的作用范围（与真实业务表同等待遇）。"""

    __tablename__ = "_filter_probe"

    id: Mapped[int] = mapped_column(primary_key=True)


class _PlatformProbe(_ProbeBase):
    """非租户（平台级）probe —— **不**继承 ``TenantMixin``，用于验证"读路径广义
    fail-closed（连平台表 SELECT 也拦）"与"纯平台表写放行"两条语义。"""

    __tablename__ = "_platform_probe"

    id: Mapped[int] = mapped_column(primary_key=True)


@pytest.fixture
def probe_session_factory() -> Iterator[sessionmaker[AppSession]]:
    """sync in-memory SQLite + ``AppSession`` 工厂，预置两租户各一行。

    种子用 ``SYSTEM_CTX`` 写入（before_flush 对 system 不自动填，显式带 tenant_id），
    避免插数据时撞 fail-closed。
    """
    engine = create_engine("sqlite://")
    # _ProbeBase 只含 _FilterProbe，create_all 无需 tables= 过滤，只建 _filter_probe。
    _ProbeBase.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=AppSession)

    seed = factory()
    seed.info[TENANT_CTX_KEY] = SYSTEM_CTX
    seed.add_all(
        [
            _FilterProbe(id=1, tenant_id=A_ID),
            _FilterProbe(id=2, tenant_id=B_ID),
            _PlatformProbe(id=1),
        ]
    )
    seed.commit()
    seed.close()

    yield factory
    engine.dispose()


def test_business_query_without_context_raises(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    session = probe_session_factory()  # session.info 无 tenant_ctx
    with pytest.raises(TenantContextMissing):
        session.execute(select(_FilterProbe))
    session.close()


def test_tenant_context_filters_to_own_rows(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    session = probe_session_factory()
    session.info[TENANT_CTX_KEY] = {"tenant_id": A_ID, "platform": False}
    rows = session.execute(select(_FilterProbe)).scalars().all()
    assert {row.tenant_id for row in rows} == {A_ID}  # 只见 A，B 被过滤掉
    session.close()


def test_system_context_bypasses_filter(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    session = probe_session_factory()
    session.info[TENANT_CTX_KEY] = SYSTEM_CTX
    rows = session.execute(select(_FilterProbe)).scalars().all()
    assert {row.tenant_id for row in rows} == {A_ID, B_ID}  # 跨租户全见
    session.close()


def test_platform_context_bypasses_filter(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    session = probe_session_factory()
    session.info[TENANT_CTX_KEY] = {"tenant_id": A_ID, "platform": True}
    rows = session.execute(select(_FilterProbe)).scalars().all()
    assert {row.tenant_id for row in rows} == {A_ID, B_ID}  # 平台超管跨租户全见
    session.close()


def test_before_flush_autofills_tenant_id(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    session = probe_session_factory()
    session.info[TENANT_CTX_KEY] = {"tenant_id": B_ID, "platform": False}
    probe = _FilterProbe(id=99)  # 不显式给 tenant_id
    session.add(probe)
    session.flush()
    assert probe.tenant_id == B_ID  # before_flush 按当前租户上下文自动填充
    session.close()


def test_tenant_write_without_context_raises(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    """写路径 fail-closed（与读路径对称）：无上下文 session **即便显式带 tenant_id**，
    flush 租户对象也抛错——堵住裸 session 绕过上下文写入跨租户数据。"""
    session = probe_session_factory()  # session.info 无 tenant_ctx
    session.add(_FilterProbe(id=50, tenant_id=A_ID))  # 显式带 tenant_id 也不放行
    with pytest.raises(TenantContextMissing):
        session.flush()
    session.close()


def test_platform_write_without_context_allowed(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    """写 fail-closed 只针对租户表：无上下文写纯平台表（非 TenantMixin）放行。"""
    session = probe_session_factory()  # 无上下文
    probe = _PlatformProbe(id=50)
    session.add(probe)
    session.flush()  # 不抛错
    assert probe not in session.new  # flush 后已落库，离开 pending 集合
    session.close()


def test_platform_query_without_context_also_raises(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    """读路径**广义** fail-closed（设计决策）：无上下文连非租户表 SELECT 也拦。

    原因：``select(平台表).join(租户表)`` 时 ``all_mappers`` 漏掉 join 的租户表，
    按"只拦租户表"收窄会让这类 join 在无上下文时漏过 → fail-open。宁可广义拦截，
    平台查询显式走 system_session。
    """
    session = probe_session_factory()  # 无上下文
    with pytest.raises(TenantContextMissing):
        session.execute(select(_PlatformProbe))
    session.close()


def test_system_context_allows_platform_query(
    probe_session_factory: sessionmaker[AppSession],
) -> None:
    """system bypass 对平台表同样生效：无上下文被拦的平台查询，走 SYSTEM_CTX 即可。"""
    session = probe_session_factory()
    session.info[TENANT_CTX_KEY] = SYSTEM_CTX
    rows = session.execute(select(_PlatformProbe)).scalars().all()
    assert len(rows) == 1
    session.close()


def test_async_sessionmaker_uses_appsession_as_sync_class() -> None:
    """防回归：async 路径底层 sync session 必须是 AppSession（事件锚点正确），
    否则租户过滤在生产 async 路径静默失效。autouse fixture 负责 dispose 引擎。"""
    assert get_sessionmaker().kw.get("sync_session_class") is AppSession
