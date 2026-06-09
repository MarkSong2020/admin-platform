"""任务处理器 registry —— ``handler_key → HandlerSpec`` 白名单（P4c 安全核心）。

**反 RuoYi「任意调用目标字符串」**（Codex PK §3）：管理员只能选 registry 里**代码侧预注册**的
``handler_key``，DB 只存 key + ``params_json``，永远不存 import path / bean.method / 表达式 /
shell——后台管理权限不会被放大成服务器 RCE。每个 handler 自带 Pydantic params schema，参数在
create/update/manual_run 时强校验。

handler 契约：``async (params: dict) -> str | None``（返回值作 ``result_summary``）。需要 DB 的
handler 自行用 ``db_session()`` 开独立事务（与执行日志 session 解耦）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from admin_platform.db.session import db_session
from admin_platform.domains.auth.repository import RefreshTokenRepository

JobHandler = Callable[[dict[str, Any]], Awaitable[str | None]]


class HandlerParamsError(ValueError):
    """params 不符合 handler 的 schema（service 翻 422）。"""


@dataclass(frozen=True)
class HandlerSpec:
    """一个可调度任务处理器的元信息。``params_schema=None`` 表示零参 handler。"""

    key: str
    display_name: str
    handler: JobHandler
    params_schema: type[BaseModel] | None = None
    allow_manual: bool = True  # 是否允许手动触发


class JobHandlerRegistry:
    """进程级 handler 白名单。注册在 import 期完成（代码侧），运行期只读查询。"""

    def __init__(self) -> None:
        self._specs: dict[str, HandlerSpec] = {}

    def register(self, spec: HandlerSpec) -> None:
        if spec.key in self._specs:
            raise ValueError(f"重复注册 handler_key: {spec.key}")
        self._specs[spec.key] = spec

    def get(self, key: str) -> HandlerSpec | None:
        return self._specs.get(key)

    def keys(self) -> list[str]:
        return sorted(self._specs)

    def specs(self) -> list[HandlerSpec]:
        return [self._specs[k] for k in sorted(self._specs)]

    def validate_params(self, key: str, params: dict[str, Any]) -> dict[str, Any]:
        """用 handler 的 schema 校验并归一 params。零参 handler 要求 params 为空。

        命中 registry 是 service 的前置（此处假定 key 已存在）；params 非法抛 ``HandlerParamsError``。
        """
        spec = self._specs[key]
        if spec.params_schema is None:
            if params:
                raise HandlerParamsError(f"handler {key} 是零参，不接受 params")
            return {}
        try:
            return spec.params_schema.model_validate(params).model_dump(mode="json")
        except ValidationError as exc:
            raise HandlerParamsError(str(exc)) from exc


# ---- 全局 registry + 内置 handler -------------------------------------------

JOB_REGISTRY = JobHandlerRegistry()


async def _noop(params: dict[str, Any]) -> str | None:
    """空操作（演示 / 心跳 / 测试用）。"""
    return "ok"


class _EchoParams(BaseModel):
    message: str


async def _echo(params: dict[str, Any]) -> str | None:
    """回显参数 message（演示带参 handler + schema 校验）。"""
    return _EchoParams.model_validate(params).message


async def _cleanup_expired_refresh_tokens(params: dict[str, Any]) -> str | None:
    """清理已过期的 refresh token（真实维护任务，开独立事务）。"""
    async with db_session() as session:
        deleted = await RefreshTokenRepository(session).delete_expired()
    return f"deleted {deleted} expired refresh tokens"


JOB_REGISTRY.register(HandlerSpec("noop", "空操作", _noop))
JOB_REGISTRY.register(HandlerSpec("echo", "回显消息", _echo, params_schema=_EchoParams))
JOB_REGISTRY.register(
    HandlerSpec(
        "cleanup_expired_refresh_tokens", "清理过期refresh token", _cleanup_expired_refresh_tokens
    )
)
