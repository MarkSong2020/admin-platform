"""_login_guard_redis 解耦回归（Codex 深审）—— DB/Redis-free。

登录防护用的 Redis 由 ``auth_login_guard_enabled`` 驱动，**不再**隐式依赖 ``app.state.redis``
是否存在（原先是 idempotency_enabled 的副作用，关幂等会静默关防护）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request

from admin_platform.api.v1.auth import _login_guard_redis
from admin_platform.core.config import get_settings


def _fake_request(redis_obj: object | None) -> Request:
    """鸭子类型 Request：仅暴露 _login_guard_redis 访问的 app.state.redis。"""
    app = SimpleNamespace(state=SimpleNamespace(redis=redis_obj))
    return cast("Request", SimpleNamespace(app=app))


def test_guard_disabled_returns_none_even_with_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # guard 关：即便 app.state.redis 存在也返回 None → login 跳过防护（解耦核心）。
    monkeypatch.setenv("APP_AUTH_LOGIN_GUARD_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert _login_guard_redis(_fake_request(object())) is None
    finally:
        get_settings.cache_clear()


def test_guard_enabled_returns_state_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # guard 开：返回 app.state.redis（main.py 已按 guard_enabled 创建）。
    monkeypatch.setenv("APP_AUTH_LOGIN_GUARD_ENABLED", "true")
    get_settings.cache_clear()
    sentinel = object()
    try:
        assert _login_guard_redis(_fake_request(sentinel)) is sentinel
    finally:
        get_settings.cache_clear()
