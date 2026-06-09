"""定时任务组合根（Composition Root）。

组装 ScheduledTaskService（repo + 全局 registry + executor），使 api.py 只依赖 service。
registry 在 import 期注册满；executor 无状态（自带 db_session），故每请求新建无副作用。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.scheduled_task.executor import TaskExecutor
from admin_platform.domains.scheduled_task.registry import JOB_REGISTRY
from admin_platform.domains.scheduled_task.repository import ScheduledTaskRepository
from admin_platform.domains.scheduled_task.service import ScheduledTaskService


async def get_scheduled_task_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduledTaskService:
    return ScheduledTaskService(
        ScheduledTaskRepository(session), JOB_REGISTRY, TaskExecutor(JOB_REGISTRY)
    )
