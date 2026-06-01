"""Unified error response shape for unhandled exceptions (ADR 0001 §1)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

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
