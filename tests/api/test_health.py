"""Health probe + request ID middleware + readiness DB ping behavior."""

import pytest
from fastapi.testclient import TestClient

from admin_platform.api.v1 import health
from admin_platform.core.config import get_settings
from admin_platform.main import create_app


@pytest.fixture(autouse=True)
def _stub_health_pings_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: DB + Redis pings both succeed. Individual tests override."""

    async def _ok_db() -> None:
        return None

    async def _ok_redis(_redis: object) -> None:
        return None

    monkeypatch.setattr(health, "db_ping", _ok_db)
    monkeypatch.setattr(health, "redis_ping", _ok_redis)


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # ADR §4: every response (success or error) must carry X-Request-ID so
    # callers can correlate logs across services. Middleware chain guarantee —
    # if this assertion ever fails, RequestIDMiddleware ordering broke.
    assert response.headers.get("X-Request-ID")


def test_startupz_returns_started(client: TestClient) -> None:
    """ADR §6: /startupz returns 200 once lifespan startup completes."""
    response = client.get("/startupz")
    assert response.status_code == 200
    assert response.json() == {"status": "started"}


def test_readyz_returns_ready_when_db_ping_succeeds(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_returns_503_when_db_ping_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom() -> None:
        raise ConnectionError("db down")

    monkeypatch.setattr(health, "db_ping", _boom)

    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["type"] == "framework.NOT_READY"
    assert body["title"] == "Dependency unavailable"
    assert body["status"] == 503
    assert body["request_id"]
    assert body["errors"] is None  # debug=False by default
    # ADR §4: error responses (5xx via exception handler) must still carry
    # the X-Request-ID header — log correlation is critical exactly when things
    # break. Guards against future middleware-chain refactors that bypass
    # RequestIDMiddleware on the error path.
    assert response.headers.get("X-Request-ID") == body["request_id"]


def test_readyz_returns_503_when_redis_ping_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.4.11: idempotency-enabled services treat Redis loss as not-ready
    so K8s pulls traffic before the de-dupe guarantee silently disappears."""

    async def _boom(_redis: object) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(health, "redis_ping", _boom)

    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["type"] == "framework.NOT_READY"
    # Same X-Request-ID header guard as the db_ping 503 case (different code
    # path — Redis ping wired separately via /readyz fail-closed for idem-on
    # services).
    assert response.headers.get("X-Request-ID") == body["request_id"]


def test_readyz_skips_redis_when_idempotency_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """idempotency_enabled=False removes Redis from the critical path —
    Redis being down should NOT flip the pod to not-ready."""
    monkeypatch.setenv("APP_IDEMPOTENCY_ENABLED", "false")
    get_settings.cache_clear()

    async def _redis_boom(_redis: object) -> None:
        raise ConnectionError("redis down (would not be ping'd)")

    monkeypatch.setattr(health, "redis_ping", _redis_boom)

    app = create_app()
    with TestClient(app) as c:
        response = c.get("/readyz")
    assert response.status_code == 200


def test_request_id_echoed_from_header(client: TestClient) -> None:
    """ADR §4: 合法 32-char hex 入站值必须透传。"""
    valid_hex = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = client.get("/healthz", headers={"X-Request-ID": valid_hex})
    assert response.headers["X-Request-ID"] == valid_hex


def test_request_id_invalid_header_is_dropped_and_regenerated(client: TestClient) -> None:
    """ADR §4: 非 hex 格式的入站值必须被丢弃, 服务端生成新 hex."""
    response = client.get("/healthz", headers={"X-Request-ID": "fixed-id-123"})
    request_id = response.headers["X-Request-ID"]
    assert request_id != "fixed-id-123"
    assert len(request_id) == 32
    assert all(c in "0123456789abcdef" for c in request_id)


def test_request_id_generated_when_missing(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.headers.get("X-Request-ID")


def test_request_id_is_32_char_hex_format(client: TestClient) -> None:
    """ADR 0001 §4: X-Request-ID is 32-char lowercase hex (W3C trace-id format)."""
    response = client.get("/healthz")
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert "-" not in request_id
    assert all(c in "0123456789abcdef" for c in request_id)


def test_404_returns_unified_error_shape(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    # ADR §3: 404 displays as framework.NOT_FOUND (not framework.HTTP_<code> fallback)
    assert body["type"] == "framework.NOT_FOUND"
    assert body["status"] == 404
    assert "title" in body
    assert "request_id" in body
    assert body["errors"] is None
