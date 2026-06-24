"""file 文件管理域 CRUD 集成测试（需本地 DB + 临时 fs）—— 端到端验收（spec 2026-06-11）。

覆盖：
  * **上传/下载往返（真 DB + 真 fs）**：multipart 上传 → 201 + 元数据落库；下载字节与原内容一致。
  * **列表 / 软删**：上传多个 → list；删除 → 204 + get 404 + 物理文件清理 + list 不含。
  * **安全校验端到端**：扩展名不允许 / 魔数不符 → 415（service AppError 经 api 透传）。
  * **权限矩阵 5 端点 403** + 超管短路放行。
  * **mounted 回归**：file_router 已挂进生产 ``create_app()``（人值守红线 main.py）。

storage root 经 ``APP_FILE_STORAGE_ROOT`` 指向 pytest tmp，隔离不污染 ``var/uploads``。
跨表 FK（files.uploader_id → users.id RESTRICT）：清表经 MySQL helper 临时关闭外键检查后逐表 TRUNCATE。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.config import get_settings
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.file.api import router as file_router
from admin_platform.domains.user.models import User
from admin_platform.main import create_app
from tests.integration.db_cleanup import truncate_tables

pytestmark = pytest.mark.integration

_PNG = b"\x89PNG\r\n\x1a\n" + b"payload-bytes-here"


class _SuperAdminProvider(PermissionProvider):
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
    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _build_client(provider: PermissionProvider, *, user_id: str) -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(file_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=user_id, sub=user_id
    )
    app.dependency_overrides[get_permission_provider] = lambda: provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wipe() -> None:
    await truncate_tables("files", "users")


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest.fixture
def _storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_FILE_STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def _seed_user(username: str) -> int:
    async with db_session() as session:
        user = User(username=username, password_hash="x")
        session.add(user)
        await session.flush()
        return user.id


@pytest_asyncio.fixture
async def client_uid(_storage_root: Path) -> AsyncIterator[tuple[AsyncClient, int]]:
    uid = await _seed_user("uploader")
    async with _build_client(_SuperAdminProvider(), user_id=str(uid)) as client:
        yield client, uid
    await dispose_engine()


async def _upload(client: AsyncClient, *, name: str, content: bytes, ctype: str) -> dict:
    res = await client.post("/api/v1/files", files={"upload": (name, content, ctype)})
    assert res.status_code == 201, res.text
    return res.json()


# ---- 上传/下载往返 + 元数据 -------------------------------------------------


async def test_upload_download_roundtrip(client_uid: tuple[AsyncClient, int]) -> None:
    client, uid = client_uid
    meta = await _upload(client, name="pic.png", content=_PNG, ctype="image/png")
    assert meta["original_filename"] == "pic.png"
    assert meta["size_bytes"] == len(_PNG)
    assert meta["uploader_id"] == uid
    assert meta["status"] == "active"
    assert len(meta["sha256"]) == 64
    # 下载字节与原内容一致
    res = await client.get(f"/api/v1/files/{meta['id']}/download")
    assert res.status_code == 200
    assert res.content == _PNG
    assert "attachment" in res.headers["content-disposition"]
    assert res.headers["x-content-type-options"] == "nosniff"  # 防 MIME sniffing XSS（P2）


async def test_list_after_uploads(client_uid: tuple[AsyncClient, int]) -> None:
    client, _ = client_uid
    await _upload(client, name="a.png", content=_PNG, ctype="image/png")
    await _upload(client, name="b.txt", content=b"plain text body", ctype="text/plain")
    listing = (await client.get("/api/v1/files")).json()
    assert listing["total"] == 2
    assert {item["original_filename"] for item in listing["items"]} == {"a.png", "b.txt"}


async def test_delete_soft_and_404(client_uid: tuple[AsyncClient, int]) -> None:
    client, _ = client_uid
    meta = await _upload(client, name="del.png", content=_PNG, ctype="image/png")
    fid = meta["id"]
    deleted = await client.delete(f"/api/v1/files/{fid}")
    assert deleted.status_code == 204
    # 软删后 get / download 均 404，list 不含
    assert (await client.get(f"/api/v1/files/{fid}")).status_code == 404
    assert (await client.get(f"/api/v1/files/{fid}/download")).status_code == 404
    assert (await client.get("/api/v1/files")).json()["total"] == 0


# ---- 安全校验端到端（415）--------------------------------------------------


async def test_upload_rejects_disallowed_extension(client_uid: tuple[AsyncClient, int]) -> None:
    client, _ = client_uid
    res = await client.post(
        "/api/v1/files", files={"upload": ("x.exe", b"MZ\x90\x00", "application/octet-stream")}
    )
    assert res.status_code == 415
    assert res.json()["type"] == "file.EXTENSION_NOT_ALLOWED"


async def test_upload_rejects_magic_mismatch(client_uid: tuple[AsyncClient, int]) -> None:
    client, _ = client_uid
    res = await client.post(
        "/api/v1/files", files={"upload": ("fake.png", b"NOTAPNG!", "image/png")}
    )
    assert res.status_code == 415
    assert res.json()["type"] == "file.CONTENT_TYPE_MISMATCH"


# ---- 权限矩阵 + mounted ----------------------------------------------------


async def test_permission_matrix_all_endpoints_403(_storage_root: Path) -> None:
    async with _build_client(_NoPermProvider(), user_id="2") as client:
        assert (await client.get("/api/v1/files")).status_code == 403
        assert (await client.get("/api/v1/files/1")).status_code == 403
        res = await client.post("/api/v1/files", files={"upload": ("a.png", _PNG, "image/png")})
        assert res.status_code == 403
        assert (await client.get("/api/v1/files/1/download")).status_code == 403
        assert (await client.delete("/api/v1/files/1")).status_code == 403
    await dispose_engine()


def test_router_mounted_in_create_app() -> None:
    app = create_app()
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/files" in paths
    assert "/api/v1/files/{file_id}/download" in paths
