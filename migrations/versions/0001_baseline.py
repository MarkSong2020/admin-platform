"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-14

Empty baseline. Add your first table via ``make migration name=create_xxx``
once you register models in ``migrations/env.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
