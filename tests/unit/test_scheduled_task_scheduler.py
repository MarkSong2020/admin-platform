"""定时任务 scheduler 单元契约。"""

from __future__ import annotations

from admin_platform.core.config import Settings
from admin_platform.domains.scheduled_task.scheduler import _leader_lock_name


def test_leader_lock_name_is_isolated_by_database_schema() -> None:
    base = {
        "scheduler_leader_lock_key": 478270,
        "scheduler_enabled": True,
    }

    first = _leader_lock_name(
        Settings(database_url="mysql+aiomysql://app:app@db.example.com:3306/app_a", **base)
    )
    second = _leader_lock_name(
        Settings(database_url="mysql+aiomysql://app:app@db.example.com:3306/app_b", **base)
    )

    assert first != second
    assert first.startswith("admin-platform:scheduler:")
    assert second.startswith("admin-platform:scheduler:")
