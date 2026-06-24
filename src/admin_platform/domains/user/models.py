"""User ORM 映射 — 表 ``users``。

表名用复数 ``users``（不是 ``user``）：①符合本仓 ``docs/standards/NAMING_CONVENTIONS.md``
的「表名 = URL 复数」约定（与 ``depts`` / ``roles`` 等域一致）；②``user`` 是 SQL 保留字
（PostgreSQL ``SELECT user`` 返回当前角色），用作表名后所有 raw SQL 都得永久 quoting，
``users`` 规避此坑。

``is_super_admin`` 是单租户下的超级管理员标志（bootstrap 信任根 + break-glass）：CLI
建首个超管时置 True；P1 RBAC 落地后由「超级管理员角色」接管，该布尔届时再评估去留。
``username`` 全局唯一。

``dept_id`` 是 P1 RBAC 接入的所属部门（数据权限「本部门」/「本部门及以下」范围的载体）：
FK ``depts.id`` ``ondelete=SET NULL``（部门删除后用户落为「无部门」而非级联删用户）；nullable
（未分配部门的用户 / 超管可为空，此时部门类 data_scope 贡献空集 → 安全 deny，见
``domains.role.provider`` O2 归一）。
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


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        # status 枚举约束（Codex 系统级 PK：与 dept/role/menu/post 同源，防脏状态被隐式停用）。
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        CheckConstraint("is_super_admin IN (0, 1)", name="ck_users_is_super_admin_bool"),
        # P0.9 临时信任根约束：MySQL 生成列 + unique 利用「多个 NULL 不冲突」实现条件唯一。
        # P1 RBAC 接管超管模型（roadmap §7 Q6：布尔 vs 角色）后复审是否放宽。
        Index(
            "uq_users_one_super_admin",
            "super_admin_unique_key",
            unique=True,
        ),
        # dept_id 索引（Codex 深审）：部门删除 ON DELETE SET NULL 需按 dept_id 定位用户行；
        # 后续 data_scope「本部门」按 dept_id 查用户也走它。无索引则两者全表扫 + SET NULL 取锁慢。
        Index("ix_users_dept_id", "dept_id"),
    )

    username: Mapped[str] = mapped_column(String(64), comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(255), comment="密码哈希")
    nickname: Mapped[str] = mapped_column(String(64), default="", comment="昵称")
    status: Mapped[str] = mapped_column(String(16), default="active", comment="状态")
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否超级管理员")
    super_admin_unique_key: Mapped[int | None] = mapped_column(
        Integer,
        Computed("CASE WHEN is_super_admin = 1 THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
        comment="MySQL生成列: is_super_admin=true时为1,否则NULL",
    )
    dept_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("depts.id", ondelete="SET NULL"),
        nullable=True,
        comment="所属部门ID",
    )


# DB 唯一约束 → 业务错误码：并发预检都通过时第二个 INSERT 撞 uq_users_username →
# IntegrityError handler 据此把 500 翻成 409（与 service 的 USERNAME_DUPLICATE 同码）。
register_unique_constraint(
    "uq_users_username",
    "user.USERNAME_DUPLICATE",
    "Username already exists",
)
