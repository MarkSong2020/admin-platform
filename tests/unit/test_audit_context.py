"""请求级审计上下文 ContextVar 单测（DB-free）——守 P2 §4 上下文传播。

P1 envelope.request 恒空因 service 层拿不到 Request；P2 用 ContextVar 解。这里证：
build_audit_event 默认读上下文、显式传入可覆盖、未 set 时空、**异步 task 边界不丢**。
"""

from __future__ import annotations

import asyncio

from admin_platform.audit.context import (
    current_request_context,
    reset_request_context,
    set_request_context,
)
from admin_platform.audit.emit import build_audit_event
from admin_platform.audit.events import AuditRequest, AuditResult

_OK = AuditResult(status="success", http_status=200)


def test_current_request_context_empty_when_unset() -> None:
    # 无 set（后台任务 / 单测未 set）→ 空 AuditRequest，所有字段 None。
    ctx = current_request_context()
    assert ctx.ip is None
    assert ctx.request_id is None


def test_build_audit_event_reads_request_context() -> None:
    # 中间件灌的 IP/UA/id 应自动进 envelope.request（service 层不传 request）。
    token = set_request_context(
        AuditRequest(request_id="r1", ip="203.0.113.7", user_agent="pytest-ua", path="/x")
    )
    try:
        event = build_audit_event(
            event_type="rbac_write", action="system:user:add", title="x", result=_OK
        )
        assert event.request.ip == "203.0.113.7"
        assert event.request.user_agent == "pytest-ua"
        assert event.request.request_id == "r1"
    finally:
        reset_request_context(token)


def test_explicit_request_overrides_context() -> None:
    # 显式传入 request 覆盖 ContextVar（测试注入固定值的口子不被破坏）。
    token = set_request_context(AuditRequest(ip="203.0.113.7"))
    try:
        event = build_audit_event(
            event_type="rbac_write",
            action="a",
            title="x",
            result=_OK,
            request=AuditRequest(ip="198.51.100.2"),
        )
        assert event.request.ip == "198.51.100.2"
    finally:
        reset_request_context(token)


def test_reset_clears_context() -> None:
    token = set_request_context(AuditRequest(ip="203.0.113.7"))
    reset_request_context(token)
    assert current_request_context().ip is None


async def test_context_propagates_into_created_task() -> None:
    # 异步传播正确性（spec §4）：入口 set 后，同链 await + create_task 快照都读得到——
    # 防 task 边界丢上下文导致审计 request 段在并发下时有时无。
    token = set_request_context(AuditRequest(request_id="async-1", ip="192.0.2.9"))
    try:

        async def _inner() -> str | None:
            return current_request_context().ip

        # 同协程链直接读
        assert (await _inner()) == "192.0.2.9"
        # create_task 创建时快照当前 context → 子 task 仍读得到
        assert (await asyncio.create_task(_inner())) == "192.0.2.9"
    finally:
        reset_request_context(token)
