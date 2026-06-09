"""P0.9 认证安全原语 —— Argon2id 密码哈希 + JWT access token 签发/解码。

职责（ADR-C / ADR-F）：

  * ``hash_password`` / ``verify_password`` —— Argon2id（``argon2.PasswordHasher`` 默认参数
    m=64 MiB / t=3 / p=4 / hash_len=32 / salt_len=16，强于 OWASP 最低线）。
  * ``issue_access_token`` —— 登录成功后签发 JWT access token（claims = sub/username/iat/exp，
    TTL 取 ``auth_access_token_ttl_seconds``）。P0.9 不发 refresh token。
  * ``decode_token`` —— 解码 + 校验，require ``sub`` / ``exp`` / ``iat``。

签名密钥 / 算法 / iss / aud 直接读 ``Settings.auth_jwt_*``（不经 auth 层，保持
``config ← security ← auth`` 单向依赖 —— 中间件 ``AuthMiddleware`` 复用本模块 ``decode_token``，
若 security 反向依赖 auth 会构成循环 import）。

安全设计（经 Codex 安全 PK 收紧）：

  * **空 secret fail-fast**：PyJWT 用空字符串密钥 encode/decode 会"成功"（只发不安全警告），
    等于签发可伪造 token。``issue`` / ``decode`` 在 secret 为空时直接抛 ``TokenConfigError``，
    不依赖 ``Settings`` 的 ``auth_enabled=true`` 校验（那条只在开启鉴权时生效）。
  * **iss/aud 仅在 config 配置时写入/校验**：P0.9 默认空（等团队 SSO + Q4 决议）。access TTL 2h
    令"后续启用校验使旧 token 失效"的迁移成本可忽略，故此处不预埋固定值。
"""

from __future__ import annotations

import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from admin_platform.core.config import get_settings

logger = logging.getLogger("admin_platform.security")

# 进程级单例 —— 默认参数即 ADR-F 选定值，无需调参（调参须先压测登录并发 × 单次内存）。
_password_hasher = PasswordHasher()

# decode 必需 claims：sub / exp / iat（单租户，不再 require tenant_id）。
_REQUIRED_CLAIMS = ("sub", "exp", "iat")


class TokenConfigError(RuntimeError):
    """签发/解码所需的 JWT secret 缺失 —— 拒绝用空密钥处理可伪造 token。"""


# ---- 密码哈希 ----


def hash_password(password: str) -> str:
    """返回 Argon2id 编码串（自带算法参数 + 盐，可直接入库 ``password_hash``）。"""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与存量 hash 是否匹配。

    登录边界：任何"不匹配 / hash 损坏 / 格式不支持"都返回 ``False`` 而非抛错，避免把
    存量数据问题暴露成 500 或制造账号状态差异（可被用于枚举）。但不 ``except Exception``
    全吞 —— ``TypeError`` 等编程错误仍应冒泡，由测试/告警暴露。
    """
    try:
        _password_hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False  # 正常的密码不匹配
    except VerificationError, InvalidHashError:
        # 存量 hash 损坏 / 非 argon2 格式 / 被篡改 —— 返 False，但记脱敏 warning 供告警。
        logger.warning("verify_password: 存量 hash 无法校验（损坏或格式不支持）")
        return False


# ---- access token 签发 ----


def _require_secret(secret: str) -> str:
    if not secret:
        raise TokenConfigError(
            "auth_jwt_secret 为空：拒绝用空密钥签发/解码 token（设 APP_AUTH_JWT_SECRET）"
        )
    return secret


def issue_access_token(*, user_id: int, username: str) -> str:
    """签发 access token。claims = sub/username/iat/exp(+iss/aud)。"""
    settings = get_settings()
    secret = _require_secret(settings.auth_jwt_secret)
    issued_at = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=settings.auth_access_token_ttl_seconds),
    }
    if settings.auth_jwt_issuer:
        claims["iss"] = settings.auth_jwt_issuer
    if settings.auth_jwt_audience:
        claims["aud"] = settings.auth_jwt_audience
    return jwt.encode(claims, key=secret, algorithm=settings.auth_jwt_algorithm)


# ---- access token 解码 + 校验 ----


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验 access token，返回 payload。

    抛 ``jwt.ExpiredSignatureError`` / ``jwt.InvalidTokenError`` —— 由 ``AuthMiddleware``
    据此分别映射 401 ``auth.TOKEN_EXPIRED`` / ``auth.TOKEN_INVALID``。
    """
    settings = get_settings()
    secret = _require_secret(settings.auth_jwt_secret)
    validate_issuer = bool(settings.auth_jwt_issuer)
    validate_audience = bool(settings.auth_jwt_audience)
    payload: dict[str, Any] = jwt.decode(
        token,
        key=secret,
        algorithms=[settings.auth_jwt_algorithm],
        options={
            "require": list(_REQUIRED_CLAIMS),
            "verify_exp": True,
            "verify_iat": True,
            "verify_nbf": False,
            "verify_iss": validate_issuer,
            "verify_aud": validate_audience,
        },
        audience=settings.auth_jwt_audience if validate_audience else None,
        issuer=settings.auth_jwt_issuer if validate_issuer else None,
    )
    # PyJWT 的 require 只保证 sub 存在且非 None，不挡空串。空 sub 没有有效 subject —— 拒之，
    # 防"合法签名但 sub='' 的 token"访问私有路由（纵深加固，P0.9 Codex review）。
    if not payload["sub"]:
        raise jwt.InvalidTokenError("sub 不能为空")
    return payload


# ---- refresh token 原语（P1.4：opaque + HMAC 落库可撤销，spec 2026-06-09）----

_REFRESH_PREFIX = "rt_"


def _require_pepper(pepper: str) -> str:
    if not pepper:
        raise TokenConfigError(
            "auth_refresh_token_pepper 为空：拒绝用空密钥 HMAC refresh token（设 APP_AUTH_REFRESH_TOKEN_PEPPER）"
        )
    return pepper


def generate_refresh_token() -> tuple[str, str, str]:
    """生成 opaque refresh token，返回 (明文 token, jti, token_hash)。

    明文 ``rt_<jti>.<secret>`` 只返回给客户端一次（不落库）；DB 存 ``token_hash``
    = ``HMAC-SHA256(pepper, secret)`` 的 hex。高熵随机 secret 用 HMAC+pepper 而非 Argon2
    （Argon2 适合低熵密码；refresh 高频等值校验，HMAC 快且抗彩虹表）。
    """
    jti = str(uuid.uuid4())
    secret = secrets.token_urlsafe(32)  # 256-bit
    token = f"{_REFRESH_PREFIX}{jti}.{secret}"
    return token, jti, hash_refresh_secret(secret)


def hash_refresh_secret(secret: str) -> str:
    """``HMAC-SHA256(pepper, secret)`` 的 hex（64 字符）。"""
    pepper = _require_pepper(get_settings().auth_refresh_token_pepper)
    return hmac.new(pepper.encode(), secret.encode(), sha256).hexdigest()


def parse_refresh_token(token: str) -> tuple[str, str] | None:
    """解析明文 ``rt_<jti>.<secret>`` → (jti, secret)；格式非法返回 None（统一无效处理）。"""
    if not token.startswith(_REFRESH_PREFIX):
        return None
    body = token[len(_REFRESH_PREFIX) :]
    jti, sep, secret = body.partition(".")
    if not sep or not jti or not secret:
        return None
    return jti, secret


def verify_refresh_secret(secret: str, token_hash: str) -> bool:
    """常量时间比对 secret 的 HMAC 与库存 hash。"""
    return hmac.compare_digest(hash_refresh_secret(secret), token_hash)
