"""认证 HTTP 端点（Task 6）—— P0 仅 ``POST /api/v1/auth/login``。

登录是公开端点（免 token，见 ``auth_public_paths``）；refresh / 验证码下放 P1。
业务逻辑在 ``domains/auth/service.py``，本层只做 HTTP 入参/出参（分层：api 不写业务）。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Request, status
from redis.asyncio import Redis

from admin_platform.core.errors import AppError, ProblemDetail
from admin_platform.domains.auth.schemas import (
    CaptchaResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
)
from admin_platform.domains.auth.service import issue_captcha, login, logout, refresh

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 登录失败返 401 + ProblemDetail —— 在 route 声明让 _custom_openapi 改写 schema，
# SDK 生成器才能看到类型化的失败路径。429（IP 限流）/403（验证码）也声明。
_LOGIN_FAILED_RESPONSE: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
    429: {"model": ProblemDetail},
}
_REFRESH_FAILED_RESPONSE: dict[int | str, dict[str, object]] = {401: {"model": ProblemDetail}}
_CAPTCHA_RESPONSE: dict[int | str, dict[str, object]] = {503: {"model": ProblemDetail}}


def _require_redis(request: Request) -> Redis | None:
    """从 app.state 取 Redis（idempotency_enabled 时存在）；未部署则 None（限流/验证码降级）。"""
    return getattr(request.app.state, "redis", None)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", operation_id="auth_login", responses=_LOGIN_FAILED_RESPONSE)
async def login_endpoint(payload: LoginRequest, request: Request) -> LoginResponse:
    return await login(
        payload.username,
        payload.password,
        captcha_id=payload.captcha_id,
        captcha_answer=payload.captcha_answer,
        client_ip=_client_ip(request),
        redis=_require_redis(request),
    )


@router.get("/captcha", operation_id="auth_captcha", responses=_CAPTCHA_RESPONSE)
async def captcha_endpoint(request: Request) -> CaptchaResponse:
    """生成算术验证码（spec §1.4）。Redis 未部署 → 503（验证码功能不可用）。"""
    redis: Annotated[Redis | None, "from app.state"] = _require_redis(request)
    if redis is None:
        raise AppError(
            code="framework.SERVICE_UNAVAILABLE",
            title="Captcha unavailable",
            detail="验证码服务未启用（需配置 Redis）",
            status_code=int(HTTPStatus.SERVICE_UNAVAILABLE),
        )
    return await issue_captcha(redis)


@router.post("/refresh", operation_id="auth_refresh", responses=_REFRESH_FAILED_RESPONSE)
async def refresh_endpoint(payload: RefreshRequest) -> LoginResponse:
    """轮换 refresh token → 新 access + 新 refresh（强制 rotation，spec §1.3）。"""
    return await refresh(payload.refresh_token)


@router.post("/logout", operation_id="auth_logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_endpoint(payload: LogoutRequest) -> None:
    """登出：撤销 refresh token 所在 family（幂等）。"""
    await logout(payload.refresh_token)
