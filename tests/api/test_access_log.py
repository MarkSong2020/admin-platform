"""Access log emits one record per request with request_id / method / path / status / duration."""

import logging

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from admin_platform.core import middleware

_VALID_HEX = "4bf92f3577b34da6a3ce929d0e0e4736"


def test_access_log_contains_request_id_and_fields(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="admin_platform.access")
    response = client.get("/healthz", headers={"X-Request-ID": _VALID_HEX})
    assert response.status_code == 200

    access_records = [r for r in caplog.records if r.name == "admin_platform.access"]
    assert len(access_records) == 1
    record = access_records[0]
    assert getattr(record, "request_id", None) == _VALID_HEX
    # ADR §4 / §9: trace_id field must always be on the record — None when no
    # traceparent is present, hex when it is. Without this assertion the field
    # could silently disappear from access_log extras and only traceparent-path
    # tests would catch it.
    assert "trace_id" in vars(record)
    assert vars(record)["trace_id"] is None
    assert getattr(record, "method", None) == "GET"
    assert getattr(record, "path", None) == "/healthz"
    assert getattr(record, "status_code", None) == 200
    duration_ms = getattr(record, "duration_ms", None)
    assert isinstance(duration_ms, float)
    assert duration_ms >= 0


def test_access_log_generates_request_id_when_missing(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="admin_platform.access")
    response = client.get("/healthz")
    assert response.status_code == 200

    record = next(r for r in caplog.records if r.name == "admin_platform.access")
    request_id = getattr(record, "request_id", None)
    assert request_id
    assert response.headers["X-Request-ID"] == request_id


def test_invalid_inbound_request_id_is_replaced_with_fresh_hex(
    client: TestClient,
) -> None:
    """ADR §4: malformed X-Request-ID (not 32-char lowercase hex) must be dropped."""
    response = client.get("/healthz", headers={"X-Request-ID": "trace-abc"})
    echoed = response.headers["X-Request-ID"]
    assert echoed != "trace-abc"
    assert len(echoed) == 32
    assert "-" not in echoed
    assert all(c in "0123456789abcdef" for c in echoed)


_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_TRACEPARENT = f"00-{_TRACE_ID}-00f067aa0ba902b7-01"


def test_traceparent_trace_id_becomes_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """ADR §4: when W3C traceparent is present, its trace-id wins over any X-Request-ID."""
    caplog.set_level(logging.INFO, logger="admin_platform.access")
    response = client.get("/healthz", headers={"traceparent": _TRACEPARENT})
    assert response.headers["X-Request-ID"] == _TRACE_ID
    record = next(r for r in caplog.records if r.name == "admin_platform.access")
    assert getattr(record, "request_id", None) == _TRACE_ID
    assert getattr(record, "trace_id", None) == _TRACE_ID


def test_traceparent_wins_over_x_request_id(
    client: TestClient,
) -> None:
    """ADR §4: traceparent has priority over X-Request-ID (single-source ID)."""
    competing_hex = "0" * 32
    response = client.get(
        "/healthz",
        headers={"traceparent": _TRACEPARENT, "X-Request-ID": competing_hex},
    )
    assert response.headers["X-Request-ID"] == _TRACE_ID
    assert response.headers["X-Request-ID"] != competing_hex


def test_malformed_traceparent_falls_back_to_x_request_id(
    client: TestClient,
) -> None:
    """ADR §4: invalid traceparent does not poison the chain — fall through."""
    valid_hex = "1" * 32
    response = client.get(
        "/healthz",
        headers={"traceparent": "not-a-valid-traceparent", "X-Request-ID": valid_hex},
    )
    assert response.headers["X-Request-ID"] == valid_hex


def test_trace_id_appears_in_error_response_body(client: TestClient) -> None:
    """ADR §1: when traceparent is present, error responses carry trace_id."""
    response = client.get("/does-not-exist", headers={"traceparent": _TRACEPARENT})
    assert response.status_code == 404
    body = response.json()
    assert body["trace_id"] == _TRACE_ID
    assert body["request_id"] == _TRACE_ID


def test_trace_id_is_null_when_no_traceparent(client: TestClient) -> None:
    """ADR §1: trace_id stays null until OTel context is available."""
    response = client.get("/does-not-exist")
    body = response.json()
    assert body["trace_id"] is None
    assert body["request_id"]  # still set by middleware fallback


def test_span_id_is_null_when_otel_disabled(app, monkeypatch: pytest.MonkeyPatch) -> None:
    """OTel 未开启时 access log extra 的 span_id 为 None。"""
    captured: list = []

    def _spy_info(msg, *a, extra=None, **kw):
        captured.append(extra or {})

    monkeypatch.setattr(middleware.access_logger, "info", _spy_info)

    @app.get("/__span-test")
    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as c:
        c.get("/__span-test")

    assert len(captured) >= 1
    assert "span_id" in captured[0], "access log extra 应含 span_id 字段"
    assert captured[0]["span_id"] is None, "OTel 未开启时 span_id 应为 None"


def test_client_disconnect_records_499_in_access_log(app, monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.4.12: ``RequestIDMiddleware`` splits user cancellation from real
    server errors. ``ClientDisconnect`` raised by a handler must surface as
    status 499 in access logs (nginx convention) so 5xx error-rate dashboards
    are not polluted by users closing tabs.

    ``configure_logging`` resets root handlers during lifespan startup, so
    ``caplog`` may not see records depending on order. Spy directly on
    ``access_logger.info`` to assert the ``extra`` payload the middleware
    builds, regardless of where it ultimately gets emitted.
    """

    @app.get("/__disconnect")
    async def disconnect_endpoint() -> None:
        raise ClientDisconnect

    captured_extras: list[dict] = []

    original_info = middleware.access_logger.info

    def spy(msg, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_extras.append(kwargs.get("extra", {}))
        return original_info(msg, *args, **kwargs)

    monkeypatch.setattr(middleware.access_logger, "info", spy)

    with TestClient(app, raise_server_exceptions=False) as c:
        c.get("/__disconnect")

    assert captured_extras, "no access log was emitted at all"
    final = captured_extras[-1]
    assert final.get("status_code") == 499
    assert final.get("path") == "/__disconnect"
