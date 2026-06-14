"""统一错误响应形状 —— 详见 ADR 0001 §1（RFC 9457 对齐）。

响应 body 字段::

    {
      "type":       "<service>.<ERROR_CODE>",          # AppError.code（如 payment.ORDER_NOT_FOUND）
      "title":      "<short type-level summary>",      # AppError.title（按错误码固定，i18n key 候选）
      "status":     <http status code>,                # 与 HTTP status line 冗余
      "detail":     "<instance-specific message>"|null,# AppError.detail（可含 id / 上下文）
      "instance":   null,                              # ADR baseline；未来：error-instance URI
      "request_id": "<32-char hex>"|null,              # 见 ADR §4
      "trace_id":   "<32-char hex>"|null,              # OTel 设置；middleware 集成前为 null
      "errors":     <any>|null                         # AppError.errors（字段级 / 结构化补充）
    }

生产环境永不返回 stack trace。业务错误继承 ``AppError``；未捕获异常由
通用 handler 兜住，包装成 ``framework.INTERNAL_ERROR`` 返回，仅当
``settings.debug`` 为 True 时才输出 ``errors`` 详情。
"""

from __future__ import annotations

import logging
import re
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from admin_platform.core.config import get_settings


class ProblemDetail(BaseModel):
    """ADR 0001 §1 错误响应形状（RFC 9457 对齐）。

    声明为 Pydantic model，让它进入 OpenAPI ``components.schemas``，
    SDK 生成器才能 emit 类型化的错误类。runtime payload 仍由 ``_payload()``
    构造；本 model 仅用于 schema 可见性。
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "payment.ORDER_NOT_FOUND",
                "title": "Order not found",
                "status": 404,
                "detail": "Order id=42 not found",
                "instance": None,
                "request_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                "errors": None,
            }
        }
    )

    type: str = Field(description="错误码，ADR §3 ``{service}.{ERROR_CODE}`` 格式")
    title: str = Field(description="简短的类型级摘要，不含 instance id")
    status: int = Field(description="HTTP 状态码（与 HTTP status line 冗余）")
    detail: str | None = Field(default=None, description="instance 级描述")
    instance: str | None = Field(
        default=None, description="error-instance URI（RFC 9457 §3.1.5）；baseline 为 null"
    )
    request_id: str | None = Field(description="32 字符 hex request id（ADR §4）")
    trace_id: str | None = Field(default=None, description="W3C trace-id；OTel 集成后填充")
    errors: Any | None = Field(default=None, description="字段级或结构化的额外上下文")


logger = logging.getLogger("admin_platform.errors")

# ADR §3 禁止 `ERROR_404` 式编码 —— 给常见 HTTP status 显式语义 code 名。
_HTTP_STATUS_CODES: dict[int, str] = {
    400: "framework.BAD_REQUEST",
    401: "framework.UNAUTHORIZED",
    403: "framework.FORBIDDEN",
    404: "framework.NOT_FOUND",
    405: "framework.METHOD_NOT_ALLOWED",
    406: "framework.NOT_ACCEPTABLE",
    409: "framework.CONFLICT",
    410: "framework.GONE",
    413: "framework.PAYLOAD_TOO_LARGE",
    415: "framework.UNSUPPORTED_MEDIA_TYPE",
    422: "framework.UNPROCESSABLE_CONTENT",
    429: "framework.TOO_MANY_REQUESTS",
    500: "framework.INTERNAL_ERROR",
    502: "framework.BAD_GATEWAY",
    503: "framework.SERVICE_UNAVAILABLE",
    504: "framework.GATEWAY_TIMEOUT",
}


def _http_code(status_code: int) -> str:
    """把 HTTP 状态码映射到 ADR §3 规范的语义 ``type``。"""
    return _HTTP_STATUS_CODES.get(status_code, f"framework.HTTP_{status_code}")


# ---- ADR §5 JWT Bearer 错误码 ----
AUTH_TOKEN_INVALID = "auth.TOKEN_INVALID"  # noqa: S105
AUTH_TOKEN_EXPIRED = "auth.TOKEN_EXPIRED"  # noqa: S105
AUTH_FORBIDDEN_BY_ROLE = "auth.FORBIDDEN_BY_ROLE"
AUTH_FORBIDDEN_BY_SCOPE = "auth.FORBIDDEN_BY_SCOPE"
# 账号停用（请求期校验，Codex 深审）：持有效 token 但账号 status != active → 403。
# 与 LOGIN_FAILED（登录期，401，防枚举）分开：此处账号身份已确认，是状态禁止而非凭证问题。
AUTH_ACCOUNT_DISABLED = "auth.ACCOUNT_DISABLED"
# 登录失败统一码（Task 6）：租户不存在/停用、用户不存在/停用、密码错一律此码 + 401，
# 不区分以防账号枚举（spec 字面写 admin.LOGIN_FAILED，本仓归入 auth.* 体系，与
# auth.TOKEN_* 一致；admin_platform.* 留给业务资源错误）。
AUTH_LOGIN_FAILED = "auth.LOGIN_FAILED"

# ---- P1.4 登录增强错误码（spec 2026-06-09）----
# refresh token 无效/过期/查无（统一不暴露细节，防探测）。
AUTH_REFRESH_TOKEN_INVALID = "auth.REFRESH_TOKEN_INVALID"  # noqa: S105
# refresh token reuse 检测命中（已轮换 token 再用 → 整个 family 撤销，token theft 信号）。
AUTH_REFRESH_TOKEN_REUSED = "auth.REFRESH_TOKEN_REUSED"  # noqa: S105
# 登录失败达阈值，要求验证码（Q14：验证码作纵深，失败 N 次后触发，非首登必填）。
AUTH_CAPTCHA_REQUIRED = "auth.CAPTCHA_REQUIRED"
# 验证码错误 / 过期 / 已消费。
AUTH_CAPTCHA_INVALID = "auth.CAPTCHA_INVALID"
# IP 维度限流触发（429 + Retry-After）。账号软锁仍走统一 LOGIN_FAILED 防枚举。
AUTH_LOGIN_RATE_LIMITED = "auth.LOGIN_RATE_LIMITED"
# 自助改密（change-password）：原密码错（已鉴权，故 400 非 401）+ 新密码不满足强度（422）。
AUTH_PASSWORD_INCORRECT = "auth.PASSWORD_INCORRECT"  # noqa: S105
AUTH_PASSWORD_TOO_WEAK = "auth.PASSWORD_TOO_WEAK"  # noqa: S105


# ----------------------------- IntegrityError 兜底映射 ----------------------------- #
# 业务 service 的 find_by_xxx 预检与 DB 写之间存在 race 窗口：两个并发请求
# 同时查到「不存在」，各自 INSERT，第二个撞 DB UniqueConstraint → asyncpg
# 抛 UniqueViolationError → SQLAlchemy 包成 IntegrityError。本 handler 把
# IntegrityError 兜底成 409，避免落到通用 Exception handler 退化成 500。
#
# 业务 domain 在 import 时通过 ``register_unique_constraint`` 注册自己的
# 约束名 → 业务错误码映射；未注册的约束走 framework.CONFLICT fallback。
_UNIQUE_CONSTRAINT_CODES: dict[str, tuple[str, str]] = {}

# Postgres 错误消息里的 constraint 名抽取（asyncpg 的 orig 有
# ``constraint_name`` 属性；其它 driver 可能只有字符串形式，所以双轨）。
_CONSTRAINT_RE = re.compile(r'constraint "([^"]+)"')


def register_unique_constraint(constraint_name: str, code: str, title: str) -> None:
    """业务 domain 注册「DB 唯一约束 → 业务错误码」映射。

    在 domain 的 ``models.py`` 模块级调用一次。framework 层的
    ``IntegrityError`` handler 据此把竞态撞约束的 500 翻译成有意义的
    409 业务错误码。

    示例（``domains/<domain>/models.py`` 末尾）::

        from admin_platform.core.errors import register_unique_constraint

        register_unique_constraint(
            "uq_users_username",
            "user.USERNAME_DUPLICATE",
            "Username already exists",
        )

    fail-fast（防注册表静默漂移）：同名重复注册**相同** ``(code, title)`` 幂等放行（容忍 models
    模块被多次 import）；同名注册**不同**值直接 ``RuntimeError``——否则 ``IntegrityError``→409 的业务码
    会随 import 顺序漂移，客户端可能收到错误业务码（拷贝建模块时漏改约束名的典型征兆）。
    """
    existing = _UNIQUE_CONSTRAINT_CODES.get(constraint_name)
    if existing is not None and existing != (code, title):
        raise RuntimeError(
            f"约束名 {constraint_name!r} 已注册为 {existing!r}，拒绝用 {(code, title)!r} 覆盖"
            "——同名不同码会让 IntegrityError→409 业务码随 import 顺序漂移；检查是否拷贝建模块时漏改约束名。"
        )
    _UNIQUE_CONSTRAINT_CODES[constraint_name] = (code, title)


def _extract_constraint_name(exc: IntegrityError) -> str | None:
    """从 SQLAlchemy IntegrityError 抽取数据库约束名。

    asyncpg 的 ``UniqueViolationError`` 有 ``constraint_name`` 属性；其它
    driver 没有时 fallback 解析 ``str(exc.orig)`` 里的 ``constraint "xxx"``。
    """
    orig = exc.orig
    if orig is not None and hasattr(orig, "constraint_name"):
        name = getattr(orig, "constraint_name", None)
        if isinstance(name, str) and name:
            return name
    if orig is not None:
        match = _CONSTRAINT_RE.search(str(orig))
        if match:
            return match.group(1)
    return None


class AppError(Exception):
    """业务 / 领域错误，对齐 ADR §1 RFC 9457 字段。

    Args:
        code: 错误码，必须遵循 ADR §3 ``{service}.{ERROR_CODE}``
            （如 ``payment.ORDER_NOT_FOUND``）。映射到响应 ``type``。
        title: 简短类型级摘要（不含 instance id）。映射到响应 ``title``。
        detail: 可选的 instance 级描述（可含 id / 上下文）。映射到响应 ``detail``。
        status_code: HTTP 状态码；默认 400。
        errors: 可选的结构化字段级错误。映射到响应 ``errors``。
        headers: 可选的响应 header（如 401 的 ``WWW-Authenticate: Bearer``、
            429 的 ``Retry-After``）。由 ``_app_error`` handler 透传到响应。
    """

    def __init__(  # noqa: PLR0913
        self,
        code: str,
        title: str,
        *,
        detail: str | None = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        errors: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(title)
        self.code = code
        self.title = title
        self.detail = detail
        self.status_code = status_code
        self.errors = errors
        self.headers = headers


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _trace_id(request: Request) -> str | None:
    """W3C trace-id 占位。OTel middleware 集成后由它填充。"""
    return getattr(request.state, "trace_id", None)


def _payload(  # noqa: PLR0913
    *,
    code: str,
    title: str,
    status_code: int,
    detail: str | None,
    request_id: str | None,
    trace_id: str | None,
    errors: Any = None,
) -> dict[str, Any]:
    return {
        "type": code,
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": None,
        "request_id": request_id,
        "trace_id": trace_id,
        "errors": errors,
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(
                code=exc.code,
                title=exc.title,
                status_code=exc.status_code,
                detail=exc.detail,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
                errors=exc.errors,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 透传 exc.headers：401 的 ``WWW-Authenticate: Bearer``（RFC 6750 §3）、
        # 405 的 ``Allow``、429 的 ``Retry-After`` 等 challenge/控制 header 都靠它
        # 才能到达客户端——否则 raise HTTPException(..., headers=...) 会被静默丢弃。
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(
                code=_http_code(exc.status_code),
                title=str(exc.detail),
                status_code=exc.status_code,
                detail=None,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
                errors=None,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # SECURITY（v0.4.13）：``exc.errors()`` 里每条都带 ``input`` 字段，
        # 是被拒掉的原始值 —— 会通过 422 body 把 password / API key /
        # token / PII 漏给调用方。``OBSERVABILITY.md`` 明确禁止这些字段
        # 出现在任何响应面，所以在框架边界把 ``input`` strip 掉。
        # （FastAPI 的 ``RequestValidationError`` 不是 Pydantic 原生，所以
        # 不能依赖 Pydantic 的 ``include_input=False`` 参数。）
        sanitised_errors = [{k: v for k, v in err.items() if k != "input"} for err in exc.errors()]
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            content=_payload(
                code="framework.VALIDATION_FAILED",
                title="Request validation failed",
                status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
                detail=None,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
                errors=sanitised_errors,
            ),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # service 层 find_by_xxx 预检与 DB 写之间的 race：两个并发请求
        # 同时通过预检 → 第二个撞 UniqueConstraint → 这里兜底。
        # 业务 domain 在 models.py 注册了约束名 → 业务码映射，能给出
        # typed 409；未注册的走 framework.CONFLICT。
        #
        # 约束名只进 log extra，不暴露在响应 body —— DB 内部 schema 名
        # （如 uq_users_username）不是对外契约。
        constraint = _extract_constraint_name(exc)
        if constraint is not None and constraint in _UNIQUE_CONSTRAINT_CODES:
            code, title = _UNIQUE_CONSTRAINT_CODES[constraint]
            logger.info(
                "integrity error mapped to business code",
                extra={
                    "request_id": _request_id(request),
                    "constraint": constraint,
                    "code": code,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
        else:
            code = "framework.CONFLICT"
            title = "Resource constraint violation"
            logger.warning(
                "unmapped integrity error",
                extra={
                    "request_id": _request_id(request),
                    "constraint": constraint,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
        return JSONResponse(
            status_code=HTTPStatus.CONFLICT,
            content=_payload(
                code=code,
                title=title,
                status_code=HTTPStatus.CONFLICT,
                detail=None,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
                errors=None,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled exception",
            extra={
                "request_id": _request_id(request),
                "method": request.method,
                "path": request.url.path,
            },
        )
        errors: Any = None
        if get_settings().debug:
            errors = {"type": exc.__class__.__name__, "args": [str(a) for a in exc.args]}
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_payload(
                code="framework.INTERNAL_ERROR",
                title="Internal server error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=None,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
                errors=errors,
            ),
        )
