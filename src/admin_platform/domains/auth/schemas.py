"""登录 API 的 DTO（Task 6）。纯 Pydantic，不碰 ORM / sqlalchemy（分层契约 C5/C6）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求体。字段加长度上限：public 端点防超大输入放大 argon2 / DB 比较成本。"""

    username: str = Field(max_length=64, description="用户名（全局唯一）")
    password: str = Field(max_length=256, description="明文密码")


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
