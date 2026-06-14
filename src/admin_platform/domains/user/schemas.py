"""User DTO —— /api/v1/users 的请求/响应形状。纯 Pydantic（C5/C6：不碰 models/sqlalchemy）。

安全（经 Codex 隔离 PK，沿用到单租户）：
  * **请求侧不接** id / password_hash / is_super_admin / created_at / updated_at——
    is_super_admin 是 CLI 专属（超级管理员 bootstrap）；时间戳由 DB 维护。客户端只能设
    username / password / nickname / status。
  * **响应侧 ``UserRead`` 不含 ``password_hash``**（绝不序列化口令哈希）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 账号状态取值（与其余 RBAC 域同源：dept/role/menu/post 都是 active/disabled）。
# provider/login 只认 "active" → 其余值视作停用；用 Literal + DB CheckConstraint 防脏状态。
StatusValue = Literal["active", "disabled"]
# 排序方向取值（对标 RuoYi isAsc；与 core.pagination.OrderValue 同源字面量）。
OrderValue = Literal["asc", "desc"]


class UserListQuery(BaseModel):
    """用户列表过滤 / 排序参数（对标 RuoYi 用户管理查询；全可选）。

    纯输入 DTO：不进响应（不改 ``UserPage`` 形状）。``order_by`` 是逻辑字段名，repository 用
    allowlist 映射到 ORM Column（防注入）；非法字段 → service 抛 422。
    """

    username: str | None = Field(default=None, max_length=64, description="用户名模糊匹配")
    status: StatusValue | None = Field(default=None, description="账号状态（active / disabled）")
    dept_id: int | None = Field(default=None, description="所属部门ID（精确匹配）")
    created_at_begin: datetime | None = Field(default=None, description="创建时间起（含）")
    created_at_end: datetime | None = Field(default=None, description="创建时间止（含）")
    order_by: str | None = Field(
        default=None, max_length=64, description="排序字段（id / username / created_at）"
    )
    order: OrderValue = Field(default="desc", description="排序方向（asc / desc，默认 desc）")
    # 分页参数折进本模型：query-model 与独立标量 Query 参数混用时，FastAPI 不再把本模型展开为
    # query 参数，而是把整个模型参数当成必填且无法从 query 填充的字段，canonical 请求遂报 422
    # （错误是「该模型参数 missing」，非「page/size 被当额外参数拒」——query-model 实测并不
    # forbid 额外参数）。故 page/size 必须内联于此。约束与 core.pagination.PageQ/SizeQ 值同源。
    page: int = Field(
        default=1, ge=1, le=10000, description="页码（从 1 开始，上限 10000 防深分页 DoS）"
    )
    size: int = Field(default=20, ge=1, le=100, description="每页条数（上限 100）")


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
