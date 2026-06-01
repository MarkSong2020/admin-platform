"""IdempotencyMiddleware unit tests — in-memory store, no Redis required.

Covers the v0.4.9 B-plan upgrade: in-flight SET NX lock + same-key/diff-body
422 rejection (formerly: cache-replay only, which double-executed under
concurrent races and silently re-ran on body changes).
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from admin_platform.core.idempotency import (
    IDEMPOTENCY_KEY_INVALID_CODE,
    IDEMPOTENCY_KEY_REUSED_CODE,
    IDEMPOTENT_IN_FLIGHT_CODE,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    REPLAY_HEADER,
    IdempotencyMiddleware,
    IdempotencyStore,
    RedisIdempotencyStore,
    idempotent,
)


class _MemoryStore:
    """In-memory :class:`IdempotencyStore` stand-in for tests.

    Implements all three Protocol methods. ``set_nx`` is atomic enough for
    single-threaded TestClient; concurrency tests stub it explicitly.
    """

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def setex(self, key: str, ttl: int, value: bytes) -> None:
        del ttl
        self.data[key] = value

    async def set_nx(self, key: str, ttl: int, value: bytes) -> bool:
        del ttl
        if key in self.data:
            return False
        self.data[key] = value
        return True


class _Payload(BaseModel):
    name: str


def _make_app(store: IdempotencyStore | None = None) -> tuple[FastAPI, _MemoryStore]:
    store = store or _MemoryStore()
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware, store=store, ttl_seconds=60)

    call_count = {"value": 0}

    @app.post("/items")
    @idempotent
    def create_item(payload: _Payload) -> dict[str, Any]:
        call_count["value"] += 1
        return {"name": payload.name, "call": call_count["value"]}

    @app.post("/raw")
    def raw_post(payload: _Payload) -> dict[str, Any]:
        return {"name": payload.name}

    return app, store  # type: ignore[return-value]


def test_idempotent_decorator_marks_function() -> None:
    @idempotent
    def handler() -> None:
        pass

    assert getattr(handler, "_idempotent", False) is True


def test_idempotent_marker_survives_functools_wraps() -> None:
    """``functools.wraps`` 的 ``WRAPPER_UPDATES`` 含 ``__dict__``——所以
    ``_idempotent`` 会跟着 update 过去, ``@idempotent`` 放在 wraps wrapper
    之下时仍然有效. 本测试锁定这个事实, 防 ``idempotent`` 改造 (例如改成
    ``@dataclass`` field / class-level descriptor) 后默默破坏 wraps 透传."""

    def require_auth[F: Callable[..., Any]](func: F) -> F:
        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    @require_auth
    @idempotent
    def create() -> None:
        pass

    assert getattr(create, "_idempotent", False) is True, (
        "functools.wraps no longer propagates __dict__ (or @idempotent was "
        "refactored to not use a plain attribute). The decorator-order safety "
        "story in idempotency.idempotent docstring needs revisiting."
    )


def test_idempotent_marker_lost_under_bare_wrapper_without_wraps() -> None:
    """真陷阱: 业务装饰器**没有**用 ``functools.wraps`` (常见教程里"最简版"
    手写 wrapper) 时, ``_idempotent`` 会丢, middleware 不去重, 重试重复扣款.

        @require_auth_bare   # 裸 wrapper, 不 wraps
        @idempotent          # 加 _idempotent=True 到 *原* func
        async def create(...): ...

    最终 endpoint = ``require_auth_bare(create)``, 这个新函数没有
    ``_idempotent`` 属性, ``_route_is_idempotent(endpoint)`` 返回 False.

    守门方式: 本测试 + ``idempotent`` docstring "innermost-decorator 是最安全
    位置" + generator 模板注释三处. 测试如果开始 pass=True, 说明业务侧不应
    再写裸 wrapper, 或 idempotent 改成会主动 forward attribute 的实现."""

    def require_auth_bare[F: Callable[..., Any]](func: F) -> F:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)  # type: ignore[misc]

        return wrapped  # type: ignore[return-value]

    @require_auth_bare
    @idempotent
    def create() -> None:
        pass

    assert getattr(create, "_idempotent", False) is False


def test_post_without_key_passes_through_uncached() -> None:
    app, store = _make_app()
    client = TestClient(app)
    res = client.post("/items", json={"name": "x"})
    assert res.status_code == 200
    assert res.json() == {"name": "x", "call": 1}
    assert REPLAY_HEADER not in res.headers
    assert store.data == {}


def test_post_with_key_caches_and_replays() -> None:
    app, _store = _make_app()
    client = TestClient(app)
    headers = {"Idempotency-Key": "abc"}
    first = client.post("/items", json={"name": "x"}, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"name": "x", "call": 1}
    assert REPLAY_HEADER not in first.headers

    # Replay: same key, same body.
    second = client.post("/items", json={"name": "x"}, headers=headers)
    assert second.status_code == 200
    assert second.json() == {"name": "x", "call": 1}  # call counter unchanged
    assert second.headers[REPLAY_HEADER] == "true"


def test_idempotency_key_above_max_length_is_rejected_400() -> None:
    """v0.4.14: Stripe-style 255-char cap on Idempotency-Key. Without this
    cap a client can submit a 1 MB key and pay the linear cost on every
    Redis GET/SET, an asymmetric DoS vector against the cache."""
    app, store = _make_app()
    client = TestClient(app)
    oversize_key = "a" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1)

    res = client.post("/items", json={"name": "x"}, headers={"Idempotency-Key": oversize_key})

    assert res.status_code == 400
    body = res.json()
    assert body["type"] == IDEMPOTENCY_KEY_INVALID_CODE
    assert str(MAX_IDEMPOTENCY_KEY_LENGTH) in body["detail"]
    # Handler must NOT have run; store must remain untouched.
    assert store.data == {}


def test_idempotency_key_at_max_length_is_accepted() -> None:
    """Boundary case — exactly 255 chars passes through to handler."""
    app, _ = _make_app()
    client = TestClient(app)
    boundary_key = "a" * MAX_IDEMPOTENCY_KEY_LENGTH

    res = client.post("/items", json={"name": "x"}, headers={"Idempotency-Key": boundary_key})

    assert res.status_code == 200


def test_same_key_different_body_is_rejected_422() -> None:
    """B-plan: silently re-running on body change was unsafe for money-moving
    POSTs (caller bug masquerades as a new request). Now returns 422 with
    framework.IDEMPOTENCY_KEY_REUSED."""
    app, _ = _make_app()
    client = TestClient(app)
    headers = {"Idempotency-Key": "abc"}
    first = client.post("/items", json={"name": "x"}, headers=headers)
    assert first.status_code == 200
    assert first.json()["call"] == 1

    second = client.post("/items", json={"name": "y"}, headers=headers)
    assert second.status_code == 422
    body = second.json()
    assert body["type"] == IDEMPOTENCY_KEY_REUSED_CODE
    assert body["status"] == 422
    assert "different request body" in body["detail"]
    # Critical: the handler must NOT have run a second time.
    third = client.post("/items", json={"name": "x"}, headers=headers)
    assert third.json()["call"] == 1  # still 1 — the diff-body 422 didn't increment


def test_same_key_same_body_in_flight_returns_409() -> None:
    """Pre-existing in_progress lock + same body hash → 409 retry signal.

    Simulates concurrent retry by pre-seeding the store with an in_progress
    lock that matches what the middleware would compute for the request."""
    store = _MemoryStore()
    body = b'{"name":"x"}'
    body_hash = hashlib.sha256(body).hexdigest()
    store.data["idem:/items:abc"] = json.dumps(
        {"state": "in_progress", "body_hash": body_hash}
    ).encode()

    app, _ = _make_app(store)
    client = TestClient(app)
    res = client.post(
        "/items",
        content=body,
        headers={"Idempotency-Key": "abc", "Content-Type": "application/json"},
    )
    assert res.status_code == 409
    payload = res.json()
    assert payload["type"] == IDEMPOTENT_IN_FLIGHT_CODE
    assert payload["status"] == 409


def test_lock_release_via_completed_payload_allows_replay() -> None:
    """When a previous request finished and wrote state=completed, the next
    same-key/same-body retry must replay the cached response, not 409."""
    app, store = _make_app()
    client = TestClient(app)
    headers = {"Idempotency-Key": "abc"}

    first = client.post("/items", json={"name": "x"}, headers=headers)
    assert first.status_code == 200
    # The stored payload must already be in completed state at this point.
    stored = json.loads(store.data["idem:/items:abc"])
    assert stored["state"] == "completed"

    # Retry → replay (no 409, no double-execute).
    second = client.post("/items", json={"name": "x"}, headers=headers)
    assert second.status_code == 200
    assert second.headers[REPLAY_HEADER] == "true"
    assert second.json()["call"] == 1


def test_get_request_skips_idempotency() -> None:
    app, store = _make_app()

    @app.get("/healthcheck")
    @idempotent
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    client.get("/healthcheck", headers={"Idempotency-Key": "abc"})
    assert store.data == {}  # GET is HTTP-idempotent by spec; middleware ignores


def test_unmarked_post_route_is_not_cached() -> None:
    app, store = _make_app()
    client = TestClient(app)
    res = client.post("/raw", json={"name": "x"}, headers={"Idempotency-Key": "abc"})
    assert res.status_code == 200
    assert store.data == {}  # /raw has no @idempotent marker


def test_failure_response_keeps_lock_for_short_retry_window() -> None:
    """Non-2xx leaves the lock in place so the caller can retry once the
    transient failure clears (or wait for lock_ttl to expire). The cache
    payload stays in the in_progress state — never gets overwritten to
    completed for a 4xx/5xx."""
    store = _MemoryStore()
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware, store=store, ttl_seconds=60)

    @app.post("/fail")
    @idempotent
    def fail() -> dict[str, str]:
        raise HTTPException(status_code=400, detail="bad")

    client = TestClient(app)
    res = client.post("/fail", json={}, headers={"Idempotency-Key": "k"})
    assert res.status_code == 400
    # Lock was acquired but not overwritten with completed.
    stored = json.loads(store.data["idem:/fail:k"])
    assert stored["state"] == "in_progress"


@pytest.mark.asyncio
async def test_redis_store_swallows_errors_on_get() -> None:
    """RedisIdempotencyStore.get should log + return None when Redis raises."""

    class _BrokenRedis:
        async def get(self, key: str) -> None:
            raise ConnectionError("redis down")

        async def setex(self, key: str, ttl: int, value: bytes) -> None:
            raise ConnectionError("redis down")

        async def set(self, key: str, value: bytes, ex: int, nx: bool) -> None:
            raise ConnectionError("redis down")

    store = RedisIdempotencyStore(_BrokenRedis())  # type: ignore[arg-type]
    assert await store.get("anything") is None
    await store.setex("k", 60, b"v")  # must not raise


@pytest.mark.asyncio
async def test_redis_store_swallows_errors_on_set_nx() -> None:
    """B-plan: set_nx must fail-open (return False + log) when Redis is down.

    Middleware treats a False return as "lock contended"; combined with the
    follow-up get returning None it falls open to the handler — matches the
    legacy cache-miss behaviour for Redis outages."""

    class _BrokenRedis:
        async def set(self, key: str, value: bytes, ex: int, nx: bool) -> None:
            raise ConnectionError("redis down")

    store = RedisIdempotencyStore(_BrokenRedis())  # type: ignore[arg-type]
    assert await store.set_nx("k", 30, b"v") is False  # log + fail-open
