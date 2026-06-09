"""在线用户 API 集成测试（P4）—— 真 DB 派生活动会话 + 强制下线。

覆盖：① 活动会话聚合（含轮换 family 的 login_time 取**原点**而非最近轮换——核心正确性）；
② 排除已撤销 / 已过期 family；③ 强制下线撤销 family 全部活动 token（reason=forced_logout）；
④ 不存在 / 已结束会话 → 404。需 DB。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.auth.models import RefreshToken
from admin_platform.domains.monitor.api import router as monitor_router
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)  # family 原点（登录时刻）
_T0B = _T0 + timedelta(hours=1)  # 轮换时刻
_FUTURE = datetime(2030, 1, 1, tzinfo=UTC)
_PAST = datetime(2020, 1, 1, tzinfo=UTC)


class _SuperProvider(PermissionProvider):
    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _hash() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex  # 唯一 64 字符 token_hash


async def _wipe() -> None:
    async with db_session() as s:
        await s.execute(text("TRUNCATE TABLE auth_refresh_tokens, users, audit_events CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


async def _seed() -> dict[str, uuid.UUID | int]:
    async with db_session() as s:
        alice = User(username="alice", password_hash="x")
        bob = User(username="bob", password_hash="x")
        s.add_all([alice, bob])
        await s.flush()
        f1, f2, f3, f4 = (uuid.uuid4() for _ in range(4))
        # F1（alice）：轮换链——旧 token 已撤销(rotated) + 新 token 活动。
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=f1,
                user_id=alice.id,
                token_hash=_hash(),
                issued_at=_T0,
                expires_at=_FUTURE,
                revoked_at=_T0B,
                revoked_reason="rotated",
                rotated_to_jti=uuid.uuid4(),
            )
        )
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=f1,
                user_id=alice.id,
                token_hash=_hash(),
                issued_at=_T0B,
                expires_at=_FUTURE,
                last_used_at=_T0B,
            )
        )
        # F2（bob）：单 token 活动。
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=f2,
                user_id=bob.id,
                token_hash=_hash(),
                issued_at=_T0B,
                expires_at=_FUTURE,
            )
        )
        # F3（alice）：全撤销 → 非活动。
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=f3,
                user_id=alice.id,
                token_hash=_hash(),
                issued_at=_T0,
                expires_at=_FUTURE,
                revoked_at=_T0B,
                revoked_reason="logout",
            )
        )
        # F4（alice）：已过期 → 非活动。
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=f4,
                user_id=alice.id,
                token_hash=_hash(),
                issued_at=_PAST,
                expires_at=_PAST,
            )
        )
        return {"alice": alice.id, "bob": bob.id, "f1": f1, "f2": f2, "f3": f3, "f4": f4}


def _client() -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(monitor_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = _SuperProvider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_only_active_families_with_origin_login_time() -> None:
    ids = await _seed()
    async with _client() as c:
        resp = await c.get("/api/v1/monitor/online")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 仅 F1 / F2 活动；F3（撤销）/ F4（过期）排除。
        assert body["total"] == 2
        by_id = {item["session_id"]: item for item in body["items"]}
        assert str(ids["f1"]) in by_id
        assert str(ids["f2"]) in by_id
        # 核心：F1 轮换过，login_time 仍取原点 _T0（而非最近轮换 _T0B）。
        f1 = by_id[str(ids["f1"])]
        assert f1["login_time"].startswith("2026-01-01T08:00")
        assert f1["username"] == "alice"


async def test_force_logout_revokes_active_tokens() -> None:
    ids = await _seed()
    async with _client() as c:
        resp = await c.delete(f"/api/v1/monitor/online/{ids['f1']}")
        assert resp.status_code == 204, resp.text
        # F1 不再活动 → 列表只剩 F2。
        remaining = (await c.get("/api/v1/monitor/online")).json()
        assert remaining["total"] == 1
        assert remaining["items"][0]["session_id"] == str(ids["f2"])
    # DB 校验：F1 原活动 token 现已撤销，reason=forced_logout。
    async with db_session() as s:
        rows = (
            await s.execute(
                select(RefreshToken.revoked_reason).where(
                    RefreshToken.family_id == ids["f1"],
                    RefreshToken.revoked_reason == "forced_logout",
                )
            )
        ).all()
        assert len(rows) == 1


async def test_force_logout_unknown_session_404() -> None:
    await _seed()
    async with _client() as c:
        resp = await c.delete(f"/api/v1/monitor/online/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["type"] == "monitor.ONLINE_SESSION_NOT_FOUND"


async def test_force_logout_already_ended_session_404() -> None:
    """已全撤销（F3）/ 已过期（F4）的 family 非活动 → 强退 404（幂等：踢已结束会话不报成功）。"""
    ids = await _seed()
    async with _client() as c:
        assert (await c.delete(f"/api/v1/monitor/online/{ids['f3']}")).status_code == 404
        assert (await c.delete(f"/api/v1/monitor/online/{ids['f4']}")).status_code == 404


# ---- 审计织入（强退是撤销会话的授权写，成功 + 失败都须记 rbac_write）-----------------


def _rbac_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    """从 audit logger 抓 rbac_write 审计事件（bare app 无 request session → 审计走 logger）。"""
    out: list[dict] = []
    for record in caplog.records:
        event = getattr(record, "audit_event", None)
        if event and event.get("event_type") == "rbac_write":
            out.append(event)
    return out


async def test_force_logout_emits_success_audit(caplog: pytest.LogCaptureFixture) -> None:
    ids = await _seed()
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        async with _client() as c:
            assert (await c.delete(f"/api/v1/monitor/online/{ids['f1']}")).status_code == 204
    success = [e for e in _rbac_events(caplog) if e["result"]["status"] == "success"]
    assert len(success) == 1, success
    event = success[0]
    assert event["action"] == "system:online:remove"
    assert event["result"]["http_status"] == 204
    assert event["target"]["type"] == "online_session"
    assert event["target"]["id"] == str(ids["f1"])  # 目标 = 会话 UUID
    assert event["target"]["display"] == "alice"  # display 取到真实被踢用户名（非 None）


async def test_force_logout_failure_emits_audit(caplog: pytest.LogCaptureFixture) -> None:
    await _seed()
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        async with _client() as c:
            assert (await c.delete(f"/api/v1/monitor/online/{uuid.uuid4()}")).status_code == 404
    failures = [e for e in _rbac_events(caplog) if e["result"]["status"] == "failure"]
    assert failures, "强退失败（404）也必须记 rbac_write 审计"
    fail = failures[0]
    assert fail["action"] == "system:online:remove"
    assert fail["result"]["http_status"] == 404
    assert fail["result"]["error_code"] == "monitor.ONLINE_SESSION_NOT_FOUND"


# ---- 分页：切的是 family 不是 token；count 与 list 口径一致 ------------------------


async def _seed_three_active() -> list[str]:
    """3 个活动 family（按 last_active 降序 FA>FB>FC），FA 含 2 个 token（轮换）守「按 family 分页」。"""
    async with db_session() as s:
        user = User(username="paged", password_hash="x")
        s.add(user)
        await s.flush()
        fa, fb, fc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        t_a, t_b, t_c = (_T0 + timedelta(hours=h) for h in (3, 2, 1))
        # FA：轮换 family（旧撤销 + 新活动），last_active=t_a。
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=fa,
                user_id=user.id,
                token_hash=_hash(),
                issued_at=_T0,
                expires_at=_FUTURE,
                revoked_at=t_a,
                revoked_reason="rotated",
                rotated_to_jti=uuid.uuid4(),
            )
        )
        s.add(
            RefreshToken(
                jti=uuid.uuid4(),
                family_id=fa,
                user_id=user.id,
                token_hash=_hash(),
                issued_at=t_a,
                expires_at=_FUTURE,
                last_used_at=t_a,
            )
        )
        for fam, ts in ((fb, t_b), (fc, t_c)):
            s.add(
                RefreshToken(
                    jti=uuid.uuid4(),
                    family_id=fam,
                    user_id=user.id,
                    token_hash=_hash(),
                    issued_at=ts,
                    expires_at=_FUTURE,
                    last_used_at=ts,
                )
            )
        return [str(fa), str(fb), str(fc)]


async def test_list_paginates_by_family_not_token() -> None:
    sids = await _seed_three_active()
    async with _client() as c:
        p1 = (await c.get("/api/v1/monitor/online?page=1&size=2")).json()
        p2 = (await c.get("/api/v1/monitor/online?page=2&size=2")).json()
    # total 数 family（3）——FA 是 2-token family 仍算 1 个会话（否则 total 会是 4）。
    assert p1["total"] == 3
    assert p1["total_pages"] == 2
    assert len(p1["items"]) == 2
    assert len(p2["items"]) == 1
    page_sids = [i["session_id"] for i in p1["items"]] + [i["session_id"] for i in p2["items"]]
    assert len(set(page_sids)) == 3  # 跨页无重叠
    assert sorted(page_sids) == sorted(sids)  # 并集 = 全部 3 个 family
