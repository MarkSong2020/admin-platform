"""Dept DTO — /api/v1/depts 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

部门树是邻接表：``parent_id`` 指父节点（None=根）。``code`` 全局唯一（业务编码）。
``DeptUpdate`` 全字段可选（PATCH merge 语义）；改 ``parent_id`` 会触发 service 的移动防环校验。
通过 ``exclude_unset`` 区分「未传该字段」与「显式传 None（置为根）」。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeptCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    name: str = Field(min_length=1, max_length=64, description="部门名称")
    code: str = Field(min_length=1, max_length=64, description="部门编码（全局唯一）")
    parent_id: int | None = Field(default=None, description="父部门ID(None=根部门)")
    sort_order: int = Field(default=0, description="显示顺序")
    leader: str | None = Field(default=None, max_length=64, description="负责人")
    phone: str | None = Field(default=None, max_length=32, description="联系电话")
    email: str | None = Field(default=None, max_length=128, description="邮箱")


class DeptUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。改 ``parent_id`` 触发移动防环校验。"""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=64, description="部门名称")
    code: str | None = Field(default=None, min_length=1, max_length=64, description="部门编码")
    parent_id: int | None = Field(default=None, description="父部门ID(None=根部门)")
    sort_order: int | None = Field(default=None, description="显示顺序")
    status: str | None = Field(default=None, max_length=16, description="active / disabled")
    leader: str | None = Field(default=None, max_length=64, description="负责人")
    phone: str | None = Field(default=None, max_length=32, description="联系电话")
    email: str | None = Field(default=None, max_length=128, description="邮箱")


class DeptRead(BaseModel):
    """响应 DTO —— 含树结构（parent_id）与生命周期时间戳。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: int | None
    name: str
    code: str
    sort_order: int
    status: str
    leader: str | None
    phone: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime


class DeptPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[DeptRead]
    page: int
    size: int
    total: int
    total_pages: int
