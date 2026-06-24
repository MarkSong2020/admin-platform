"""MySQL 集成测试清表 helper。"""

from __future__ import annotations

import os
import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.engine import make_url

from admin_platform.core.config import get_settings
from admin_platform.db.session import db_session

_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "db"}
_ALLOW_DESTRUCTIVE_ENV = "APP_TEST_DB_ALLOW_DESTRUCTIVE"
_ALLOW_NONLOCAL_ENV = "APP_TEST_DB_ALLOW_NONLOCAL"


def assert_destructive_test_database_allowed(database_url: str | None = None) -> None:
    """集成测试清库前的显式授权 guard。

    MySQL 清理会临时关闭外键并 ``TRUNCATE`` 多张表；即使 URL 指向 localhost，也可能是
    SSH 隧道、共享开发库或宿主已有库。必须由调用方显式设置 destructive 开关。
    """
    url = database_url or get_settings().database_url
    if os.getenv(_ALLOW_DESTRUCTIVE_ENV) != "1":
        raise RuntimeError(
            "集成测试会 TRUNCATE 测试库；请确认指向 disposable 本地测试库后设置 "
            f"{_ALLOW_DESTRUCTIVE_ENV}=1"
        )
    try:
        host = make_url(url).host
    except Exception as exc:  # pragma: no cover - SQLAlchemy URL 解析失败路径只用于错误提示
        raise RuntimeError(f"无法解析 APP_DATABASE_URL，拒绝执行破坏性集成测试: {url}") from exc
    if host not in _LOCAL_DB_HOSTS and os.getenv(_ALLOW_NONLOCAL_ENV) != "1":
        raise RuntimeError(
            "集成测试拒绝在疑似非本地库执行 TRUNCATE（database_url host 非 "
            f"{sorted(_LOCAL_DB_HOSTS)}）；确认是 disposable 测试库后才可设置 "
            f"{_ALLOW_NONLOCAL_ENV}=1"
        )


async def _referencing_tables() -> dict[str, set[str]]:
    """读取当前 schema 的 FK 依赖图：parent_table -> child_tables。"""
    async with db_session() as session:
        result = await session.execute(
            text(
                """
                SELECT TABLE_NAME AS child_table, REFERENCED_TABLE_NAME AS parent_table
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND REFERENCED_TABLE_SCHEMA = DATABASE()
                  AND REFERENCED_TABLE_NAME IS NOT NULL
                """
            )
        )
        rows = list(result.mappings())
    graph: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        graph[str(row["parent_table"])].add(str(row["child_table"]))
    return graph


def _expand_with_referencing_tables(
    requested_tables: set[str], graph: dict[str, set[str]]
) -> set[str]:
    """把显式表扩展为 FK 子表闭包，模拟 PostgreSQL ``TRUNCATE ... CASCADE``。"""
    expanded = set(requested_tables)
    pending = list(requested_tables)
    while pending:
        parent = pending.pop()
        for child in graph.get(parent, set()):
            if child not in expanded:
                expanded.add(child)
                pending.append(child)
    return expanded


async def truncate_tables(*table_names: str) -> None:
    """逐表 TRUNCATE，并自动补齐 FK 子表闭包。

    PostgreSQL 的 ``TRUNCATE ... CASCADE`` 不能直接迁到 MySQL；集成测试只连
    disposable 本地库，清理时按显式表清单扩展出所有引用它们的子表，再临时
    关闭 MySQL 外键检查逐个截断，避免留下孤儿行。
    """
    assert_destructive_test_database_allowed()
    for table_name in table_names:
        if not _TABLE_NAME_RE.fullmatch(table_name):
            raise ValueError(f"invalid table name for truncate: {table_name!r}")
    expanded_tables = _expand_with_referencing_tables(set(table_names), await _referencing_tables())
    async with db_session() as session:
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for table_name in sorted(expanded_tables):
                await session.execute(text(f"TRUNCATE TABLE {table_name}"))
        finally:
            await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
