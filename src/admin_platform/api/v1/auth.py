"""认证 HTTP 端点（Task 6）—— P0 仅 ``POST /api/v1/auth/login``。

登录是公开端点（免 token，见 ``auth_public_paths``）；refresh / 验证码下放 P1。
业务逻辑在 ``domains/auth/service.py``，本层只做 HTTP 入参/出参（分层：api 不写业务）。
"""

from __future__ import annotations

from fastapi import APIRouter, status

from admin_platform.core.errors import ProblemDetail
from admin_platform.domains.auth.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
)
from admin_platform.domains.auth.service import login, logout, refresh

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 登录失败返 401 + ProblemDetail —— 在 route 声明让 _custom_openapi 改写 schema，
# SDK 生成器才能看到类型化的失败路径。
_LOGIN_FAILED_RESPONSE: dict[int | str, dict[str, object]] = {401: {"model": ProblemDetail}}
# refresh 失败 / reuse：401 + ProblemDetail（auth.REFRESH_TOKEN_INVALID / REUSED）。
_REFRESH_FAILED_RESPONSE: dict[int | str, dict[str, object]] = {401: {"model": ProblemDetail}}


@router.post("/login", operation_id="auth_login", responses=_LOGIN_FAILED_RESPONSE)
async def login_endpoint(payload: LoginRequest) -> LoginResponse:
    return await login(payload.username, payload.password)


@router.post("/refresh", operation_id="auth_refresh", responses=_REFRESH_FAILED_RESPONSE)
async def refresh_endpoint(payload: RefreshRequest) -> LoginResponse:
    """轮换 refresh token → 新 access + 新 refresh（强制 rotation，spec §1.3）。"""
    return await refresh(payload.refresh_token)


@router.post("/logout", operation_id="auth_logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_endpoint(payload: LogoutRequest) -> None:
    """登出：撤销 refresh token 所在 family（幂等）。"""
    await logout(payload.refresh_token)
