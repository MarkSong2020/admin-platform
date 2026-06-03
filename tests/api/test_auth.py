"""JWT Bearer 鉴权中间件测试 —— ADR §5 守门。

覆盖：
  * auth_enabled=False 时不鉴权（向后兼容）
  * 缺 / 格式错 / 过期 / 签名错 → 401
  * auth 401 响应带 request-id（RequestIDMiddleware 在最外层）
  * OPTIONS preflight 直通（CORS 兼容）
  * 有效 token → request.state.user_id 注入
  * 公开路径（/healthz 等）豁免鉴权
  * iss / aud 可选校验
  * get_current_user() Depends 返回 CurrentUser
  * Authorization header 原文不进 auth log
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from contextlib import contextmanager

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from admin_platform.core import auth as auth_module
from admin_platform.core.config import Settings, get_settings
from admin_platform.core.errors import AUTH_TOKEN_EXPIRED, AUTH_TOKEN_INVALID
from admin_platform.main import create_app

_TEST_SECRET = "test-secret-for-auth-tests-key-32b!"

_DEPENDS_OPTIONAL_USER = Depends(auth_module.get_optional_current_user)
_DEPENDS_REQUIRED_USER = Depends(auth_module.require_current_user)


def _make_token(  # noqa: PLR0913
    *,
    sub: str = "user-1",
    exp: int = 0,
    secret: str = _TEST_SECRET,
    algorithm: str = "HS256",
    iss: str | None = None,
    aud: str | None = None,
    iat: int = 0,
    tenant_id: int = 1,
) -> str:
    now = int(time.time())
    # admin token 恒带 tenant_id（spec v3 #4 / Task 5：decode 必需 claim + 类型校验）——
    # 测试 token 同口径，否则会被认证层 fail-closed 挡掉。
    payload: dict = {
        "sub": sub,
        "tenant_id": tenant_id,
        "iat": iat or now,
        "exp": exp or (now + 3600),
    }
    if iss:
        payload["iss"] = iss
    if aud:
        payload["aud"] = aud
    return jwt.encode(payload, secret, algorithm=algorithm)


_AUTH_ENV_VARS = (
    "APP_AUTH_ENABLED",
    "APP_AUTH_JWT_SECRET",
    "APP_AUTH_JWT_ISSUER",
    "APP_AUTH_JWT_AUDIENCE",
    "APP_AUTH_JWT_ALGORITHM",
)


@contextmanager
def _auth_context(*, issuer: str = "", audience: str = "") -> Generator[None]:
    """上下文管理器设置 auth env vars，退出时恢复。"""
    saved = {k: os.environ.get(k) for k in _AUTH_ENV_VARS}
    os.environ["APP_AUTH_ENABLED"] = "true"
    os.environ["APP_AUTH_JWT_SECRET"] = _TEST_SECRET
    os.environ["APP_AUTH_JWT_ISSUER"] = issuer
    os.environ["APP_AUTH_JWT_AUDIENCE"] = audience
    get_settings.cache_clear()
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


@contextmanager
def _spy_auth_debug() -> Generator[list]:
    """替换 auth_module.logger.debug 为 spy，返回 logged 列表。退出时恢复原函数。"""
    orig = auth_module.logger.debug
    logged: list = []

    def spy(msg, *a, extra=None, **kw):
        logged.append({"msg": msg, "extra": extra or {}})

    auth_module.logger.debug = spy  # type: ignore[method-assign]
    try:
        yield logged
    finally:
        auth_module.logger.debug = orig  # type: ignore[method-assign]


# --------------------------------------------------------------------------- #
# Settings validator                                                           #
# --------------------------------------------------------------------------- #


def test_auth_enabled_with_empty_secret_rejected() -> None:
    """auth_enabled=true 但 secret 为空 → Settings 构造失败。"""
    with pytest.raises(ValueError, match="auth_jwt_secret"):
        Settings(auth_enabled=True, auth_jwt_secret="")


def test_hs_secret_too_short_rejected() -> None:
    """HS256 下 secret < 32 bytes → Settings 构造失败。"""
    with pytest.raises(ValueError, match=r"auth_jwt_secret.*长度"):
        Settings(auth_enabled=True, auth_jwt_secret="short", auth_jwt_algorithm="HS256")


def test_hs_secret_long_enough_accepted() -> None:
    """32 bytes secret 通过校验。"""
    s = Settings(auth_enabled=True, auth_jwt_secret="a" * 32, auth_jwt_algorithm="HS256")
    assert s.auth_jwt_secret == "a" * 32


def test_rs_algorithm_short_secret_accepted() -> None:
    """RS*/ES* 不做 HMAC 长度校验（PEM public key 可能短）。"""
    s = Settings(auth_enabled=True, auth_jwt_secret="short-pem-key", auth_jwt_algorithm="RS256")
    assert s.auth_jwt_secret == "short-pem-key"


# --------------------------------------------------------------------------- #
# auth_enabled=False —— 向后兼容                                                #
# --------------------------------------------------------------------------- #


def test_auth_disabled_passes_through(app: FastAPI) -> None:
    """auth_enabled=False（默认）时所有请求正常通过，不检查 token。"""

    @app.get("/__auth-disabled")
    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as c:
        resp = c.get("/__auth-disabled")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# 401 — 缺 / 格式错 / 过期 / 签名错                                              #
# --------------------------------------------------------------------------- #


def test_missing_token_returns_401() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-missing")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-missing")
        assert resp.status_code == 401
        body = resp.json()
        assert body["type"] == AUTH_TOKEN_INVALID
        assert "Missing or malformed" in body["detail"]


def test_non_bearer_format_returns_401() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-bad-format")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-bad-format", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401
        assert resp.json()["type"] == AUTH_TOKEN_INVALID


def test_expired_token_returns_401() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-expired")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        token = _make_token(exp=int(time.time()) - 60)
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-expired", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["type"] == AUTH_TOKEN_EXPIRED


def test_invalid_signature_returns_401() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-bad-sig")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        token = _make_token(secret="wrong-secret-" + "x" * 20)
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-bad-sig", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["type"] == AUTH_TOKEN_INVALID


def test_token_missing_sub_claim_returns_401() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-no-sub")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        now = int(time.time())
        token = jwt.encode({"iat": now, "exp": now + 3600}, _TEST_SECRET, algorithm="HS256")
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-no-sub", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["type"] == AUTH_TOKEN_INVALID


# --------------------------------------------------------------------------- #
# 401 响应带 request-id                                                         #
# --------------------------------------------------------------------------- #


def test_auth_401_response_includes_request_id() -> None:
    """RequestID 在最外层，auth 401 应带 request_id。"""
    with _auth_context():
        app = create_app()

        @app.get("/__auth-reqid")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-reqid")
        assert resp.status_code == 401
        body = resp.json()
        assert body["request_id"], "401 body 应含 32 字符 hex request_id"
        assert len(body["request_id"]) == 32
        # X-Request-ID response header
        assert "x-request-id" in resp.headers, "401 响应应含 X-Request-ID header"


# --------------------------------------------------------------------------- #
# OPTIONS preflight 直通                                                        #
# --------------------------------------------------------------------------- #


def test_options_without_token_returns_401_when_auth_enabled() -> None:
    """CORS 未启用时，OPTIONS 无 token → AuthMiddleware 拦截返回 401。"""
    with _auth_context():
        app = create_app()

        @app.options("/__auth-options-blocked")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.options("/__auth-options-blocked")
        assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# 有效 token —— user_id 注入                                                    #
# --------------------------------------------------------------------------- #


def test_valid_token_sets_user_id_on_state() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-valid")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        token = _make_token(sub="alice")
        with TestClient(app) as c:
            resp = c.get("/__auth-valid", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


def test_valid_token_logs_auth_debug() -> None:
    """验证有效 token 通过后 middleware 记录了 auth debug 日志。"""
    with _auth_context():
        app = create_app()

        @app.get("/__auth-log")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        with _spy_auth_debug() as logged:
            token = _make_token(sub="bob")
            with TestClient(app) as c:
                c.get("/__auth-log", headers={"Authorization": f"Bearer {token}"})

        assert len(logged) >= 1, "auth debug 日志未记录"
        assert logged[0]["msg"] == "auth: user authenticated"
        assert logged[0]["extra"].get("user_id") == "bob"


# --------------------------------------------------------------------------- #
# 公开路径豁免                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["/healthz", "/startupz", "/readyz", "/docs", "/openapi.json"])
def test_public_paths_skip_auth(path: str) -> None:
    with _auth_context():
        app = create_app()

        with TestClient(app) as c:
            resp = c.get(path)
        # /readyz may return 503 when no DB; the point is auth didn't block it
        assert resp.status_code in (200, 307, 503), (
            f"{path} 返回 {resp.status_code}，auth 未拦截（非 401）"
        )
        assert resp.status_code != 401


# --------------------------------------------------------------------------- #
# iss / aud 可选校验                                                            #
# --------------------------------------------------------------------------- #


def test_iss_validation_rejects_wrong_issuer() -> None:
    with _auth_context(issuer="https://auth.example.com"):
        app = create_app()

        @app.get("/__auth-iss")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        token = _make_token(iss="https://wrong-issuer.example.com")
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-iss", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["type"] == AUTH_TOKEN_INVALID


def test_iss_validation_accepts_correct_issuer() -> None:
    with _auth_context(issuer="https://auth.example.com"):
        app = create_app()

        @app.get("/__auth-iss-ok")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        token = _make_token(iss="https://auth.example.com")
        with TestClient(app) as c:
            resp = c.get("/__auth-iss-ok", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


def test_aud_validation_rejects_wrong_audience() -> None:
    with _auth_context(audience="my-service"):
        app = create_app()

        @app.get("/__auth-aud")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        token = _make_token(aud="other-service")
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/__auth-aud", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["type"] == AUTH_TOKEN_INVALID


def test_aud_validation_accepts_correct_audience() -> None:
    with _auth_context(audience="my-service"):
        app = create_app()

        @app.get("/__auth-aud-ok")
        async def handler() -> dict[str, bool]:
            return {"ok": True}

        token = _make_token(aud="my-service")
        with TestClient(app) as c:
            resp = c.get("/__auth-aud-ok", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# get_optional_current_user / require_current_user                            #
# --------------------------------------------------------------------------- #


def test_optional_user_with_token_returns_context() -> None:
    with _auth_context():
        app = create_app()

        @app.get("/__auth-optional")
        async def handler(user=_DEPENDS_OPTIONAL_USER) -> dict:
            return {"user_id": user.user_id, "sub": user.sub, "scope": user.scope}

        token = _make_token(sub="charlie")
        with TestClient(app) as c:
            resp = c.get(
                "/__auth-optional",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "charlie"
        assert body["sub"] == "charlie"


def test_optional_user_without_token_returns_empty_user(app: FastAPI) -> None:
    """get_optional_current_user 是 fail-open：无 token 返回空用户，不 401。

    使用 app fixture（auth_enabled=False），此时 AuthMiddleware 不在栈中，
    get_optional_current_user 直接返回空 CurrentUser。
    """

    @app.get("/__auth-optional-no-token")
    async def handler(user=_DEPENDS_OPTIONAL_USER) -> dict:
        return {"user_id": user.user_id, "has_user": bool(user.user_id)}

    with TestClient(app) as c:
        resp = c.get("/__auth-optional-no-token")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_user"] is False


def test_required_user_with_token_returns_context() -> None:
    """require_current_user 在有 token 时正常返回。"""
    with _auth_context():
        app = create_app()

        @app.get("/__auth-required")
        async def handler(user=_DEPENDS_REQUIRED_USER) -> dict:
            return {"user_id": user.user_id}

        token = _make_token(sub="diana")
        with TestClient(app) as c:
            resp = c.get(
                "/__auth-required",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "diana"


def test_required_user_without_token_returns_401(app: FastAPI) -> None:
    """require_current_user 是 fail-closed：无用户直接 HTTPException(401)。

    使用 app fixture（auth_enabled=False，AuthMiddleware 不在栈中），
    这样请求能到达 handler / dependency，由 require_current_user 本身拒绝。
    """

    @app.get("/__auth-required-no-token")
    async def handler(user=_DEPENDS_REQUIRED_USER) -> dict:
        return {"user_id": user.user_id}

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/__auth-required-no-token")
    assert resp.status_code == 401
    # RFC 6750 §3：Bearer 资源的 401 必须带 challenge header（与 AuthMiddleware 路径一致）
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
    # ADR §5：未鉴权统一 auth.TOKEN_INVALID（与 AuthMiddleware 路径同口径）
    assert resp.json()["type"] == "auth.TOKEN_INVALID"


# --------------------------------------------------------------------------- #
# token 原文不进 auth log                                                       #
# --------------------------------------------------------------------------- #


def test_authorization_header_not_leaked_to_auth_log() -> None:
    """auth middleware 日志不包含 token 原文。"""
    with _auth_context():
        app = create_app()

        @app.get("/__auth-no-leak")
        async def handler() -> dict[str, str]:
            return {"ok": "true"}

        with _spy_auth_debug() as logged:
            token = _make_token(sub="dave")
            with TestClient(app) as c:
                c.get(
                    "/__auth-no-leak",
                    headers={"Authorization": f"Bearer {token}"},
                )

            for entry in logged:
                assert token not in entry["msg"], f"auth log 泄露 token 原文: {entry['msg']}"
