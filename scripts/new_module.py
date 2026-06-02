"""在 ``src/<service>/domains/<name>/`` 下生成一个业务 domain 模块。

设计源：``doc/standards/CODE_GENERATOR.md``。CLI 是 argparse + 纯 flag；
模板作为模块级常量嵌入，用 ``str.format`` 渲染。

用法::

    uv run python scripts/new_module.py --name order [--with-model] [--dry-run]
"""

from __future__ import annotations

import argparse
import contextlib
import keyword
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parent.parent

NAME_REGEX = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_NAMES = frozenset(
    {"models", "schemas", "api", "service", "repository", "test", "tests", "db", "core", "main"}
)


@dataclass(frozen=True)
class Context:
    service: str
    name: str
    name_pascal: str
    name_upper: str
    plural: str
    plural_pascal: str
    with_model: bool

    def as_format_kwargs(self) -> dict[str, str]:
        return {
            "service": self.service,
            "name": self.name,
            "Name": self.name_pascal,
            "NAME_UPPER": self.name_upper,
            "plural": self.plural,
            "Plural": self.plural_pascal,
        }


# --------------------------------------------------------------------------- #
# 模板                                                                        #
# --------------------------------------------------------------------------- #

TEMPLATE_INIT = '"""{Name} domain 包。"""\n'


TEMPLATE_SCHEMAS = dedent('''\
    """{Name} DTO — {plural} API 的请求 / 响应形状。"""

    from __future__ import annotations

    from pydantic import BaseModel, ConfigDict


    class {Name}Base(BaseModel):
        model_config = ConfigDict(from_attributes=True)
        name: str


    class {Name}Create({Name}Base):
        pass


    class {Name}Update(BaseModel):
        model_config = ConfigDict(from_attributes=True)
        name: str | None = None


    class {Name}Read({Name}Base):
        id: int


    class {Name}Page(BaseModel):
        """分页 envelope（ADR 0001 §7.5）。"""

        model_config = ConfigDict(from_attributes=True)
        items: list[{Name}Read]
        page: int
        size: int
        total: int
        total_pages: int
''')


TEMPLATE_REPOSITORY_INMEM = dedent('''\
    """{Name} 内存版 repository — 在接真 DB 之前作为单测 stub。"""

    from __future__ import annotations

    from typing import Any

    from {service}.domains.{name}.schemas import {Name}Create, {Name}Update


    class {Name}Repository:
        def __init__(self) -> None:
            self._rows: dict[int, dict[str, Any]] = {{}}
            self._next_id: int = 1

        async def list_paginated(self, page: int, size: int) -> list[dict[str, Any]]:
            start = (page - 1) * size
            return list(self._rows.values())[start : start + size]

        async def count(self) -> int:
            return len(self._rows)

        async def get(self, item_id: int) -> dict[str, Any] | None:
            return self._rows.get(item_id)

        async def create(self, payload: {Name}Create) -> dict[str, Any]:
            row: dict[str, Any] = {{"id": self._next_id, **payload.model_dump()}}
            self._rows[self._next_id] = row
            self._next_id += 1
            return row

        async def update(self, item_id: int, payload: {Name}Update) -> dict[str, Any] | None:
            row = self._rows.get(item_id)
            if row is None:
                return None
            # RFC 7396 PATCH 语义：只更新调用方显式传入的字段；
            # 显式 None 是合法 update（DB repo 行为一致）。
            row.update(payload.model_dump(exclude_unset=True))
            return row

        async def delete(self, item_id: int) -> bool:
            return self._rows.pop(item_id, None) is not None
''')


TEMPLATE_REPOSITORY_DB = dedent('''\
    """{Name} repository — SQLAlchemy 2.x async 数据访问层。"""

    from __future__ import annotations

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from {service}.domains.{name}.models import {Name}
    from {service}.domains.{name}.schemas import {Name}Create, {Name}Update


    class {Name}Repository:
        def __init__(self, session: AsyncSession) -> None:
            self._session = session

        async def list_paginated(self, page: int, size: int) -> list[{Name}]:
            offset = (page - 1) * size
            stmt = select({Name}).offset(offset).limit(size).order_by({Name}.id)
            result = await self._session.execute(stmt)
            return list(result.scalars().all())

        async def count(self) -> int:
            stmt = select(func.count()).select_from({Name})
            result = await self._session.execute(stmt)
            return int(result.scalar_one())

        async def get(self, item_id: int) -> {Name} | None:
            return await self._session.get({Name}, item_id)

        async def create(self, payload: {Name}Create) -> {Name}:
            obj = {Name}(**payload.model_dump())
            self._session.add(obj)
            await self._session.flush()
            return obj

        async def update(self, item_id: int, payload: {Name}Update) -> {Name} | None:
            obj = await self._session.get({Name}, item_id)
            if obj is None:
                return None
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(obj, key, value)
            await self._session.flush()
            return obj

        async def delete(self, item_id: int) -> bool:
            obj = await self._session.get({Name}, item_id)
            if obj is None:
                return False
            await self._session.delete(obj)
            return True
''')


TEMPLATE_SERVICE = dedent('''\
    """{Name} service — 业务用例层。

    事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时**
    raise（触发请求事务回滚），也可以用 ``session.begin_nested()`` 开 SAVEPOINT
    做 saga 流程里的部分提交。
    """

    from __future__ import annotations

    from {service}.core.errors import AppError
    from {service}.domains.{name}.repository import {Name}Repository
    from {service}.domains.{name}.schemas import (
        {Name}Create,
        {Name}Page,
        {Name}Read,
        {Name}Update,
    )


    class {Name}Service:
        def __init__(self, repository: {Name}Repository) -> None:
            self._repo = repository

        async def list_(self, *, page: int, size: int) -> {Name}Page:
            """offset 分页（ADR 0001 §7.5 envelope）。"""
            rows = await self._repo.list_paginated(page, size)
            total = await self._repo.count()
            total_pages = (total + size - 1) // size if size > 0 else 0
            return {Name}Page(
                items=[{Name}Read.model_validate(row) for row in rows],
                page=page,
                size=size,
                total=total,
                total_pages=total_pages,
            )

        async def get(self, item_id: int) -> {Name}Read:
            row = await self._repo.get(item_id)
            if row is None:
                raise AppError(
                    code="{service}.{NAME_UPPER}_NOT_FOUND",
                    title="{Name} not found",
                    status_code=404,
                )
            return {Name}Read.model_validate(row)

        async def create(self, payload: {Name}Create) -> {Name}Read:
            row = await self._repo.create(payload)
            return {Name}Read.model_validate(row)

        async def update(self, item_id: int, payload: {Name}Update) -> {Name}Read:
            row = await self._repo.update(item_id, payload)
            if row is None:
                raise AppError(
                    code="{service}.{NAME_UPPER}_NOT_FOUND",
                    title="{Name} not found",
                    status_code=404,
                )
            return {Name}Read.model_validate(row)

        async def delete(self, item_id: int) -> None:
            ok = await self._repo.delete(item_id)
            if not ok:
                raise AppError(
                    code="{service}.{NAME_UPPER}_NOT_FOUND",
                    title="{Name} not found",
                    status_code=404,
                )
''')


TEMPLATE_API_INMEM = dedent('''\
    """{Plural} HTTP API — /api/v1/{plural} 下的 CRUD 路由。"""

    from __future__ import annotations

    from typing import Annotated

    from fastapi import APIRouter, Depends, Query, status

    from {service}.core.errors import ProblemDetail
    from {service}.core.idempotency import idempotent
    from {service}.domains.{name}.deps import get_{name}_service
    from {service}.domains.{name}.schemas import (
        {Name}Create,
        {Name}Page,
        {Name}Read,
        {Name}Update,
    )
    from {service}.domains.{name}.service import {Name}Service

    router = APIRouter(prefix="/api/v1/{plural}", tags=["{plural}"])

    ServiceDep = Annotated[{Name}Service, Depends(get_{name}_service)]
    PageQ = Annotated[int, Query(ge=1, description="页码（从 1 开始）")]
    SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]
    NOT_FOUND_RESPONSE: dict[int | str, dict[str, object]] = {{404: {{"model": ProblemDetail}}}}
    PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {{
        404: {{"model": ProblemDetail}},
        422: {{"model": ProblemDetail}},
    }}
    # v0.4.9+ IdempotencyMiddleware 在 middleware 层就会拒绝以下 POST 情况：
    #   400 framework.IDEMPOTENCY_KEY_INVALID        （key 超过 255 字符）
    #   409 framework.IDEMPOTENT_RETRY_IN_FLIGHT     （同 key+body 仍在运行）
    #   422 framework.IDEMPOTENCY_KEY_REUSED         （同 key 但 body 不同）
    # FastAPI 看不到这些状态码，所以 generator 必须在 ``responses=`` 显式声明，
    # 否则 SDK 生成器漏掉这些错误路径，下游代码只能 catch 一个泛型 Error。
    IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {{
        400: {{"model": ProblemDetail}},
        409: {{"model": ProblemDetail}},
        422: {{"model": ProblemDetail}},
    }}


    @router.get("", operation_id="{plural}_list", response_model={Name}Page)
    async def list_{plural}(svc: ServiceDep, page: PageQ = 1, size: SizeQ = 20) -> {Name}Page:
        return await svc.list_(page=page, size=size)


    @router.get(
        "/{{item_id}}",
        operation_id="{plural}_get",
        response_model={Name}Read,
        responses=NOT_FOUND_RESPONSE,
    )
    async def get_{name}(item_id: int, svc: ServiceDep) -> {Name}Read:
        return await svc.get(item_id)


    # ADR §11：POST 默认幂等 —— 调用方可以用同一个 Idempotency-Key header 安全
    # 重试。如果这个端点本身就幂等（如内容寻址上传）或者不想要客户端驱动的
    # 去重，把装饰器去掉就行。
    #
    # 装饰器顺序 —— ``@idempotent`` 必须放**最内层**（紧贴 ``async def``）。
    # 它是个 marker（在下面的函数上设置 ``_idempotent = True``）；外层如果有
    # 一个没用 ``functools.wraps`` 的简陋 wrapper，会丢掉这个属性，悄悄关闭
    # 去重（→ 重试时重复扣款）。``functools.wraps`` 会更新 ``__dict__``，所以
    # 这个属性确实能存活下来 —— 但放在最底层从根上回避这个问题。详见
    # ``core/idempotency.py`` 的 ``idempotent`` docstring；
    # ``tests/unit/test_idempotency.py`` 守门。
    #     @router.post(...)
    #     @require_auth     # 任何业务 wrapper 在外层
    #     @idempotent       # 最内层，紧贴 ``async def``
    #     async def create_xxx(...): ...
    @router.post(
        "",
        operation_id="{plural}_create",
        response_model={Name}Read,
        status_code=status.HTTP_201_CREATED,
        responses=IDEMPOTENT_POST_ERROR_RESPONSES,
    )
    @idempotent
    async def create_{name}(payload: {Name}Create, svc: ServiceDep) -> {Name}Read:
        return await svc.create(payload)


    @router.patch(
        "/{{item_id}}",
        operation_id="{plural}_update",
        response_model={Name}Read,
        responses=PATCH_ERROR_RESPONSES,
    )
    async def update_{name}(
        item_id: int, payload: {Name}Update, svc: ServiceDep
    ) -> {Name}Read:
        return await svc.update(item_id, payload)


    @router.delete(
        "/{{item_id}}",
        operation_id="{plural}_delete",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=NOT_FOUND_RESPONSE,
    )
    async def delete_{name}(item_id: int, svc: ServiceDep) -> None:
        await svc.delete(item_id)
''')


TEMPLATE_API_DB = dedent('''\
    """{Plural} HTTP API — /api/v1/{plural} 下的 CRUD 路由。"""

    from __future__ import annotations

    from typing import Annotated

    from fastapi import APIRouter, Depends, Query, status

    from {service}.core.errors import ProblemDetail
    from {service}.core.idempotency import idempotent
    from {service}.domains.{name}.deps import get_{name}_service
    from {service}.domains.{name}.schemas import (
        {Name}Create,
        {Name}Page,
        {Name}Read,
        {Name}Update,
    )
    from {service}.domains.{name}.service import {Name}Service

    router = APIRouter(prefix="/api/v1/{plural}", tags=["{plural}"])

    ServiceDep = Annotated[{Name}Service, Depends(get_{name}_service)]
    PageQ = Annotated[int, Query(ge=1, description="页码（从 1 开始）")]
    SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]
    NOT_FOUND_RESPONSE: dict[int | str, dict[str, object]] = {{404: {{"model": ProblemDetail}}}}
    PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {{
        404: {{"model": ProblemDetail}},
        422: {{"model": ProblemDetail}},
    }}
    # v0.4.9+ IdempotencyMiddleware 在 middleware 层就会拒绝以下 POST 情况：
    #   400 framework.IDEMPOTENCY_KEY_INVALID        （key 超过 255 字符）
    #   409 framework.IDEMPOTENT_RETRY_IN_FLIGHT     （同 key+body 仍在运行）
    #   422 framework.IDEMPOTENCY_KEY_REUSED         （同 key 但 body 不同）
    # FastAPI 看不到这些状态码，所以 generator 必须在 ``responses=`` 显式声明，
    # 否则 SDK 生成器漏掉这些错误路径，下游代码只能 catch 一个泛型 Error。
    IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {{
        400: {{"model": ProblemDetail}},
        409: {{"model": ProblemDetail}},
        422: {{"model": ProblemDetail}},
    }}


    @router.get("", operation_id="{plural}_list", response_model={Name}Page)
    async def list_{plural}(svc: ServiceDep, page: PageQ = 1, size: SizeQ = 20) -> {Name}Page:
        return await svc.list_(page=page, size=size)


    @router.get(
        "/{{item_id}}",
        operation_id="{plural}_get",
        response_model={Name}Read,
        responses=NOT_FOUND_RESPONSE,
    )
    async def get_{name}(item_id: int, svc: ServiceDep) -> {Name}Read:
        return await svc.get(item_id)


    # ADR §11：POST 默认幂等 —— 调用方可以用同一个 Idempotency-Key header 安全
    # 重试。如果这个端点本身就幂等（如内容寻址上传）或者不想要客户端驱动的
    # 去重，把装饰器去掉就行。
    #
    # 装饰器顺序 —— ``@idempotent`` 必须放**最内层**（紧贴 ``async def``）。
    # 它是个 marker（在下面的函数上设置 ``_idempotent = True``）；外层如果有
    # 一个没用 ``functools.wraps`` 的简陋 wrapper，会丢掉这个属性，悄悄关闭
    # 去重（→ 重试时重复扣款）。``functools.wraps`` 会更新 ``__dict__``，所以
    # 这个属性确实能存活下来 —— 但放在最底层从根上回避这个问题。详见
    # ``core/idempotency.py`` 的 ``idempotent`` docstring；
    # ``tests/unit/test_idempotency.py`` 守门。
    #     @router.post(...)
    #     @require_auth     # 任何业务 wrapper 在外层
    #     @idempotent       # 最内层，紧贴 ``async def``
    #     async def create_xxx(...): ...
    @router.post(
        "",
        operation_id="{plural}_create",
        response_model={Name}Read,
        status_code=status.HTTP_201_CREATED,
        responses=IDEMPOTENT_POST_ERROR_RESPONSES,
    )
    @idempotent
    async def create_{name}(payload: {Name}Create, svc: ServiceDep) -> {Name}Read:
        return await svc.create(payload)


    @router.patch(
        "/{{item_id}}",
        operation_id="{plural}_update",
        response_model={Name}Read,
        responses=PATCH_ERROR_RESPONSES,
    )
    async def update_{name}(
        item_id: int, payload: {Name}Update, svc: ServiceDep
    ) -> {Name}Read:
        return await svc.update(item_id, payload)


    @router.delete(
        "/{{item_id}}",
        operation_id="{plural}_delete",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=NOT_FOUND_RESPONSE,
    )
    async def delete_{name}(item_id: int, svc: ServiceDep) -> None:
        await svc.delete(item_id)
''')


TEMPLATE_DEPS_DB = dedent('''\
    """{Name} 组合根（Composition Root）。

    在此组装 {Name}Service 的具体依赖，使 api.py 只依赖 service、不直接
    import repository（分层契约：``*.api`` 禁 import ``*.repository``）。
    """

    from __future__ import annotations

    from typing import Annotated

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    from {service}.db.session import get_session
    from {service}.domains.{name}.repository import {Name}Repository
    from {service}.domains.{name}.service import {Name}Service


    async def get_{name}_service(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> {Name}Service:
        return {Name}Service({Name}Repository(session))
''')


TEMPLATE_DEPS_INMEM = dedent('''\
    """{Name} 组合根（Composition Root，内存版）。"""

    from __future__ import annotations

    from {service}.domains.{name}.repository import {Name}Repository
    from {service}.domains.{name}.service import {Name}Service


    async def get_{name}_service() -> {Name}Service:
        return {Name}Service({Name}Repository())
''')


TEMPLATE_MODELS = dedent('''\
    """{Name} ORM 映射 — 表 ``{plural}``。"""

    from __future__ import annotations

    from datetime import datetime

    from sqlalchemy import DateTime, func
    from sqlalchemy.orm import Mapped, mapped_column

    from {service}.db.base import Base


    class {Name}(Base):
        __tablename__ = "{plural}"

        # __table_args__ —— 在这里声明索引和约束，例如：
        #
        #     from sqlalchemy import Index, UniqueConstraint
        #     __table_args__ = (
        #         Index("ix_{plural}_name", "name"),
        #         UniqueConstraint("name", name="uq_{plural}_name"),
        #     )
        #
        # generator 默认不加额外索引。一旦你知道 query 模式就立刻加 ——
        # 事后补复合索引需要 Alembic migration + 在热表上做停机规划。
        __table_args__ = ()

        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column()
        gmt_create: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
        gmt_modified: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
        )
''')


TEMPLATE_TEST_SERVICE = dedent('''\
    """{Name}Service 单元测试 —— stub repository 覆盖 NOT_FOUND 分支。"""

    from __future__ import annotations

    from typing import Any

    import pytest

    from {service}.core.errors import AppError
    from {service}.domains.{name}.schemas import {Name}Create, {Name}Update
    from {service}.domains.{name}.service import {Name}Service


    class _StubRepo:
        def __init__(self) -> None:
            self.rows: dict[int, dict[str, Any]] = {{}}

        async def list_paginated(self, page: int, size: int) -> list[dict[str, Any]]:
            start = (page - 1) * size
            return list(self.rows.values())[start : start + size]

        async def count(self) -> int:
            return len(self.rows)

        async def get(self, item_id: int) -> dict[str, Any] | None:
            return self.rows.get(item_id)

        async def create(self, payload: {Name}Create) -> dict[str, Any]:
            next_id = max(self.rows, default=0) + 1
            row: dict[str, Any] = {{"id": next_id, **payload.model_dump()}}
            self.rows[next_id] = row
            return row

        async def update(self, item_id: int, payload: {Name}Update) -> dict[str, Any] | None:
            row = self.rows.get(item_id)
            if row is None:
                return None
            for key, value in payload.model_dump(exclude_unset=True).items():
                row[key] = value
            return row

        async def delete(self, item_id: int) -> bool:
            return self.rows.pop(item_id, None) is not None


    @pytest.mark.asyncio
    async def test_get_raises_when_missing() -> None:
        svc = {Name}Service(_StubRepo())  # type: ignore[arg-type]
        with pytest.raises(AppError) as exc:
            await svc.get(999)
        assert exc.value.code == "{service}.{NAME_UPPER}_NOT_FOUND"
        assert exc.value.status_code == 404


    @pytest.mark.asyncio
    async def test_create_returns_read_dto() -> None:
        svc = {Name}Service(_StubRepo())  # type: ignore[arg-type]
        out = await svc.create({Name}Create(name="x"))
        assert out.id == 1
        assert out.name == "x"


    @pytest.mark.asyncio
    async def test_delete_missing_raises() -> None:
        svc = {Name}Service(_StubRepo())  # type: ignore[arg-type]
        with pytest.raises(AppError) as exc:
            await svc.delete(999)
        assert exc.value.code == "{service}.{NAME_UPPER}_NOT_FOUND"


    @pytest.mark.asyncio
    async def test_list_returns_pagination_envelope() -> None:
        repo = _StubRepo()
        svc = {Name}Service(repo)  # type: ignore[arg-type]
        # seed 23 个，让 total_pages != size 边界。
        for i in range(23):
            await repo.create({Name}Create(name=f"item-{{i}}"))
        page = await svc.list_(page=2, size=10)
        assert page.page == 2
        assert page.size == 10
        assert page.total == 23
        assert page.total_pages == 3
        assert len(page.items) == 10
        assert page.items[0].id == 11


    @pytest.mark.asyncio
    async def test_list_empty_returns_zero_total_pages() -> None:
        svc = {Name}Service(_StubRepo())  # type: ignore[arg-type]
        page = await svc.list_(page=1, size=20)
        assert page.items == []
        assert page.total == 0
        assert page.total_pages == 0
''')


TEMPLATE_TEST_API_INMEM = dedent('''\
    """/api/v1/{plural} 的 API 测试 —— TestClient + 内存 repository。

    用模块默认的 ``_get_service``（不接 DB）。完整 CRUD happy path 在
    单测里跑；本文件覆盖 HTTP 边界（404 / 422）。

    本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception
    handler），错误响应里的 ``request_id`` 字段与线上服务一致 —— 让
    生成的 SDK 和消费方期望保持诚实。
    """

    from __future__ import annotations

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from {service}.core.errors import register_exception_handlers
    from {service}.core.middleware import RequestIDMiddleware
    from {service}.domains.{name}.api import router


    def _client() -> TestClient:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        register_exception_handlers(app)
        app.include_router(router)
        return TestClient(app)


    def test_get_returns_404_when_missing() -> None:
        body = _client().get("/api/v1/{plural}/999").json()
        assert body["type"] == "{service}.{NAME_UPPER}_NOT_FOUND"


    def test_create_returns_422_on_missing_field() -> None:
        res = _client().post("/api/v1/{plural}", json={{}})
        assert res.status_code == 422


    def test_list_returns_pagination_envelope_with_defaults() -> None:
        body = _client().get("/api/v1/{plural}").json()
        assert body == {{"items": [], "page": 1, "size": 20, "total": 0, "total_pages": 0}}


    def test_list_size_above_max_is_rejected() -> None:
        res = _client().get("/api/v1/{plural}?size=101")
        assert res.status_code == 422
''')


TEMPLATE_TEST_API_DB = dedent('''\
    """/api/v1/{plural} 的 API 测试 —— DB-backed 路由。

    这里只跑 validation (422)：它在 AsyncSession 依赖之前短路，无需真 DB。
    完整 CRUD happy / NOT_FOUND 路径放 ``tests/integration/`` 等表建好后再跑。

    本地 app 镜像生产 middleware 拓扑（RequestIDMiddleware + exception
    handler），错误响应里的 ``request_id`` 字段与线上服务一致。
    """

    from __future__ import annotations

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from {service}.core.errors import register_exception_handlers
    from {service}.core.middleware import RequestIDMiddleware
    from {service}.domains.{name}.api import router


    def _client() -> TestClient:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        register_exception_handlers(app)
        app.include_router(router)
        return TestClient(app)


    def test_create_returns_422_on_missing_field() -> None:
        res = _client().post("/api/v1/{plural}", json={{}})
        assert res.status_code == 422


    def test_update_returns_422_on_invalid_payload() -> None:
        res = _client().patch("/api/v1/{plural}/1", json={{"name": 123}})
        assert res.status_code == 422


    def test_list_size_above_max_is_rejected() -> None:
        res = _client().get("/api/v1/{plural}?size=101")
        assert res.status_code == 422
''')


# --------------------------------------------------------------------------- #
# 核心逻辑                                                                    #
# --------------------------------------------------------------------------- #


def _pascal_case(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_") if part)


def _validate_name(value: str, *, flag: str) -> str:
    if not NAME_REGEX.fullmatch(value):
        suggestion = ""
        # 常见情况：有人按 Java 肌肉记忆敲了 CamelCase（如 ``Order``）。
        # 转成 snake_case 再作为建议给出来，新人不必去读 regex 自己琢磨。
        if value and value[0].isalpha():
            snake = "".join(
                "_" + ch.lower() if ch.isupper() and i > 0 else ch.lower()
                for i, ch in enumerate(value)
            )
            if snake != value and NAME_REGEX.fullmatch(snake):
                suggestion = f" Try {flag}={snake!r}."
        _exit(
            2,
            f"{flag} must be lowercase snake_case (matches {NAME_REGEX.pattern}); "
            f"got {value!r}.{suggestion} "
            "The generator auto-converts to PascalCase for class names — "
            f"e.g. {flag}=order generates ``class Order``.",
        )
    if keyword.iskeyword(value) or value in RESERVED_NAMES:
        _exit(
            2,
            f"{flag}={value!r} is a Python keyword or one of the reserved package "
            f"names: {sorted(RESERVED_NAMES)}. Pick a domain-specific name (e.g. "
            f"'order_item' instead of 'models').",
        )
    return value


def _resolve_service_package(explicit: str | None) -> str:
    if explicit:
        return _validate_name(explicit, flag="--service-package")
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        _exit(1, f"pyproject.toml not found at {pyproject}; pass --service-package")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    packages = data.get("tool", {}).get("hatch", {}).get("build", {}).get("packages") or data.get(
        "tool", {}
    ).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {}).get("packages")
    if isinstance(packages, list) and packages:
        candidate = Path(str(packages[0])).name
        if NAME_REGEX.fullmatch(candidate):
            return candidate
    name = data.get("project", {}).get("name")
    if isinstance(name, str):
        candidate = name.replace("-", "_")
        if NAME_REGEX.fullmatch(candidate):
            return candidate
    _exit(1, "could not infer service package; pass --service-package explicitly")


def _build_context(args: argparse.Namespace) -> Context:
    name = _validate_name(args.name, flag="--name")
    plural = _validate_name(args.plural or f"{name}s", flag="--plural")
    if plural == name:
        _exit(2, "--plural must differ from --name")
    service = _resolve_service_package(args.service_package)
    return Context(
        service=service,
        name=name,
        name_pascal=_pascal_case(name),
        name_upper=name.upper(),
        plural=plural,
        plural_pascal=_pascal_case(plural),
        with_model=args.with_model,
    )


def _target_paths(ctx: Context) -> dict[Path, str]:
    domain_dir = REPO_ROOT / "src" / ctx.service / "domains" / ctx.name
    fmt = ctx.as_format_kwargs()
    files: dict[Path, str] = {
        domain_dir / "__init__.py": TEMPLATE_INIT.format(**fmt),
        domain_dir / "schemas.py": TEMPLATE_SCHEMAS.format(**fmt),
        domain_dir / "service.py": TEMPLATE_SERVICE.format(**fmt),
        REPO_ROOT / "tests" / "unit" / f"test_{ctx.name}_service.py": TEMPLATE_TEST_SERVICE.format(
            **fmt
        ),
    }
    if ctx.with_model:
        files[domain_dir / "models.py"] = TEMPLATE_MODELS.format(**fmt)
        files[domain_dir / "repository.py"] = TEMPLATE_REPOSITORY_DB.format(**fmt)
        files[domain_dir / "deps.py"] = TEMPLATE_DEPS_DB.format(**fmt)
        files[domain_dir / "api.py"] = TEMPLATE_API_DB.format(**fmt)
        files[REPO_ROOT / "tests" / "api" / f"test_{ctx.name}_api.py"] = (
            TEMPLATE_TEST_API_DB.format(**fmt)
        )
    else:
        files[domain_dir / "repository.py"] = TEMPLATE_REPOSITORY_INMEM.format(**fmt)
        files[domain_dir / "deps.py"] = TEMPLATE_DEPS_INMEM.format(**fmt)
        files[domain_dir / "api.py"] = TEMPLATE_API_INMEM.format(**fmt)
        files[REPO_ROOT / "tests" / "api" / f"test_{ctx.name}_api.py"] = (
            TEMPLATE_TEST_API_INMEM.format(**fmt)
        )

    # 确保 domains/__init__.py 存在；不存在就建一个空的（不覆盖既有的）。
    domains_init = REPO_ROOT / "src" / ctx.service / "domains" / "__init__.py"
    if not domains_init.exists():
        files[domains_init] = '"""本服务的业务 domain 包。"""\n'
    return files


def _check_conflicts(targets: dict[Path, str], *, force: bool) -> None:
    existing = [p for p in targets if p.exists()]
    if existing and not force:
        for path in existing:
            print(f"  conflict: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        _exit(1, f"{len(existing)} target file(s) already exist; pass --force to overwrite")


def _write_all(targets: dict[Path, str]) -> list[Path]:
    written: list[Path] = []
    try:
        for path, content in targets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
    except OSError as exc:
        for path in written:
            with contextlib.suppress(OSError):
                path.unlink()
        _exit(3, f"write failed: {exc}; rolled back {len(written)} file(s)")
    return written


_ALEMBIC_REGISTER_MARKER = "--- Register models here for autogenerate"


def _patch_alembic_env(ctx: Context) -> tuple[Path, bool]:
    """把 ORM model 的 import 插到 ``migrations/env.py`` 的 register block。

    v0.4.13：漏掉这步手工动作是"服务 ship 出去没建表"的主要陷阱 ——
    ``alembic check`` 静默通过（空 metadata vs 空 DB = 无 drift），
    ``make migration`` 生成空 revision，业务在生产环境才发现。generator
    在 ``--with-model`` 时自动 patch 这一步。

    幂等 —— 如果同样的 import 行已经在了就不写入。``migrations/env.py``
    缺失或 register block 被重度自定义（没找到 closing dashes 行）时，
    走 soft skip 并在 next-steps 打印，让用户手工补。

    返回 (env_path, was_changed)，让 CLI 报告 patch 情况。
    """
    env_path = REPO_ROOT / "migrations" / "env.py"
    if not env_path.is_file():
        return env_path, False

    import_line = (
        f"from {ctx.service}.domains.{ctx.name}.models import {ctx.name_pascal}  # noqa: F401"
    )
    text = env_path.read_text(encoding="utf-8")
    if import_line in text:
        return env_path, False

    lines = text.splitlines(keepends=True)
    marker_idx: int | None = None
    closing_idx: int | None = None
    for i, line in enumerate(lines):
        if marker_idx is None and _ALEMBIC_REGISTER_MARKER in line:
            marker_idx = i
            continue
        # closing 行是下一个 strip 后全是 '#' + 短横的注释行（example 之后的
        # 视觉分隔条）。
        if marker_idx is not None and line.lstrip().startswith("#"):
            stripped = line.strip().lstrip("#").strip()
            if stripped and set(stripped) <= {"-"}:
                closing_idx = i
                break
    if marker_idx is None or closing_idx is None:
        return env_path, False

    # v0.4.15：首次 patch 后面要留一行空行，让 ruff 的 isort 规则（I001）
    # 把 patched ``from ... import ...`` 当作 import group 的结尾。否则 closing
    # 短横注释会被当作还在 import block 内，``make new-module ... with-model=1``
    # 之后立刻 ``make check`` fail。
    #
    # v0.5.0：但**后续**的 patch 不能再插空行 —— ``smoke-generator``（在已经
    # patch 过一个真 domain 之后跑）抓到回归：两个 patched import 之间被空行 +
    # 短横注释隔开，import block 不连续，ruff I001 fire。修复：检测「register
    # block 内最后一个非空行已经是 patched import」时直接追加，不加额外空行。
    last_content_idx = closing_idx - 1
    while last_content_idx > marker_idx and lines[last_content_idx].strip() == "":
        last_content_idx -= 1
    is_appending_to_prior_patch = (
        last_content_idx > marker_idx
        and lines[last_content_idx].lstrip().startswith("from ")
        and "noqa: F401" in lines[last_content_idx]
    )
    if is_appending_to_prior_patch:
        lines.insert(last_content_idx + 1, import_line + "\n")
    else:
        lines.insert(closing_idx, import_line + "\n\n")
    env_path.write_text("".join(lines), encoding="utf-8")
    return env_path, True


def _print_next_steps(ctx: Context, written: list[Path], env_patched: bool) -> None:
    print(f"\nGenerated {len(written)} file(s):")
    for path in written:
        print(f"  + {path.relative_to(REPO_ROOT)}")
    print("\nNext steps:")
    print(f"  1. Register the router in src/{ctx.service}/main.py create_app():")
    print(f"       from {ctx.service}.domains.{ctx.name}.api import router as {ctx.name}_router")
    print(f"       app.include_router({ctx.name}_router)")
    if ctx.with_model:
        if env_patched:
            print(
                "\n  2. (auto) Patched migrations/env.py to register the new model — "
                "verify the diff before committing."
            )
        else:
            print(
                "\n  2. Could not auto-patch migrations/env.py "
                "(missing or heavily customised). Add manually:"
            )
            print(
                f"       from {ctx.service}.domains.{ctx.name}.models "
                f"import {ctx.name_pascal}  # noqa: F401"
            )
        print(
            f"\n  3. Create a migration: uv run alembic revision --autogenerate -m 'add {ctx.plural} table'"
        )
        print("     Review the generated file, then: uv run alembic upgrade head")
    print("\n  Finally: make check")


def _exit(code: int, message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="new_module",
        description="Generate a business-domain module (schemas/service/repository/api[+models]+tests).",
    )
    parser.add_argument(
        "--name", required=True, help="Module name (snake_case singular), e.g. order"
    )
    parser.add_argument(
        "--plural", default=None, help="Plural form for URL/table (default: <name>+s)"
    )
    parser.add_argument(
        "--with-model", action="store_true", help="Generate ORM model + DB-backed repository"
    )
    parser.add_argument(
        "--service-package",
        default=None,
        help="Service package (default: inferred from pyproject.toml)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print target files without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ctx = _build_context(args)
    targets = _target_paths(ctx)

    if args.dry_run:
        print(f"Would generate {len(targets)} file(s):")
        for path in targets:
            print(f"  + {path.relative_to(REPO_ROOT)}")
        return 0

    _check_conflicts(targets, force=args.force)
    written = _write_all(targets)
    env_patched = False
    if ctx.with_model:
        _env_path, env_patched = _patch_alembic_env(ctx)
    _print_next_steps(ctx, written, env_patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
