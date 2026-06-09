"""RBAC 绑定子资源 API 端到端（P1.5）—— 4 类绑定 PUT/GET + 存在性校验 + 数据权限 + rbac_write 审计。

覆盖（decision-log 2026-06-09 + Codex PK 要求）：成功 / 空清空 / 去重 / 不存在 id 422 /
主体 404 / 非超管越权 404·403 / 绑定成功失败都产 rbac_write 审计。需本地 DB。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import PermissionProvider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.dept.models import Dept
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.post.models import Post
from admin_platform.domains.rbac_binding.api import router as rbac_binding_router
from admin_platform.domains.role.models import Role
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration

_BIND_PERMS = frozenset(
    {"system:user:query", "system:user:edit", "system:role:query", "system:role:edit"}
)


class _SuperProvider(PermissionProvider):
    """超管 stub：is_super_admin → require_permission 短路放行，data_scope=ALL 不限制。"""

    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


class _LimitedProvider(PermissionProvider):
    """非超管 stub：有绑定权限点，data_scope=CUSTOM_DEPT 限定可见部门集合。"""

    def __init__(self, *, visible: frozenset[int]) -> None:
        self._visible = visible

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return _BIND_PERMS

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.CUSTOM_DEPT, user_id=user_id, visible_dept_ids=self._visible)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE user_roles, role_menus, role_depts, user_posts, "
                "menus, roles, posts, depts, users CASCADE"
            )
        )


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client(provider: PermissionProvider, *, user_id: str = "1") -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(rbac_binding_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=user_id, sub=user_id
    )
    app.dependency_overrides[get_permission_provider] = lambda: provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed() -> dict[str, int]:
    """建 user + 2 role + 2 menu + 2 post + 2 dept，返回 ids。"""
    async with db_session() as session:
        target = User(username="target", password_hash="x", status="active", dept_id=None)
        r1 = Role(name="r1", code="r1", data_scope="custom_dept", status="active")
        r2 = Role(name="r2", code="r2", data_scope="self", status="active")
        m1, m2 = Menu(name="m1", menu_type="C"), Menu(name="m2", menu_type="C")
        p1, p2 = Post(name="p1", code="p1"), Post(name="p2", code="p2")
        d1, d2 = Dept(name="d1", code="d1"), Dept(name="d2", code="d2")
        session.add_all([target, r1, r2, m1, m2, p1, p2, d1, d2])
        await session.flush()
        return {
            "user": target.id, "r1": r1.id, "r2": r2.id, "m1": m1.id, "m2": m2.id,
            "p1": p1.id, "p2": p2.id, "d1": d1.id, "d2": d2.id,
        }  # fmt: skip


# ---- 成功路径 + 回显 -----------------------------------------------------------


async def test_bind_user_roles_success_and_get() -> None:
    ids = await _seed()
    async with _client(_SuperProvider()) as c:
        res = await c.put(
            f"/api/v1/users/{ids['user']}/roles", json={"role_ids": [ids["r1"], ids["r2"]]}
        )
        assert res.status_code == 200, res.text
        assert res.json()["ids"] == [ids["r1"], ids["r2"]]
        got = await c.get(f"/api/v1/users/{ids['user']}/roles")
        assert got.status_code == 200
        assert set(got.json()["ids"]) == {ids["r1"], ids["r2"]}
    await dispose_engine()


async def test_bind_role_menus_depts_and_user_posts() -> None:
    ids = await _seed()
    async with _client(_SuperProvider()) as c:
        assert (
            await c.put(f"/api/v1/roles/{ids['r1']}/menus", json={"menu_ids": [ids["m1"]]})
        ).status_code == 200
        assert (
            await c.put(f"/api/v1/roles/{ids['r1']}/depts", json={"dept_ids": [ids["d1"]]})
        ).status_code == 200
        assert (
            await c.put(f"/api/v1/users/{ids['user']}/posts", json={"post_ids": [ids["p1"]]})
        ).status_code == 200
        assert (await c.get(f"/api/v1/roles/{ids['r1']}/menus")).json()["ids"] == [ids["m1"]]
        assert (await c.get(f"/api/v1/roles/{ids['r1']}/depts")).json()["ids"] == [ids["d1"]]
        assert (await c.get(f"/api/v1/users/{ids['user']}/posts")).json()["ids"] == [ids["p1"]]
    await dispose_engine()


async def test_bind_dedup_and_empty_clears() -> None:
    ids = await _seed()
    async with _client(_SuperProvider()) as c:
        # 重复 id 去重
        dup = await c.put(
            f"/api/v1/users/{ids['user']}/roles", json={"role_ids": [ids["r1"], ids["r1"]]}
        )
        assert dup.json()["ids"] == [ids["r1"]]
        # 空数组清空
        empty = await c.put(f"/api/v1/users/{ids['user']}/roles", json={"role_ids": []})
        assert empty.json()["ids"] == []
        assert (await c.get(f"/api/v1/users/{ids['user']}/roles")).json()["ids"] == []
    await dispose_engine()


# ---- 存在性 + 主体校验 ---------------------------------------------------------


async def test_bind_nonexistent_ids_returns_422() -> None:
    ids = await _seed()
    async with _client(_SuperProvider()) as c:
        res = await c.put(
            f"/api/v1/users/{ids['user']}/roles", json={"role_ids": [ids["r1"], 999999]}
        )
        assert res.status_code == 422
        assert res.json()["type"] == "admin_platform.ROLE_IDS_INVALID"
    await dispose_engine()


async def test_bind_nonexistent_subject_returns_404() -> None:
    await _seed()
    async with _client(_SuperProvider()) as c:
        assert (await c.put("/api/v1/users/999999/roles", json={"role_ids": []})).status_code == 404
        assert (await c.put("/api/v1/roles/999999/menus", json={"menu_ids": []})).status_code == 404
    await dispose_engine()


# ---- 数据权限（非超管越权）-----------------------------------------------------


async def test_non_superadmin_cannot_bind_invisible_user() -> None:
    ids = await _seed()
    async with db_session() as session:
        invisible = User(username="inv", password_hash="x", status="active", dept_id=ids["d2"])
        session.add(invisible)
        await session.flush()
        inv_id = invisible.id
    # 非超管只可见 d1；目标 user 属 d2 → 不可见 → 404（不泄露存在性）。
    async with _client(_LimitedProvider(visible=frozenset({ids["d1"]})), user_id="2") as c:
        res = await c.put(f"/api/v1/users/{inv_id}/roles", json={"role_ids": [ids["r1"]]})
        assert res.status_code == 404
    await dispose_engine()


async def test_non_superadmin_cannot_bind_invisible_dept_to_role() -> None:
    ids = await _seed()
    # 非超管只可见 d1；给角色绑 d2（不可见）→ 403 FORBIDDEN_BY_SCOPE。
    async with _client(_LimitedProvider(visible=frozenset({ids["d1"]})), user_id="2") as c:
        res = await c.put(f"/api/v1/roles/{ids['r1']}/depts", json={"dept_ids": [ids["d2"]]})
        assert res.status_code == 403
        assert res.json()["type"] == "auth.FORBIDDEN_BY_SCOPE"
    await dispose_engine()


# ---- rbac_write 审计 -----------------------------------------------------------


async def test_rbac_write_audit_on_success_and_failure(caplog: pytest.LogCaptureFixture) -> None:
    ids = await _seed()
    async with _client(_SuperProvider()) as c:
        with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
            await c.put(f"/api/v1/users/{ids['user']}/roles", json={"role_ids": [ids["r1"]]})
            await c.put(f"/api/v1/users/{ids['user']}/roles", json={"role_ids": [999999]})
    events = [getattr(r, "audit_event", None) for r in caplog.records]
    rbac = [e for e in events if e and e.get("event_type") == "rbac_write"]
    success = [e for e in rbac if e["result"]["status"] == "success"]
    failure = [e for e in rbac if e["result"]["status"] == "failure"]
    assert success and success[0]["action"] == "system:user:bind_roles"
    assert success[0]["target"]["type"] == "user"
    assert failure and failure[0]["result"]["error_code"] == "admin_platform.ROLE_IDS_INVALID"
    await dispose_engine()
