"""Task 9 CLI 集成测试（需本地 DB）—— 一次性创建平台超管。

覆盖 spec 验收（设 env → 建超管 / 不设 env → 失败不建记录 / 重复 → 拒绝）+ Codex 安全 PK 收紧：
弱密码拒绝、非法 username 拒绝、已有任意超管即拒（不只同名）、密码不进任何输出。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from admin_platform.cli import CliError, create_platform_admin, main
from admin_platform.core.security import verify_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import system_session
from admin_platform.domains.tenant.models import Tenant
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration

_ENV = "ADMIN_BOOTSTRAP_PASSWORD"
_STRONG_PW = "bootstrap-strong-" + "z" * 12  # ≥12、无空白、≠username


async def _wipe() -> None:
    async with system_session() as session:
        await session.execute(delete(User))
        await session.execute(delete(Tenant))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


async def _all_users() -> list[User]:
    async with system_session() as session:
        return list((await session.execute(select(User))).scalars().all())


async def _platform_admin(username: str) -> User | None:
    async with system_session() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.code == "PLATFORM"))
        ).scalar_one_or_none()
        if tenant is None:
            return None
        return (
            await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.username == username)
            )
        ).scalar_one_or_none()


async def test_create_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, _STRONG_PW)
    user_id = await create_platform_admin("root")
    assert user_id > 0
    admin = await _platform_admin("root")
    assert admin is not None
    assert admin.is_platform_admin is True
    assert admin.status == "active"
    assert verify_password(_STRONG_PW, admin.password_hash)  # 口令确实写进去了


async def test_missing_env_raises_and_creates_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(CliError):
        await create_platform_admin("root")
    assert await _all_users() == []  # 不设 env 绝不建记录


async def test_weak_password_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "short")  # <12
    with pytest.raises(CliError):
        await create_platform_admin("root")
    assert await _all_users() == []


async def test_password_equal_username_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "rootrootroot")  # ≥12 但等于 username
    with pytest.raises(CliError):
        await create_platform_admin("rootrootroot")
    assert await _all_users() == []


async def test_invalid_username_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, _STRONG_PW)
    with pytest.raises(CliError):
        await create_platform_admin("bad name")  # 含空白
    assert await _all_users() == []


async def test_rejects_second_admin_even_different_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Codex PK：一次性信任根 —— 已有任意平台超管即拒，不只拒同名。
    monkeypatch.setenv(_ENV, _STRONG_PW)
    await create_platform_admin("root")
    with pytest.raises(CliError):
        await create_platform_admin("admin2")
    usernames = {u.username for u in await _all_users()}
    assert usernames == {"root"}  # admin2 没被创建


def test_main_missing_env_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    # 同步测 main()（无运行中 loop）：缺 env 在 DB 之前就失败 → 退出码非 0，不建记录。
    monkeypatch.delenv(_ENV, raising=False)
    assert main(["create-platform-admin", "--username", "root"]) != 0
