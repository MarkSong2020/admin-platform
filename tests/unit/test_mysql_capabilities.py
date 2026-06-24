"""MySQL 迁移前置能力校验。"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.engine import Connection

from admin_platform.db.mysql_capabilities import (
    REQUIRED_MYSQL_COLLATION,
    assert_app_locks_table_healthy,
    parse_mysql_version,
    validate_mysql_capability_values,
)


def test_parse_mysql_version_ignores_suffix() -> None:
    assert parse_mysql_version("8.0.36-0ubuntu0.22.04.1") == (8, 0, 36)


def test_validate_mysql_capabilities_accepts_required_baseline() -> None:
    validate_mysql_capability_values("8.0.16", REQUIRED_MYSQL_COLLATION)


def test_validate_mysql_capabilities_rejects_old_check_implementation() -> None:
    with pytest.raises(RuntimeError, match=r"8\.0\.16"):
        validate_mysql_capability_values("8.0.15", REQUIRED_MYSQL_COLLATION)


def test_validate_mysql_capabilities_rejects_case_insensitive_collation() -> None:
    with pytest.raises(RuntimeError, match=REQUIRED_MYSQL_COLLATION):
        validate_mysql_capability_values("8.0.36", "utf8mb4_0900_ai_ci")


def test_validate_mysql_capabilities_rejects_binlog_without_trust_function_creators() -> None:
    with pytest.raises(RuntimeError, match="log_bin_trust_function_creators"):
        validate_mysql_capability_values(
            "8.0.36",
            REQUIRED_MYSQL_COLLATION,
            log_bin_enabled=True,
            trust_function_creators=False,
        )


# ---- assert_app_locks_table_healthy（codex 第二轮：迁移内/后置自检 app_locks 真实结构）----


class _FakeResult:
    def __init__(self, *, first_row: object = None, all_rows: list[tuple] | None = None) -> None:
        self._first = first_row
        self._all = all_rows or []

    def first(self) -> object:
        return self._first

    def fetchall(self) -> list[tuple]:
        return self._all


class _FakeDialect:
    name = "mysql"


class _FakeConn:
    """按 SQL 内容返回 TABLES（engine/collation）/ STATISTICS（PK 列）/ COLUMNS（name 列结构）。"""

    def __init__(  # noqa: PLR0913
        self,
        *,
        engine: str,
        collation: str,
        pk_columns: list[str],
        name_type: str = "varchar",
        name_length: int = 191,
        name_nullable: str = "NO",
        name_collation: str = REQUIRED_MYSQL_COLLATION,
    ) -> None:
        self.dialect = _FakeDialect()
        self._engine = engine
        self._collation = collation
        self._pk = pk_columns
        self._name_col = (name_type, name_length, name_nullable, name_collation)

    def exec_driver_sql(self, sql: str) -> _FakeResult:
        if "information_schema.TABLES" in sql:
            return _FakeResult(first_row=(self._engine, self._collation))
        if "information_schema.COLUMNS" in sql:
            return _FakeResult(first_row=self._name_col)
        if "information_schema.STATISTICS" in sql:
            return _FakeResult(all_rows=[(c,) for c in self._pk])
        return _FakeResult()


def _conn(  # noqa: PLR0913
    *,
    engine: str = "InnoDB",
    collation: str = REQUIRED_MYSQL_COLLATION,
    pk_columns: list[str] | None = None,
    name_type: str = "varchar",
    name_length: int = 191,
    name_nullable: str = "NO",
    name_collation: str = REQUIRED_MYSQL_COLLATION,
) -> Connection:
    fake = _FakeConn(
        engine=engine,
        collation=collation,
        pk_columns=["name"] if pk_columns is None else pk_columns,
        name_type=name_type,
        name_length=name_length,
        name_nullable=name_nullable,
        name_collation=name_collation,
    )
    return cast(Connection, fake)


def test_app_locks_healthy_accepts_innodb_bin_with_pk() -> None:
    assert_app_locks_table_healthy(_conn())


def test_app_locks_rejects_non_innodb_engine() -> None:
    with pytest.raises(RuntimeError, match="InnoDB"):
        assert_app_locks_table_healthy(_conn(engine="MyISAM"))


def test_app_locks_rejects_case_insensitive_collation() -> None:
    with pytest.raises(RuntimeError, match=REQUIRED_MYSQL_COLLATION):
        assert_app_locks_table_healthy(_conn(collation="utf8mb4_0900_ai_ci"))


def test_app_locks_rejects_missing_primary_key() -> None:
    with pytest.raises(RuntimeError, match="主键"):
        assert_app_locks_table_healthy(_conn(pk_columns=[]))


def test_app_locks_rejects_short_name_column() -> None:
    # 既存 name VARCHAR(64)：ENGINE/collation/PK 都对但列宽不足 → 长锁名(65-191)插入会失败。
    with pytest.raises(RuntimeError, match="VARCHAR"):
        assert_app_locks_table_healthy(_conn(name_length=64))


def test_app_locks_rejects_nullable_name_column() -> None:
    with pytest.raises(RuntimeError, match="NOT NULL"):
        assert_app_locks_table_healthy(_conn(name_nullable="YES"))
