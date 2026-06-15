# Cross-Language ADR — 引用 Stub

> 跨语言协同 ADR（Java/Python HTTP 边界）**不在本仓**，正本位于团队级独立仓库。

## 正本位置

→ **`~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`**

当前状态：本地草稿仓（未上独立 git 远端）；团队后续会推到阿里云效 / GitLab。

## ADR 0001 章节速查

| § | 主题 | 本仓实现位置 |
|---|---|---|
| §1 | ProblemDetail RFC 9457 错误响应 shape（8 字段） | `core/errors.py` `ProblemDetail` / `_payload` |
| §2 | HTTP 状态码语义（RFC 9110） | `core/errors.py` `_HTTP_STATUS_CODES` 16 项映射 |
| §3 | 错误码命名 `{service}.{ERROR_CODE}` | 全仓所有 `code=` 调用 |
| §4 | X-Request-ID 32-char hex + W3C traceparent | `core/middleware.py` `_resolve_ids` |
| §5 | JWT iss/aud / `Settings.service_id` | ✅ `service_id` 已实现（v0.4.6）；iss/aud 校验策略待 Q4 |
| §6 | 健康检查三轨 `/healthz` `/readyz` `/startupz` | `api/v1/health.py` |
| §7 | API 版本前缀 `/api/v1/` | generator 模板 |
| §7.5 | 分页 envelope `{Name}Page` (offset) | generator `TEMPLATE_SCHEMAS` |
| §8 | OpenAPI tag / operation_id / 动词状态码 | generator + `main.py` `_custom_openapi` |
| §9 | JSON log 毫秒+Z / level=WARN 4-char | `core/logging.py` |
| §10 | env_prefix=APP_ | `core/config.py` Settings |
| §11 | Idempotency-Key middleware（Stripe 风格 cached replay）| `core/idempotency.py` |

## 引用 ADR 的本仓文档

- [../INDEX.md](../INDEX.md) — 顶层导航
- [../PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md) — v0.4.4 契约对照表
- [../architecture/ERROR_RESPONSE.md](../architecture/ERROR_RESPONSE.md) — §1 §2 §3 实现细节
- [../architecture/REQUEST_LIFECYCLE.md](../architecture/REQUEST_LIFECYCLE.md) — §4 §11 middleware 链
- [../architecture/OBSERVABILITY.md](../architecture/OBSERVABILITY.md) — §4 §9 链路 + 日志
- [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md) — §3 §4 §7 §8 §10 命名速查
- [../standards/AI_CODING_RULES.md](../standards/AI_CODING_RULES.md) — AI 落地约束

## 为什么独立仓

1. **名义中立**：跨语言 ADR 不该挂在某个语言脚手架仓里
2. **single source of truth**：避免 Python 仓和 Java 仓双轨并存
3. **第三方语言接入低摩擦**：未来 Go / Rust / Node 服务直接引用团队仓
4. **版本化 + PR 评审**：ADR 修订独立流程，不受单一项目仓库节奏影响

## 引用 ADR 的其它仓

| 仓库 | 状态 |
|---|---|
| `python-web-service-template` (本仓) | ✅ Implemented (v0.4.4) |
| `spring-boot-scaffold` | ✅ Implemented (main + archetype 2026-05-15)；剩余 §5 JWT Bearer 等 SSO 接入场景下游补 |

## 跨语言 follow-up（Java 侧）

详细 Java follow-up 表在 ADR 0001 中维护。
