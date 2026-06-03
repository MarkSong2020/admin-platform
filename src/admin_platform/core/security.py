"""P0 认证安全原语 —— Argon2id 密码哈希 + JWT access token 签发/解码。

职责（ADR-C / ADR-F）：

  * ``hash_password`` / ``verify_password`` —— Argon2id（``argon2.PasswordHasher`` 默认参数
    m=64 MiB / t=3 / p=4 / hash_len=32 / salt_len=16，强于 OWASP 最低线）。
  * ``issue_access_token`` —— 登录成功后签发 JWT access token（claims 带 ``tenant_id`` /
    ``is_platform``，TTL 取 ``auth_access_token_ttl_seconds``）。P0 不发 refresh token。
  * ``decode_token`` —— 解码 + 校验。在底座 require(``sub``/``exp``/``iat``)之上**强制
    ``tenant_id`` 必需并做类型校验**，把 fail-closed 从隔离层延伸到认证层。

签名密钥 / 算法 / iss / aud 复用底座 ``get_auth_config()``（即 ``Settings.auth_jwt_*``）。

安全设计（经 Codex 安全 PK 收紧）：

  * **claim 类型校验**：PyJWT 的 ``options.require`` 只保证 claim 存在且非 ``None``，
    **不校验类型**。若不补校验，``tenant_id="42"``（字符串）会让 ORM 过滤拿字符串去比，
    ``is_platform="false"``（字符串）在 Python truthiness 下为真 → 误判平台超管、跨租户越权。
    故 ``decode_token`` 解码后强制 ``tenant_id`` 为正整数、``is_platform``（若存在）为 ``bool``，
    用 ``type(x) is int`` 而非 ``isinstance``（``bool`` 是 ``int`` 子类，``True`` 会被当 1 放行）。
  * **空 secret fail-fast**：PyJWT 用空字符串密钥 encode/decode 会"成功"（只发不安全警告），
    等于签发可伪造 token。``issue``/``decode`` 在 secret 为空时直接抛 ``TokenConfigError``，
    不依赖 ``Settings`` 的 ``auth_enabled=true`` 校验（那条只在开启鉴权时生效）。
  * **iss/aud 仅在 config 配置时写入/校验**：P0 默认空（等团队 SSO + Q4 决议）。access TTL 2h
    令"后续启用校验使旧 token 失效"的迁移成本可忽略，故此处不预埋固定值。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from admin_platform.core.auth import get_auth_config
from admin_platform.core.config import get_settings

logger = logging.getLogger("admin_platform.security")

# 进程级单例 —— 默认参数即 ADR-F 选定值，无需调参（调参须先压测登录并发 × 单次内存）。
_password_hasher = PasswordHasher()

# decode 必需 claims：底座 sub/exp/iat 之上加 tenant_id（fail-closed 延伸到认证层）。
_REQUIRED_CLAIMS = ("sub", "exp", "iat", "tenant_id")


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


def issue_access_token(*, user_id: int, tenant_id: int, is_platform: bool, username: str) -> str:
    """签发 access token。claims = sub/tenant_id/is_platform/username/iat/exp(+iss/aud)。"""
    config = get_auth_config()
    secret = _require_secret(config.secret)
    ttl_seconds = get_settings().auth_access_token_ttl_seconds
    issued_at = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "is_platform": is_platform,
        "username": username,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl_seconds),
    }
    if config.issuer:
        claims["iss"] = config.issuer
    if config.audience:
        claims["aud"] = config.audience
    return jwt.encode(claims, key=secret, algorithm=config.algorithm)


# ---- access token 解码 + 校验 ----


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验 access token，返回 payload。

    抛 ``jwt.ExpiredSignatureError`` / ``jwt.InvalidTokenError`` —— 由 ``AuthMiddleware``
    据此分别映射 401 ``auth.TOKEN_EXPIRED`` / ``auth.TOKEN_INVALID``。tenant_id / is_platform
    的类型不合法亦抛 ``jwt.InvalidTokenError``（当作非法 token，而非服务端错误）。
    """
    config = get_auth_config()
    secret = _require_secret(config.secret)
    audience = config.audience if config.validate_audience else None
    issuer = config.issuer if config.validate_issuer else None
    payload: dict[str, Any] = jwt.decode(
        token,
        key=secret,
        algorithms=[config.algorithm],
        options={
            "require": list(_REQUIRED_CLAIMS),
            "verify_exp": True,
            "verify_iat": True,
            "verify_nbf": False,
            "verify_iss": config.validate_issuer,
            "verify_aud": config.validate_audience,
        },
        audience=audience,
        issuer=issuer,
    )
    _validate_claim_types(payload)
    return payload


def _validate_claim_types(payload: dict[str, Any]) -> None:
    """补 PyJWT require 不做的类型校验（防字符串 claim 绕过隔离 / 误判超管）。"""
    tenant_id = payload["tenant_id"]
    # type() is int —— 不用 isinstance，因为 bool 是 int 子类（True/False 会被当 1/0）。
    if type(tenant_id) is not int or tenant_id <= 0:
        raise jwt.InvalidTokenError("tenant_id 必须是正整数")
    # is_platform 可选（缺失由消费方默认 False）；存在则必须是 bool，
    # 否则 "false"/"0" 这类字符串在 truthiness 下为真 → 误判超管越权。
    if "is_platform" in payload and type(payload["is_platform"]) is not bool:
        raise jwt.InvalidTokenError("is_platform 必须是布尔值")
