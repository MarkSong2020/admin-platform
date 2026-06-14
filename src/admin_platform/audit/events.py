"""审计事件 envelope —— ``audit_event.v1``（spec §13.3 / Q16，P1 冻字段契约）。

P1 只**冻结内部事件模型**（带 ``schema_version``）+ 脱敏双层；P2 做完整中间件织入 + 持久化表，
**保持 v1 字段兼容**（``schema_version`` + ``metadata`` 扩展位保证迁表/扩字段不破契约）。

与对外 ``ProblemDetail`` **分离**（§6.3 保留 RFC 9457）：审计是内部事件，二者只共享
``request_id`` / ``trace_id`` / ``error_code`` 作关联键，不互相塞字段。

脱敏双层（Codex 风险 3）：
  * **deny-list**：``Authorization`` / ``password`` / ``token`` / ``cookie`` / ``secret`` 等敏感 key
    **永不入审计**（``redact_metadata`` 在构造时剔除）。
  * **allow-list**：``request`` 段只记录白名单字段（不吞整个 headers）。
  * ``redaction_applied`` 标记本事件是否发生过脱敏。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "audit_event.v1"

# refresh_reused（P1.4）：refresh token 重用检测命中 = token theft 信号，高风险审计事件。
# login_success（P2）：登录成功，让审计 envelope 覆盖完整登录活动（compliance 常要成功登录留痕）。
# v1 EventType 演进（decision-log 2026-06-09 §3）—— schema_version 不变，枚举扩展向后兼容。
EventType = Literal[
    "permission_denied",
    "login_failed",
    "rbac_write",
    "refresh_reused",
    "login_success",
    "password_change",
]
RiskLevel = Literal["low", "medium", "high"]

# 敏感 key（小写包含匹配）——命中即从 metadata 剔除，永不进审计（deny-list）。
_DENY_KEYS = (
    "authorization",
    "password",
    "passwd",
    "token",
    "cookie",
    "secret",
    "api_key",
    "apikey",
    "credential",
)


def redact_metadata(raw: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    """剔除 ``raw`` 中命中 deny-list 的 key（大小写不敏感），返回 (清洁 dict, 是否脱敏过)。

    **递归脱敏**（Codex 深审）：嵌套 dict / list 内的敏感 key 也剔除——P2 写审计 payload 可能
    带嵌套结构（如 ``{"changes": {"password": ...}}``），仅清顶层会漏。
    """
    if not raw:
        return {}, False
    return _redact_dict(raw)


def _redact_dict(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    cleaned: dict[str, Any] = {}
    redacted = False
    for key, value in data.items():
        if any(bad in key.lower() for bad in _DENY_KEYS):
            redacted = True
            continue
        new_value, sub_redacted = _redact_value(value)
        cleaned[key] = new_value
        redacted = redacted or sub_redacted
    return cleaned, redacted


def _redact_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        return _redact_dict(value)
    if isinstance(value, list):
        out: list[Any] = []
        any_redacted = False
        for item in value:
            new_item, item_redacted = _redact_value(item)
            out.append(new_item)
            any_redacted = any_redacted or item_redacted
        return out, any_redacted
    return value, False


class AuditActor(BaseModel):
    """事件触发者（超管不绕审计，呼应 §2.3）。"""

    model_config = ConfigDict(frozen=True)
    user_id: int | None = None
    username: str | None = None
    is_super_admin: bool = False


class AuditTarget(BaseModel):
    """事件作用对象（被增删改的资源 / 登录尝试的目标账号）。"""

    model_config = ConfigDict(frozen=True)
    type: str | None = None
    id: str | None = None
    display: str | None = None


class AuditRequest(BaseModel):
    """请求上下文（allow-list：只记录白名单字段，不吞整个 headers）。"""

    model_config = ConfigDict(frozen=True)
    request_id: str | None = None
    trace_id: str | None = None
    method: str | None = None
    path: str | None = None
    ip: str | None = None
    user_agent: str | None = None


class AuditResult(BaseModel):
    """事件结果（与 ProblemDetail 仅共享 error_code 关联键）。"""

    model_config = ConfigDict(frozen=True)
    status: Literal["success", "failure", "denied"]
    http_status: int | None = None
    error_code: str | None = None


class AuditEvent(BaseModel):
    """``audit_event.v1`` 内部事件模型（冻结字段，P2 织入保持兼容）。"""

    model_config = ConfigDict(frozen=True)
    schema_version: str = SCHEMA_VERSION
    event_id: str
    event_type: EventType
    action: str
    title: str
    occurred_at_utc: str
    actor: AuditActor
    target: AuditTarget = AuditTarget()
    request: AuditRequest = AuditRequest()
    result: AuditResult
    duration_ms: int | None = None
    risk_level: RiskLevel = "low"
    metadata: dict[str, Any] = Field(default_factory=dict)
    redaction_applied: bool = False
