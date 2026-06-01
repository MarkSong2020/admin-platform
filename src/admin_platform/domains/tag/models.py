"""Tag ORM 映射 — 表 ``tags``。

第二个 example domain（v0.5.1）。演示：
  * 「带唯一性的命名实体」最小形状 — ``name`` 是业务自然键，
    ``UniqueConstraint`` 在 DB 层强制唯一
  * 与 ``todo`` 的多对多关联，关联表为 ``todo_tags``（见
    ``migrations/versions/0003_create_tag_and_todo_tags.py``）

relationship 声明放在 ``Todo`` 那一侧（``Todo.tags``），本文件保持
不引入跨 domain import；tag 独立查询。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base


class Tag(Base):
    __tablename__ = "tags"

    __table_args__ = (UniqueConstraint("name", name="uq_tags_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    gmt_create: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    gmt_modified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# IntegrityError 兜底（v0.5.2 review fix）：service ``find_by_name`` 预检与
# DB INSERT 之间存在 race；并发请求同时通过预检会撞 ``uq_tags_name`` →
# IntegrityError → 通用 500 退化。注册下面的映射后由 ``core/errors.py`` 的
# IntegrityError handler 翻译成 409 ``TAG_NAME_DUPLICATE``。
from admin_platform.core.errors import register_unique_constraint  # noqa: E402

register_unique_constraint(
    "uq_tags_name",
    "admin_platform.TAG_NAME_DUPLICATE",
    "Tag name already exists",
)
