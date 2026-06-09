"""参数设置 CRUD 集成测试（P3）—— 真 DB 全路径 + 热更新断言 + 内置禁删 + key 唯一。

需本地 DB。覆盖：create/list/get/patch/delete + 404；key 重复 409；内置参数删 409；
**热更新**——改值提交后消费端点 /value/{key} 立即读到新值（读穿 DB，无缓存，spec §2.3 决策 B / P3 DoD）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.config.api import router as config_router

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
        await session.execute(text("TRUNCATE TABLE configs CASCADE"))


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
    app.include_router(config_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = _SuperProvider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create(c: AsyncClient, *, key: str, value: str, is_builtin: bool = False) -> int:
    res = await c.post(
        "/api/v1/configs",
        json={"name": key, "config_key": key, "config_value": value, "is_builtin": is_builtin},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_crud_end_to_end() -> None:
    async with _client() as c:
        cid = await _create(c, key="sys.index.title", value="管理后台")
        listed = (await c.get("/api/v1/configs")).json()
        assert listed["total"] == 1

        got = await c.get(f"/api/v1/configs/{cid}")
        assert got.json()["config_key"] == "sys.index.title"

        deleted = await c.delete(f"/api/v1/configs/{cid}")
        assert deleted.status_code == 204
        missing = await c.get(f"/api/v1/configs/{cid}")
        assert missing.status_code == 404
        assert missing.json()["type"] == "config.NOT_FOUND"


async def test_duplicate_key_returns_409() -> None:
    async with _client() as c:
        await _create(c, key="sys.dup", value="1")
        dup = await c.post(
            "/api/v1/configs",
            json={"name": "x", "config_key": "sys.dup", "config_value": "2"},
        )
        assert dup.status_code == 409
        assert dup.json()["type"] == "config.KEY_DUPLICATE"


async def test_builtin_config_cannot_be_deleted() -> None:
    async with _client() as c:
        cid = await _create(c, key="sys.locked", value="v", is_builtin=True)
        res = await c.delete(f"/api/v1/configs/{cid}")
        assert res.status_code == 409
        assert res.json()["type"] == "config.BUILTIN_READONLY"
        # 仍可查到（未删）。
        assert (await c.get(f"/api/v1/configs/{cid}")).status_code == 200


async def test_unprotect_builtin_then_delete() -> None:
    # 对抗审查 S2：内置参数先 PATCH is_builtin=false 解保护后可删（消除「永久不可删」不可逆）。
    async with _client() as c:
        cid = await _create(c, key="sys.protected", value="v", is_builtin=True)
        assert (await c.delete(f"/api/v1/configs/{cid}")).status_code == 409
        assert (
            await c.patch(f"/api/v1/configs/{cid}", json={"is_builtin": False})
        ).status_code == 200
        assert (await c.delete(f"/api/v1/configs/{cid}")).status_code == 204


async def test_hot_update_takes_effect_without_restart() -> None:
    # P3 DoD：改参数值提交后，消费端点 /value/{key} 立即读到新值（读穿 DB，无进程内缓存）。
    async with _client() as c:
        cid = await _create(c, key="sys.user.initPassword", value="changeit")
        before = await c.get("/api/v1/configs/value/sys.user.initPassword")
        assert before.status_code == 200
        assert before.json()["config_value"] == "changeit"

        patched = await c.patch(f"/api/v1/configs/{cid}", json={"config_value": "newpass"})
        assert patched.status_code == 200

        after = await c.get("/api/v1/configs/value/sys.user.initPassword")
        assert after.json()["config_value"] == "newpass"  # 热更新生效，无需重启


async def test_get_value_missing_key_404() -> None:
    async with _client() as c:
        res = await c.get("/api/v1/configs/value/does.not.exist")
        assert res.status_code == 404
        assert res.json()["type"] == "config.NOT_FOUND"
