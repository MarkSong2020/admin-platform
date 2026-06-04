"""认证 HTTP 端点（Task 6）—— P0 仅 ``POST /api/v1/auth/login``。

登录是公开端点（免 token，见 ``auth_public_paths``）；refresh / 验证码下放 P1。
业务逻辑在 ``domains/auth/service.py``，本层只做 HTTP 入参/出参（分层：api 不写业务）。
"""

from __future__ import annotations

from fastapi import APIRouter

from admin_platform.core.errors import ProblemDetail
from admin_platform.domains.auth.schemas import LoginRequest, LoginResponse
from admin_platform.domains.auth.service import login

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 登录失败返 401 + ProblemDetail —— 在 route 声明让 _custom_openapi 改写 schema，
# SDK 生成器才能看到类型化的失败路径。
_LOGIN_FAILED_RESPONSE: dict[int | str, dict[str, object]] = {401: {"model": ProblemDetail}}


@router.post("/login", operation_id="auth_login", responses=_LOGIN_FAILED_RESPONSE)
async def login_endpoint(payload: LoginRequest) -> LoginResponse:
    return await login(payload.username, payload.password)
