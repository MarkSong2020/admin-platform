"""登录日志写入（P2 §5）—— 登录全路径织入的落库 helper。

最佳努力（best-effort）：用**独立 session** 落 ``login_logs``，与登录业务事务解耦——失败路径的
登录日志须在业务 ROLLBACK 后仍留存（同 audit sink 的事务边界纪律），且日志写失败绝不阻断登录。
IP / User-Agent / request_id 从请求级 ``ContextVar`` 读（service 层拿不到 Request）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from admin_platform.audit.context import current_request_context
from admin_platform.db.session import db_session
from admin_platform.domains.auth.models import LoginLog

_logger = logging.getLogger("admin_platform.audit")

# 登录结果状态（对标 RuoYi sys_logininfor + admin 登录防护语义）。
LoginStatus = Literal["success", "failure", "locked", "rate_limited", "captcha_required"]


async def record_login_attempt(
    *,
    username: str,
    status: LoginStatus,
    user_id: int | None = None,
    reason_code: str | None = None,
) -> None:
    """落一条登录日志（独立 session，最佳努力，永不抛）。IP/UA/request_id 从请求上下文取。"""
    ctx = current_request_context()
    try:
        async with db_session() as session:
            session.add(
                LoginLog(
                    username=username,
                    user_id=user_id,
                    status=status,
                    reason_code=reason_code,
                    ip=ctx.ip,
                    user_agent=ctx.user_agent,
                    request_id=ctx.request_id,
                    login_at_utc=datetime.now(UTC),
                )
            )
    except Exception:  # 登录日志落库失败绝不阻断登录主流程
        _logger.warning("login log persist failed", exc_info=True)
