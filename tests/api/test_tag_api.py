"""/api/v1/tags 的 API 测试 — DB-backed 路由。

只跑 validation (422)，它在 AsyncSession 依赖之前短路，不需要真 DB。
完整 CRUD happy / NOT_FOUND / DUPLICATE 放 ``tests/integration/test_tag_db.py``。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.domains.tag.api import router


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    return TestClient(app)


def test_create_returns_422_on_missing_field() -> None:
    res = _client().post("/api/v1/tags", json={})
    assert res.status_code == 422


def test_create_returns_422_on_empty_name() -> None:
    res = _client().post("/api/v1/tags", json={"name": ""})
    assert res.status_code == 422


def test_create_returns_422_on_oversized_name() -> None:
    res = _client().post("/api/v1/tags", json={"name": "x" * 65})
    assert res.status_code == 422


def test_update_returns_422_on_invalid_payload() -> None:
    res = _client().patch("/api/v1/tags/1", json={"name": 123})
    assert res.status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    res = _client().get("/api/v1/tags?size=101")
    assert res.status_code == 422
