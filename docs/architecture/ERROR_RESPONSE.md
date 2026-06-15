# 错误响应：ProblemDetail + AppError + Handler 链

> 全仓 4xx/5xx 响应**都是同一个 shape**——RFC 9457-aligned `ProblemDetail`，由 `core/errors.py` 4 个 handler 统一产出。调用方写一份解析逻辑全仓服。

## 响应 shape（ADR §1）

```json
{
  "type": "payment.ORDER_NOT_FOUND",
  "title": "Order not found",
  "status": 404,
  "detail": "Order id=42 not found in tenant=acme",
  "instance": null,
  "request_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": null
}
```

8 字段全有，**字段顺序非强制**（Python dict 保插入顺序，Java Jackson 默认按声明顺序——契约测试请 deserialize 后比较，禁止字符串 diff）。

## 字段语义

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `type` | string | ✅ | 错误码，`{service}.{ERROR_CODE}` 或 `framework.*` / `auth.*`，见 [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md) |
| `title` | string | ✅ | 短 summary（不含 id），i18n key 候选 |
| `status` | number | ✅ | HTTP 状态码冗余（便于日志按数字筛） |
| `detail` | string\|null | — | 实例描述，可含 id / 上下文 |
| `instance` | string\|null | — | 错误实例 URI（baseline 固定 null，未来扩展） |
| `request_id` | string\|null | ✅ | 32-char hex，[OBSERVABILITY.md](./OBSERVABILITY.md) 来源 |
| `trace_id` | string\|null | — | W3C trace-id，OTel 未接入时 null |
| `errors` | any\|null | — | 字段级补充（Pydantic / Bean Validation） |

## title vs detail 边界

- `title` = 错误**类型**固定文案，同 `type` 一一对应、可做 i18n
- `detail` = 错误**实例**描述，含 id / 上下文

```python
# ✅ 正确
raise AppError(
    code="payment.INSUFFICIENT_FUNDS",
    title="Insufficient funds",                                    # 类型级
    detail=f"Balance {balance} < required {amount}",               # 实例级
    status_code=400,
)

# ❌ title 含实例信息——违反 ADR
raise AppError(
    code="payment.INSUFFICIENT_FUNDS",
    title=f"Balance {balance} < required {amount}",                # 错！i18n key 用不了
    status_code=400,
)
```

## 5 个 exception handler（`core/errors.py`）

```
异常类型                          → handler                 → 产出 type
─────────────────────────────────────────────────────────────────────────
AppError                         → _app_error              → exc.code  （业务定）
StarletteHTTPException           → _http_error             → framework.{NAME}  （查 _HTTP_STATUS_CODES 表）
RequestValidationError (Pydantic)→ _validation_error       → framework.VALIDATION_FAILED  （422）
IntegrityError (SQLAlchemy)      → _integrity_error        → 注册过的约束走业务 code  （409）
                                                             未注册的约束走 framework.CONFLICT  （409）
                                                             约束名只进 log extra，不暴露在响应 body
Exception（fallback）             → _unhandled_error        → framework.INTERNAL_ERROR    （500，日志记 stack trace）
```

**16 个 HTTP status code 显式映射**（`_HTTP_STATUS_CODES`，避免 ADR §3 禁止的 `ERROR_404` 反模式）：

| status | code |
|---|---|
| 400 | `framework.BAD_REQUEST` |
| 401 | `framework.UNAUTHORIZED` |
| 403 | `framework.FORBIDDEN` |
| 404 | `framework.NOT_FOUND` |
| 405 | `framework.METHOD_NOT_ALLOWED` |
| 406 | `framework.NOT_ACCEPTABLE` |
| 409 | `framework.CONFLICT` |
| 410 | `framework.GONE` |
| 413 | `framework.PAYLOAD_TOO_LARGE` |
| 415 | `framework.UNSUPPORTED_MEDIA_TYPE` |
| 422 | `framework.UNPROCESSABLE_CONTENT` |
| 429 | `framework.TOO_MANY_REQUESTS` |
| 500 | `framework.INTERNAL_ERROR` |
| 502 | `framework.BAD_GATEWAY` |
| 503 | `framework.SERVICE_UNAVAILABLE` |
| 504 | `framework.GATEWAY_TIMEOUT` |

未列出的 status fallback 到 `framework.HTTP_<n>`（罕见，应避免）。

## OpenAPI spec 与 ProblemDetail

`main.py` 的 `_custom_openapi()` 覆盖 FastAPI 默认行为：

- 把 `ProblemDetail` Pydantic model 注入 `components.schemas`
- 把全 spec 中所有出现的 400/401/403/404/409/422/429/500/503 response schema 改成 `#/components/schemas/ProblemDetail`

SDK 自动生成会产出**类型正确**的错误类。

> **现状（v0.4.10+）**：generator 模板的 GET/PATCH/DELETE 路由（404 路径）和 `@idempotent` POST 路由（409 路径）都已显式声明 `responses=NOT_FOUND_RESPONSE` / `responses=IDEMPOTENCY_CONFLICT_RESPONSE`，SDK 自动生成能拿到正确的 ProblemDetail 类型。v0.4.5 之前的"未声明"偏差已在 v0.4.6 / v0.4.10 闭环。

## 生产安全注意

`AppError` 的 `errors` 字段在 debug=True 时可能填充诊断信息。绝不能把：

- 完整 stack trace
- 数据库连接串（SQLAlchemy `OperationalError.__str__` 含密码！见 [../tech-debt/KNOWN_DEVIATIONS.md](../tech-debt/KNOWN_DEVIATIONS.md) 历史教训）
- Authorization header / token / 密码

塞进 `errors` 或 `detail`。`health.py:38` 已示范：`errors = {"reason": type(e).__name__}` 而非 `str(e)`。

**v0.4.13 起 422 框架级脱敏**：`_validation_error` handler 用 `exc.errors(include_input=False)`，Pydantic 校验失败时**不**回显被 reject 的字段值（loc / msg / type / ctx 保留，调试信息够用）。守门：`tests/api/test_errors.py::test_validation_422_does_not_echo_submitted_field_values`。pre-v0.4.13 直接 `exc.errors()` 会让 password / API key / token / PII 进响应 body — 这是模板自身"禁敏字段"规则的反例，必须保持当前修正。

## 测试守门

| 测试 | 守什么 |
|---|---|
| `tests/api/test_errors.py` | 500 fallback 走 ProblemDetail 8 字段 + debug 时填 errors |
| `tests/api/test_health.py::test_readyz_returns_503_when_db_ping_fails` | 503 framework.NOT_READY |
| `tests/api/test_health.py::test_404_returns_unified_error_shape` | 404 framework.NOT_FOUND（显式映射，不再走 HTTP_xxx fallback）|
| `tests/unit/test_openapi_contract.py` 3 项 | ProblemDetail 在 components / 临时 route 422 ref / 全 spec 不漏 FastAPI 默认 |
