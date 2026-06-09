"""/api/v1/monitor/server + /cache 的 API 测试 —— 权限守卫接线（DB-free）。

服务/缓存监控是只读单视图（perm = ``system:server:list`` / ``system:cache:list``）。本地 app 镜像
生产 middleware 拓扑。200 路径用 stub service 喂 canned 指标（不跑真 psutil / Redis，保持 DB-free
且无平台抖动）；401/403 在守卫层就被拦，不到 service。
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
from admin_platform.domains.monitor.deps import get_system_monitor_service
from admin_platform.domains.monitor.schemas import (
    CacheMetrics,
    ServerCpu,
    ServerDisk,
    ServerMemory,
    ServerMetrics,
    ServerProcess,
    ServerSwap,
    ServerSys,
)

SERVER_URL = "/api/v1/monitor/server"
CACHE_URL = "/api/v1/monitor/cache"


# ---- canned 指标 + stub service --------------------------------------------


def _canned_server() -> ServerMetrics:
    now = datetime.now(UTC)
    return ServerMetrics(
        cpu=ServerCpu(
            cores=4, percent=12.5, per_cpu=[10.0, 15.0, 12.0, 13.0], load_avg=[0.5, 0.4, 0.3]
        ),
        memory=ServerMemory(
            total=16_000_000_000, available=8_000_000_000, used=8_000_000_000, percent=50.0
        ),
        swap=ServerSwap(total=0, used=0, free=0, percent=0.0),
        disks=[
            ServerDisk(
                device="/dev/disk1",
                mountpoint="/",
                fstype="apfs",
                total=100,
                used=40,
                free=60,
                percent=40.0,
            )
        ],
        sys=ServerSys(
            hostname="test-host",
            os_name="Darwin",
            os_release="25.0",
            arch="arm64",
            python_version="3.14.0",
            boot_time=now,
        ),
        process=ServerProcess(
            pid=123,
            cpu_percent=1.0,
            memory_percent=2.0,
            memory_rss=1024,
            num_threads=8,
            create_time=now,
        ),
        collected_at=now,
    )


def _canned_cache(*, available: bool = True) -> CacheMetrics:
    return CacheMetrics(
        available=available,
        db_size=7 if available else None,
        info=None,
        command_stats=[],
        collected_at=datetime.now(UTC),
    )


class _StubService:
    """duck-typed 替身：dependency_overrides 注入，路由只调这两个方法。"""

    async def get_server_metrics(self) -> ServerMetrics:
        return _canned_server()

    async def get_cache_metrics(self) -> CacheMetrics:
        return _canned_cache(available=False)


# ---- 权限 provider 替身（复用各域 api 测试同款）-------------------------------


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
    # 直接传类（FastAPI 作依赖会实例化）；无参 lambda 会触 PLW0108。
    app.dependency_overrides[get_system_monitor_service] = _StubService
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


def test_server_without_auth_returns_401() -> None:
    assert _client(current_user=None, provider=None).get(SERVER_URL).status_code == 401


def test_cache_without_auth_returns_401() -> None:
    assert _client(current_user=None, provider=None).get(CACHE_URL).status_code == 401


# ---- 403 缺权限（默认 deny）-------------------------------------------------


def test_server_without_permission_returns_403() -> None:
    res = _perm_client().get(SERVER_URL)
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_cache_without_permission_returns_403() -> None:
    assert _perm_client().get(CACHE_URL).status_code == 403


def test_server_perm_does_not_grant_cache() -> None:
    """权限隔离：拿 server:list 不等于拿 cache:list。"""
    client = _perm_client("system:server:list")
    assert client.get(SERVER_URL).status_code == 200
    assert client.get(CACHE_URL).status_code == 403


def test_cache_perm_does_not_grant_server() -> None:
    client = _perm_client("system:cache:list")
    assert client.get(CACHE_URL).status_code == 200
    assert client.get(SERVER_URL).status_code == 403


# ---- 200 超管短路 + 精确权限 ------------------------------------------------


def test_server_super_admin_200() -> None:
    res = _super_client().get(SERVER_URL)
    assert res.status_code == 200
    body = res.json()
    assert body["memory"]["total"] == 16_000_000_000
    assert body["cpu"]["cores"] == 4


def test_cache_super_admin_200_available_false() -> None:
    res = _super_client().get(CACHE_URL)
    assert res.status_code == 200
    assert res.json()["available"] is False
