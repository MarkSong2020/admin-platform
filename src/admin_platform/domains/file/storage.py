"""文件存储抽象 —— 可插拔 ``StorageBackend``（v1 仅 LocalFileStorage）。

物理字节的存取与业务/元数据解耦：``service`` 只认 ``object_key``（uuid4 hex），不碰路径。
未来接 S3/OSS 只需新增一个 ``StorageBackend`` 子类，业务层不改（spec 2026-06-11 §2）。

设计纪律：
- **零新依赖**：只用 stdlib + anyio（已装）。阻塞文件 I/O 经 ``anyio`` 异步文件接口/线程池，
  不阻塞事件循环（大文件拖垮 worker 是 PK 列出的失效模式）。
- **路径守卫**：``object_key`` 强制纯 32 位 hex（自生成，不含 ``/`` 或 ``..``）+ resolve 后
  必须仍在 root 内 —— 双重防穿越。
- **边写边算**：``write_stream`` 流式累计 size + sha256，超限即中止并清理半成品。
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import anyio
import anyio.to_thread

# object_key = uuid4().hex（32 位小写 hex）。强约束杜绝任何路径分隔符 / 穿越序列。
_OBJECT_KEY_RE = re.compile(r"^[0-9a-f]{32}$")
_DEFAULT_CHUNK_SIZE = 64 * 1024


class StorageError(Exception):
    """存储层基异常（service 捕获后转 AppError）。"""


class FileSizeExceeded(StorageError):
    """写入流超过 ``max_bytes`` 上限（边写边累计触发）。"""

    def __init__(self, *, max_bytes: int) -> None:
        super().__init__(f"文件超过上限 {max_bytes} 字节")
        self.max_bytes = max_bytes


class StoragePathError(StorageError):
    """object_key 非法或解析后越出 root（纵深兜底，正常不可达）。"""


@dataclass(frozen=True)
class StoredStat:
    """写入结果：实际字节数 + 内容 SHA256（落库用）。"""

    size_bytes: int
    sha256: str


class StorageBackend(ABC):
    """文件后端契约。所有方法以 ``object_key`` 为唯一寻址，不暴露物理路径。"""

    @abstractmethod
    async def write_stream(
        self, object_key: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> StoredStat:
        """流式写入；超 ``max_bytes`` 抛 FileSizeExceeded 并清理半成品。"""

    @abstractmethod
    def aiter_chunks(
        self, object_key: str, *, chunk_size: int = _DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        """流式读出（下载）。object_key 不存在时迭代抛 FileNotFoundError。"""

    @abstractmethod
    async def delete(self, object_key: str) -> bool:
        """删除物理文件；返回是否真的删了（不存在 → False）。"""

    @abstractmethod
    async def stat(self, object_key: str) -> int | None:
        """返回物理字节数；不存在返回 None（元数据在但文件丢失的检测口）。"""


class LocalFileStorage(StorageBackend):
    """本地文件系统后端。object_key 两级分桶（``<k[:2]>/<k[2:4]>/<k>``）避免单目录文件爆炸。"""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _resolve(self, object_key: str) -> Path:
        """object_key → 绝对路径，双重防穿越（格式校验 + root 包含校验）。"""
        if not _OBJECT_KEY_RE.match(object_key):
            raise StoragePathError(f"非法 object_key: {object_key!r}")
        candidate = (self._root / object_key[:2] / object_key[2:4] / object_key).resolve()
        if not candidate.is_relative_to(self._root):
            raise StoragePathError(f"object_key 解析越出 root: {object_key!r}")
        return candidate

    async def write_stream(
        self, object_key: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> StoredStat:
        path = self._resolve(object_key)
        await anyio.to_thread.run_sync(lambda: path.parent.mkdir(parents=True, exist_ok=True))
        hasher = hashlib.sha256()
        size = 0
        try:
            async with await anyio.open_file(path, "wb") as fh:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileSizeExceeded(max_bytes=max_bytes)
                    hasher.update(chunk)
                    await fh.write(chunk)
        except BaseException:
            # 半成品清理：超限 / 客户端断连 / 任何异常都不留残文件。
            await self._safe_unlink(path)
            raise
        return StoredStat(size_bytes=size, sha256=hasher.hexdigest())

    async def aiter_chunks(
        self, object_key: str, *, chunk_size: int = _DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        path = self._resolve(object_key)
        async with await anyio.open_file(path, "rb") as fh:
            while True:
                chunk = await fh.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def delete(self, object_key: str) -> bool:
        path = self._resolve(object_key)

        def _unlink() -> bool:
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False

        return await anyio.to_thread.run_sync(_unlink)

    async def stat(self, object_key: str) -> int | None:
        path = self._resolve(object_key)

        def _size() -> int | None:
            try:
                return path.stat().st_size
            except FileNotFoundError:
                return None

        return await anyio.to_thread.run_sync(_size)

    @staticmethod
    async def _safe_unlink(path: Path) -> None:
        def _unlink() -> None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()

        await anyio.to_thread.run_sync(_unlink)


def build_storage_backend(*, backend: str, root: str) -> StorageBackend:
    """按配置构造后端。v1 仅 local；未来 s3 在此分支。"""
    if backend == "local":
        return LocalFileStorage(root=Path(root))
    raise ValueError(f"unsupported file_storage_backend: {backend!r}")
