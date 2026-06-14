"""定时任务 HTTP API — /api/v1/monitor/jobs 下 CRUD + 手动触发 + 执行日志。

对标 RuoYi 定时任务（系统监控分组）。每端点 ``require_permission`` 守（默认 deny + 超管短路）；
写操作（create/update/delete/run）经 ``audited_write`` 织入 rbac_write 审计。安全：create/update
只接 handler_key + params（service 强校验命中 registry），无任意调用目标。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.core.pagination import PageQ, SizeQ
from admin_platform.core.permissions import require_permission
from admin_platform.core.rbac_audit import audited_write
from admin_platform.domains.scheduled_task.deps import get_scheduled_task_service
from admin_platform.domains.scheduled_task.schemas import (
    HandlerInfo,
    ScheduledTaskCreate,
    ScheduledTaskLogPage,
    ScheduledTaskLogRead,
    ScheduledTaskPage,
    ScheduledTaskRead,
    ScheduledTaskUpdate,
)
from admin_platform.domains.scheduled_task.service import ScheduledTaskService

router = APIRouter(prefix="/api/v1/monitor/jobs", tags=["scheduled_task"])

ServiceDep = Annotated[ScheduledTaskService, Depends(get_scheduled_task_service)]

JobList = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_JOB_LIST))]
JobQuery = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_JOB_QUERY))]
JobAdd = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_JOB_ADD))]
JobEdit = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_JOB_EDIT))]
JobRemove = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_JOB_REMOVE))]
JobRun = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_JOB_RUN))]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
WRITE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


# ---- 只读：handlers / logs（literal 路由须先于 /{task_id}）----


@router.get(
    "/handlers",
    operation_id="scheduled_task_handlers",
    response_model=list[HandlerInfo],
    responses=AUTH_ERROR_RESPONSES,
)
async def list_handlers(svc: ServiceDep, _user: JobList) -> list[HandlerInfo]:
    """可选 handler 列表（管理员只能从 registry 预注册项中选，非任意调用目标）。"""
    return svc.list_handlers()


@router.get(
    "/logs",
    operation_id="scheduled_task_logs",
    response_model=ScheduledTaskLogPage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_logs(
    svc: ServiceDep,
    _user: JobQuery,
    task_id: Annotated[int | None, Query(description="按任务ID过滤")] = None,
    log_status: Annotated[str | None, Query(alias="status", description="按状态过滤")] = None,
    page: PageQ = 1,
    size: SizeQ = 20,
) -> ScheduledTaskLogPage:
    return await svc.list_logs(task_id=task_id, status=log_status, page=page, size=size)


# ---- 任务 CRUD ----


@router.get(
    "",
    operation_id="scheduled_task_list",
    response_model=ScheduledTaskPage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_tasks(
    svc: ServiceDep,
    _user: JobList,
    task_status: Annotated[str | None, Query(alias="status", description="按状态过滤")] = None,
    handler_key: Annotated[str | None, Query(description="按处理器过滤")] = None,
    page: PageQ = 1,
    size: SizeQ = 20,
) -> ScheduledTaskPage:
    return await svc.list_tasks(status=task_status, handler_key=handler_key, page=page, size=size)


@router.get(
    "/{task_id}",
    operation_id="scheduled_task_get",
    response_model=ScheduledTaskRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_task(task_id: int, svc: ServiceDep, _user: JobQuery) -> ScheduledTaskRead:
    return await svc.get_task(task_id)


@router.post(
    "",
    operation_id="scheduled_task_create",
    response_model=ScheduledTaskRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERROR_RESPONSES,
)
@idempotent
async def create_task(
    payload: ScheduledTaskCreate, svc: ServiceDep, user: JobAdd
) -> ScheduledTaskRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_JOB_ADD,
        "scheduled_task",
        coro=svc.create(payload),
        display=lambda t: t.name,
        success_status=201,
    )


@router.patch(
    "/{task_id}",
    operation_id="scheduled_task_update",
    response_model=ScheduledTaskRead,
    responses=WRITE_ERROR_RESPONSES,
)
async def update_task(
    task_id: int, payload: ScheduledTaskUpdate, svc: ServiceDep, user: JobEdit
) -> ScheduledTaskRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_JOB_EDIT,
        "scheduled_task",
        coro=svc.update(task_id, payload),
        target_id=task_id,
        display=lambda t: t.name,
    )


@router.delete(
    "/{task_id}",
    operation_id="scheduled_task_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=GET_ERROR_RESPONSES,
)
async def delete_task(task_id: int, svc: ServiceDep, user: JobRemove) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_JOB_REMOVE,
        "scheduled_task",
        coro=svc.delete(task_id),
        target_id=task_id,
        success_status=204,
    )


@router.post(
    "/{task_id}/run",
    operation_id="scheduled_task_run",
    response_model=ScheduledTaskLogRead,
    responses=WRITE_ERROR_RESPONSES,
)
async def run_task(task_id: int, svc: ServiceDep, user: JobRun) -> ScheduledTaskLogRead:
    """手动触发一次（同步执行 handler 后返回执行日志）。审计 rbac_write。"""
    return await audited_write(
        user,
        Permissions.SYSTEM_JOB_RUN,
        "scheduled_task",
        coro=svc.manual_run(task_id, actor_user_id=int(user.user_id)),
        target_id=task_id,
        display=lambda log: log.status,
    )
