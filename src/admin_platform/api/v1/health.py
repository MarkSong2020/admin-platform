"""K8s probe 端点 —— ADR 0001 §6。

- ``/healthz``：liveness —— 进程活着就行，不查依赖。
- ``/readyz``：readiness —— 对配置的数据库跑真正的 ``SELECT 1``；启用
  幂等时还要对 Redis ``PING``。任何失败返 503 ``framework.NOT_READY``，
  让 K8s 把 pod 从负载均衡里摘掉。
- ``/startupz``：startup —— lifespan 完成 gate（app 开始接受 HTTP 流量后
  返 200）。重型自定义 init（ML 模型加载、cache 预热）应当在返 200 前
  检查 ``app.state.startup_complete`` 等 flag。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

from admin_platform.core.config import get_settings
from admin_platform.core.errors import AppError, ProblemDetail
from admin_platform.db.engine import get_engine

router = APIRouter(tags=["health"])

# /readyz 在 DB / Redis ping 失败时返 503 + ProblemDetail body。这里在 route
# 上声明，让 ``_custom_openapi`` 改写 schema，SDK 生成器才能看到类型化的
# not-ready 路径（否则 SDK 假设 /readyz 总是 200 + {"status":"ready"}，遇到
# 503 时会炸）。
_NOT_READY_RESPONSE: dict[int | str, dict[str, object]] = {503: {"model": ProblemDetail}}


async def db_ping() -> None:
    """用 ``SELECT 1`` ping 数据库。失败抛错。"""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def redis_ping(redis: Redis) -> None:
    """Ping Redis。失败抛错。

    只在 ``settings.idempotency_enabled`` 为 True 时调用 —— 否则 Redis
    不在关键路径上，它故障不能让 pod 翻成 not-ready。
    """
    # redis-py 7.x type stub 声明 ping() -> bool，但 asyncio 上下文里
    # 实际跑的是 awaitable 那一支；pyright 推断不出来。
    await redis.ping()  # type: ignore[misc]


@router.get("/healthz", operation_id="healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/startupz", operation_id="startupz")
async def startupz() -> dict[str, str]:
    """ADR §6 的 startup probe。

    FastAPI 在 ASGI lifespan startup 完成之前根本不处理 HTTP 请求 —— 所以
    请求能打到这个 handler，意味着 app 启动已完成。重型自定义 init 的服务
    应当覆盖此 handler，在返 200 之前检查 ``app.state.startup_complete``
    （或等价的 flag）。
    """
    return {"status": "started"}


@router.get("/readyz", operation_id="readyz", responses=_NOT_READY_RESPONSE)
async def readyz(request: Request) -> dict[str, str]:
    settings = get_settings()
    try:
        await db_ping()
        if settings.idempotency_enabled:
            # 启用幂等时 Redis 是关键依赖：丢失 Redis 会悄悄关闭去重，
            # 让金额扣减类 POST 失去保护。把 Redis 失败当作 not-ready 让
            # K8s 摘掉 pod，比放行不安全流量更稳。
            redis: Redis | None = getattr(request.app.state, "redis", None)
            if redis is not None:
                await redis_ping(redis)
    except Exception as e:
        # SECURITY：**绝不**在这里 ``str(e)`` —— SQLAlchemy OperationalError
        # 在 DB 挂时会把含 credential 的完整 DSN 字符串化，Redis 连接错也
        # 可能带 credential。
        errors = {"reason": type(e).__name__} if settings.debug else None
        raise AppError(
            code="framework.NOT_READY",
            title="Dependency unavailable",
            status_code=503,
            errors=errors,
        ) from e
    return {"status": "ready"}
