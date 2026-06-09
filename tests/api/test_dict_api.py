"""/api/v1/dict 的 API 测试 —— 权限守卫接线 + 校验（DB-free）。

只跑「不需要真 DB」的路径：权限守卫（无 token 401 / 无权限 403 矩阵，覆盖 types/data 两资源 +
消费端点 /data/type/{type}）+ 校验 422。完整 CRUD / 删类型 RESTRICT / 单默认 放
``tests/integration/test_dict_crud.py``（真 DB）。
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
from admin_platform.domains.dict.api import router

_TYPE = {"name": "用户性别", "type": "sys_user_sex"}
_DATA = {"dict_type_id": 1, "label": "男", "value": "0"}


class _StubProvider(PermissionProvider):
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


def _client(*, current_user: CurrentUser | None, provider: PermissionProvider | None) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    if current_user is not None:
        app.dependency_overrides[require_current_user] = lambda: current_user
    if provider is not None:
        app.dependency_overrides[get_permission_provider] = lambda: provider
    return TestClient(app)


def _superadmin_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="1", sub="1"), provider=_StubProvider(is_super=True)
    )


def _no_perm_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset()),
    )


# ---- 权限守卫（默认 deny + 超管短路）：types 资源 ------------------------


def test_types_list_without_auth_returns_401() -> None:
    assert _client(current_user=None, provider=None).get("/api/v1/dict/types").status_code == 401


def test_types_list_without_permission_returns_403() -> None:
    res = _no_perm_client().get("/api/v1/dict/types")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_types_add_without_permission_returns_403() -> None:
    assert _no_perm_client().post("/api/v1/dict/types", json=_TYPE).status_code == 403


def test_types_remove_without_permission_returns_403() -> None:
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset({"system:dict:list"})),
    )
    assert client.delete("/api/v1/dict/types/1").status_code == 403


# ---- 权限守卫：data 资源 + 消费端点 -------------------------------------


def test_data_list_without_permission_returns_403() -> None:
    assert _no_perm_client().get("/api/v1/dict/data").status_code == 403


def test_data_by_type_consumption_requires_permission_403() -> None:
    # 消费端点也受默认 deny（守 query 权限），防裸奔。
    assert _no_perm_client().get("/api/v1/dict/data/type/sys_user_sex").status_code == 403


def test_data_add_without_permission_returns_403() -> None:
    assert _no_perm_client().post("/api/v1/dict/data", json=_DATA).status_code == 403


# ---- 校验 422（超管越过守卫后触发）----------------------------------------


def test_type_create_returns_422_on_missing_field() -> None:
    assert _superadmin_client().post("/api/v1/dict/types", json={}).status_code == 422


def test_type_create_rejects_invalid_status_422() -> None:
    res = _superadmin_client().post("/api/v1/dict/types", json={**_TYPE, "status": "bogus"})
    assert res.status_code == 422


def test_data_create_returns_422_on_missing_field() -> None:
    assert _superadmin_client().post("/api/v1/dict/data", json={}).status_code == 422


def test_types_list_size_above_max_is_rejected() -> None:
    assert _superadmin_client().get("/api/v1/dict/types?size=101").status_code == 422
