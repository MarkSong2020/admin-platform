"""/api/v1/todos 的 API 测试 — DB-backed 路由。

这里只跑 validation (422)：它在 AsyncSession 依赖之前短路，无需真 DB。
完整 CRUD happy / NOT_FOUND / DUPLICATE 路径放 ``tests/integration/test_todo_db.py``。

本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception handler），
错误响应里的 ``request_id`` 字段与线上服务一致。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.domains.todo.api import router


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    return TestClient(app)


def test_create_returns_422_on_missing_field() -> None:
    res = _client().post("/api/v1/todos", json={})
    assert res.status_code == 422


def test_create_returns_422_on_empty_title() -> None:
    res = _client().post("/api/v1/todos", json={"title": ""})
    assert res.status_code == 422


def test_create_returns_422_on_oversized_title() -> None:
    res = _client().post("/api/v1/todos", json={"title": "x" * 201})
    assert res.status_code == 422


def test_update_returns_422_on_invalid_status() -> None:
    res = _client().patch("/api/v1/todos/1", json={"status": "BOGUS"})
    assert res.status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    res = _client().get("/api/v1/todos?size=101")
    assert res.status_code == 422
