"""/api/v1/posts 的 API 测试 —— 权限守卫接线 + 校验（DB-free）。

本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception handler），错误响应里的
``request_id`` 字段与线上一致。这里只跑「不需要真 DB」的路径：

  * **权限守卫接线（spec §3.2 默认 deny）**：无 token → 401；有 token 无权限 → 403（5 端点矩阵）；
    超管短路 → 放行后才轮到校验。
  * **校验 422**：在 service / AsyncSession 依赖之前短路（用超管 stub 越过守卫后触发）。

完整 CRUD happy / NOT_FOUND / 绑定 路径放 ``tests/integration/test_post_crud.py``（真 DB）。
post router 挂进生产 ``create_app()`` 是人值守红线（``main.py``），落地后补一条「mounted」回归。
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.domains.post.api import router
from admin_platform.domains.post.deps import get_post_service
from admin_platform.domains.post.schemas import PostListQuery, PostPage
from tests.api._support import override_get_session


class _StubProvider(PermissionProvider):
    """可配的权限 stub：``is_super`` 控制超管短路，``perms`` 控制普通用户权限集。"""

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


class _StubListService:
    """只实现 list_ 的哑 service：回显收到的 page/size，验证 query 模型解析（不连 DB / 不用 Mock）。"""

    async def list_(self, query: PostListQuery, *, page: int, size: int) -> PostPage:
        return PostPage(items=[], page=page, size=size, total=0, total_pages=0)


def _make_app(*, current_user: CurrentUser | None, provider: PermissionProvider | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    # require_permission 守卫的「顺序保证」依赖了 get_session（P1 架构修复）；DB-free 测试把它
    # override 成不连库的占位，否则守卫解析时会去连真 DB。
    override_get_session(app.dependency_overrides)
    if current_user is not None:
        app.dependency_overrides[require_current_user] = lambda: current_user
    if provider is not None:
        app.dependency_overrides[get_permission_provider] = lambda: provider
    return app


def _client(*, current_user: CurrentUser | None, provider: PermissionProvider | None) -> TestClient:
    return TestClient(_make_app(current_user=current_user, provider=provider))


def _superadmin_client() -> TestClient:
    """越过守卫（超管短路）—— 让请求走到 Pydantic 校验层。"""
    return _client(
        current_user=CurrentUser(user_id="1", sub="1"),
        provider=_StubProvider(is_super=True),
    )


def _no_perm_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset()),
    )


# ---- 权限守卫接线（默认 deny + 超管短路）----------------------------------


def test_list_without_auth_returns_401() -> None:
    # 无 override、无 AuthMiddleware → require_current_user fail-closed → 401。
    res = _client(current_user=None, provider=None).get("/api/v1/posts")
    assert res.status_code == 401


def test_list_without_permission_returns_403() -> None:
    res = _no_perm_client().get("/api/v1/posts")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_query_without_permission_returns_403() -> None:
    assert _no_perm_client().get("/api/v1/posts/1").status_code == 403


def test_add_without_permission_returns_403() -> None:
    res = _no_perm_client().post("/api/v1/posts", json={"name": "x", "code": "X"})
    assert res.status_code == 403


def test_edit_without_permission_returns_403() -> None:
    assert _no_perm_client().patch("/api/v1/posts/1", json={"name": "x"}).status_code == 403


def test_remove_without_permission_returns_403() -> None:
    # 有 list 权限但无 remove 权限 → 调删除被默认 deny 拒（按钮权限 403）。
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset({"system:post:list"})),
    )
    assert client.delete("/api/v1/posts/1").status_code == 403


# ---- 校验 422（超管越过守卫后触发）----------------------------------------


def test_create_returns_422_on_missing_field() -> None:
    # 缺 name / code 必填字段。
    res = _superadmin_client().post("/api/v1/posts", json={})
    assert res.status_code == 422


def test_update_invalid_status_rejected_422() -> None:
    res = _superadmin_client().patch("/api/v1/posts/1", json={"status": "bogus"})
    assert res.status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    res = _superadmin_client().get("/api/v1/posts?size=101")
    assert res.status_code == 422


def test_list_with_page_size_and_filter_returns_200() -> None:
    # P0 回归：page/size 与过滤参数（status）同传 → 200（修复前混用独立标量 page/size Query 令
    # query-model 形参无法从 query 填充 → 422「该模型参数 missing」，与 extra 策略无关）。
    # stub service 回显 page/size 验证解析正确。
    app = _make_app(
        current_user=CurrentUser(user_id="1", sub="1"),
        provider=_StubProvider(is_super=True),
    )
    app.dependency_overrides[get_post_service] = _StubListService
    res = TestClient(app).get("/api/v1/posts?page=1&size=10&status=active")
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 1
    assert body["size"] == 10
    assert body["items"] == []


# ---- Excel 导入导出权限矩阵 + 校验（P5）-----------------------------------

_XLSX = (
    "p.xlsx",
    b"PK\x03\x04stub",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)


def test_import_without_permission_returns_403() -> None:
    res = _no_perm_client().post("/api/v1/posts/import", files={"upload": _XLSX})
    assert res.status_code == 403


def test_export_without_permission_returns_403() -> None:
    assert _no_perm_client().get("/api/v1/posts/export").status_code == 403


def test_import_missing_file_returns_422() -> None:
    # 缺 multipart 文件字段（upload 必填）→ 422，在 service/DB 依赖前短路。
    res = _superadmin_client().post("/api/v1/posts/import")
    assert res.status_code == 422


def _zip_bomb_bytes() -> bytes:
    # 小压缩 / 大解压（全零）→ 压缩比超默认 100x，reader 解压前预检拒绝（触不达 DB）。
    buffer = BytesIO()
    payload = b"<sst>" + b"0" * (20 * 1024 * 1024) + b"</sst>"
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", payload)
    return buffer.getvalue()


def test_import_zip_bomb_returns_413() -> None:
    # P1：解压前中央目录预检拦截 zip bomb → 413（与上传体积超限同语义），在 openpyxl 解压前短路。
    files = {
        "upload": (
            "bomb.xlsx",
            _zip_bomb_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    res = _superadmin_client().post("/api/v1/posts/import", files=files)
    assert res.status_code == 413
    assert res.json()["type"] == "post.EXCEL_TOO_LARGE"
