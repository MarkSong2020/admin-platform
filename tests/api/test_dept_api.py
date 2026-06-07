"""/api/v1/depts 的 API 测试 —— 权限守卫接线 + 校验（DB-free）。

本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception handler），错误响应里的
``request_id`` 字段与线上一致。这里只跑「不需要真 DB」的路径：

  * **权限守卫接线**：无 token → 401；有 token 无权限 → 403（默认 deny，spec §3.2）；
    超管短路 → 放行后才轮到校验。
  * **校验 422**：在 service / AsyncSession 依赖之前短路（用超管 stub 越过守卫后触发）。

完整 CRUD happy / NOT_FOUND / 成环 / 有子禁删 路径放 ``tests/integration/test_dept_crud.py``（真 DB）。
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
from admin_platform.domains.dept.api import router


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


def _superadmin_client() -> TestClient:
    """越过守卫（超管短路）—— 让请求走到 Pydantic 校验层。"""
    return _client(
        current_user=CurrentUser(user_id="1", sub="1"),
        provider=_StubProvider(is_super=True),
    )


def _client(*, current_user: CurrentUser | None, provider: PermissionProvider | None) -> TestClient:
    return TestClient(_make_app(current_user=current_user, provider=provider))


# ---- 权限守卫接线（默认 deny + 超管短路）----------------------------------


def test_list_without_auth_returns_401() -> None:
    # 无 override、无 AuthMiddleware → require_current_user fail-closed → 401。
    res = _client(current_user=None, provider=None).get("/api/v1/depts")
    assert res.status_code == 401


def test_list_without_permission_returns_403() -> None:
    # 已登录但权限集为空 → 默认 deny → 403 auth.FORBIDDEN_BY_ROLE。
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset()),
    )
    res = client.get("/api/v1/depts")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_delete_with_only_list_permission_returns_403() -> None:
    # 有 list 权限但无 remove 权限 → 调删除被默认 deny 拒（按钮权限 403）。
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset({"system:dept:list"})),
    )
    res = client.delete("/api/v1/depts/1")
    assert res.status_code == 403


# ---- 校验 422（超管越过守卫后触发）----------------------------------------


def test_create_returns_422_on_missing_field() -> None:
    # 缺 name / code 必填字段。
    res = _superadmin_client().post("/api/v1/depts", json={})
    assert res.status_code == 422


def test_update_returns_422_on_invalid_payload() -> None:
    res = _superadmin_client().patch("/api/v1/depts/1", json={"name": 123})
    assert res.status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    res = _superadmin_client().get("/api/v1/depts?size=101")
    assert res.status_code == 422
