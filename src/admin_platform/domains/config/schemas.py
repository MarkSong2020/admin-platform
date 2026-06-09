"""Config DTO —— /api/v1/configs 的请求 / 响应形状。纯 Pydantic（C5/C6：不碰 models / sqlalchemy）。

``config_key`` / ``is_builtin`` 创建后不可改（``ConfigUpdate`` 不含——key 改名破坏消费契约、
``is_builtin`` 是保护标记不可经 PATCH 翻转）。``ConfigValueRead`` 是消费契约端点的瘦响应。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConfigCreate(BaseModel):
    """POST payload。id / 时间戳由 DB 维护，不可由客户端设。"""

    name: str = Field(min_length=1, max_length=128, description="参数名称")
    config_key: str = Field(min_length=1, max_length=128, description="参数键名（全局唯一）")
    config_value: str = Field(description="参数键值（非敏感运营参数）")
    is_builtin: bool = Field(default=False, description="是否系统内置（内置禁删）")
    remark: str | None = Field(default=None, max_length=255, description="备注")


class ConfigUpdate(BaseModel):
    """PATCH payload —— name/value/remark/is_builtin 可改（``config_key`` 创建后不可变）。

    ``is_builtin`` 可切换（对抗审查 S2）：删内置参数前先 PATCH ``is_builtin=false`` 解保护再删——
    避免「建成内置后永久不可删」的不可逆 footgun，同时保留「误删保护」语义（对标 RuoYi config_type 可编辑）。
    """

    model_config = ConfigDict(from_attributes=True)
    name: str | None = Field(default=None, min_length=1, max_length=128, description="参数名称")
    config_value: str | None = Field(default=None, description="参数键值")
    is_builtin: bool | None = Field(
        default=None, description="是否系统内置（内置禁删，可切换解保护）"
    )
    remark: str | None = Field(default=None, max_length=255, description="备注")


class ConfigRead(BaseModel):
    """响应 DTO —— 含生命周期时间戳。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    config_key: str
    config_value: str
    is_builtin: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class ConfigValueRead(BaseModel):
    """消费契约端点（``GET /configs/value/{key}``）的瘦响应——读穿 DB 取最新值（热更新）。"""

    model_config = ConfigDict(from_attributes=True)
    config_key: str
    config_value: str


class ConfigPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[ConfigRead]
    page: int
    size: int
    total: int
    total_pages: int
