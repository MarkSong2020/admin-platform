"""Excel 导入导出通用 DTO（无 domain 知识，纯叶子机制）。

``RowError`` 命名避开内置 ``ImportError``。行号 ``row`` 为 1-based 含表头（数据首行=2），
便于用户对照 Excel 定位。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class ExcelColumn:
    """列定义：Pydantic 字段名 ↔ Excel 列头（中文）。"""

    field: str
    header: str
    required: bool = True


@dataclass(frozen=True)
class RowError:
    """行级导入错误。``column`` 为列头；``None`` 表示整行级（如缺列头/超行数）。"""

    row: int
    column: str | None
    code: str
    message: str


@dataclass(frozen=True)
class ParsedRow[T: BaseModel]:
    """通过校验的一行：保留 Excel 行号（供 service 后续聚合校验——文件内/库内重复——定位）。"""

    row: int
    data: T


@dataclass
class ImportResult[T: BaseModel]:
    """解析结果：通过校验的行（带行号）+ 全量错误（坏行不阻断后续）。"""

    rows: list[ParsedRow[T]]
    errors: list[RowError]
