"""定时任务 ORM 映射的方言无关约束。"""

from collections.abc import Callable

from admin_platform.domains.scheduled_task.models import ScheduledTask, ScheduledTaskLog


def test_scheduled_task_json_defaults_are_orm_side_only() -> None:
    """MySQL 迁移：JSON 默认值留在 ORM 侧，避免依赖 PostgreSQL ``'{}'::jsonb``。"""
    for model in (ScheduledTask, ScheduledTaskLog):
        column = model.__table__.c.params_json

        assert column.server_default is None
        assert column.default is not None
        assert column.default.is_callable
        assert isinstance(column.default.arg, Callable)
        assert column.default.arg(None) == {}
