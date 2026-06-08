"""FastAPI 应用入口 — 暴露为 ``admin_platform.main:app``。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from redis.asyncio import Redis
from sqlalchemy import text

from admin_platform.api.v1.auth import router as auth_router
from admin_platform.api.v1.health import router as health_router
from admin_platform.core.auth import AuthMiddleware, get_auth_config
from admin_platform.core.config import get_settings
from admin_platform.core.errors import ProblemDetail, register_exception_handlers
from admin_platform.core.idempotency import IdempotencyMiddleware, RedisIdempotencyStore
from admin_platform.core.logging import configure_logging
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.observability import init_observability, shutdown_observability
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine, get_engine
from admin_platform.domains.dept.api import router as dept_router
from admin_platform.domains.menu.api import router as menu_router
from admin_platform.domains.post.api import router as post_router
from admin_platform.domains.role.api import router as role_router
from admin_platform.domains.role.provider import DbPermissionProvider
from admin_platform.domains.user.api import router as user_router

# ADR 0001 §1：这些状态码上的错误响应必须符合 ProblemDetail 形状。
# FastAPI 默认的 422 HTTPValidationError schema 在 OpenAPI 生成时被替换。
_PROBLEM_STATUS_CODES = ("400", "401", "403", "404", "409", "422", "429", "500", "503")


async def _eager_probe_dependencies(app: FastAPI) -> None:
    """ADR §6 + KNOWN_DEVIATIONS #5：不可达的 DB / Redis 必须 fail-fast。

    生产环境应当设置 ``APP_STARTUP_EAGER_CONNECT=true``，让不可达依赖在
    ASGI lifespan startup 阶段抛错 → uvicorn 非零退出 → K8s **不**把 pod
    标记为 ready（流量永远不会打到坏 pod）。默认 False 是为了本地开发与
    CI 不强依赖活的 PostgreSQL / Redis 才能 import app。
    """
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    redis: Redis | None = getattr(app.state, "redis", None)
    if redis is not None:
        # redis-py 7.x 的 type stub 声明 ping() -> bool，但 async 上下文里
        # 实际返回 awaitable；pyright 在 union arm 推断时会丢一条。
        await redis.ping()  # type: ignore[misc]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """ASGI lifespan，保证 startup-failure 与 shutdown 两条路径都干净释放
    每个已获取的资源。

    eager-probe 在**跑之前**就把 cleanup 注册到 stack，所以即使 probe 时
    DB / Redis 不可达抛错，``dispose_engine`` + ``redis.aclose`` 仍会在
    出 stack 时触发。v0.4.12 之前 probe 跑在 stack 之外，startup 期间的
    DB 短暂故障会泄漏 engine pool（uvicorn 退出 → 操作系统帮忙清，但
    "谁获取谁释放" 的模型坏了）。
    """
    configure_logging()
    settings = get_settings()
    init_observability(settings)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(lambda: shutdown_observability(settings))
        stack.push_async_callback(dispose_engine)
        redis: Redis | None = getattr(app.state, "redis", None)
        if redis is not None:
            stack.push_async_callback(redis.aclose)
        if get_settings().startup_eager_connect:
            await _eager_probe_dependencies(app)
        yield


def _custom_openapi(app: FastAPI) -> dict[str, Any]:
    """覆盖 OpenAPI schema，让 4xx/5xx 响应都声明 ProblemDetail（ADR §1）。

    FastAPI 对带 Pydantic body 的路由自动生成 422 ``HTTPValidationError``
    响应；运行时的 ``_validation_error`` handler 返回的是 ADR §1 形状。
    SDK 生成器必须看到后者 —— 本函数就是改写 OpenAPI spec。
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    components_root = schema.setdefault("components", {})
    components = components_root.setdefault("schemas", {})
    components["ProblemDetail"] = ProblemDetail.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    # ADR §5 JWT Bearer security scheme — component 已声明，auth middleware 已接入。
    # 服务级 ``security``（应用到所有 operation）刻意留空 —— 业务模块按路由
    # opt-in。iss/aud 校验可通过 ``APP_AUTH_JWT_ISSUER`` / ``APP_AUTH_JWT_AUDIENCE``
    # 开启，默认关闭以等待团队 SSO 上线 + Q4 决议。
    security_schemes = components_root.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "bearerAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT Bearer token (ADR §5; auth middleware in core/auth.py)",
        },
    )
    problem_ref = {"$ref": "#/components/schemas/ProblemDetail"}
    for path_item in schema.get("paths", {}).values():
        for op in path_item.values():
            if not isinstance(op, dict):
                continue
            responses = op.get("responses", {})
            for status_code in _PROBLEM_STATUS_CODES:
                resp = responses.get(status_code)
                if resp is None:
                    continue
                resp.setdefault("content", {}).setdefault("application/json", {})["schema"] = (
                    problem_ref
                )
    app.openapi_schema = schema
    return schema


def create_app() -> FastAPI:
    settings = get_settings()
    # 注意：不要传 debug=settings.debug —— Starlette 的 debug middleware 会
    # 把我们注册的通用 Exception handler 换成 HTML traceback 页。
    # settings.debug 用于控制 handler 内的错误细节暴露程度。
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )
    # 中间件注册顺序（Starlette add_middleware 后 add 的包住先 add 的）：
    #   客户 → RequestID（最外层）
    #        → CORS（截获 preflight，Auth 之前）
    #        → Auth（验 JWT）
    #        → Idempotency（POST 幂等）
    #        → 路由 handler
    if settings.idempotency_enabled:
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        app.state.redis = redis
        app.add_middleware(
            IdempotencyMiddleware,
            store=RedisIdempotencyStore(redis),
            ttl_seconds=settings.idempotency_ttl_seconds,
            lock_ttl_seconds=settings.idempotency_lock_ttl_seconds,
        )
    if settings.auth_enabled:
        auth_config = get_auth_config()
        app.add_middleware(AuthMiddleware, config=auth_config)
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(user_router)
    app.include_router(dept_router)
    app.include_router(role_router)
    app.include_router(menu_router)
    app.include_router(post_router)
    # 业务 domain router 在此挂载（用 `make new-module` 生成 domain 后追加 include_router）。
    # RBAC PermissionProvider 接线（组合根）：core/permissions.get_permission_provider 默认
    # fail-closed 抛错（M2 占位），此处经 dependency_overrides 注入真实 DB 版 DbPermissionProvider。
    # 在组合根注入而非让 core import domains —— 避免 core→domains 耦合（M2 设计意图）。
    app.dependency_overrides[get_permission_provider] = DbPermissionProvider
    app.openapi = lambda: _custom_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
