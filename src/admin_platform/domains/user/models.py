"""User ORM 映射 — 表 ``users``。

表名用复数 ``users``（不是 ``user``）：①符合本仓 ``doc/standards/NAMING_CONVENTIONS.md``
的「表名 = URL 复数」约定（与 ``todos`` / ``tags`` 一致）；②``user`` 是 SQL 保留字
（PostgreSQL ``SELECT user`` 返回当前角色），用作表名后所有 raw SQL（含 Task 12 RLS
policy / ``SET LOCAL``）都得永久 quoting，``users`` 规避此坑。这是 Task 4 实施期对冻结
spec §2 字面 ``__tablename__="user"`` 的一处 deviation，见 spec 修订记录。

多租户业务表的范例（继承 ``TenantMixin``）：``tenant_id`` 列由 mixin 提供（非空 +
单列索引），租户隔离由 ``db/tenant_filter.py`` 的事件按上下文自动注入，业务代码
不手写 ``WHERE tenant_id =``。

本表在 mixin 之上额外加两条 DB 层约束：

  * ``ForeignKeyConstraint(tenant_id → tenants.id)`` —— 把租户归属锚到 ``tenants`` 表。
    放在 ``User.__table_args__`` 而非 ``TenantMixin`` 里：mixin 是所有业务表共享的
    通用契约，是否硬 FK 到某张具体表是各表自己的事，不该由 mixin 替所有表决定。
  * ``UniqueConstraint(tenant_id, username)`` —— 同租户内用户名唯一、跨租户可重名，
    多租户共享库的标准做法（不是全局唯一 username）。

平台超管（``is_platform_admin=True``）属哨兵租户 ``tenants.code="PLATFORM"``；鉴权层
据此 bypass 租户过滤，跨租户可见（见 ADR-B）。P0 不预留部门/data-scope 字段（YAGNI）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class User(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_users_tenant_id"),
    )

    username: Mapped[str] = mapped_column(String(64), comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(255), comment="密码哈希")
    nickname: Mapped[str] = mapped_column(String(64), default="", comment="昵称")
    status: Mapped[str] = mapped_column(String(16), default="active", comment="状态")
    is_platform_admin: Mapped[bool] = mapped_column(default=False, comment="是否平台超管")
