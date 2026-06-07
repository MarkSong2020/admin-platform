"""dept 部门树 CRUD 集成测试（需本地 DB）—— 端到端验收。

覆盖（spec §4 数据权限载体 + O1 邻接表）：
  * recursive CTE：root→A→B→C 的 ``list_descendant_dept_ids`` / ``list_ancestor_dept_ids``；
  * 移动防环：把 A 移到其子孙 C 之下 → 409 ``dept.CYCLE``；
  * 重挂父子后可见集合正确变化（把 B 提到根，A 与 B 的子孙集合随之改变）；
  * CRUD 端到端：超管 stub 越过权限守卫（``get_permission_provider`` + ``require_current_user``
    override 模拟登录），code 重复 409、有子禁删 409、删叶 204。

部门树自引用 FK ``ondelete=RESTRICT``：批量 ``DELETE`` 会触发即时约束检查（无法保证子先于父删），
故清表用 ``TRUNCATE``（PostgreSQL 允许对自引用表 TRUNCATE）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine, get_sessionmaker
from admin_platform.db.session import db_session
from admin_platform.domains.dept.api import router as dept_router
from admin_platform.domains.dept.repository import DeptRepository

pytestmark = pytest.mark.integration


class _SuperAdminProvider(PermissionProvider):
    """超管 stub：短路放行所有 dept 权限点（spec §2.3）。"""

    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE depts CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(dept_router)
    # 模拟登录 + 超管短路：越过 require_permission 守卫（DB 真实查 dept 表）。
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = _SuperAdminProvider
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()


async def _create(
    client: AsyncClient, *, code: str, name: str, parent_id: int | None = None
) -> int:
    payload: dict[str, object] = {"name": name, "code": code}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    res = await client.post("/api/v1/depts", json=payload)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


async def _descendants(dept_id: int) -> frozenset[int]:
    async with get_sessionmaker()() as session:
        return await DeptRepository(session).list_descendant_dept_ids(dept_id)


async def _ancestors(dept_id: int) -> list[int]:
    async with get_sessionmaker()() as session:
        return await DeptRepository(session).list_ancestor_dept_ids(dept_id)


# ---- recursive CTE：子孙 / 祖先 -------------------------------------------


async def test_descendant_and_ancestor_sets(client: AsyncClient) -> None:
    root = await _create(client, code="ROOT", name="总公司")
    a = await _create(client, code="A", name="A", parent_id=root)
    b = await _create(client, code="B", name="B", parent_id=a)
    c = await _create(client, code="C", name="C", parent_id=b)

    # 子孙含自身：descendants(A) == {A,B,C}；叶子 descendants(C) == {C}。
    assert await _descendants(a) == frozenset({a, b, c})
    assert await _descendants(c) == frozenset({c})
    # 祖先链（root→直属父 有序，不含自身）：ancestors(C) == [root, A, B]。
    assert await _ancestors(c) == [root, a, b]


# ---- 移动防环 + 重挂后可见集合变化 ----------------------------------------


async def test_move_into_descendant_rejected_then_reparent(client: AsyncClient) -> None:
    root = await _create(client, code="ROOT", name="总公司")
    a = await _create(client, code="A", name="A", parent_id=root)
    b = await _create(client, code="B", name="B", parent_id=a)
    c = await _create(client, code="C", name="C", parent_id=b)

    # 把 A 移到其子孙 C 之下 → 成环，拒绝。
    res = await client.patch(f"/api/v1/depts/{a}", json={"parent_id": c})
    assert res.status_code == 409
    assert res.json()["type"] == "dept.CYCLE"

    # 把 B 提到根 → A 子孙集合缩为 {A}，B 子孙集合为 {B,C}。
    moved = await client.patch(f"/api/v1/depts/{b}", json={"parent_id": None})
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_id"] is None
    assert await _descendants(a) == frozenset({a})
    assert await _descendants(b) == frozenset({b, c})


async def test_move_into_self_rejected(client: AsyncClient) -> None:
    a = await _create(client, code="A", name="A")
    res = await client.patch(f"/api/v1/depts/{a}", json={"parent_id": a})
    assert res.status_code == 409
    assert res.json()["type"] == "dept.CYCLE"


# ---- CRUD 端到端 -----------------------------------------------------------


async def test_crud_end_to_end(client: AsyncClient) -> None:
    # create → list → get → patch
    dept_id = await _create(client, code="RD", name="研发部")

    listing = (await client.get("/api/v1/depts")).json()
    assert {d["code"] for d in listing["items"]} == {"RD"}
    assert listing["total"] == 1

    got = await client.get(f"/api/v1/depts/{dept_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "研发部"

    patched = await client.patch(f"/api/v1/depts/{dept_id}", json={"name": "研发中心"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "研发中心"

    # code 重复 → 409 dept.CODE_DUPLICATE
    dup = await client.post("/api/v1/depts", json={"name": "山寨研发", "code": "RD"})
    assert dup.status_code == 409
    assert dup.json()["type"] == "dept.CODE_DUPLICATE"

    # 有子部门 → 删父被拒（409 dept.HAS_CHILDREN）
    child_id = await _create(client, code="RD-1", name="一组", parent_id=dept_id)
    blocked = await client.delete(f"/api/v1/depts/{dept_id}")
    assert blocked.status_code == 409
    assert blocked.json()["type"] == "dept.HAS_CHILDREN"

    # 删叶子 → 204；再 get → 404 dept.NOT_FOUND
    deleted = await client.delete(f"/api/v1/depts/{child_id}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/depts/{child_id}")
    assert missing.status_code == 404
    assert missing.json()["type"] == "dept.NOT_FOUND"


async def test_get_missing_returns_404(client: AsyncClient) -> None:
    res = await client.get("/api/v1/depts/999999")
    assert res.status_code == 404
    assert res.json()["type"] == "dept.NOT_FOUND"
