"""通用 Excel 导入导出机制（叶子模块，零 domain 知识，import-linter C10 守门）。

无状态：reader/writer 不拿 AsyncSession、不返回 HTTP 响应、不抛 HTTPException；只做
``.xlsx`` 解析/生成 + schema 驱动的逐行校验。domain 在自己的 ``excel.py`` 放绑定适配器
（列定义 + 行 schema），通用机制不认识具体实体。
"""

from __future__ import annotations

from admin_platform.excel.reader import ExcelImporter
from admin_platform.excel.schemas import (
    ExcelColumn,
    ExcelTooLargeError,
    ImportResult,
    ParsedRow,
    RowError,
)
from admin_platform.excel.writer import ExcelExporter

__all__ = [
    "ExcelColumn",
    "ExcelExporter",
    "ExcelImporter",
    "ExcelTooLargeError",
    "ImportResult",
    "ParsedRow",
    "RowError",
]
