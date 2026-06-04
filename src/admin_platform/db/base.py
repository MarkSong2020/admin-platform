"""SQLAlchemy 2.x declarative base 与通用字段 mixin。

Errata #7 —— async lazy 策略
---------------------------
默认策略：所有 ``relationship()`` 必须设 ``lazy="raise"``。
Eager loading 在 query 层用 ``selectinload`` / ``joinedload`` opt-in。
``AsyncSession`` 下的隐式 lazy load 会抛错，而不是悄悄发同步 query。

示例::

    from sqlalchemy import select
    from sqlalchemy.orm import Mapped, relationship, selectinload

    class User(Base, IdMixin, TimestampMixin):
        __tablename__ = "users"

        orders: Mapped[list["Order"]] = relationship(
            back_populates="user",
            lazy="raise",
        )

    # query 侧 —— eager loading 显式开启：
    stmt = select(User).options(selectinload(User.orders))

通用字段 mixin
-------------
``IdMixin`` / ``TimestampMixin`` 提供数据建模标准的基线同心圈（身份 + 生命周期，
与模板 ``python-web-service-template`` 同款）。完整规约见
``doc/standards/DATA_MODELING.md``。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM model 的 Base 类。lazy-load 策略见模块 docstring。"""


class IdMixin:
    """① 身份圈：BIGINT 代理键（DATA_MODELING.md §1.1）。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")


class TimestampMixin:
    """③ 生命周期圈：created_at / updated_at（timestamptz, UTC, DB 权威）。

    ``updated_at`` 的 ``onupdate`` 仅在 ORM flush 触发；raw SQL ``UPDATE`` 不更新它，
    需 DB 级保证时另加触发器。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间(UTC)"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间(UTC, ORM flush 触发)",
    )
