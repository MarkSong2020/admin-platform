"""LocalFileStorage 单测（P5 阶段B）——流式写/读往返、size 上限、sha256、路径穿越守卫。"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from admin_platform.domains.file.storage import (
    FileSizeExceeded,
    LocalFileStorage,
    StoragePathError,
    build_storage_backend,
)

pytestmark = pytest.mark.anyio


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def _key() -> str:
    return uuid.uuid4().hex


async def test_write_stream_computes_size_and_sha256(tmp_path: Path) -> None:
    storage = LocalFileStorage(root=tmp_path)
    key = _key()
    data = b"hello " * 1000
    stat = await storage.write_stream(
        key, _chunks(b"hello " * 500, b"hello " * 500), max_bytes=10**6
    )
    assert stat.size_bytes == len(data)
    assert stat.sha256 == hashlib.sha256(data).hexdigest()
    assert await storage.stat(key) == len(data)  # 物理文件落在分桶路径


async def test_write_stream_roundtrip(tmp_path: Path) -> None:
    storage = LocalFileStorage(root=tmp_path)
    key = _key()
    data = bytes(range(256)) * 100
    await storage.write_stream(key, _chunks(data), max_bytes=10**6)
    read = b"".join([chunk async for chunk in storage.aiter_chunks(key, chunk_size=512)])
    assert read == data


async def test_write_stream_skips_empty_chunks(tmp_path: Path) -> None:
    storage = LocalFileStorage(root=tmp_path)
    key = _key()
    stat = await storage.write_stream(key, _chunks(b"a", b"", b"b"), max_bytes=10**6)
    assert stat.size_bytes == 2


async def test_write_stream_size_exceeded_cleans_partial(tmp_path: Path) -> None:
    storage = LocalFileStorage(root=tmp_path)
    key = _key()
    with pytest.raises(FileSizeExceeded):
        await storage.write_stream(key, _chunks(b"x" * 100, b"y" * 100), max_bytes=150)
    assert await storage.stat(key) is None  # 半成品清理：超限后不留残文件


async def test_delete_existing_and_absent(tmp_path: Path) -> None:
    storage = LocalFileStorage(root=tmp_path)
    key = _key()
    await storage.write_stream(key, _chunks(b"data"), max_bytes=10**6)
    assert await storage.delete(key) is True
    assert await storage.delete(key) is False  # 已删 → False
    assert await storage.stat(key) is None


async def test_stat_absent_returns_none(tmp_path: Path) -> None:
    storage = LocalFileStorage(root=tmp_path)
    assert await storage.stat(_key()) is None


@pytest.mark.parametrize(
    "bad_key",
    [
        "../../etc/passwd",
        "abc/def",
        "..",
        "",
        "ZZZ" + "0" * 29,  # 非 hex
        "0" * 31,  # 长度不足
        "0" * 33,  # 长度超
    ],
)
async def test_resolve_rejects_illegal_object_key(tmp_path: Path, bad_key: str) -> None:
    storage = LocalFileStorage(root=tmp_path)
    with pytest.raises(StoragePathError):
        await storage.stat(bad_key)


async def test_build_storage_backend_local(tmp_path: Path) -> None:
    backend = build_storage_backend(backend="local", root=str(tmp_path))
    assert isinstance(backend, LocalFileStorage)


def test_build_storage_backend_unsupported() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        build_storage_backend(backend="s3", root="unused")
