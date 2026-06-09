"""Dict DTO —— /api/v1/dict 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

两个资源：字典类型（``DictType*``）+ 字典数据（``DictData*``）。``type`` 创建后不可改
（``DictTypeUpdate`` 不含）；``dict_type_id`` 在数据创建时定，不可改（``DictDataUpdate`` 不含）。
``status`` 用 ``Literal`` 与 models CheckConstraint 同源。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StatusValue = Literal["active", "disabled"]


# ---- 字典类型 dict_types ----------------------------------------------------


class DictTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="字典名称")
    type: str = Field(min_length=1, max_length=128, description="字典类型（全局唯一）")
    status: StatusValue = Field(default="active", description="状态（active / disabled）")
    is_builtin: bool = Field(default=False, description="是否系统内置（内置禁删）")
    remark: str | None = Field(default=None, max_length=255, description="备注")


class DictTypeUpdate(BaseModel):
    """PATCH —— ``type`` 不可改（key 改名破坏前端契约）；``is_builtin`` 可切换（解保护后才能删，
    对抗审查 S2，避免「建成内置后永久不可删」的不可逆 footgun）。"""

    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=64, description="字典名称")
    status: StatusValue | None = Field(default=None, description="状态")
    is_builtin: bool | None = Field(
        default=None, description="是否系统内置（内置禁删，可切换解保护）"
    )
    remark: str | None = Field(default=None, max_length=255, description="备注")


class DictTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str
    status: str
    is_builtin: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class DictTypePage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    items: list[DictTypeRead]
    page: int
    size: int
    total: int
    total_pages: int


# ---- 字典数据 dict_data -----------------------------------------------------


class DictDataCreate(BaseModel):
    dict_type_id: int = Field(description="字典类型ID")
    label: str = Field(min_length=1, max_length=128, description="字典标签")
    value: str = Field(min_length=1, max_length=128, description="字典键值")
    sort_order: int = Field(default=0, description="显示顺序")
    status: StatusValue = Field(default="active", description="状态")
    is_default: bool = Field(default=False, description="是否默认（同类型仅一条）")
    css_class: str | None = Field(default=None, max_length=128, description="前端样式 CSS class")
    remark: str | None = Field(default=None, max_length=255, description="备注")


class DictDataUpdate(BaseModel):
    """PATCH —— ``dict_type_id`` 不可改（数据不跨类型迁移）。"""

    model_config = ConfigDict(from_attributes=True)
    label: str | None = Field(default=None, min_length=1, max_length=128, description="字典标签")
    value: str | None = Field(default=None, min_length=1, max_length=128, description="字典键值")
    sort_order: int | None = Field(default=None, description="显示顺序")
    status: StatusValue | None = Field(default=None, description="状态")
    is_default: bool | None = Field(default=None, description="是否默认")
    css_class: str | None = Field(default=None, max_length=128, description="前端样式 CSS class")
    remark: str | None = Field(default=None, max_length=255, description="备注")


class DictDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dict_type_id: int
    label: str
    value: str
    sort_order: int
    status: str
    is_default: bool
    css_class: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class DictDataPage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    items: list[DictDataRead]
    page: int
    size: int
    total: int
    total_pages: int
