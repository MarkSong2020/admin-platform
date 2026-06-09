"""审计事件持久化 ORM —— 表 ``audit_events``（P2 §2.1）。

``audit_event.v1`` envelope 的落库镜像：``payload`` 列存**完整 envelope**（无损取证/回放），
其余列是从 envelope 拆出的**查询列**（按 event_type / actor / 时间段 / status 过滤）。是
append-only 审计轨，覆盖 RuoYi ``sys_oper_log`` 超集（rbac_write / permission_denied /
login_failed / refresh_reused 都进）。

设计要点（spec §2.1 + Codex PK）：
  * actor **不设 FK**——审计须在用户删除后留存（CASCADE 误删、SET NULL 损调查价值），
    只存 user_id + username 冗余快照。
  * ``metadata`` 已在构造时经 ``redact_metadata`` deny-list 脱敏，存 JSONB。
  * ``event_id`` UNIQUE —— 幂等键（同一事件重复投递不产生重复行，为 P2.1 Redis Stream 留位）。
  * 不做时间分区（用户拍板：普通表 + 时间索引，量大再迁移）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.audit.events import AuditEvent
from admin_platform.db.base import Base, IdMixin, TimestampMixin


def _trunc(value: str | None, maxlen: int) -> str | None:
    """把入库 VARCHAR 列截断到列宽（审计 review F3：超长 UA/path 攻击者可控，PG VARCHAR 超长
    是抛 StringDataRightTruncation 而非截断 → 会让整批 add_all 失败、连累同请求其它安全事件丢失）。
    **完整原值仍存在 payload JSONB（无长度限制）里，故拆查询列截断零数据损失。**
    """
    if value is None:
        return None
    return value[:maxlen]


class AuditEventLog(Base, IdMixin, TimestampMixin):
    """``audit_event.v1`` 持久化记录（``created_at`` = 落库时刻，``occurred_at`` = 事件时刻）。"""

    __tablename__ = "audit_events"

    __table_args__ = (
        # 查询主路径：按时间倒序、按类型+时间、按操作者+时间、按结果状态、按 request_id 关联。
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_type_time", "event_type", "occurred_at"),
        Index("ix_audit_events_actor_time", "actor_user_id", "occurred_at"),
        Index("ix_audit_events_result_status", "result_status"),
        Index("ix_audit_events_request_id", "request_id"),
    )

    event_id: Mapped[str] = mapped_column(String(64), unique=True, comment="事件UUID(幂等键)")
    schema_version: Mapped[str] = mapped_column(String(32), comment="envelope schema版本")
    event_type: Mapped[str] = mapped_column(String(32), comment="事件类型(枚举)")
    action: Mapped[str] = mapped_column(String(128), comment="权限点/操作标识")
    title: Mapped[str] = mapped_column(String(256), comment="人读操作标题")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="事件发生时刻(UTC,来自envelope)"
    )

    # actor 冗余快照（无 FK：用户删除后审计仍留存）
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作者用户ID(快照,无FK)"
    )
    actor_username: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="操作者用户名(快照)"
    )
    actor_is_super_admin: Mapped[bool] = mapped_column(Boolean, comment="操作者是否超管")

    # target 快照
    target_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="作用对象类型"
    )
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="作用对象ID")
    target_display: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="作用对象显示名"
    )

    # request 段（中间件灌的 IP/UA/id）
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="请求ID(关联键)"
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="trace ID")
    method: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="HTTP方法")
    path: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="请求路径")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="客户端IP")
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="User-Agent")

    # result 段
    result_status: Mapped[str] = mapped_column(String(16), comment="结果(success/failure/denied)")
    result_http_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="HTTP状态码"
    )
    result_error_code: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="错误码"
    )

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="耗时(毫秒)")
    risk_level: Mapped[str] = mapped_column(String(16), comment="风险等级(low/medium/high)")
    # 属性名避开 DeclarativeBase 保留的 ``metadata``——映射到 DB 列名 "metadata"。
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, comment="脱敏后业务负载(JSONB)"
    )
    redaction_applied: Mapped[bool] = mapped_column(Boolean, comment="是否发生过脱敏")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, comment="完整envelope(无损取证)")

    @classmethod
    def from_envelope(cls, event: AuditEvent) -> AuditEventLog:
        """从 ``audit_event.v1`` envelope 构造持久化记录（拆查询列 + 存完整 payload）。"""
        # 拆查询列截断到列宽防溢出（完整原值在 payload）；event_id/schema_version/枚举类列源自
        # 服务端生成或固定枚举，不会超长，无需截断。
        return cls(
            event_id=event.event_id,
            schema_version=event.schema_version,
            event_type=event.event_type,
            action=_trunc(event.action, 128),
            title=_trunc(event.title, 256),
            occurred_at=datetime.fromisoformat(event.occurred_at_utc),
            actor_user_id=event.actor.user_id,
            actor_username=_trunc(event.actor.username, 64),
            actor_is_super_admin=event.actor.is_super_admin,
            target_type=_trunc(event.target.type, 64),
            target_id=_trunc(event.target.id, 128),
            target_display=_trunc(event.target.display, 255),
            request_id=_trunc(event.request.request_id, 64),
            trace_id=_trunc(event.request.trace_id, 64),
            method=_trunc(event.request.method, 16),
            path=_trunc(event.request.path, 512),
            ip=_trunc(event.request.ip, 64),
            user_agent=_trunc(event.request.user_agent, 512),
            result_status=event.result.status,
            result_http_status=event.result.http_status,
            result_error_code=_trunc(event.result.error_code, 128),
            duration_ms=event.duration_ms,
            risk_level=event.risk_level,
            metadata_json=event.metadata,
            redaction_applied=event.redaction_applied,
            payload=event.model_dump(mode="json"),
        )
