"""JWT Bearer 鉴权中间件 —— ADR §5 落地。

Token 格式：``Authorization: Bearer <JWT>``，claims 必含 ``sub`` / ``exp`` / ``iat``。
iss/aud 校验可通过 ``APP_AUTH_JWT_ISSUER`` / ``APP_AUTH_JWT_AUDIENCE`` 开启，
默认关闭以等待团队 SSO 上线 + Q4 决议。

鉴权失败直接在 middleware 层返回 401，含 ADR §5 定义的错误码：
  * ``auth.TOKEN_INVALID`` — 签名无效 / 格式错误 / 缺必要 claims
  * ``auth.TOKEN_EXPIRED`` — exp 已过期

``request.state.user_id`` 在验证通过后设置，auth debug log 会带 user_id。
主 access log（``RequestIDMiddleware``）当前不含 user_id——后续在
``_EXTRA_FIELDS`` 已有白名单的前提下，只需 access log extra 加字段即可。

``get_optional_current_user()`` / ``require_current_user()`` 作为 FastAPI
``Depends`` 供业务 handler 获取当前用户上下文：

  * ``get_optional_current_user`` — fail-open：未鉴权返回空 CurrentUser
  * ``require_current_user`` — fail-closed：未鉴权直接返回 401

``get_current_user`` 保留为 ``get_optional_current_user`` 的别名（向后兼容）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from admin_platform.core import security
from admin_platform.core.config import get_settings
from admin_platform.core.errors import AUTH_TOKEN_EXPIRED, AUTH_TOKEN_INVALID, AppError

logger = logging.getLogger("admin_platform.auth")


# ---- Auth config ----


@dataclass(frozen=True, slots=True)
class AuthConfig:
    enabled: bool
    secret: str
    algorithm: str
    issuer: str
    audience: str
    public_paths: tuple[str, ...]

    @property
    def validate_issuer(self) -> bool:
        return bool(self.issuer)

    @property
    def validate_audience(self) -> bool:
        return bool(self.audience)


def get_auth_config() -> AuthConfig:
    s = get_settings()
    return AuthConfig(
        enabled=s.auth_enabled,
        secret=s.auth_jwt_secret,
        algorithm=s.auth_jwt_algorithm,
        issuer=s.auth_jwt_issuer,
        audience=s.auth_jwt_audience,
        public_paths=tuple(s.auth_public_paths),
    )


# ---- CurrentUser ----


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """从 JWT claims 提取的用户上下文，由 ``get_current_user()`` 注入。"""

    user_id: str  # sub claim
    sub: str = field(compare=False)  # 等于 user_id，保留给习惯 sub 字段的调用方
    scope: str = ""
    tenant_id: int | None = None  # 业务 token 必带；未鉴权 / optional 路径为 None
    is_platform: bool = False  # 平台超管 → 跨租户 bypass（缺省非超管，fail-safe）


# ---- AuthMiddleware ----

_AUTH_PROBLEM_TITLES = {
    AUTH_TOKEN_INVALID: "Token is invalid or malformed",
    AUTH_TOKEN_EXPIRED: "Token has expired",
}


def _problem_auth(
    request: Request, code: str, status_code: HTTPStatus, *, detail: str | None = None
) -> JSONResponse:
    """构造 auth 401 的 ProblemDetail 响应。

    request.state.request_id 由外层的 RequestIDMiddleware 在 auth 之前设置，
    因此即使 auth 拒绝也能在响应中返回 request_id。

    RFC 6750 §3：401 必须带 ``WWW-Authenticate: Bearer`` challenge header。
    """
    return JSONResponse(
        status_code=int(status_code),
        content={
            "type": code,
            "title": _AUTH_PROBLEM_TITLES[code],
            "status": int(status_code),
            "detail": detail,
            "instance": None,
            "request_id": getattr(request.state, "request_id", None),
            "trace_id": getattr(request.state, "trace_id", None),
            "errors": None,
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT Bearer 鉴权。非公开路由的每个请求必须携带有效 ``Authorization: Bearer <token>``。

    公开路径（``/healthz`` 等）与 ``auth_enabled=False`` 时不鉴权。
    """

    def __init__(self, app: Any, config: AuthConfig) -> None:
        super().__init__(app)
        self._config = config
        self._public_prefixes = config.public_paths

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # CORS preflight 由外层 CORSMiddleware 在 Auth 之前截获——
        # Auth 不需要放行 OPTIONS。详见 main.py 中间件注册顺序注释。
        if self._is_public_path(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _problem_auth(
                request,
                AUTH_TOKEN_INVALID,
                HTTPStatus.UNAUTHORIZED,
                detail="Missing or malformed Authorization header",
            )

        token = auth_header[7:]  # len("Bearer ") == 7

        try:
            payload = security.decode_token(token)
        except jwt.ExpiredSignatureError:
            logger.info("auth: token expired", extra={"path": request.url.path})
            return _problem_auth(request, AUTH_TOKEN_EXPIRED, HTTPStatus.UNAUTHORIZED)
        except jwt.InvalidTokenError as exc:
            logger.info(
                "auth: token invalid",
                extra={"path": request.url.path, "reason": str(exc)},
            )
            return _problem_auth(
                request,
                AUTH_TOKEN_INVALID,
                HTTPStatus.UNAUTHORIZED,
                detail="Token validation failed",
            )

        sub = payload["sub"]
        request.state.user_id = sub
        request.state.token_sub = sub
        request.state.token_scope = payload.get("scope", "")
        # tenant_id 是 decode_token 的必需 claim（缺失/类型非法已在上面 401）——直取、
        # 不软取，与隔离层 fail-closed 同口径。is_platform 可选，缺失默认非超管（fail-safe）。
        request.state.tenant_id = payload["tenant_id"]
        request.state.is_platform = payload.get("is_platform", False)

        response = await call_next(request)

        # 将 user_id 注入 access log extra。Note: ``RequestIDMiddleware`` 在
        # auth middleware 之前注册，它的 access log 还没执行，所以我们改不了
        # 那条 log。这里的 log 补充一条 auth 专用的 user-id 信息。
        logger.debug(
            "auth: user authenticated",
            extra={"path": request.url.path, "user_id": sub},
        )
        return response

    def _is_public_path(self, path: str) -> bool:
        return any(
            path == p or path.startswith(p + "/") or path.startswith(p + "?")
            for p in self._public_prefixes
        )


# ---- FastAPI dependency ----


def get_optional_current_user(request: Request) -> CurrentUser:
    """FastAPI ``Depends``：读当前用户上下文（fail-open）。

    auth middleware 未设置用户时返回空 ``CurrentUser``。
    适用于公开端点或同时支持鉴权/未鉴权的路径——handler 自行判断
    ``user.user_id`` 是否为空。

    用法::

        @router.get("/profile")
        async def profile(user: CurrentUser = Depends(get_optional_current_user)):
            if not user.user_id:
                return {"anonymous": True}
            return {"user_id": user.user_id}
    """
    return CurrentUser(
        user_id=getattr(request.state, "user_id", ""),
        sub=getattr(request.state, "token_sub", ""),
        scope=getattr(request.state, "token_scope", ""),
        tenant_id=getattr(request.state, "tenant_id", None),
        is_platform=getattr(request.state, "is_platform", False),
    )


def require_current_user(request: Request) -> CurrentUser:
    """FastAPI ``Depends``：读取当前用户上下文（fail-closed）。

    auth middleware 未设置用户时抛出 ``AppError(auth.TOKEN_INVALID, 401)``，
    由 framework 异常处理链路转为 ProblemDetail 响应，并带上 RFC 6750 §3
    要求的 ``WWW-Authenticate: Bearer`` challenge header——type / title /
    header 与 AuthMiddleware 的 ``_problem_auth`` 401 路径完全一致。
    适用于必须鉴权的端点。

    用法::

        @router.get("/orders")
        async def list_orders(user: CurrentUser = Depends(require_current_user)):
            return {"user_id": user.user_id}
    """
    user_id = getattr(request.state, "user_id", "")
    if not user_id:
        # 与 AuthMiddleware 的 _problem_auth 同口径：auth.TOKEN_INVALID + 401 +
        # WWW-Authenticate（ADR §5「未鉴权 → auth.TOKEN_INVALID」/ RFC 6750 §3）。
        raise AppError(
            code=AUTH_TOKEN_INVALID,
            title=_AUTH_PROBLEM_TITLES[AUTH_TOKEN_INVALID],
            detail="Authentication required",
            status_code=int(HTTPStatus.UNAUTHORIZED),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(
        user_id=user_id,
        sub=getattr(request.state, "token_sub", ""),
        scope=getattr(request.state, "token_scope", ""),
        tenant_id=getattr(request.state, "tenant_id", None),
        is_platform=getattr(request.state, "is_platform", False),
    )


# 保留旧名称 get_current_user 作为 get_optional_current_user 的别名，
# 避免破坏现有调用方。
get_current_user = get_optional_current_user
