# 请求生命周期：Middleware 链 + 装饰器

> 一个 HTTP 请求从落到服务到返回响应，经历的所有 baseline 处理顺序。**改动 middleware 顺序前必读**。

## 中间件入栈顺序（`main.py` `create_app`）

```python
# 注册顺序（按 main.py create_app 代码出现顺序）：
1. IdempotencyMiddleware     (if settings.idempotency_enabled)
2. AuthMiddleware            (if settings.auth_enabled)
3. CORSMiddleware            (if settings.cors_allow_origins)
4. RequestIDMiddleware       (always)
```

**Starlette LIFO 入栈语义**：后注册的中间件 → 栈顶 → **请求入站时先执行**。

## 实际请求入站路径

```
inbound request
   │
   ▼
┌─────────────────────────────┐
│ RequestIDMiddleware          │  ← 最先入站（always）
│ • 解析 traceparent           │
│ • 校验 X-Request-ID hex      │
│ • 写 request.state.request_id│
│ • ContextVar.set(token)      │
│ • access_logger 准备         │
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│ CORSMiddleware               │  (if cors_allow_origins)
│ • preflight 拒绝时 transport-│
│   level，不走 §1 shape       │
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│ AuthMiddleware               │  (if auth_enabled)
│ • 解析 Bearer token / 校验   │
│ • public path 放行           │
│ • 注入身份到 request.state   │
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│ IdempotencyMiddleware        │  (if idempotency_enabled)
│ • 只检 POST + @idempotent    │
│ • 读 Idempotency-Key header  │
│ • Redis hash 查 cache        │
│ • 命中：直接返 cached + Replayed│
│ • 未命中：放行 + 缓存响应    │
└─────────────────────────────┘
   │
   ▼
┌─────────────────────────────┐
│ Route matching → handler     │
│   (api.py)                   │
│   ↓                          │
│   service.py                 │
│   ↓                          │
│   repository.py / session    │
└─────────────────────────────┘
   │
   ▼ AppError raised
┌─────────────────────────────┐
│ register_exception_handlers  │
│ • _app_error                 │
│ • _http_error                │
│ • _validation_error          │
│ • _unhandled_error           │
└─────────────────────────────┘
   │
   ▼ ProblemDetail JSON
   响应反向出栈，每层 middleware finally 块跑：
   - access log 单条记录
   - X-Request-ID header 回写
   - Idempotency 缓存（仅 2xx）
```

## RequestIDMiddleware（`core/middleware.py`）

**职责**：注入 32-char hex `request_id` + `trace_id` 到 `request.state` 和 ContextVar。

**优先级**（`_resolve_ids`）：
1. W3C `traceparent` 合法 → `trace-id` 作 `request_id` 和 `trace_id`（同源单一 ID）
2. `X-Request-ID` 合法 hex → 透传；`trace_id = None`
3. 都没/不合法 → `uuid.uuid4().hex` 生成；`trace_id = None`

**响应**：
- 回写 `X-Request-ID: <hex>` header
- access log 一条 JSON（含 request_id / trace_id / method / path / status_code / duration_ms）
- 异常逃逸时 status_code fallback 到 500（access log 仍记录，不静默丢失）

## IdempotencyMiddleware（`core/idempotency.py`）

**触发条件**（任一不满足 → 透传）：

- HTTP method == POST
- 路由 endpoint 标了 `@idempotent` 装饰器
- 请求带 `Idempotency-Key` header

**Cache key**：`idem:{path}:{client-key}`（body hash 进 payload，不进 key）

**两阶段写**（v0.4.9 B 方案：cache-replay → in-flight lock + cache-replay）：

1. **Phase 1 — `SET NX EX=30s`**：first writer 抢锁，payload = `{"state":"in_progress","body_hash":sha256(body)}`
2. **Phase 2 — `SETEX EX=86400s`**：handler 成功完成（2xx）后覆盖锁为 `{"state":"completed","body_hash":...,"status_code":...,"body":...,"headers":...}`

**命中逻辑**（first writer 抢锁失败时）：

| 条件 | 响应 |
|---|---|
| 同 key + 同 body + state=`completed` | replay cached + `Idempotent-Replayed: true` |
| 同 key + 同 body + state=`in_progress` | **409** `framework.IDEMPOTENT_RETRY_IN_FLIGHT` |
| 同 key + **异 body** | **422** `framework.IDEMPOTENCY_KEY_REUSED`（caller bug，不静默重发） |

**只 2xx 写 completed**：4xx/5xx 保留 in_progress 锁直到 30s TTL 自然过期，调用方短期内重试会拿到 409。

**Failure modes**（fail-open，不阻塞业务）：
- Redis `.set_nx()` 失败 → log warning + 退化为"无 idempotency"，直接调 handler
- Redis `.get()` 失败 → log warning + 当 cache miss 处理
- Redis `.setex()` 失败 → log warning + 响应仍返回（仅丢 cache）

**强 at-most-once 边界**：本 middleware 抵御**瞬时并发 race**，**不能**抵御 Redis 失联。金额扣减 / 订单创建场景**必须**在 service 层额外加 DB-level idempotency table 或 unique constraint（参考 Stripe / Square 实现模型），把幂等保证绑到业务事务上而不是缓存层。

**Generator 默认行为**（v0.4.6+）：`make new-module` 生成的 POST 端点默认带 `@idempotent` 装饰器（ADR §11 强制：金额扣减 / 订单创建幂等）。如该端点本身**天然幂等**或 **content-addressed**，**显式移除**装饰器并在 commit message 注明原因。

## Exception handler 链（`core/errors.py` `register_exception_handlers`）

| handler | 触发 | 输出 type |
|---|---|---|
| `_app_error` | `AppError` | `exc.code`（业务定） |
| `_http_error` | `StarletteHTTPException`（404 路由未命中 / 405 等） | `framework.{NAME}` 查表 |
| `_validation_error` | `RequestValidationError` (Pydantic 入参) | `framework.VALIDATION_FAILED`（422） |
| `_unhandled_error` | 其他所有 Exception | `framework.INTERNAL_ERROR`（500） |

详见 [ERROR_RESPONSE.md](./ERROR_RESPONSE.md)。

## 配置开关

`core/config.py` `Settings`：

| 字段 | 默认 | 作用 |
|---|---|---|
| `cors_allow_origins` | `[]` | 非空才注册 CORSMiddleware |
| `idempotency_enabled` | `True` | 注册 IdempotencyMiddleware；False 则 Redis 不连 |
| `idempotency_ttl_seconds` | `86400` | 缓存 TTL（24h，ADR §11） |
| `redis_url` | `redis://localhost:6379/0` | Redis 连接（lazy pool） |
| `request_id_header` | `X-Request-ID` | header 名（不建议改） |
| `service_id` | `service_name` | ADR §3 / §5 / §8 / §10 服务前缀（同源 OpenAPI tag / Datadog service / Prometheus label / JWT aud）|
| `database_url` | `postgresql+asyncpg://app:app@localhost:5432/app` | DB |

## 启动行为（lifespan）

```python
async def lifespan(app: FastAPI):
    configure_logging()                       # JsonFormatter + addLevelName WARN
    if settings.startup_eager_connect:        # v0.4.7 加，默认 False
        await _eager_probe_dependencies(app)  # SELECT 1 + redis.ping()，失败 → 进程退出
    yield
    await dispose_engine()                    # 关 DB pool
    await app.state.redis.aclose()            # 关 Redis pool
```

**默认 lazy**：`Redis.from_url` 和 `create_async_engine` 都 lazy，本地开发 / CI / 单元测试不需要真依赖即可 import app。

**生产推荐 opt-in**：设 `APP_STARTUP_EAGER_CONNECT=true` 让 lifespan 主动 `SELECT 1` + `redis.ping()`。失败时 raise → uvicorn 退出 → K8s 不 mark ready（pod 起不来时不被路由流量）。比 readiness polling 摘流更 fail-fast。

## 修改 middleware 顺序的影响

**禁止**改顺序，除非清楚副作用：

| 顺序变化 | 后果 |
|---|---|
| Idempotency 注册到 RequestID 之前 | `IdempotencyMiddleware` 入站早于 `RequestIDMiddleware` → 缓存内含**上次**的 request_id；replay 会泄露给新调用方 |
| CORS 注册到 RequestID 之后 | `RequestIDMiddleware` 包不到 CORS preflight → preflight 响应无 X-Request-ID header |
| 任何 middleware 注册到 RequestID 之前 | 该 middleware 看不到 `request.state.request_id`（未注入） |

## 测试守门

| 测试 | 守什么 |
|---|---|
| `tests/api/test_access_log.py` 8 项 | request_id 透传 + 生成 + hex 格式 + traceparent 5 用例 |
| `tests/unit/test_idempotency.py` 8 项 | 装饰器 / POST opt-in / cached replay / 不同 body / GET 跳过 / 4xx 不缓存 / Redis 失败降级 |
| `tests/unit/test_openapi_contract.py` | 422 schema = ProblemDetail |
| `tests/api/test_errors.py` | 500 fallback + debug 时 errors 填 |
