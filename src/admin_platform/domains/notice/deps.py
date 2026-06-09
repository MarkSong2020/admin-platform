"""Notice 组合根（Composition Root）。

在此组装 NoticeService 的具体依赖，使 api.py 只依赖 service、不直接 import repository
（分层契约：``*.api`` 禁 import ``*.repository``）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.notice.repository import NoticeRepository
from admin_platform.domains.notice.service import NoticeService


async def get_notice_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NoticeService:
    return NoticeService(NoticeRepository(session))
