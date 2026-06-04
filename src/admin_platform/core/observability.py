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
    """模块级 OTel provider 引用——进程内只创建一次。

    ``owns_provider`` 区分"我们建的 provider 是否真装进了全局"——见
    ``init_observability`` 对 ``set_tracer_provider`` 全局 Once 的校验。
    只有 owned provider 才在 shutdown 时 flush；否则 ``force_flush`` 会作用在
    一个根本没承载请求 span 的 provider 上。
    """

    def __init__(self) -> None:
        self.provider: TracerProvider | None = None
        self.owns_provider: bool = False


_state = _ProviderState()


def init_observability(settings: Settings | None = None) -> None:
    """初始化 OTel TracerProvider + OTLP SpanExporter。

    整个进程生命周期只执行一次——重复调用是安全的 no-op。
    未开启时不执行任何操作。

    **健壮性**（lifecycle hardening）：OTel 是可选观测能力，**任何初始化失败都
    不得阻塞服务启动**——异常一律降级为 warning + 关闭 tracing 后继续。两条
    失败路径：

    1. exporter/provider 构造抛错（endpoint 非法、SDK 内部错）→ 捕获后 return，
       ``_state.provider`` 保持 None，请求侧走 NoOp tracer。
    2. ``set_tracer_provider`` 受全局 Once 约束 no-op（进程内已有别的 provider）
       → 我们新建的 provider **没装进全局**，但它的 ``BatchSpanProcessor`` 后台
       线程已经起来了。必须 ``shutdown()`` 清理（否则线程泄漏），且**不**把这个
       未安装的 provider 存进 ``_state``（否则 shutdown 时 flush 错对象、日志谎报
       初始化成功）。

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

    try:
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
        trace.set_tracer_provider(provider)
    except Exception:
        logger.warning(
            "OTel 初始化失败，tracing 已禁用，服务继续启动",
            extra={"admin_platform": admin_platform, "endpoint": endpoint},
            exc_info=True,
        )
        return

    # set_tracer_provider 全局只能成功设一次（OTel 内部用 Once）：已有全局 provider
    # 时第二次调用只打 warning、静默 no-op。用 identity 校验确认本次真的安装成功，
    # 而不是无条件相信。
    if trace.get_tracer_provider() is provider:
        _state.provider = provider
        _state.owns_provider = True
        logger.info(
            "OTel SDK 已初始化",
            extra={"admin_platform": admin_platform, "endpoint": endpoint},
        )
    else:
        # 全局已有 provider（Once no-op）：清理我们刚建的、未安装的 provider，
        # 停掉它的后台导出线程，避免泄漏；不存进 _state。
        try:
            provider.shutdown()
        except Exception:
            logger.warning("清理未安装的 OTel provider 失败", exc_info=True)
        logger.warning(
            "进程内已存在全局 TracerProvider，跳过本模块 OTel 初始化",
            extra={"admin_platform": admin_platform},
        )


async def shutdown_observability(settings: Settings | None = None) -> None:
    """flush 未发送 span。不 shutdown 全局 provider（进程级单例）。

    只对 **owned** provider（``set_tracer_provider`` 真装进全局的那个）force_flush；
    Once no-op 下未安装的 provider 已在 ``init_observability`` 里清理，不在此处理。
    """
    s = settings or get_settings()
    if not s.otel_enabled:
        return
    if _state.provider is None or not _state.owns_provider:
        return

    try:
        _state.provider.force_flush()
    except Exception:
        logger.warning("OTel force_flush 失败，忽略", exc_info=True)


def get_tracer(name: str = "admin_platform"):
    """获取命名 tracer。未开启 OTel 时返回 NoOp tracer。"""
    return trace.get_tracer(name)
