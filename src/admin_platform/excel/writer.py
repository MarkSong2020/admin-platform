"""Excel 生成（openpyxl write-only 流式，无 domain 知识）。

write-only 模式近常量内存，适合大表导出。所有 cell 一律 canonical 文本化（``str``）——
与 reader 对称，保证「导出再导入」canonical row 相等（往返一致）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from io import BytesIO

from openpyxl import Workbook

from admin_platform.excel.schemas import ExcelColumn


class ExcelExporter:
    def __init__(self, columns: Sequence[ExcelColumn]) -> None:
        self._columns = list(columns)

    def write(self, rows: Iterable[Mapping[str, object]]) -> bytes:
        workbook = Workbook(write_only=True)
        worksheet = workbook.create_sheet()
        worksheet.append([col.header for col in self._columns])
        for row in rows:
            worksheet.append([_canonical(row.get(col.field)) for col in self._columns])
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()


# Excel/CSV formula injection 防御（OWASP CWE-1236）：以公式触发字符开头的值前缀单引号文本化，
# 防 Excel/WPS 打开导出文件时把 ``=HYPERLINK(...)`` / ``=cmd|...`` 等当公式执行（数据外泄/RCE）。
# 单引号是 Excel 文本化约定（显示时不可见）。正常值（不以触发字符开头）不变，往返一致。
_FORMULA_TRIGGERS = frozenset("=+-@\t\r")


def _canonical(value: object) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_TRIGGERS:
        return "'" + text
    return text
