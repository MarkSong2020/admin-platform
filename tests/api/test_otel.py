"""OpenTelemetry 集成测试 —— ADR §4 守门 + lifecycle hardening。

覆盖：
  * otel_enabled=False 时 span_id 为 None
  * otel_enabled=True 时 trace_id/span_id 进入 access log
  * span 真被导出到 exporter（不止于 access log 注入）
  * 入站 traceparent → 导出 span 的 remote parent 正确串联
  * 多次 create_app() → span 正常创建（进程级单例 provider，幂等复用）
  * init 失败（exporter 构造抛错）降级、不阻塞启动
  * 全局已有 provider 时（Once no-op）不保存假 provider、清理未安装的 provider

OTel 的 ``set_tracer_provider`` 是进程级 Once：provider 只能成功装一次。逐测试
装/拆会因 Once 永久卡在首个 provider 上，拿不到后续测试的导出 span（旧测试只断
言 access log 有 span_id，恰好绕过了这个假绿陷阱）。故"真导出"类断言统一复用一个
module 级 provider；degrade/Once 两个纯单测自管 ``_state``，不依赖跑序。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from admin_platform.core import middleware as mw_module
from admin_platform.core import observability as otel_module
from admin_platform.core.config import get_settings
from admin_platform.main import create_app

# OTEL_EXPORTER_OTLP_ENDPOINT 仅为让 enabled 路径有个值；真 exporter 在测试里被
# InMemorySpanExporter 顶替，从不发网络（否则会朝此死端点重试、污染 make check 输出）。
_TEST_ENDPOINT = "http://127.0.0.1:9/v1/traces"

_OTEL_ENV_VARS = (
    "APP_OTEL_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
)

# 合法 W3C traceparent 的字段，用于 remote-parent 串联断言。
_REMOTE_TRACE_ID = "1234567890abcdef1234567890abcdef"
_REMOTE_PARENT_ID = "abcdef1234567890"
_REMOTE_TRACEPARENT = f"00-{_REMOTE_TRACE_ID}-{_REMOTE_PARENT_ID}-01"


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


# --------------------------------------------------------------------------- #
# 共享 enabled provider（module 级，顺应 OTel 全局 Once）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def otel_exporter() -> Iterator[InMemorySpanExporter]:
    """整个 module 装一次 enabled provider + InMemory exporter，测试间复用。

    见模块 docstring：Once 约束下逐测试装/拆拿不到导出 span。这里 module 级装一次、
    共享、末尾统一 shutdown（停 BatchSpanProcessor 后台线程）。
    """
    exporter = InMemorySpanExporter()
    saved = {k: os.environ.get(k) for k in _OTEL_ENV_VARS}
    saved_factory = otel_module.OTLPSpanExporter
    os.environ["APP_OTEL_ENABLED"] = "true"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = _TEST_ENDPOINT
    otel_module.OTLPSpanExporter = lambda **_kw: exporter  # type: ignore[assignment]
    get_settings.cache_clear()
    otel_module.init_observability()  # 装 provider（owns_provider=True）
    try:
        yield exporter
    finally:
        otel_module.OTLPSpanExporter = saved_factory
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
        if otel_module._state.provider is not None:
            otel_module._state.provider.shutdown()
        otel_module._state.provider = None
        otel_module._state.owns_provider = False


@pytest.fixture
def otel_app(otel_exporter: InMemorySpanExporter) -> FastAPI:
    """每测试一个新 app（复用 module provider，init 幂等 no-op）+ 清空 exporter。"""
    otel_exporter.clear()
    return create_app()


# --------------------------------------------------------------------------- #
# disabled 路径
# --------------------------------------------------------------------------- #
def test_otel_disabled_span_id_is_none(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> None:
    """otel_enabled=False 时 span_id 为 None（显式关，不依赖跑序）。"""
    monkeypatch.delenv("APP_OTEL_ENABLED", raising=False)
    get_settings.cache_clear()
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


# --------------------------------------------------------------------------- #
# enabled 路径（共享 module provider）
# --------------------------------------------------------------------------- #
class TestOtelEnabled:
    def test_span_id_injected_into_access_log(self, otel_app: FastAPI) -> None:
        """otel_enabled=True 时 access log 含非 None 的 32-hex trace_id + 16-hex span_id。"""

        @otel_app.get("/__otel-on")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        logged, orig = _spy_access_log()
        try:
            with TestClient(otel_app) as c:
                c.get("/__otel-on")
        finally:
            _restore_access_log(orig)

        assert len(logged) >= 1, "未捕获到 access log"
        extra = logged[0]
        assert extra.get("trace_id"), f"trace_id 不应为 None: {extra}"
        assert len(extra["trace_id"]) == 32, "trace_id 应为 32 字符 hex"
        assert extra.get("span_id"), f"span_id 不应为 None: {extra}"
        assert len(extra["span_id"]) == 16, "span_id 应为 16 字符 hex"

    def test_span_actually_exported(
        self, otel_app: FastAPI, otel_exporter: InMemorySpanExporter
    ) -> None:
        """span 真被导出到 exporter（不止 access log 注入）——旧测试的假绿盲区。"""

        @otel_app.get("/__otel-export")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(otel_app) as c:
            c.get("/__otel-export")
        otel_module._state.provider.force_flush()  # type: ignore[union-attr]

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1, f"应导出恰好 1 个 span，实得 {len(spans)}"
        span = spans[0]
        assert span.name == "GET /__otel-export"
        assert span.parent is None, "无入站 traceparent 时应是 root span"

    def test_remote_parent_chained_from_traceparent(
        self, otel_app: FastAPI, otel_exporter: InMemorySpanExporter
    ) -> None:
        """入站 traceparent → 导出 span 的 remote parent 正确串联（trace_id + parent span_id）。"""

        @otel_app.get("/__otel-parent")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        logged, orig = _spy_access_log()
        try:
            with TestClient(otel_app) as c:
                resp = c.get("/__otel-parent", headers={"traceparent": _REMOTE_TRACEPARENT})
        finally:
            _restore_access_log(orig)
        otel_module._state.provider.force_flush()  # type: ignore[union-attr]

        # access log 的 trace_id 透传入站 trace-id（端到端单一 id）。
        assert logged[0]["trace_id"] == _REMOTE_TRACE_ID
        # 响应 X-Request-ID 也等于入站 trace-id。
        assert resp.headers["x-request-id"] == _REMOTE_TRACE_ID

        spans = otel_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.context is not None
        assert span.context.trace_id == int(_REMOTE_TRACE_ID, 16), "span 应在入站 trace 下"
        assert span.parent is not None, "应有 remote parent"
        assert span.parent.span_id == int(_REMOTE_PARENT_ID, 16), (
            "parent span_id 应是入站 parent-id"
        )
        assert span.parent.is_remote is True

    def test_multiple_app_lifecycles_reuse_provider(
        self, otel_exporter: InMemorySpanExporter
    ) -> None:
        """两次 create_app → TestClient 生命周期后 span 仍正常（provider 进程级单例，幂等复用）。"""
        for tag in ("a", "b"):
            otel_exporter.clear()
            app = create_app()

            @app.get(f"/__otel-{tag}")
            async def handler() -> dict[str, str]:
                return {"id": "x"}

            logged, orig = _spy_access_log()
            try:
                with TestClient(app) as c:
                    c.get(f"/__otel-{tag}")
            finally:
                _restore_access_log(orig)
            assert logged[0].get("span_id"), f"第 {tag} 轮 span_id 不应为 None"


# --------------------------------------------------------------------------- #
# lifecycle hardening 单测（自管 _state，不依赖共享 provider / 跑序）
# --------------------------------------------------------------------------- #
@pytest.fixture
def _clean_otel_state() -> Iterator[None]:
    """临时清空 _state（保留并还原），让被测的 init 分支真正执行而非幂等 no-op。"""
    saved_provider = otel_module._state.provider
    saved_owns = otel_module._state.owns_provider
    otel_module._state.provider = None
    otel_module._state.owns_provider = False
    try:
        yield
    finally:
        otel_module._state.provider = saved_provider
        otel_module._state.owns_provider = saved_owns


@pytest.mark.usefixtures("_clean_otel_state")
def test_init_degrades_when_exporter_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """exporter 构造抛错 → init 不抛、tracing 禁用、服务可继续（provider 仍 None）。"""
    monkeypatch.setenv("APP_OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", _TEST_ENDPOINT)
    get_settings.cache_clear()

    def _boom(**_kw: object) -> object:
        raise RuntimeError("exporter 构造失败")

    monkeypatch.setattr(otel_module, "OTLPSpanExporter", _boom)

    otel_module.init_observability()  # 不应抛

    assert otel_module._state.provider is None
    assert otel_module._state.owns_provider is False


@pytest.mark.usefixtures("_clean_otel_state")
def test_init_skips_when_global_provider_already_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局已有 provider（set_tracer_provider Once no-op）→ 不保存假 provider，
    且清理我们新建的、未安装的 provider（停后台线程，防泄漏）。"""
    monkeypatch.setenv("APP_OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", _TEST_ENDPOINT)
    get_settings.cache_clear()
    monkeypatch.setattr(otel_module, "OTLPSpanExporter", lambda **_kw: InMemorySpanExporter())

    # 模拟全局已被别人占用：set 是 no-op，get 永远返回外部 sentinel（≠ 我们新建的）。
    sentinel = object()
    shutdown_calls: list[int] = []

    class _SpyProvider(TracerProvider):
        def shutdown(self) -> None:
            shutdown_calls.append(1)
            super().shutdown()

    monkeypatch.setattr(otel_module, "TracerProvider", _SpyProvider)
    monkeypatch.setattr(otel_module.trace, "set_tracer_provider", lambda _p: None)
    monkeypatch.setattr(otel_module.trace, "get_tracer_provider", lambda: sentinel)

    otel_module.init_observability()

    assert otel_module._state.provider is None, "Once no-op 时不得保存未安装的假 provider"
    assert otel_module._state.owns_provider is False
    assert shutdown_calls, "未安装的 provider 应被 shutdown 清理（防后台线程泄漏）"
