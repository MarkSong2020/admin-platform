"""Configs HTTP API —— /api/v1/configs 下的 CRUD + 消费契约路由。

鉴权 + 授权（spec §3.2 默认 deny）：每端点 ``require_permission`` 守卫（对标若依
``system:config:{action}``）。写操作经 ``audited_write`` 织入 rbac_write 审计。

消费契约 ``GET /value/{config_key}``：按 key **读穿 DB** 取最新值（热更新——无缓存）。
路由声明在 ``/{item_id}`` **之前**，否则 "value" 会先撞 int 路径（422）。

错误路径在 ``responses=`` 声明（ADR §1）：401/403/404 + 409（key 重复 / 内置禁删）。
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
from admin_platform.domains.config.deps import get_config_service
from admin_platform.domains.config.schemas import (
    ConfigCreate,
    ConfigPage,
    ConfigRead,
    ConfigUpdate,
    ConfigValueRead,
)
from admin_platform.domains.config.service import ConfigService

router = APIRouter(prefix="/api/v1/configs", tags=["configs"])

ServiceDep = Annotated[ConfigService, Depends(get_config_service)]
KeywordQ = Annotated[str | None, Query(description="按参数键名 / 名称模糊过滤")]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:config:{action}。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_CONFIG_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_CONFIG_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_CONFIG_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_CONFIG_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_CONFIG_REMOVE))]

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
    422: {"model": ProblemDetail},
}
# DELETE：404（不存在）+ 409（内置参数禁删 config.BUILTIN_READONLY）。
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
}
# POST：IdempotencyMiddleware 层 400/409/422 + 业务 409 config.KEY_DUPLICATE。
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get(
    "", operation_id="configs_list", response_model=ConfigPage, responses=AUTH_ERROR_RESPONSES
)
async def list_configs(
    svc: ServiceDep, _user: ListGuard, keyword: KeywordQ = None, page: PageQ = 1, size: SizeQ = 20
) -> ConfigPage:
    return await svc.list_(keyword=keyword, page=page, size=size)


# 消费契约：声明在 /{item_id} 之前（否则 "value" 撞 int 路径）。读穿 DB 取最新值（热更新）。
@router.get(
    "/value/{config_key}",
    operation_id="configs_get_value",
    response_model=ConfigValueRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_config_value(config_key: str, svc: ServiceDep, _user: QueryGuard) -> ConfigValueRead:
    return await svc.get_value(config_key)


@router.get(
    "/{item_id}",
    operation_id="configs_get",
    response_model=ConfigRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_config(item_id: int, svc: ServiceDep, _user: QueryGuard) -> ConfigRead:
    return await svc.get(item_id)


@router.post(
    "",
    operation_id="configs_create",
    response_model=ConfigRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_config(payload: ConfigCreate, svc: ServiceDep, user: AddGuard) -> ConfigRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_CONFIG_ADD,
        "config",
        coro=svc.create(payload),
        display=lambda c: c.config_key,
        success_status=201,
    )


@router.patch(
    "/{item_id}",
    operation_id="configs_update",
    response_model=ConfigRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_config(
    item_id: int, payload: ConfigUpdate, svc: ServiceDep, user: EditGuard
) -> ConfigRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_CONFIG_EDIT,
        "config",
        coro=svc.update(item_id, payload),
        target_id=item_id,
        display=lambda c: c.config_key,
    )


@router.delete(
    "/{item_id}",
    operation_id="configs_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_config(item_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_CONFIG_REMOVE,
        "config",
        coro=svc.delete(item_id),
        target_id=item_id,
    )
