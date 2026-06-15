# 已知偏差（Known Deviations）

> 现状 vs 应然 的差距清单。每项含**证据 file:line** + **修复路径**。**修一个划一个**——不要让此表无限膨胀。

## 评级

- **P0**：阻塞 ADR 强制约定 / 调用方对接 / 安全
- **P1**：影响 API 行为或 DX
- **P2**：优化项

## v0.5.0 post-release reality check（2026-05-18）

剩余 #7 / #11 / #12 / #13 / #14 在 v0.5.0 落地后被集体复审：每条 deviation 自己就明确**「触发条件未到不修」**（每个都有「自动升 P1 信号」表，信号未触发就不该重写）。

原计划 v0.5.1 重写 `BaseHTTPMiddleware` 关闭 #11/#12/#13 —— **撤回**。提前主动重写 = 完美主义陷阱（引入 middleware 重写高风险，来修测量上不存在的问题）。

**当前策略**：按各自定义的「触发条件 / 自动升 P1 信号」**被动等待**触发后再处理；不主动追求「关闭所有 deviation」。

完整决议见 [`CHANGELOG.md`](../../CHANGELOG.md) v0.5.0 章节末「reality check」段。

---

## ~~#1~~ — ~~Generator POST 端点缺 `@idempotent` 默认~~（✅ 已修，v0.4.6）

✅ **v0.4.6 已修**：`scripts/new_module.py` 两个 API 模板（TEMPLATE_API_INMEM / TEMPLATE_API_DB）`create_{name}` handler 现在默认带 `@idempotent` 装饰器 + 注释明示 "ADR §11: POST is idempotent by default" + opt-out 说明。从模板生成的服务现在自动满足 ADR §11 强制金额扣减 / 订单创建幂等的要求。

---

## ~~#2~~ — ~~`Settings.service_id` 字段未实现~~（✅ 已修，v0.4.6）

✅ **v0.4.6 已修**：`core/config.py` 加 `service_id: str = "service_name"` 字段（含 docstring 关联 ADR §3 / §5 / §8 / §10 多上下文同源 + service-prefix-registry 引用）；`tests/unit/test_config.py` 加 2 项守门（默认值 + `APP_SERVICE_ID` env 覆盖）；`docs/operations/LOCAL_SETUP.md` 加 sed rename 后该字段自动 cover 的说明 + 注册前缀流程链接。

---

## ~~#3~~ — ~~Generated 4xx routes OpenAPI 没声明~~（✅ 已修，v0.4.6）

✅ **v0.4.6 已修**：generator 两个 API 模板里 GET `/{item_id}` / PATCH `/{item_id}` / DELETE `/{item_id}` 都加了 `responses=NOT_FOUND_RESPONSE`（指向 `ProblemDetail` model）。SDK 自动生成现在能拿到正确的 404 错误类型。

---

## ~~#4~~ — ~~`test_access_log_contains_request_id_and_fields` 没断言 `trace_id` 字段~~（✅ 已修，v0.4.7）

✅ **v0.4.7 已修**：`tests/api/test_access_log.py` 在该测试中加 `assert "trace_id" in vars(record)` + `assert vars(record)["trace_id"] is None`，把"无 traceparent 路径下 trace_id 必为 None"作为 mutation 守门。

---

## ~~#5~~ — ~~Lifespan 不主动连 Redis/DB~~（✅ 已修，v0.4.7，opt-in）

✅ **v0.4.7 已修**：选方案 A + B 组合：
- 加 `Settings.startup_eager_connect: bool = False`（baseline 不变，dev / CI 不需要真依赖）
- 加 `_eager_probe_dependencies(app)`：true 时 lifespan startup 跑 `SELECT 1` + `redis.ping()`；失败 raise → uvicorn 退出 → K8s 不 mark ready
- 生产 env 设 `APP_STARTUP_EAGER_CONNECT=true` 启用
- 守门：`tests/unit/test_config.py` +2（default False / env override True）

文档：`docs/architecture/REQUEST_LIFECYCLE.md` 启动行为段标 opt-in；`docs/operations/DEPLOYMENT.md` 生产 checklist 加这一项。

---

## ~~#6~~ — ~~`_EXTRA_FIELDS` 不含 `span_id` / `user_id`~~（✅ 已修，v0.4.7，预留 hook）

✅ **v0.4.7 已修**：`core/logging.py` `_EXTRA_FIELDS` 加 `span_id` / `user_id` 占位 + 详细 docstring 说明"injection points for future auth middleware + OTel SDK"。**当前**这两个字段不会出现在日志（middleware 不注入），但 OTel SDK / auth middleware 接入时只需把值放到 `request.state.*` + access log extra，**logging.py 不用改**。

（v0.5.3 更新：`user_id` 已由 `AuthMiddleware` 注入；`span_id` 已由 OTel SDK 注入，`APP_OTEL_ENABLED=true` 时自动序列化到 access log extra。）

---

## #7 — Cursor 分页 shape 约定但生成器未实施（P2）

**证据**：
- ADR §7.5 强制 cursor 分页 shape `{items, next_cursor, prev_cursor, has_more}`
- generator 模板 0 处 `next_cursor` / `prev_cursor` / `has_more`
- ADR 自己说 cursor 分页"仅在 offset 性能不足时使用"——属于"约定层条款，实现按需"

**影响**：业务真要 cursor 分页时手写 + 易跑偏 shape。

**修复路径**：generator 加 `--cursor` flag 切换模板。

**当前缓解**：业务先用 offset 分页 baseline；性能不足时**严格按 ADR §7.5 cursor shape** 手写。

---

## #8 — ADR Adoption status 历史口径错（已修，留作教训）

**证据**：
- 历史版本 ADR `line 10` Adoption status 写"9 字段 RFC 9457 shape"
- 实际 §1 表只列 8 字段（type / title / status / detail / instance / request_id / trace_id / errors）
- 用户在 IDE 中已修正为 v0.4.4 全实施状态

**教训**：ADR 编辑时口径要与 §1 表对账；编辑后跑 fact-check。

---

## ~~#9~~ — ~~Generator `update()` 语义不对齐（PATCH 行为分裂）~~（✅ 已修，v0.4.8）

✅ **v0.4.8 已修**（review 新发现项，非 v0.4.5 baseline 列表）：

**问题**：`scripts/new_module.py` 三处 `update()` 实现语义不一致——
- `TEMPLATE_REPOSITORY_INMEM.update()`：`model_dump().items() if v is not None`（吞掉显式 None）
- `TEMPLATE_REPOSITORY_DB.update()`：`model_dump(exclude_unset=True)`（正确 PATCH 语义）
- `TEMPLATE_TEST_SERVICE _StubRepo.update()`：`exclude_unset=True` + 再加 `is not None` 过滤（半对半错）

业务从 InMem 切到 `--with-model` 时会出现"显式置 None"隐性回归。

**修复**：InMem + `_StubRepo` 统一改为 `model_dump(exclude_unset=True)`，不再过滤 None；按 RFC 7396 PATCH 语义对齐 DB 版。`tests/unit/test_new_module.py` 加 `test_repository_update_uses_patch_semantics` 防回归。

---

## ~~#10~~ — ~~`Settings.log_level` 无枚举校验，typo 静默到 runtime~~（✅ 已修，v0.4.8）

✅ **v0.4.8 已修**（review 新发现项）：

**问题**：`core/config.py` `log_level: str = "INFO"` 容许任意值。`APP_LOG_LEVEL=INOF` 这种 typo 要等到 `configure_logging()` 才 raise `ValueError`，不符合"配置在 Pydantic 构造阶段校验"的设计意图，也没传达"合法值域"给模板使用者。

**修复**：引入 `LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]`，`log_level: LogLevel = "INFO"`。`tests/unit/test_config.py` +2 守门（5 个合法值通过 / typo 触发 `ValidationError`）。

---

## #11 — `IdempotencyMiddleware._route_is_idempotent` O(N) 路由遍历（P2）

**证据**：`src/admin_platform/core/idempotency.py:369` `for route in request.app.routes: route.matches(...)`。

每个进入的 idempotent POST 都会再做一次 starlette routing match（O(N) 比对 path pattern）。FastAPI 内部已经做过一次同样的 match，相当于在 middleware 层重复了一次。100+ 路由的 service 在每请求两次正则比对，理论成本 < 10μs/req，**实测不是热点**——但属于"做得不漂亮"。

**为什么不修**：要去掉这次遍历需要把判断时机搬到 routing 之后（用 dependency / endpoint decorator 而非 BaseHTTPMiddleware），这会拆掉当前 middleware 的封装边界 + 改变 idempotency 触发顺序。**不成比例**——只在真正路由表 1000+ 且 idempotent POST QPS > 1k 时才值得做。

**触发条件**：实测路由表 ≥ 500 路由 + idempotent POST > 500 QPS / pod。届时实现：

```python
# 装饰时直接把 endpoint id 加进集合
_IDEMPOTENT_ENDPOINTS: set[int] = set()
def idempotent(func):
    _IDEMPOTENT_ENDPOINTS.add(id(func))
    return func
# middleware 用 starlette scope["route"] 拿到 endpoint，O(1) 查集合
```

需要先升级到不走 BaseHTTPMiddleware 的实现，配合 starlette router 暴露 endpoint。

### 自动升 P1 信号

| 信号 | 监控位置 | 升级动作 |
|---|---|---|
| `len(app.routes) >= 500` | unit test `test_route_count_under_500_until_idempotency_v2` 兜底 + service 自检 startup log | 加路由前先讨论：拆服务 vs 升 #11 |
| idempotent POST QPS > 500 / pod 持续 5 min | Prometheus `rate(http_requests_total{method="POST",idempotent="true"}[5m]) > 500` | PR 修 #11，纳入下个 sprint |
| middleware p99 latency 占请求 p99 > 5% | OTel span `idempotency.middleware` 占比 alert | 立刻 P1 重写 |

---

## #12 — Idempotency cache write 早于 transaction commit（P2，需 DB-level idempotency table 兜底）

**证据**：v0.4.11 后 `get_session` 在 dep teardown 才 commit；`IdempotencyMiddleware._cache_and_return`（`src/admin_platform/core/idempotency.py:302` 的 `setex`）在 handler return 后立刻 SETEX 写 "completed" → **commit 失败的话 cache 已经标完成**。

**影响**：超罕见 race window（handler 返 200 + IdempotencyMiddleware 写 cache + commit 时 DB 短暂挂掉），但确实存在。同 key 重试会拿到 cached 200 但实际数据没存。

**修复路径**（不在 baseline，业务侧自做）：金额扣减 / 订单创建场景必须在 service 层加 DB-level `idempotency_keys` 表，与业务表同事务原子写：

```python
# pseudo
async with session.begin():           # 已被 get_session 包了
    existing = await repo.get_idempotency_key(key)
    if existing: return existing.response
    new_order = await order_repo.create(...)
    await repo.save_idempotency_key(key, response=...)  # 同事务 INSERT
# commit 失败 → key 也回滚 → 重试时仍是 first-write
```

Redis cache 只做性能加速，**不参与正确性保证**。这是 Stripe / Square 的标准做法。

**已在 docs/architecture/REQUEST_LIFECYCLE.md "强 at-most-once 边界" 段写清** —— 此条作为提醒而非待修项。

### Redis 拓扑适用范围（v0.4.20 补充）

`IdempotencyMiddleware` 的 `SET NX EX` 仅在以下拓扑下**安全**：

| 拓扑 | 安全性 | 备注 |
|---|---|---|
| **Redis 单节点**（dev / 小服务）| ✅ | 默认假设；本模板 `compose.yaml` 的 cache profile 即此 |
| **主从 + 同步复制**（小风险）| ⚠️ | failover 窗内（秒级）的 SET NX 可能在旧 master 成功，新 master 看不到 → 同 key 多写；金融场景必须 + DB-level table |
| **Redis Cluster**（多分片）| ⚠️ | 同 key 命中同 slot → 同 master，理论 OK；但 slot 迁移 / failover 期可能短暂分裂脑 → 同上 |
| **Redis Sentinel**（高可用）| ⚠️ | failover 期 1-30s 无法获新 lock；正确性同 "主从 + 同步" |
| **多区域 Redis（active-active）**| ❌ | 不要用；正确性完全失守 |

**规则**：本模板的 idempotency cache 是"性能/重复优化"层，**正确性的 SoT 永远是业务侧 DB-level `idempotency_keys` 表**（见上文 #12）。 拓扑选择只影响 cache 命中率与 false negative 率，**不应**靠 Redis 保 at-most-once。

> 推论：**只要业务是"对外不可重放"（金额扣减、订单创建、积分发放）就必须做 #12 兜底**，Redis 拓扑随便选；只是 cache miss 多走一次 DB 表查询而已。

### 自动升 P1 信号

| 信号 | 监控位置 | 升级动作 |
|---|---|---|
| 域内引入金额扣减 / 订单创建 / 任何"对外不可重放"业务 | code review checklist + AI_CODING_RULES.md §6 grep `class .*(Service)` 时人工标记 | 必须先建 DB-level `idempotency_keys` 表，service 层走 #12 模式 |
| 业务侧 incident：cache 返 200 但 DB 无对应记录 | Grafana alert `idempotency_cache_hit_count - business_record_count > 0` over 1h | 立即 P0 修：禁该 endpoint cache，回滚到无幂等 |
| commit 失败率 > 0.1% 持续 10 min | Prometheus `rate(db_commit_failures_total[10m]) > 0.001 * rate(http_requests_total[10m])` | DB 健康检查 + 评估是否要强制 #12 |

---

## #13 — IdempotencyMiddleware / RequestIDMiddleware / AuthMiddleware 用 BaseHTTPMiddleware（P1 长期债，触发条件待）

**证据**：
- `src/admin_platform/core/idempotency.py:157` `class IdempotencyMiddleware(BaseHTTPMiddleware)`
- `src/admin_platform/core/middleware.py:136` `class RequestIDMiddleware(BaseHTTPMiddleware)`
- `src/admin_platform/core/auth.py:149` `class AuthMiddleware(BaseHTTPMiddleware)`（v0.5.3）

**问题**：Starlette 官方文档明确推荐新代码避免 `BaseHTTPMiddleware`，已知 limitations：

1. **body 消费 / 恢复 hack**：`IdempotencyMiddleware.dispatch` 用 `request._receive = _receive`（idempotency.py:155-159）重写私有属性。Starlette 社区已多次讨论是否要 hard-break 这种 hack；真破坏时模板的 idempotency 中间件会直接 crash。
2. **StreamingResponse 不友好**：BaseHTTPMiddleware 强制 collect 整个 response body（`idempotency.py:228-230` 的 `async for chunk in response.body_iterator`）；业务真要做大文件下载 / SSE + idempotency 路由时会内存 spike。
3. **anyio TaskGroup 跑 call_next**：child task 跟 caller 不共享 `ContextVar` copy（除非显式 `contextvars.copy_context()`）。`RequestIDMiddleware` 的 `_request_id_var.set(token)` 在某些 starlette 版本可能跨 task 看不到 → access log 偶发丢 `request_id`。
4. **异常传播**：BaseHTTPMiddleware 内抛的异常**不**进 FastAPI exception_handler 链 —— v0.4.9 引入的 `_problem_response` 就是为此在 middleware 内手 build ProblemDetail，违反 "一处错误响应构造" 的设计意图。

**为什么不立即做**：当前实测**没有触发任何上述限制**——is_known_to_break ≠ breaking_now。改造为 pure ASGI middleware 是中等侵入重写（三个 middleware 都要改 + 测试全套重跑 + 错误响应构造分裂的 v0.4.9 hack 可以借机收敛）。

**触发条件**（任一）：
- starlette 版本破坏 `request._receive` 重写（社区 issue 已有讨论 #2391）
- 业务出现 StreamingResponse（文件下载 / SSE / WebSocket-like long-poll）+ `@idempotent` POST 路由
- 监控发现 access log `request_id` 偶发为 null（ContextVar 跨 task 丢失）
- 任意 middleware 想用 `AppError` / `register_exception_handlers` 而非自建 problem_response

**修复路径**（触发时）：
- 把 `IdempotencyMiddleware` / `RequestIDMiddleware` 改为 pure ASGI middleware（`async def __call__(self, scope, receive, send)`）—— 不走 BaseHTTPMiddleware
- IdempotencyMiddleware 的 body 处理改为 `receive` 包装器，不再 `request._receive = ...`
- access log 改用 ASGI send hook 截 `response_start` 事件取 status_code
- 借机把 `_problem_response` 收敛到 `core/errors.py`（middleware 抛特定异常 → FastAPI exception_handler 接住）

**当前缓解**：保留现实现 + 此处归档警示；不写新的依赖 `request._receive` 重写的 middleware。

### 自动升 P1 信号

| 信号 | 监控位置 | 升级动作 |
|---|---|---|
| Starlette release notes 出现 `request._receive` 删除 / deprecation | 关注 starlette/starlette#2391 + `make audit` 升级 starlette 前手动 review CHANGELOG | 立刻 P0 重写两个 middleware，回滚 starlette 升级直到修完 |
| 业务路由树出现 `StreamingResponse` / SSE / WebSocket-like | `grep -r 'StreamingResponse(' src/` 加 CI lint；新增此类响应类型的 PR 必走 #13 升级评估 | 升 P1，下个 sprint 重写为 pure ASGI |
| Access log `request_id` 为空（fallback 到 `unknown`）比例 > 0.01% | Grafana alert `count(access_log{request_id="unknown"}) / count(access_log) > 0.0001` over 1h | 立即 P1：先观察是否 ContextVar 跨 task 丢；持续超阈值则推 #13 |
| 任意 middleware 想用 `AppError` / `register_exception_handlers` 而非自建 `_problem_response` | 代码 review：grep 新 middleware 是否 import `_problem_response` 或重复 ProblemDetail build | 借机收敛 + 升 #13 一起做（错误响应构造统一）|

---

## #14 — Idempotency replay `_serialisable_headers` collapse 多值响应头（P2）

**证据**：`src/admin_platform/core/idempotency.py:386`

```python
def _serialisable_headers(headers: Any) -> dict[str, str]:
    """过滤成纯 ``str: str`` 映射。多值 header 折叠成最后一个。"""
    return {k: v for k, v in headers.items() if isinstance(k, str) and isinstance(v, str)}
```

**问题**：dict comprehension 对同名 key 自然去重，只保留最后一个值。Starlette 的 `MutableHeaders` 允许同名多值头（HTTP/1.1 § 4.2 标准）；最典型场景是 `Set-Cookie`（session token + tracking id + auth refresh 经常各一行）。idempotent POST 重放时，cached headers 只有最后一个 Set-Cookie 被存 / 重放，前几个全丢。

**影响**：业务接 session/auth/tracking cookie 后做 POST 幂等，客户端在网络抖动重试时收到的响应只含一个 Set-Cookie → 浏览器丢其它 cookie → **用户掉登录态 / 丢 tracking session**。Stripe-style 标准 idempotency 不强制处理这点；当前实现的 docstring 也只是"承认"未处理。

**为什么不立刻修**：fix 路径要把存储格式从 `dict[str, str]` 换成 `list[tuple[str, str]]` + replay 时一行一行 `headers.append(...)`，对 cache 二进制格式向后不兼容（旧 cache 反序列化会报错），需要 cache key 加版本前缀或迁移期双读双写。当前业务还没踩到这条，不值得即刻偿。

**自动升 P1 信号**：

| 信号 | 监控位置 | 升级动作 |
|---|---|---|
| 业务接入 session/auth cookie 框架 且 POST 端点标 `@idempotent` | code review：grep `Set-Cookie` 出现位置 + 是否在 idempotent POST 路径上 | 立即 P1 修：cache headers 改 list-of-tuples 存储 + cache key 加 `v=2:` 前缀 |
| 监控发现登录态丢失 / cookie 计数下降可疑 spike 与 POST 重试 QPS 相关 | Grafana：`rate(http_5xx{path="/auth/refresh"}[5m])` ∝ `rate(idempotency_cache_replay_total[5m])` | 立即 P0 关该端点 cache，强制路径无幂等直到 #14 修完 |
| 业务接入 Server-Timing / X-Custom-* 同名多值头做 trace | code review：grep `headers.append(` 在 production 代码中出现 | 升 P1，下个 sprint 修 |

---

## 修复优先级建议

```
v0.4.6 closed:  ✅ #1 (@idempotent 默认), ✅ #2 (service_id), ✅ #3 (OpenAPI 404 schema)
v0.4.7 closed:  ✅ #4 (test_access_log gap), ✅ #5 (eager connect opt-in), ✅ #6 (span_id/user_id hook)
v0.4.8 closed:  ✅ #9 (generator update PATCH 语义), ✅ #10 (log_level Literal 校验)
v0.4.11 P0:     ✅ get_session 真起 transaction (commit 5a71c94)
v0.4.11 P1/P2:  ✅ readyz 加 Redis ping / Dockerfile 缓存层 + tini / lifespan
                AsyncExitStack / fixture 真清 engine / pytest-cov / trace-id
                全 0 防御 / DB pool sizing doc / pytest-mock / compose env 化
v0.4.12 第二轮 review 闭环:
                ✅ lifespan eager probe 进 stack (P1 残留)
                ✅ CI audit 阻塞 + redis profile + check-db 顺序
                ✅ generator API test 挂 RequestIDMiddleware
                ✅ ruff 加 S/ASYNC/T20
                ✅ TEMPLATE_MODELS __table_args__ 占位
                ✅ alembic compare_server_default=True
                ✅ Redis-backed Idempotency E2E (4 项守门)
                ✅ 限流/metrics/graceful-shutdown 文档边界
                ✅ ClientDisconnect → 499 (access log 区分客户取消)
                ✅ _sync_dispose_engine future-compat (Python 3.14 ready)
v0.4.14 第四轮 review 闭环 (边界硬化):
                ✅ uvicorn 生产参数 (--proxy-headers / --forwarded-allow-ips=* / --no-access-log)
                ✅ Idempotency-Key 长度 ≤255 (防 DoS)
                ✅ Settings 字段 Field(ge/le) + URL scheme 校验 (database/redis)
                ✅ .python-version (3.13) / .pre-commit-config.yaml
                ✅ OpenAPI bearerAuth securitySchemes 占位
                ✅ body size limit 文档 (ingress 兜底)
                ✅ CHANGELOG.md 首版
                ⏭️  .editorconfig 跳过 (Claude hook 阻拦 config 改动,用户可手加)

v0.4.13 第三轮 review 闭环:
                ✅ P1 validation 422 input leak 修复 + 守门
                ✅ 3 处文档 drift (ERROR_RESPONSE / OBSERVABILITY)
                ✅ generator 自动 patch migrations/env.py (--with-model 时)
                ✅ ClientDisconnect → 499 守门测试
                ✅ make audit 本地验证 baseline 0 CVEs
                ✅ make coverage 实测 91% → fail_under 85%
                ✅ HTTPStatus.UNPROCESSABLE_CONTENT (starlette 0.45 deprecation 修)

Remaining:
  P2 →  #7  cursor 分页 — generator 不出，offset 足够时不做；按 ADR §7.5 约定即可
  P2 →  #11 idempotency middleware O(N) 路由遍历 — 路由表/QPS 触阈值再做
  P2 →  #12 idempotency cache 早于 commit race — 业务侧 DB idempotency table 兜底
  P1 →  #13 BaseHTTPMiddleware 长期债 — starlette breaking change / streaming /
            ContextVar 跨 task 任一触发再做（v0.4.13 评估，重写为 pure ASGI）
  P2 →  #14 idempotency cache 多值响应头 collapse — 业务接 session/auth cookie
            到 idempotent POST 时升 P1，需 cache key 加 v=2 前缀做迁移（v0.4.18 加）
```

每修一项 → 划除 + 在 commit message 标 "closes KNOWN_DEVIATIONS.md #N"。
