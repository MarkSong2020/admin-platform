"""监控日志 HTTP API（P2 Phase 4）—— /api/v1/monitor 下审计/登录日志只读查询。

对标 RuoYi 系统监控：操作日志（audit_events）+ 登录日志（login_logs）。只读（list + detail），
每端点 ``require_permission`` 守（默认 deny + 超管短路）。分层：api 只依赖 service（C2）。

错误路径在 ``responses=`` 声明（ADR §1）：401 未登录 / 403 缺权限 / 404 不存在。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.permissions import require_permission
from admin_platform.domains.monitor.deps import get_monitor_service
from admin_platform.domains.monitor.schemas import (
    AuditEventDetail,
    AuditEventPage,
    LoginLogPage,
    LoginLogRead,
)
from admin_platform.domains.monitor.service import MonitorService

router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])

ServiceDep = Annotated[MonitorService, Depends(get_monitor_service)]
# page 上限防深分页 DoS（review O1：审计表 append-only 持续增长，大 offset 扫描+count 成本随表涨）。
PageQ = Annotated[int, Query(ge=1, le=10000, description="页码（从 1 开始，上限 10000）")]
SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]

# 权限守卫（默认 deny + 超管短路）。只读日志：list + query（detail）。
OperLogList = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_OPERLOG_LIST))]
OperLogQuery = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_OPERLOG_QUERY))]
LoginInfoList = Annotated[
    CurrentUser, Depends(require_permission(Permissions.SYSTEM_LOGININFOR_LIST))
]
LoginInfoQuery = Annotated[
    CurrentUser, Depends(require_permission(Permissions.SYSTEM_LOGININFOR_QUERY))
]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}


@router.get(
    "/operlog",
    operation_id="monitor_operlog_list",
    response_model=AuditEventPage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_operlog(  # noqa: PLR0913 —— FastAPI 注入的查询过滤参数，端点签名可放宽
    svc: ServiceDep,
    _user: OperLogList,
    event_type: Annotated[str | None, Query(description="按事件类型过滤")] = None,
    actor_user_id: Annotated[int | None, Query(description="按操作者用户ID过滤")] = None,
    result_status: Annotated[
        str | None, Query(description="按结果过滤(success/failure/denied)")
    ] = None,
    page: PageQ = 1,
    size: SizeQ = 20,
) -> AuditEventPage:
    return await svc.list_audit_events(
        event_type=event_type,
        actor_user_id=actor_user_id,
        result_status=result_status,
        page=page,
        size=size,
    )


@router.get(
    "/operlog/{event_pk}",
    operation_id="monitor_operlog_get",
    response_model=AuditEventDetail,
    responses=GET_ERROR_RESPONSES,
)
async def get_operlog(event_pk: int, svc: ServiceDep, _user: OperLogQuery) -> AuditEventDetail:
    return await svc.get_audit_event(event_pk)


@router.get(
    "/logininfor",
    operation_id="monitor_logininfor_list",
    response_model=LoginLogPage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_logininfor(
    svc: ServiceDep,
    _user: LoginInfoList,
    username: Annotated[str | None, Query(description="按用户名过滤")] = None,
    status: Annotated[str | None, Query(description="按状态过滤")] = None,
    page: PageQ = 1,
    size: SizeQ = 20,
) -> LoginLogPage:
    return await svc.list_login_logs(username=username, status=status, page=page, size=size)


@router.get(
    "/logininfor/{log_pk}",
    operation_id="monitor_logininfor_get",
    response_model=LoginLogRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_logininfor(log_pk: int, svc: ServiceDep, _user: LoginInfoQuery) -> LoginLogRead:
    return await svc.get_login_log(log_pk)
