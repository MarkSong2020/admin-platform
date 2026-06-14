"""定时任务 CRUD + 手动触发集成测试（P4c）—— 真 DB + 真 executor（noop handler）。

覆盖：CRUD 往返 / 名唯一 409 / registry·cron·params 校验 422 / 手动触发真执行（success 日志）/
执行日志查询 / 删任务后日志 FK SET NULL 存活 / 写操作审计 rbac_write。需 DB。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.scheduled_task.api import router as job_router
from admin_platform.domains.scheduled_task.models import ScheduledTaskLog

pytestmark = pytest.mark.integration

BASE = "/api/v1/monitor/jobs"
_VALID = {"name": "cleanup", "handler_key": "noop", "cron_expression": "0 2 * * *"}


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


async def _wipe() -> None:
    async with db_session() as s:
        await s.execute(
            text("TRUNCATE TABLE scheduled_task_logs, scheduled_tasks, audit_events CASCADE")
        )


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client() -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(job_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = _SuperProvider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_crud_roundtrip() -> None:
    async with _client() as c:
        created = await c.post(BASE, json={**_VALID, "status": "enabled"})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert created.json()["next_run_at"] is not None  # enabled → 算下次触发

        got = await c.get(f"{BASE}/{task_id}")
        assert got.status_code == 200
        assert got.json()["handler_key"] == "noop"

        listed = await c.get(BASE)
        assert listed.json()["total"] == 1

        patched = await c.patch(f"{BASE}/{task_id}", json={"cron_expression": "*/5 * * * *"})
        assert patched.status_code == 200
        assert patched.json()["cron_expression"] == "*/5 * * * *"

        assert (await c.delete(f"{BASE}/{task_id}")).status_code == 204
        assert (await c.get(f"{BASE}/{task_id}")).status_code == 404


async def test_update_clears_nullable_field_via_explicit_null() -> None:
    # PATCH 显式传 null 清空 nullable 列（timeout_seconds / remark）并真持久化到 DB——守 service
    # 用 model_fields_set 而非 is not None（后者吞显式 null，旧值残留，运维以为取消 timeout 实际没取消）。
    async with _client() as c:
        created = await c.post(BASE, json={**_VALID, "timeout_seconds": 30, "remark": "x"})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert created.json()["timeout_seconds"] == 30
        assert created.json()["remark"] == "x"

        patched = await c.patch(f"{BASE}/{task_id}", json={"timeout_seconds": None, "remark": None})
        assert patched.status_code == 200, patched.text
        assert patched.json()["timeout_seconds"] is None
        assert patched.json()["remark"] is None

        # GET 复核真持久化（不止响应回显）
        got = await c.get(f"{BASE}/{task_id}")
        assert got.json()["timeout_seconds"] is None
        assert got.json()["remark"] is None


async def test_name_unique_409() -> None:
    async with _client() as c:
        assert (await c.post(BASE, json=_VALID)).status_code == 201
        dup = await c.post(BASE, json=_VALID)
        assert dup.status_code == 409


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"handler_key": "ghost"}, "scheduled_task.HANDLER_UNKNOWN"),
        ({"cron_expression": "bogus"}, "scheduled_task.CRON_INVALID"),
        ({"handler_key": "echo", "params": {}}, "scheduled_task.PARAMS_INVALID"),
    ],
)
async def test_create_validation_422(patch: dict, code: str) -> None:
    async with _client() as c:
        res = await c.post(BASE, json={**_VALID, **patch})
        assert res.status_code == 422, res.text
        assert res.json()["type"] == code


async def test_manual_run_executes_noop() -> None:
    async with _client() as c:
        task_id = (await c.post(BASE, json=_VALID)).json()["id"]
        run = await c.post(f"{BASE}/{task_id}/run")
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["trigger_type"] == "manual"
        assert body["status"] == "success"
        assert body["result_summary"] == "ok"  # noop 返回 "ok"
        assert body["duration_ms"] is not None
        # 执行日志可查
        logs = await c.get(f"{BASE}/logs?task_id={task_id}")
        assert logs.json()["total"] == 1


async def test_manual_run_cleanup_handler() -> None:
    """真实维护 handler：清理过期 refresh token（空库返回 deleted 0）。"""
    async with _client() as c:
        task_id = (
            await c.post(
                BASE,
                json={
                    "name": "cleanup-rt",
                    "handler_key": "cleanup_expired_refresh_tokens",
                    "cron_expression": "0 3 * * *",
                },
            )
        ).json()["id"]
        run = await c.post(f"{BASE}/{task_id}/run")
        assert run.status_code == 200
        assert "expired refresh tokens" in run.json()["result_summary"]


async def test_delete_task_keeps_logs_via_set_null() -> None:
    async with _client() as c:
        task_id = (await c.post(BASE, json=_VALID)).json()["id"]
        await c.post(f"{BASE}/{task_id}/run")
        assert (await c.delete(f"{BASE}/{task_id}")).status_code == 204
    # 日志存活，task_id 置空（FK SET NULL）。
    async with db_session() as s:
        rows = (await s.execute(select(ScheduledTaskLog.task_id))).all()
        assert len(rows) == 1
        assert rows[0][0] is None


# ---- 审计织入 ----


def _rbac_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    out: list[dict] = []
    for record in caplog.records:
        event = getattr(record, "audit_event", None)
        if event and event.get("event_type") == "rbac_write":
            out.append(event)
    return out


async def test_create_and_run_emit_audit(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        async with _client() as c:
            task_id = (await c.post(BASE, json=_VALID)).json()["id"]
            await c.post(f"{BASE}/{task_id}/run")
    actions = [e["action"] for e in _rbac_events(caplog) if e["result"]["status"] == "success"]
    assert "system:job:add" in actions
    assert "system:job:run" in actions
