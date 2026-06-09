"""审计持久化集成测试（P2 Phase 2）——落 audit_events 表 + 事务边界不变式 + 请求段端到端。

验证 Claude×Codex PK 收敛的写入路径：
  * 成功 rbac_write 落库，且 request 段（IP/UA/path）经中间件 ContextVar **端到端**灌入
    —— 同时验证 contextvar 从 BaseHTTPMiddleware **下行传播**到 service 层 emit 点。
  * 失败审计在业务 **ROLLBACK** 后仍独立落库（不被回滚牵连，P1.5「revoke 被回滚」同类陷阱）。
  * permission_denied 在【同步】依赖里 emit（FastAPI 线程池）→ 验证 buffer 经 anyio context
    复制 + 共享 list mutation 仍命中（同步依赖路径不丢审计）。需 DB。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from admin_platform.audit.emit import build_audit_event
from admin_platform.audit.events import AuditEvent, AuditResult
from admin_platform.audit.models import AuditEventLog
from admin_platform.audit.sink import DbAuditSink, configure_audit_sink, persist_audit_in_session
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.role.api import router as role_router

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


class _DenyProvider(PermissionProvider):
    """active 但非超管、无权限 → require_permission 403 FORBIDDEN_BY_ROLE → permission_denied。"""

    def get_is_active(self, user_id: int) -> bool:
        return True

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE roles CASCADE"))
        await session.execute(text("TRUNCATE TABLE audit_events CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_and_sink() -> AsyncIterator[None]:
    await _wipe()
    # lifespan 不在 ASGITransport 下跑，显式注册 sink（生产由 main lifespan 注册）。
    configure_audit_sink(DbAuditSink())
    yield
    configure_audit_sink(None)
    await _wipe()
    await dispose_engine()


async def _audit_rows(event_type: str) -> list[AuditEventLog]:
    async with db_session() as session:
        stmt = (
            select(AuditEventLog)
            .where(AuditEventLog.event_type == event_type)
            .order_by(AuditEventLog.id)
        )
        return list((await session.execute(stmt)).scalars().all())


async def _role_count() -> int:
    async with db_session() as session:
        return (await session.execute(text("SELECT count(*) FROM roles"))).scalar_one()


def _client(provider: type[PermissionProvider]) -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(role_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_rbac_write_success_persisted_with_request_context() -> None:
    async with _client(_SuperProvider) as c:
        created = await c.post(
            "/api/v1/roles",
            json={"name": "r1", "code": "r1"},
            headers={"User-Agent": "pytest-agent"},
        )
        assert created.status_code == 201, created.text

    rows = await _audit_rows("rbac_write")
    assert len(rows) == 1
    row = rows[0]
    assert row.result_status == "success"
    assert row.action == "system:role:add"
    # 端到端：request 段经中间件 ContextVar 下行灌入（service 层拿不到 Request）。
    assert row.path == "/api/v1/roles"
    assert row.method == "POST"
    assert row.user_agent == "pytest-agent"
    assert row.ip is not None
    # payload 存完整 envelope（无损取证）。
    assert row.payload["schema_version"] == "audit_event.v1"
    assert row.payload["result"]["status"] == "success"


async def test_rbac_write_failure_persisted_after_business_rollback() -> None:
    # 第二条撞 code uq → service 抛 AppError(409) → 业务 ROLLBACK；失败审计须独立落库。
    async with _client(_SuperProvider) as c:
        assert (
            await c.post("/api/v1/roles", json={"name": "dup", "code": "dup"})
        ).status_code == 201
        res = await c.post("/api/v1/roles", json={"name": "dup2", "code": "dup"})
        assert res.status_code == 409

    failures = [r for r in await _audit_rows("rbac_write") if r.result_status == "failure"]
    assert len(failures) == 1
    assert failures[0].action == "system:role:add"
    assert failures[0].result_error_code == "role.CODE_DUPLICATE"
    assert failures[0].result_http_status == 409
    # 业务确实回滚：只有第一个 role 落库（失败审计不牵连业务、业务回滚不吞审计）。
    assert await _role_count() == 1


async def test_permission_denied_persisted_from_sync_dependency() -> None:
    # permission_denied 在【同步】require_permission._dep 里 emit（FastAPI 线程池）——
    # 验证 buffer 经 anyio context 复制 + 共享 list mutation 仍命中，审计不丢。
    async with _client(_DenyProvider) as c:
        res = await c.post("/api/v1/roles", json={"name": "x", "code": "x"})
        assert res.status_code == 403, res.text

    denied = await _audit_rows("permission_denied")
    assert len(denied) == 1
    assert denied[0].result_status == "denied"
    assert denied[0].result_http_status == 403
    # 同步线程池依赖里 build_audit_event 也读到了 request 段（context 复制进线程）。
    assert denied[0].path == "/api/v1/roles"


async def test_oversized_user_agent_does_not_lose_audit() -> None:
    # review F3：超长 UA（攻击者可控）会让 VARCHAR(512) insert 抛 StringDataRightTruncation，
    # 连累整批 add_all 失败 → 审计静默丢失。截断防御：拆查询列截断、payload(JSONB) 留完整原值。
    async with _client(_SuperProvider) as c:
        created = await c.post(
            "/api/v1/roles",
            json={"name": "ua", "code": "ua"},
            headers={"User-Agent": "X" * 5000},
        )
        assert created.status_code == 201, created.text

    rows = await _audit_rows("rbac_write")
    assert len(rows) == 1  # 审计未因超长 UA 丢失
    assert rows[0].user_agent is not None
    assert len(rows[0].user_agent) == 512  # 查询列截断到列宽
    # 完整原值仍在 payload（无损取证，JSONB 无长度限制）。
    assert len(rows[0].payload["request"]["user_agent"]) == 5000


async def _audit_by_event_id(event_id: str) -> list[AuditEventLog]:
    async with db_session() as session:
        stmt = select(AuditEventLog).where(AuditEventLog.event_id == event_id)
        return list((await session.execute(stmt)).scalars().all())


def _success_event() -> AuditEvent:
    return build_audit_event(
        event_type="rbac_write",
        action="system:role:add",
        title="审计原子性",
        result=AuditResult(status="success", http_status=201),
    )


async def test_success_audit_rolls_back_with_business_transaction() -> None:
    # review F1 方案 B 核心不变式：成功审计经 SAVEPOINT 写在业务事务内 → 业务 ROLLBACK 时
    # 审计**一同回滚**，不留假成功审计（commit 失败/业务回滚不产生「业务没生效却记 success」）。
    event = _success_event()
    try:
        async with db_session() as session:
            await persist_audit_in_session(session, event)
            raise RuntimeError("强制外层事务回滚")
    except RuntimeError:
        pass
    assert await _audit_by_event_id(event.event_id) == []


async def test_success_audit_commits_with_business_transaction() -> None:
    # 正向对照：业务事务正常提交 → 同事务内的成功审计随之落库（原子提交）。
    event = _success_event()
    async with db_session() as session:
        await persist_audit_in_session(session, event)
    rows = await _audit_by_event_id(event.event_id)
    assert len(rows) == 1
    assert rows[0].result_status == "success"
