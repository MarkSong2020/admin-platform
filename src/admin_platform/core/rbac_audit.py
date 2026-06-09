"""RBAC 写操作审计的 api 层织入 helper（spec §13.3）—— 裸资源 CRUD 写路径统一 emit rbac_write。

绑定写在 ``domains/rbac_binding/service.py`` 内 emit（精确 metadata）；裸资源 CRUD（user/role/
menu/dept/post 的 create/update/delete）用本 helper 在 api 层织入：actor 来自 ``CurrentUser``，
target 来自返回资源（``.id`` + display）/ path id。成功与失败（``AppError``）都记，失败 re-raise
不吞。请求段（method/path/request_id）留 P2 中间件统一补（decision-log §3）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable  # Callable 用于 display 提取器

from admin_platform.audit.emit import emit_rbac_write
from admin_platform.audit.events import AuditActor, AuditTarget
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import AppError


def _actor(user: CurrentUser) -> AuditActor:
    return AuditActor(user_id=int(user.user_id), is_super_admin=user.is_super_admin)


def _opt(value: int | None) -> str | None:
    return str(value) if value is not None else None


async def audited_write[T](  # noqa: PLR0913 —— api 层审计织入 helper，target/display/status 全命名 kwargs
    user: CurrentUser,
    action: str,
    target_type: str,
    *,
    coro: Awaitable[T],
    target_id: int | None = None,
    display: Callable[[T], str | None] | None = None,
    success_status: int = 200,
) -> T:
    """await ``coro`` 并 emit ``rbac_write``（成功带 target/display，失败带 error_code 后 re-raise）。

    ``target_id`` 已知（update/delete 的 path id）时直接传；create 时为 None，从返回资源 ``.id`` 取。
    ``display`` 从返回资源提取（code/name/username）；delete 无返回资源则不传。
    """
    try:
        result = await coro
    except AppError as exc:
        emit_rbac_write(
            actor=_actor(user),
            action=action,
            target=AuditTarget(type=target_type, id=_opt(target_id)),
            status="failure",
            http_status=exc.status_code,
            error_code=exc.code,
        )
        raise
    resolved_id = target_id if target_id is not None else getattr(result, "id", None)
    emit_rbac_write(
        actor=_actor(user),
        action=action,
        target=AuditTarget(
            type=target_type,
            id=_opt(resolved_id),
            display=display(result) if display is not None else None,
        ),
        status="success",
        http_status=success_status,
    )
    return result
