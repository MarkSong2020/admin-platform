# Generator: `scripts/new_module.py`

> 业务域模块生成器。给定一个 domain 名（如 `order`），按 [LAYERED_DESIGN.md](../architecture/LAYERED_DESIGN.md) 5 层契约 + ADR 0001 §7.5 分页 envelope，**一次产出**直接通过 `make check` 的最小桩模块。

## 速查

```bash
make new-module name=order                    # 最小模块（内存仓储桩）
make new-module name=product with-model=1     # 含 ORM model + 真 DB repository
make new-module name=category plural=categories with-model=1   # 不规则复数
make new-module name=order dry-run=1          # 干跑预览
make new-module name=order force=1            # 覆盖已存在文件

# 也可直接调脚本：
uv run python scripts/new_module.py --name order --with-model
```

## 生成的文件清单

### 最小模式（无 `--with-model`）

```
src/<service>/domains/order/
├── __init__.py
├── schemas.py        # OrderBase / OrderCreate / OrderUpdate / OrderRead / OrderPage
├── repository.py     # InMemory: list_paginated / count / get / create / update / delete
├── service.py        # OrderService: list_(page=, size=) → OrderPage / get/create/update/delete
└── api.py            # /api/v1/orders 五端点 + PageQ/SizeQ Annotated 参数

tests/unit/test_order_service.py    # 5 项守门
tests/api/test_order_api.py         # 4 项守门
```

### 含 `--with-model`

在最小模式基础上追加：

```
src/<service>/domains/order/
└── models.py         # SQLAlchemy 2.x: id (PK) / name / gmt_create / gmt_modified
```

`repository.py` 切到 DB 模式：用 `AsyncSession` + `select().offset().limit().order_by(id)` 实现 `list_paginated`，用 `select(func.count())` 实现 `count`。

`api.py` 的 DI 改为 `Annotated[AsyncSession, Depends(get_session)]`。

## 模板要点（与 v0.5.2 实际生成器对齐）

> **v0.5.2 起生成代码 docstring 是简体中文**（AI_CODING_RULES.md §0）。所有 `TEMPLATE_*` 字符串内的 docstring + 注释 + `_patch_alembic_env` 等核心函数 docstring 已翻译；保留代码 identifier / 错误码字面量 / CLI argparse help 英文。业务团队从 v0.5.2 起 `make new-module` 出来的 domain 代码 docstring **直接中文**，无需手工补翻。


### `schemas.py`

```python
class OrderBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str

class OrderCreate(OrderBase): pass

class OrderUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str | None = None

class OrderRead(OrderBase):
    id: int

class OrderPage(BaseModel):                # ADR §7.5 强制
    model_config = ConfigDict(from_attributes=True)
    items: list[OrderRead]
    page: int
    size: int
    total: int
    total_pages: int
```

### `service.py`（含 list_ 分页签名）

```python
class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int) -> OrderPage:
        rows = await self._repo.list_paginated(page, size)
        total = await self._repo.count()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return OrderPage(
            items=[OrderRead.model_validate(r) for r in rows],
            page=page, size=size, total=total, total_pages=total_pages,
        )

    async def get(self, item_id: int) -> OrderRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise AppError(
                code="service_name.ORDER_NOT_FOUND",  # ADR §3 — 替换 service_name 为实际服务前缀
                title="Order not found",
                status_code=404,
            )
        return OrderRead.model_validate(row)

    # create / update / delete 类似
```

### `api.py`（含 PageQ/SizeQ Annotated）

```python
from typing import Annotated
from fastapi import APIRouter, Depends, Query, status

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

ServiceDep = Annotated[OrderService, Depends(_get_service)]
PageQ = Annotated[int, Query(ge=1, description="Page number (1-indexed)")]
SizeQ = Annotated[int, Query(ge=1, le=100, description="Items per page (max 100)")]

@router.get("", operation_id="orders_list", response_model=OrderPage)
async def list_orders(svc: ServiceDep, page: PageQ = 1, size: SizeQ = 20) -> OrderPage:
    return await svc.list_(page=page, size=size)

IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ProblemDetail},  # framework.IDEMPOTENCY_KEY_INVALID
    409: {"model": ProblemDetail},  # framework.IDEMPOTENT_RETRY_IN_FLIGHT
    422: {"model": ProblemDetail},  # framework.IDEMPOTENCY_KEY_REUSED
}
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}

@router.post(
    "",
    operation_id="orders_create",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_order(payload: OrderCreate, svc: ServiceDep) -> OrderRead:
    return await svc.create(payload)

@router.patch(
    "/{item_id}",
    operation_id="orders_update",
    response_model=OrderRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_order(item_id: int, payload: OrderUpdate, svc: ServiceDep) -> OrderRead:
    return await svc.update(item_id, payload)

# get/delete 类似（用 NOT_FOUND_RESPONSE）
```

> **POST 默认 `@idempotent`**（v0.4.6 起）：POST 端点（如 `create_{name}`）模板自动套 `@idempotent` 装饰器 + `from service_name.core.idempotency import idempotent` 导入。如该端点天然幂等（如 content-addressed upload）显式删除装饰器并在 commit message 注明原因。
>
> **`IDEMPOTENT_POST_ERROR_RESPONSES`**（v0.4.16 起）：POST 显式声明 400 / 409 / 422 三条 middleware 拦截路径，让 SDK 生成器看到完整错误集合。FastAPI 不知道 middleware 拒绝的请求；不显式声明 SDK 只能 catch 通用 Error。
>
> **`PATCH_ERROR_RESPONSES`**（v0.4.16 起）：PATCH 显式声明 404 + 422。`_custom_openapi` 把这两个 status 的 schema rewrite 成 ProblemDetail（ADR §1）。
>
> GET / DELETE 仍用 `NOT_FOUND_RESPONSE`（只声明 404）。

### `models.py`（仅 `--with-model`）

```python
class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    gmt_create: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    gmt_modified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),                # ORM-level，session.commit() 时触发；不映射到 DDL
    )
```

## 测试模板（自动产出）

`tests/unit/test_<name>_service.py` 5 项：
- `test_get_raises_when_missing` — service 抛 `service_name.{NAME_UPPER}_NOT_FOUND`
- `test_create_returns_read_dto`
- `test_delete_missing_raises`
- `test_list_returns_pagination_envelope` — seed 23 项 + page=2/size=10 → total_pages=3
- `test_list_empty_returns_zero_total_pages`

`tests/api/test_<name>_api.py` 4 项（含 model 模式 3 项）：
- `test_get_returns_404_when_missing`（无 model 模式）
- `test_create_returns_422_on_missing_field`
- `test_list_returns_pagination_envelope_with_defaults`
- `test_list_size_above_max_is_rejected`（Query le=100 守门）

## Next steps（每次生成后必须做）

Generator 末尾打印：

1. **注册路由** 到 `main.py`：
   ```python
   from service_name.domains.order.api import router as order_router
   app.include_router(order_router)
   ```
2. **（仅 `--with-model`）建迁移**：
   `uv run alembic revision --autogenerate -m 'add orders table'` + 人工 review + `uv run alembic upgrade head`
   > generator 已**自动 patch** `migrations/env.py` 加 `from service_name.domains.order.models import Order  # noqa: F401`（v0.4.13 起）；忘加这一行会让 `alembic check` 静默通过、autogenerate 出空 revision，曾是常踩的坑。
3. **（可选）天然幂等 / content-addressed 的 POST** → 显式**移除** `@idempotent` 装饰器并在 commit message 注明原因（v0.4.6 起 generator 默认套，符合 ADR §11；见 [AI_CODING_RULES.md](./AI_CODING_RULES.md) §2）
4. **跑** `make check`（首次改 generator 模板时再跑一次 `make smoke-generator` 验证模板"开箱即过 check"）

## 设计要点

- **零额外依赖**：argparse + pathlib + tomllib + str.format。不引入 cookiecutter / jinja2
- **模板嵌入脚本**：每个 TEMPLATE_* 常量字符串都在 `scripts/new_module.py` 模块顶层，可一眼看明白生成出什么
- **占位变量**：`service / name / Name / NAME_UPPER / plural / Plural` 6 个，通过 `Context.as_format_kwargs()` 提供
- **事务性写盘**：任一文件写失败 → `contextlib.suppress(OSError)` 删已写文件 → 退出码 3

## CLI 参数

| flag | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--name` | ✅ | — | 模块名 snake_case 单数 |
| `--plural` | — | `<name>s` | URL / 表名复数；不规则手传 |
| `--with-model` | — | false | 加 `models.py` + DB-backed repository |
| `--service-package` | — | 推断自 pyproject.toml `[tool.hatch.build.targets.wheel].packages` | service 包名（错误码前缀来源） |
| `--dry-run` | — | false | 只打印将创建的文件 |
| `--force` | — | false | 覆盖已存在文件 |

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（或 dry-run 成功） |
| 1 | 业务冲突（文件已存在、未传 `--with-model` 却调 migration 等） |
| 2 | 参数非法（name 不匹配 regex / 保留字 / 同 plural） |
| 3 | I/O 失败（已回滚） |

## 生成器自身的测试

`tests/unit/test_new_module.py` 31 项守门（v0.5.0 +1 multi-patch I001 regression guard）：
- pure helpers（pascal_case / validate_name）
- service package resolution（hatch packages / project name / 显式 --service-package）
- dry-run（无 model / 含 model）
- 真生成 + 占位替换正确
- `--with-model` 生成 ORM + DB repository
- `--plural` 覆盖默认
- 冲突 / `--force` / OSError 回滚

## 设计源头

历史 design rationale + 替代方案讨论 → 见 [`../archive/EVOLUTION.md`](../archive/EVOLUTION.md) 起源段。**本文件**是当前 v0.5.2 真相源。

## 不在 generator 范围（留给用户）

- 注册路由到 `main.py`（防止 git 冲突）
- 写 Alembic migration 文件（用 `alembic revision --autogenerate`）
- 配置 `Settings.service_id`（手动；rename 阶段一并替换）

> v0.4.13 起 ORM 注册到 `migrations/env.py` 已**自动 patch**（idempotent，幂等可重复跑）；本节移除"留给用户"那一行避免误导。
