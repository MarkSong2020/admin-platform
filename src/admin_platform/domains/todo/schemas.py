"""Todo DTO — /api/v1/todos 接口的请求 / 响应形状。

DTO 与 ORM model 独立。``model_config = from_attributes=True`` 让 Pydantic
能直接吃 SQLAlchemy 行；其它（校验、默认值、JSON alias）都放这里，避免业务
代码同时维护两套契约。

v0.5.1：``tag_ids`` 在 Create / Update 是**全量替换**语义（不是追加）。
``tags`` 在 Read 里回显已解析的 Tag DTO，让调用方看到实际关联的是哪些。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from admin_platform.domains.tag.schemas import TagRead
from admin_platform.domains.todo.models import TodoStatus


class TodoBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str = Field(min_length=1, max_length=200, description="简短、人类可读的概括")
    due_at: datetime | None = Field(default=None, description="可选截止时间（UTC）")


class TodoCreate(TodoBase):
    """POST payload — ``status`` 默认 OPEN，调用方不能预设。"""

    tag_ids: list[int] | None = Field(
        default=None,
        description=(
            "可选：创建时关联的 Tag id 列表。缺省 / None ⇒ 不关联任何 tag；空列表 ⇒ 明确不关联。"
        ),
    )


class TodoUpdate(BaseModel):
    """PATCH payload — 字段全可选（RFC 7396 merge 语义）。"""

    model_config = ConfigDict(from_attributes=True)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: TodoStatus | None = None
    due_at: datetime | None = None
    tag_ids: list[int] | None = Field(
        default=None,
        description=(
            "传值时**全量替换**当前 tag 集合。缺省 / None ⇒ 不动 tag 关联；空列表 ⇒ 清空所有 tag。"
        ),
    )


class TodoRead(TodoBase):
    id: int
    status: TodoStatus
    tags: list[TagRead] = Field(default_factory=list)


class TodoPage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)
    items: list[TodoRead]
    page: int
    size: int
    total: int
    total_pages: int
