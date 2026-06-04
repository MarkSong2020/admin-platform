# 可观测性：日志 / Request ID / Trace ID

> 三件套：JSON 日志、X-Request-ID 链路、W3C trace-id 接入。**生产前必读**——监控告警和日志聚合都依赖此处约定。

## JSON 日志（`core/logging.py`）

**格式**：单行 JSON per record，UTF-8。

**必含字段**：

| 字段 | 来源 | 例 |
|---|---|---|
| `timestamp` | `_adr_timestamp()` 毫秒+Z（ADR §9） | `"2026-05-15T08:30:15.123Z"` |
| `level` | `addLevelName(WARNING, "WARN")` 强制 4-char | `"INFO"` / `"WARN"` / `"ERROR"` / `"DEBUG"` |
| `logger` | logger name | `"service_name.access"` |
| `message` | record.getMessage() | `"request handled"` |

**推荐字段**（access log 通过 `extra=` 注入）：

| 字段 | 来源 | 含义 |
|---|---|---|
| `request_id` | RequestIDMiddleware | 32-char hex |
| `trace_id` | RequestIDMiddleware | 同 W3C trace-id，OTel 未接入时 null |
| `method` | request.method | GET / POST 等 |
| `path` | request.url.path | URL path |
| `status_code` | response.status_code | 异常逃逸时 fallback 500 |
| `duration_ms` | `time.perf_counter()` 计算 | 毫秒精度 |

**预留 hook**（v0.4.7 起）：`span_id` / `user_id` 已在 `_EXTRA_FIELDS` 白名单。
- `user_id`：v0.5.3 auth middleware 已注入 `request.state.user_id`（auth debug log 含 user_id；
  主 access log 后续加 extra 字段即可自动序列化）
- `span_id`：v0.5.3 OTel SDK 已接入（默认关闭）；``APP_OTEL_ENABLED=true`` 时自动注入 access log extra

**禁止字段**：

- 明文 password / token / API key
- `Authorization` header 完整值
- 完整 credit card number / 国民身份号 / 邮箱（部分场景）

**注意**：`/readyz` 失败时**绝不**`str(SQLAlchemyError)`——含 DSN 密码。`health.py` 用 `type(e).__name__`，参考 ADR v0.3.2 fix。

## X-Request-ID（ADR §4）

**Header 名**：`X-Request-ID`（全大写 ID）

**值格式**：32-char lowercase hex，**无连字符**（W3C trace-id 同格式，OTel 接入零跳变）

**生命周期**：
1. 入站 `traceparent` 合法 → 提取 trace-id 作 request_id（同时 `trace_id` 字段）
2. 入站 `X-Request-ID` 合法 hex → 透传
3. 都不合法 → `uuid.uuid4().hex` 生成

响应回写同名 header。错误响应 body 含 `request_id` 字段（不论是否有 traceparent）。

**跨服务调用**：HTTP 客户端必须把当前请求的 `X-Request-ID` 透传到下游。OTel 接入后**同时**透传 `traceparent` / `tracestate`。

## Trace ID 与 W3C Trace Context

**`traceparent` 格式**：`{version}-{trace-id}-{parent-id}-{trace-flags}`

```
00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
   └────── 32-char trace-id ─────┘ └─ 16-char span-id ─┘
```

middleware 用 regex `^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$` 捕获 group 1（trace-id）/ group 2（parent-id）/ group 3（trace-flags）。trace-id 作 `request_id`；OTel 开启时 parent-id 作入站 span 的 parent，据此构造子 span（见 `middleware.py::_create_span_context`）。

**OTel 接入状态**：
- **v0.5.3**：`opentelemetry-sdk` + `exporter-otlp-proto-http` 已装，默认关闭
- `APP_OTEL_ENABLED=true` 时：lifespan 初始化 TracerProvider + BatchSpanProcessor + OTLPSpanExporter；`RequestIDMiddleware` 为每个请求创建 span，`span_id` 注入 access log extra
- 配置走标准 OTel env vars（`OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` 等）
- 未开启时 span_id 为 None（零开销，NoOp tracer）

**生命周期健壮性**（`observability.py`）：
- **初始化失败降级**：OTel 是可选能力——exporter/provider 构造抛错时降级为 warning + 关闭 tracing，**绝不阻塞服务启动**（`init_observability` 整段 try/except）
- **全局 Once**：`trace.set_tracer_provider` 进程内只能成功设一次。本模块用 identity 校验（`get_tracer_provider() is provider`）确认真的安装成功才记为 owned；否则说明已有别的全局 provider → 清理刚新建的 provider（停 `BatchSpanProcessor` 后台导出线程，防泄漏）+ **不保存假引用**（避免日志谎报、shutdown flush 错对象）
- **shutdown 只 flush owned provider**：lifespan teardown 调 `force_flush()` 把缓冲 span 推出去；不调 `provider.shutdown()`（进程级单例，进程退出即回收）

**测试守门**：`tests/api/test_access_log.py::test_traceparent_*` 5 项 + `tests/api/test_otel.py` 7 项（disabled / span_id 注入 / **span 真导出** / **入站 traceparent → remote parent 串联** / 多生命周期复用 / **init 失败降级** / **Once 不保存假 provider**）。

## Access log per request

每个请求结束（含异常路径）出一条 access log：

```json
{
  "timestamp": "2026-05-15T08:30:15.123Z",
  "level": "INFO",
  "logger": "service_name.access",
  "message": "request handled",
  "request_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "trace_id": null,
  "method": "POST",
  "path": "/api/v1/orders",
  "status_code": 201,
  "duration_ms": 23.45
}
```

异常逃逸时 `status_code` fallback 500（Starlette 包成 500 响应给客户端）。客户端断开（`starlette.requests.ClientDisconnect`）时 access log 记 **499** —— nginx 惯例 "client closed request"，让 5xx 错误率监控不被用户取消污染（v0.4.12 起）。

## ProblemDetail 中的 ID 字段

错误响应 body 8 字段中：

```json
{
  "request_id": "<from middleware>",
  "trace_id": "<from middleware, null if no traceparent>",
  ...
}
```

调用方主要按 `request_id` 对账（不论 OTel 状态都有值）。

## 监控指标（**baseline 不内置；业务自加**）

**ADR §11 未强制** metrics。当前 baseline:
- ❌ 无 Prometheus `/metrics` endpoint（baseline 不内置 → 不绑死监控栈）
- ❌ 无 QPS / 错误率 / p99 latency / Redis hit rate / Idempotent replay rate
- ✅ 有结构化日志可被 Loki / Datadog / ELK 聚合

**业务接入方式**：见 [../operations/DEPLOYMENT.md](../operations/DEPLOYMENT.md) "Metrics endpoint" 段——推荐 `prometheus-fastapi-instrumentator` 在 `create_app()` 末尾装上、`/metrics` 用 `include_in_schema=False` 不污染 OpenAPI、K8s `ServiceMonitor` 配置示例。

完整指标接入策略待团队评估（ADR Open Q10），见 [../tech-debt/OPEN_QUESTIONS.md](../tech-debt/OPEN_QUESTIONS.md)。

## 调试 tips

**查某个请求的全链路**：

```bash
# 假设 request_id = 4bf92f...
grep '"request_id":"4bf92f3577b34da6a3ce929d0e0e4736"' /var/log/app.log
```

**跨服务调用追踪**：上游和下游服务都打这个 `request_id` 到日志 → 一条 grep 命令拉到完整调用链。

**OTel 接入后**：`trace_id` 同 `traceparent` 中的 trace-id → 用 OTel collector / Jaeger UI 直接看 span tree。

## 相关文档

- middleware 入栈顺序 → [REQUEST_LIFECYCLE.md](./REQUEST_LIFECYCLE.md)
- 错误响应 body 字段 → [ERROR_RESPONSE.md](./ERROR_RESPONSE.md)
- 已知偏差（span_id / user_id 等）→ [../tech-debt/KNOWN_DEVIATIONS.md](../tech-debt/KNOWN_DEVIATIONS.md)
