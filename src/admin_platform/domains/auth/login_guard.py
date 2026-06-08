"""登录限流（Redis 组合维度，Q14 联动，spec 2026-06-09 §1.5）。

防分布式撞库（账号维度）+ 防单源打多账号（IP 维度）。Q14：失败 N 次后**要求验证码**
（验证码作纵深，非首登必填）；更高阈值账号软锁；IP 维度超限 429。

**fail-closed**（Codex 纠正：认证防护 ≠ 幂等 fail-open）：Redis 操作异常时**要求验证码**
（``LoginGuardDecision.require_captcha=True``），不静默放行 —— redis 抖动时登录受限但不被撞库。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis

from admin_platform.core.config import get_settings

logger = logging.getLogger("admin_platform.auth")

_FAIL_USER = "auth:fail:user:{}"
_FAIL_IP = "auth:fail:ip:{}"
_LOCK_USER = "auth:lock:user:{}"


@dataclass(frozen=True)
class LoginGuardDecision:
    """登录前置判定：是否要求验证码 / 账号软锁 / IP 限流。"""

    require_captcha: bool = False
    account_locked: bool = False
    ip_rate_limited: bool = False


async def _safe_int(redis: Redis, key: str) -> int:
    val = await redis.get(key)
    if val is None:
        return 0
    try:
        return int(val)
    except ValueError, TypeError:
        return 0


async def pre_check(redis: Redis, *, username: str, client_ip: str | None) -> LoginGuardDecision:
    """登录前查计数：决定是否要求验证码 / 已锁定 / IP 限流。Redis 异常 → fail-closed（要求验证码）。"""
    settings = get_settings()
    try:
        if await redis.get(_LOCK_USER.format(username)) is not None:
            return LoginGuardDecision(account_locked=True)
        user_fails = await _safe_int(redis, _FAIL_USER.format(username))
        ip_fails = await _safe_int(redis, _FAIL_IP.format(client_ip)) if client_ip else 0
        if client_ip and ip_fails >= settings.auth_login_ip_limit:
            return LoginGuardDecision(ip_rate_limited=True)
        require_captcha = user_fails >= settings.auth_login_captcha_threshold
        return LoginGuardDecision(require_captcha=require_captcha)
    except Exception:  # redis 不可用 → fail-closed：要求验证码（不静默放行，Codex）
        logger.warning("login_guard pre_check redis failed → require captcha", exc_info=True)
        return LoginGuardDecision(require_captcha=True)


async def record_failure(redis: Redis, *, username: str, client_ip: str | None) -> None:
    """登录失败：累加 user/ip 计数（窗口 TTL）；user 计数达锁定阈值 → 设软锁。Redis 异常吞掉。"""
    settings = get_settings()
    window = settings.auth_login_fail_window_seconds
    try:
        user_key = _FAIL_USER.format(username)
        user_fails = await redis.incr(user_key)
        await redis.expire(user_key, window)
        if client_ip:
            ip_key = _FAIL_IP.format(client_ip)
            await redis.incr(ip_key)
            await redis.expire(ip_key, window)
        if user_fails >= settings.auth_login_lock_threshold:
            await redis.setex(_LOCK_USER.format(username), settings.auth_login_lock_seconds, "1")
    except Exception:  # 记录失败不阻断主流程（已是失败路径）
        logger.warning("login_guard record_failure redis failed", exc_info=True)


async def clear_on_success(redis: Redis, *, username: str, client_ip: str | None) -> None:
    """登录成功：清 combo 计数。保守保留 user 计数短期（撞库偶中不清零历史）—— P1.4 清 ip 与锁。"""
    try:
        await redis.delete(_FAIL_IP.format(client_ip)) if client_ip else None
        await redis.delete(_LOCK_USER.format(username))
    except Exception:
        logger.warning("login_guard clear_on_success redis failed", exc_info=True)
