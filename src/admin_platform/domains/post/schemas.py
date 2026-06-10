"""Post DTO —— /api/v1/posts 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

岗位是扁平域（无 data_scope、无树），故比 ``RoleCreate/Update/Read/Page`` 更简单：只有
name / code / sort_order / status。``status`` 用 ``Literal`` 限定为 active / disabled，与
``models.Post`` 的 ``ck_posts_status`` CheckConstraint 同源。``PostUpdate`` 全字段可选
（PATCH merge 语义）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StatusValue = Literal["active", "disabled"]


class PostCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    name: str = Field(min_length=1, max_length=64, description="岗位名称")
    code: str = Field(min_length=1, max_length=64, description="岗位编码（全局唯一）")
    sort_order: int = Field(default=0, ge=0, le=999999, description="显示顺序（防 int4 越界）")
    status: StatusValue = Field(default="active", description="岗位状态（active / disabled）")


class PostUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。"""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=64, description="岗位名称")
    code: str | None = Field(default=None, min_length=1, max_length=64, description="岗位编码")
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
