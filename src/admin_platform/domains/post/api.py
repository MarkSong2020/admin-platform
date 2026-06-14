"""Posts HTTP API —— /api/v1/posts 下的 CRUD 路由。

鉴权 + 授权（spec §3.2 默认 deny）：每个端点用 ``require_permission`` 守卫显式声明所需
权限点（对标若依 ``system:post:{action}``）。超管短路在依赖内最前（spec §2.3）。守卫即
基础设施层依赖（类似 ``require_current_user``），不破坏分层契约。

错误路径在 ``responses=`` 声明，SDK 生成器据此 emit 类型化错误类（ADR §1）：
  * 401 auth.TOKEN_INVALID         —— 未携带 / 无效 token
  * 403 auth.FORBIDDEN_BY_ROLE     —— 缺少所需权限点
  * 404 post.NOT_FOUND             —— get/update/delete 命中不存在的 id
  * 409 post.CODE_DUPLICATE        —— create/update 想用已存在 code
  * 422 framework.VALIDATION_FAILED —— Pydantic 拒绝 payload
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.config import get_settings
from admin_platform.core.errors import AppError, ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.core.permissions import require_permission
from admin_platform.core.rbac_audit import audited_write
from admin_platform.domains.post.deps import get_post_service
from admin_platform.domains.post.schemas import (
    PostCreate,
    PostImportSummary,
    PostListQuery,
    PostPage,
    PostRead,
    PostUpdate,
)
from admin_platform.domains.post.service import PostService

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/api/v1/posts", tags=["posts"])

ServiceDep = Annotated[PostService, Depends(get_post_service)]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:post:{action}：list/query/add/edit/remove。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_REMOVE))]
ImportGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_IMPORT))]
ExportGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_EXPORT))]

# 受守卫端点都可能返回 401（未登录）/ 403（缺权限）—— 声明进 OpenAPI。
AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
# 列表端点叠加 422：order_by 非 allowlist 字段 → framework.SORT_FIELD_INVALID（防注入拒绝）。
LIST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    422: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# PATCH：404（不存在）+ 409（code 重复）+ 422（校验）。
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
# DELETE：404（不存在）。
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# v0.4.9+ IdempotencyMiddleware 在 middleware 层就会拒绝以下 POST 情况：
#   400 framework.IDEMPOTENCY_KEY_INVALID        （key 超过 255 字符）
#   409 framework.IDEMPOTENT_RETRY_IN_FLIGHT     （同 key+body 仍在运行）
#   422 framework.IDEMPOTENCY_KEY_REUSED         （同 key 但 body 不同）
# 叠加业务 409 post.CODE_DUPLICATE（code 重复）。FastAPI 看不到这些状态码，
# 所以 generator 必须在 ``responses=`` 显式声明，否则 SDK 漏掉这些错误路径。
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
# 导入：413 文件过大 / 422 缺 multipart 字段（行级校验错误走 200+summary.errors 业务通道，非 422）。
IMPORT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    413: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
# 导出：422 超过行数上限 + 200 xlsx 二进制流 content —— Response 不带 response_model，FastAPI
# 默认不会给 200 声明 content，SDK（openapi-fetch）拿不到 blob 返回类型，故在此显式补上。
EXPORT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    422: {"model": ProblemDetail},
    200: {"content": {_XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}},
}


@router.get("", operation_id="posts_list", response_model=PostPage, responses=LIST_ERROR_RESPONSES)
async def list_posts(
    svc: ServiceDep,
    _user: ListGuard,
    query: Annotated[PostListQuery, Query()],
) -> PostPage:
    # page/size 折进 PostListQuery（query-model 与独立标量 page/size Query 并存时，标量令整个
    # model 形参无法从 query 填充，canonical 请求报 422「该模型参数 missing」——与 extra 策略无关，
    # query-model 实测并不 forbid 额外参数）；折进后仍以 query 参数形式暴露在 OpenAPI。
    return await svc.list_(query, page=query.page, size=query.size)


_UPLOAD_CHUNK = 64 * 1024


async def _read_within_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """流式读上传体，累计超 max_bytes 即 413——防超大 xlsx 整体读入内存 OOM（对抗审查 P0）。"""
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(_UPLOAD_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise AppError(
                code="post.EXCEL_TOO_LARGE",
                title="Excel 文件过大",
                detail=f"超过 {max_bytes} 字节上限",
                status_code=413,
            )
        chunks.append(chunk)
    return b"".join(chunks)


# 导入/导出在 /{item_id} **之前**注册——否则 "import"/"export" 被当作 item_id（int）触发 422。
@router.post(
    "/import",
    operation_id="posts_import",
    response_model=PostImportSummary,
    responses=IMPORT_ERROR_RESPONSES,
)
async def import_posts(
    svc: ServiceDep,
    user: ImportGuard,
    upload: Annotated[UploadFile, File(description="岗位 Excel（.xlsx），一步全有全无导入")],
) -> PostImportSummary:
    content = await _read_within_limit(upload, get_settings().excel_max_upload_size_bytes)
    return await audited_write(
        user,
        Permissions.SYSTEM_POST_IMPORT,
        "post",
        coro=svc.import_posts(content),
        # 审计 display 标注成功/失败计数——imported=0+errors 时审计可区分「未写入」（对抗审查 P1）。
        display=lambda summary: f"导入 {summary.imported} 条岗位，{len(summary.errors)} 处错误",
    )


@router.get("/export", operation_id="posts_export", responses=EXPORT_ERROR_RESPONSES)
async def export_posts(svc: ServiceDep, user: ExportGuard) -> Response:
    # 导出审计（对抗审查 R2）：全量导出岗位是数据外泄取证点，记「谁导出」（写操作之外的读取证链）。
    content = await audited_write(
        user,
        Permissions.SYSTEM_POST_EXPORT,
        "post",
        coro=svc.export_posts(),
        display=lambda data: f"导出岗位 Excel（{len(data)} 字节）",
    )
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="posts.xlsx"'},
    )


@router.get(
    "/{item_id}",
    operation_id="posts_get",
    response_model=PostRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_post(item_id: int, svc: ServiceDep, _user: QueryGuard) -> PostRead:
    return await svc.get(item_id)


# ADR §11：POST 默认幂等 —— 调用方可以用同一个 Idempotency-Key header 安全重试。
# 装饰器顺序 —— ``@idempotent`` 必须放**最内层**（紧贴 ``async def``），它是 marker；
# 外层守卫在它之上。详见 ``core/idempotency.py``；``tests/unit/test_idempotency.py`` 守门。
@router.post(
    "",
    operation_id="posts_create",
    response_model=PostRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_post(payload: PostCreate, svc: ServiceDep, user: AddGuard) -> PostRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_POST_ADD,
        "post",
        coro=svc.create(payload),
        display=lambda p: p.code,
        success_status=201,
    )


@router.patch(
    "/{item_id}",
    operation_id="posts_update",
    response_model=PostRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_post(
    item_id: int, payload: PostUpdate, svc: ServiceDep, user: EditGuard
) -> PostRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_POST_EDIT,
        "post",
        coro=svc.update(item_id, payload),
        target_id=item_id,
        display=lambda p: p.code,
    )


@router.delete(
    "/{item_id}",
    operation_id="posts_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_post(item_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_POST_REMOVE,
        "post",
        coro=svc.delete(item_id),
        target_id=item_id,
    )
