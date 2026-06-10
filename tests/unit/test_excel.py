"""通用 Excel 机制单测（P5 Excel 阶段1）——往返一致 / 坏行不阻断 / 缺列头 / 类型漂移 / 行数上限。"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field

from admin_platform.excel import ExcelColumn, ExcelExporter, ExcelImporter

_COLUMNS = [
    ExcelColumn("name", "名称"),
    ExcelColumn("code", "编码"),
    ExcelColumn("count", "数量", required=False),
]


class _SampleRow(BaseModel):
    name: str = Field(min_length=1, max_length=10)
    code: str = Field(min_length=1)
    count: int = 0


def _manual_xlsx(rows: list[list[object]]) -> bytes:
    """手写 xlsx（含数字/空 cell），模拟用户真实 Excel（绕过 exporter 的 canonical 化）。"""
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    for row in rows:
        worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_roundtrip_export_then_import() -> None:
    content = ExcelExporter(_COLUMNS).write(
        [{"name": "甲", "code": "x1", "count": 5}, {"name": "乙", "code": "x2", "count": 0}]
    )
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert result.errors == []
    assert [(r.data.name, r.data.code, r.data.count) for r in result.rows] == [
        ("甲", "x1", 5),
        ("乙", "x2", 0),
    ]
    assert [r.row for r in result.rows] == [2, 3]  # Excel 行号（含表头）保留


def test_bad_row_collected_not_blocking() -> None:
    # 第 2 行 name 空（必填失败），第 3 行正常 → 好行通过 + 坏行定位
    content = ExcelExporter(_COLUMNS).write(
        [{"name": "", "code": "x1"}, {"name": "ok", "code": "x2"}]
    )
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert [r.data.name for r in result.rows] == ["ok"]
    assert len(result.errors) == 1
    assert result.errors[0].row == 2
    assert result.errors[0].column == "名称"
    assert result.errors[0].code == "VALIDATION"


def test_optional_empty_uses_default() -> None:
    # 非必填 count 空 cell → 省略 → Pydantic default 0（不误报 int 解析失败）
    content = _manual_xlsx([["名称", "编码", "数量"], ["甲", "x1", None]])
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert result.errors == []
    assert result.rows[0].data.count == 0


def test_numeric_cell_canonical_to_str() -> None:
    # 编码列填数字 123（用户 Excel 数字格式）→ canonical 成 str "123"，不漂移
    content = _manual_xlsx([["名称", "编码", "数量"], ["item", 123, 5]])
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert result.errors == []
    assert result.rows[0].data.code == "123"


def test_missing_column_header() -> None:
    # 导出只含「名称」列，导入期望「编码」→ MISSING_COLUMN
    content = ExcelExporter([ExcelColumn("name", "名称")]).write([{"name": "甲"}])
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert result.rows == []
    assert any(e.code == "MISSING_COLUMN" and e.column == "编码" for e in result.errors)


def test_empty_data_no_error() -> None:
    # 只表头无数据行 → 空结果，无错误（非 EMPTY，EMPTY 是连表头都没）
    content = ExcelExporter(_COLUMNS).write([])
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert result.rows == []
    assert result.errors == []


def test_completely_empty_workbook() -> None:
    content = _manual_xlsx([])  # 无任何行
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert any(e.code == "EMPTY" for e in result.errors)


def test_max_rows_exceeded() -> None:
    content = ExcelExporter(_COLUMNS).write([{"name": f"n{i}", "code": f"c{i}"} for i in range(5)])
    result = ExcelImporter(_SampleRow, _COLUMNS, max_rows=3).parse(content)
    assert len(result.rows) == 3
    assert any(e.code == "TOO_MANY_ROWS" for e in result.errors)


def test_blank_rows_skipped() -> None:
    content = _manual_xlsx(
        [["名称", "编码", "数量"], ["甲", "x1", 1], [None, None, None], ["乙", "x2", 2]]
    )
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(content)
    assert [r.data.name for r in result.rows] == ["甲", "乙"]  # 全空行跳过
    assert result.errors == []


# ---- 对抗审查回归：formula injection / 非法 xlsx ---------------------------


def test_writer_escapes_formula_injection() -> None:
    # 导出 cell 以 =/+/@ 开头 → 前缀单引号文本化，data_type='s'（字符串非公式 'f'），防 Excel 执行
    content = ExcelExporter(_COLUMNS).write([{"name": "=1+1", "code": "+cmd", "count": "@x"}])
    sheet = load_workbook(BytesIO(content)).active
    assert sheet is not None
    assert sheet.cell(row=2, column=1).data_type == "s"
    assert sheet.cell(row=2, column=1).value == "'=1+1"
    assert sheet.cell(row=2, column=2).value == "'+cmd"
    assert sheet.cell(row=2, column=3).value == "'@x"


def test_writer_normal_value_not_escaped() -> None:
    content = ExcelExporter(_COLUMNS).write([{"name": "工程师", "code": "eng", "count": "5"}])
    sheet = load_workbook(BytesIO(content)).active
    assert sheet is not None
    assert sheet.cell(row=2, column=1).value == "工程师"  # 正常值无前导单引号，往返一致


def test_invalid_xlsx_returns_business_error() -> None:
    # 损坏/非 xlsx 内容 → INVALID_FILE 业务错误，不冒泡 500
    result = ExcelImporter(_SampleRow, _COLUMNS).parse(b"this is not a zip/xlsx at all")
    assert result.rows == []
    assert any(e.code == "INVALID_FILE" for e in result.errors)
