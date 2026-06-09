"""验证码（算术文本，不引图形库）—— Redis 存储 + 一次性消费（spec 2026-06-09 §1.4）。

P1.4 用算术文本（如 "3 + 5 = ?"），规避图形库新依赖（符合 P0 spec「避免 Pillow」）。图形
base64 留 P6 前端阶段。Redis key ``auth:captcha:{id}`` 存答案，TTL 短；校验**无论对错都消费**
（删 key），防同一 captcha 暴力试答。
"""

from __future__ import annotations

import logging
import secrets

from redis.asyncio import Redis

from admin_platform.core.config import get_settings

logger = logging.getLogger("admin_platform.auth")

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
    """校验 + **原子**一次性消费（Codex 复审修复）。缺参数 / 过期 / 错误 / Redis 故障 → False。

    用 ``GETDEL`` 原子读取并删除（Redis 6.2+）：避免「GET 后 DEL」非原子窗口里并发请求读到
    同一答案绕过一次性。Redis 异常 → 返回 False（**fail-closed**：故障时验证码视为未通过，
    不放行；认证防护不静默 fail-open）。
    """
    if not captcha_id or not answer:
        return False
    try:
        stored = await redis.getdel(_KEY.format(captcha_id))  # 原子读+删
    except Exception:
        logger.warning(
            "verify_captcha redis failed → treat as invalid (fail-closed)", exc_info=True
        )
        return False
    if stored is None:
        return False
    expected = stored.decode() if isinstance(stored, bytes) else str(stored)
    return expected == answer.strip()
