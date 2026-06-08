"""Role DTO —— /api/v1/roles 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

``data_scope`` 用 ``Literal`` 限定为 5 个 ``ScopeType.value``（spec §4 数据权限 5 范围）：
与 ``models.Role`` 的 ``ck_roles_data_scope`` CheckConstraint、``authz.ScopeType`` 三处同源。
``tests/unit/test_role_schemas.py`` 守 Literal ↔ ScopeType 一致，防漂移。``RoleUpdate`` 全字段
可选（PATCH merge 语义）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# data_scope 取值（= authz.ScopeType 的 5 个 value）。schemas 不 import authz（保持 DTO 纯净，
# 且 Literal 需静态字面量），以测试守同源；列在此处便于 RoleCreate/Update 复用。
DataScopeValue = Literal["all", "custom_dept", "self_dept", "self_dept_and_below", "self"]
StatusValue = Literal["active", "disabled"]


class RoleCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    name: str = Field(min_length=1, max_length=64, description="角色名称")
    code: str = Field(min_length=1, max_length=64, description="角色编码（全局唯一）")
    data_scope: DataScopeValue = Field(default="self", description="数据权限范围（ScopeType 值）")
    sort_order: int = Field(default=0, description="显示顺序")
    status: StatusValue = Field(default="active", description="角色状态（active / disabled）")


class RoleUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。不支持改 code 之外字段的约束在 service。"""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=64, description="角色名称")
    code: str | None = Field(default=None, min_length=1, max_length=64, description="角色编码")
    data_scope: DataScopeValue | None = Field(
        default=None, description="数据权限范围（ScopeType 值）"
    )
    sort_order: int | None = Field(default=None, description="显示顺序")
    status: StatusValue | None = Field(default=None, description="角色状态（active / disabled）")


class RoleRead(BaseModel):
    """响应 DTO —— 含数据权限范围与生命周期时间戳。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    data_scope: str
    sort_order: int
    status: str
    created_at: datetime
    updated_at: datetime


class RolePage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[RoleRead]
    page: int
    size: int
    total: int
    total_pages: int
