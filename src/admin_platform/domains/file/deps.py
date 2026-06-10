"""File 组合根（Composition Root）。

组装 FileService 的依赖（repository + StorageBackend + 配置），使 api.py 只依赖 service、
不直接 import repository/storage（分层契约：``*.api`` 禁 import ``*.repository``）。
StorageBackend 按 ``settings.file_storage_backend`` 选型（v1 local），LocalFileStorage 轻量
（仅持 root Path），每请求构造无虞。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.config import get_settings
from admin_platform.db.session import get_session
from admin_platform.domains.file.repository import FileRepository
from admin_platform.domains.file.service import FileService
from admin_platform.domains.file.storage import build_storage_backend


async def get_file_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileService:
    settings = get_settings()
    storage = build_storage_backend(
        backend=settings.file_storage_backend, root=settings.file_storage_root
    )
    return FileService(
        FileRepository(session),
        storage,
        max_bytes=settings.file_max_upload_size_bytes,
        allowed_extensions=settings.file_allowed_extensions,
        storage_backend_name=settings.file_storage_backend,
    )
