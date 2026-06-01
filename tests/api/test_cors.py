"""CORS middleware behaviour — verifies settings actually flow to the running app.

These tests build the app under explicit env vars rather than reusing the
default ``client`` fixture, since CORS settings are read once at app construction.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from admin_platform.core.config import get_settings
from admin_platform.main import create_app


def _build_client(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


def _preflight(client: TestClient) -> dict[str, str]:
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    return {k.lower(): v for k, v in response.headers.items()}


def test_cors_preflight_allow_credentials_defaults_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _build_client(
        monkeypatch,
        APP_CORS_ALLOW_ORIGINS='["http://example.com"]',
    )
    headers = _preflight(client)
    assert headers.get("access-control-allow-origin") == "http://example.com"
    assert headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_allow_credentials_false_suppresses_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _build_client(
        monkeypatch,
        APP_CORS_ALLOW_ORIGINS='["http://example.com"]',
        APP_CORS_ALLOW_CREDENTIALS="false",
    )
    headers = _preflight(client)
    assert headers.get("access-control-allow-origin") == "http://example.com"
    assert "access-control-allow-credentials" not in headers
