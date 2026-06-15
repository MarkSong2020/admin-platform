# 跨语言协同契约（HTTP 边界约定）

> 本仓的 HTTP 边界（错误响应 / 错误码 / 链路标识 / 健康检查 / 分页 / 幂等）遵循一套**与语言无关的工程约定**，让 Java / Go / Node 等其他后端能以同一套契约对齐。本文把每条约定映射到本仓的具体实现位置，方便按图索骥。

## 约定 → 本仓实现

| § | 主题 | 本仓实现位置 |
|---|---|---|
| §1 | ProblemDetail RFC 9457 错误响应 shape（8 字段） | `core/errors.py` `ProblemDetail` / `_payload` |
| §2 | HTTP 状态码语义（RFC 9110） | `core/errors.py` `_HTTP_STATUS_CODES` 16 项映射 |
| §3 | 错误码命名 `{service}.{ERROR_CODE}` | 全仓所有 `code=` 调用 |
| §4 | X-Request-ID 32-char hex + W3C traceparent | `core/middleware.py` `_resolve_ids` |
| §5 | JWT iss/aud / `Settings.service_id` | `service_id` 已实现；iss/aud 校验策略待定 |
| §6 | 健康检查三轨 `/healthz` `/readyz` `/startupz` | `api/v1/health.py` |
| §7 | API 版本前缀 `/api/v1/` | generator 模板 |
| §7.5 | 分页 envelope `{Name}Page`（offset） | generator `TEMPLATE_SCHEMAS` |
| §8 | OpenAPI tag / operation_id / 动词状态码 | generator + `main.py` `_custom_openapi` |
| §9 | JSON log 毫秒+Z / level=WARN 4-char | `core/logging.py` |
| §10 | env_prefix=`APP_` | `core/config.py` `Settings` |
| §11 | Idempotency-Key middleware（Stripe 风格 cached replay）| `core/idempotency.py` |

## 设计理念

1. **名义中立**：跨语言契约不绑定任何单一语言的脚手架，便于多语言后端共享同一套边界语义。
2. **single source of truth**：错误码 / 链路 / 分页 envelope 等约定只定义一次，避免各语言实现各写一套、互相漂移。
3. **第三方语言低摩擦接入**：新的 Go / Rust / Node 服务可直接照此约定实现 HTTP 边界，无需逆向某个语言的实现。

## 引用本约定的本仓文档

- [../INDEX.md](../INDEX.md) — 顶层导航
- [../PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md) — 契约对照表
- [../architecture/ERROR_RESPONSE.md](../architecture/ERROR_RESPONSE.md) — §1 §2 §3 实现细节
- [../architecture/REQUEST_LIFECYCLE.md](../architecture/REQUEST_LIFECYCLE.md) — §4 §11 middleware 链
- [../architecture/OBSERVABILITY.md](../architecture/OBSERVABILITY.md) — §4 §9 链路 + 日志
- [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md) — §3 §4 §7 §8 §10 命名速查
- [../standards/AI_CODING_RULES.md](../standards/AI_CODING_RULES.md) — AI 落地约束
