"""RBAC 绑定 DTO —— 子资源 PUT 的全量替换请求 + 回显响应（纯 Pydantic，C5/C6 不碰 ORM）。

子资源 PUT 优于扩展 PATCH（decision-log 2026-06-09 §2）：绑定是全量替换语义，与 PATCH
merge 冲突。空数组 = 解绑全部（幂等）。响应 ``BindingRead`` 回显**去重后**最终 ids。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserRolesBinding(BaseModel):
    """PUT /users/{id}/roles —— 用户角色全量替换。"""

    role_ids: list[int] = Field(
        default_factory=list, description="角色 id 全集（全量替换，空=解绑全部）"
    )


class UserPostsBinding(BaseModel):
    """PUT /users/{id}/posts —— 用户岗位全量替换。"""

    post_ids: list[int] = Field(
        default_factory=list, description="岗位 id 全集（全量替换，空=解绑全部）"
    )


class RoleMenusBinding(BaseModel):
    """PUT /roles/{id}/menus —— 角色菜单全量替换。"""

    menu_ids: list[int] = Field(
        default_factory=list, description="菜单 id 全集（全量替换，空=清空）"
    )


class RoleDeptsBinding(BaseModel):
    """PUT /roles/{id}/depts —— 角色自定义数据范围部门全量替换。"""

    dept_ids: list[int] = Field(
        default_factory=list, description="自定义数据范围部门 id 全集（全量替换，空=清空）"
    )


class BindingRead(BaseModel):
    """绑定回显 —— 去重后最终 ids（有序），便于管理端确认去重结果。"""

    ids: list[int]
