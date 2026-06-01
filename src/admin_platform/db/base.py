"""SQLAlchemy 2.x declarative base。

Errata #7 —— async lazy 策略
---------------------------
默认策略：所有 ``relationship()`` 必须设 ``lazy="raise"``。
Eager loading 在 query 层用 ``selectinload`` / ``joinedload`` opt-in。
``AsyncSession`` 下的隐式 lazy load 会抛错，而不是悄悄发同步 query。

示例::

    from sqlalchemy import select
    from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

    class User(Base):
        __tablename__ = "users"

        id: Mapped[int] = mapped_column(primary_key=True)
        orders: Mapped[list["Order"]] = relationship(
            back_populates="user",
            lazy="raise",
        )

    # query 侧 —— eager loading 显式开启：
    stmt = select(User).options(selectinload(User.orders))
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM model 的 Base 类。lazy-load 策略见模块 docstring。"""
