"""验证码（算术文本，不引图形库）—— Redis 存储 + 一次性消费（spec 2026-06-09 §1.4）。

P1.4 用算术文本（如 "3 + 5 = ?"），规避图形库新依赖（符合 P0 spec「避免 Pillow」）。图形
base64 留 P6 前端阶段。Redis key ``auth:captcha:{id}`` 存答案，TTL 短；校验**无论对错都消费**
（删 key），防同一 captcha 暴力试答。
"""

from __future__ import annotations

import secrets

from redis.asyncio import Redis

from admin_platform.core.config import get_settings

_KEY = "auth:captcha:{}"
_MAX_OPERAND = 9


async def generate_captcha(redis: Redis) -> tuple[str, str]:
    """生成算术验证码，存 Redis（TTL），返回 (captcha_id, question)。"""
    a = secrets.randbelow(_MAX_OPERAND) + 1
    b = secrets.randbelow(_MAX_OPERAND) + 1
    captcha_id = secrets.token_urlsafe(16)
    answer = str(a + b)
    await redis.setex(_KEY.format(captcha_id), get_settings().auth_captcha_ttl_seconds, answer)
    return captcha_id, f"{a} + {b} = ?"


async def verify_captcha(redis: Redis, captcha_id: str | None, answer: str | None) -> bool:
    """校验 + 一次性消费（无论对错都删 key，防暴力试答）。缺参数 / 过期 / 错误 → False。"""
    if not captcha_id or not answer:
        return False
    key = _KEY.format(captcha_id)
    stored = await redis.get(key)
    if stored is None:
        return False
    await redis.delete(key)  # 一次性：消费后即失效
    expected = stored.decode() if isinstance(stored, bytes) else str(stored)
    return expected == answer.strip()
