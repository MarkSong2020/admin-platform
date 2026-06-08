"""RBAC 前端契约 DTO —— getInfo / getRouters payload（spec §6.1 必冻字段）。

字段名按若依形状冻结（前端选 RuoYi-Vue3 零适配 / vben 薄适配）。``getRouters`` 路由 payload
由 ``domains.menu.routers.build_routers`` 产出（``RouterVO`` TypedDict），本模块只定 getInfo。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UserInfoUser(BaseModel):
    """getInfo 的 ``user`` 段（基础身份字段）。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str
    status: str
    is_super_admin: bool
    dept_id: int | None


class UserInfoResponse(BaseModel):
    """getInfo payload（§6.1 必冻）：``user`` + ``roles``（角色 code 数组）+ ``permissions``。

    超管：``roles=["superadmin"]`` + ``permissions=["*:*:*"]``（§2.4 展示语义，非安全判定）。
    非超管：真实角色 code 集 + 经 role_menus 派生的权限标识集。
    """

    user: UserInfoUser
    roles: list[str]
    permissions: list[str]
