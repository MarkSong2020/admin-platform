"""post 岗位域 CRUD + user_posts 绑定 集成测试（需本地 DB）—— 端到端验收。

覆盖（spec §7 / §9 DoD）：
  * **CRUD 端到端**：超管 stub 越过权限守卫（``get_permission_provider`` + ``require_current_user``
    override 模拟登录），create / list / get / patch / delete + code 重复 409 + NOT_FOUND 404。
  * **权限矩阵 5 端点 403**：非超管、无权限 → list/query/add/edit/remove 全 403（默认 deny）。
  * **超管短路放行**：超管 stub → list 200。
  * **绑定（真 DB）**：``set_user_posts`` / ``list_posts_for_user`` 绑定正确；空列表解绑；去重。
  * **并发 last-writer-wins**：两请求并发替换同一 user 的岗位 → 事务级行锁串行化后恰好一个
    岗位（非并集），不撞 ``uq_user_posts``（镜像 role 域 F3 测试）。

跨表 FK：清表经 MySQL helper 临时关闭外键检查后逐表 TRUNCATE（一并清子表绑定）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.post.api import router as post_router
from admin_platform.domains.post.excel import POST_EXCEL_COLUMNS
from admin_platform.domains.post.models import Post
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.post.schemas import PostCreate
from admin_platform.domains.user.models import User
from admin_platform.excel import ExcelExporter, ExcelImporter
from tests.integration.db_cleanup import truncate_tables

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
    await truncate_tables("user_posts", "posts", "users")


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


# ---- P1 列表过滤 / 排序 / count 一致（真 DB SQL）---------------------------


async def test_list_filter_by_code_keyword(client: AsyncClient) -> None:
    # 三条岗位，code 关键字 "dev" 只命中其中一条（ilike 子串匹配，参数化非拼接）。
    await _create(client, code="dev-be", name="后端")
    await _create(client, code="dev-fe", name="前端")
    await _create(client, code="pm", name="项目经理")
    res = (await client.get("/api/v1/posts", params={"code": "dev"})).json()
    assert {p["code"] for p in res["items"]} == {"dev-be", "dev-fe"}
    # count 与过滤一致：total 反映过滤后数量（非全表 3）。
    assert res["total"] == 2


async def test_list_filter_by_status(client: AsyncClient) -> None:
    a = await _create(client, code="a", name="A")
    await _create(client, code="b", name="B")
    await client.patch(f"/api/v1/posts/{a}", json={"status": "disabled"})
    res = (await client.get("/api/v1/posts", params={"status": "disabled"})).json()
    assert {p["code"] for p in res["items"]} == {"a"}
    assert res["total"] == 1


async def test_list_sort_by_sort_order_asc_desc(client: AsyncClient) -> None:
    await _create(client, code="s1", name="一", sort_order=3)
    await _create(client, code="s2", name="二", sort_order=1)
    await _create(client, code="s3", name="三", sort_order=2)
    asc = (
        await client.get("/api/v1/posts", params={"order_by": "sort_order", "order": "asc"})
    ).json()
    assert [p["code"] for p in asc["items"]] == ["s2", "s3", "s1"]
    desc = (
        await client.get("/api/v1/posts", params={"order_by": "sort_order", "order": "desc"})
    ).json()
    assert [p["code"] for p in desc["items"]] == ["s1", "s3", "s2"]


async def test_list_invalid_order_by_returns_422(client: AsyncClient) -> None:
    # 防注入守门（端到端）：order_by 非 allowlist（注入串）→ 422，绝不进 SQL。
    await _create(client, code="x", name="X")
    res = await client.get("/api/v1/posts", params={"order_by": "code; DROP TABLE posts"})
    assert res.status_code == 422
    assert res.json()["type"] == "framework.SORT_FIELD_INVALID"
    # 表未被破坏：DROP 没执行，岗位仍在。
    assert (await client.get("/api/v1/posts")).json()["total"] == 1


async def test_patch_to_duplicate_code_returns_409(client: AsyncClient) -> None:
    # Codex 深审：PATCH 改 code 撞已存在 code → 409（update 的 code 唯一预检，非仅 create）。
    await _create(client, code="pm", name="项目经理")
    other = await _create(client, code="dev", name="开发")
    res = await client.patch(f"/api/v1/posts/{other}", json={"code": "pm"})
    assert res.status_code == 409
    assert res.json()["type"] == "post.CODE_DUPLICATE"


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


# ---- 绑定全量替换并发 last-writer-wins（事务级行锁串行化，镜像 role F3）---


async def test_delete_post_cascades_user_posts(client: AsyncClient) -> None:
    # Codex 深审：FK ondelete=CASCADE —— 删岗位后 user_posts 绑定自动清理。
    uid = await _seed_user(username="u-cascade")
    pid = await _seed_post(code="cas")
    async with db_session() as session:
        await PostRepository(session).set_user_posts(uid, [pid])
    res = await client.delete(f"/api/v1/posts/{pid}")
    assert res.status_code == 204
    async with db_session() as session:
        posts = await PostRepository(session).list_posts_for_user(uid)
    assert posts == []


async def test_set_user_posts_concurrent_last_writer_wins(client: AsyncClient) -> None:
    # 两请求并发把同一 user 的岗位分别替换为 [p1] / [p2]：事务级行锁串行化后最终恰好
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


# ---- Excel 导入导出端到端往返（P5）----------------------------------------


async def test_excel_import_export_roundtrip(client: AsyncClient) -> None:
    content = ExcelExporter(POST_EXCEL_COLUMNS).write(
        [
            {"name": "工程师", "code": "eng", "sort_order": 1, "status": "active"},
            {"name": "经理", "code": "mgr", "sort_order": 2, "status": "disabled"},
        ]
    )
    res = await client.post(
        "/api/v1/posts/import", files={"upload": ("p.xlsx", content, _XLSX_MEDIA)}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 2
    assert body["errors"] == []
    # 入库确认
    listing = (await client.get("/api/v1/posts")).json()
    assert {p["code"] for p in listing["items"]} == {"eng", "mgr"}
    # 导出往返：canonical row 一致
    exp = await client.get("/api/v1/posts/export")
    assert exp.status_code == 200
    assert exp.headers["content-type"].startswith("application/vnd.openxmlformats")
    parsed = ExcelImporter(PostCreate, POST_EXCEL_COLUMNS).parse(exp.content)
    assert {p.data.code for p in parsed.rows} == {"eng", "mgr"}
    assert {(p.data.name, p.data.status) for p in parsed.rows} == {
        ("工程师", "active"),
        ("经理", "disabled"),
    }


async def test_excel_import_db_duplicate_no_write(client: AsyncClient) -> None:
    await _create(client, code="eng", name="已存在")
    content = ExcelExporter(POST_EXCEL_COLUMNS).write([{"name": "新", "code": "eng"}])
    res = await client.post(
        "/api/v1/posts/import", files={"upload": ("p.xlsx", content, _XLSX_MEDIA)}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == 0  # 全有全无：库内重复 → 不写
    assert any(e["code"] == "DB_DUPLICATE" for e in body["errors"])
    # 库内仍只有预建的 eng（未写新行）
    assert (await client.get("/api/v1/posts")).json()["total"] == 1


def _audit_actions(caplog: pytest.LogCaptureFixture, *, status: str) -> list[str]:
    """取审计事件 action（按结果状态过滤）——审计经 admin_platform.audit logger 发 audit_event。"""
    actions: list[str] = []
    for record in caplog.records:
        event = getattr(record, "audit_event", None)
        if event is not None and event["result"]["status"] == status:
            actions.append(event["action"])
    return actions


async def test_excel_import_export_emit_audit(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # 导入/导出是数据进出取证点（导出=数据外泄取证）——须各 emit 一条成功审计（对抗审查 R5 补盲区：
    # 新增的 export audited_write 此前零测试断言）。
    content = ExcelExporter(POST_EXCEL_COLUMNS).write(
        [{"name": "工程师", "code": "eng", "sort_order": 1, "status": "active"}]
    )
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        imp = await client.post(
            "/api/v1/posts/import", files={"upload": ("p.xlsx", content, _XLSX_MEDIA)}
        )
        assert imp.status_code == 200, imp.text
        exp = await client.get("/api/v1/posts/export")
        assert exp.status_code == 200
    actions = _audit_actions(caplog, status="success")
    assert "system:post:import" in actions
    assert "system:post:export" in actions
