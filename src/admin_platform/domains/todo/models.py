"""Todo ORM 映射 — 表 ``todos``。

本 domain 是新业务模块的**教科书蓝本**。在 ``make new-module`` 的最小骨架
（单 ``name`` 列）之上扩展出：

  * ``title`` + ``UniqueConstraint`` — 演示「在 DB 层加业务不变式 + service
    层做预检」的模式
  * ``status`` enum 映射成 Postgres native ENUM — 类型化状态机（而非自由字符串）
  * ``due_at`` nullable timestamp — 演示 Optional 列声明
  * **`tags` 多对多关联 Tag（v0.5.1）** — 演示 ``lazy="raise"`` +
    ``selectinload`` 模式：任何访问 ``todo.tags`` 但没显式预加载的代码
    都会**抛错**，而不是悄悄发出 N+1 query。

每条选择的「为何」详见 ``doc/architecture/EXAMPLE_DOMAIN.md``。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from admin_platform.db.base import Base
from admin_platform.domains.tag.models import Tag

# todo↔tag 多对多的关联表。
# 定义为 Core ``Table``（不是 ORM-mapped class），因为边上除了两个 FK
# 列 + 复合 PK 之外没有业务行为 —— 这是 SA 推荐的「纯关联表」用法。
# 物理表由 migration 0003 创建；这里的声明把它注册到 ``Base.metadata``，
# 让 alembic autogenerate 看到它，并允许 ``relationship(secondary=...)``
# 直接引用对象（而非字符串名）。
todo_tags = Table(
    "todo_tags",
    Base.metadata,
    Column(
        "todo_id",
        Integer,
        ForeignKey("todos.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        Integer,
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # 两个 FK index 与 migration 0003 对齐 —— 必须显式声明，否则
    # ``alembic check`` 会检测到「metadata 没要这两个 index」并把它们
    # 标成 remove_index drift（v0.5.1 GHA 抓到此漂移）。
    Index("ix_todo_tags_todo_id", "todo_id"),
    Index("ix_todo_tags_tag_id", "tag_id"),
)


class TodoStatus(StrEnum):
    """Todo 生命周期状态。``StrEnum``（3.11+）⇒ JSON 序列化为字面 name。"""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class Todo(Base):
    __tablename__ = "todos"

    __table_args__ = (
        UniqueConstraint("title", name="uq_todos_title"),
        Index("ix_todos_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column()
    status: Mapped[TodoStatus] = mapped_column(
        Enum(TodoStatus, name="todo_status", native_enum=True),
        default=TodoStatus.OPEN,
        server_default=TodoStatus.OPEN.value,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gmt_create: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    gmt_modified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 通过 ``todo_tags`` 关联表与 Tag 建立多对多。
    #
    # ``lazy="raise"`` — 访问 ``todo.tags`` 前没显式 ``selectinload(Todo.tags)``
    # 会抛 ``StatementError``，而不是悄悄按行发 SELECT（典型的 async N+1 陷阱）。
    # repository 所有读路径都自动加 ``selectinload``；绕过 repository 的
    # 调用方需要自己加。详见 ``db/base.py`` 的项目级 lazy 策略。
    tags: Mapped[list[Tag]] = relationship(
        Tag,
        secondary=todo_tags,
        lazy="raise",
    )


# IntegrityError 兜底（v0.5.2 review fix）：service 层 ``find_by_title`` 预检与
# DB INSERT 之间存在 race；并发请求同时通过预检会撞 ``uq_todos_title`` →
# asyncpg UniqueViolationError → SQLAlchemy IntegrityError → 通用 Exception
# handler 退化成 500。注册下面的映射后由 ``core/errors.py`` 的 IntegrityError
# handler 翻译成 409 ``TODO_TITLE_DUPLICATE``，与 service 层预检的 happy
# path 返回相同的 typed 错误码。
from admin_platform.core.errors import register_unique_constraint  # noqa: E402

register_unique_constraint(
    "uq_todos_title",
    "admin_platform.TODO_TITLE_DUPLICATE",
    "Todo title already exists",
)
