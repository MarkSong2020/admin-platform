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

from sqlalchemy import BigInteger
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM model 的 Base 类。lazy-load 策略见模块 docstring。"""


class TenantMixin:
    """多租户业务表 mixin —— 带 ``tenant_id`` 列，是租户隔离机制的契约。

    任何继承 ``TenantMixin`` 的 mapped 类都会被 ``db/tenant_filter.py`` 的
    ``do_orm_execute`` 事件自动注入 ``tenant_id`` 过滤（见 ADR-A/E）：
    业务 session 无租户上下文时 fail-closed 抛错，带上下文时只见本租户行，
    显式 system / 平台超管上下文 bypass。

    平台级表（如 ``Tenant`` 本身、跨租户的注册表）**不**继承本 mixin。

    ``index=True``：tenant 维度是几乎所有业务查询的隐含过滤条件，单列索引是
    多租户共享库的基本盘；复合索引（``tenant_id`` + 业务键）由各表按需追加。
    """

    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
