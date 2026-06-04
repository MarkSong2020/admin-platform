"""单测：Argon2id 哈希 + access token 签发/解码（单租户）。

设计经 Codex 安全 PK 收紧（见 ADR-C/F）：
  * ``verify_password`` 对损坏 hash 返 ``False`` 不抛（登录边界不因存量 hash 损坏 500）。
  * ``decode_token`` require ``sub`` / ``exp`` / ``iat``，缺失即 ``InvalidTokenError``。
  * 空 secret fail-fast（拒绝用空密钥签发可伪造 token）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from admin_platform.core.config import get_settings
from admin_platform.core.security import (
    TokenConfigError,
    decode_token,
    hash_password,
    issue_access_token,
    verify_password,
)

_TEST_SECRET = "unit-test-secret-" + "x" * 32  # ≥32 bytes（HS256 要求，RFC 7518 §3.2）


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """每个用例注入测试 secret + 清 settings 缓存（避免空 secret fail-fast）。"""
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _TEST_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _encode(claims: dict) -> str:
    """用测试 secret 直接编码任意 claims —— 用于构造非法 token。"""
    return jwt.encode(claims, key=_TEST_SECRET, algorithm="HS256")


def _base_claims(**override: object) -> dict:
    now = datetime.now(UTC)
    claims: dict = {
        "sub": "7",
        "username": "alice",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(override)
    return claims


# ---- 密码哈希 ----


def test_password_roundtrip() -> None:
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_verify_corrupt_hash_returns_false() -> None:
    # 损坏 / 非 argon2 格式的 hash 在登录边界返 False，不抛（不 500）。
    assert verify_password("whatever", "not-a-valid-argon2-hash") is False


# ---- token 签发 + claims ----


def test_access_token_carries_claims() -> None:
    tok = issue_access_token(user_id=7, username="alice")
    p = decode_token(tok)
    assert p["sub"] == "7"
    assert p["username"] == "alice"


# ---- decode fail-closed：必需 claim ----


def test_decode_missing_sub_rejected() -> None:
    tok = _encode({k: v for k, v in _base_claims().items() if k != "sub"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tok)


def test_decode_expired_raises() -> None:
    now = datetime.now(UTC)
    tok = _encode(_base_claims(iat=now - timedelta(hours=2), exp=now - timedelta(hours=1)))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(tok)


# ---- 空 secret fail-fast ----


def test_empty_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", "")
    get_settings.cache_clear()
    with pytest.raises(TokenConfigError):
        issue_access_token(user_id=1, username="x")
