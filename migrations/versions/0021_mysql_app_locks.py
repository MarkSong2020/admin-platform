"""MySQL 事务级行锁 sentinel 表

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from admin_platform.db.mysql_capabilities import assert_app_locks_table_healthy

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 显式声明 ENGINE/CHARSET/COLLATE，不继承服务器 default_storage_engine：
    # app_locks 是事务级 advisory 锁的唯一载体，靠 InnoDB 行锁(SELECT ... FOR UPDATE)
    # 实现互斥。若落到 MyISAM 等非事务引擎，FOR UPDATE 静默退化为无锁 → 全部应用锁失效
    # 且不报错。collate 用 utf8mb4_0900_bin 保证锁名 PK 大小写敏感比较(对齐 mysql_capabilities)。
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS app_locks (
                name VARCHAR(191) NOT NULL COMMENT '锁名',
                PRIMARY KEY (name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin
            """
        )
    )
    # IF NOT EXISTS 会跳过既存表的 ENGINE/COLLATE 声明：若 app_locks 曾由失败迁移/人工预建成
    # MyISAM 或错误 collation，上面的声明不生效，FOR UPDATE 行锁会静默退化为无锁(并发互斥失效)。
    # 幂等 ALTER 强制修正为 InnoDB + bin collation(已正确则近似 no-op，app_locks 是小表成本可忽略)，
    # 堵死 codex 对抗审查的 BLOCKING：仅靠 CREATE ... ENGINE 不闭环。
    op.execute(sa.text("ALTER TABLE app_locks ENGINE=InnoDB"))
    op.execute(
        sa.text("ALTER TABLE app_locks CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin")
    )
    # migration-invariant 自检（codex 第二轮）：在迁移内确认实际 engine/collation/主键，失败即本
    # revision 失败、版本不推进、可重跑修复——胜过仅靠 env.py 迁移后 post-check（那会留「版本已推进
    # 但命令失败」的半闭环状态）。env.py 的 post-check 保留作纵深兜底。offline（--sql）无真实连接，跳过。
    if not context.is_offline_mode():
        assert_app_locks_table_healthy(op.get_bind())


def downgrade() -> None:
    # 注意（codex 第三轮）：0021 起本仓「拥有」app_locks。若该表是失败迁移/人工预建后被 0021
    # 收编（而非本 revision 首次创建），downgrade 的 drop 会删除既存表 —— 回滚前确认表归属，
    # 避免误删外部数据。
    op.drop_table("app_locks")
