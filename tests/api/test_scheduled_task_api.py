"""/api/v1/monitor/jobs 的 API 测试 —— 权限守卫 + schema 校验（DB-free）。

定时任务 CRUD + 手动触发。守卫矩阵（401/403/超管短路）+ 路径/body 校验在 DB 依赖前短路，
无需真 DB（stub service 喂 canned）。完整 CRUD/执行/claim 放 tests/integration/。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.domains.scheduled_task.api import router
from admin_platform.domains.scheduled_task.deps import get_scheduled_task_service
from admin_platform.domains.scheduled_task.schemas import (
    HandlerInfo,
    ScheduledTaskLogPage,
    ScheduledTaskLogRead,
    ScheduledTaskPage,
    ScheduledTaskRead,
)
from tests.api._support import override_get_session

BASE = "/api/v1/monitor/jobs"
_VALID = {"name": "j1", "handler_key": "noop", "cron_expression": "0 2 * * *"}


def _canned_task() -> ScheduledTaskRead:
    now = datetime.now(UTC)
    return ScheduledTaskRead(
        id=1,
        name="j1",
        handler_key="noop",
        params_json={},
        cron_expression="0 2 * * *",
        cron_timezone="Asia/Shanghai",
        status="disabled",
        allow_concurrent=False,
        misfire_grace_seconds=300,
        timeout_seconds=None,
        last_run_at=None,
        last_status=None,
        remark=None,
        created_at=now,
        updated_at=now,
    )


def _canned_log() -> ScheduledTaskLogRead:
    now = datetime.now(UTC)
    return ScheduledTaskLogRead(
        id=1,
        task_id=1,
        execution_id=uuid.uuid4(),
        trigger_type="manual",
        scheduled_at=None,
        handler_key="noop",
        params_json={},
        status="success",
        started_at=now,
        finished_at=now,
        duration_ms=1,
        error_code=None,
        error_message=None,
        result_summary="ok",
        worker_id="w",
        actor_user_id=1,
        created_at=now,
    )


class _StubService:
    async def list_tasks(self, **kw: Any) -> ScheduledTaskPage:
        return ScheduledTaskPage(items=[_canned_task()], page=1, size=20, total=1, total_pages=1)

    async def get_task(self, task_id: int) -> ScheduledTaskRead:
        return _canned_task()

    async def create(self, payload: Any) -> ScheduledTaskRead:
        return _canned_task()

    async def update(self, task_id: int, payload: Any) -> ScheduledTaskRead:
        return _canned_task()

    async def delete(self, task_id: int) -> None:
        return None

    async def list_logs(self, **kw: Any) -> ScheduledTaskLogPage:
        return ScheduledTaskLogPage(items=[_canned_log()], page=1, size=20, total=1, total_pages=1)

    async def manual_run(self, task_id: int, *, actor_user_id: int | None) -> ScheduledTaskLogRead:
        return _canned_log()

    def list_handlers(self) -> list[HandlerInfo]:
        return [HandlerInfo(key="noop", display_name="noop", allow_manual=True)]


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
    app.dependency_overrides[get_scheduled_task_service] = _StubService
    if current_user is not None:
        app.dependency_overrides[require_current_user] = lambda: current_user
    if provider is not None:
        app.dependency_overrides[get_permission_provider] = lambda: provider
    return TestClient(app)


def _super() -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="1", sub="1"), provider=_StubProvider(is_super=True)
    )


def _perm(*perms: str) -> TestClient:
    return _client(
        current_user=CurrentUser(user_id="2", sub="2"),
        provider=_StubProvider(is_super=False, perms=frozenset(perms)),
    )


# ---- 401 未登录 ----


def test_list_without_auth_401() -> None:
    assert _client(current_user=None, provider=None).get(BASE).status_code == 401


def test_create_without_auth_401() -> None:
    assert _client(current_user=None, provider=None).post(BASE, json=_VALID).status_code == 401


def test_run_without_auth_401() -> None:
    assert _client(current_user=None, provider=None).post(f"{BASE}/1/run").status_code == 401


# ---- 403 缺权限矩阵 ----


def test_list_without_perm_403() -> None:
    res = _perm().get(BASE)
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"


def test_get_without_perm_403() -> None:
    assert _perm().get(f"{BASE}/1").status_code == 403


def test_create_without_perm_403() -> None:
    assert _perm().post(BASE, json=_VALID).status_code == 403


def test_update_without_perm_403() -> None:
    assert _perm().patch(f"{BASE}/1", json={"remark": "x"}).status_code == 403


def test_delete_without_perm_403() -> None:
    assert _perm().delete(f"{BASE}/1").status_code == 403


def test_run_without_perm_403() -> None:
    assert _perm().post(f"{BASE}/1/run").status_code == 403


def test_list_perm_does_not_grant_add() -> None:
    client = _perm("system:job:list")
    assert client.get(BASE).status_code == 200
    assert client.post(BASE, json=_VALID).status_code == 403


def test_run_perm_isolated() -> None:
    client = _perm("system:job:run")
    assert client.post(f"{BASE}/1/run").status_code == 200
    assert client.get(BASE).status_code == 403


# ---- 200 超管短路（stub service）----


def test_list_super_200() -> None:
    body = _super().get(BASE).json()
    assert body["total"] == 1
    assert body["items"][0]["handler_key"] == "noop"


def test_handlers_super_200() -> None:
    body = _super().get(f"{BASE}/handlers").json()
    assert body[0]["key"] == "noop"


def test_logs_super_200() -> None:
    body = _super().get(f"{BASE}/logs").json()
    assert body["items"][0]["status"] == "success"


def test_create_super_201() -> None:
    res = _super().post(BASE, json=_VALID)
    assert res.status_code == 201
    assert res.json()["name"] == "j1"


def test_run_super_200() -> None:
    res = _super().post(f"{BASE}/1/run")
    assert res.status_code == 200
    assert res.json()["status"] == "success"


# ---- 422 body 校验（超管越过守卫后触发）----


def test_create_missing_fields_422() -> None:
    assert _super().post(BASE, json={}).status_code == 422


def test_create_invalid_status_422() -> None:
    assert _super().post(BASE, json={**_VALID, "status": "bogus"}).status_code == 422


def test_create_negative_misfire_422() -> None:
    assert _super().post(BASE, json={**_VALID, "misfire_grace_seconds": -1}).status_code == 422


def test_list_size_above_max_422() -> None:
    assert _super().get(f"{BASE}?size=101").status_code == 422


# ---- canonical 分页请求形状回归（锁住 ?page=&size=&<filter> → 200，防混用 422 反模式复发）----


def test_list_tasks_canonical_page_size_filter_200() -> None:
    # page/size + 合法 filter（status / handler_key）同传 → 200。
    res = _super().get(f"{BASE}?page=1&size=10&status=active&handler_key=noop")
    assert res.status_code == 200


def test_list_logs_canonical_page_size_filter_200() -> None:
    res = _super().get(f"{BASE}/logs?page=1&size=10&task_id=1&status=success")
    assert res.status_code == 200
