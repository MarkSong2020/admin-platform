"""refresh token 落库 + 轮换 + reuse 检测 + 并发上限 集成测试（spec 2026-06-09 §1.3）。"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update

from admin_platform.core.config import get_settings
from admin_platform.core.errors import AppError
from admin_platform.core.security import parse_refresh_token
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.auth.models import RefreshToken
from admin_platform.domains.auth.refresh_service import (
    enforce_concurrency_limit,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from admin_platform.domains.auth.repository import RefreshTokenRepository
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration

_PEPPER = "integration-refresh-pepper-" + "p" * 32


@pytest_asyncio.fixture(autouse=True)
async def _setup(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("APP_AUTH_REFRESH_TOKEN_PEPPER", _PEPPER)
    get_settings.cache_clear()
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE auth_refresh_tokens, users CASCADE"))
    yield
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE auth_refresh_tokens, users CASCADE"))
    await dispose_engine()
    get_settings.cache_clear()


async def _seed_user(username: str = "alice") -> int:
    async with db_session() as session:
        user = User(username=username, password_hash="x")
        session.add(user)
        await session.flush()
        return user.id


async def test_issue_stores_hash_not_plaintext() -> None:
    uid = await _seed_user()
    async with db_session() as session:
        issued = await issue_refresh_token(session, user_id=uid)
    plain = issued.token
    parsed = parse_refresh_token(plain)
    assert parsed is not None and plain.startswith("rt_")
    async with db_session() as session:
        rows = (await session.scalars(select(RefreshToken))).all()
    assert len(rows) == 1
    # DB 不存明文：token_hash 是 64 hex，明文 secret 不出现在任何列。
    assert len(rows[0].token_hash) == 64
    assert parsed[1] not in rows[0].token_hash


async def test_rotate_issues_new_and_revokes_old() -> None:
    uid = await _seed_user()
    async with db_session() as session:
        issued = await issue_refresh_token(session, user_id=uid)
        old_jti = issued.jti
    async with db_session() as session:
        result = await rotate_refresh_token(session, raw_token=issued.token)
    assert result.user_id == uid
    assert result.refresh.family_id == issued.family_id  # 同 family 续链
    async with db_session() as session:
        old = await session.scalar(select(RefreshToken).where(RefreshToken.jti == old_jti))
        new = await session.scalar(
            select(RefreshToken).where(RefreshToken.jti == result.refresh.jti)
        )
    assert old is not None and old.revoked_reason == "rotated"
    assert old.rotated_to_jti == result.refresh.jti
    assert new is not None and new.revoked_at is None


async def test_reuse_detection_revokes_whole_family() -> None:
    uid = await _seed_user()
    async with db_session() as session:
        issued = await issue_refresh_token(session, user_id=uid)
    # 第一次轮换正常
    async with db_session() as session:
        rotated = await rotate_refresh_token(session, raw_token=issued.token)
    # 再用**旧**（已轮换）token → reuse 检测 → 整个 family 撤销 + 抛 REUSED
    async with db_session() as session:
        with pytest.raises(AppError) as exc:
            await rotate_refresh_token(session, raw_token=issued.token)
    assert exc.value.code == "auth.REFRESH_TOKEN_REUSED"
    # family 内全部 token（含刚轮换出的新 token）都被撤销
    async with db_session() as session:
        active = (
            await session.scalars(
                select(RefreshToken).where(
                    RefreshToken.family_id == issued.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).all()
    assert active == []
    # 被撤销的新 token 也不能再轮换（L：pin 错误码——命中 reuse 检测的 revoked_reason 分支 → REUSED）
    async with db_session() as session:
        with pytest.raises(AppError) as exc2:
            await rotate_refresh_token(session, raw_token=rotated.refresh.token)
    assert exc2.value.code == "auth.REFRESH_TOKEN_REUSED"


async def test_invalid_token_rejected() -> None:
    await _seed_user()
    async with db_session() as session:
        with pytest.raises(AppError) as exc:
            await rotate_refresh_token(session, raw_token="rt_not-a-uuid.garbage")
    assert exc.value.code == "auth.REFRESH_TOKEN_INVALID"


async def test_logout_revokes_family() -> None:
    uid = await _seed_user()
    async with db_session() as session:
        issued = await issue_refresh_token(session, user_id=uid)
    async with db_session() as session:
        ok = await revoke_refresh_token(session, raw_token=issued.token)
    assert ok is True
    async with db_session() as session:
        with pytest.raises(AppError) as exc:
            await rotate_refresh_token(session, raw_token=issued.token)
    # L：pin 错误码——logout 撤销（非 reuse）后轮换 → INVALID（不误报为 REUSED 泄露盗用信号）。
    assert exc.value.code == "auth.REFRESH_TOKEN_INVALID"


async def test_rotate_rejected_when_family_absolute_exceeded() -> None:
    """H2 + M6：family_absolute_at 达硬上限 → 轮换拒绝（须重登），锚点取本行不随 cleanup 漂移。

    构造一个 idle 未过期、但 family_absolute_at 已过去的活动 token：旧实现按 min(issued_at)+ttl
    重算锚点（≈now+30d，永不过期 = bug）；新实现直接读本行 family_absolute_at（已过期）→ 拒。
    """
    uid = await _seed_user()
    async with db_session() as session:
        issued = await issue_refresh_token(session, user_id=uid)
    # 模拟时间流逝到 absolute 上限：把本行 family_absolute_at 拨到过去（idle expires_at 仍未到）。
    async with db_session() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.jti == issued.jti)
            .values(family_absolute_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    async with db_session() as session:
        with pytest.raises(AppError) as exc:
            await rotate_refresh_token(session, raw_token=issued.token)
    assert exc.value.code == "auth.REFRESH_TOKEN_INVALID"


async def test_concurrent_rotate_and_revoke_no_token_escapes() -> None:
    """H1：并发「轮换」与「撤销 family」经 per-user advisory lock 串行化——撤销后无活动 token 逃逸。

    旧实现（无 user 锁）：rotate 先插新 token Z，revoke 的单语句 UPDATE 快照不含 Z → Z 逃逸为活动
    （reuse 检测/强制下线/logout 被击穿）。新实现两路经同一 advisory lock 串行：revoke 必能看到 Z
    （或 rotate 看到已撤销而拒），最终 family 一定无未撤销 token。
    """
    uid = await _seed_user()
    async with db_session() as session:
        issued = await issue_refresh_token(session, user_id=uid)
    fam = issued.family_id

    async def _rotate() -> None:
        async with db_session() as session:
            with contextlib.suppress(AppError):
                await rotate_refresh_token(session, raw_token=issued.token)

    async def _revoke() -> None:
        async with db_session() as session:
            repo = RefreshTokenRepository(session)
            await repo.acquire_user_lock(uid)  # 镜像 force_logout/logout 的锁路径
            await repo.revoke_family(fam, reason="forced_logout", now=datetime.now(UTC))

    await asyncio.gather(_rotate(), _revoke())
    async with db_session() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.family_id == fam, RefreshToken.revoked_at.is_(None))
        )
    assert active == 0  # 无 token 逃逸撤销


async def test_concurrency_limit_revokes_oldest_family() -> None:
    uid = await _seed_user()
    limit = get_settings().auth_refresh_max_sessions_per_user
    # 建 limit+1 个 family（每个 issue 一个新 family）
    families = []
    for _ in range(limit + 1):
        async with db_session() as session:
            issued = await issue_refresh_token(session, user_id=uid)
            families.append(issued.family_id)
        async with db_session() as session:
            await enforce_concurrency_limit(session, user_id=uid)
    async with db_session() as session:
        active = await RefreshTokenRepository(session).list_active_families(
            uid, now=datetime.now(UTC)
        )
    assert len(active) == limit  # 超出的最旧 family 被撤销
    assert families[0] not in active  # 最早的被淘汰


async def test_delete_expired() -> None:
    uid = await _seed_user()
    async with db_session() as session:
        repo = RefreshTokenRepository(session)
        await repo.create(
            jti=uuid.uuid4(),
            family_id=uuid.uuid4(),
            user_id=uid,
            token_hash="0" * 64,
            issued_at=datetime.now(UTC) - timedelta(days=40),
            expires_at=datetime.now(UTC) - timedelta(days=10),  # 已过期
            family_absolute_at=datetime.now(UTC) - timedelta(days=10),
        )
    async with db_session() as session:
        deleted = await RefreshTokenRepository(session).delete_expired()
    assert deleted == 1
