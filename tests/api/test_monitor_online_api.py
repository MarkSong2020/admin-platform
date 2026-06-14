"""/api/v1/monitor/online 的 API 测试 —— 权限守卫 + 校验（DB-free）。

在线用户：list（system:online:list）+ 强制下线 DELETE（system:online:remove）。本地 app 镜像生产
middleware 拓扑。list 200 用 stub service 喂 canned 分页；强退的 204 成功路径（走 audited_write 真
审计）留 tests/integration/test_monitor_online_integration.py。这里只验守卫矩阵 + 路径 UUID 校验。
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
from admin_platform.domains.monitor.api import router
from admin_platform.domains.monitor.deps import get_monitor_service
from admin_platform.domains.monitor.schemas import (
    AuditEventPage,
    LoginLogPage,
    OnlineSession,
    OnlineSessionPage,
)
from tests.api._support import override_get_session

LIST_URL = "/api/v1/monitor/online"
_SESSION_UUID = "11111111-1111-1111-1111-111111111111"
KICK_URL = f"/api/v1/monitor/online/{_SESSION_UUID}"


def _canned_page() -> OnlineSessionPage:
    now = datetime.now(UTC)
    return OnlineSessionPage(
        items=[
            OnlineSession(
                session_id=_SESSION_UUID,
                user_id=9,
                username="alice",
                login_time=now,
                last_active_time=now,
                expires_at=now,
            )
        ],
        page=1,
        size=20,
        total=1,
        total_pages=1,
    )


class _StubService:
    async def list_online_sessions(self, *, page: int, size: int) -> OnlineSessionPage:
        return _canned_page()

    async def force_logout(self, session_id: object) -> str:
        return "alice"

    # operlog / logininfor 也走 get_monitor_service —— 哑实现回空页，供 canonical 请求形状回归用。
    async def list_audit_events(self, **kw: object) -> AuditEventPage:
        return AuditEventPage(items=[], page=1, size=10, total=0, total_pages=0)

    async def list_login_logs(self, **kw: object) -> LoginLogPage:
        return LoginLogPage(items=[], page=1, size=10, total=0, total_pages=0)


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
    app.dependency_overrides[get_monitor_service] = _StubService
    if current_user is not None:
        app.dependency_overrides[require_current_user] = lambda: current_user
    if provider is not None:
        app.dependency_overrides[get_permission_provider] = lambda: provider
    return TestClient(app)


def _super_client() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="1", sub="1"), provider=_StubProvider(is_super=True)
    )


def _perm_client(*perms: str) -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset(perms)),
    )


# ---- 401 未登录 -------------------------------------------------------------


def test_list_without_auth_returns_401() -> None:
    assert _client(current_user=None, provider=None).get(LIST_URL).status_code == 401


def test_kick_without_auth_returns_401() -> None:
    assert _client(current_user=None, provider=None).delete(KICK_URL).status_code == 401


# ---- 403 缺权限（默认 deny）-------------------------------------------------


def test_list_without_permission_returns_403() -> None:
    res = _perm_client().get(LIST_URL)
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_kick_without_permission_returns_403() -> None:
    assert _perm_client().delete(KICK_URL).status_code == 403


def test_list_perm_does_not_grant_kick() -> None:
    """权限隔离：online:list 不等于 online:remove。"""
    client = _perm_client("system:online:list")
    assert client.get(LIST_URL).status_code == 200
    assert client.delete(KICK_URL).status_code == 403


def test_kick_perm_does_not_grant_list() -> None:
    client = _perm_client("system:online:remove")
    assert client.get(LIST_URL).status_code == 403


# ---- 200 list（超管短路 + stub service）-------------------------------------


def test_list_super_admin_200() -> None:
    res = _super_client().get(LIST_URL)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["username"] == "alice"
    assert body["items"][0]["session_id"] == _SESSION_UUID


# ---- 422 路径 UUID 校验（超管越过守卫后触发）--------------------------------


def test_kick_malformed_session_id_returns_422() -> None:
    assert _super_client().delete("/api/v1/monitor/online/not-a-uuid").status_code == 422


def test_list_size_above_max_is_rejected() -> None:
    assert _super_client().get(f"{LIST_URL}?size=101").status_code == 422


# ---- canonical 分页请求形状回归（锁住 ?page=&size=&<filter> → 200，防混用 422 反模式复发）----
# monitor 三个分页 list 端点（online / operlog / logininfor）都走 get_monitor_service，本文件
# 已 override 成 stub，故可在同一 app 上发 canonical 请求。online 无 filter，只 page/size。


def test_online_canonical_page_size_200() -> None:
    assert _super_client().get(f"{LIST_URL}?page=1&size=10").status_code == 200


def test_operlog_canonical_page_size_filter_200() -> None:
    res = _super_client().get(
        "/api/v1/monitor/operlog?page=1&size=10"
        "&event_type=login&actor_user_id=1&result_status=success"
    )
    assert res.status_code == 200


def test_logininfor_canonical_page_size_filter_200() -> None:
    res = _super_client().get(
        "/api/v1/monitor/logininfor?page=1&size=10&username=admin&status=success"
    )
    assert res.status_code == 200
