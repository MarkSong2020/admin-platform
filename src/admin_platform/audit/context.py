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

from admin_platform.audit.events import AuditEvent, AuditRequest

_request_ctx_var: ContextVar[AuditRequest | None] = ContextVar("audit_request_ctx", default=None)

# 请求级审计事件缓冲（P2 §3 写入路径）：中间件入口 set 一个空 list，下游 emit_audit 往里
# append，响应后中间件 flush 一次（独立 session 批量落库）。
#
# 为何用「中间件持有引用的可变 list」而非「事件追加进 contextvar 值」：BaseHTTPMiddleware 下，
# 下游对 contextvar 的【重新赋值】不会上行传播回中间件（Starlette 已知行为），但对中间件 set 的
# 【同一 list 对象的 mutation】可见（同一内存对象）。故只 append、绝不重新 set，flush 用中间件
# 本地持有的那个 list 引用。同步线程池依赖（如 permissions._dep）由 anyio 复制 context 进线程，
# append 仍命中同一 list。
_audit_buffer_var: ContextVar[list[AuditEvent] | None] = ContextVar(
    "audit_event_buffer", default=None
)


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


def set_audit_buffer(buffer: list[AuditEvent]) -> Token[list[AuditEvent] | None]:
    """中间件入口设置请求级审计缓冲（传入中间件本地持有的空 list），返回 reset token。"""
    return _audit_buffer_var.set(buffer)


def reset_audit_buffer(token: Token[list[AuditEvent] | None]) -> None:
    _audit_buffer_var.reset(token)


def append_audit_event(event: AuditEvent) -> None:
    """把审计事件追加进当前请求缓冲（仅 mutate，不重新 set）。无缓冲（CLI/单测）= no-op。"""
    buffer = _audit_buffer_var.get()
    if buffer is not None:
        buffer.append(event)
