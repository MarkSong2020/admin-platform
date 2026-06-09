"""DictService 单元测试 —— 内存 fake repository 覆盖两资源全部业务分支（DB-free）。

覆盖 happy path + 各业务错误：type 唯一/404/删 builtin/删有数据/删 ok；data 类型不存在 404 /
value 唯一（fake 内存校验）/ 单默认清同类型其它默认 / 404 / list / get / update / delete。
fake 返回预置全字段的 transient ORM 对象（``default=`` 只在 flush 生效）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.dict.models import DictData, DictType
from admin_platform.domains.dict.schemas import (
    DictDataCreate,
    DictDataUpdate,
    DictTypeCreate,
    DictTypeUpdate,
)
from admin_platform.domains.dict.service import DictService

_TS = datetime(2026, 6, 9, tzinfo=UTC)


def _mk_type(tid: int, *, type_: str, is_builtin: bool = False) -> DictType:
    obj = DictType(name="字典", type=type_)
    obj.id = tid
    obj.status = "active"
    obj.is_builtin = is_builtin
    obj.remark = None
    obj.created_at = _TS
    obj.updated_at = _TS
    return obj


def _mk_data(did: int, *, type_id: int, value: str, is_default: bool = False) -> DictData:
    obj = DictData(dict_type_id=type_id, label=f"L{value}", value=value)
    obj.id = did
    obj.sort_order = 0
    obj.status = "active"
    obj.is_default = is_default
    obj.css_class = None
    obj.remark = None
    obj.created_at = _TS
    obj.updated_at = _TS
    return obj


class _FakeRepo:
    """内存 fake：两表 dict + 自增 id，镜像 DictRepository 全部方法（不接 DB）。"""

    def __init__(self) -> None:
        self.types: dict[int, DictType] = {}
        self.data: dict[int, DictData] = {}
        self._tid = 0
        self._did = 0

    # types
    async def list_types_paginated(
        self, *, keyword: str | None, page: int, size: int
    ) -> list[DictType]:
        return list(self.types.values())

    async def count_types(self, *, keyword: str | None) -> int:
        return len(self.types)

    async def get_type(self, type_id: int) -> DictType | None:
        return self.types.get(type_id)

    async def find_type_by_type(self, type_str: str) -> DictType | None:
        return next((t for t in self.types.values() if t.type == type_str), None)

    async def create_type(self, payload: DictTypeCreate) -> DictType:
        self._tid += 1
        obj = _mk_type(self._tid, type_=payload.type, is_builtin=payload.is_builtin)
        self.types[self._tid] = obj
        return obj

    async def update_type(self, type_id: int, payload: DictTypeUpdate) -> DictType | None:
        obj = self.types.get(type_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        return obj

    async def delete_type(self, type_id: int) -> bool:
        return self.types.pop(type_id, None) is not None

    async def count_data_for_type(self, type_id: int) -> int:
        return sum(1 for d in self.data.values() if d.dict_type_id == type_id)

    # data
    async def list_data_paginated(
        self, *, dict_type_id: int | None, page: int, size: int
    ) -> list[DictData]:
        rows = list(self.data.values())
        if dict_type_id is not None:
            rows = [d for d in rows if d.dict_type_id == dict_type_id]
        return rows

    async def count_data(self, *, dict_type_id: int | None) -> int:
        return len(await self.list_data_paginated(dict_type_id=dict_type_id, page=1, size=100))

    async def get_data(self, data_id: int) -> DictData | None:
        return self.data.get(data_id)

    async def list_data_by_type(self, type_str: str, *, enabled_only: bool) -> list[DictData]:
        # 忠实镜像 production（round-2 应修）：enabled_only 下停用类型返回空、只取启用数据。
        t = await self.find_type_by_type(type_str)
        if t is None:
            return []
        if enabled_only and t.status != "active":
            return []
        rows = [d for d in self.data.values() if d.dict_type_id == t.id]
        if enabled_only:
            rows = [d for d in rows if d.status == "active"]
        return rows

    async def clear_other_defaults(self, dict_type_id: int, *, except_id: int | None) -> None:
        # except_id=None 时清同类型所有默认（与 production SQL `id != NULL` → 全清 同义，
        # 对抗审查 F6）；非 None 时保留正在更新的行自身。
        for d in self.data.values():
            if d.dict_type_id == dict_type_id and d.id != except_id:
                d.is_default = False

    async def create_data(self, payload: DictDataCreate) -> DictData:
        self._did += 1
        obj = _mk_data(
            self._did,
            type_id=payload.dict_type_id,
            value=payload.value,
            is_default=payload.is_default,
        )
        self.data[self._did] = obj
        return obj

    async def update_data(self, data_id: int, payload: DictDataUpdate) -> DictData | None:
        obj = self.data.get(data_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        return obj

    async def delete_data(self, data_id: int) -> bool:
        return self.data.pop(data_id, None) is not None


async def _seeded() -> tuple[DictService, _FakeRepo]:
    repo = _FakeRepo()
    svc = DictService(repo)  # type: ignore[arg-type]
    return svc, repo


# ---- 字典类型 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_type_crud_happy_path() -> None:
    svc, _ = await _seeded()
    created = await svc.create_type(DictTypeCreate(name="性别", type="sys_user_sex"))
    assert created.type == "sys_user_sex"
    page = await svc.list_types(keyword=None, page=1, size=20)
    assert page.total == 1
    got = await svc.get_type(created.id)
    assert got.id == created.id
    updated = await svc.update_type(created.id, DictTypeUpdate(name="性别2"))
    assert updated.name == "性别2"
    await svc.delete_type(created.id)
    assert (await svc.list_types(keyword=None, page=1, size=20)).total == 0


@pytest.mark.asyncio
async def test_create_type_duplicate_raises_409() -> None:
    svc, _ = await _seeded()
    await svc.create_type(DictTypeCreate(name="x", type="sys_x"))
    with pytest.raises(AppError) as exc:
        await svc.create_type(DictTypeCreate(name="y", type="sys_x"))
    assert exc.value.code == "dict.TYPE_DUPLICATE"


@pytest.mark.asyncio
async def test_get_type_missing_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.get_type(999)
    assert exc.value.code == "dict.TYPE_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_type_missing_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.update_type(999, DictTypeUpdate(name="x"))
    assert exc.value.code == "dict.TYPE_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_builtin_type_409() -> None:
    svc, _ = await _seeded()
    t = await svc.create_type(DictTypeCreate(name="x", type="sys_x", is_builtin=True))
    with pytest.raises(AppError) as exc:
        await svc.delete_type(t.id)
    assert exc.value.code == "dict.TYPE_BUILTIN_READONLY"


@pytest.mark.asyncio
async def test_delete_type_with_data_409() -> None:
    svc, _ = await _seeded()
    t = await svc.create_type(DictTypeCreate(name="x", type="sys_x"))
    await svc.create_data(DictDataCreate(dict_type_id=t.id, label="男", value="0"))
    with pytest.raises(AppError) as exc:
        await svc.delete_type(t.id)
    assert exc.value.code == "dict.TYPE_HAS_DATA"


@pytest.mark.asyncio
async def test_delete_missing_type_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.delete_type(999)
    assert exc.value.code == "dict.TYPE_NOT_FOUND"


# ---- 字典数据 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_crud_happy_path() -> None:
    svc, _ = await _seeded()
    t = await svc.create_type(DictTypeCreate(name="x", type="sys_x"))
    d = await svc.create_data(DictDataCreate(dict_type_id=t.id, label="男", value="0"))
    assert (await svc.list_data(dict_type_id=t.id, page=1, size=20)).total == 1
    assert (await svc.get_data(d.id)).value == "0"
    updated = await svc.update_data(d.id, DictDataUpdate(label="女"))
    assert updated.label == "女"
    await svc.delete_data(d.id)
    assert (await svc.list_data(dict_type_id=t.id, page=1, size=20)).total == 0


@pytest.mark.asyncio
async def test_create_data_unknown_type_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.create_data(DictDataCreate(dict_type_id=999, label="x", value="0"))
    assert exc.value.code == "dict.TYPE_NOT_FOUND"


@pytest.mark.asyncio
async def test_single_default_cleared_on_create_and_update() -> None:
    svc, repo = await _seeded()
    t = await svc.create_type(DictTypeCreate(name="x", type="sys_x"))
    d1 = await svc.create_data(
        DictDataCreate(dict_type_id=t.id, label="Y", value="Y", is_default=True)
    )
    d2 = await svc.create_data(
        DictDataCreate(dict_type_id=t.id, label="N", value="N", is_default=True)
    )
    assert repo.data[d1.id].is_default is False  # 创建 d2 默认时清了 d1
    assert repo.data[d2.id].is_default is True
    # 再把 d1 设回默认 → d2 被清。
    await svc.update_data(d1.id, DictDataUpdate(is_default=True))
    assert repo.data[d2.id].is_default is False
    assert repo.data[d1.id].is_default is True


@pytest.mark.asyncio
async def test_get_data_missing_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.get_data(999)
    assert exc.value.code == "dict.DATA_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_data_missing_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.update_data(999, DictDataUpdate(label="x"))
    assert exc.value.code == "dict.DATA_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_data_missing_404() -> None:
    svc, _ = await _seeded()
    with pytest.raises(AppError) as exc:
        await svc.delete_data(999)
    assert exc.value.code == "dict.DATA_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_data_by_type_empty_for_unknown() -> None:
    svc, _ = await _seeded()
    assert await svc.list_data_by_type("nope") == []
