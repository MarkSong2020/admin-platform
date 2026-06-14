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


class ExcelTooLargeError(Exception):
    """解压前中央目录预检超限（zip bomb / inflated XML DoS）。

    excel 是纯叶子（C10：禁 import core/fastapi），不能抛 AppError；抛此叶子自有异常，
    由 domain 绑定层映射成 413 业务错误。``reason`` 标明触发哪条阈值（供调用方记审计/日志），
    不向最终用户透露具体声明大小（防探测）。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
