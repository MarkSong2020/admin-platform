"""User DTO —— /api/v1/users 的请求/响应形状。纯 Pydantic（C5/C6：不碰 models/sqlalchemy）。

安全（经 Codex 隔离 PK，沿用到单租户）：
  * **请求侧不接** id / password_hash / is_super_admin / created_at / updated_at——
    is_super_admin 是 CLI 专属（超级管理员 bootstrap）；时间戳由 DB 维护。客户端只能设
    username / password / nickname / status。
  * **响应侧 ``UserRead`` 不含 ``password_hash``**（绝不序列化口令哈希）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 账号状态取值（与其余 RBAC 域同源：dept/role/menu/post 都是 active/disabled）。
# provider/login 只认 "active" → 其余值视作停用；用 Literal + DB CheckConstraint 防脏状态。
StatusValue = Literal["active", "disabled"]


class UserCreate(BaseModel):
    """POST payload。id / is_super_admin / 时间戳不可由客户端设。"""

    username: str = Field(min_length=1, max_length=64, description="用户名（全局唯一）")
    password: str = Field(
        min_length=1, max_length=256, description="明文密码（入库前 argon2 哈希）"
    )
    nickname: str = Field(default="", max_length=64, description="昵称")
    dept_id: int | None = Field(default=None, description="所属部门ID(None=未分配)")


class UserUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。不支持改 username（唯一键）。"""

    model_config = ConfigDict(from_attributes=True)
    nickname: str | None = Field(default=None, max_length=64)
    status: StatusValue | None = Field(default=None, description="账号状态（active / disabled）")
    password: str | None = Field(
        default=None, min_length=1, max_length=256, description="传值则改密（重新哈希）"
    )
    dept_id: int | None = Field(default=None, description="所属部门ID(None=未分配)")


class UserRead(BaseModel):
    """响应 DTO —— **故意不含 password_hash**。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str
    status: str
    is_super_admin: bool
    dept_id: int | None


class UserPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[UserRead]
    page: int
    size: int
    total: int
    total_pages: int
