"""registry + cron 单测（P4c，DB-free）—— 安全核心（白名单 + params 校验）+ cron 校验。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from admin_platform.domains.scheduled_task.cron import (
    CronValidationError,
    build_cron_trigger,
    next_run_after,
    validate_cron,
)
from admin_platform.domains.scheduled_task.registry import (
    JOB_REGISTRY,
    HandlerParamsError,
    HandlerSpec,
    JobHandlerRegistry,
)


class _P(BaseModel):
    message: str


async def _h(params: dict) -> str | None:
    return "ok"


# ---- registry 机制 ----


def test_register_and_get() -> None:
    reg = JobHandlerRegistry()
    reg.register(HandlerSpec("k1", "K1", _h))
    assert reg.get("k1") is not None
    assert reg.get("missing") is None
    assert reg.keys() == ["k1"]


def test_register_duplicate_raises() -> None:
    reg = JobHandlerRegistry()
    reg.register(HandlerSpec("k", "K", _h))
    with pytest.raises(ValueError, match="重复注册"):
        reg.register(HandlerSpec("k", "K2", _h))


def test_validate_params_zero_arg_rejects_params() -> None:
    reg = JobHandlerRegistry()
    reg.register(HandlerSpec("noop", "noop", _h))  # 无 params_schema
    assert reg.validate_params("noop", {}) == {}
    with pytest.raises(HandlerParamsError):
        reg.validate_params("noop", {"x": 1})


def test_validate_params_with_schema() -> None:
    reg = JobHandlerRegistry()
    reg.register(HandlerSpec("echo", "echo", _h, params_schema=_P))
    assert reg.validate_params("echo", {"message": "hi"}) == {"message": "hi"}
    with pytest.raises(HandlerParamsError):
        reg.validate_params("echo", {})  # 缺必填 message
    with pytest.raises(HandlerParamsError):
        reg.validate_params("echo", {"message": 123, "extra": "no"})  # 类型错 / 多字段


def test_global_registry_has_builtins() -> None:
    assert set(JOB_REGISTRY.keys()) >= {"noop", "echo", "cleanup_expired_refresh_tokens"}
    specs = {s.key: s for s in JOB_REGISTRY.specs()}
    assert specs["echo"].params_schema is not None
    assert specs["noop"].params_schema is None


# ---- cron 校验 ----


def test_cron_valid_5_field() -> None:
    validate_cron("0 2 * * *", timezone="Asia/Shanghai")
    assert build_cron_trigger("*/5 * * * *", timezone="UTC") is not None


@pytest.mark.parametrize(
    "bad",
    ["0 0 2 * * *", "0 2 * * ?", "bogus", "0 2 * *", "99 2 * * *", "0 2 * * * *"],
)
def test_cron_invalid_rejected(bad: str) -> None:
    with pytest.raises(CronValidationError):
        validate_cron(bad, timezone="Asia/Shanghai")


def test_cron_bad_timezone_rejected() -> None:
    with pytest.raises(CronValidationError):
        validate_cron("0 2 * * *", timezone="Mars/Phobos")


def test_next_run_after_computes() -> None:
    nxt = next_run_after(
        "*/5 * * * *", timezone="UTC", now=datetime(2026, 6, 10, 10, 1, tzinfo=UTC)
    )
    assert nxt is not None
    assert nxt.minute == 5  # 10:01 → 下一个 */5 = 10:05
