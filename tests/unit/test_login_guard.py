"""login_guard fail-closed 单测（M5 hardening-r1）—— Redis 异常时要求验证码，不静默放行。

fleet 深审盲区：fail-closed 分支（pre_check 的 except → require_captcha）此前从未被任何测试执行
（login_guard 在 coverage omit）。用最小 broken redis stub 触发 except，测真实 fail-closed 行为。
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from redis.asyncio import Redis

from admin_platform.domains.auth import login_guard

pytestmark = pytest.mark.anyio


class _BrokenRedis:
    """镜像 redis.asyncio.Redis 最小契约：所有读操作抛 ConnectionError（模拟黑洞/不可用）。"""

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("redis unavailable")


async def test_pre_check_fail_closed_on_redis_error() -> None:
    """Redis 异常 → fail-closed：要求验证码（不静默放行，也不误报 ip_rate_limited/account_locked）。"""
    decision = await login_guard.pre_check(
        cast(Redis, _BrokenRedis()), username="x", client_ip="1.2.3.4"
    )
    assert decision.require_captcha is True
    assert decision.account_locked is False
    assert decision.ip_rate_limited is False
