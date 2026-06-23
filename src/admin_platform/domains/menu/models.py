"""Menu ORM 映射 — 表 ``menus``（菜单树，邻接表）+ 关联表 ``role_menus``（角色 ↔ 菜单）。

菜单树镜像 dept 树存储（O1：邻接表 ``parent_id`` 自引用，几百节点、深度 <10，闭包表 / 路径
枚举属过度工程）。查子孙用 SQL recursive CTE（见 ``repository.py``），删父防有子复用。
``parent_id`` 外键 ``ondelete=RESTRICT``：DB 层硬保证有子菜单时禁删父；service 另做友好 409
预检（``menu.HAS_CHILDREN``）。

三类菜单（对标若依 ``sys_menu.menu_type``）：``M`` 目录 / ``C`` 菜单 / ``F`` 按钮。目录/菜单
进前端动态路由（``getRouters``，见 ``routers.build_routers``）；按钮只承载 ``perms`` 权限标识、
不进路由树。``visible=False`` 的菜单仍下发但 ``getRouters`` 标 ``hidden=true``（注册路由但侧边栏
不显示）；``status!=active`` 的菜单不下发。

与 dept/role 不同：菜单**无业务唯一编码**（``code``），靠 ``id`` + 树结构标识，故不注册
``register_unique_constraint``、不建 ``uq``。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TimestampMixin


class Menu(Base, IdMixin, TimestampMixin):
    __tablename__ = "menus"

    __table_args__ = (
        # menu_type 枚举约束：只允许 M(目录)/C(菜单)/F(按钮)（与 schemas Literal 对齐，防脏数据）。
        CheckConstraint("menu_type IN ('M', 'C', 'F')", name="ck_menus_menu_type"),
        # status 枚举约束：只允许 active / disabled（与 schemas Literal 对齐）。
        CheckConstraint("status IN ('active', 'disabled')", name="ck_menus_status"),
        CheckConstraint("visible IN (0, 1)", name="ck_menus_visible_bool"),
        # 按父节点取子节点并排序的复合索引（建树 / 同级排序的主查询路径）。
        Index("ix_menus_parent_sort", "parent_id", "sort_order", "id"),
        # seed_key 唯一：MySQL unique 允许多个 NULL，天然只约束非空 seed_key。
        Index(
            "uq_menus_seed_key",
            "seed_key",
            unique=True,
        ),
    )

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("menus.id", ondelete="RESTRICT"),
        nullable=True,
        comment="父菜单ID(NULL=根)",
    )
    name: Mapped[str] = mapped_column(String(64), comment="菜单名称")
    menu_type: Mapped[str] = mapped_column(String(8), comment="类型(M目录/C菜单/F按钮)")
    path: Mapped[str] = mapped_column(String(255), default="", comment="路由地址(按钮类可空串)")
    component: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="前端组件路径(目录/按钮可空)"
    )
    perms: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="权限标识(如system:user:list,目录类可空)"
    )
    icon: Mapped[str] = mapped_column(String(64), default="", comment="菜单图标")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="显示顺序")
    visible: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否显示(False=侧边栏隐藏)"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )
    seed_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="seed稳定键(非空=内置菜单,NULL=用户自建)"
    )


class RoleMenu(Base, IdMixin, TimestampMixin):
    """角色 ↔ 菜单多对多（镜像 ``role_depts``：IdMixin 代理键 + 复合唯一，非复合主键）。

    FK ``ondelete=CASCADE``：角色 / 菜单删除时自动清理绑定（绑定无独立价值）。``uq_role_menus``
    防重复绑定；两列各加索引（按角色取菜单 / 按菜单反查角色）。
    """

    __tablename__ = "role_menus"

    __table_args__ = (
        UniqueConstraint("role_id", "menu_id", name="uq_role_menus"),
        Index("ix_role_menus_role", "role_id"),
        Index("ix_role_menus_menu", "menu_id"),
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), comment="角色ID"
    )
    menu_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("menus.id", ondelete="CASCADE"), comment="菜单ID"
    )
