"""数据字典 CRUD 集成测试（P3）—— 真 DB 全路径（两资源）+ 跨表不变式。

需本地 DB。覆盖：type/data CRUD + 404；type 重复 409；**删有数据的类型 409 TYPE_HAS_DATA（FK
RESTRICT 不级联）**；data 同类型 value 唯一 409 / 跨类型可复用；**单默认值**（设新默认清旧默认）；
消费端点 /data/type/{type} 取启用数据并排序；create_data 类型不存在 404；权限矩阵 403。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.dict.api import router as dict_router
from admin_platform.domains.dict.models import DictData

pytestmark = pytest.mark.integration


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


class _NoPermProvider(PermissionProvider):
    def get_is_active(self, user_id: int) -> bool:
        return True

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE dict_data, dict_types CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client(provider: type[PermissionProvider]) -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(dict_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(user_id="1", sub="1")
    app.dependency_overrides[get_permission_provider] = provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _new_type(c: AsyncClient, *, type_str: str, is_builtin: bool = False) -> int:
    res = await c.post(
        "/api/v1/dict/types",
        json={"name": type_str, "type": type_str, "is_builtin": is_builtin},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _new_data(
    c: AsyncClient, *, type_id: int, value: str, is_default: bool = False, status: str = "active"
) -> int:
    res = await c.post(
        "/api/v1/dict/data",
        json={
            "dict_type_id": type_id,
            "label": f"L{value}",
            "value": value,
            "is_default": is_default,
            "status": status,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_type_crud_and_duplicate() -> None:
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_user_sex")
        assert (await c.get("/api/v1/dict/types")).json()["total"] == 1
        assert (await c.get(f"/api/v1/dict/types/{tid}")).json()["type"] == "sys_user_sex"
        # type 重复 → 409
        dup = await c.post("/api/v1/dict/types", json={"name": "x", "type": "sys_user_sex"})
        assert dup.status_code == 409
        assert dup.json()["type"] == "dict.TYPE_DUPLICATE"
        # 删空类型 ok
        assert (await c.delete(f"/api/v1/dict/types/{tid}")).status_code == 204
        assert (await c.get(f"/api/v1/dict/types/{tid}")).status_code == 404


async def test_delete_type_with_data_restricted() -> None:
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_status")
        await _new_data(c, type_id=tid, value="0")
        res = await c.delete(f"/api/v1/dict/types/{tid}")
        assert res.status_code == 409
        assert res.json()["type"] == "dict.TYPE_HAS_DATA"
        # 类型与数据都还在（未级联删）。
        assert (await c.get(f"/api/v1/dict/types/{tid}")).status_code == 200


async def test_delete_builtin_type_forbidden() -> None:
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_locked", is_builtin=True)
        res = await c.delete(f"/api/v1/dict/types/{tid}")
        assert res.status_code == 409
        assert res.json()["type"] == "dict.TYPE_BUILTIN_READONLY"


async def test_data_value_unique_per_type_but_reusable_across_types() -> None:
    async with _client(_SuperProvider) as c:
        t1 = await _new_type(c, type_str="sys_a")
        t2 = await _new_type(c, type_str="sys_b")
        await _new_data(c, type_id=t1, value="0")
        # 同类型 value 重复 → 409
        dup = await c.post(
            "/api/v1/dict/data", json={"dict_type_id": t1, "label": "x", "value": "0"}
        )
        assert dup.status_code == 409
        assert dup.json()["type"] == "dict.DATA_DUPLICATE"
        # 跨类型同 value → ok
        ok = await c.post(
            "/api/v1/dict/data", json={"dict_type_id": t2, "label": "x", "value": "0"}
        )
        assert ok.status_code == 201


async def test_single_default_per_type() -> None:
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_yes_no")
        d1 = await _new_data(c, type_id=tid, value="Y", is_default=True)
        d2 = await _new_data(c, type_id=tid, value="N", is_default=True)
        # 设 d2 为默认后，d1 的 is_default 被清。
        assert (await c.get(f"/api/v1/dict/data/{d1}")).json()["is_default"] is False
        assert (await c.get(f"/api/v1/dict/data/{d2}")).json()["is_default"] is True


async def test_consumption_endpoint_returns_enabled_sorted() -> None:
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_user_sex")
        await _new_data(c, type_id=tid, value="1")  # sort_order 默认 0
        await _new_data(c, type_id=tid, value="0")
        await _new_data(c, type_id=tid, value="2", status="disabled")  # 停用 → 不出现
        res = await c.get("/api/v1/dict/data/type/sys_user_sex")
        assert res.status_code == 200
        values = [d["value"] for d in res.json()]
        assert values == ["1", "0"]  # 启用项，按 sort_order(0,0) 后 id 序
        # 不存在的类型 → 空列表（非 404）。
        assert (await c.get("/api/v1/dict/data/type/nope")).json() == []


async def test_partial_unique_index_blocks_two_defaults() -> None:
    # 对抗审查 B1：DB partial unique index 兜底——绕过 service clear-siblings 直接插两条
    # is_default=true 同类型 → 第二条撞 uq_dict_data_one_default_per_type → IntegrityError。
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_bool")
    async with db_session() as session:
        session.add(DictData(dict_type_id=tid, label="是", value="Y", is_default=True))
        await session.flush()
        session.add(DictData(dict_type_id=tid, label="否", value="N", is_default=True))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_disabled_type_consumption_returns_empty() -> None:
    # 对抗审查 S3：停用的字典类型不应继续向消费端点下发数据。
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_off")
        await _new_data(c, type_id=tid, value="0")
        assert len((await c.get("/api/v1/dict/data/type/sys_off")).json()) == 1
        # 停用类型后消费端点返回空。
        assert (
            await c.patch(f"/api/v1/dict/types/{tid}", json={"status": "disabled"})
        ).status_code == 200
        assert (await c.get("/api/v1/dict/data/type/sys_off")).json() == []


async def test_patch_missing_type_and_data_404() -> None:
    # 对抗审查 S7：真 DB 下 update 不存在 id 返回 404 而非 500。
    async with _client(_SuperProvider) as c:
        t = await c.patch("/api/v1/dict/types/999999", json={"name": "x"})
        assert t.status_code == 404
        assert t.json()["type"] == "dict.TYPE_NOT_FOUND"
        d = await c.patch("/api/v1/dict/data/999999", json={"label": "x"})
        assert d.status_code == 404
        assert d.json()["type"] == "dict.DATA_NOT_FOUND"


async def test_unprotect_builtin_type_then_delete() -> None:
    # 对抗审查 S2：内置类型先 PATCH is_builtin=false 解保护后可删（消除「永久不可删」不可逆）。
    async with _client(_SuperProvider) as c:
        tid = await _new_type(c, type_str="sys_protected", is_builtin=True)
        assert (await c.delete(f"/api/v1/dict/types/{tid}")).status_code == 409
        assert (
            await c.patch(f"/api/v1/dict/types/{tid}", json={"is_builtin": False})
        ).status_code == 200
        assert (await c.delete(f"/api/v1/dict/types/{tid}")).status_code == 204


async def test_create_data_unknown_type_404() -> None:
    async with _client(_SuperProvider) as c:
        res = await c.post(
            "/api/v1/dict/data", json={"dict_type_id": 999999, "label": "x", "value": "0"}
        )
        assert res.status_code == 404
        assert res.json()["type"] == "dict.TYPE_NOT_FOUND"


async def test_permission_matrix_403() -> None:
    async with _client(_NoPermProvider) as c:
        assert (await c.get("/api/v1/dict/types")).status_code == 403
        assert (await c.get("/api/v1/dict/data")).status_code == 403
        assert (await c.get("/api/v1/dict/data/type/sys_user_sex")).status_code == 403
        assert (
            await c.post("/api/v1/dict/types", json={"name": "x", "type": "y"})
        ).status_code == 403
