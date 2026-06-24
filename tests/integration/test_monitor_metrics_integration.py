"""服务/缓存监控 API 集成测试（P4）—— 经真实 app 走真 psutil + 真 Redis。

补 DB-free api 测试缺的「真实接线」腿：/server 跑真 psutil；/cache 覆盖 Redis 配置/缺失两情形。
覆盖 deps 组合根（get_system_monitor_service 读 app.state.redis 的 present/absent 两分支）+ 真实
service→collector 端到端。缓存 available=True 分支需本地 Redis（CI integration lane 提供）。
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.config import get_settings
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.domains.monitor.api import router as monitor_router

pytestmark = pytest.mark.integration


class _SuperProvider(PermissionProvider):
    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _app(*, with_redis: bool) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(monitor_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = _SuperProvider
    if with_redis:
        app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_server_metrics_real_psutil() -> None:
    """真实 app + 真 psutil：deps 组合根（无 redis 分支）+ service.get_server_metrics 全打通。"""
    async with _client(_app(with_redis=False)) as c:
        resp = await c.get("/api/v1/monitor/server")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["memory"]["total"] > 0
        assert body["cpu"]["cores"] is None or body["cpu"]["cores"] >= 1
        assert isinstance(body["disks"], list)
        assert body["process"]["pid"] > 0
        assert body["sys"]["python_version"]


async def test_cache_metrics_unavailable_without_redis() -> None:
    """app.state.redis 缺失 → available=False（不 500）。覆盖 deps 的 redis=None 分支。"""
    async with _client(_app(with_redis=False)) as c:
        resp = await c.get("/api/v1/monitor/cache")
        assert resp.status_code == 200, resp.text
        assert resp.json()["available"] is False


@pytest.mark.redis_integration
async def test_cache_metrics_real_redis() -> None:
    """真 Redis：available=True + 真实 INFO 字段。覆盖 deps 的 redis-present 分支 + 真采集。"""
    app = _app(with_redis=True)
    try:
        try:
            await app.state.redis.ping()
        except (RedisError, OSError) as exc:
            strict = os.environ.get("STRICT_REDIS_INTEGRATION", "").lower() in {
                "1",
                "true",
                "yes",
            }
            msg = f"Redis unavailable at {get_settings().redis_url}: {exc}"
            if strict:
                pytest.fail(msg + " — STRICT_REDIS_INTEGRATION=1 is set.")
            pytest.skip(msg)
        async with _client(app) as c:
            resp = await c.get("/api/v1/monitor/cache")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["available"] is True
            assert body["info"]["version"]
            assert body["db_size"] >= 0
    finally:
        await app.state.redis.aclose()
