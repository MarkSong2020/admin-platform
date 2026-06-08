"""审计事件构造 + 落地（spec §13.3，P1 最小 hook = 结构化日志）。

P1 只把审计事件**写结构化日志**（``admin_platform.audit`` logger，JSON 一行）；P2 接中间件 +
持久化表。``build_audit_event`` 负责生成 ``event_id`` / ``occurred_at_utc`` + 脱敏 metadata；
生产调用走默认（自动生成），测试可注入固定值断言 envelope 形状。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

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
        request=request or AuditRequest(),
        result=result,
        duration_ms=duration_ms,
        risk_level=risk_level,
        metadata=cleaned,
        redaction_applied=redacted,
    )


def emit_audit(event: AuditEvent) -> None:
    """把审计事件落结构化日志（一行 JSON 嵌在 ``audit_event`` 字段，见 core.logging 白名单）。

    P1 最小 hook —— 失败不抛（审计不应阻断主流程）：日志器异常吞掉只记一条 warning。
    """
    try:
        _audit_logger.info(
            event.event_type,
            extra={"audit_event": event.model_dump(mode="json")},
        )
    except Exception:  # 审计落地失败绝不阻断业务主流程
        _audit_logger.warning("audit emit failed", exc_info=True)
