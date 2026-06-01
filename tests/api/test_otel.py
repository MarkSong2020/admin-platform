"""OpenTelemetry 集成测试 —— ADR §4 守门。

覆盖：
  * otel_enabled=True 时 trace_id/span_id 进入 access log
  * 多次 create_app() → span 正常创建（进程级单例 provider，幂等复用）
  * otel_enabled=False 时 span_id 为 None
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.trace import NoOpTracerProvider

from admin_platform.core import middleware as mw_module
from admin_platform.core.config import get_settings
from admin_platform.core.observability import _state
from admin_platform.main import create_app

_TEST_ENDPOINT = "http://127.0.0.1:9/v1/traces"  # 不可达，不影响 span 创建

_OTEL_ENV_VARS = (
    "APP_OTEL_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
)


@contextmanager
def _otel_context() -> Generator[None]:
    saved = {k: os.environ.get(k) for k in _OTEL_ENV_VARS}
    os.environ["APP_OTEL_ENABLED"] = "true"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = _TEST_ENDPOINT
    get_settings.cache_clear()
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
        # 重置 OTel 全局 provider，避免跨测试文件污染
        trace.set_tracer_provider(NoOpTracerProvider())
        _state.provider = None


def _spy_access_log() -> tuple[list, object]:
    """替换 access_logger.info 为 spy。返回 (logged_list, original_info)。"""
    logged: list = []
    orig = mw_module.access_logger.info

    def spy(msg, *a, extra=None, **kw):
        logged.append(extra or {})

    mw_module.access_logger.info = spy  # type: ignore[method-assign]
    return logged, orig


def _restore_access_log(orig: object) -> None:
    mw_module.access_logger.info = orig  # type: ignore[method-assign]


def test_otel_disabled_span_id_is_none(app: FastAPI) -> None:
    """otel_enabled=False 时 span_id 为 None。"""
    logged, orig = _spy_access_log()
    try:

        @app.get("/__otel-off")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app) as c:
            c.get("/__otel-off")
    finally:
        _restore_access_log(orig)

    assert len(logged) >= 1
    assert "span_id" in logged[0]
    assert logged[0]["span_id"] is None


def test_otel_enabled_injects_trace_and_span_id() -> None:
    """otel_enabled=True 时 access log 含非 None 的 trace_id 和 span_id。"""
    with _otel_context():
        app = create_app()

        @app.get("/__otel-on")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        logged, orig = _spy_access_log()
        try:
            with TestClient(app) as c:
                c.get("/__otel-on")
        finally:
            _restore_access_log(orig)

    assert len(logged) >= 1, "未捕获到 access log"
    extra = logged[0]
    assert extra.get("trace_id"), f"trace_id 不应为 None: {extra}"
    assert len(extra["trace_id"]) == 32, "trace_id 应为 32 字符 hex"
    assert extra.get("span_id"), f"span_id 不应为 None: {extra}"
    assert len(extra["span_id"]) == 16, "span_id 应为 16 字符 hex"


def test_multiple_lifecycles_spans_are_valid() -> None:
    """两次完整 create_app → TestClient 生命周期后 span 仍正常。

    OTel provider 是进程级单例：shutdown 只 force_flush、不清空 _state.provider，
    第二次 init 命中幂等保护复用同一 provider，span 仍正常创建。"""
    with _otel_context():
        # 第一次生命周期
        app1 = create_app()

        @app1.get("/__otel-a")
        async def ha() -> dict[str, str]:
            return {"id": "a"}

        logged1, orig1 = _spy_access_log()
        try:
            with TestClient(app1) as c:
                c.get("/__otel-a")
        finally:
            _restore_access_log(orig1)

        # 第二次生命周期（复用同一进程级 provider，init 幂等 no-op）
        app2 = create_app()

        @app2.get("/__otel-b")
        async def hb() -> dict[str, str]:
            return {"id": "b"}

        logged2, orig2 = _spy_access_log()
        try:
            with TestClient(app2) as c:
                c.get("/__otel-b")
        finally:
            _restore_access_log(orig2)

    assert logged1[0].get("span_id"), "第一轮 span_id 不应为 None"
    assert logged2[0].get("span_id"), "第二轮 span_id 不应为 None"
