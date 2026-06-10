"""Excel 生成（openpyxl write-only 流式，无 domain 知识）。

write-only 模式近常量内存，适合大表导出。所有 cell 一律 canonical 文本化（``str``）——
与 reader 对称，保证「导出再导入」canonical row 相等（往返一致）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from admin_platform.excel.schemas import ExcelColumn

# openpyxl ``ILLEGAL_CHARACTERS_RE`` 覆盖 C0 控制字符，但漏 BMP 非字符 U+FFFE/U+FFFF——XML 1.0 Char
# 上限是 U+FFFD，这两个不进 ILLEGAL 集（``worksheet.append`` 不抛错），却会让生成的 .xlsx XML 损坏
# （重开报 not well-formed）。对抗审查 R5 skeptic 扩面发现，writer 一并剥除（codepoint 表避免源码含
# 字面非字符）。
_NONCHAR_CODEPOINTS: dict[int, None] = dict.fromkeys((0xFFFE, 0xFFFF))


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
# 触发集含换行（对抗审查 R2 闭合 \n 开头的理论缺口）。
_FORMULA_TRIGGERS = frozenset("=+-@\t\r\n")


def _canonical(value: object) -> str:
    text = "" if value is None else str(value)
    # 剥除导出会破坏 .xlsx 的字符（defense-in-depth 兜底，对抗审查 R5 存储型 DoS）：openpyxl 非法控制
    # 字符（0x00-08 / 0x0b-0c / 0x0e-1f；不含合法 \t \n \r）否则让 ``worksheet.append`` 抛
    # IllegalCharacterError → 整表导出对全体永久 500；BMP 非字符 U+FFFE/U+FFFF 则生成损坏 XML。
    # 剥除在 formula 判断之前，故剥掉前导非法字符后若暴露公式触发字符仍会被正确转义。
    text = ILLEGAL_CHARACTERS_RE.sub("", text).translate(_NONCHAR_CODEPOINTS)
    if text and text[0] in _FORMULA_TRIGGERS:
        return "'" + text
    return text
