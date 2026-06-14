"""DB-free api 测试的共享支持件。

这些 api 测试只验证「权限守卫接线 + Pydantic 校验」等不需要真 DB 的路径，service / provider
均经 ``dependency_overrides`` 注入 stub。``require_permission`` 守卫（P1 架构修复后）声明了对
``get_session`` 的「顺序保证依赖」——本身不会读 session，但 FastAPI 解析守卫时会先解析
``get_session``，未 override 就会去连真 DB。故每个本地 app 都需把 ``get_session`` 也 override 成
``fake_session``：yield 一个不连库的占位对象（守卫只为建立 ContextVar，session 实际不被使用）。

不用 MagicMock / AsyncMock（项目红线）——用手写哑对象。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from admin_platform.db.session import get_session


async def fake_session() -> AsyncIterator[Any]:
    """``get_session`` 的 DB-free 替身：yield 一个占位对象。

    DB-free api 测试里 service / provider 都已 stub，守卫声明的 session 不被任何代码实际读写，
    只需被 yield 出来满足 FastAPI 依赖解析（并触发 ``_request_session_var`` 设置）。yield 一个
    标识对象而非 None，便于将来若有断言「拿到的是替身」时区分。
    """
    yield object()


def override_get_session(overrides: dict[Any, Any]) -> None:
    """把 ``get_session`` 在给定 ``app.dependency_overrides`` 里替换为 ``fake_session``。

    供各 api 测试的 ``_make_app`` 复用：``override_get_session(app.dependency_overrides)``。
    """
    overrides[get_session] = fake_session
