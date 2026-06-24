"""Unified error response shape for unhandled exceptions (ADR 0001 §1)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

import admin_platform.domains.dict.models  # noqa: F401  —— import 时注册 dict 单默认值约束映射
from admin_platform.core.config import get_settings
from admin_platform.core.errors import register_unique_constraint
from admin_platform.main import create_app


@pytest.fixture
def app_with_boom(app: FastAPI) -> FastAPI:
    @app.get("/__boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    return app


class _Credentials(BaseModel):
    username: str = Field(min_length=3)
    password: str = Field(min_length=8)


@pytest.fixture
def app_with_login(app: FastAPI) -> FastAPI:
    @app.post("/__login")
    async def login(payload: _Credentials) -> dict[str, bool]:
        return {"ok": True}

    return app


def test_unhandled_exception_returns_unified_error_shape(app_with_boom: FastAPI) -> None:
    with TestClient(app_with_boom, raise_server_exceptions=False) as c:
        response = c.get("/__boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["type"] == "framework.INTERNAL_ERROR"
    assert body["title"] == "Internal server error"
    assert body["status"] == 500
    assert body["request_id"]
    assert (
        body["instance"] is None
    )  # ADR §1 baseline: instance reserved for future error-instance URI
    assert body["detail"] is None
    assert body["trace_id"] is None
    assert body["errors"] is None  # debug=False by default


def test_validation_422_does_not_echo_submitted_field_values(
    app_with_login: FastAPI,
) -> None:
    """SECURITY (v0.4.13): Pydantic's ``errors()`` defaults to
    ``include_input=True`` — every rejected field value (password, API key,
    token, PII) gets echoed in the 422 body. ``OBSERVABILITY.md`` bans those
    fields from any response surface; this test enforces it at the framework
    boundary, not as a per-route audit."""
    with TestClient(app_with_login) as c:
        # Both fields fail validation (password under min_length AND user
        # under min_length). Pre-v0.4.13 both raw values would appear in
        # ``errors[*].input``.
        response = c.post("/__login", json={"username": "ab", "password": "Sup3"})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "framework.VALIDATION_FAILED"
    assert body["errors"], "errors must list the failing fields"
    for error in body["errors"]:
        # Loc / msg / type / ctx remain — clients can pinpoint and fix.
        assert "loc" in error
        assert "msg" in error
        # The submitted value MUST NOT appear. ``input`` key must be absent
        # entirely (Pydantic omits it when ``include_input=False``).
        assert "input" not in error, (
            f"validation 422 leaked the submitted value back to the caller: {error!r}"
        )


def test_unhandled_exception_includes_errors_when_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DEBUG", "true")
    get_settings.cache_clear()
    debug_app = create_app()

    @debug_app.get("/__boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    with TestClient(debug_app, raise_server_exceptions=False) as c:
        response = c.get("/__boom")

    body = response.json()
    assert body["errors"] == {"type": "RuntimeError", "args": ["kaboom"]}


# --------------------------------------------------------------------------- #
# IntegrityError handler — DB 约束竞态兜底                                      #
# --------------------------------------------------------------------------- #


class _MockOrigWithConstraintName(Exception):
    """模拟 asyncpg UniqueViolationError（有 constraint_name 属性）。"""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


class _MockOrigWithConstraintInMessage(Exception):
    """模拟只有 str 消息里含 ``constraint "xxx"`` 的驱动异常。"""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'duplicate key value violates unique constraint "{constraint_name}"')


class _MockMysqlDuplicateEntry(Exception):
    """模拟 aiomysql/MySQL 1062 duplicate entry。"""

    def __init__(self, key_name: str) -> None:
        super().__init__(1062, f"Duplicate entry 'alice' for key 'users.{key_name}'")


class _MockMysqlForeignKeyConstraint(Exception):
    """模拟 aiomysql/MySQL 1451 foreign key constraint fails。"""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(
            1451,
            "Cannot delete or update a parent row: a foreign key constraint fails "
            f"(`app`.`dict_data`, CONSTRAINT `{constraint_name}` FOREIGN KEY (`dict_type_id`) "
            "REFERENCES `dict_types` (`id`))",
        )


# 下面三类 orig 的 (类, errno) 取自真库实测(mysql:8.0 + aiomysql)：
# 1406 超长 → DataError；3819 CHECK → OperationalError；1213 死锁 → OperationalError。
class _MockMysqlDataTooLong(Exception):
    """模拟 aiomysql/MySQL 1406 Data too long（DataError.orig）。"""

    def __init__(self) -> None:
        super().__init__(1406, "Data too long for column 'name' at row 1")


class _MockMysqlCheckViolation(Exception):
    """模拟 aiomysql/MySQL 3819 CHECK 约束违反（OperationalError.orig）。"""

    def __init__(self) -> None:
        super().__init__(3819, "Check constraint 'ck_scheduled_tasks_status' is violated.")


class _MockMysqlDeadlock(Exception):
    """模拟 aiomysql/MySQL 1213 死锁（OperationalError.orig，非数据非法 → 仍 500）。"""

    def __init__(self) -> None:
        super().__init__(1213, "Deadlock found when trying to get lock; try restarting transaction")


class _MockMysqlSelfParentSignal(Exception):
    """模拟 depts self-parent trigger 的 SIGNAL（errno 1644 + 约束名 MESSAGE_TEXT）。

    真库实测（mysql:8.0 + aiomysql）：orig.args == (1644, 'ck_depts_not_self_parent')。
    """

    def __init__(self) -> None:
        super().__init__(1644, "ck_depts_not_self_parent")


class _MockMysqlGenericSignal(Exception):
    """模拟未知来源的 SIGNAL（errno 1644 但非已知 self-parent 约束名）→ 须保持 500。"""

    def __init__(self) -> None:
        super().__init__(1644, "some_unrelated_user_signal")


def test_integrity_registered_constraint_returns_typed_409(app: FastAPI) -> None:
    """注册过的约束 → 409 + typed code，响应 body 不暴露 DB 约束名。"""
    register_unique_constraint("uq_alpha_col", "test.ALPHA_DUPLICATE", "Alpha already exists")

    @app.post("/__integrity-registered")
    async def handler() -> None:
        raise IntegrityError(
            "INSERT INTO ...",
            {"params": None},
            orig=_MockOrigWithConstraintName("uq_alpha_col"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-registered")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "test.ALPHA_DUPLICATE"
    assert body["title"] == "Alpha already exists"
    assert body["detail"] is None
    assert body["request_id"]


def test_integrity_dict_default_constraint_returns_typed_409(app: FastAPI) -> None:
    """真实 dict 单默认值生成列唯一索引竞态兜底：撞 ``uq_dict_data_one_default_per_type``
    → 409 ``dict.DEFAULT_DUPLICATE``（service clear-siblings 之外的 DB 层并发双默认拦截）。
    映射在 ``domains/dict/models.py`` import 时注册（见文件顶部 import），不靠 app 装配顺序。
    """

    @app.post("/__integrity-dict-default")
    async def handler() -> None:
        raise IntegrityError(
            "INSERT INTO dict_data ...",
            {"params": None},
            orig=_MockOrigWithConstraintName("uq_dict_data_one_default_per_type"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-dict-default")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "dict.DEFAULT_DUPLICATE"
    # DB 约束名不外泄（只进 log extra）。
    assert "uq_dict_data_one_default_per_type" not in str(body)


def test_integrity_unmapped_constraint_returns_framework_409(app: FastAPI) -> None:
    """未注册的约束 → 409 + framework.CONFLICT，detail 为 None。"""

    @app.post("/__integrity-unmapped")
    async def handler() -> None:
        raise IntegrityError(
            "INSERT INTO ...",
            {"params": None},
            orig=_MockOrigWithConstraintName("uq_unknown_zzz"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-unmapped")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "framework.CONFLICT"
    assert body["title"] == "Resource constraint violation"
    assert body["detail"] is None


def test_integrity_string_fallback_extracts_constraint(app: FastAPI) -> None:
    """无 constraint_name 属性 → 从 str(orig) 正则提取 → 走映射。"""
    register_unique_constraint("uq_beta_col", "test.BETA_DUPLICATE", "Beta already exists")

    @app.post("/__integrity-fallback")
    async def handler() -> None:
        raise IntegrityError(
            "INSERT INTO ...",
            {"params": None},
            orig=_MockOrigWithConstraintInMessage("uq_beta_col"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-fallback")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "test.BETA_DUPLICATE"
    assert body["detail"] is None


def test_integrity_mysql_1062_extracts_key_name(app: FastAPI) -> None:
    """MySQL 1062 ``for key 'table.uq_xxx'`` → 提取唯一索引名并映射到业务 409。"""
    register_unique_constraint("uq_gamma_col", "test.GAMMA_DUPLICATE", "Gamma already exists")

    @app.post("/__integrity-mysql-1062")
    async def handler() -> None:
        raise IntegrityError(
            "INSERT INTO ...",
            {"params": None},
            orig=_MockMysqlDuplicateEntry("uq_gamma_col"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-mysql-1062")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "test.GAMMA_DUPLICATE"
    assert "uq_gamma_col" not in str(body)


def test_integrity_mysql_fk_extracts_constraint_name(app: FastAPI) -> None:
    """MySQL 1451 ``CONSTRAINT `fk_xxx``` → 提取 FK 名并映射到业务 409。"""

    @app.post("/__integrity-mysql-fk")
    async def handler() -> None:
        raise IntegrityError(
            "DELETE FROM dict_types ...",
            {"params": None},
            orig=_MockMysqlForeignKeyConstraint("fk_dict_data_type_id"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-mysql-fk")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "dict.TYPE_HAS_DATA"
    assert "fk_dict_data_type_id" not in str(body)


def test_integrity_without_constraint_returns_framework_409(app: FastAPI) -> None:
    """orig 无 constraint_name 且 str 不含 constraint 模式 → framework.CONFLICT。"""

    @app.post("/__integrity-no-hint")
    async def handler() -> None:
        raise IntegrityError(
            "INSERT INTO ...",
            {"params": None},
            orig=ValueError("some totally different error"),
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__integrity-no-hint")

    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "framework.CONFLICT"
    assert body["detail"] is None


def test_register_unique_constraint_idempotent_same_value() -> None:
    # 同名同值重复注册幂等放行（容忍 models 模块在测试收集等场景被多次 import）。
    register_unique_constraint("uq_failfast_probe", "test.FAILFAST", "x")
    register_unique_constraint("uq_failfast_probe", "test.FAILFAST", "x")  # 不抛


def test_register_unique_constraint_conflict_fails_fast() -> None:
    # 同名注册不同值 → RuntimeError（防 IntegrityError→409 业务码随 import 顺序漂移）。
    register_unique_constraint("uq_failfast_probe2", "test.A_DUP", "a")
    with pytest.raises(RuntimeError, match="漂移"):
        register_unique_constraint("uq_failfast_probe2", "test.B_DUP", "b")


def test_data_error_returns_422_constraint_violation(app: FastAPI) -> None:
    """1406 超长属 DataError，整类映 422（防 schema 漏配 max_length 时退化成 500）。
    body 脱敏：不回显被拒值，也不漏 DB 列名。"""

    @app.post("/__data-too-long")
    async def handler() -> None:
        raise DataError("INSERT INTO ...", {"params": None}, orig=_MockMysqlDataTooLong())

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__data-too-long")

    assert resp.status_code == 422
    body = resp.json()
    assert body["type"] == "framework.CONSTRAINT_VIOLATION"
    assert body["detail"] is None
    assert "name" not in (body.get("errors") or {})  # 列名不外泄


def test_check_violation_operational_error_returns_422(app: FastAPI) -> None:
    """3819 CHECK 违反归到 OperationalError，从宽类里挑出 → 422。"""

    @app.post("/__check-violation")
    async def handler() -> None:
        raise OperationalError("INSERT INTO ...", {"params": None}, orig=_MockMysqlCheckViolation())

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__check-violation")

    assert resp.status_code == 422
    assert resp.json()["type"] == "framework.CONSTRAINT_VIOLATION"


def test_non_check_operational_error_stays_500(app: FastAPI) -> None:
    """OperationalError 宽类里的非 CHECK（死锁 1213）是服务端/瞬态问题 → 保持 500，
    不能误判成 422 让客户端以为是自己数据非法。"""

    @app.post("/__deadlock")
    async def handler() -> None:
        raise OperationalError("UPDATE ...", {"params": None}, orig=_MockMysqlDeadlock())

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__deadlock")

    assert resp.status_code == 500
    assert resp.json()["type"] == "framework.INTERNAL_ERROR"


def test_self_parent_signal_returns_422_constraint_violation(app: FastAPI) -> None:
    """depts/menus self-parent trigger 的 SIGNAL(errno 1644)是 DB 兜底的数据非法，
    与 CHECK 同类挑出 → 422，不让 raw/内部写路径退化成 500。"""

    @app.post("/__self-parent")
    async def handler() -> None:
        raise OperationalError(
            "INSERT INTO ...", {"params": None}, orig=_MockMysqlSelfParentSignal()
        )

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__self-parent")

    assert resp.status_code == 422
    assert resp.json()["type"] == "framework.CONSTRAINT_VIOLATION"


def test_unknown_signal_operational_error_stays_500(app: FastAPI) -> None:
    """errno 1644 但非已知 self-parent 约束名（其它来源 SIGNAL）→ 保持 500，
    防把任意 SIGNAL 误判成 422 客户端数据非法。"""

    @app.post("/__unknown-signal")
    async def handler() -> None:
        raise OperationalError("INSERT INTO ...", {"params": None}, orig=_MockMysqlGenericSignal())

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/__unknown-signal")

    assert resp.status_code == 500
    assert resp.json()["type"] == "framework.INTERNAL_ERROR"
