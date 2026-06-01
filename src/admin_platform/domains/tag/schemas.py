"""Tag DTO — /api/v1/tags 接口的请求 / 响应形状。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TagBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str = Field(min_length=1, max_length=64, description="Tag 标签文本（业务唯一键）")


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=64)


class TagRead(TagBase):
    id: int


class TagPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[TagRead]
    page: int
    size: int
    total: int
    total_pages: int
