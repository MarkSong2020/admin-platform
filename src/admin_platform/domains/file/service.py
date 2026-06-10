"""File service — 业务用例层（上传校验 / 流式下载 / 列表 / 软删）。

安全模型（defense-in-depth，spec 2026-06-11 §5）：
- L1 扩展名白名单（原文件名后缀 ∈ 配置白名单）；
- L2 魔数头匹配扩展名（有签名类型强校验，纯文本类豁免）+ 边写边累计 size 上限 + object_key=uuid4
  （不信任原文件名）；
- L3 存储层路径守卫（StorageBackend 内）；L4 审计由 api 层 audited_write 织入。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from admin_platform.core.errors import AppError
from admin_platform.domains.file.repository import FileRepository
from admin_platform.domains.file.schemas import FilePage, FileRead
from admin_platform.domains.file.storage import FileSizeExceeded, StorageBackend

NOT_FOUND_CODE = "file.NOT_FOUND"
EXTENSION_NOT_ALLOWED_CODE = "file.EXTENSION_NOT_ALLOWED"
CONTENT_TYPE_MISMATCH_CODE = "file.CONTENT_TYPE_MISMATCH"
SIZE_EXCEEDED_CODE = "file.SIZE_EXCEEDED"
EMPTY_FILE_CODE = "file.EMPTY_FILE"

# 魔数头白名单（stdlib，不引 python-magic）：有签名类型强校验扩展名↔内容一致。
# 纯文本类（txt/csv/log）无稳定签名 → 不在表中 → 跳过魔数校验（仅扩展名白名单）。
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "xlsx": (b"PK\x03\x04",),
    "docx": (b"PK\x03\x04",),
    "zip": (b"PK\x03\x04",),
}
# 累积到此字节数再验魔数（覆盖最长签名 PNG 8 字节）。
_MAGIC_PEEK = 8


def _extract_ext(filename: str) -> str:
    """取小写无点扩展名；无扩展名返回空串（→ 白名单不含 → 拒）。"""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


class FileService:
    def __init__(
        self,
        repository: FileRepository,
        storage: StorageBackend,
        *,
        max_bytes: int,
        allowed_extensions: list[str],
        storage_backend_name: str,
    ) -> None:
        self._repo = repository
        self._storage = storage
        self._max_bytes = max_bytes
        self._allowed_extensions = frozenset(ext.lower() for ext in allowed_extensions)
        self._storage_backend_name = storage_backend_name

    def _verify_magic(self, ext: str, header: bytes) -> None:
        if not header:
            return  # 空内容留给 size==0 报 EMPTY_FILE，不误报 mismatch
        signatures = _MAGIC_SIGNATURES.get(ext)
        if signatures and not any(header.startswith(sig) for sig in signatures):
            raise AppError(
                code=CONTENT_TYPE_MISMATCH_CODE,
                title="文件内容与扩展名不符",
                detail=f"扩展名 .{ext} 的魔数头校验未通过",
                status_code=415,
            )

    async def _verify_and_rechain(
        self, ext: str, stream: AsyncIterator[bytes]
    ) -> AsyncIterator[bytes]:
        """流式透传 stream，首 ``_MAGIC_PEEK`` 字节累积后验魔数再放行（不缓冲整文件）。"""
        head = b""
        checked = False
        async for chunk in stream:
            if not checked:
                head += chunk
                if len(head) >= _MAGIC_PEEK:
                    self._verify_magic(ext, head)
                    checked = True
                    yield head
                    head = b""
                continue
            yield chunk
        if not checked:  # 流结束仍不足 peek（小文件）：验已累积部分
            self._verify_magic(ext, head)
            if head:
                yield head

    async def upload(
        self,
        *,
        filename: str,
        content_type: str,
        stream: AsyncIterator[bytes],
        uploader_id: int,
    ) -> FileRead:
        ext = _extract_ext(filename)
        if ext not in self._allowed_extensions:
            raise AppError(
                code=EXTENSION_NOT_ALLOWED_CODE,
                title="不支持的文件类型",
                detail=f"扩展名 .{ext} 不在允许列表",
                status_code=415,
            )
        # 写物理前防御列长度（避免 flush 因超长 raise 后留下已写的孤儿物理文件，对抗审查 P1）。
        filename = filename[:255]
        content_type = content_type[:128]
        object_key = uuid.uuid4().hex
        rechained = self._verify_and_rechain(ext, stream)
        try:
            stat = await self._storage.write_stream(
                object_key, rechained, max_bytes=self._max_bytes
            )
        except FileSizeExceeded as exc:
            raise AppError(
                code=SIZE_EXCEEDED_CODE,
                title="文件超过大小上限",
                detail=f"上限 {self._max_bytes} 字节",
                status_code=413,
            ) from exc
        if stat.size_bytes == 0:
            await self._storage.delete(object_key)  # 清理空文件
            raise AppError(code=EMPTY_FILE_CODE, title="空文件不允许上传", status_code=422)
        try:
            row = await self._repo.create(
                object_key=object_key,
                storage_backend=self._storage_backend_name,
                original_filename=filename,
                content_type=content_type,
                size_bytes=stat.size_bytes,
                sha256=stat.sha256,
                uploader_id=uploader_id,
            )
        except Exception:
            # repo.create/flush 失败（约束/FK/连接）→ 清理已写物理文件，不留孤儿（对抗审查 P1）。
            # commit 阶段失败的残窗仍存在，靠 orphan sweeper 兜底（spec §1 排期）。
            await self._storage.delete(object_key)
            raise
        return FileRead.model_validate(row)

    async def get(self, file_id: int) -> FileRead:
        row = await self._repo.get_active(file_id)
        if row is None:
            raise AppError(code=NOT_FOUND_CODE, title="文件不存在", status_code=404)
        return FileRead.model_validate(row)

    async def list_(self, *, page: int, size: int) -> FilePage:
        rows = await self._repo.list_active(page=page, size=size)
        total = await self._repo.count_active()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return FilePage(
            items=[FileRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def prepare_download(self, file_id: int) -> tuple[FileRead, AsyncIterator[bytes]]:
        """返回 (元数据, 内容流)。元数据在但物理文件丢失 → 404（资源不可得）。"""
        row = await self._repo.get_active(file_id)
        if row is None:
            raise AppError(code=NOT_FOUND_CODE, title="文件不存在", status_code=404)
        if await self._storage.stat(row.object_key) is None:
            raise AppError(code=NOT_FOUND_CODE, title="文件内容已丢失", status_code=404)
        meta = FileRead.model_validate(row)
        return meta, self._storage.aiter_chunks(row.object_key)

    async def delete(self, file_id: int) -> str:
        """软删元数据（保留审计），返回待物理删的 object_key。不存在/已删 → 404。

        物理删除**不在此同步执行**：由 api 层经 BackgroundTasks 在请求事务 commit 成功后才删
        （commit 失败 → 不删 → DB 回滚 active 与物理文件保持一致）。避免「commit 前不可逆 unlink」
        造成「active 元数据指向已删文件」的数据丢失（对抗审查 P1）。
        """
        row = await self._repo.soft_delete(file_id, now=datetime.now(UTC))
        if row is None:
            raise AppError(code=NOT_FOUND_CODE, title="文件不存在", status_code=404)
        return row.object_key

    async def delete_physical(self, object_key: str) -> None:
        """物理删文件（api 经 BackgroundTasks 在 commit 后调用；幂等：不存在静默）。"""
        await self._storage.delete(object_key)
