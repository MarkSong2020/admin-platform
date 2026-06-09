"""监控日志查询 DTO（P2 §6 / Phase 4）—— audit_events（操作日志）+ login_logs（登录日志）。

只读视图：list 用 summary 列（不含完整 envelope payload，避免响应膨胀）；detail 额外带 ``payload``
（完整 envelope，无损取证）+ request 段。分页 envelope 对齐 ADR 0001 §7.5（RolePage 同款）。

C5/C6 分层：schemas 不 import models / sqlalchemy（纯 Pydantic DTO，from_attributes 读 ORM 属性）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    """审计/操作日志列表项（summary，不含完整 payload）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    event_type: str
    action: str
    title: str
    occurred_at: datetime
    actor_user_id: int | None
    actor_username: str | None
    actor_is_super_admin: bool
    target_type: str | None
    target_id: str | None
    target_display: str | None
    ip: str | None
    method: str | None
    path: str | None
    result_status: str
    result_http_status: int | None
    result_error_code: str | None
    duration_ms: int | None
    risk_level: str
    redaction_applied: bool
    created_at: datetime


class AuditEventDetail(AuditEventRead):
    """审计事件详情：summary + 完整 envelope payload + request 关联段。"""

    request_id: str | None
    trace_id: str | None
    user_agent: str | None
    payload: dict[str, Any]


class AuditEventPage(BaseModel):
    """审计日志分页 envelope（ADR 0001 §7.5）。"""

    items: list[AuditEventRead]
    page: int
    size: int
    total: int
    total_pages: int


class LoginLogRead(BaseModel):
    """登录日志项（RuoYi sys_logininfor 对标）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    user_id: int | None
    status: str
    reason_code: str | None
    ip: str | None
    user_agent: str | None
    request_id: str | None
    login_at_utc: datetime
    created_at: datetime


class LoginLogPage(BaseModel):
    """登录日志分页 envelope。"""

    items: list[LoginLogRead]
    page: int
    size: int
    total: int
    total_pages: int
