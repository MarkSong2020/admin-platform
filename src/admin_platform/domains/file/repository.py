"""File repository — SQLAlchemy 2.x async 数据访问层。

只读/写 ``status='active'`` 的可见行；软删行（status='deleted'）保留供审计，不在常规查询出现。
物理文件存取不在本层（service 经 StorageBackend）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.file.models import File


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(  # noqa: PLR0913 —— 显式命名落库字段比传 dataclass 清晰
        self,
        *,
        object_key: str,
        storage_backend: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        uploader_id: int,
    ) -> File:
        obj = File(
            object_key=object_key,
            storage_backend=storage_backend,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            uploader_id=uploader_id,
            status="active",
        )
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_active(self, file_id: int) -> File | None:
        stmt = select(File).where(File.id == file_id, File.status == "active")
        return await self._session.scalar(stmt)

    async def list_active(self, *, page: int, size: int) -> list[File]:
        offset = (page - 1) * size
        stmt = (
            select(File)
            .where(File.status == "active")
            .order_by(File.id.desc())
            .offset(offset)
            .limit(size)
        )
        return list((await self._session.scalars(stmt)).all())

    async def count_active(self) -> int:
        stmt = select(func.count()).select_from(File).where(File.status == "active")
        return int((await self._session.execute(stmt)).scalar_one())

    async def soft_delete(self, file_id: int, *, now: datetime) -> File | None:
        """active → deleted（标记软删 + deleted_at），返回被删行供物理清理；不存在/已删 → None。"""
        obj = await self.get_active(file_id)
        if obj is None:
            return None
        obj.status = "deleted"
        obj.deleted_at = now
        await self._session.flush()
        return obj
