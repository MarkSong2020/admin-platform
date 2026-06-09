"""ConfigService 单元测试 —— stub repository 覆盖业务分支（DB-free）。

覆盖：分页 envelope / key 唯一预检 409 / get|delete 404 / **内置参数禁删 409** / get_value 读穿 404。
stub 返回预置全字段的 transient ``Config``（``default=`` 只在 flush 生效，transient 需手工补齐）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.config.models import Config
from admin_platform.domains.config.schemas import ConfigCreate, ConfigUpdate
from admin_platform.domains.config.service import ConfigService

_TS = datetime(2026, 6, 9, tzinfo=UTC)


def _config(cid: int, *, key: str = "k", value: str = "v", is_builtin: bool = False) -> Config:
    obj = Config(name="参数", config_key=key, config_value=value)
    obj.id = cid
    obj.is_builtin = is_builtin
    obj.remark = None
    obj.created_at = _TS
    obj.updated_at = _TS
    return obj


class _StubRepo:
    def __init__(self, *, rows: list[Config] | None = None) -> None:
        self._rows = {row.id: row for row in (rows or [])}
        self._by_key = {row.config_key: row for row in (rows or [])}

    async def list_paginated(self, *, keyword: str | None, page: int, size: int) -> list[Config]:
        return list(self._rows.values())

    async def count(self, *, keyword: str | None) -> int:
        return len(self._rows)

    async def get(self, item_id: int) -> Config | None:
        return self._rows.get(item_id)

    async def find_by_key(self, config_key: str) -> Config | None:
        return self._by_key.get(config_key)

    async def create(self, payload: ConfigCreate) -> Config:
        return _config(1, key=payload.config_key, value=payload.config_value)

    async def update(self, item_id: int, payload: object) -> Config | None:
        return self._rows.get(item_id)

    async def delete(self, item_id: int) -> bool:
        return self._rows.pop(item_id, None) is not None


def _svc(repo: _StubRepo) -> ConfigService:
    return ConfigService(repo)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_pagination_envelope() -> None:
    repo = _StubRepo(rows=[_config(i, key=f"k{i}") for i in range(1, 4)])
    page = await _svc(repo).list_(keyword=None, page=1, size=10)
    assert page.total == 3
    assert page.total_pages == 1


@pytest.mark.asyncio
async def test_get_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get(999)
    assert exc.value.code == "config.NOT_FOUND"


@pytest.mark.asyncio
async def test_create_duplicate_key_raises_409() -> None:
    repo = _StubRepo(rows=[_config(1, key="sys.x")])
    with pytest.raises(AppError) as exc:
        await _svc(repo).create(ConfigCreate(name="x", config_key="sys.x", config_value="1"))
    assert exc.value.code == "config.KEY_DUPLICATE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_returns_read_dto() -> None:
    out = await _svc(_StubRepo()).create(
        ConfigCreate(name="x", config_key="sys.new", config_value="42")
    )
    assert out.config_key == "sys.new"
    assert out.config_value == "42"


@pytest.mark.asyncio
async def test_delete_builtin_raises_409() -> None:
    repo = _StubRepo(rows=[_config(1, key="sys.locked", is_builtin=True)])
    with pytest.raises(AppError) as exc:
        await _svc(repo).delete(1)
    assert exc.value.code == "config.BUILTIN_READONLY"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.code == "config.NOT_FOUND"


@pytest.mark.asyncio
async def test_update_missing_raises_404() -> None:
    # 对抗审查 S7：PATCH 到不存在 id 的 404 分支（repo.update 返回 None）。
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).update(999, ConfigUpdate(config_value="x"))
    assert exc.value.code == "config.NOT_FOUND"


@pytest.mark.asyncio
async def test_get_value_reads_through_by_key() -> None:
    repo = _StubRepo(rows=[_config(1, key="sys.user.initPassword", value="changeit")])
    out = await _svc(repo).get_value("sys.user.initPassword")
    assert out.config_value == "changeit"


@pytest.mark.asyncio
async def test_get_value_missing_key_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get_value("nope")
    assert exc.value.code == "config.NOT_FOUND"
