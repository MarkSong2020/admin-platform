"""/api/v1/configs 的 API 测试 —— 权限守卫接线 + 校验（DB-free）。

只跑「不需要真 DB」的路径：权限守卫（无 token 401 / 无权限 403 矩阵，含消费端点 /value/{key}）+
校验 422。完整 CRUD / 热更新 / 内置禁删 放 ``tests/integration/test_config_crud.py``（真 DB）。
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
from admin_platform.domains.config.api import router
from admin_platform.domains.config.deps import get_config_service
from admin_platform.domains.config.schemas import ConfigPage
from tests.api._support import override_get_session

_VALID = {"name": "初始密码", "config_key": "sys.user.initPassword", "config_value": "changeit"}


class _StubListService:
    """只实现 list_ 的哑 service：回显 page/size，验证 canonical 请求解析（不连 DB / 不用 Mock）。"""

    async def list_(self, *, keyword: str | None, page: int, size: int) -> ConfigPage:
        return ConfigPage(items=[], page=page, size=size, total=0, total_pages=0)


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
    # require_permission 守卫的「顺序保证」依赖了 get_session（P1 架构修复）；DB-free 测试把它
    # override 成不连库的占位，否则守卫解析时会去连真 DB。
    override_get_session(app.dependency_overrides)
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


# ---- 权限守卫（默认 deny + 超管短路）--------------------------------------


def test_list_without_auth_returns_401() -> None:
    assert _client(current_user=None, provider=None).get("/api/v1/configs").status_code == 401


def test_list_without_permission_returns_403() -> None:
    res = _no_perm_client().get("/api/v1/configs")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_get_value_consumption_endpoint_requires_permission_403() -> None:
    # 消费端点也受默认 deny（守 query 权限）—— 防裸奔（test_route_auth_contract 同口径）。
    assert _no_perm_client().get("/api/v1/configs/value/sys.x").status_code == 403


def test_add_without_permission_returns_403() -> None:
    assert _no_perm_client().post("/api/v1/configs", json=_VALID).status_code == 403


def test_edit_without_permission_returns_403() -> None:
    assert (
        _no_perm_client().patch("/api/v1/configs/1", json={"config_value": "x"}).status_code == 403
    )


def test_remove_without_permission_returns_403() -> None:
    client = _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset({"system:config:list"})),
    )
    assert client.delete("/api/v1/configs/1").status_code == 403


# ---- 校验 422（超管越过守卫后触发）----------------------------------------


def test_create_returns_422_on_missing_field() -> None:
    assert _superadmin_client().post("/api/v1/configs", json={}).status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    assert _superadmin_client().get("/api/v1/configs?size=101").status_code == 422


# ---- canonical 分页请求形状回归（锁住 ?page=&size=&<filter> → 200，防混用 422 反模式复发）----


def test_list_canonical_page_size_filter_200() -> None:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    override_get_session(app.dependency_overrides)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = lambda: _StubProvider(is_super=True)
    app.dependency_overrides[get_config_service] = _StubListService
    res = TestClient(app).get("/api/v1/configs?page=1&size=10&keyword=sys")
    assert res.status_code == 200
