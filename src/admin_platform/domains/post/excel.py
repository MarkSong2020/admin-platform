"""Post 域 Excel 导入导出绑定适配器（列定义）。

通用机制（``admin_platform.excel``）不认识 Post；本模块把 Post 字段映射到 Excel 列头。
导入行 schema 直接复用 ``PostCreate``（字段 name/code/sort_order/status 一致）——Pydantic 从
canonical str coerce int/Literal，无需单独 row schema。
"""

from __future__ import annotations

from admin_platform.excel import ExcelColumn

POST_EXCEL_COLUMNS = [
    ExcelColumn("name", "岗位名称"),
    ExcelColumn("code", "岗位编码"),
    ExcelColumn("sort_order", "显示顺序", required=False),
    ExcelColumn("status", "状态", required=False),
]
