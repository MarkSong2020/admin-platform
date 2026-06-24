"""定时任务 ORM 映射的方言无关约束。"""

from collections.abc import Callable

from admin_platform.domains.scheduled_task.models import ScheduledTask, ScheduledTaskLog


def test_scheduled_task_json_has_db_and_orm_defaults() -> None:
    """params_json 同时有 DB server_default(MySQL JSON_OBJECT()，raw SQL/seed 省略也得空对象)
    与 ORM default=dict(应用层省略也得空对象)——保留 PG jsonb '{}' 的 DB 契约（codex 审查）。"""
    for model in (ScheduledTask, ScheduledTaskLog):
        column = model.__table__.c.params_json

        assert column.server_default is not None
        assert "JSON_OBJECT" in str(column.server_default.arg).upper()
        assert column.default is not None
        assert column.default.is_callable
        assert isinstance(column.default.arg, Callable)
        assert column.default.arg(None) == {}
