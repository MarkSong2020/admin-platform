# 分层设计：5 层 + tests

> 业务模块默认 5 层。各层职责严格分离，**违反层级边界是 hard rule**。
> **结构边界**（import 方向、api↛repository、schemas↛models、service/repository↛fastapi、models↛pydantic）由 `make check` 的 **import-linter 机检**（契约 C1–C10，见 `.importlinter`）——直接跨层 import 会让 CI 红。
> **语义边界**（api 不写业务逻辑、repository 不抛业务异常等无法静态投影的约定）仍由 **code review** 兜。
> DI 组合根（装配 service + repository）在 `domains/<x>/deps.py`，不在 `api.py`（这样 api 不直接 import repository，满足 C2）。
> **C1–C10 全部生效**（`make check` 10 contracts kept）：`user` 域已完整五层、纳入 C1 `containers`；`auth` 仅 service/schemas（router 在 `api/v1/auth.py` 顶层）暂不纳入 C1，待长出三层再加；`tenant` 域已随单租户回归（2026-06-05）删除。C2–C7 用 wildcard 覆盖全部域；C8 守 `authz` 纯基座（不 import domains / core，避免循环依赖）；C9 守 `api/v1` 聚合层不直接 import domains repository；C10 守 `excel` 叶子机制不 import fastapi / sqlalchemy / domains / core。

## 一图看懂

```
HTTP request
     │
     ▼
┌─────────────────────────────────────┐
│  api.py        路由 + 入参 + 状态码  │  ← 只做这些；禁止业务判断
├─────────────────────────────────────┤
│  service.py    业务用例 + 事务边界   │  ← AppError 在这里抛；禁止 fastapi.Request
├─────────────────────────────────────┤
│  repository.py 数据访问              │  ← SQL 在这里；禁止抛业务异常
├─────────────────────────────────────┤
│  schemas.py    Pydantic DTO         │  ← 纯数据契约
│  models.py     SQLAlchemy ORM       │  ← 仅 --with-model 时存在
└─────────────────────────────────────┘
```

## 各层职责 + 禁止项

| 层 | 必做 | 禁止 |
|---|---|---|
| `api.py` | 解 HTTP 参数 / 调 service / 返 model；声明 `operation_id` `response_model` `status_code` | 业务判断（if status == ...）；直接 import models / repository；返回 ORM 对象 |
| `service.py` | 业务规则、状态机、跨域调用、**逻辑事务责任**（决定何时抛 AppError 触发回滚 / 何时 `session.begin_nested()` 起 savepoint）、抛 `AppError(code=..., title=...)` | 引入 `fastapi.Request` / `fastapi.Response`；抛 `HTTPException`；写 SQL；显式 commit/rollback（dep 自动管） |
| `repository.py` | `select().where()` / `session.add` / `session.flush`；返 `None` 或 `False` 表示未找到 | 抛 `HTTPException` 或 `AppError`（让 service 翻译）；显式 commit/rollback |
| `schemas.py` | Pydantic v2 `BaseModel` + `ConfigDict(from_attributes=True)` | 引用 `models.py`；混入 SQLAlchemy session |
| `models.py` | SQLAlchemy 2.x typed mapping（`Mapped[T]` + `mapped_column`） | `to_dict()` / `__json__()`（序列化是 schemas 的事） |

### 事务边界（v0.4.11+）

**物理边界**：`db/session.py` `get_session` dep 用 `async with session.begin():` 包裹整个 request——handler 正常返回 → COMMIT；handler 抛任何异常（`AppError` / `HTTPException` / 未捕获）→ ROLLBACK。**一 endpoint = 一 transaction** 是 default。

**逻辑边界**：service 决定何时抛 `AppError`（触发整个 request 回滚），需要 saga / 部分提交时显式 `session.begin_nested()` 起 SAVEPOINT（不影响外层 request transaction）。

**严格 at-most-once（金额扣减 / 订单创建）**：Idempotency middleware 写 cache 在 commit **之前**，存在 race window（cache 标 completed 但 commit 失败 → 业务以为成功）。强保证要求 service 层加 DB-level idempotency table，与业务表同事务原子写——见 [REQUEST_LIFECYCLE.md](./REQUEST_LIFECYCLE.md) "强 at-most-once 边界" 段。

## DTO 三件套约定

每个业务域必有：

```python
class {Name}Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    # 共享字段...

class {Name}Create({Name}Base):
    pass                               # 创建时用

class {Name}Update(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    # 字段都改为 Optional

class {Name}Read({Name}Base):
    id: int                            # 含 PK

class {Name}Page(BaseModel):           # 分页 envelope（ADR §7.5 强制）
    items: list[{Name}Read]
    page: int
    size: int
    total: int
    total_pages: int
```

Generator 自动产出上述结构，详见 [../standards/CODE_GENERATOR.md](../standards/CODE_GENERATOR.md)。

## 异常约定

业务异常一律 `core.errors.AppError(code, title, *, detail=None, status_code=400, errors=None)`，**不要**`raise HTTPException`。

```python
# ✅ 正确
raise AppError(
    code="payment.ORDER_NOT_FOUND",      # ADR §3 {service}.{ERROR_CODE}
    title="Order not found",              # short type-level summary, no id
    detail=f"Order id={order_id} not found in tenant={tenant_id}",  # may contain ids
    status_code=404,
)

# ❌ 错误
raise HTTPException(status_code=404, detail="Order not found")
```

全局 handler 把 `AppError` 翻译成 ADR §1 ProblemDetail 8 字段响应：

| `AppError` 参数 | 响应字段 | 备注 |
|---|---|---|
| `code` | `type` | 错误类型 identifier |
| `title` | `title` | i18n key 候选 |
| `detail` | `detail` | 实例描述（含 id 上下文）|
| `status_code` | `status` | HTTP 状态码冗余 |
| `errors` | `errors` | 字段级结构化补充 |
| —（middleware 注入） | `request_id` / `trace_id` | 见 [OBSERVABILITY.md](./OBSERVABILITY.md) |
| —（baseline 固定 null） | `instance` | 未来扩展为 URI |

完整 ProblemDetail 字段语义见 [ERROR_RESPONSE.md](./ERROR_RESPONSE.md)。

## 文件命名 + 目录结构

```
src/<service>/domains/<name>/
├── __init__.py
├── schemas.py          # 必有
├── repository.py       # 必有（即使是 InMemory 桩）
├── service.py          # 必有
├── api.py              # 必有
└── models.py           # 仅 --with-model 时

tests/unit/test_<name>_service.py    # service 单测（mock repo）
tests/api/test_<name>_api.py         # API 测试（TestClient 422 等）
tests/integration/test_<name>_*.py   # 真 DB 集成测试（用户自加，按需）
```

`<name>` 始终 **snake_case 单数**（`order`、`user_profile`）；复数自动推断（`orders`），不规则用 `--plural` 显式传。

## 为什么是 5 层 / 为何要严格

**多服务一致性**：5 个服务都按这个结构 → review / 调试 / 新人 onboarding 一致；不需要每个服务问"这逻辑在哪个文件"。

**测试金字塔**：

| 测试类型 | 用 | 不用 |
|---|---|---|
| unit | mock repo，专测 service 业务规则 | 起 FastAPI app |
| api | TestClient，专测 HTTP 边界（422 / 404） | 起 DB |
| integration | testcontainers / compose，专测真事务 | mock |

3 种测试**互不重复**——每种只测一层关注点。

## 相关文档

- 错误响应详细字段 → [ERROR_RESPONSE.md](./ERROR_RESPONSE.md)
- 请求 middleware 链 → [REQUEST_LIFECYCLE.md](./REQUEST_LIFECYCLE.md)
- 命名约定速查 → [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md)
- 生成器使用 → [../standards/CODE_GENERATOR.md](../standards/CODE_GENERATOR.md)
