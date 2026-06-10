"""File service 单测（P5 阶段C）——上传校验分支 / 下载 / 列表 / 软删。

测真实 service 行为：用**真实 LocalFileStorage**（tmp_path，不 mock 存储）+ duck-typed fake repo
（只隔离 DB）。验证扩展名/魔数/size/空文件四类拒绝 + happy 落库 + 软删物理清理。
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.file.repository import FileRepository
from admin_platform.domains.file.service import FileService
from admin_platform.domains.file.storage import LocalFileStorage

pytestmark = pytest.mark.anyio

_PNG = b"\x89PNG\r\n\x1a\n"


async def _stream(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


class _FakeRepo:
    """镜像 FileRepository 契约（DB-free，行用 SimpleNamespace）。"""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows: dict[int, Any] = {r.id: r for r in (rows or [])}
        self.created: list[dict[str, Any]] = []
        self.soft_deleted: list[int] = []
        self._next_id = (max(self._rows) if self._rows else 0) + 1

    async def create(self, **kw: Any) -> Any:
        row = SimpleNamespace(id=self._next_id, status="active", created_at=datetime.now(UTC), **kw)
        self._next_id += 1
        self.created.append(kw)
        self._rows[row.id] = row
        return row

    async def get_active(self, file_id: int) -> Any:
        row = self._rows.get(file_id)
        return row if row is not None and row.status == "active" else None

    async def list_active(self, *, page: int, size: int) -> list[Any]:
        return [r for r in self._rows.values() if r.status == "active"]

    async def count_active(self) -> int:
        return len([r for r in self._rows.values() if r.status == "active"])

    async def soft_delete(self, file_id: int, *, now: datetime) -> Any:
        row = self._rows.get(file_id)
        if row is None or row.status != "active":
            return None
        row.status = "deleted"
        row.deleted_at = now
        self.soft_deleted.append(file_id)
        return row


def _service(
    tmp_path: Path,
    *,
    repo: _FakeRepo | None = None,
    max_bytes: int = 10**6,
    allowed: list[str] | None = None,
) -> FileService:
    storage = LocalFileStorage(root=tmp_path)
    return FileService(
        cast(FileRepository, repo or _FakeRepo()),
        storage,
        max_bytes=max_bytes,
        allowed_extensions=allowed or ["png", "jpg", "txt", "pdf", "xlsx"],
        storage_backend_name="local",
    )


async def test_upload_png_happy_persists_and_writes(tmp_path: Path) -> None:
    repo = _FakeRepo()
    svc = _service(tmp_path, repo=repo)
    data = _PNG + b"imagebytes"
    result = await svc.upload(
        filename="pic.png", content_type="image/png", stream=_stream(data), uploader_id=7
    )
    assert result.original_filename == "pic.png"
    assert result.size_bytes == len(data)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.uploader_id == 7
    assert repo.created[0]["storage_backend"] == "local"
    object_key = repo.created[0]["object_key"]  # object_key 不外泄进 FileRead，从落库参数取
    assert await svc._storage.stat(object_key) == len(data)  # type: ignore[attr-defined]


async def test_upload_txt_no_magic_happy(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    result = await svc.upload(
        filename="notes.txt",
        content_type="text/plain",
        stream=_stream(b"plain text"),
        uploader_id=1,
    )
    assert result.size_bytes == len(b"plain text")


async def test_upload_rejects_disallowed_extension(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(AppError) as exc:
        await svc.upload(
            filename="evil.exe",
            content_type="application/octet-stream",
            stream=_stream(b"MZ\x90\x00binary"),
            uploader_id=1,
        )
    assert exc.value.code == "file.EXTENSION_NOT_ALLOWED"
    assert exc.value.status_code == 415


async def test_upload_rejects_no_extension(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(AppError) as exc:
        await svc.upload(
            filename="noext", content_type="text/plain", stream=_stream(b"data"), uploader_id=1
        )
    assert exc.value.code == "file.EXTENSION_NOT_ALLOWED"


async def test_upload_rejects_magic_mismatch(tmp_path: Path) -> None:
    repo = _FakeRepo()
    svc = _service(tmp_path, repo=repo)
    with pytest.raises(AppError) as exc:
        await svc.upload(
            filename="fake.png",
            content_type="image/png",
            stream=_stream(b"NOTAPNG!"),
            uploader_id=1,
        )
    assert exc.value.code == "file.CONTENT_TYPE_MISMATCH"
    assert exc.value.status_code == 415
    assert repo.created == []  # 校验失败不落库


async def test_upload_rejects_oversize_and_cleans(tmp_path: Path) -> None:
    repo = _FakeRepo()
    svc = _service(tmp_path, repo=repo, max_bytes=10)
    with pytest.raises(AppError) as exc:
        await svc.upload(
            filename="big.txt",
            content_type="text/plain",
            stream=_stream(b"x" * 100),
            uploader_id=1,
        )
    assert exc.value.code == "file.SIZE_EXCEEDED"
    assert exc.value.status_code == 413
    assert repo.created == []


async def test_upload_rejects_empty_file(tmp_path: Path) -> None:
    repo = _FakeRepo()
    svc = _service(tmp_path, repo=repo)
    with pytest.raises(AppError) as exc:
        await svc.upload(
            filename="empty.txt", content_type="text/plain", stream=_stream(), uploader_id=1
        )
    assert exc.value.code == "file.EMPTY_FILE"
    assert exc.value.status_code == 422
    assert repo.created == []


async def test_get_active_and_not_found(tmp_path: Path) -> None:
    row = SimpleNamespace(
        id=5,
        object_key=uuid.uuid4().hex,
        original_filename="a.png",
        content_type="image/png",
        size_bytes=10,
        sha256="0" * 64,
        uploader_id=7,
        status="active",
        created_at=datetime.now(UTC),
    )
    svc = _service(tmp_path, repo=_FakeRepo([row]))
    got = await svc.get(5)
    assert got.id == 5
    with pytest.raises(AppError) as exc:
        await svc.get(999)
    assert exc.value.code == "file.NOT_FOUND"
    assert exc.value.status_code == 404


async def test_list_maps_page(tmp_path: Path) -> None:
    rows = [
        SimpleNamespace(
            id=i,
            object_key=uuid.uuid4().hex,
            original_filename=f"f{i}.txt",
            content_type="text/plain",
            size_bytes=i,
            sha256="0" * 64,
            uploader_id=1,
            status="active",
            created_at=datetime.now(UTC),
        )
        for i in (1, 2, 3)
    ]
    svc = _service(tmp_path, repo=_FakeRepo(rows))
    page = await svc.list_(page=1, size=20)
    assert page.total == 3
    assert page.total_pages == 1
    assert len(page.items) == 3


async def test_prepare_download_streams_content(tmp_path: Path) -> None:
    repo = _FakeRepo()
    svc = _service(tmp_path, repo=repo)
    data = _PNG + b"payload"
    uploaded = await svc.upload(
        filename="d.png", content_type="image/png", stream=_stream(data), uploader_id=7
    )
    meta, chunks = await svc.prepare_download(uploaded.id)
    assert meta.original_filename == "d.png"
    body = b"".join([chunk async for chunk in chunks])
    assert body == data


async def test_prepare_download_404_when_absent(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(AppError) as exc:
        await svc.prepare_download(123)
    assert exc.value.code == "file.NOT_FOUND"


async def test_prepare_download_404_when_physical_lost(tmp_path: Path) -> None:
    # 元数据在但物理文件从未写入（object_key 指向空）→ 404
    row = SimpleNamespace(
        id=9,
        object_key=uuid.uuid4().hex,
        original_filename="lost.png",
        content_type="image/png",
        size_bytes=10,
        sha256="0" * 64,
        uploader_id=7,
        status="active",
        created_at=datetime.now(UTC),
    )
    svc = _service(tmp_path, repo=_FakeRepo([row]))
    with pytest.raises(AppError) as exc:
        await svc.prepare_download(9)
    assert exc.value.code == "file.NOT_FOUND"


async def test_delete_soft_marks_returns_key_physical_deferred(tmp_path: Path) -> None:
    # delete 软删元数据 + 返回 object_key，但**不**同步物理删（延后到 commit 后 background，P1）。
    repo = _FakeRepo()
    svc = _service(tmp_path, repo=repo)
    data = _PNG + b"todelete"
    uploaded = await svc.upload(
        filename="x.png", content_type="image/png", stream=_stream(data), uploader_id=7
    )
    object_key = repo.created[0]["object_key"]
    returned_key = await svc.delete(uploaded.id)
    assert uploaded.id in repo.soft_deleted
    assert returned_key == object_key
    # 物理文件此刻仍在（delete 不同步删）
    assert await svc._storage.stat(object_key) is not None  # type: ignore[attr-defined]
    # delete_physical（api BackgroundTasks 在 commit 后调）才真正删物理
    await svc.delete_physical(object_key)
    assert await svc._storage.stat(object_key) is None  # type: ignore[attr-defined]


async def test_delete_404_when_absent(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(AppError) as exc:
        await svc.delete(404)
    assert exc.value.code == "file.NOT_FOUND"


async def test_upload_cleans_physical_when_repo_create_fails(tmp_path: Path) -> None:
    # repo.create 失败（约束/FK/连接）→ 已写物理文件被清理，不留孤儿（对抗审查 P1）。
    class _FailRepo(_FakeRepo):
        async def create(self, **kw: Any) -> Any:
            raise RuntimeError("simulated flush failure")

    svc = _service(tmp_path, repo=_FailRepo())
    with pytest.raises(RuntimeError, match="simulated"):
        await svc.upload(
            filename="x.png",
            content_type="image/png",
            stream=_stream(_PNG + b"data"),
            uploader_id=7,
        )
    leftover = [p for p in tmp_path.rglob("*") if p.is_file()]  # noqa: ASYNC240 测试同步遍历断言
    assert leftover == []  # storage root 下无残留孤儿文件


async def test_upload_truncates_overlong_filename(tmp_path: Path) -> None:
    # filename > 255 → 截断到 255（写物理前防御，避免 flush 因超长 raise 留孤儿，对抗审查 P1）。
    svc = _service(tmp_path)
    result = await svc.upload(
        filename="a" * 300 + ".png",
        content_type="image/png",
        stream=_stream(_PNG + b"d"),
        uploader_id=7,
    )
    assert len(result.original_filename) == 255
