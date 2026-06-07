"""Role ORM 映射 — 表 ``roles`` + 关联表 ``user_roles`` / ``role_depts``（RBAC 角色域）。

``roles`` 是全局角色（单租户无 tenant_id）：``code`` 全局唯一（前端 / 授权引用），``data_scope``
存 ``ScopeType.value``（5 范围之一，CheckConstraint 兜底防脏数据），多角色合并语义见
``domains.role.provider`` 的 O2 归一（spec §11 O2）。

关联表都用 ``IdMixin`` 代理键 + 复合唯一（对标本仓「每表 IdMixin」约定，非 RuoYi 复合主键）：
  * ``user_roles`` —— 用户 ↔ 角色多对多；``uq_user_roles`` 防重复绑定。
  * ``role_depts`` —— 角色 ↔ 部门（``CUSTOM_DEPT`` 自定义数据范围的部门集合）；``uq_role_depts``
    防重复。FK ``ondelete=CASCADE``：用户 / 角色 / 部门删除时自动清理绑定（绑定无独立价值）。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.core.errors import register_unique_constraint
from admin_platform.db.base import Base, IdMixin, TimestampMixin

# data_scope 允许值（= authz.ScopeType 的 5 个 value）。CheckConstraint 与 schemas 的 Literal
# 同源约束；tests/unit/test_role_schemas.py 守 Literal ↔ ScopeType 一致，防三处漂移。
_DATA_SCOPE_CHECK = (
    "data_scope IN ('all', 'custom_dept', 'self_dept', 'self_dept_and_below', 'self')"
)


class Role(Base, IdMixin, TimestampMixin):
    __tablename__ = "roles"

    __table_args__ = (
        UniqueConstraint("code", name="uq_roles_code"),
        # data_scope 枚举约束：只允许 5 个 ScopeType.value（与 schemas Literal 对齐，防脏数据）。
        CheckConstraint(_DATA_SCOPE_CHECK, name="ck_roles_data_scope"),
        # status 枚举约束：只允许 active / disabled（与 schemas Literal 对齐）。
        CheckConstraint("status IN ('active', 'disabled')", name="ck_roles_status"),
    )

    name: Mapped[str] = mapped_column(String(64), comment="角色名称")
    code: Mapped[str] = mapped_column(String(64), comment="角色编码")
    data_scope: Mapped[str] = mapped_column(
        String(32), default="self", comment="数据权限范围(ScopeType值)"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="显示顺序")
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )


class UserRole(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_roles"

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles"),
        Index("ix_user_roles_user", "user_id"),
        Index("ix_user_roles_role", "role_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), comment="用户ID"
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), comment="角色ID"
    )


class RoleDept(Base, IdMixin, TimestampMixin):
    __tablename__ = "role_depts"

    __table_args__ = (
        UniqueConstraint("role_id", "dept_id", name="uq_role_depts"),
        Index("ix_role_depts_role", "role_id"),
        Index("ix_role_depts_dept", "dept_id"),
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), comment="角色ID"
    )
    dept_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("depts.id", ondelete="CASCADE"), comment="部门ID"
    )


# DB 唯一约束 → 业务错误码：并发预检都通过时第二个 INSERT 撞 uq_roles_code →
# IntegrityError handler 据此把 500 翻成 409（与 service 的 role.CODE_DUPLICATE 同码）。
register_unique_constraint(
    "uq_roles_code",
    "role.CODE_DUPLICATE",
    "Role code already exists",
)
