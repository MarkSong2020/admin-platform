"""User DTO —— /api/v1/users 的请求/响应形状。纯 Pydantic（C5/C6：不碰 models/sqlalchemy）。

安全（经 Codex 隔离 PK，沿用到单租户）：
  * **请求侧不接** id / password_hash / is_super_admin / created_at / updated_at——
    is_super_admin 是 CLI 专属（超级管理员 bootstrap）；时间戳由 DB 维护。客户端只能设
    username / password / nickname / status。
  * **响应侧 ``UserRead`` 不含 ``password_hash``**（绝不序列化口令哈希）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """POST payload。id / is_super_admin / 时间戳不可由客户端设。"""

    username: str = Field(min_length=1, max_length=64, description="用户名（全局唯一）")
    password: str = Field(
        min_length=1, max_length=256, description="明文密码（入库前 argon2 哈希）"
    )
    nickname: str = Field(default="", max_length=64, description="昵称")


class UserUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。不支持改 username（唯一键）。"""

    model_config = ConfigDict(from_attributes=True)
    nickname: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=16, description="active / disabled 等")
    password: str | None = Field(
        default=None, min_length=1, max_length=256, description="传值则改密（重新哈希）"
    )


class UserRead(BaseModel):
    """响应 DTO —— **故意不含 password_hash**。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str
    status: str
    is_super_admin: bool


class UserPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[UserRead]
    page: int
    size: int
    total: int
    total_pages: int
