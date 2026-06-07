"""空操作占位 —— autogenerate 残留，review 时删除本文件

Revision ID: f499852e96f8
Revises: 0004
Create Date: 2026-06-07

⚠️ 本文件是 `alembic revision --autogenerate -m p1_depts` 的临时产物，已被改用顺序号的
`0004_p1_depts.py`（内容等价）取代。无人值守模式下「删文件」是 review 前的不可逆红线
（doc/operations/UNATTENDED_EXECUTION.md §1），agent 无权 rm，故只能将其降级为空操作占位以
收敛单 head（链：0003 → 0004 → 本占位）。

**review 时请删除本文件**：它是叶子节点（无下游依赖），删后 `0004` 即为 head；本地一次性
DB 按 UNATTENDED_EXECUTION.md §2-L3「make compose-down && make compose-up && make migrate」
重置即可（或 `alembic stamp 0004`）。
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f499852e96f8"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
