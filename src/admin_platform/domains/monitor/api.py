"""监控日志 HTTP API（P2 Phase 4）—— /api/v1/monitor 下审计/登录日志只读查询。

对标 RuoYi 系统监控：操作日志（audit_events）+ 登录日志（login_logs）。只读（list + detail），
每端点 ``require_permission`` 守（默认 deny + 超管短路）。分层：api 只依赖 service（C2）。

错误路径在 ``responses=`` 声明（ADR §1）：401 未登录 / 403 缺权限 / 404 不存在。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.permissions import require_permission
from admin_platform.core.rbac_audit import audited_write
from admin_platform.domains.monitor.deps import get_monitor_service, get_system_monitor_service
from admin_platform.domains.monitor.schemas import (
    AuditEventDetail,
    AuditEventPage,
    CacheMetrics,
    LoginLogPage,
    LoginLogRead,
    OnlineSessionPage,
    ServerMetrics,
)
from admin_platform.domains.monitor.service import MonitorService, SystemMonitorService

router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])

ServiceDep = Annotated[MonitorService, Depends(get_monitor_service)]
SysMonServiceDep = Annotated[SystemMonitorService, Depends(get_system_monitor_service)]
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
# P4 服务/缓存监控守卫（只读单视图）。
ServerView = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_SERVER_LIST))]
CacheView = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_CACHE_LIST))]
# P4 在线用户守卫（查 + 强制下线）。
OnlineList = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ONLINE_LIST))]
OnlineRemove = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ONLINE_REMOVE))]

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


@router.get(
    "/server",
    operation_id="monitor_server_metrics",
    response_model=ServerMetrics,
    responses=AUTH_ERROR_RESPONSES,
)
async def get_server_metrics(svc: SysMonServiceDep, _user: ServerView) -> ServerMetrics:
    """服务监控：CPU / 内存 / 磁盘 / 进程实时指标（psutil 采集）。"""
    return await svc.get_server_metrics()


@router.get(
    "/cache",
    operation_id="monitor_cache_metrics",
    response_model=CacheMetrics,
    responses=AUTH_ERROR_RESPONSES,
)
async def get_cache_metrics(svc: SysMonServiceDep, _user: CacheView) -> CacheMetrics:
    """缓存监控：Redis INFO 摘要 + 命令统计。Redis 不可达时 available=False（不 500）。"""
    return await svc.get_cache_metrics()


@router.get(
    "/online",
    operation_id="monitor_online_list",
    response_model=OnlineSessionPage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_online_sessions(
    svc: ServiceDep, _user: OnlineList, page: PageQ = 1, size: SizeQ = 20
) -> OnlineSessionPage:
    """在线用户：当前活动会话（未撤销未过期的 refresh token family）分页。"""
    return await svc.list_online_sessions(page=page, size=size)


@router.delete(
    "/online/{session_id}",
    operation_id="monitor_online_force_logout",
    response_model=None,
    status_code=204,
    responses=GET_ERROR_RESPONSES,
)
async def force_logout(session_id: uuid.UUID, svc: ServiceDep, user: OnlineRemove) -> None:
    """强制下线：撤销指定会话 family。审计 rbac_write（目标= 会话 UUID + 用户名）。会话不存在 → 404。"""
    await audited_write(
        user,
        Permissions.SYSTEM_ONLINE_REMOVE,
        "online_session",
        coro=svc.force_logout(session_id),
        target_id=str(session_id),
        display=lambda username: username,
        success_status=204,
    )
