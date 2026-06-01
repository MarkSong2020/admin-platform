# Example Domain — `todo` 与 `tag`

> **本文是什么**：教科书蓝本式的业务 domain。新人 `make init` 跑通后第一份
> 应该读的文档；任何 AI agent 在新建 domain 之前都应该 grep 本文。
>
> **本文不是什么**：生产级 todo 软件。业务规则**刻意做得最小** —— title
> 唯一、三态 enum、可选 due date —— 让重点保持在*分层、错误响应、幂等、
> 事务、迁移、测试*，而不是 todo 业务特有的边界。

## 为什么需要

v0.5.0 之前模板只 ship 了 `core/` + 测试 + 文档，`domains/` 是空的。新人
和 AI agent 没有"一个完成模块在本仓长什么样"的正面例子 —— 只有
`AI_CODING_RULES.md` 里的抽象规则。结果是：

- AI 生成的代码违反分层（service 抛 `HTTPException`、api 里含业务逻辑）
- 错误码命名不一致
- 漏写 `responses=` 声明 → SDK 生成器吐出无类型错误
- POST 漏写 `@idempotent` → 重试时双扣风险

`todo` domain 就是参考答案。v0.5.1 加入第二个 domain `tag` + 多对多关联，
覆盖业务团队真正第一个 PR 经常碰到的「跨 domain 关联模式」。

## 5 分钟速览

```
src/service_name/domains/todo/
├── __init__.py          仅 docstring 标记
├── models.py            SQLAlchemy ORM — 表形状、约束、索引
├── schemas.py           Pydantic DTO — 线上形状、校验、默认值
├── repository.py        SQL —— 不抛业务异常
├── service.py           业务规则 —— 持有 AppError raise
└── api.py               HTTP —— 仅路由，无业务逻辑

src/service_name/domains/tag/      # v0.5.1 加入
├── __init__.py
├── models.py            name UniqueConstraint
├── schemas.py
├── repository.py        + get_many_by_ids 供 todo 批量取
├── service.py
└── api.py
```

测试：
```
tests/unit/test_todo_service.py        通过 stub repo 守业务规则
tests/api/test_todo_api.py             校验 422 路径（无需 DB）
tests/integration/test_todo_db.py      真 Postgres 端到端 + N+1 守门
tests/unit/test_tag_service.py
tests/api/test_tag_api.py
tests/integration/test_tag_db.py
```

迁移：
```
migrations/versions/0002_create_todo.py            手写示例
migrations/versions/0003_create_tag_and_todo_tags.py
```

## 逐层注解

### `models.py` — ORM

- **`UniqueConstraint("title")`** — DB 层不变式，**仅作兜底**。service
  层的预检（见下文）才是主要机制；约束防的是竞态和直写 DB 的场景。
- **`Enum(TodoStatus, native_enum=True)`** — Postgres native ENUM，不是
  自由字符串。写入时就抓 typo，`\d todos` 输出可读。
- **`due_at: Mapped[datetime | None]`** — 显式 Optional 映射，演示如何
  无歧义地声明 nullable 列。
- **`gmt_create` / `gmt_modified`** — 命名遵循
  [阿里巴巴 Java 开发手册](https://github.com/alibaba/p3c)，跨栈对齐
  （同组织内 Java 服务用同样的命名）。
- **`tags: Mapped[list[Tag]] = relationship(secondary=todo_tags, lazy="raise")`**
  — v0.5.1 加的多对多。`lazy="raise"` 是项目级 N+1 防御策略（详见
  「多 domain 关联模式」段）。

### `schemas.py` — DTO

- **三种 DTO**（`Create`、`Update`、`Read`）—— 每个操作字段不同。
  `Create` 不能设 `status`（服务端默认）；`Update` 把每个字段都设可选
  （RFC 7396 merge 语义）；`Read` 暴露完整形状。
- **`Field(min_length=1, max_length=200)`** —— 校验在 schema 层，
  service 永远不会看到非法字符串。422 错误在 service 跑前由 FastAPI 发出。
- **`TodoPage`** —— ADR 0001 §7.5 分页 envelope。本仓所有 list endpoint
  都遵循此形状；新人可以逐字拷贝。

### `repository.py` — 数据访问

- **不抛业务异常**。返回 `Todo | None` / `list[Todo]` / `bool`。契约是
  "执行 SQL，把结果原样返回"。
- **`find_by_title`** 是 domain 专属的查找方法，存在的原因是 service
  做唯一性预检需要它。Repository 的方法是按需加，不是预测性加。
- **`flush()`（不是 `commit()`）** —— 事务由 `get_session` 持有。
  repository 的写在同一请求的后续读里可见，不会提前 close 事务。

### `service.py` — 业务规则

- **持有本 domain 的所有 `AppError` raise**。判断标准：如果是"todo 的工作
  规则"就放这里。例如：
  - get / update / delete 缺 id ⇒ `TODO_NOT_FOUND`
  - create / update 用已存在 title ⇒ `TODO_TITLE_DUPLICATE`
  - tag_ids 含不存在 id ⇒ `TODO_TAG_NOT_FOUND`（v0.5.1）
- **insert 前唯一性预检**（`find_by_title` before `create`）—— 保持错误码
  整洁。没有预检的话，调用方会拿到一个 500（泄露 `IntegrityError`）。
  DB `UniqueConstraint` 仍在那里作为竞态兜底。
- **不 import `fastapi`** —— service 与框架无关。可以用 stub repo 跑单测
  （不需 FastAPI app）、可以被 background worker / CLI / batch job 复用
  而不必改写。

### `api.py` — HTTP

- **仅路由，无业务逻辑**。每个 handler 都是一行委托给 service。忍住
  "顺手加个小校验"的冲动 —— 校验属于 schema，业务属于 service。
- **`responses=` 完备**。调用方能命中的每条错误路径都声明，让 SDK 生成器
  emit 类型化错误类：
  - `404 TODO_NOT_FOUND`（get/update/delete）
  - `409 TODO_TITLE_DUPLICATE`（create/update —— 本 domain 自己的 409）
  - `422 VALIDATION_FAILED`（框架级）
  - `422 TODO_TAG_NOT_FOUND`（v0.5.1，tag 关联失败）
  - `400/409/422 framework.IDEMPOTENCY_*`（middleware 层在 POST 上的拒绝）
- **`@idempotent` 放最内层**（紧贴 `async def`）。装饰器顺序要紧 —— 在
  `@router.post` 下面如果有不带 `functools.wraps` 的 wrapper，会丢掉
  `_idempotent` 标记，悄悄关闭去重。放在最底层从根上回避这个问题。

## 多 domain 关联模式（v0.5.1 — todo ↔ tag）

真实服务很少只有一个孤立 domain。`tag` domain 与 `todo` 一起 ship 作为
**跨 domain 关联的教科书示例**。下面三个 SA 模式都演示了；你写自己的关系
时直接拷过来。

### 1. 纯关联表（Core `Table`，不是 ORM 类）

```python
# src/service_name/domains/todo/models.py
todo_tags = Table(
    "todo_tags",
    Base.metadata,
    Column("todo_id", Integer, ForeignKey("todos.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)
```

- **两个 FK 上的复合 PK** —— 自带去重、不要管 surrogate id
- **`ondelete="CASCADE"`** —— 任一边删除自动清理关联行
- **Core `Table`，不是 ORM 类** —— 关联边本身没有业务行为。如果以后要
  加元数据字段（`added_at` / `added_by_user_id`），切换到 **Association
  Object 模式**（ORM 映射的类）

### 2. `lazy="raise"` + `selectinload`（N+1 防御）

```python
class Todo(Base):
    tags: Mapped[list[Tag]] = relationship(Tag, secondary=todo_tags, lazy="raise")
```

`lazy="raise"` 是项目级默认策略（见 `db/base.py`）。访问 `todo.tags`
之前没 eager-load 会抛 `StatementError`，而不是按行 SELECT。

repository 所有读路径都自动预加载：

```python
async def list_paginated(self, page, size):
    stmt = (
        select(Todo)
        .options(selectinload(Todo.tags))  # <-- 这一行才是关键
        .offset(...).limit(...).order_by(Todo.id)
    )
```

`selectinload` 发出一条额外的 `SELECT ... FROM tags WHERE id IN (...)`，
一次把所有行的 tag 集合 hydrate 完，与 N 无关。

### 3. 跨 domain 持有 repository（不是 service-to-service）

```python
# todo/service.py
class TodoService:
    def __init__(self, repository: TodoRepository, tag_repository: TagRepository):
        self._repo = repository
        self._tag_repo = tag_repository
```

`TodoService` 持有 `TagRepository`（数据形状关切），**不是**
`TagService`（业务规则关切）。service 不调用其它 service —— 这样依赖
方向无环，"事务由 `get_session` 拥有" 的承诺才真的成立：两个 repo 通过
同一个 `AsyncSession` 写入，任何失败都让整个请求事务回滚。

### 4. all-or-nothing 引用检查（TODO_TAG_NOT_FOUND 422）

分配 tag 之前，service 用一次 `tag_repo.get_many_by_ids(...)` 解析所有
id。**部分缺失 ⇒ 422**，`detail` 里列出缺失的 id。为什么走 all-or-nothing：

- "悄悄关联存在子集"是**有损操作** —— 调用方传 3 个 tag、收到 2 个，
  响应里没有任何字段说丢了哪一个
- 类型化 422 让契约显式；SDK 生成器吐出一个 TodoTagNotFound 错误类，
  消费方可以 catch

### 5. N+1 守门测试（不要只信 lazy="raise"）

`tests/integration/test_todo_db.py::test_list_todos_with_tags_does_not_trigger_n_plus_1`
钩进 SQLAlchemy `before_execute` 数 SELECT。10 个带 tag 的 todo ⇒ ≤ 8
个 SELECT（count + page + tags + 多对多 + 驱动 bookkeeping）。超过即
N+1 回归。

`lazy="raise"` 在 N+1 发生时会**直接 crash**而不是 slow-burn —— 本测试
存在的意义是抓另一种场景：有人绕过 repository（比如 service 自己写
query）然后给**错误的 query path** 加 selectinload。

### 不该用本模式的场景

- **每行 > 50 个关联的热表**：通过 secondary table 的多对多最多扩展到
  每父行几百关联。换成去规范化的 JSON 列或专用子查询
- **跨服务边界**（微服务 A 引用服务 B 的 domain）：永远不要跨服务用 SA
  relationship，换成 `*_id` 引用列 + 显式 fetch B 的 API

---

## 想加一个新 domain 时拷什么

```bash
make new-module name=ledger with-model=1
```

会按 `todo` 模式生成骨架（不带 title 唯一性规则 —— 那是 per-domain
定制）。对照 `todo/` 看 diff，决定保留 vs 特化：

- **永远特化**：model 字段、schema 校验、service 业务规则、migration
- **通常保持原样**：api `responses=` 声明、`@idempotent` 顺序、repository
  契约（不抛业务异常）、测试结构（unit + api + integration）

## 关于 KNOWN_DEVIATIONS

`todo` domain 故意命中 `doc/tech-debt/KNOWN_DEVIATIONS.md` 里追踪的
每条偏差路径：

- `#11` IdempotencyMiddleware O(N) 路由遍历 —— POST `/api/v1/todos`
  每次都走一遍
- `#12` cache-before-commit race —— `create_todo` 在请求事务里 commit，
  middleware 在那之前就写 cache
- `#14` 多值响应头 —— 错误响应同时设 `Content-Type` + `X-Request-ID`

当那些偏差被修（或范围变化），`todo` domain 是第一个验证「修复没回归
生产路径」的测试面。
