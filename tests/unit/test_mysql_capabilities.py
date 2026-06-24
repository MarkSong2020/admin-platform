"""MySQL 迁移前置能力校验。"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.engine import Connection

from admin_platform.db.mysql_capabilities import (
    REQUIRED_MYSQL_COLLATION,
    assert_app_locks_table_healthy,
    assert_mysql_database_capabilities,
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


def test_validate_mysql_capabilities_rejects_non_innodb_default_engine() -> None:
    # 非 InnoDB 默认引擎：业务表会建成非事务引擎，FK/CHECK/FOR UPDATE 静默失效（codex 高审）。
    with pytest.raises(RuntimeError, match="InnoDB"):
        validate_mysql_capability_values(
            "8.0.36", REQUIRED_MYSQL_COLLATION, default_storage_engine="MyISAM"
        )


def test_validate_mysql_capabilities_accepts_innodb_case_insensitively() -> None:
    # @@default_storage_engine 大小写不固定（InnoDB / INNODB），校验须大小写无关。
    validate_mysql_capability_values(
        "8.0.36", REQUIRED_MYSQL_COLLATION, default_storage_engine="INNODB"
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


# ---- assert_mysql_database_capabilities（读连接 → 校验；覆盖新增 @@default_storage_engine SQL）----


class _CapResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeCapabilityConn:
    """按 SQL 内容回放 VERSION / collation / 默认引擎 / binlog 探测结果。"""

    def __init__(  # noqa: PLR0913
        self,
        *,
        dialect: str = "mysql",
        version: str = "8.0.36",
        collation: str = REQUIRED_MYSQL_COLLATION,
        default_engine: str = "InnoDB",
        log_bin: int = 0,
        trust: int = 1,
    ) -> None:
        self.dialect = _FakeDialect() if dialect == "mysql" else cast(_FakeDialect, _OtherDialect())
        self._version = version
        self._collation = collation
        self._engine = default_engine
        self._log_bin = log_bin
        self._trust = trust

    def exec_driver_sql(self, sql: str) -> _CapResult:
        # 非 MySQL 方言下绝不应发探测 SQL（调用方须先 early-return）。这里直接 fail，
        # 让 test_assert_capabilities_skips_non_mysql_dialect 成为真守门：若有人删掉
        # assert_mysql_database_capabilities 的 `dialect != "mysql"` 早退，此处会被调到 → 测试失败。
        if self.dialect.name != "mysql":
            raise AssertionError(f"非 MySQL 方言不应发探测 SQL，但收到: {sql!r}")
        normalized = " ".join(sql.split())
        if "VERSION()" in normalized and "DATABASE()" not in normalized:
            return _CapResult(self._version)
        if "DEFAULT_COLLATION_NAME" in normalized:
            return _CapResult(self._collation)
        if "@@default_storage_engine" in normalized:
            return _CapResult(self._engine)
        # 注意：@@log_bin 是 @@log_bin_trust_function_creators 的子串，先判更长的。
        if "@@log_bin_trust_function_creators" in normalized:
            return _CapResult(self._trust)
        if "@@log_bin" in normalized:
            return _CapResult(self._log_bin)
        return _CapResult(None)


class _OtherDialect:
    name = "sqlite"


def _cap_conn(**kwargs: object) -> Connection:
    return cast(Connection, _FakeCapabilityConn(**kwargs))  # type: ignore[arg-type]


def test_assert_capabilities_accepts_full_innodb_baseline() -> None:
    # 走完整读连接路径（含新增 SELECT @@default_storage_engine），合规库不报错。
    assert_mysql_database_capabilities(_cap_conn())


def test_assert_capabilities_rejects_non_innodb_default_engine() -> None:
    with pytest.raises(RuntimeError, match="InnoDB"):
        assert_mysql_database_capabilities(_cap_conn(default_engine="MyISAM"))


def test_assert_capabilities_skips_non_mysql_dialect() -> None:
    # 非 MySQL 方言（如 sqlite 单测）必须早退、不发任何探测 SQL。
    assert_mysql_database_capabilities(_cap_conn(dialect="sqlite"))
