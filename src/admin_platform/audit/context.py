"""请求级审计上下文（``ContextVar``）—— 把 IP/UA/request_id 等带到 service 层。

为什么要这层（P2 设计 §4）：``AuditRequest``（``events.py``）的 request 段在 P1 恒空，因为
**service / repository 层拿不到 ``Request``**（分层：仅 api 层有）。``build_audit_event`` 又在
service 层被调用（登录失败 / 权限拒绝 / rbac 写）。用穿层传 ``Request`` 会污染所有签名；改用
请求级 ``ContextVar``：``RequestIDMiddleware`` 在请求入口 set，``build_audit_event`` 默认 read。

分层（C8 / import-linter）：本模块是 ``audit`` 叶子，只依赖 ``audit.events``，**不 import core**
（``core.middleware`` 反过来 import 本模块来 set —— core → audit 方向已由 ``core.rbac_audit`` 确立）。

异步传播：``ContextVar`` 在 ``await`` 链上自然透传；``asyncio.create_task`` 会在创建时**快照**当前
context，所以请求入口 set 之后、同一 task 链内的所有 emit 都读得到（见 ``test_audit_context``）。
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from admin_platform.audit.events import AuditRequest

_request_ctx_var: ContextVar[AuditRequest | None] = ContextVar("audit_request_ctx", default=None)


def set_request_context(request: AuditRequest) -> Token[AuditRequest | None]:
    """在请求入口设置当前审计请求上下文，返回 reset token（中间件 finally 复位）。"""
    return _request_ctx_var.set(request)


def reset_request_context(token: Token[AuditRequest | None]) -> None:
    """复位上下文（请求结束，防止跨请求泄漏到复用的事件循环 task）。"""
    _request_ctx_var.reset(token)


def current_request_context() -> AuditRequest:
    """读当前请求上下文；无（如后台任务 / 单测未 set）时返回空 ``AuditRequest``。"""
    ctx = _request_ctx_var.get()
    return ctx if ctx is not None else AuditRequest()
