"""post 岗位域 CRUD + user_posts 绑定 集成测试（需本地 DB）—— 端到端验收。

覆盖（spec §7 / §9 DoD）：
  * **CRUD 端到端**：超管 stub 越过权限守卫（``get_permission_provider`` + ``require_current_user``
    override 模拟登录），create / list / get / patch / delete + code 重复 409 + NOT_FOUND 404。
  * **权限矩阵 5 端点 403**：非超管、无权限 → list/query/add/edit/remove 全 403（默认 deny）。
  * **超管短路放行**：超管 stub → list 200。
  * **绑定（真 DB）**：``set_user_posts`` / ``list_posts_for_user`` 绑定正确；空列表解绑；去重。
  * **并发 last-writer-wins**：两请求并发替换同一 user 的岗位 → advisory lock 串行化后恰好一个
    岗位（非并集），不撞 ``uq_user_posts``（镜像 role 域 F3 测试）。

跨表 FK：清表用 ``TRUNCATE ... CASCADE``（一并清子表绑定）。
"""

from __future__ import annotations

import asyncio
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
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.post.api import router as post_router
from admin_platform.domains.post.models import Post
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration


# ---- 权限 stub（CRUD / 矩阵用，不查 DB）------------------------------------


class _SuperAdminProvider(PermissionProvider):
    """超管 stub：短路放行所有 post 权限点（spec §2.3）。"""

    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


class _NoPermProvider(PermissionProvider):
    """非超管、无权限 stub：5 端点全默认 deny（403）。"""

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _build_client(provider: PermissionProvider, *, user_id: str = "1") -> AsyncClient:
    """建一个 post app 的 AsyncClient（override 登录 + provider）。"""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(post_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=user_id, sub=user_id
    )
    app.dependency_overrides[get_permission_provider] = lambda: provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE user_posts, posts, users CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with _build_client(_SuperAdminProvider()) as c:
        yield c
    await dispose_engine()


async def _create(client: AsyncClient, *, code: str, name: str, sort_order: int = 0) -> int:
    res = await client.post(
        "/api/v1/posts", json={"name": name, "code": code, "sort_order": sort_order}
    )
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# ---- CRUD 端到端 -----------------------------------------------------------


async def test_crud_end_to_end(client: AsyncClient) -> None:
    post_id = await _create(client, code="pm", name="项目经理", sort_order=1)

    listing = (await client.get("/api/v1/posts")).json()
    assert {p["code"] for p in listing["items"]} == {"pm"}
    assert listing["total"] == 1

    got = await client.get(f"/api/v1/posts/{post_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "项目经理"

    patched = await client.patch(
        f"/api/v1/posts/{post_id}", json={"name": "高级项目经理", "sort_order": 5}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "高级项目经理"
    assert patched.json()["sort_order"] == 5

    # code 重复 → 409 post.CODE_DUPLICATE
    dup = await client.post("/api/v1/posts", json={"name": "山寨", "code": "pm"})
    assert dup.status_code == 409
    assert dup.json()["type"] == "post.CODE_DUPLICATE"

    # 删除 → 204；再 get → 404 post.NOT_FOUND
    deleted = await client.delete(f"/api/v1/posts/{post_id}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/posts/{post_id}")
    assert missing.status_code == 404
    assert missing.json()["type"] == "post.NOT_FOUND"


async def test_get_missing_returns_404(client: AsyncClient) -> None:
    res = await client.get("/api/v1/posts/999999")
    assert res.status_code == 404
    assert res.json()["type"] == "post.NOT_FOUND"


# ---- 权限矩阵 5 端点 403（非超管、无权限）+ 超管短路放行 --------------------


async def test_permission_matrix_all_endpoints_403() -> None:
    async with _build_client(_NoPermProvider(), user_id="2") as c:
        assert (await c.get("/api/v1/posts")).status_code == 403
        assert (await c.get("/api/v1/posts/1")).status_code == 403
        assert (await c.post("/api/v1/posts", json={"name": "x", "code": "X"})).status_code == 403
        assert (await c.patch("/api/v1/posts/1", json={"name": "x"})).status_code == 403
        assert (await c.delete("/api/v1/posts/1")).status_code == 403
    await dispose_engine()


async def test_superadmin_short_circuit_allows(client: AsyncClient) -> None:
    # 超管 stub 短路放行受守卫的 GET /api/v1/posts → 200。
    res = await client.get("/api/v1/posts")
    assert res.status_code == 200


# ---- user_posts 绑定（真 DB）：set / list 正确 -------------------------------


async def _seed_user(*, username: str) -> int:
    async with db_session() as session:
        user = User(username=username, password_hash="x")
        session.add(user)
        await session.flush()
        return user.id


async def _seed_post(*, code: str, name: str = "p") -> int:
    async with db_session() as session:
        post = Post(name=name, code=code)
        session.add(post)
        await session.flush()
        return post.id


async def test_set_and_list_user_posts(client: AsyncClient) -> None:
    uid = await _seed_user(username="u-bind")
    p1 = await _seed_post(code="b1")
    p2 = await _seed_post(code="b2")

    async with db_session() as session:
        await PostRepository(session).set_user_posts(uid, [p1, p2, p1])  # 去重

    async with db_session() as session:
        posts = await PostRepository(session).list_posts_for_user(uid)
    assert {p.id for p in posts} == {p1, p2}

    # 全量替换为单个 → 旧绑定被清
    async with db_session() as session:
        await PostRepository(session).set_user_posts(uid, [p2])
    async with db_session() as session:
        posts = await PostRepository(session).list_posts_for_user(uid)
    assert {p.id for p in posts} == {p2}

    # 空列表 = 解绑所有
    async with db_session() as session:
        await PostRepository(session).set_user_posts(uid, [])
    async with db_session() as session:
        posts = await PostRepository(session).list_posts_for_user(uid)
    assert posts == []


# ---- 绑定全量替换并发 last-writer-wins（advisory lock 串行化，镜像 role F3）---


async def test_set_user_posts_concurrent_last_writer_wins(client: AsyncClient) -> None:
    # 两请求并发把同一 user 的岗位分别替换为 [p1] / [p2]：advisory lock 串行化后最终恰好
    # 一个岗位（last-writer-wins），而非并集 [p1, p2]，也不撞 uq_user_posts。
    uid = await _seed_user(username="u-concurrent")
    p1 = await _seed_post(code="cc1")
    p2 = await _seed_post(code="cc2")

    async def _replace(post_id: int) -> None:
        async with db_session() as session:
            await PostRepository(session).set_user_posts(uid, [post_id])

    await asyncio.gather(_replace(p1), _replace(p2))

    async with db_session() as session:
        posts = await PostRepository(session).list_posts_for_user(uid)
    assert len(posts) == 1
    assert posts[0].id in {p1, p2}
