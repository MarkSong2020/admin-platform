"""/api/v1/users 的 API 测试 —— 权限守卫接线 + 列表分页解析（DB-free）。

本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception handler），错误响应里的
``request_id`` 字段与线上一致。这里只跑「不需要真 DB」的路径：

  * **权限守卫接线（spec §3.2 默认 deny）**：无 token → 401；有 token 无权限 → 403。
  * **列表分页解析（P0 回归）**：page/size 折进 ``UserListQuery``（query-model 与独立标量
    page/size Query 并存时，标量令整个 model 形参无法从 query 填充 → 422「该模型参数 missing」，
    与 extra 策略无关）；同传过滤参数 → 200。

完整 CRUD happy / NOT_FOUND / data_scope 路径放 ``tests/integration/test_user_crud.py``（真 DB）。
不用 MagicMock / AsyncMock（项目红线）——用手写哑对象。
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
from admin_platform.domains.user.api import router
from admin_platform.domains.user.deps import get_user_service
from admin_platform.domains.user.schemas import UserListQuery, UserPage
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

    async def list_(
        self,
        query: UserListQuery,
        *,
        page: int,
        size: int,
        scope: DataScope | None = None,
    ) -> UserPage:
        return UserPage(items=[], page=page, size=size, total=0, total_pages=0)


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


def _no_perm_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset()),
    )


# ---- 权限守卫接线（默认 deny + 超管短路）----------------------------------


def test_list_without_auth_returns_401() -> None:
    # 无 override、无 AuthMiddleware → require_current_user fail-closed → 401。
    res = _client(current_user=None, provider=None).get("/api/v1/users")
    assert res.status_code == 401


def test_list_without_permission_returns_403() -> None:
    res = _no_perm_client().get("/api/v1/users")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


# ---- 列表分页解析（P0 回归）----------------------------------------------


def test_list_size_above_max_is_rejected() -> None:
    app = _make_app(
        current_user=CurrentUser(user_id="1", sub="1"),
        provider=_StubProvider(is_super=True),
    )
    res = TestClient(app).get("/api/v1/users?size=101")
    assert res.status_code == 422


def test_list_with_page_size_and_filter_returns_200() -> None:
    # P0 回归：page/size 与过滤参数（status）同传 → 200（修复前混用独立标量 page/size Query 令
    # query-model 形参无法从 query 填充 → 422「该模型参数 missing」，与 extra 策略无关）。
    # stub service 回显 page/size 验证解析正确。
    app = _make_app(
        current_user=CurrentUser(user_id="1", sub="1"),
        provider=_StubProvider(is_super=True),
    )
    app.dependency_overrides[get_user_service] = _StubListService
    res = TestClient(app).get("/api/v1/users?page=1&size=10&status=active")
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 1
    assert body["size"] == 10
    assert body["items"] == []
