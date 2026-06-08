"""Menu DTO — /api/v1/menus 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

菜单树是邻接表：``parent_id`` 指父节点（None=根）。``menu_type`` 用 ``Literal['M','C','F']``
（目录 / 菜单 / 按钮，与 ``models.Menu`` 的 ``ck_menus_menu_type`` CheckConstraint 同源）；
``status`` 用 ``Literal``。菜单**无 code**（与 dept/role 不同，靠 id + 树结构标识）。

``MenuUpdate`` 全字段可选（PATCH merge 语义）；改 ``parent_id`` 触发 service 的移动防环校验。
``MenuTree`` 是带 ``children`` 的递归树形 DTO（菜单管理 UI / 后续树端点用）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MenuTypeValue = Literal["M", "C", "F"]
StatusValue = Literal["active", "disabled"]


class MenuCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    name: str = Field(min_length=1, max_length=64, description="菜单名称")
    menu_type: MenuTypeValue = Field(description="类型(M目录/C菜单/F按钮)")
    parent_id: int | None = Field(default=None, description="父菜单ID(None=根菜单)")
    path: str = Field(default="", max_length=255, description="路由地址(按钮类可空串)")
    component: str | None = Field(default=None, max_length=255, description="前端组件路径")
    perms: str | None = Field(
        default=None, max_length=128, description="权限标识(如system:user:list)"
    )
    icon: str = Field(default="", max_length=64, description="菜单图标")
    sort_order: int = Field(default=0, description="显示顺序")
    visible: bool = Field(default=True, description="是否显示(False=侧边栏隐藏)")
    status: StatusValue = Field(default="active", description="菜单状态（active / disabled）")


class MenuUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。改 ``parent_id`` 触发移动防环校验。"""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=64, description="菜单名称")
    menu_type: MenuTypeValue | None = Field(default=None, description="类型(M目录/C菜单/F按钮)")
    parent_id: int | None = Field(default=None, description="父菜单ID(None=根菜单)")
    path: str | None = Field(default=None, max_length=255, description="路由地址")
    component: str | None = Field(default=None, max_length=255, description="前端组件路径")
    perms: str | None = Field(default=None, max_length=128, description="权限标识")
    icon: str | None = Field(default=None, max_length=64, description="菜单图标")
    sort_order: int | None = Field(default=None, description="显示顺序")
    visible: bool | None = Field(default=None, description="是否显示")
    status: StatusValue | None = Field(default=None, description="菜单状态（active / disabled）")


class MenuRead(BaseModel):
    """响应 DTO —— 含树结构（parent_id）与生命周期时间戳。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: int | None
    name: str
    menu_type: str
    path: str
    component: str | None
    perms: str | None
    icon: str
    sort_order: int
    visible: bool
    status: str
    created_at: datetime
    updated_at: datetime


class MenuTree(MenuRead):
    """递归树形 DTO（菜单管理 UI / 后续树端点用）：``MenuRead`` + 子节点列表。"""

    children: list[MenuTree] = Field(default_factory=list)


class MenuPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[MenuRead]
    page: int
    size: int
    total: int
    total_pages: int
