"""登录 API 的 DTO（Task 6）。纯 Pydantic，不碰 ORM / sqlalchemy（分层契约 C5/C6）。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    """登录请求体。字段加长度上限：public 端点防超大输入放大 argon2 / DB 比较成本。"""

    username: str = Field(max_length=64, description="用户名（全局唯一）")
    password: str = Field(max_length=256, description="明文密码")
    captcha_id: str | None = Field(
        default=None, max_length=64, description="验证码ID（失败N次后需要）"
    )
    captcha_answer: str | None = Field(default=None, max_length=16, description="验证码答案")


class CaptchaResponse(BaseModel):
    """验证码响应（算术文本，spec §1.4）。"""

    captcha_id: str = Field(description="验证码ID（登录时回传）")
    question: str = Field(description="算术题（如 '3 + 5 = ?'）")
    expires_in: int = Field(description="验证码存活秒数")


class LoginResponse(BaseModel):
    """登录 / 轮换成功响应。P1.4 起含 refresh token（向后兼容新增可选字段）。"""

    access_token: str = Field(description="JWT access token")
    token_type: str = Field(default="bearer", description="RFC 6750 token 类型")
    expires_in: int = Field(description="access token 存活秒数")
    refresh_token: str | None = Field(default=None, description="opaque refresh token（轮换用）")
    refresh_expires_in: int | None = Field(default=None, description="refresh token 存活秒数")


class RefreshRequest(BaseModel):
    """轮换请求体。"""

    refresh_token: str = Field(max_length=512, description="opaque refresh token")


class LogoutRequest(BaseModel):
    """登出请求体。``all_devices`` 预留（P1.4 暂按 family 撤销）。"""

    refresh_token: str = Field(max_length=512, description="opaque refresh token")


class ChangePasswordRequest(BaseModel):
    """自助改密请求体（已登录用户改自己的密码，需验原密码）。

    强度分两层：``≥12 字符`` / 不含首尾空白在本 schema 层（Pydantic，422）；不等于用户名 +
    新≠旧在 service 层（需 user 上下文，抛 ``auth.PASSWORD_TOO_WEAK`` 422）。改密成功撤销该用户
    **全部**旧 refresh 会话并给当前会话重签新 token（响应复用 ``LoginResponse``，见 service.change_password）。
    """

    old_password: str = Field(max_length=256, description="当前密码（验证身份）")
    new_password: str = Field(min_length=12, max_length=256, description="新密码（≥12 字符）")

    @field_validator("new_password")
    @classmethod
    def _no_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("新密码不能含首尾空白")
        return value
