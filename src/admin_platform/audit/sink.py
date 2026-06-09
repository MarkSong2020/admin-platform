"""审计持久化 sink 抽象（P2 §3 写入路径）。

**写入路径裁决**（Claude×Codex PK 收敛）：审计落库走**独立 session**、**响应后批量 flush**，
非同业务事务、非纯 BackgroundTask。理由——

  * 失败/拒绝类事件在业务 ``raise AppError`` 时 emit，业务随 ``session.begin()`` 的 ``__aexit__``
    ROLLBACK；若审计同事务则**最该留的安全事件被一起回滚**（P1.5「revoke 被 ROLLBACK」同类陷阱）。
  * 独立 session 切断两个耦合：①审计不被业务回滚牵连；②审计写失败不回滚业务。
  * **响应后批量**（emit 只往请求缓冲 append，中间件在 ``call_next`` 后一次性 flush）：时点对
    所有事件统一正确（业务已 commit/rollback）；一请求 N 条审计 = **1 个独立 session 批量插入**
    （解决 Codex 担心的「每 emit 一连接」放大）。

``AuditSink`` 是抽象：P2 用 ``DbAuditSink``；P2.1 可换 ``RedisStreamSink``（异步 + consumer group
+ DLQ），靠 ``event_id`` UNIQUE 幂等去重。``flush_audit_events`` 是统一入口，**永不抛**（写失败
降级 logger，绝不阻断业务）——守 ``emit_audit`` 既有契约。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from admin_platform.audit.events import AuditEvent
from admin_platform.audit.models import AuditEventLog
from admin_platform.db.session import db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger("admin_platform.audit")


async def persist_audit_in_session(session: AsyncSession, event: AuditEvent) -> None:
    """在给定（业务）session 内写审计行——成功审计与业务**原子提交**（review F1 修复，方案 B）。

    用 ``begin_nested()`` SAVEPOINT 隔离：审计 insert 失败只回滚 savepoint，**不连累业务**（守
    「审计写失败不阻断业务」）；审计行随外层业务事务一起 commit / rollback → commit 失败时审计
    与业务一同回滚，不留假成功审计。**永不抛**。
    """
    try:
        async with session.begin_nested():
            session.add(AuditEventLog.from_envelope(event))
    except Exception:  # 审计落库失败绝不阻断业务（SAVEPOINT 已回滚该 insert）
        _logger.warning("in-tx audit persist failed", exc_info=True)


class AuditSink(Protocol):
    """审计持久化 sink 协议（P2 DbAuditSink / P2.1 RedisStreamSink 可替换）。批量接收一请求的事件。"""

    async def persist(self, events: Sequence[AuditEvent]) -> None: ...


class DbAuditSink:
    """独立 session 批量持久化（P2 基线）。一请求所有审计一个独立连接/事务，与业务解耦。"""

    async def persist(self, events: Sequence[AuditEvent]) -> None:
        async with db_session() as session:
            session.add_all([AuditEventLog.from_envelope(e) for e in events])
        # __aexit__ 独立 commit。event_id 撞 UNIQUE（重复投递）抛 IntegrityError，由
        # flush_audit_events 吞成 warning —— 幂等去重，不产生重复行。


class _Registry:
    """进程级 sink 持有者（用类属性而非 module global，规避 ruff PLW0603）。"""

    sink: AuditSink | None = None


def configure_audit_sink(sink: AuditSink | None) -> None:
    """注册全局审计 sink（app lifespan / 集成测试调用）。None = 关持久化（仅 logger）。"""
    _Registry.sink = sink


def current_audit_sink() -> AuditSink | None:
    return _Registry.sink


async def flush_audit_events(events: Sequence[AuditEvent]) -> None:
    """把一请求缓冲的审计事件批量落库（经注册的 sink）。无 sink / 空缓冲 = no-op。

    **永不抛**：写失败只记 warning（logger sink 是 durable 底线），绝不阻断业务/响应。
    """
    sink = _Registry.sink
    if sink is None or not events:
        return
    try:
        await sink.persist(events)
    except Exception:  # 审计落库失败绝不阻断业务（守 emit_audit 契约）
        _logger.warning("audit persist failed (%d events)", len(events), exc_info=True)
