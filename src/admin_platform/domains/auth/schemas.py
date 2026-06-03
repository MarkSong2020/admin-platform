"""登录 API 的 DTO（Task 6）。纯 Pydantic，不碰 ORM / sqlalchemy（分层契约 C5/C6）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求体。字段加长度上限：public 端点防超大输入放大 argon2 / DB 比较成本。"""

    tenant_code: str = Field(max_length=64, description="租户编码（tenants.code）")
    username: str = Field(max_length=64, description="用户名（租户内唯一）")
    password: str = Field(max_length=256, description="明文密码")


class LoginResponse(BaseModel):
    """登录成功响应。P0 只发 access token，无 refresh。"""

    access_token: str = Field(description="JWT access token")
    token_type: str = Field(default="bearer", description="RFC 6750 token 类型")
    expires_in: int = Field(description="access token 存活秒数")
