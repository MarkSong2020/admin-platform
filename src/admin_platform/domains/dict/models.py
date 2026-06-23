"""Dict ORM 映射 —— 表 ``dict_types`` + ``dict_data``（数据字典，对标 RuoYi sys_dict_type/data）。

一个字典类型（``dict_types``）下挂多条字典数据（``dict_data``，label/value 对），前端按 ``type``
拉数据渲染下拉 / 状态标签。关联决策（Codex PK 收敛）：``dict_data.dict_type_id`` 外键到代理键
``dict_types.id`` + ``ondelete RESTRICT``（**非** type 字符串、**非** 无 FK）——改 type 不触子表；
删有数据的类型由 service 预检拦（409 ``dict.TYPE_HAS_DATA``），不走 DB 静默级联删配置事实。

``type`` 创建后不可改（service 层 PATCH 拒绝）；同类型内 ``value`` 唯一；单默认值由 service 层
「设默认时清同类型其它默认」保证（spec §2.2）。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.core.errors import register_unique_constraint
from admin_platform.db.base import Base, IdMixin, TimestampMixin


class DictType(Base, IdMixin, TimestampMixin):
    __tablename__ = "dict_types"

    __table_args__ = (
        UniqueConstraint("type", name="uq_dict_types_type"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_dict_types_status"),
        CheckConstraint("is_builtin IN (0, 1)", name="ck_dict_types_is_builtin_bool"),
    )

    name: Mapped[str] = mapped_column(String(64), comment="字典名称")
    type: Mapped[str] = mapped_column(
        String(128), comment="字典类型(全局唯一标识，如 sys_user_sex)"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否系统内置(内置禁删)"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class DictData(Base, IdMixin, TimestampMixin):
    __tablename__ = "dict_data"

    __table_args__ = (
        # 同一类型内 value 唯一（跨类型可复用）。
        UniqueConstraint("dict_type_id", "value", name="uq_dict_data_type_value"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_dict_data_status"),
        CheckConstraint("is_default IN (0, 1)", name="ck_dict_data_is_default_bool"),
        # 单默认值不变式（DB 兜底，对抗审查 B1）：MySQL 生成列 + unique 利用「多个 NULL 不冲突」
        # 实现同类型至多一行 is_default=true。
        Index(
            "uq_dict_data_one_default_per_type",
            "dict_type_id",
            "default_unique_key",
            unique=True,
        ),
        # 常按类型 + 排序拉某类型的全部数据（消费契约）。
        Index("ix_dict_data_type_sort", "dict_type_id", "sort_order", "id"),
    )

    dict_type_id: Mapped[int] = mapped_column(
        BigInteger,
        # FK 显式命名（对抗审查 S1）：删类型与并发建数据竞态时 RESTRICT 抛 FK 违例，注册名 →
        # 业务码 dict.TYPE_HAS_DATA，与 service 预检路径同码（否则退化为 framework.CONFLICT）。
        ForeignKey("dict_types.id", ondelete="RESTRICT", name="fk_dict_data_type_id"),
        comment="字典类型ID(关联 dict_types.id)",
    )
    label: Mapped[str] = mapped_column(String(128), comment="字典标签(显示文本)")
    value: Mapped[str] = mapped_column(String(128), comment="字典键值")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="显示顺序")
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否默认(同类型仅一条)"
    )
    default_unique_key: Mapped[int | None] = mapped_column(
        Integer,
        Computed("CASE WHEN is_default = 1 THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
        comment="MySQL生成列: is_default=true时为1,否则NULL",
    )
    css_class: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="前端样式(CSS class)"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


# DB 约束名 → 业务错误码（IntegrityError handler 据此把竞态 500 翻成 409；含 unique / FK /
# 生成列唯一索引）。错误码常量见 service.py。
register_unique_constraint(
    "uq_dict_types_type",
    "dict.TYPE_DUPLICATE",
    "Dict type already exists",
)
register_unique_constraint(
    "uq_dict_data_type_value",
    "dict.DATA_DUPLICATE",
    "Dict data value already exists in this type",
)
# 单默认值生成列唯一索引竞态兜底 → dict.DEFAULT_DUPLICATE（对抗审查 B1）。
register_unique_constraint(
    "uq_dict_data_one_default_per_type",
    "dict.DEFAULT_DUPLICATE",
    "Dict type already has a default data item",
)
# 删类型撞 FK RESTRICT（与并发建数据竞态）→ dict.TYPE_HAS_DATA，与 service 预检同码（对抗审查 S1）。
register_unique_constraint(
    "fk_dict_data_type_id",
    "dict.TYPE_HAS_DATA",
    "Dict type still has data",
)
