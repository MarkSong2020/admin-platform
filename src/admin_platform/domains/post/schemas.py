"""Post DTO —— /api/v1/posts 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

岗位是扁平域（无 data_scope、无树），故比 ``RoleCreate/Update/Read/Page`` 更简单：只有
name / code / sort_order / status。``status`` 用 ``Literal`` 限定为 active / disabled，与
``models.Post`` 的 ``ck_posts_status`` CheckConstraint 同源。``PostUpdate`` 全字段可选
（PATCH merge 语义）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

StatusValue = Literal["active", "disabled"]

# openpyxl 视为非法的控制字符（0x00-08 / 0x0b-0c / 0x0e-1f；不含合法的 \t \n \r）。岗位名/编码含这些
# 字符会让 Excel 导出在 ``worksheet.append`` 抛 IllegalCharacterError（存储型 DoS，对抗审查 R5：低权限
# 用户投毒一行即可让全表导出对所有人永久 500）。L1 入口在此拒绝（import 行→VALIDATION RowError /
# create→422）；``excel/writer`` 另有剥除兜底，两层 defense-in-depth。
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# BMP 非字符 U+FFFE/U+FFFF（chr() 避免源码含字面非字符）——XML 1.0 Char 上限 U+FFFD，能过控制字符
# 正则但进库后让导出生成损坏 .xlsx（对抗审查 R5 skeptic 扩面发现），L1 同源拒绝。
_NONCHARS = frozenset((chr(0xFFFE), chr(0xFFFF)))


def _reject_control_chars(value: str) -> str:
    if _CONTROL_CHARS_RE.search(value) or _NONCHARS.intersection(value):
        raise ValueError("不能包含 Excel 非法字符")
    return value


CleanText = Annotated[str, AfterValidator(_reject_control_chars)]

# 排序方向取值（对标 RuoYi isAsc；与 core.pagination.OrderValue 同源字面量）。
OrderValue = Literal["asc", "desc"]


class PostListQuery(BaseModel):
    """岗位列表过滤 / 排序参数（对标 RuoYi 岗位管理查询；全可选）。

    纯输入 DTO（不进响应，不改 ``PostPage`` 形状）。``code`` / ``name`` 模糊匹配，``status`` 精确；
    ``order_by`` 是逻辑字段名，repository 用 allowlist 映射 ORM Column（防注入）。
    """

    code: str | None = Field(default=None, max_length=64, description="岗位编码模糊匹配")
    name: str | None = Field(default=None, max_length=64, description="岗位名称模糊匹配")
    status: StatusValue | None = Field(default=None, description="岗位状态（active / disabled）")
    order_by: str | None = Field(
        default=None, max_length=64, description="排序字段（sort_order / created_at / id）"
    )
    order: OrderValue = Field(default="desc", description="排序方向（asc / desc，默认 desc）")
    # 分页参数折进本模型：query-model 与独立标量 Query 参数混用时，FastAPI 不再把本模型展开为
    # query 参数，而是把整个模型参数当成必填且无法从 query 填充的字段，canonical 请求遂报 422
    # （错误是「该模型参数 missing」，非「page/size 被当额外参数拒」——query-model 实测并不
    # forbid 额外参数）。故 page/size 必须内联于此。约束与 core.pagination.PageQ/SizeQ 值同源。
    page: int = Field(
        default=1, ge=1, le=10000, description="页码（从 1 开始，上限 10000 防深分页 DoS）"
    )
    size: int = Field(default=20, ge=1, le=100, description="每页条数（上限 100）")


class PostCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    name: CleanText = Field(min_length=1, max_length=64, description="岗位名称")
    code: CleanText = Field(min_length=1, max_length=64, description="岗位编码（全局唯一）")
    sort_order: int = Field(default=0, ge=0, le=999999, description="显示顺序（防 int4 越界）")
    status: StatusValue = Field(default="active", description="岗位状态（active / disabled）")


class PostUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。"""

    model_config = ConfigDict(from_attributes=True)
    name: CleanText | None = Field(
        default=None, min_length=1, max_length=64, description="岗位名称"
    )
    code: CleanText | None = Field(
        default=None, min_length=1, max_length=64, description="岗位编码"
    )
    sort_order: int | None = Field(
        default=None, ge=0, le=999999, description="显示顺序（防 int4 越界）"
    )
    status: StatusValue | None = Field(default=None, description="岗位状态（active / disabled）")


class PostRead(BaseModel):
    """响应 DTO —— 含生命周期时间戳。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    sort_order: int
    status: str
    created_at: datetime
    updated_at: datetime


class PostPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[PostRead]
    page: int
    size: int
    total: int
    total_pages: int


class PostImportRowError(BaseModel):
    """导入行级错误（业务结果，随 200 返回——非系统错误，不走 ProblemDetail 脱敏通道）。"""

    row: int = Field(description="Excel 行号（含表头，数据首行=2）")
    column: str | None = Field(default=None, description="列头；None=整行级")
    code: str = Field(
        description="错误码（VALIDATION/DUPLICATE_IN_FILE/DB_DUPLICATE/MISSING_COLUMN/...）"
    )
    message: str = Field(description="错误说明")


class PostImportSummary(BaseModel):
    """Excel 导入结果（全有全无）：errors 非空则 imported=0 且未写任何行。

    导入校验错误是**业务结果**（用户数据反馈），随 200 返回 errors 全量；不走 422/ProblemDetail
    （系统错误通道，errors 受 debug 脱敏，生产看不到行级反馈）。
    """

    imported: int = Field(description="成功导入的岗位数（有错误时为 0）")
    errors: list[PostImportRowError] = Field(
        default_factory=list, description="全量行级错误（非空则未写入任何行）"
    )
