"""监控日志查询 API 集成测试（P2 Phase 4）—— 分页 / 过滤 / detail / 404 + 权限守卫。

操作日志（audit_events）+ 登录日志（login_logs）只读查询；require_permission 默认 deny 守。需 DB。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin_platform.audit.models import AuditEventLog
from admin_platform.authz.permissions import Permissions
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.auth.models import LoginLog
from admin_platform.domains.monitor.api import router as monitor_router
from tests.integration.db_cleanup import truncate_tables

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


class _NoLogPermProvider(PermissionProvider):
    """active 非超管，持 user:list 但无 operlog 权限 → 403。"""

    def get_is_active(self, user_id: int) -> bool:
        return True

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset({Permissions.SYSTEM_USER_LIST})

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    await truncate_tables("audit_events", "login_logs")


async def _seed_audit(n: int, *, event_type: str = "rbac_write", status: str = "success") -> None:
    async with db_session() as session:
        for i in range(n):
            session.add(
                AuditEventLog(
                    event_id=f"evt-{event_type}-{status}-{i}",
                    schema_version="audit_event.v1",
                    event_type=event_type,
                    action="system:role:add",
                    title="审计",
                    occurred_at=datetime.now(UTC),
                    actor_user_id=1,
                    actor_username="admin",
                    actor_is_super_admin=True,
                    result_status=status,
                    risk_level="medium",
                    metadata_json={"k": "v"},
                    redaction_applied=False,
                    payload={"schema_version": "audit_event.v1", "event_type": event_type},
                )
            )


async def _seed_login(n: int, *, status: str = "success") -> None:
    async with db_session() as session:
        for i in range(n):
            session.add(
                LoginLog(username=f"u{i}", user_id=i, status=status, login_at_utc=datetime.now(UTC))
            )


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client(provider: type[PermissionProvider]) -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(monitor_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_operlog_list_paginated_and_filtered() -> None:
    await _seed_audit(3, event_type="rbac_write")
    await _seed_audit(2, event_type="login_failed", status="failure")
    async with _client(_SuperProvider) as c:
        resp = await c.get("/api/v1/monitor/operlog?page=1&size=10")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 5
        assert body["total_pages"] == 1
        # 按 event_type 过滤
        filtered = await c.get("/api/v1/monitor/operlog?event_type=login_failed")
        assert filtered.json()["total"] == 2
        # 按 result_status 过滤
        denied = await c.get("/api/v1/monitor/operlog?result_status=failure")
        assert denied.json()["total"] == 2


async def test_log_endpoints_page_capped_at_500() -> None:
    # 日志端点用 LogPageQ（le=500，比业务表 PageQ le=10000 更严）——OFFSET 深翻页在高增长 append-only
    # 日志表上代价高（PK 项3）。page=501 → 422（FastAPI 解析层拒）；page=500 仍在范围内 → 200。
    async with _client(_SuperProvider) as c:
        assert (await c.get("/api/v1/monitor/operlog?page=501")).status_code == 422
        assert (await c.get("/api/v1/monitor/logininfor?page=501")).status_code == 422
        assert (await c.get("/api/v1/monitor/operlog?page=500")).status_code == 200


async def test_operlog_detail_returns_full_payload() -> None:
    await _seed_audit(1)
    async with _client(_SuperProvider) as c:
        listed = (await c.get("/api/v1/monitor/operlog")).json()
        pk = listed["items"][0]["id"]
        detail = await c.get(f"/api/v1/monitor/operlog/{pk}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["payload"]["schema_version"] == "audit_event.v1"


async def test_operlog_detail_404() -> None:
    async with _client(_SuperProvider) as c:
        resp = await c.get("/api/v1/monitor/operlog/999999")
        assert resp.status_code == 404
        assert resp.json()["type"] == "monitor.AUDIT_EVENT_NOT_FOUND"


async def test_logininfor_list_filtered_by_status() -> None:
    await _seed_login(2, status="success")
    await _seed_login(3, status="failure")
    async with _client(_SuperProvider) as c:
        resp = await c.get("/api/v1/monitor/logininfor?status=failure")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 3
        assert (await c.get("/api/v1/monitor/logininfor")).json()["total"] == 5


async def test_monitor_requires_permission_403() -> None:
    await _seed_audit(1)
    async with _client(_NoLogPermProvider) as c:
        assert (await c.get("/api/v1/monitor/operlog")).status_code == 403
        assert (await c.get("/api/v1/monitor/logininfor")).status_code == 403
