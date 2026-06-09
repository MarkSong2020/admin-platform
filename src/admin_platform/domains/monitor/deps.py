"""Monitor 组合根（Composition Root）。

组装 MonitorService 依赖，使 api.py 只依赖 service、不直接 import repository（C2 分层契约）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.monitor.collector import SystemMetricsCollector
from admin_platform.domains.monitor.repository import MonitorRepository
from admin_platform.domains.monitor.service import MonitorService, SystemMonitorService


async def get_monitor_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MonitorService:
    return MonitorService(MonitorRepository(session))


def get_system_monitor_service(request: Request) -> SystemMonitorService:
    """服务 / 缓存监控 service —— 无 DB，从 ``app.state.redis`` 取（可能 None）。

    Redis 仅在 idempotency 或登录防护启用时创建（见 main.py）；都没开则注入 None，
    缓存监控降级为 available=False。"""
    redis: Redis | None = getattr(request.app.state, "redis", None)
    return SystemMonitorService(SystemMetricsCollector(), redis)
