"""User ORM 映射 — 表 ``users``。

表名用复数 ``users``（不是 ``user``）：①符合本仓 ``doc/standards/NAMING_CONVENTIONS.md``
的「表名 = URL 复数」约定（与 ``todos`` / ``tags`` 一致）；②``user`` 是 SQL 保留字
（PostgreSQL ``SELECT user`` 返回当前角色），用作表名后所有 raw SQL 都得永久 quoting，
``users`` 规避此坑。

``is_super_admin`` 是单租户下的超级管理员标志（bootstrap 信任根 + break-glass）：CLI
建首个超管时置 True；P1 RBAC 落地后由「超级管理员角色」接管，该布尔届时再评估去留。
``username`` 全局唯一。P0.9 不预留部门 / data-scope 字段（YAGNI，P1 RBAC 接 dept）。
"""

from __future__ import annotations

from sqlalchemy import Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.core.errors import register_unique_constraint
from admin_platform.db.base import Base, IdMixin, TimestampMixin


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        # P0.9 临时信任根约束：DB 硬保证【至多一个】超管（一次性 bootstrap，防 CLI 并发竞态）。
        # partial unique index 让 is_super_admin=true 的行在索引上唯一 → 至多一行 true。
        # P1 RBAC 接管超管模型（roadmap §7 Q6：布尔 vs 角色）后复审是否放宽。
        Index(
            "uq_users_one_super_admin",
            "is_super_admin",
            unique=True,
            postgresql_where=text("is_super_admin"),
        ),
    )

    username: Mapped[str] = mapped_column(String(64), comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(255), comment="密码哈希")
    nickname: Mapped[str] = mapped_column(String(64), default="", comment="昵称")
    status: Mapped[str] = mapped_column(String(16), default="active", comment="状态")
    is_super_admin: Mapped[bool] = mapped_column(default=False, comment="是否超级管理员")


# DB 唯一约束 → 业务错误码：并发预检都通过时第二个 INSERT 撞 uq_users_username →
# IntegrityError handler 据此把 500 翻成 409（与 service 的 USERNAME_DUPLICATE 同码）。
register_unique_constraint(
    "uq_users_username",
    "admin_platform.USERNAME_DUPLICATE",
    "Username already exists",
)
