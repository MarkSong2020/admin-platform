"""Post ORM 映射 —— 表 ``posts`` + 关联表 ``user_posts``（RBAC 岗位域）。

``posts`` 是全局岗位（单租户无 tenant_id，扁平无树）：``code`` 全局唯一（前端 / 引用），
``status`` 用 CheckConstraint 兜底防脏数据（与 schemas 的 ``Literal`` 同源约束）。岗位无
data_scope（数据权限只挂角色），故比 role 更简单。

关联表 ``user_posts`` 用 ``IdMixin`` 代理键 + 复合唯一（对标本仓「每表 IdMixin」约定，
镜像 role 域 ``user_roles``，非 RuoYi 复合主键）：用户 ↔ 岗位多对多；``uq_user_posts``
防重复绑定。FK ``ondelete=CASCADE``：用户 / 岗位删除时自动清理绑定（绑定无独立价值）。
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


class Post(Base, IdMixin, TimestampMixin):
    __tablename__ = "posts"

    __table_args__ = (
        UniqueConstraint("code", name="uq_posts_code"),
        # status 枚举约束：只允许 active / disabled（与 schemas Literal 对齐，防脏数据）。
        CheckConstraint("status IN ('active', 'disabled')", name="ck_posts_status"),
    )

    name: Mapped[str] = mapped_column(String(64), comment="岗位名称")
    code: Mapped[str] = mapped_column(String(64), comment="岗位编码")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="显示顺序")
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )


class UserPost(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_posts"

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_user_posts"),
        Index("ix_user_posts_user", "user_id"),
        Index("ix_user_posts_post", "post_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), comment="用户ID"
    )
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), comment="岗位ID"
    )


# DB 唯一约束 → 业务错误码：并发预检都通过时第二个 INSERT 撞 uq_posts_code →
# IntegrityError handler 据此把 500 翻成 409（与 service 的 post.CODE_DUPLICATE 同码）。
register_unique_constraint(
    "uq_posts_code",
    "post.CODE_DUPLICATE",
    "Post code already exists",
)
