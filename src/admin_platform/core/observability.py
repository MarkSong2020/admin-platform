"""OpenTelemetry SDK 初始化 —— ADR §4 落地。

开关由 ``Settings.otel_enabled``（``APP_OTEL_ENABLED``）控制。
exporter endpoint / service name / resource attributes 走标准
`OTEL_* 环境变量 <https://opentelemetry.io/docs/languages/sdk-configuration/general/>`_
（``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_SERVICE_NAME`` 等）。

默认关闭（向后兼容）。生产接入只需设置
``APP_OTEL_ENABLED=true`` + ``OTEL_EXPORTER_OTLP_ENDPOINT``。
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from admin_platform.core.config import Settings, get_settings

logger = logging.getLogger("admin_platform.observability")


class _ProviderState:
    """模块级 OTel provider 引用——进程内只创建一次。"""

    def __init__(self) -> None:
        self.provider: TracerProvider | None = None


_state = _ProviderState()


def init_observability(settings: Settings | None = None) -> None:
    """初始化 OTel TracerProvider + OTLP SpanExporter。

    整个进程生命周期只执行一次——重复调用是安全的 no-op。
    未开启时不执行任何操作。

    Args:
        settings: 如果为 None，从 ``get_settings()`` 获取。
    """
    s = settings or get_settings()
    if not s.otel_enabled:
        return
    if _state.provider is not None:
        return  # 已初始化，幂等

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
    admin_platform = os.environ.get("OTEL_SERVICE_NAME", s.app_name)

    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        timeout=5,  # collector 不可达时不阻塞 shutdown
    )
    provider = TracerProvider(resource=Resource.create({"service.name": admin_platform}))
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            export_timeout_millis=5_000,
        )
    )
    # set_tracer_provider 全局只能成功设一次（OTel 内部用 Once 实现）：进程内
    # 已有全局 provider 时第二次调用只打一条 warning、静默 no-op，不抛异常。
    # 本函数靠上面的 _state.provider 幂等保护，正常流程只会执行到这里一次。
    trace.set_tracer_provider(provider)
    _state.provider = provider

    logger.info(
        "OTel SDK 已初始化",
        extra={"admin_platform": admin_platform, "endpoint": endpoint},
    )


async def shutdown_observability(settings: Settings | None = None) -> None:
    """flush 未发送 span。不 shutdown 全局 provider（进程级单例）。"""
    s = settings or get_settings()
    if not s.otel_enabled:
        return
    if _state.provider is None:
        return

    try:
        _state.provider.force_flush()
    except Exception:
        logger.warning("OTel force_flush 失败，忽略", exc_info=True)


def get_tracer(name: str = "admin_platform"):
    """获取命名 tracer。未开启 OTel 时返回 NoOp tracer。"""
    return trace.get_tracer(name)
