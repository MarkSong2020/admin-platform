# 术语表

> 本仓 / 跨语言 ADR / 团队约定中出现的术语。**碰到不明白的词先查这里**。

## A

**ADR**（Architecture Decision Record）
跨服务 / 跨语言的架构决策记录。本仓引用的正本是 `~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`。

**AppError**
`core/errors.py` 定义的业务异常类。签名：`AppError(code, title, *, detail=None, status_code=400, errors=None)`。所有业务异常**必须**通过它抛出，**不要**用 `HTTPException`。

**Annotated\[Service, Depends(...)\]**
FastAPI 现代 DI 模式。替代旧的 `svc: Service = Depends(...)`（触发 ruff B008）。Generator 模板默认产出此风格。

## C

**ContextVar**
Python `contextvars.ContextVar` 用于跨 async task 传递 request_id 等上下文。本仓在 `core/middleware.py` 用它存 `_request_id_var`。

**CORS preflight**
浏览器跨域前的 `OPTIONS` 请求。CORS 拒绝 = transport-level 错误，**不**走 ADR §1 ProblemDetail shape。

**`@idempotent`**
`core/idempotency.py` 装饰器。标 POST 路由为幂等——`IdempotencyMiddleware` 见到此标记 + `Idempotency-Key` header 才启用缓存。**Opt-in**——默认不启用。

## E

**`framework.*` / `auth.*` / `{service}.*`**
错误码（`type` 字段）的三类前缀。`framework` = 框架自动触发（VALIDATION_FAILED / INTERNAL_ERROR 等）；`auth` = 鉴权层；其它 = 业务服务名。详见 [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md)。

## H

**hex 32-char**
ADR §4 强制的 `X-Request-ID` / `trace_id` 格式：32 个十六进制字符，**无连字符**。例 `4bf92f3577b34da6a3ce929d0e0e4736`。与 W3C trace-id 同格式，OTel 接入零跳变。

## I

**Idempotency-Key**
客户端在 POST 请求 header 中提供的唯一标识，用于服务端去重重试。本仓 `core/idempotency.py` 实现 Stripe 风格 cached replay（同 key 同 body 返 cached + `Idempotent-Replayed: true` header）。

**InMemoryRepository**
Generator 不带 `--with-model` 时产出的内存仓储桩。用于单测和早期 HTTP 层调试，不涉及 DB。

## J

**JsonFormatter**
`core/logging.py` 定义的日志格式化器。产出 ADR §9 强制的毫秒+Z timestamp + level 4-char + request_id / trace_id 等字段。

## L

**lifespan**
ASGI 协议 startup / shutdown hook。本仓在 `main.py` 用它：
- startup: `configure_logging()`
- shutdown: `dispose_engine()` + `redis.aclose()`

**LIFO middleware ordering**
Starlette 中间件入栈语义：**后注册的在外层**，入站时先执行。`main.py` 注册顺序 CORS → Idempotency → RequestID 的实际入站顺序是反的（RequestID 最先）。

## P

**ProblemDetail**
`core/errors.py` 定义的 Pydantic model，对应 ADR §1 RFC 9457-aligned 8 字段错误响应。注入 OpenAPI `components.schemas` 让 SDK 生成器拿到正确类型。

**`{Name}Page`**
分页响应 envelope（ADR §7.5）。5 字段：`items / page / size / total / total_pages`。Generator v0.4 起每个业务域自动生成。

## R

**RequestIDMiddleware**
`core/middleware.py` 中间件。注入 `request.state.request_id` 和 `request.state.trace_id`；access log 每请求一条。

**RedisIdempotencyStore**
`core/idempotency.py` 实现。`IdempotencyStore` Protocol 的 Redis 后端。错误降级（log warning + 当 cache miss / 仍返响应）。

## S

**Settings**
`core/config.py` 中的 Pydantic `BaseSettings` 类。所有运行时配置（database_url / redis_url / cors_allow_origins 等）走它读取，**不要**业务代码硬编码。

**`service_id`**
`Settings` 字段（v0.4.6 实现）。用于 JWT `aud` 校验、OpenAPI tag root、Datadog `service` tag、Prometheus label 同源（详见 [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md) 服务前缀段）。注册到团队仓 `service-prefix-registry.md` 才能用。

## T

**traceparent**
W3C Trace Context spec 的 HTTP header：`{version}-{trace-id}-{parent-id}-{trace-flags}`。本仓中间件解析它优先于 `X-Request-ID`。

**`type` (in ProblemDetail)**
错误响应字段，等于 `AppError.code`，格式 `{service}.{ERROR_CODE}`（ADR §3）。**不是** Python 内置 `type()`。

## W

**WARN（4-char）**
ADR §9 强制日志 level 字段是 `WARN` 四字符（不是 Python 默认 `WARNING` 七字符）。本仓 `logging.py` 顶层 `addLevelName(WARNING, "WARN")` 实现 mapping。

**W3C Trace Context**
[`https://www.w3.org/TR/trace-context/`](https://www.w3.org/TR/trace-context/) 跨语言分布式链路 header 标准。本仓接入 `traceparent` 解析，未接入完整 OTel SDK。

## X

**`X-Request-ID`**
ADR §4 强制 HTTP header，32-char lowercase hex。响应必回写。任何 4xx/5xx 响应 body 含 `request_id` 字段。

## 缩写

| 缩写 | 全称 |
|---|---|
| ADR | Architecture Decision Record |
| DTO | Data Transfer Object (Pydantic 模型) |
| ORM | Object-Relational Mapping (SQLAlchemy) |
| PII | Personally Identifiable Information |
| TTL | Time To Live (Redis cache 过期时间) |
| W3C | World Wide Web Consortium |
