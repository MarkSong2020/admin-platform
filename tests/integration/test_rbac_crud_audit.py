"""RBAC 裸资源 CRUD 写审计（P1.5）—— create/update/delete 经 audited_write 产 rbac_write。

audited_write helper 在 user/role/menu/dept/post 五域 api 统一织入；本测试用 role 域代表验证
机制（成功 + 失败都 emit，失败带 error_code）。Codex PK 红线：CRUD 写改变授权，不能漏审计。需 DB。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.role.api import router as role_router

pytestmark = pytest.mark.integration


class _SuperProvider(PermissionProvider):
    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE roles CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client() -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(role_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = _SuperProvider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _rbac_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    out = []
    for record in caplog.records:
        event = getattr(record, "audit_event", None)
        if event and event.get("event_type") == "rbac_write":
            out.append(event)
    return out


async def test_crud_emits_rbac_write_success(caplog: pytest.LogCaptureFixture) -> None:
    async with _client() as c:
        with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
            created = await c.post("/api/v1/roles", json={"name": "r1", "code": "r1"})
            assert created.status_code == 201, created.text
            rid = created.json()["id"]
            assert (await c.patch(f"/api/v1/roles/{rid}", json={"name": "r1x"})).status_code == 200
            assert (await c.delete(f"/api/v1/roles/{rid}")).status_code == 204
    actions = [e["action"] for e in _rbac_events(caplog) if e["result"]["status"] == "success"]
    assert "system:role:add" in actions
    assert "system:role:edit" in actions
    assert "system:role:remove" in actions
    await dispose_engine()


async def test_crud_failure_emits_rbac_write_failure(caplog: pytest.LogCaptureFixture) -> None:
    async with _client() as c:
        await c.post("/api/v1/roles", json={"name": "dup", "code": "dup"})
        with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
            res = await c.post(
                "/api/v1/roles", json={"name": "dup2", "code": "dup"}
            )  # code 重复 409
            assert res.status_code == 409
    failures = [e for e in _rbac_events(caplog) if e["result"]["status"] == "failure"]
    assert failures and failures[0]["action"] == "system:role:add"
    assert failures[0]["result"]["error_code"] == "role.CODE_DUPLICATE"
    await dispose_engine()
