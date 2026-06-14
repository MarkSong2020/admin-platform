"""Dict HTTP API —— /api/v1/dict 下的两资源路由（字典类型 + 字典数据）。

鉴权 + 授权（spec §3.2 默认 deny）：两资源共用 ``system:dict:{action}`` 权限点（对标若依）。写
操作经 ``audited_write`` 织入 rbac_write 审计（target_type 区分 dict_type / dict_data）。

消费契约 ``GET /data/type/{dict_type}``：按 type 取启用数据（前端渲染下拉）。声明在 ``/data/{id}``
**之前**（否则 "type" 撞 int 路径）。

错误路径在 ``responses=`` 声明（ADR §1）：401/403 + 404（不存在）+ 409（type 重复 / 删类型有数据 /
内置类型禁删 / data value 同类型重复）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.core.pagination import PageQ, SizeQ
from admin_platform.core.permissions import require_permission
from admin_platform.core.rbac_audit import audited_write
from admin_platform.domains.dict.deps import get_dict_service
from admin_platform.domains.dict.schemas import (
    DictDataCreate,
    DictDataPage,
    DictDataRead,
    DictDataUpdate,
    DictTypeCreate,
    DictTypePage,
    DictTypeRead,
    DictTypeUpdate,
)
from admin_platform.domains.dict.service import DictService

router = APIRouter(prefix="/api/v1/dict", tags=["dict"])

ServiceDep = Annotated[DictService, Depends(get_dict_service)]
KeywordQ = Annotated[str | None, Query(description="按字典名称 / 类型模糊过滤")]
TypeIdQ = Annotated[int | None, Query(description="按字典类型 ID 过滤数据")]

# 权限守卫（默认 deny + 超管短路）。两资源共用 system:dict:{action}。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_DICT_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_DICT_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_DICT_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_DICT_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_DICT_REMOVE))]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
}
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


# ==== 字典类型 dict_types ====================================================


@router.get(
    "/types",
    operation_id="dict_types_list",
    response_model=DictTypePage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_dict_types(
    svc: ServiceDep, _user: ListGuard, keyword: KeywordQ = None, page: PageQ = 1, size: SizeQ = 20
) -> DictTypePage:
    return await svc.list_types(keyword=keyword, page=page, size=size)


@router.get(
    "/types/{type_id}",
    operation_id="dict_types_get",
    response_model=DictTypeRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_dict_type(type_id: int, svc: ServiceDep, _user: QueryGuard) -> DictTypeRead:
    return await svc.get_type(type_id)


@router.post(
    "/types",
    operation_id="dict_types_create",
    response_model=DictTypeRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_dict_type(
    payload: DictTypeCreate, svc: ServiceDep, user: AddGuard
) -> DictTypeRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_DICT_ADD,
        "dict_type",
        coro=svc.create_type(payload),
        display=lambda t: t.type,
        success_status=201,
    )


@router.patch(
    "/types/{type_id}",
    operation_id="dict_types_update",
    response_model=DictTypeRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_dict_type(
    type_id: int, payload: DictTypeUpdate, svc: ServiceDep, user: EditGuard
) -> DictTypeRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_DICT_EDIT,
        "dict_type",
        coro=svc.update_type(type_id, payload),
        target_id=type_id,
        display=lambda t: t.type,
    )


@router.delete(
    "/types/{type_id}",
    operation_id="dict_types_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_dict_type(type_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_DICT_REMOVE,
        "dict_type",
        coro=svc.delete_type(type_id),
        target_id=type_id,
    )


# ==== 字典数据 dict_data =====================================================


@router.get(
    "/data",
    operation_id="dict_data_list",
    response_model=DictDataPage,
    responses=AUTH_ERROR_RESPONSES,
)
async def list_dict_data(
    svc: ServiceDep,
    _user: ListGuard,
    dict_type_id: TypeIdQ = None,
    page: PageQ = 1,
    size: SizeQ = 20,
) -> DictDataPage:
    return await svc.list_data(dict_type_id=dict_type_id, page=page, size=size)


# 消费契约：声明在 /data/{data_id} 之前（否则 "type" 撞 int 路径）。按 type 取启用数据。
@router.get(
    "/data/type/{dict_type}",
    operation_id="dict_data_by_type",
    response_model=list[DictDataRead],
    responses=AUTH_ERROR_RESPONSES,
)
async def list_dict_data_by_type(
    dict_type: str, svc: ServiceDep, _user: QueryGuard
) -> list[DictDataRead]:
    return await svc.list_data_by_type(dict_type)


@router.get(
    "/data/{data_id}",
    operation_id="dict_data_get",
    response_model=DictDataRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_dict_data(data_id: int, svc: ServiceDep, _user: QueryGuard) -> DictDataRead:
    return await svc.get_data(data_id)


@router.post(
    "/data",
    operation_id="dict_data_create",
    response_model=DictDataRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_dict_data(
    payload: DictDataCreate, svc: ServiceDep, user: AddGuard
) -> DictDataRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_DICT_ADD,
        "dict_data",
        coro=svc.create_data(payload),
        display=lambda d: d.value,
        success_status=201,
    )


@router.patch(
    "/data/{data_id}",
    operation_id="dict_data_update",
    response_model=DictDataRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_dict_data(
    data_id: int, payload: DictDataUpdate, svc: ServiceDep, user: EditGuard
) -> DictDataRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_DICT_EDIT,
        "dict_data",
        coro=svc.update_data(data_id, payload),
        target_id=data_id,
        display=lambda d: d.value,
    )


@router.delete(
    "/data/{data_id}",
    operation_id="dict_data_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_dict_data(data_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_DICT_REMOVE,
        "dict_data",
        coro=svc.delete_data(data_id),
        target_id=data_id,
    )
