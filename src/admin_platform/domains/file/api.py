"""Files HTTP API —— /api/v1/files：上传(multipart) / 流式下载 / 列表 / 元数据 / 删除。

鉴权 + 授权（默认 deny）：每端点 ``require_permission`` 守卫显式声明所需权限点（对标若依
``system:file:{action}``）。写操作（上传/删除）经 ``audited_write`` 织入审计；下载为读操作，
第一版不审计（与 list/get 一致，下载审计排期，spec §4）。

错误路径（SDK 据 ``responses=`` emit 类型化错误类）：
  * 401 auth.TOKEN_INVALID / 403 auth.FORBIDDEN_BY_ROLE —— 鉴权 / 授权
  * 404 file.NOT_FOUND          —— get/download/delete 命中不存在或已软删
  * 413 file.SIZE_EXCEEDED      —— 上传超大小上限
  * 415 file.EXTENSION_NOT_ALLOWED / file.CONTENT_TYPE_MISMATCH —— 扩展名 / 魔数校验
  * 422 file.EMPTY_FILE / framework.VALIDATION_FAILED —— 空文件 / 缺 multipart 字段
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from fastapi.responses import StreamingResponse

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.pagination import PageQ, SizeQ
from admin_platform.core.permissions import require_permission
from admin_platform.core.rbac_audit import audited_write
from admin_platform.domains.file.deps import get_file_service
from admin_platform.domains.file.schemas import FilePage, FileRead
from admin_platform.domains.file.service import FileService

router = APIRouter(prefix="/api/v1/files", tags=["files"])

ServiceDep = Annotated[FileService, Depends(get_file_service)]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:file:{action}：list/query/upload/download/remove。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_FILE_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_FILE_QUERY))]
UploadGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_FILE_UPLOAD))]
DownloadGuard = Annotated[
    CurrentUser, Depends(require_permission(Permissions.SYSTEM_FILE_DOWNLOAD))
]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_FILE_REMOVE))]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# 下载端点：复用 GET 的 401/403/404，再补 200 二进制流 content —— StreamingResponse 不带
# response_model，FastAPI 默认不会给 200 声明 content，SDK（openapi-fetch）拿不到 blob 返回类型。
DOWNLOAD_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **GET_ERROR_RESPONSES,
    200: {
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
    },
}
# 上传错误路径：413 超大 / 415 扩展名或魔数 / 422 空文件或缺 multipart 字段。
# 上传不挂 @idempotent（multipart body 哈希对大文件昂贵且为流，RuoYi 上传亦不幂等）。
UPLOAD_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    413: {"model": ProblemDetail},
    415: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}

_CHUNK_SIZE = 64 * 1024


async def _iter_upload(upload: UploadFile, chunk_size: int = _CHUNK_SIZE) -> AsyncIterator[bytes]:
    """UploadFile（SpooledTemporaryFile，大文件落盘不占内存）→ 异步分块流。"""
    while chunk := await upload.read(chunk_size):
        yield chunk


def _content_disposition(filename: str) -> str:
    """RFC 5987：ASCII 回退 + UTF-8 编码并存，兼容中文/特殊字符文件名。

    回退段剥离 CR/LF（防响应头注入/拆分）+ 剥离 ``"`` / ``;``（防 quoted-string 越界注入额外
    disposition 参数，对抗审查 P1）。``filename*=`` 段经 ``quote`` 百分号编码本身安全。
    """
    sanitized = filename.replace("\r", "").replace("\n", "")
    ascii_fallback = (
        sanitized.encode("ascii", "ignore").decode().replace('"', "").replace(";", "").strip()
        or "download"
    )
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(sanitized)}"


@router.get("", operation_id="files_list", response_model=FilePage, responses=AUTH_ERROR_RESPONSES)
async def list_files(
    svc: ServiceDep, _user: ListGuard, page: PageQ = 1, size: SizeQ = 20
) -> FilePage:
    return await svc.list_(page=page, size=size)


@router.get(
    "/{file_id}",
    operation_id="files_get",
    response_model=FileRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_file(file_id: int, svc: ServiceDep, _user: QueryGuard) -> FileRead:
    return await svc.get(file_id)


@router.post(
    "",
    operation_id="files_upload",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
    responses=UPLOAD_ERROR_RESPONSES,
)
async def upload_file(
    svc: ServiceDep,
    user: UploadGuard,
    upload: Annotated[UploadFile, File(description="上传的文件（multipart/form-data）")],
) -> FileRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_FILE_UPLOAD,
        "file",
        coro=svc.upload(
            filename=upload.filename or "unnamed",
            content_type=upload.content_type or "application/octet-stream",
            stream=_iter_upload(upload),
            uploader_id=int(user.user_id),
        ),
        display=lambda f: f.original_filename,
        success_status=201,
    )


@router.get(
    "/{file_id}/download",
    operation_id="files_download",
    responses=DOWNLOAD_ERROR_RESPONSES,
)
async def download_file(file_id: int, svc: ServiceDep, _user: DownloadGuard) -> StreamingResponse:
    meta, chunks = await svc.prepare_download(file_id)
    return StreamingResponse(
        chunks,
        media_type=meta.content_type,
        headers={
            "Content-Disposition": _content_disposition(meta.original_filename),
            # 强制禁 MIME sniffing：防客户端可控 content_type 下的 polyglot（GIF/HTML 等）
            # 被浏览器嗅探渲染成存储型 XSS（attachment + nosniff 双兜底，对抗审查 P2）。
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/{file_id}",
    operation_id="files_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_file(
    file_id: int, svc: ServiceDep, user: RemoveGuard, background: BackgroundTasks
) -> None:
    object_key = await audited_write(
        user,
        Permissions.SYSTEM_FILE_REMOVE,
        "file",
        coro=svc.delete(file_id),
        target_id=file_id,
    )
    # 物理删延后到请求事务 commit 成功之后（BackgroundTasks 在 response 发出后才跑）：
    # commit 失败 → response 5xx → 本任务不执行 → 文件保留，与回滚的 active 元数据一致（P1）。
    background.add_task(svc.delete_physical, object_key)
