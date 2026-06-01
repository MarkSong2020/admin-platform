"""Request ID middleware + 访问日志 + OTel span 管理。

- 透传 / 生成 X-Request-ID，通过 ContextVar 和 request.state 暴露出去。
- 解析 W3C ``traceparent`` 抽取 trace-id（ADR §4 OTel 绑定）。
- OTel 启用时为每个请求创建 span，span_id 注入 access log extra。
- 每个请求 emit 一条访问日志（method / path / status_code / duration_ms）。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect

from admin_platform.core.config import get_settings

# nginx 风格的「客户端关闭请求」状态码 —— 在客户端在 handler 完成前
# 断开时记进访问日志，避免 5xx 错误率指标被「用户主动关页」污染。
_CLIENT_CLOSED_REQUEST = 499

access_logger = logging.getLogger("admin_platform.access")

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# ADR §4：X-Request-ID 必须是 32 字符小写 hex（W3C trace-id 格式）。
_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# W3C Trace Context traceparent: {version}-{trace-id}-{parent-id}-{trace-flags}
# https://www.w3.org/TR/trace-context/#traceparent-header-field-values
_TRACEPARENT_PATTERN = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def current_request_id() -> str | None:
    return _request_id_var.get()


_ALL_ZERO_TRACE_ID = "0" * 32
_ALL_ZERO_SPAN_ID = "0" * 16


def _generate_request_id() -> str:
    """uuid4().hex，符合 W3C trace-id 规范：**不能**全 0。

    理论上极罕见（~1 / 2**122），但 W3C Trace Context 规范明确把全 0
    trace-id 标为 invalid。循环到非全 0 hex 才返回，保证这个 id 后续
    可以安全作为 OTel trace-id 用。
    """
    while True:
        candidate = uuid.uuid4().hex
        if candidate != _ALL_ZERO_TRACE_ID:
            return candidate


class _TraceContext:
    """从 W3C traceparent header 解析出的 trace 上下文。"""

    __slots__ = ("parent_id", "trace_flags", "trace_id")

    def __init__(self, trace_id: str, parent_id: str, trace_flags: str) -> None:
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.trace_flags = trace_flags


def _resolve_ids(request: Request, header: str) -> tuple[str, str | None, _TraceContext | None]:
    """按 ADR §4 优先级解析 (request_id, trace_id, trace_ctx)。

    1. ``traceparent`` —— 解出 trace-id / parent-id / trace-flags。
       trace-id 同时作为 request_id（端到端单一 id）。
    2. ``X-Request-ID`` 如果格式合法 —— 透传。
    3. 其它 —— 服务端生成新的 32 字符 hex。
    """
    traceparent = request.headers.get("traceparent")
    if traceparent is not None:
        match = _TRACEPARENT_PATTERN.fullmatch(traceparent)
        if match:
            trace_id = match.group(1)
            parent_id = match.group(2)
            trace_flags = match.group(3)
            if trace_id != _ALL_ZERO_TRACE_ID and parent_id != _ALL_ZERO_SPAN_ID:
                return trace_id, trace_id, _TraceContext(trace_id, parent_id, trace_flags)

    candidate = request.headers.get(header)
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate, None, None

    return _generate_request_id(), None, None


def _create_span_context(trace_ctx: _TraceContext | None) -> SpanContext | None:
    """用 traceparent 的真实 parent-id 构造 remote SpanContext。

    trace_ctx 为 None 表示无入站 trace（由 OTel SDK 自动生成根 span）。
    """
    if trace_ctx is None:
        return None
    flags = int(trace_ctx.trace_flags, 16)
    return SpanContext(
        trace_id=int(trace_ctx.trace_id, 16),
        span_id=int(trace_ctx.parent_id, 16),
        is_remote=True,
        trace_flags=TraceFlags(flags),
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        header = settings.request_id_header
        request_id, trace_id, trace_ctx = _resolve_ids(request, header)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.span_id = None
        token = _request_id_var.set(request_id)
        start = time.perf_counter()

        span_id: str | None = None
        status_code = 500
        try:
            if settings.otel_enabled:
                tracer = trace.get_tracer("admin_platform.http")
                span_name = f"{request.method} {request.url.path}"
                parent_ctx = _create_span_context(trace_ctx)

                if parent_ctx is not None:
                    parent = trace.set_span_in_context(NonRecordingSpan(parent_ctx))
                    span_cm = tracer.start_as_current_span(span_name, context=parent)
                else:
                    span_cm = tracer.start_as_current_span(span_name)

                with span_cm as active_span:
                    span_ctx = active_span.get_span_context()  # type: ignore[attr-defined]
                    if span_ctx.is_valid:
                        span_id = format(span_ctx.span_id, "016x")
                        request.state.span_id = span_id
                        if trace_id is None:
                            trace_id = format(span_ctx.trace_id, "032x")
                            request.state.trace_id = trace_id
                    response = await call_next(request)
            else:
                response = await call_next(request)
            status_code = response.status_code
            response.headers[header] = request_id
            return response
        except ClientDisconnect:
            status_code = _CLIENT_CLOSED_REQUEST
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            _request_id_var.reset(token)
            access_logger.info(
                "request handled",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
