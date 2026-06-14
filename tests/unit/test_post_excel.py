"""Post Excel 导入导出 service 单测（P5 Excel 阶段2）——一步全有全无 + 全量错误 + 往返。

真 ExcelImporter/Exporter（不 mock 机制）+ fake repo（隔离 DB）。验证：导入全有全无（任一错误
不写任何行）、文件内/库内 code 重复定位、导出往返一致 + 超限。
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from admin_platform.core.errors import AppError
from admin_platform.domains.post.excel import POST_EXCEL_COLUMNS
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.post.schemas import PostCreate
from admin_platform.domains.post.service import _EXCEL_MAX_ROWS, PostService
from admin_platform.excel import ExcelExporter, ExcelImporter

pytestmark = pytest.mark.anyio


class _FakeRepo:
    def __init__(
        self, *, existing: set[str] | None = None, export_rows: list[Any] | None = None
    ) -> None:
        self._existing = existing or set()
        self._export_rows = export_rows or []
        self.created: list[PostCreate] = []

    async def list_existing_codes(self, codes: list[str]) -> set[str]:
        return {c for c in codes if c in self._existing}

    async def bulk_create(self, payloads: list[PostCreate]) -> int:
        self.created = list(payloads)
        return len(payloads)

    async def list_for_export(self, *, limit: int) -> list[Any]:
        return self._export_rows[:limit]


def _xlsx(rows: list[dict[str, object]]) -> bytes:
    return ExcelExporter(POST_EXCEL_COLUMNS).write(rows)


def _service(repo: _FakeRepo) -> PostService:
    return PostService(cast(PostRepository, repo))


async def test_import_happy_bulk_creates() -> None:
    repo = _FakeRepo()
    content = _xlsx(
        [
            {"name": "甲", "code": "a", "sort_order": 1, "status": "active"},
            {"name": "乙", "code": "b", "sort_order": 2, "status": "disabled"},
        ]
    )
    summary = await _service(repo).import_posts(content)
    assert summary.imported == 2
    assert [p.code for p in repo.created] == ["a", "b"]
    assert repo.created[1].status == "disabled"


async def test_import_duplicate_in_file_no_write() -> None:
    repo = _FakeRepo()
    content = _xlsx([{"name": "甲", "code": "dup"}, {"name": "乙", "code": "dup"}])
    summary = await _service(repo).import_posts(content)
    assert summary.imported == 0  # 全有全无：不写任何行
    assert any(e.code == "DUPLICATE_IN_FILE" for e in summary.errors)
    assert repo.created == []


async def test_import_db_duplicate_no_write() -> None:
    repo = _FakeRepo(existing={"exists"})
    content = _xlsx([{"name": "甲", "code": "exists"}])
    summary = await _service(repo).import_posts(content)
    assert summary.imported == 0
    assert any(e.code == "DB_DUPLICATE" for e in summary.errors)
    assert repo.created == []


async def test_import_validation_error_locates_row() -> None:
    repo = _FakeRepo()
    content = _xlsx([{"name": "", "code": "a"}])  # name 必填空
    summary = await _service(repo).import_posts(content)
    assert summary.imported == 0
    err = next(e for e in summary.errors if e.code == "VALIDATION")
    assert err.row == 2
    assert err.column == "岗位名称"
    assert repo.created == []


async def test_import_partial_bad_writes_nothing() -> None:
    # 一行好一行坏 → 全有全无：坏行报告，好行也不写
    repo = _FakeRepo()
    content = _xlsx([{"name": "甲", "code": "a"}, {"name": "", "code": "b"}])
    summary = await _service(repo).import_posts(content)
    assert summary.imported == 0
    assert summary.errors  # 有错误报告
    assert repo.created == []


async def test_export_roundtrip_canonical_equal() -> None:
    rows = [
        SimpleNamespace(name="甲", code="a", sort_order=1, status="active"),
        SimpleNamespace(name="乙", code="b", sort_order=2, status="disabled"),
    ]
    content = await _service(_FakeRepo(export_rows=rows)).export_posts()
    parsed = ExcelImporter(PostCreate, POST_EXCEL_COLUMNS).parse(content)
    assert parsed.errors == []
    assert [(p.data.name, p.data.code, p.data.sort_order, p.data.status) for p in parsed.rows] == [
        ("甲", "a", 1, "active"),
        ("乙", "b", 2, "disabled"),
    ]


async def test_export_too_large_422() -> None:
    overflow = [
        SimpleNamespace(name="x", code=f"c{i}", sort_order=0, status="active")
        for i in range(_EXCEL_MAX_ROWS + 1)
    ]
    with pytest.raises(AppError) as exc:
        await _service(_FakeRepo(export_rows=overflow)).export_posts()
    assert exc.value.code == "post.EXPORT_TOO_LARGE"
    assert exc.value.status_code == 422


async def test_import_sort_order_out_of_range_rejected() -> None:
    # sort_order 超 le=999999 → Pydantic VALIDATION 拒，不写（防 DB int4 越界 DataError 退化 500）
    repo = _FakeRepo()
    content = _xlsx([{"name": "甲", "code": "a", "sort_order": "99999999999", "status": "active"}])
    summary = await _service(repo).import_posts(content)
    assert summary.imported == 0
    assert any(e.code == "VALIDATION" for e in summary.errors)
    assert repo.created == []


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "\x0b评估专员", "code": "a"},  # name 含垂直制表（0x0b）
        {"name": "ok", "code": "a\x00b"},  # code 含 NUL（0x00）
    ],
)
async def test_post_create_rejects_control_char(payload: dict[str, str]) -> None:
    # L1 入口防御（对抗审查 R5 存储型 DoS）：含 openpyxl 非法控制字符的 name/code → PostCreate 拒绝。
    # 防止其进库后让 ``GET /posts/export`` 整表导出对全体永久 500。reader 逐行用 PostCreate 校验，
    # 故导入路径同受此拦截（坏行 → VALIDATION RowError）。注：正常 xlsx 通道无法注入这些字符
    # （openpyxl 写时即拒），真实注入需 create JSON `` 或手构 OOXML `_x000B_`，故此处直测 schema。
    with pytest.raises(ValidationError):
        PostCreate(name=payload["name"], code=payload["code"])


async def test_post_create_rejects_noncharacter() -> None:
    # U+FFFE/U+FFFF 非字符能过控制字符正则，但进库后让导出生成损坏 .xlsx（对抗审查 R5 skeptic 扩面）→
    # L1 同源拒绝（chr() 构造，避免源码含字面非字符）。
    for nonchar in (chr(0xFFFE), chr(0xFFFF)):
        with pytest.raises(ValidationError):
            PostCreate(name=nonchar + "x", code="ok")


# ---- zip bomb 防护（P1）：service 把 reader 的 ExcelTooLargeError 映成 413 -------


def _bomb_xlsx() -> bytes:
    """小压缩 / 大解压的恶意 xlsx（高度可压缩的全零 sharedStrings）→ 压缩比远超默认 100x。"""
    buffer = BytesIO()
    payload = b"<sst>" + b"0" * (20 * 1024 * 1024) + b"</sst>"  # 20MB 全零，DEFLATE 后几 KB
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", payload)
    return buffer.getvalue()


async def test_import_zip_bomb_raises_413() -> None:
    # 解压前预检（默认阈值，settings 注入）超限 → AppError 413，未触达 DB（repo 无任何写）
    repo = _FakeRepo()
    with pytest.raises(AppError) as exc:
        await _service(repo).import_posts(_bomb_xlsx())
    assert exc.value.status_code == 413
    assert exc.value.code == "post.EXCEL_TOO_LARGE"
    assert repo.created == []


async def test_import_bad_zip_is_invalid_file_not_413() -> None:
    # 坏 zip（非 xlsx 字节）→ INVALID_FILE 行级业务错误随 200，非 413（zip bomb 守卫放行坏 zip）
    repo = _FakeRepo()
    summary = await _service(repo).import_posts(b"not a zip at all")
    assert summary.imported == 0
    assert any(e.code == "INVALID_FILE" for e in summary.errors)
    assert repo.created == []
