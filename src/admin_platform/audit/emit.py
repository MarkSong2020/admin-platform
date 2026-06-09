"""审计事件构造 + 落地（spec §13.3，P1 最小 hook = 结构化日志）。

P1 只把审计事件**写结构化日志**（``admin_platform.audit`` logger，JSON 一行）；P2 接中间件 +
持久化表。``build_audit_event`` 负责生成 ``event_id`` / ``occurred_at_utc`` + 脱敏 metadata；
生产调用走默认（自动生成），测试可注入固定值断言 envelope 形状。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from admin_platform.audit.context import append_audit_event, current_request_context
from admin_platform.audit.events import (
    AuditActor,
    AuditEvent,
    AuditRequest,
    AuditResult,
    AuditTarget,
    EventType,
    RiskLevel,
    redact_metadata,
)
from admin_platform.audit.sink import persist_audit_in_session
from admin_platform.db.session import current_request_session

_audit_logger = logging.getLogger("admin_platform.audit")


def build_audit_event(  # noqa: PLR0913 —— audit_event.v1 字段多且全命名 kwargs，工厂可放宽
    *,
    event_type: EventType,
    action: str,
    title: str,
    result: AuditResult,
    actor: AuditActor | None = None,
    target: AuditTarget | None = None,
    request: AuditRequest | None = None,
    duration_ms: int | None = None,
    risk_level: RiskLevel = "low",
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    occurred_at_utc: str | None = None,
) -> AuditEvent:
    """构造 ``audit_event.v1``（自动生成 id/时间 + 脱敏 metadata）。"""
    cleaned, redacted = redact_metadata(metadata)
    return AuditEvent(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        action=action,
        title=title,
        occurred_at_utc=occurred_at_utc or datetime.now(UTC).isoformat(),
        actor=actor or AuditActor(),
        target=target or AuditTarget(),
        # request 默认从请求级 ContextVar 读（中间件灌的 IP/UA/id）——service 层拿不到 Request，
        # 这是 P1 envelope.request 恒空的解法（P2 §4）。显式传入则覆盖（如测试注入固定值）。
        request=request if request is not None else current_request_context(),
        result=result,
        duration_ms=duration_ms,
        risk_level=risk_level,
        metadata=cleaned,
        redaction_applied=redacted,
    )


def _emit_to_logger(event: AuditEvent) -> None:
    """落结构化日志（一行 JSON 嵌在 ``audit_event`` 字段，见 core.logging 白名单）。失败不抛。"""
    try:
        _audit_logger.info(
            event.event_type,
            extra={"audit_event": event.model_dump(mode="json")},
        )
    except Exception:  # 审计落地失败绝不阻断业务主流程
        _audit_logger.warning("audit emit failed", exc_info=True)


def emit_audit(event: AuditEvent) -> None:
    """失败/拒绝类审计落地：logger（durable 底线）+ 追加请求缓冲（响应后中间件独立 session flush）。

    用于业务已 ROLLBACK 的事件（permission_denied / login_failed / rbac_write 失败 / refresh_reused）——
    这些不能随业务事务、必须独立落（守住失败审计不被回滚吞）。无缓冲（CLI/单测）= 仅 logger。
    """
    _emit_to_logger(event)
    append_audit_event(event)


async def record_audit_committed(event: AuditEvent) -> None:
    """成功类审计落地（review F1 修复，方案 B）：logger + 写**当前请求业务 session**（SAVEPOINT
    隔离，与业务原子提交）。

    成功审计必须与业务**原子**——commit 失败时审计随业务一同回滚，不留假成功审计。无请求 session
    （非 HTTP 上下文）回退缓冲独立 flush（无业务事务可绑，本就无 F1 风险）。
    """
    _emit_to_logger(event)
    session = current_request_session()
    if session is not None:
        await persist_audit_in_session(session, event)
    else:
        append_audit_event(event)


async def emit_rbac_write(  # noqa: PLR0913 —— audit_event 字段多（actor/target/result/metadata），全命名 kwargs 可放宽
    *,
    actor: AuditActor,
    action: str,
    target: AuditTarget,
    status: Literal["success", "failure"],
    http_status: int,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
    title: str = "RBAC 写操作",
) -> None:
    """发射 ``rbac_write`` 审计（spec §13.3）——所有 RBAC 管理写（CRUD + 绑定）的统一入口。

    成功 / 失败都记（失败带 ``error_code``，不阻断原业务错误）；``metadata`` 只放非敏感差异
    摘要（password/token 等再经 ``redact_metadata`` deny-list 兜底剔除）。risk_level 固定 medium。

    **写入路径按结果分流（review F1 方案 B）**：成功 → ``record_audit_committed``（写业务 session，
    SAVEPOINT 隔离，与业务原子提交）；失败 → ``emit_audit``（缓冲独立 flush，因业务已回滚）。
    """
    event = build_audit_event(
        event_type="rbac_write",
        action=action,
        title=title,
        actor=actor,
        target=target,
        result=AuditResult(status=status, http_status=http_status, error_code=error_code),
        risk_level="medium",
        metadata=metadata,
    )
    if status == "success":
        await record_audit_committed(event)
    else:
        emit_audit(event)
