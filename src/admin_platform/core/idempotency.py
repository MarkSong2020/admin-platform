"""Idempotency-Key middleware —— ADR 0001 §11 / Open Q7 决议落地。

通过 ``@idempotent`` 装饰器 opt-in 的 POST 路由，会按客户端传的
``Idempotency-Key`` header + 请求 path 去重重试。行为遵循 Stripe 公开的
幂等契约，走两阶段存储：

  Phase 1（抢锁）
    首位 writer 用 ``SET NX EX=lock_ttl`` 写 ``idem:{path}:{client-key}``，
    payload ``{"state": "in_progress", "body_hash": sha256(body)}``。竞争
    失败方读现有值决定怎么响应。

  Phase 2（写完成）
    2xx 时把锁覆盖成 ``{"state": "completed", ...}``，TTL 改为更长的
    cache TTL（ADR §11 规定 24h）。非 2xx 不动锁，让 ``lock_ttl`` 自然
    到期 —— 调用方在瞬时故障解决后可以重试。

冲突结果（替代旧的「不同 body = 当新请求处理」语义，那个对金额扣减
类 POST 不安全）：

  * 同 key + 同 body + completed         → 重放缓存响应
                                            + ``Idempotent-Replayed: true``
  * 同 key + 同 body + 仍在飞            → ``409 Conflict``
                                            ``framework.IDEMPOTENT_RETRY_IN_FLIGHT``
  * 同 key + 不同 body                   → ``422 Unprocessable Content``
                                            ``framework.IDEMPOTENCY_KEY_REUSED``

存储后端：Redis（``redis.asyncio``）—— 分布式友好，多副本去重一致。
故障模式（任一都不应阻塞流量，统一 fail-open + log warning）：

  * Redis 在 ``set_nx`` 时不可达 → log warning，当「无幂等」处理转发到
    handler（与 legacy cache-miss 行为一致）
  * Redis 在 ``get`` 时不可达 → log warning，当 cache miss 处理
  * Redis 在 ``setex`` 时不可达 → log warning，响应仍正常返回

金额扣减场景的严格 at-most-once 需要 DB 级 idempotency 表（见
``doc/architecture/REQUEST_LIFECYCLE.md`` —— Redis 锁只防并发竞态，
扛不住 Redis 整体宕机）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any, Protocol

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match

logger = logging.getLogger("admin_platform.idempotency")

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replayed"

IDEMPOTENT_IN_FLIGHT_CODE = "framework.IDEMPOTENT_RETRY_IN_FLIGHT"
IDEMPOTENCY_KEY_REUSED_CODE = "framework.IDEMPOTENCY_KEY_REUSED"
IDEMPOTENCY_KEY_INVALID_CODE = "framework.IDEMPOTENCY_KEY_INVALID"

# Stripe 公开的 ``Idempotency-Key`` 上限。Redis 接受最大 512 MB 的 key，
# 但每次 GET/SET 都是 O(len) 处理，1 MB 的 key 等于放大 DoS 经济性。
# Stripe API 契约也是 255，镜像它让 cache_key 大小可预测。
MAX_IDEMPOTENCY_KEY_LENGTH = 255

# In-flight 锁 TTL —— 短到崩溃的 handler 不会长时间挡住重试，长到能盖住
# 最慢合法 handler 的运行时间。
DEFAULT_LOCK_TTL_SECONDS = 30

_STATE_IN_FLIGHT = "in_progress"
_STATE_COMPLETED = "completed"


class _PassThrough:
    """sentinel 单例，表示「本请求不在幂等层的射程内」。专门起一个 class
    （而不是用 ``object()``）让 pyright 在 isinstance 排除掉 pass-through
    和 rejection 分支后能把 gate 返回类型 narrow 到 ``str``。"""


_PASS_THROUGH = _PassThrough()


def idempotent[F: Callable[..., Any]](func: F) -> F:
    """标记一个路由 handler 为幂等 —— middleware 会去重重试。

    这是个 marker 装饰器：在 ``func`` 上直接设 ``_idempotent = True`` 并
    返回原对象（无 wrapping）。

    **最内层装饰器规则（推荐）**：把 ``@idempotent`` 紧贴 ``async def``
    放最里层。marker-on-original 是任何外层装饰器实现下都安全的唯一位置：

        @router.post("/items", responses=IDEMPOTENT_POST_ERROR_RESPONSES)
        @require_auth        # 任何业务 wrapper 放外层
        @idempotent          # 最内层，紧贴 ``async def``
        async def create_item(...): ...

    **为什么重要**：``@idempotent`` 在外层 wrapper 下面时，marker 能不能
    存活完全取决于 wrapper 怎么写：

    - ``functools.wraps`` 会更新 ``__dict__``（见 ``functools.WRAPPER_UPDATES``），
      ``_idempotent`` **能**存活 —— 这种情况 OK。
    - 简陋的 ``def wrapped(): ...; return wrapped``（没 ``wraps``）—— 教程
      复制粘贴里常见 —— **不会**拷贝自定义属性。router 拿到的 wrapper 没
      ``_idempotent``，``_route_is_idempotent(endpoint)`` 返 False，middleware
      跳过去重，重试会重跑副作用（如重复扣款）。

    把 ``@idempotent`` 放最底层从根上回避这个问题。

    守门：``tests/unit/test_idempotency.py``
    （``test_idempotent_marker_survives_functools_wraps`` /
    ``test_idempotent_marker_lost_under_bare_wrapper_without_wraps``）。
    """
    func._idempotent = True  # type: ignore[attr-defined]
    return func


class IdempotencyStore(Protocol):
    """:class:`IdempotencyMiddleware` 用的最小 async key-value 存储接口。"""

    async def get(self, key: str) -> bytes | None: ...
    async def setex(self, key: str, ttl: int, value: bytes) -> None: ...
    async def set_nx(self, key: str, ttl: int, value: bytes) -> bool: ...


class RedisIdempotencyStore:
    """Redis 后端的 :class:`IdempotencyStore`。错误只 log 不抛。"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> bytes | None:
        try:
            return await self._redis.get(key)
        except Exception:
            logger.warning("idempotency: redis get failed", exc_info=True, extra={"key": key})
            return None

    async def setex(self, key: str, ttl: int, value: bytes) -> None:
        try:
            await self._redis.setex(key, ttl, value)
        except Exception:
            logger.warning("idempotency: redis setex failed", exc_info=True, extra={"key": key})

    async def set_nx(self, key: str, ttl: int, value: bytes) -> bool:
        try:
            # redis.set(..., nx=True) 成功返 True，已存在返 None。
            result = await self._redis.set(key, value, ex=ttl, nx=True)
            return bool(result)
        except Exception:
            logger.warning("idempotency: redis set_nx failed", exc_info=True, extra={"key": key})
            return False


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """为带 ``@idempotent`` 标记的路由 cache POST 响应，配合 in-flight 锁。"""

    def __init__(
        self,
        app: Any,
        store: IdempotencyStore,
        ttl_seconds: int,
        lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> None:
        super().__init__(app)
        self._store = store
        self._ttl = ttl_seconds
        self._lock_ttl = lock_ttl_seconds

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Gate：本请求不在射程或 key header 缺/非法时早 bail 出来。把这段
        # 前奏放进一个 helper，让 ``dispatch`` 自己保持「锁 + cache 状态机」
        # 的焦点。
        gated = await self._gate(request)
        if isinstance(gated, _PassThrough):
            return await call_next(request)
        if isinstance(gated, Response):
            return gated
        client_key: str = gated

        # body 只读一次 —— 既要 hash 又要 replay 给下游。
        body = await request.body()
        body_hash = hashlib.sha256(body).hexdigest()
        # H4：键含认证主体（AuthMiddleware 在 request.state.user_id 设 sub；未鉴权/匿名为 anon）——
        # 否则跨用户重放他人 Idempotency-Key 会命中缓存、绕过路由级权限/停用检查。
        subject = getattr(request.state, "user_id", "") or "anon"
        cache_key = _build_cache_key(subject, request.url.path, client_key)

        # Phase 1：尝试抢 in-flight 锁。
        lock_payload = json.dumps({"state": _STATE_IN_FLIGHT, "body_hash": body_hash}).encode()
        acquired = await self._store.set_nx(cache_key, self._lock_ttl, lock_payload)
        if not acquired:
            conflict = await self._resolve_conflict(request, cache_key, body_hash)
            if conflict is not None:
                return conflict
            # Store 层故障（payload 为 None）→ fail-open，按 legacy cache-miss 走。
            logger.warning(
                "idempotency: lock contention with no stored payload; falling through",
                extra={"path": request.url.path, "key": client_key},
            )

        # Phase 2：跑真 handler。恢复 body —— Starlette 已经把 stream 消费完了。
        async def _receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[method-assign]

        response = await call_next(request)
        # 只 cache 成功响应；失败时不动锁，让调用方在底层问题解决后重试
        # （或者等短的 lock TTL 到期）。
        if HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            return await self._cache_and_return(cache_key, response, body_hash)
        return response

    async def _gate(self, request: Request) -> str | Response | _PassThrough:
        """返回三种之一：

        * ``_PASS_THROUGH`` — 不在射程内（method 不对、路由没标记、缺 key
          header）。调用方应当 ``call_next``。
        * ``Response`` — gate 阶段就拒掉了（key 太长）。
        * ``str`` — 通过校验的 client_key；调用方继续走锁阶段。
        """
        if request.method != "POST":
            return _PASS_THROUGH
        if not _route_is_idempotent(request):
            return _PASS_THROUGH

        client_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not client_key:
            logger.warning(
                "idempotent route invoked without Idempotency-Key header",
                extra={"path": request.url.path, "method": request.method},
            )
            return _PASS_THROUGH

        # v0.4.14：限 key 长度。Redis 接受最大 512 MB，但每次 GET/SET 都
        # O(len) 处理 —— 1 MB 的 key 让 DoS 经济性放大。Stripe API 契约
        # 是 255，镜像它让 cache_key 大小可预测。
        if len(client_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            return _problem_response(
                request,
                IDEMPOTENCY_KEY_INVALID_CODE,
                HTTPStatus.BAD_REQUEST,
                detail=(
                    f"Idempotency-Key length {len(client_key)} exceeds "
                    f"{MAX_IDEMPOTENCY_KEY_LENGTH} character limit"
                ),
            )
        return client_key

    async def _resolve_conflict(
        self, request: Request, cache_key: str, body_hash: str
    ) -> Response | None:
        """锁抢失败 —— 检查已存 payload 决定怎么响应。

        返回 ``None`` 表示「没找到 payload」（让调用方 fall-open），否则
        返回对应的 409 / 422 / replay 响应。
        """
        existing = await self._store.get(cache_key)
        if existing is None:
            return None
        try:
            stored = json.loads(existing)
        except json.JSONDecodeError:
            logger.warning(
                "idempotency: stored payload not JSON; treating as in-flight",
                extra={"cache_key": cache_key},
            )
            return _problem_response(request, IDEMPOTENT_IN_FLIGHT_CODE, HTTPStatus.CONFLICT)

        if stored.get("body_hash") != body_hash:
            return _problem_response(
                request,
                IDEMPOTENCY_KEY_REUSED_CODE,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                detail="Idempotency-Key already used with a different request body",
            )

        if stored.get("state") == _STATE_COMPLETED:
            return _replay(stored)

        # state == in_progress → 首位 writer 还在跑。
        return _problem_response(request, IDEMPOTENT_IN_FLIGHT_CODE, HTTPStatus.CONFLICT)

    async def _cache_and_return(
        self, cache_key: str, response: Response, body_hash: str
    ) -> Response:
        body_bytes = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body_bytes += chunk
        try:
            body_obj: Any = json.loads(body_bytes) if body_bytes else None
        except json.JSONDecodeError:
            body_obj = body_bytes.decode("utf-8", errors="replace")

        await self._store.setex(
            cache_key,
            self._ttl,
            json.dumps(
                {
                    "state": _STATE_COMPLETED,
                    "body_hash": body_hash,
                    "status_code": response.status_code,
                    "body": body_obj,
                    "headers": _serialisable_headers(response.headers),
                }
            ).encode("utf-8"),
        )
        return JSONResponse(
            status_code=response.status_code,
            content=body_obj,
            headers=_serialisable_headers(response.headers),
        )


def _replay(stored: dict[str, Any]) -> JSONResponse:
    headers = dict(stored.get("headers", {}))
    headers[REPLAY_HEADER] = "true"
    return JSONResponse(
        status_code=stored["status_code"],
        content=stored["body"],
        headers=headers,
    )


_PROBLEM_TITLES = {
    IDEMPOTENT_IN_FLIGHT_CODE: "Idempotent request still in flight",
    IDEMPOTENCY_KEY_REUSED_CODE: "Idempotency-Key reused with a different body",
    IDEMPOTENCY_KEY_INVALID_CODE: "Idempotency-Key is malformed",
}


def _problem_response(
    request: Request,
    code: str,
    status_code: HTTPStatus,
    *,
    detail: str | None = None,
) -> JSONResponse:
    """构造一个 RFC 9457 ProblemDetail 响应。

    BaseHTTPMiddleware 不在 FastAPI 的 ``exception_handler`` 链上，所以
    要在这里手动构造 ADR §1 形状。字段集**必须**与 ``core/errors.py``
    ``_payload()`` 保持同步。
    """
    return JSONResponse(
        status_code=int(status_code),
        content={
            "type": code,
            "title": _PROBLEM_TITLES[code],
            "status": int(status_code),
            "detail": detail,
            "instance": None,
            "request_id": getattr(request.state, "request_id", None),
            "trace_id": getattr(request.state, "trace_id", None),
            "errors": None,
        },
    )


def _route_is_idempotent(request: Request) -> bool:
    """把请求 match 到 app 里的某条 route，检查其 endpoint 上的 marker。"""
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            endpoint = getattr(route, "endpoint", None)
            return bool(getattr(endpoint, "_idempotent", False))
    return False


def _build_cache_key(subject: str, path: str, client_key: str) -> str:
    """``idem:<subject>:<path>:<client-key>`` —— subject = 认证主体 user_id（未鉴权/匿名为 anon）。

    H4：键含主体后，重放他人 ``Idempotency-Key`` 不再命中缓存——否则持有效 token 的低权限用户重放
    他人 key 可拿到完整响应体、绕过路由级 require_permission / 账号停用检查（中间件命中缓存即返回，
    不进路由）。body hash 在 payload 里（同 key + 不同 body 撞 422，不悄悄重跑）。"""
    return f"idem:{subject}:{path}:{client_key}"


def _serialisable_headers(headers: Any) -> dict[str, str]:
    """过滤成纯 ``str: str`` 映射。多值 header 折叠成最后一个。"""
    return {k: v for k, v in headers.items() if isinstance(k, str) and isinstance(v, str)}
