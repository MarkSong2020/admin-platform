"""Task 5 单测：Argon2id 哈希 + access token 签发/解码（含认证层 fail-closed 类型校验）。

设计经 Codex 安全 PK 收紧（见 spec Task 5 + ADR-C/F）：
  * ``verify_password`` 对损坏 hash 返 ``False`` 不抛（登录边界不因存量 hash 损坏 500）。
  * ``decode_token`` 强制 ``tenant_id`` 必需 + **类型校验**（tenant_id 正整数、is_platform 必 bool）。
    PyJWT 的 ``require`` 只查存在性、不查类型；缺类型校验则 ``tenant_id="42"`` 会让 ORM 过滤
    比较字符串、``is_platform="false"`` 在 truthiness 下被误判超管 → 跨租户越权。
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
        "tenant_id": 42,
        "is_platform": False,
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


def test_access_token_carries_tenant_claims() -> None:
    tok = issue_access_token(user_id=7, tenant_id=42, is_platform=False, username="alice")
    p = decode_token(tok)
    assert p["sub"] == "7"
    assert p["tenant_id"] == 42
    assert p["is_platform"] is False
    assert p["username"] == "alice"


def test_platform_admin_token() -> None:
    tok = issue_access_token(user_id=1, tenant_id=1, is_platform=True, username="root")
    assert decode_token(tok)["is_platform"] is True


# ---- decode fail-closed：tenant_id 必需 + 类型校验 ----


def test_decode_missing_tenant_id_rejected() -> None:
    tok = _encode({k: v for k, v in _base_claims().items() if k != "tenant_id"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tok)


def test_decode_tenant_id_as_string_rejected() -> None:
    tok = _encode(_base_claims(tenant_id="42"))
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tok)


def test_decode_tenant_id_nonpositive_rejected() -> None:
    tok = _encode(_base_claims(tenant_id=0))
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tok)


def test_decode_tenant_id_bool_rejected() -> None:
    # bool 是 int 子类；True 不该被当 tenant_id=1 放行。
    tok = _encode(_base_claims(tenant_id=True))
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tok)


def test_decode_is_platform_string_rejected() -> None:
    # "false" 字符串在 truthiness 下为真 → 必须在 decode 层拦掉（防超管越权）。
    tok = _encode(_base_claims(is_platform="false"))
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tok)


def test_decode_is_platform_absent_ok() -> None:
    claims = {k: v for k, v in _base_claims().items() if k != "is_platform"}
    p = decode_token(_encode(claims))
    assert "is_platform" not in p  # decode 不注入默认；消费方自行 .get(..., False)


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
        issue_access_token(user_id=1, tenant_id=1, is_platform=False, username="x")
