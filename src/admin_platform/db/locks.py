"""MySQL 事务级行锁 sentinel。

PostgreSQL ``pg_advisory_xact_lock`` 迁移到 MySQL 后，统一使用
``app_locks(name)`` 哨兵行承载事务级互斥：

1. 业务 session 尚未取连接时，先用独立短事务确保哨兵行存在；
2. 业务 session 已取连接时，退回当前事务内 ``INSERT IGNORE``，不再借第二条连接；
3. 调用方事务 ``SELECT ... FOR UPDATE`` 锁住该行，commit / rollback 时自动释放行锁。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import String, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base
from admin_platform.db.engine import get_engine

_LOCK_NAME_MAX_LENGTH = 191
_MYSQL_DEADLOCK = 1213
_LOCK_RETRY_LIMIT = 3
_LOCK_RETRY_BACKOFF_SECONDS = 0.02
_ENSURE_ROW_GUARDS: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    WeakKeyDictionary()
)
_KNOWN_LOCK_ROWS: set[str] = set()


class AppLock(Base):
    """应用级事务锁哨兵表。

    显式锁定 InnoDB + utf8mb4_0900_bin：行锁(FOR UPDATE)是事务级互斥的实现基础，
    非事务引擎会让锁静默失效；与 0021 迁移的裸 DDL 声明保持一致(SQLite 测试忽略
    mysql_* 选项)。
    """

    __tablename__ = "app_locks"
    # tuple 末尾 dict = 表级 kwargs（与项目其余 model 的 __table_args__ tuple 风格一致，
    # 避免 mutable dict 触发 RUF012 / ClassVar override）。
    __table_args__ = (
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_bin",
        },
    )

    name: Mapped[str] = mapped_column(
        String(_LOCK_NAME_MAX_LENGTH), primary_key=True, comment="锁名"
    )


def app_lock_name(namespace: str, *parts: object) -> str:
    """拼接稳定锁名，避免各调用点手写字符串格式。"""
    suffix = ":".join(str(part) for part in parts)
    return f"{namespace}:{suffix}" if suffix else namespace


async def acquire_transaction_lock(session: AsyncSession, name: str) -> None:
    """获取事务级应用锁。

    调用方必须已处于业务事务中；本函数只获取行锁，不主动提交。锁释放由外层事务
    commit / rollback 决定，语义对齐 PostgreSQL ``pg_advisory_xact_lock``。
    """
    _validate_lock_name(name)
    if name not in _KNOWN_LOCK_ROWS:
        if _session_has_checked_out_connection(session):
            # 调用方可能已在同一 session 内做过业务查询；此时不能再借第二条连接，
            # pool_size=1 会自锁。退回当前事务内占位，随后 FOR UPDATE 持锁。
            await _ensure_lock_row_in_current_transaction(session, name)
        else:
            # 先于调用方 session 的首次 SQL 预创建哨兵行，避免多事务首插同名
            # sentinel 后再 FOR UPDATE 触发 MySQL 1213 deadlock。
            await _ensure_lock_row(name)
    for _ in range(2):
        locked = (
            await session.execute(
                select(AppLock.name).where(AppLock.name == name).with_for_update()
            )
        ).scalar_one_or_none()
        if locked is not None:
            _KNOWN_LOCK_ROWS.add(name)
            return
        # 进程缓存可能因测试清库/维护误删 app_locks 而过期；不能把 0 行 FOR UPDATE
        # 当作已持锁继续执行。
        _KNOWN_LOCK_ROWS.discard(name)
        await _ensure_lock_row_in_current_transaction(session, name)
    raise RuntimeError(f"app lock row still missing after recreate: {name}")


async def ensure_transaction_lock_row(name: str) -> None:
    """在进入业务事务前预创建事务锁哨兵行。"""
    _validate_lock_name(name)
    # 即使进程缓存认为行存在，也要在业务事务外用独立短事务确认一次。测试清库 /
    # 运维误删 / 同进程切库都可能让缓存过期；若等到 FOR UPDATE 0 行后再修复，就会在
    # 已持有业务事务连接时再借第二条连接，重新引入低连接池下的卡顿风险。
    await _ensure_lock_row(name)


def _session_has_checked_out_connection(session: AsyncSession) -> bool:
    """判断业务 session 是否已借出连接。

    SQLAlchemy 没有公开的 async API 直接暴露“事务已开始但还没 checkout 连接”的状态。
    这里只读同步 SessionTransaction 的连接映射：空映射表示尚未执行 SQL，仍可安全使用
    独立短事务预热 sentinel；非空则必须避免再借第二条连接。
    """
    transaction = session.sync_session.get_transaction()
    if transaction is None:
        return False
    return bool(getattr(transaction, "_connections", None))


async def _ensure_lock_row_in_current_transaction(session: AsyncSession, name: str) -> None:
    """在当前业务事务内确保 sentinel 行存在，不额外借连接。"""
    async with _ensure_guard(name):
        if name not in _KNOWN_LOCK_ROWS:
            await _insert_ignore_app_lock(session, name)
            _KNOWN_LOCK_ROWS.add(name)


async def _ensure_lock_row(name: str) -> None:
    """用独立短事务确保 sentinel 行存在。

    MySQL 在高并发 ``INSERT IGNORE`` + ``SELECT ... FOR UPDATE`` 同事务模式下可能把
    1213 deadlock 抛在后续 ``SELECT`` 上；低连接池下，业务事务占住连接后再借第二条连接
    也会自锁。因此把“占位行创建”收敛到业务 session 首次取连接前的独立短事务，
    业务事务只负责持有行锁。
    """
    async with _ensure_guard(name):
        for attempt in range(_LOCK_RETRY_LIMIT):
            try:
                async with get_engine().begin() as conn:
                    exists = (
                        await conn.execute(
                            select(AppLock.name).where(AppLock.name == name).limit(1)
                        )
                    ).scalar_one_or_none()
                    if exists is not None:
                        _KNOWN_LOCK_ROWS.add(name)
                        return
                    await _insert_ignore_app_lock(conn, name)
                _KNOWN_LOCK_ROWS.add(name)
                return
            except DBAPIError as exc:
                if _mysql_error_code(exc) != _MYSQL_DEADLOCK or attempt == _LOCK_RETRY_LIMIT - 1:
                    raise
                await asyncio.sleep(_LOCK_RETRY_BACKOFF_SECONDS * (2**attempt))


def _ensure_guard(name: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    guards = _ENSURE_ROW_GUARDS.get(loop)
    if guards is None:
        guards = {}
        _ENSURE_ROW_GUARDS[loop] = guards
    guard = guards.get(name)
    if guard is None:
        guard = asyncio.Lock()
        guards[name] = guard
    return guard


async def _insert_ignore_app_lock(conn: Any, name: str) -> None:
    # INSERT IGNORE 命中重复会产生 MySQL NOTE 级 warning。sql_notes=0 在占位写入期间抑制其
    # 记录，随后立即恢复——驱动无关的轻量卫生措施（aiomysql/PyMySQL 默认不外显该 warning，真库实测
    # stderr 为空；asyncmy 评估期则会刷到 stderr）。保留这层抑制，避免驱动/代理/审计侧记录无谓噪声。
    await conn.execute(text("SET sql_notes = 0"))
    try:
        await conn.execute(
            text("INSERT IGNORE INTO app_locks (name) VALUES (:name)"), {"name": name}
        )
    finally:
        with contextlib.suppress(Exception):
            await conn.execute(text("SET sql_notes = 1"))


def _validate_lock_name(name: str) -> None:
    if not name:
        raise ValueError("app lock name must not be empty")
    if len(name) > _LOCK_NAME_MAX_LENGTH:
        raise ValueError(f"app lock name too long: {len(name)} > {_LOCK_NAME_MAX_LENGTH}")


def _mysql_error_code(exc: BaseException) -> int | None:
    candidates: tuple[Any, ...] = (getattr(exc, "orig", None), exc)
    for candidate in candidates:
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return int(args[0])
    return None
