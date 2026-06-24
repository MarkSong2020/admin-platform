"""Config ORM 映射 —— 表 ``configs``（运营参数键值，对标 RuoYi ``sys_config``）。

扁平域（单租户无 tenant_id、无树）：``config_key`` 全局唯一（消费方按 key 读值）；``config_value``
存非敏感运营参数（**禁存密钥/密码**——密钥走 ``~/.secrets`` / env，安全基线）。``is_builtin`` 标记
系统内置参数（service 层禁删，spec §2.3）。**无进程内缓存**：消费方读穿 DB，更新提交后即生效
（热更新，spec §2.3 决策 B）。
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.core.errors import register_unique_constraint
from admin_platform.db.base import Base, IdMixin, TimestampMixin


class Config(Base, IdMixin, TimestampMixin):
    __tablename__ = "configs"

    __table_args__ = (
        UniqueConstraint("config_key", name="uq_configs_key"),
        CheckConstraint("is_builtin IN (0, 1)", name="ck_configs_is_builtin_bool"),
    )

    name: Mapped[str] = mapped_column(String(128), comment="参数名称")
    config_key: Mapped[str] = mapped_column(String(128), comment="参数键名(全局唯一)")
    config_value: Mapped[str] = mapped_column(Text, comment="参数键值(非敏感运营参数)")
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否系统内置(内置禁删)"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


# DB 唯一约束 → 业务错误码：并发预检都通过时第二个 INSERT 撞 uq_configs_key →
# IntegrityError handler 翻成 409（与 service 的 config.KEY_DUPLICATE 同码）。
register_unique_constraint(
    "uq_configs_key",
    "config.KEY_DUPLICATE",
    "Config key already exists",
)
