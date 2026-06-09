"""通知公告 CRUD 集成测试（P3）—— 真 DB 全路径 + 权限矩阵 + 过滤 + 富文本原样往返。

需本地 DB。覆盖：create/list/get/patch/delete + 404；notice_type/status 过滤；无权限 403 矩阵；
content 富文本（含 <script> payload）后端原样存取不被静默篡改（spec §2.4 / Codex XSS ask）。
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
from admin_platform.domains.notice.api import router as notice_router

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


class _NoPermProvider(PermissionProvider):
    def get_is_active(self, user_id: int) -> bool:
        return True

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE notices CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client(provider: type[PermissionProvider]) -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(notice_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_crud_end_to_end() -> None:
    async with _client(_SuperProvider) as c:
        created = await c.post(
            "/api/v1/notices",
            json={"title": "停机", "notice_type": "notification", "content": "今晚维护"},
        )
        assert created.status_code == 201, created.text
        nid = created.json()["id"]

        listed = (await c.get("/api/v1/notices")).json()
        assert listed["total"] == 1
        assert listed["items"][0]["title"] == "停机"

        got = await c.get(f"/api/v1/notices/{nid}")
        assert got.status_code == 200

        patched = await c.patch(f"/api/v1/notices/{nid}", json={"status": "disabled"})
        assert patched.status_code == 200
        assert patched.json()["status"] == "disabled"

        deleted = await c.delete(f"/api/v1/notices/{nid}")
        assert deleted.status_code == 204
        missing = await c.get(f"/api/v1/notices/{nid}")
        assert missing.status_code == 404
        assert missing.json()["type"] == "notice.NOT_FOUND"


async def test_list_filtered_by_type_and_status() -> None:
    async with _client(_SuperProvider) as c:
        await c.post(
            "/api/v1/notices",
            json={"title": "通知A", "notice_type": "notification", "content": "x"},
        )
        await c.post(
            "/api/v1/notices",
            json={"title": "公告B", "notice_type": "announcement", "content": "x"},
        )
        by_type = await c.get("/api/v1/notices?notice_type=announcement")
        assert by_type.json()["total"] == 1
        assert by_type.json()["items"][0]["title"] == "公告B"
        # 对抗审查 S4：?status= 过滤真正生效（alias，非 status_filter）。
        await c.post(
            "/api/v1/notices",
            json={
                "title": "停用",
                "notice_type": "notification",
                "content": "x",
                "status": "disabled",
            },
        )
        by_status = await c.get("/api/v1/notices?status=disabled")
        assert by_status.json()["total"] == 1
        assert by_status.json()["items"][0]["title"] == "停用"
        # 非法过滤值 → 422（Literal 校验）。
        assert (await c.get("/api/v1/notices?status=bogus")).status_code == 422


async def test_rich_text_content_round_trips_verbatim() -> None:
    # 富文本含 <script> payload：后端 JSON 存取应原样往返、不被静默篡改/净化（净化是 P6 渲染期职责）。
    payload = "<p>维护</p><script>alert('xss')</script>"
    async with _client(_SuperProvider) as c:
        created = await c.post(
            "/api/v1/notices",
            json={"title": "x", "notice_type": "announcement", "content": payload},
        )
        nid = created.json()["id"]
        got = await c.get(f"/api/v1/notices/{nid}")
        assert got.json()["content"] == payload


async def test_permission_matrix_403() -> None:
    async with _client(_NoPermProvider) as c:
        assert (await c.get("/api/v1/notices")).status_code == 403
        assert (await c.get("/api/v1/notices/1")).status_code == 403
        assert (
            await c.post(
                "/api/v1/notices",
                json={"title": "x", "notice_type": "notification", "content": "x"},
            )
        ).status_code == 403
        assert (await c.patch("/api/v1/notices/1", json={"title": "x"})).status_code == 403
        assert (await c.delete("/api/v1/notices/1")).status_code == 403
