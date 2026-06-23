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
``docs/standards/DATA_MODELING.md``。
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, DateTime, func, text
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """统一 UTC datetime 类型。

    MySQL ``DATETIME`` 不保存时区信息；本类型在写入时统一折算为 UTC，MySQL/SQLite
    落库为 naive UTC，读回时统一补 ``tzinfo=UTC``。PostgreSQL 仍使用 timezone-aware
    列，便于本迁移分支过渡期兼容旧环境。
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        timezone = dialect.name == "postgresql"
        return dialect.type_descriptor(DateTime(timezone=timezone))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        value_utc = self._to_utc_aware(value)
        if dialect.name == "postgresql":
            return value_utc
        return value_utc.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return self._to_utc_aware(value)

    @staticmethod
    def _to_utc_aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """所有 ORM model 的 Base 类。lazy-load 策略见模块 docstring。"""


class IdMixin:
    """① 身份圈：BIGINT 代理键（DATA_MODELING.md §1.1）。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="主键")


class TimestampMixin:
    """③ 生命周期圈：created_at / updated_at（DATETIME, UTC, DB 权威）。

    ``updated_at`` 的 ``onupdate`` 仅在 ORM flush 触发；raw SQL ``UPDATE`` 不更新它，
    需 DB 级保证时另加触发器。
    """

    __mapper_args__: ClassVar[dict[str, bool]] = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=text("CURRENT_TIMESTAMP"), comment="创建时间(UTC)"
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
        comment="更新时间(UTC, ORM flush 触发)",
    )
