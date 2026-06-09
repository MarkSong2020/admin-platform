"""Monitor 组合根（Composition Root）。

组装 MonitorService 依赖，使 api.py 只依赖 service、不直接 import repository（C2 分层契约）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.monitor.repository import MonitorRepository
from admin_platform.domains.monitor.service import MonitorService


async def get_monitor_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MonitorService:
    return MonitorService(MonitorRepository(session))
