"""Post service —— 业务用例层（RBAC 岗位，抛 ``AppError``，错误码 ``post.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise（触发请求
事务回滚），不抛 HTTPException（分层契约 C3）。

业务不变式：
  * **code 全局唯一** —— create / update（改 code 时）用 ``find_by_code`` 预检，违反抛 409
    ``post.CODE_DUPLICATE``。DB 的 ``uq_posts_code`` 是竞态兜底：并发预检都通过时第二个
    INSERT 撞约束 → ``IntegrityError`` handler 按 ``models.py`` 注册映射翻成同一码。

岗位是扁平域：无树、无 data_scope，故比 role service 更简单（无 O2 归一）。
"""

from __future__ import annotations

from admin_platform.core.config import get_settings
from admin_platform.core.errors import AppError
from admin_platform.core.pagination import compute_total_pages, resolve_sort
from admin_platform.domains.post.excel import POST_EXCEL_COLUMNS
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.post.schemas import (
    PostCreate,
    PostImportRowError,
    PostImportSummary,
    PostListQuery,
    PostPage,
    PostRead,
    PostUpdate,
)
from admin_platform.excel import ExcelExporter, ExcelImporter, ExcelTooLargeError

NOT_FOUND_CODE = "post.NOT_FOUND"
CODE_DUPLICATE_CODE = "post.CODE_DUPLICATE"
EXPORT_TOO_LARGE_CODE = "post.EXPORT_TOO_LARGE"
IMPORT_TOO_LARGE_CODE = "post.EXCEL_TOO_LARGE"
# Excel 导入/导出行数上限（配置化排期，spec §1 非目标）。
_EXCEL_MAX_ROWS = 10000


class PostService:
    def __init__(self, repository: PostRepository) -> None:
        self._repo = repository

    async def list_(self, query: PostListQuery, *, page: int, size: int) -> PostPage:
        """offset 分页（ADR 0001 §7.5 envelope）。岗位是全局配置，不受 data_scope 约束。

        排序在此层解析（resolve_sort 防注入：非法 order_by → 422）；过滤条件由 repository 构造。
        """
        order_by = resolve_sort(
            query.order_by,
            query.order,
            allowed=PostRepository.SORT_ALLOWED,
            default=PostRepository.SORT_DEFAULT,
            tie_break=PostRepository.SORT_TIE_BREAK,
        )
        rows = await self._repo.list_paginated(query, page, size, order_by=order_by)
        total = await self._repo.count(query)
        return PostPage(
            items=[PostRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=compute_total_pages(total, size),
        )

    async def get(self, item_id: int) -> PostRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return PostRead.model_validate(row)

    async def create(self, payload: PostCreate) -> PostRead:
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)
        row = await self._repo.create(payload)
        return PostRead.model_validate(row)

    async def update(self, item_id: int, payload: PostUpdate) -> PostRead:
        existing = await self._repo.get(item_id)
        if existing is None:
            raise self._not_found(item_id)
        await self._check_code_unique(existing, payload)
        row = await self._repo.update(item_id, payload)
        if row is None:  # 并发删除兜底：预检后被他人删除
            raise self._not_found(item_id)
        return PostRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        ok = await self._repo.delete(item_id)
        if not ok:
            raise self._not_found(item_id)

    # ---- Excel 导入导出（P5，一步全有全无 + 全量错误报告）---------------------

    async def import_posts(self, content: bytes) -> PostImportSummary:
        """全量校验（Pydantic 逐行 + 文件内/库内 code 重复）：errors 非空 → imported=0 不写；
        全通过 → 单事务批量写入。导入错误随 200 返回（业务结果，errors 始终可见，非系统错误）。

        解压前 zip bomb 预检（reader 内）超限 → ``ExcelTooLargeError`` → 413（payload too large，
        与上传体积超限 ``post.EXCEL_TOO_LARGE`` 同语义，系统级拒绝，非行级业务结果）。
        """
        settings = get_settings()
        importer = ExcelImporter(
            PostCreate,
            POST_EXCEL_COLUMNS,
            max_rows=_EXCEL_MAX_ROWS,
            max_uncompressed_bytes=settings.excel_max_uncompressed_bytes,
            max_zip_entries=settings.excel_max_zip_entries,
            max_compression_ratio=settings.excel_max_compression_ratio,
        )
        try:
            result = importer.parse(content)
        except ExcelTooLargeError as exc:
            raise AppError(
                code=IMPORT_TOO_LARGE_CODE,
                title="Excel 文件过大",
                detail="解压后体积/条目超限，疑似 zip bomb，已拒绝",
                status_code=413,
            ) from exc
        errors = [
            PostImportRowError(row=e.row, column=e.column, code=e.code, message=e.message)
            for e in result.errors
        ]

        # 文件内 code 重复（跨行）
        seen: dict[str, int] = {}
        for parsed in result.rows:
            if parsed.data.code in seen:
                errors.append(
                    PostImportRowError(
                        row=parsed.row,
                        column="岗位编码",
                        code="DUPLICATE_IN_FILE",
                        message=f"文件内 code 重复: {parsed.data.code}",
                    )
                )
            else:
                seen[parsed.data.code] = parsed.row

        # 库内 code 重复
        existing = await self._repo.list_existing_codes([p.data.code for p in result.rows])
        for parsed in result.rows:
            if parsed.data.code in existing:
                errors.append(
                    PostImportRowError(
                        row=parsed.row,
                        column="岗位编码",
                        code="DB_DUPLICATE",
                        message=f"库内已存在 code: {parsed.data.code}",
                    )
                )

        if errors:
            return PostImportSummary(imported=0, errors=errors)  # 全有全无：不写任何行
        imported = await self._repo.bulk_create([p.data for p in result.rows])
        return PostImportSummary(imported=imported)

    async def export_posts(self) -> bytes:
        """全量导出（行数上限兜底；超限 422，提示用筛选/后台任务）。"""
        rows = await self._repo.list_for_export(limit=_EXCEL_MAX_ROWS + 1)
        if len(rows) > _EXCEL_MAX_ROWS:
            raise AppError(
                code=EXPORT_TOO_LARGE_CODE,
                title="导出超过行数上限",
                detail=f"超过 {_EXCEL_MAX_ROWS} 行，请用筛选或后台任务（排期）",
                status_code=422,
            )
        exporter = ExcelExporter(POST_EXCEL_COLUMNS)
        return exporter.write(
            [
                {"name": r.name, "code": r.code, "sort_order": r.sort_order, "status": r.status}
                for r in rows
            ]
        )

    async def _check_code_unique(self, existing: object, payload: PostUpdate) -> None:
        """改 code 且与现值不同时校验全局唯一（未改 code 跳过）。"""
        if "code" not in payload.model_fields_set or payload.code is None:
            return
        if payload.code == getattr(existing, "code", None):
            return
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Post not found",
            detail=f"id={item_id}",
            status_code=404,
        )

    @staticmethod
    def _duplicate(code: str) -> AppError:
        return AppError(
            code=CODE_DUPLICATE_CODE,
            title="Post code already exists",
            detail=f"code={code!r}",
            status_code=409,
        )
