"""Task 7：AuthMiddleware 解 token → request.state → CurrentUser 暴露 tenant_id/is_platform。

DB-free：路由只读 request.state（不查库）。验证认证层把 tenant_id/is_platform 透传到业务
handler，以及"缺 tenant_id 的 token 被 decode 必需校验挡在 401"（fail-closed 延伸到认证层）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.config import get_settings
from admin_platform.core.security import issue_access_token
from admin_platform.main import create_app

_SECRET = "task7-auth-ctx-secret-" + "x" * 32


@pytest.fixture
def auth_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    monkeypatch.setenv("APP_IDEMPOTENCY_ENABLED", "false")  # 避开 Redis，聚焦 auth
    get_settings.cache_clear()
    app = create_app()

    @app.get("/_ctx")
    async def _ctx(user: Annotated[CurrentUser, Depends(require_current_user)]) -> dict:
        return {
            "user_id": user.user_id,
            "tenant_id": user.tenant_id,
            "is_platform": user.is_platform,
        }

    yield app
    get_settings.cache_clear()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_tenant_token_flows_to_current_user(auth_app: FastAPI) -> None:
    tok = issue_access_token(user_id=7, tenant_id=42, is_platform=False, username="alice")
    with TestClient(auth_app) as client:
        resp = client.get("/_ctx", headers=_bearer(tok))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == "7"
    assert body["tenant_id"] == 42
    assert body["is_platform"] is False


def test_platform_token_sets_is_platform(auth_app: FastAPI) -> None:
    tok = issue_access_token(user_id=1, tenant_id=1, is_platform=True, username="root")
    with TestClient(auth_app) as client:
        resp = client.get("/_ctx", headers=_bearer(tok))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_platform"] is True


def test_token_missing_tenant_id_rejected(auth_app: FastAPI) -> None:
    # 手工签个缺 tenant_id 的 token → 中间件 decode（require tenant_id）→ 401，不进 handler。
    now = datetime.now(UTC)
    bad = jwt.encode(
        {"sub": "7", "iat": now, "exp": now + timedelta(hours=1)},
        key=_SECRET,
        algorithm="HS256",
    )
    with TestClient(auth_app) as client:
        resp = client.get("/_ctx", headers=_bearer(bad))
    assert resp.status_code == 401
