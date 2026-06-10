"""/api/v1/files 的 API 测试 —— 权限守卫接线 + 校验（DB-free）。

本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception handler），错误响应里的
``request_id`` 字段与线上一致。这里只跑「不需要真 DB」的路径：

  * **权限守卫接线（默认 deny）**：无 token → 401；有 token 无权限 → 403（5 端点矩阵）；
    超管短路 → 放行后才轮到校验。
  * **校验 422**：multipart 缺文件字段 / 分页越界，在 service / AsyncSession 依赖前短路。

完整上传/下载/删除往返放 ``tests/integration/test_file_crud.py``（真 DB + 真 fs）。
file router 挂进生产 ``create_app()`` 是人值守红线（``main.py``），已落地（mounted 回归在集成）。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.domains.file.api import _content_disposition, router

_PNG = ("a.png", b"\x89PNG\r\n\x1a\nimg", "image/png")


class _StubProvider(PermissionProvider):
    """可配权限 stub：``is_super`` 控超管短路，``perms`` 控普通用户权限集。"""

    def __init__(self, *, is_super: bool = False, perms: frozenset[str] = frozenset()) -> None:
        self._is_super = is_super
        self._perms = perms

    def get_is_super_admin(self, user_id: int) -> bool:
        return self._is_super

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return self._perms

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _make_app(*, current_user: CurrentUser | None, provider: PermissionProvider | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    if current_user is not None:
        app.dependency_overrides[require_current_user] = lambda: current_user
    if provider is not None:
        app.dependency_overrides[get_permission_provider] = lambda: provider
    return app


def _client(*, current_user: CurrentUser | None, provider: PermissionProvider | None) -> TestClient:
    return TestClient(_make_app(current_user=current_user, provider=provider))


def _superadmin_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="1", sub="1"), provider=_StubProvider(is_super=True)
    )


def _no_perm_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset()),
    )


# ---- 权限守卫接线（默认 deny + 超管短路）----------------------------------


def test_list_without_auth_returns_401() -> None:
    res = _client(current_user=None, provider=None).get("/api/v1/files")
    assert res.status_code == 401


def test_list_without_permission_returns_403() -> None:
    res = _no_perm_client().get("/api/v1/files")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_query_without_permission_returns_403() -> None:
    assert _no_perm_client().get("/api/v1/files/1").status_code == 403


def test_upload_without_permission_returns_403() -> None:
    res = _no_perm_client().post("/api/v1/files", files={"upload": _PNG})
    assert res.status_code == 403


def test_download_without_permission_returns_403() -> None:
    assert _no_perm_client().get("/api/v1/files/1/download").status_code == 403


def test_delete_without_permission_returns_403() -> None:
    # 有 list 权限但无 remove 权限 → 删除被默认 deny 拒（按钮权限 403）。
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset({"system:file:list"})),
    )
    assert client.delete("/api/v1/files/1").status_code == 403


# ---- 校验 422（超管越过守卫后触发）----------------------------------------


def test_upload_missing_file_returns_422() -> None:
    # 缺 multipart 文件字段（upload 必填）→ 422，在 service/DB 依赖前短路。
    res = _superadmin_client().post("/api/v1/files")
    assert res.status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    res = _superadmin_client().get("/api/v1/files?size=101")
    assert res.status_code == 422


# ---- Content-Disposition 注入防御（对抗审查 P1）---------------------------


def test_content_disposition_strips_crlf_and_quotes() -> None:
    # 文件名含裸引号 + CRLF + 分号 → 回退段剥离，整 header 无换行（防响应头注入/参数越界）。
    out = _content_disposition('a"b\r\nc;x=evil.png')
    assert "\r" not in out
    assert "\n" not in out
    fallback = out.split('filename="')[1].split('"')[0]  # 包裹引号内的 ASCII 回退名
    assert '"' not in fallback
    assert ";" not in fallback


def test_content_disposition_unicode_uses_rfc5987() -> None:
    # 纯中文名（无 ASCII 字符）→ ASCII 回退退化为 download，UTF-8 段百分号编码携带原名。
    out = _content_disposition("报表")
    assert "filename*=UTF-8''" in out
    assert 'filename="download"' in out
