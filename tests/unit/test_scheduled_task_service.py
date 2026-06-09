"""定时任务 service 单测（P4c，DB-free）—— CRUD 校验分支 + 手动触发分支。

fake repo（内存）+ 自建 registry（可控 allow_manual）+ stub executor。测真实 service 行为：
registry/cron/params 强校验、名唯一、handler 下线/不可手动的 409、手动触发回读。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from admin_platform.core.errors import AppError
from admin_platform.domains.scheduled_task.executor import ExecutionOutcome, TaskExecutor
from admin_platform.domains.scheduled_task.models import ScheduledTask, ScheduledTaskLog
from admin_platform.domains.scheduled_task.registry import HandlerSpec, JobHandlerRegistry
from admin_platform.domains.scheduled_task.schemas import ScheduledTaskCreate, ScheduledTaskUpdate
from admin_platform.domains.scheduled_task.service import ScheduledTaskService

pytestmark = pytest.mark.anyio


class _EchoParams(BaseModel):
    message: str


async def _noop(params: dict[str, Any]) -> str | None:
    return "ok"


def _registry() -> JobHandlerRegistry:
    reg = JobHandlerRegistry()
    reg.register(HandlerSpec("noop", "noop", _noop))
    reg.register(HandlerSpec("echo", "echo", _noop, params_schema=_EchoParams))
    reg.register(HandlerSpec("auto_only", "auto", _noop, allow_manual=False))
    return reg


class _FakeRepo:
    def __init__(self) -> None:
        self.tasks: dict[int, ScheduledTask] = {}
        self.logs: dict[int, ScheduledTaskLog] = {}
        self._seq = 0

    def seed_task(self, **kw: Any) -> ScheduledTask:
        self._seq += 1
        now = datetime.now(UTC)
        defaults: dict[str, Any] = {
            "name": f"t{self._seq}",
            "handler_key": "noop",
            "params_json": {},
            "cron_expression": "0 2 * * *",
            "cron_timezone": "Asia/Shanghai",
            "status": "disabled",
            "allow_concurrent": False,
            "misfire_grace_seconds": 300,
            "timeout_seconds": None,
            "last_run_at": None,
            "last_status": None,
            "remark": None,
        }
        defaults.update(kw)
        task = ScheduledTask(**defaults)
        task.id = self._seq
        task.created_at = now
        task.updated_at = now
        self.tasks[task.id] = task
        return task

    async def get(self, task_id: int) -> ScheduledTask | None:
        return self.tasks.get(task_id)

    async def refresh(self, task: ScheduledTask) -> None:  # fake：内存对象无需 reload
        return None

    async def get_by_name(self, name: str) -> ScheduledTask | None:
        return next((t for t in self.tasks.values() if t.name == name), None)

    async def list(
        self, *, status: str | None, handler_key: str | None, page: int, size: int
    ) -> list[ScheduledTask]:
        rows = [
            t
            for t in self.tasks.values()
            if (status is None or t.status == status)
            and (handler_key is None or t.handler_key == handler_key)
        ]
        return rows[(page - 1) * size : (page - 1) * size + size]

    async def count(self, *, status: str | None, handler_key: str | None) -> int:
        return len(
            [
                t
                for t in self.tasks.values()
                if (status is None or t.status == status)
                and (handler_key is None or t.handler_key == handler_key)
            ]
        )

    async def create(self, task: ScheduledTask) -> ScheduledTask:
        if task.id is None:
            self._seq += 1
            task.id = self._seq
            now = datetime.now(UTC)
            task.created_at = now
            task.updated_at = now
        self.tasks[task.id] = task
        return task

    async def delete(self, task: ScheduledTask) -> None:
        self.tasks.pop(task.id, None)

    async def get_log(self, log_id: int) -> ScheduledTaskLog | None:
        return self.logs.get(log_id)


class _StubExecutor(TaskExecutor):
    def __init__(self, registry: JobHandlerRegistry, repo: _FakeRepo) -> None:
        super().__init__(registry)
        self._repo = repo

    async def run(  # type: ignore[override]
        self, task_id: int, *, trigger_type: str, scheduled_at: object, actor_user_id: int | None
    ) -> ExecutionOutcome:
        log = ScheduledTaskLog(
            task_id=task_id,
            execution_id=uuid.uuid4(),
            trigger_type=trigger_type,
            scheduled_at=None,
            handler_key="noop",
            params_json={},
            status="success",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            actor_user_id=actor_user_id,
        )
        log.id = 1
        log.created_at = datetime.now(UTC)
        self._repo.logs[1] = log
        return ExecutionOutcome(execution_id=log.execution_id, status="success", log_id=1)


def _service(repo: _FakeRepo) -> ScheduledTaskService:
    reg = _registry()
    return ScheduledTaskService(repo, reg, _StubExecutor(reg, repo))  # type: ignore[arg-type]


def _create(**kw: Any) -> ScheduledTaskCreate:
    base: dict[str, Any] = {"name": "job", "handler_key": "noop", "cron_expression": "0 2 * * *"}
    base.update(kw)
    return ScheduledTaskCreate(**base)


# ---- create 校验 ----


async def test_create_unknown_handler_422() -> None:
    svc = _service(_FakeRepo())
    with pytest.raises(AppError) as e:
        await svc.create(_create(handler_key="ghost"))
    assert e.value.code == "scheduled_task.HANDLER_UNKNOWN"
    assert e.value.status_code == 422


async def test_create_invalid_params_422() -> None:
    svc = _service(_FakeRepo())
    with pytest.raises(AppError) as e:
        await svc.create(_create(handler_key="echo", params={"wrong": 1}))
    assert e.value.code == "scheduled_task.PARAMS_INVALID"


async def test_create_invalid_cron_422() -> None:
    svc = _service(_FakeRepo())
    with pytest.raises(AppError) as e:
        await svc.create(_create(cron_expression="bogus"))
    assert e.value.code == "scheduled_task.CRON_INVALID"


async def test_create_duplicate_name_409() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="dup")
    svc = _service(repo)
    with pytest.raises(AppError) as e:
        await svc.create(_create(name="dup"))
    assert e.value.status_code == 409


async def test_create_success() -> None:
    svc = _service(_FakeRepo())
    read = await svc.create(_create(name="ok", handler_key="echo", params={"message": "hi"}))
    assert read.name == "ok"
    assert read.handler_key == "echo"
    assert read.params_json == {"message": "hi"}
    assert read.next_run_at is None  # disabled 默认不算 next_run


# ---- get / update / delete ----


async def test_get_task_404() -> None:
    with pytest.raises(AppError) as e:
        await _service(_FakeRepo()).get_task(999)
    assert e.value.status_code == 404


async def test_update_not_found_404() -> None:
    with pytest.raises(AppError) as e:
        await _service(_FakeRepo()).update(999, ScheduledTaskUpdate(remark="x"))
    assert e.value.status_code == 404


async def test_update_change_handler_revalidates_params() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="j", handler_key="noop", params_json={})
    svc = _service(repo)
    # 切到 echo 但没给 message → params 重校验失败 422。
    with pytest.raises(AppError) as e:
        await svc.update(1, ScheduledTaskUpdate(handler_key="echo"))
    assert e.value.code == "scheduled_task.PARAMS_INVALID"


async def test_update_name_conflict_409() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="a")
    repo.seed_task(name="b")
    svc = _service(repo)
    with pytest.raises(AppError) as e:
        await svc.update(1, ScheduledTaskUpdate(name="b"))
    assert e.value.status_code == 409


async def test_delete_not_found_404() -> None:
    with pytest.raises(AppError) as e:
        await _service(_FakeRepo()).delete(999)
    assert e.value.status_code == 404


# ---- 手动触发 ----


async def test_manual_run_not_found_404() -> None:
    with pytest.raises(AppError) as e:
        await _service(_FakeRepo()).manual_run(999, actor_user_id=1)
    assert e.value.status_code == 404


async def test_manual_run_handler_offline_409() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="j", handler_key="ghost")  # registry 无此 handler
    svc = _service(repo)
    with pytest.raises(AppError) as e:
        await svc.manual_run(1, actor_user_id=1)
    assert e.value.code == "scheduled_task.HANDLER_UNKNOWN"
    assert e.value.status_code == 409


async def test_manual_run_not_allowed_409() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="j", handler_key="auto_only")  # allow_manual=False
    svc = _service(repo)
    with pytest.raises(AppError) as e:
        await svc.manual_run(1, actor_user_id=1)
    assert e.value.code == "scheduled_task.MANUAL_NOT_ALLOWED"


async def test_manual_run_success_returns_log() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="j", handler_key="noop")
    svc = _service(repo)
    log = await svc.manual_run(1, actor_user_id=7)
    assert log.status == "success"
    assert log.trigger_type == "manual"
    assert log.actor_user_id == 7


class _NoneExecutor(TaskExecutor):
    async def run(self, task_id, *, trigger_type, scheduled_at, actor_user_id):  # type: ignore[override]
        return None  # 真实 executor 在 task 被删 / claim 被抢占时返回 None


async def test_manual_run_outcome_none_409() -> None:
    """executor 返回 None（task 调度后消失 / claim 抢占）→ 409，不 500。"""
    repo = _FakeRepo()
    repo.seed_task(name="j", handler_key="noop")
    reg = _registry()
    svc = ScheduledTaskService(repo, reg, _NoneExecutor(reg))  # type: ignore[arg-type]
    with pytest.raises(AppError) as e:
        await svc.manual_run(1, actor_user_id=1)
    assert e.value.status_code == 409


async def test_create_enabled_computes_next_run() -> None:
    svc = _service(_FakeRepo())
    read = await svc.create(_create(name="en", cron_expression="*/5 * * * *", status="enabled"))
    assert read.status == "enabled"
    assert read.next_run_at is not None  # enabled → _to_read 算下次触发


async def test_update_applies_all_fields() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="j", handler_key="noop")
    svc = _service(repo)
    read = await svc.update(
        1,
        ScheduledTaskUpdate(
            name="j2",
            cron_expression="*/10 * * * *",
            cron_timezone="UTC",
            status="enabled",
            allow_concurrent=True,
            misfire_grace_seconds=60,
            timeout_seconds=30,
            remark="r",
        ),
    )
    assert read.name == "j2"
    assert read.cron_expression == "*/10 * * * *"
    assert read.cron_timezone == "UTC"
    assert read.status == "enabled"
    assert read.allow_concurrent is True
    assert read.misfire_grace_seconds == 60
    assert read.timeout_seconds == 30
    assert read.remark == "r"


async def test_list_tasks_maps_and_paginates() -> None:
    repo = _FakeRepo()
    repo.seed_task(name="a")
    repo.seed_task(name="b")
    svc = _service(repo)
    page = await svc.list_tasks(status=None, handler_key=None, page=1, size=20)
    assert page.total == 2
    assert {t.name for t in page.items} == {"a", "b"}


async def test_list_handlers() -> None:
    handlers = {h.key: h for h in _service(_FakeRepo()).list_handlers()}
    assert handlers["auto_only"].allow_manual is False
    assert handlers["noop"].allow_manual is True
