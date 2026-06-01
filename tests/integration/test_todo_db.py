"""/api/v1/todos 的集成测试 — 真实 Postgres CRUD。

覆盖（todo domain 自身 + 与 tag 的多对多）：

  * 201 happy create — 默认空 tags
  * 200 list — 分页 envelope + N+1 守门
  * 404 TODO_NOT_FOUND（GET / PATCH / DELETE）
  * 409 TODO_TITLE_DUPLICATE（重名）
  * 422 TODO_TAG_NOT_FOUND（tag_ids 含不存在 id）
  * 200 PATCH 状态转换 + 204 DELETE
  * **Tag 关联 E2E**：create with tag_ids → 重新 SELECT 看到关联
  * **N+1 守门**：list 10 个 todo + tags 发出的 SELECT ≤ 8

集成测试 conftest 默认关闭 idempotency；本套件不依赖 Redis。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import event, text

from admin_platform.db.engine import get_engine
from admin_platform.domains.todo.repository import TodoRepository

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _truncate_all() -> AsyncIterator[None]:
    """每个 test 跑前清空三张表，保证 seed 计数可预测（FK-aware 顺序 + 重置自增）。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE todo_tags, todos, tags RESTART IDENTITY CASCADE"))
    yield


async def test_create_then_get_round_trips(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/v1/todos", json={"title": "buy milk"})
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "buy milk"
    assert body["status"] == "OPEN"
    assert body["due_at"] is None
    assert body["tags"] == []

    fetched = await async_client.get(f"/api/v1/todos/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "buy milk"


async def test_get_missing_returns_404_with_typed_code(async_client: AsyncClient) -> None:
    res = await async_client.get("/api/v1/todos/999")
    assert res.status_code == 404
    body = res.json()
    assert body["type"] == "admin_platform.TODO_NOT_FOUND"
    assert body["detail"] == "id=999"


async def test_duplicate_title_returns_409_with_typed_code(async_client: AsyncClient) -> None:
    first = await async_client.post("/api/v1/todos", json={"title": "alpha"})
    assert first.status_code == 201
    dup = await async_client.post("/api/v1/todos", json={"title": "alpha"})
    assert dup.status_code == 409
    assert dup.json()["type"] == "admin_platform.TODO_TITLE_DUPLICATE"


async def test_patch_status_transition_commits(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/v1/todos", json={"title": "work"})
    item_id = created.json()["id"]

    patched = await async_client.patch(f"/api/v1/todos/{item_id}", json={"status": "DONE"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "DONE"

    refetched = await async_client.get(f"/api/v1/todos/{item_id}")
    assert refetched.json()["status"] == "DONE"


async def test_patch_missing_returns_404(async_client: AsyncClient) -> None:
    res = await async_client.patch("/api/v1/todos/999", json={"title": "nope"})
    assert res.status_code == 404
    assert res.json()["type"] == "admin_platform.TODO_NOT_FOUND"


async def test_delete_then_get_returns_404(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/v1/todos", json={"title": "ephemeral"})
    item_id = created.json()["id"]

    deleted = await async_client.delete(f"/api/v1/todos/{item_id}")
    assert deleted.status_code == 204

    refetched = await async_client.get(f"/api/v1/todos/{item_id}")
    assert refetched.status_code == 404


async def test_list_returns_pagination_envelope(async_client: AsyncClient) -> None:
    for i in range(5):
        await async_client.post("/api/v1/todos", json={"title": f"item-{i}"})

    res = await async_client.get("/api/v1/todos?page=1&size=3")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["size"] == 3
    assert body["total_pages"] == 2
    assert len(body["items"]) == 3
    # 每个 list 项必须带 tags 字段（即使为空）。
    assert all("tags" in item for item in body["items"])


# --------------------------------------------------------------------------- #
# v0.5.1 — tag 关联 E2E                                                       #
# --------------------------------------------------------------------------- #


async def test_create_todo_with_tag_ids_associates_via_secondary(
    async_client: AsyncClient,
) -> None:
    tag_urgent = (await async_client.post("/api/v1/tags", json={"name": "urgent"})).json()
    tag_home = (await async_client.post("/api/v1/tags", json={"name": "home"})).json()

    created = await async_client.post(
        "/api/v1/todos",
        json={"title": "buy milk", "tag_ids": [tag_urgent["id"], tag_home["id"]]},
    )
    assert created.status_code == 201
    body = created.json()
    assert {t["name"] for t in body["tags"]} == {"urgent", "home"}

    # 走新请求重新 fetch —— 验证关联行真的 commit 了（不是仅在同一请求
    # 的 session 里临时可见）。
    refetched = await async_client.get(f"/api/v1/todos/{body['id']}")
    assert {t["name"] for t in refetched.json()["tags"]} == {"urgent", "home"}


async def test_create_todo_with_missing_tag_id_returns_422(
    async_client: AsyncClient,
) -> None:
    res = await async_client.post("/api/v1/todos", json={"title": "buy milk", "tag_ids": [999]})
    assert res.status_code == 422
    body = res.json()
    assert body["type"] == "admin_platform.TODO_TAG_NOT_FOUND"
    assert "missing_tag_ids=[999]" in body["detail"]


async def test_patch_todo_with_empty_tag_ids_clears_association(
    async_client: AsyncClient,
) -> None:
    tag = (await async_client.post("/api/v1/tags", json={"name": "urgent"})).json()
    created = await async_client.post(
        "/api/v1/todos", json={"title": "buy milk", "tag_ids": [tag["id"]]}
    )
    todo_id = created.json()["id"]

    cleared = await async_client.patch(f"/api/v1/todos/{todo_id}", json={"tag_ids": []})
    assert cleared.status_code == 200
    assert cleared.json()["tags"] == []


async def test_unique_constraint_race_returns_409_not_500(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """竞态 race：service.find_by_title 预检与 repo.create 之间撞 DB 唯一约束。

    场景：两个并发请求同时通过 find_by_title 预检（都查到「不存在」），各自
    INSERT → 第二个撞 ``uq_todos_title`` → asyncpg UniqueViolationError →
    SQLAlchemy IntegrityError。

    本测试用 monkeypatch 让 ``find_by_title`` 总返回 None（模拟预检失明的
    race 窗口），结合先用 raw SQL 插入一行制造冲突状态。验证
    ``core/errors.py`` 的 IntegrityError handler 把这种竞态兜底成 409 +
    typed 业务错误码，而不是退化成 500。

    v0.5.2-audit.1 review 抓到的 P1 修复，本测试守护此回归。
    """
    # 先用 raw SQL 直接插一行（绕过 service 预检层）。
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO todos (title, status) VALUES ('alpha', 'OPEN')"))

    # 让 service 层的 find_by_title 永远返回 None ——模拟「预检时数据还没出现」
    # 这个 race 窗口。第二步 repo.create 真撞约束时，IntegrityError 兜底。
    async def _always_none(self, title: str):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(TodoRepository, "find_by_title", _always_none)

    res = await async_client.post("/api/v1/todos", json={"title": "alpha"})
    assert res.status_code == 409, f"竞态应该走 409，实际 {res.status_code}：{res.text}"
    body = res.json()
    # 验证 typed 业务码（来自 todo/models.py 的 register_unique_constraint）
    assert body["type"] == "admin_platform.TODO_TITLE_DUPLICATE"
    # detail 不暴露 DB 约束名（内部 schema 名不是对外契约）
    assert body["detail"] is None


async def test_delete_tag_cascades_through_association(async_client: AsyncClient) -> None:
    """todo_tags.tag_id 上的 ON DELETE CASCADE —— 删 tag 必须删掉关联行，
    但 todo 本身保留。"""
    tag = (await async_client.post("/api/v1/tags", json={"name": "urgent"})).json()
    created = await async_client.post(
        "/api/v1/todos", json={"title": "buy milk", "tag_ids": [tag["id"]]}
    )
    todo_id = created.json()["id"]

    deleted = await async_client.delete(f"/api/v1/tags/{tag['id']}")
    assert deleted.status_code == 204

    # Todo 还在；tags 集合现在为空。
    refetched = await async_client.get(f"/api/v1/todos/{todo_id}")
    assert refetched.status_code == 200
    assert refetched.json()["tags"] == []


# --------------------------------------------------------------------------- #
# N+1 守门                                                                    #
# --------------------------------------------------------------------------- #


async def test_list_todos_with_tags_does_not_trigger_n_plus_1(
    async_client: AsyncClient,
) -> None:
    """回归守门：``list_paginated`` 发出的 SELECT 数量必须与 N（todo 行数）
    无关。没有 ``selectinload(Todo.tags)`` 的话每行会触发一次额外 SELECT
    （经典 async N+1）—— 但 ``Todo.tags`` 声明 ``lazy="raise"``，实际上会
    直接 crash 而不是 slow burn。本测试同时守 SELECT 计数 + constant-query
    属性。

    /api/v1/todos?size=10 + 10 行带 tag 的期望 query plan：
      1. COUNT(*) FROM todos               （分页 total）
      2. SELECT ... FROM todos LIMIT       （取页）
      3. SELECT ... FROM tags WHERE id IN  （selectinload 后续）
      4. SELECT ... FROM todo_tags WHERE todo_id IN  （多对多关联解析）

    预算：5 个 SELECT。超过即 N+1 回归。
    """
    # Seed：1 个 tag，10 个 todo 都关联它。
    tag = (await async_client.post("/api/v1/tags", json={"name": "urgent"})).json()
    for i in range(10):
        await async_client.post(
            "/api/v1/todos", json={"title": f"item-{i}", "tag_ids": [tag["id"]]}
        )

    # Hook SELECT event；只数 list 调用本身发的 SELECT。
    engine = get_engine().sync_engine
    select_count = 0

    def _on_before_execute(_conn, _clause, _multiparams, _params, _execution_options):
        nonlocal select_count
        sql = str(_clause).strip().upper()
        if sql.startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_execute", _on_before_execute)
    try:
        res = await async_client.get("/api/v1/todos?page=1&size=10")
    finally:
        event.remove(engine, "before_execute", _on_before_execute)

    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 10
    # 所有 10 行都带它们关联的那个 tag（证明 selectinload 真的跑了）。
    assert all(len(item["tags"]) == 1 for item in body["items"])
    # constant-query 预算：8 个 SELECT 覆盖 count + page + tags + 多对多
    # + 某些驱动首次用时的 alembic_version 探查。≥ 10 就是 per-row lazy
    # load 漏过来了。
    assert select_count <= 8, f"N+1 回归：{select_count} 个 SELECT 用于 10 行 todo"
