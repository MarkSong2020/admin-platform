"""Redis-backed Idempotency middleware E2E — v0.4.12.

The unit suite (``tests/unit/test_idempotency.py``) covers the dispatch
logic with an in-memory ``_MemoryStore``. That misses the part the model
actually depends on: ``SET key value EX ttl NX`` against real Redis,
``GET`` returning the original bytes, TTL-driven expiry letting a stuck
lock recover, and the JSON encode/decode round-trip surviving an actual
Redis hop.

Requires ``docker compose --profile cache up -d --wait`` (or the GitHub
Actions ``redis`` service in db lane). Tests are marked
``redis_integration`` so the baseline ``make test-integration`` (which
sets ``APP_IDEMPOTENCY_ENABLED=false``) skips them; CI's db lane has
Redis up so it runs them automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from redis.asyncio import Redis

from admin_platform.core.config import get_settings
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.idempotency import (
    IDEMPOTENCY_KEY_REUSED_CODE,
    IDEMPOTENT_IN_FLIGHT_CODE,
    REPLAY_HEADER,
    IdempotencyMiddleware,
    RedisIdempotencyStore,
    idempotent,
)
from admin_platform.core.middleware import RequestIDMiddleware

pytestmark = [pytest.mark.integration, pytest.mark.redis_integration]


@pytest.fixture(autouse=True)
def _enable_idempotency_for_this_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override the integration-suite default that disables idempotency."""
    monkeypatch.setenv("APP_IDEMPOTENCY_ENABLED", "true")
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Real Redis connection. Default: skip on connection failure (lets local
    devs run the broader suite without bringing Redis up). CI sets
    ``STRICT_REDIS_INTEGRATION=1`` to convert the skip into a hard fail —
    otherwise CI can stay green while the actual Redis-dependent tests never
    ran. See ``LOCAL_SETUP.md`` for the contract."""
    settings = get_settings()
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await client.ping()  # type: ignore[misc]
    except Exception as e:
        strict = os.environ.get("STRICT_REDIS_INTEGRATION", "").lower() in {"1", "true", "yes"}
        msg = f"Redis unavailable at {settings.redis_url}: {e}"
        if strict:
            pytest.fail(
                msg + " — STRICT_REDIS_INTEGRATION=1 is set; refuse to silently skip "
                "(check `docker compose --profile cache up -d --wait`)."
            )
        pytest.skip(msg)
    yield client
    await client.aclose()


class _Payload(BaseModel):
    name: str


def _app_with_short_lock(redis: Redis, lock_ttl_seconds: int = 30) -> FastAPI:
    """Build a minimal app with idempotency middleware wired to the real
    Redis client. The route deliberately sleeps a few ms so a concurrent
    burst can race on the in-flight lock."""
    app = FastAPI()
    app.add_middleware(
        IdempotencyMiddleware,
        store=RedisIdempotencyStore(redis),
        ttl_seconds=60,
        lock_ttl_seconds=lock_ttl_seconds,
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    call_count = {"n": 0}

    @app.post("/items")
    @idempotent
    async def create_item(payload: _Payload) -> dict[str, object]:
        call_count["n"] += 1
        await asyncio.sleep(0.01)  # let concurrent retries collide on the lock
        return {"name": payload.name, "call": call_count["n"]}

    app.state.call_count = call_count
    return app


def _unique_key() -> str:
    """Each test uses a fresh Idempotency-Key so Redis state from previous
    runs cannot influence the outcome (no global cleanup needed)."""
    return uuid.uuid4().hex


async def _async_client(app: FastAPI) -> AsyncClient:
    """httpx.AsyncClient + ASGITransport — runs in the SAME event loop as the
    pytest-asyncio fixtures, so the Redis client doesn't end up with futures
    attached to a different loop than the middleware."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_redis_replay_returns_cached_response(redis_client: Redis) -> None:
    app = _app_with_short_lock(redis_client)
    key = _unique_key()
    headers = {"Idempotency-Key": key}

    async with await _async_client(app) as client:
        first = await client.post("/items", json={"name": "alpha"}, headers=headers)
        second = await client.post("/items", json={"name": "alpha"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers[REPLAY_HEADER] == "true"
    assert second.json() == first.json()
    assert app.state.call_count["n"] == 1


async def test_redis_same_key_different_body_returns_422(redis_client: Redis) -> None:
    app = _app_with_short_lock(redis_client)
    key = _unique_key()
    headers = {"Idempotency-Key": key}

    async with await _async_client(app) as client:
        first = await client.post("/items", json={"name": "alpha"}, headers=headers)
        clash = await client.post("/items", json={"name": "beta"}, headers=headers)

    assert first.status_code == 200
    assert clash.status_code == 422
    body = clash.json()
    assert body["type"] == IDEMPOTENCY_KEY_REUSED_CODE
    assert body.get("request_id")  # RequestIDMiddleware wired
    assert app.state.call_count["n"] == 1  # handler did NOT run for the clash


async def test_redis_in_flight_lock_returns_409(redis_client: Redis) -> None:
    """Pre-seed an ``in_progress`` lock that matches what the middleware
    would compute, then prove the second caller gets 409 and the handler
    is not invoked."""
    key = _unique_key()
    body = b'{"name":"alpha"}'
    body_hash = hashlib.sha256(body).hexdigest()
    cache_key = f"idem:/items:{key}"

    await redis_client.set(
        cache_key,
        json.dumps({"state": "in_progress", "body_hash": body_hash}).encode(),
        ex=30,
    )

    app = _app_with_short_lock(redis_client)
    async with await _async_client(app) as client:
        response = await client.post(
            "/items",
            content=body,
            headers={"Idempotency-Key": key, "Content-Type": "application/json"},
        )

    assert response.status_code == 409
    assert response.json()["type"] == IDEMPOTENT_IN_FLIGHT_CODE
    assert app.state.call_count["n"] == 0


async def test_redis_lock_expiry_allows_retry(redis_client: Redis) -> None:
    """A stuck ``in_progress`` lock must let retries through once its TTL
    expires — otherwise a crashed handler would brick the key forever."""
    key = _unique_key()
    body = b'{"name":"alpha"}'
    body_hash = hashlib.sha256(body).hexdigest()
    cache_key = f"idem:/items:{key}"

    # Stuck lock with a 1-second TTL.
    await redis_client.set(
        cache_key,
        json.dumps({"state": "in_progress", "body_hash": body_hash}).encode(),
        ex=1,
    )

    app = _app_with_short_lock(redis_client)
    async with await _async_client(app) as client:
        first = await client.post(
            "/items",
            content=body,
            headers={"Idempotency-Key": key, "Content-Type": "application/json"},
        )
        assert first.status_code == 409

        await asyncio.sleep(1.2)  # let the lock expire

        second = await client.post(
            "/items",
            content=body,
            headers={"Idempotency-Key": key, "Content-Type": "application/json"},
        )
        assert second.status_code == 200
        assert second.json()["name"] == "alpha"


async def test_redis_replay_preserves_201_created_status(redis_client: Redis) -> None:
    """Generator 默认 POST `status_code=201`, 但本文件其余测试都用默认 200
    endpoint. 那条 _replay 路径上的 `status_code=stored["status_code"]` 没有
    integration 测试守门——未来谁误改 `_cache_and_return` 把 status_code 漏
    存, 重放会 fallback 到 200, 客户端按 201 分支会出错.

    本测试用 201 endpoint 显式锁定: 首次 + 重放 status 都是 201."""
    app = FastAPI()
    app.add_middleware(
        IdempotencyMiddleware,
        store=RedisIdempotencyStore(redis_client),
        ttl_seconds=60,
        lock_ttl_seconds=30,
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.post("/items", status_code=status.HTTP_201_CREATED)
    @idempotent
    async def create_item(payload: _Payload) -> dict[str, object]:
        return {"name": payload.name}

    key = _unique_key()
    headers = {"Idempotency-Key": key}
    async with await _async_client(app) as client:
        first = await client.post("/items", json={"name": "alpha"}, headers=headers)
        second = await client.post("/items", json={"name": "alpha"}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201, (
        f"Replay returned {second.status_code} instead of 201 — "
        "_cache_and_return likely dropped status_code from the stored payload."
    )
    assert second.headers[REPLAY_HEADER] == "true"
    assert second.json() == first.json()
