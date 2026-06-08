"""/api/v1/menus 的 API 测试 —— 权限守卫接线 + 校验（DB-free）。

本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception handler），错误响应里的
``request_id`` 字段与线上一致。这里只跑「不需要真 DB」的路径：

  * **权限守卫接线（spec §3.2 默认 deny）**：无 token → 401；有 token 无权限 → 403（5 端点矩阵）；
    超管短路 → 放行后才轮到校验。
  * **校验 422**：在 service / AsyncSession 依赖之前短路（用超管 stub 越过守卫后触发）。

完整 CRUD happy / NOT_FOUND / 树路径放 ``tests/integration/test_menu_crud.py``（真 DB）。
menu router 挂进生产 ``create_app()`` 是人值守红线（``main.py``），落地后补一条「mounted」回归。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.domains.menu.api import router
from admin_platform.domains.menu.deps import get_menu_service
from admin_platform.domains.menu.schemas import MenuCreate, MenuPage, MenuRead, MenuUpdate


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
    res = _client(current_user=None, provider=None).get("/api/v1/menus")
    assert res.status_code == 401


def test_list_without_permission_returns_403() -> None:
    res = _no_perm_client().get("/api/v1/menus")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_query_without_permission_returns_403() -> None:
    assert _no_perm_client().get("/api/v1/menus/1").status_code == 403


def test_add_without_permission_returns_403() -> None:
    res = _no_perm_client().post("/api/v1/menus", json={"name": "x", "menu_type": "C"})
    assert res.status_code == 403


def test_edit_without_permission_returns_403() -> None:
    assert _no_perm_client().patch("/api/v1/menus/1", json={"name": "x"}).status_code == 403


def test_remove_without_permission_returns_403() -> None:
    # 有 list 权限但无 remove 权限 → 调删除被默认 deny 拒（按钮权限 403）。
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset({"system:menu:list"})),
    )
    assert client.delete("/api/v1/menus/1").status_code == 403


# ---- 校验 422（超管越过守卫后触发）----------------------------------------


def test_create_returns_422_on_missing_field() -> None:
    # 缺 name / menu_type 必填字段。
    res = _superadmin_client().post("/api/v1/menus", json={})
    assert res.status_code == 422


def test_create_invalid_menu_type_rejected_422() -> None:
    # menu_type 非 M/C/F → Pydantic Literal 拒绝。
    res = _superadmin_client().post("/api/v1/menus", json={"name": "x", "menu_type": "Z"})
    assert res.status_code == 422


def test_update_invalid_status_rejected_422() -> None:
    res = _superadmin_client().patch("/api/v1/menus/1", json={"status": "bogus"})
    assert res.status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    res = _superadmin_client().get("/api/v1/menus?size=101")
    assert res.status_code == 422


# ---- happy-path（stub service 越过 DB，覆盖 handler 路由 / 序列化）---------

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _read(item_id: int = 1, name: str = "用户") -> MenuRead:
    return MenuRead(
        id=item_id,
        parent_id=None,
        name=name,
        menu_type="C",
        path="user",
        component="views/User",
        perms="system:user:list",
        icon="",
        sort_order=0,
        visible=True,
        status="active",
        created_at=_TS,
        updated_at=_TS,
    )


class _StubService:
    """MenuService 替身（不查 DB）：让 api handler body 在 unit/api 跑里执行。"""

    async def list_(self, *, page: int, size: int) -> MenuPage:
        return MenuPage(items=[_read()], page=page, size=size, total=1, total_pages=1)

    async def get(self, item_id: int) -> MenuRead:
        return _read(item_id)

    async def create(self, payload: MenuCreate) -> MenuRead:
        return _read(name=payload.name)

    async def update(self, item_id: int, payload: MenuUpdate) -> MenuRead:
        return _read(item_id)

    async def delete(self, item_id: int) -> None:
        return None


def _stub_service_client() -> TestClient:
    app = _make_app(
        current_user=CurrentUser(user_id="1", sub="1"),
        provider=_StubProvider(is_super=True),
    )
    app.dependency_overrides[get_menu_service] = _StubService
    return TestClient(app)


def test_happy_paths_through_handlers() -> None:
    client = _stub_service_client()
    assert client.get("/api/v1/menus").status_code == 200
    assert client.get("/api/v1/menus/1").status_code == 200
    created = client.post("/api/v1/menus", json={"name": "用户", "menu_type": "C"})
    assert created.status_code == 201
    assert client.patch("/api/v1/menus/1", json={"name": "x"}).status_code == 200
    assert client.delete("/api/v1/menus/1").status_code == 204
