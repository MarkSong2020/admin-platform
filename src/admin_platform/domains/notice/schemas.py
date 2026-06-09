"""Notice DTO —— /api/v1/notices 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

``notice_type`` / ``status`` 用 ``Literal`` 限定，与 ``models.Notice`` 的 CheckConstraint 同源。
``NoticeUpdate`` 全字段可选（PATCH merge 语义）。``content`` 为富文本，**后端不净化**——
渲染期净化是 P6 前端职责（spec §2.4）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NoticeType = Literal["notification", "announcement"]
StatusValue = Literal["active", "disabled"]


class NoticeCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    title: str = Field(min_length=1, max_length=128, description="公告标题")
    notice_type: NoticeType = Field(description="公告类型（notification / announcement）")
    content: str = Field(min_length=1, description="公告内容（富文本）")
    status: StatusValue = Field(default="active", description="状态（active / disabled）")
    remark: str | None = Field(default=None, max_length=255, description="备注")


class NoticeUpdate(BaseModel):
    """PATCH payload —— 字段全可选（merge 语义）。"""

    model_config = ConfigDict(from_attributes=True)
    title: str | None = Field(default=None, min_length=1, max_length=128, description="公告标题")
    notice_type: NoticeType | None = Field(default=None, description="公告类型")
    content: str | None = Field(default=None, min_length=1, description="公告内容")
    status: StatusValue | None = Field(default=None, description="状态")
    remark: str | None = Field(default=None, max_length=255, description="备注")


class NoticeRead(BaseModel):
    """响应 DTO —— 含生命周期时间戳。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    notice_type: str
    content: str
    status: str
    remark: str | None
    created_at: datetime
    updated_at: datetime


class NoticePage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[NoticeRead]
    page: int
    size: int
    total: int
    total_pages: int
