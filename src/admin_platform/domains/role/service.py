"""Role service —— 业务用例层（RBAC 角色，抛 ``AppError``，错误码 ``role.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise（触发请求
事务回滚），不抛 HTTPException（分层契约 C3）。

业务不变式：
  * **code 全局唯一** —— create / update（改 code 时）用 ``find_by_code`` 预检，违反抛 409
    ``role.CODE_DUPLICATE``。DB 的 ``uq_roles_code`` 是竞态兜底：并发预检都通过时第二个
    INSERT 撞约束 → ``IntegrityError`` handler 按 ``models.py`` 注册映射翻成同一码。
"""

from __future__ import annotations

from admin_platform.core.errors import AUTH_FORBIDDEN_BY_ROLE, AppError
from admin_platform.core.pagination import compute_total_pages, resolve_sort
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.role.schemas import (
    RoleCreate,
    RoleListQuery,
    RolePage,
    RoleRead,
    RoleUpdate,
)

NOT_FOUND_CODE = "role.NOT_FOUND"
CODE_DUPLICATE_CODE = "role.CODE_DUPLICATE"

# 授权根字段（P0 提权防护，用户拍板 2026-06-13）：data_scope 决定角色的数据权限范围、
# status 决定角色是否生效——二者直接放大被绑用户的后端权限集（授权不缓存 Q8，改完下一请求即生效）。
# 收紧为仅超管可写：非超管即使持 system:role:edit（展示字段编辑权）也不得改这些字段，杜绝
# 「改 data_scope=all 自我提权」绕过 rbac_binding 已有的超管 gate（镜像 rbac_binding 的
# _require_super_admin 模式：service 层做授权决策、抛 AppError，不 import CurrentUser/fastapi）。
_ROLE_SECURITY_FIELDS = ("data_scope", "status")
# create 纵深防御的默认基线（与 schemas.RoleCreate 的 Field default 同源）：非超管 create 时
# 这些字段被设成非默认值即拦——避免「create 直接落库高权限角色」绕过 update gate。
_ROLE_CREATE_DEFAULTS = {"data_scope": "self", "status": "active"}


class RoleService:
    def __init__(self, repository: RoleRepository) -> None:
        self._repo = repository

    async def list_(self, query: RoleListQuery, *, page: int, size: int) -> RolePage:
        """offset 分页（ADR 0001 §7.5 envelope）。角色是全局配置，不受 data_scope 约束。

        排序在此层解析（resolve_sort 防注入：非法 order_by → 422）；过滤条件由 repository 构造。
        """
        order_by = resolve_sort(
            query.order_by,
            query.order,
            allowed=RoleRepository.SORT_ALLOWED,
            default=RoleRepository.SORT_DEFAULT,
            tie_break=RoleRepository.SORT_TIE_BREAK,
        )
        rows = await self._repo.list_paginated(query, page, size, order_by=order_by)
        total = await self._repo.count(query)
        return RolePage(
            items=[RoleRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=compute_total_pages(total, size),
        )

    async def get(self, item_id: int) -> RoleRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return RoleRead.model_validate(row)

    async def create(self, payload: RoleCreate, *, is_super_admin: bool) -> RoleRead:
        self._guard_security_fields_create(payload, is_super_admin=is_super_admin)
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)
        row = await self._repo.create(payload)
        return RoleRead.model_validate(row)

    async def update(self, item_id: int, payload: RoleUpdate, *, is_super_admin: bool) -> RoleRead:
        self._guard_security_fields_update(payload, is_super_admin=is_super_admin)
        existing = await self._repo.get(item_id)
        if existing is None:
            raise self._not_found(item_id)
        await self._check_code_unique(existing, payload)
        row = await self._repo.update(item_id, payload)
        if row is None:  # 并发删除兜底：预检后被他人删除
            raise self._not_found(item_id)
        return RoleRead.model_validate(row)

    @staticmethod
    def _guard_security_fields_update(payload: RoleUpdate, *, is_super_admin: bool) -> None:
        """UPDATE 关键修复：改任一授权根字段必须超管，否则 403（杜绝改 data_scope=all 自我提权）。"""
        if is_super_admin:
            return
        touched = payload.model_fields_set & set(_ROLE_SECURITY_FIELDS)
        if touched:
            raise _forbidden_security_fields()

    @staticmethod
    def _guard_security_fields_create(payload: RoleCreate, *, is_super_admin: bool) -> None:
        """CREATE 纵深防御：非超管把授权根字段设成非默认值即 403（默认值放行，不阻塞建普通角色）。"""
        if is_super_admin:
            return
        for field_name, default in _ROLE_CREATE_DEFAULTS.items():
            if getattr(payload, field_name) != default:
                raise _forbidden_security_fields()

    async def delete(self, item_id: int) -> None:
        ok = await self._repo.delete(item_id)
        if not ok:
            raise self._not_found(item_id)

    async def _check_code_unique(self, existing: object, payload: RoleUpdate) -> None:
        """改 code 且与现值不同时校验全局唯一（未改 code 跳过）。"""
        if "code" not in payload.model_fields_set or payload.code is None:
            return
        if payload.code == getattr(existing, "code", None):
            return
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Role not found",
            detail=f"id={item_id}",
            status_code=404,
        )

    @staticmethod
    def _duplicate(code: str) -> AppError:
        return AppError(
            code=CODE_DUPLICATE_CODE,
            title="Role code already exists",
            detail=f"code={code!r}",
            status_code=409,
        )


def _forbidden_security_fields() -> AppError:
    """授权根字段越权写的统一 403（P0 提权防护）。"""
    return AppError(
        code=AUTH_FORBIDDEN_BY_ROLE,
        title="Forbidden",
        detail="data_scope/status/perms 等授权根字段仅超级管理员可修改",
        status_code=403,
    )
