# 命名约定速查

> 错误码 / OpenAPI tag / operation_id / 服务前缀 / 表名 / 模块名 一张表搞清。**生产前必读**——这些一旦发布到生产就锁死。

## 服务前缀（最重要）

ADR §3 规定：服务前缀 **= 部署单元名 = OpenAPI tag = Prometheus label = Datadog `service` tag = `Settings.service_id`**——**四者必须同源**。

```
payment       (示例服务)
├── 错误码 type:        payment.ORDER_NOT_FOUND
├── OpenAPI tag:        payment / orders / users (每个业务域一个 tag)
├── Datadog service:    payment
├── Prometheus label:   service="payment"
└── Settings.service_id: "payment"  ← v0.4.6 实现（见 core/config.py:30）
```

冲突治理：服务前缀需全局唯一，命名规则见 [跨语言协同契约](../reference/CROSS_LANGUAGE_ADR.md)；多服务协同时新前缀须保证不与既有冲突。

## 错误码（`type` 字段）

格式：`{service}.{ERROR_CODE}`

| `type` | 解读 |
|---|---|
| `payment.ORDER_NOT_FOUND` | service=payment, code=ORDER_NOT_FOUND |
| `order.ALREADY_PAID` | service=order, code=ALREADY_PAID |
| `user.ALREADY_EXISTS` | service=user, code=ALREADY_EXISTS |
| `framework.VALIDATION_FAILED` | 框架自动触发（Pydantic 422 等） |
| `framework.NOT_READY` | `/readyz` 失败 |
| `auth.TOKEN_EXPIRED` | 鉴权层（JWT 过期） |
| `auth.FORBIDDEN_BY_ROLE` | 鉴权层（权限不足） |

**ERROR_CODE 部分**：SCREAMING_SNAKE_CASE，允许多段下划线，**不强制** `{DOMAIN}_{REASON}` 切分。

**保留前缀**：
- `framework.*` — 框架/基础设施触发，全 16 条 HTTP status 显式映射见 [../architecture/ERROR_RESPONSE.md](../architecture/ERROR_RESPONSE.md)
- `auth.*` — 鉴权 / 权限层

**禁止**：
- `ERROR_404` / `HTTP_404` — HTTP status 已在 `status` 字段
- `not_found` / `NotFound` — 不统一大小写
- 裸 `ORDER_NOT_FOUND`（缺服务前缀，多服务时不知归属）

## OpenAPI tag

格式：**业务域复数小写**，单数概念例外：

| 类别 | tag | 示例 |
|---|---|---|
| 业务域 | 复数小写 | `orders` / `users` / `payments` |
| 基础设施 | 单数 group 名 | `health` / `observability` |

SDK 生成器（如 openapi-generator）基于 tag 自动产 `OrdersApi` 类名，无需 ADR 强制驼峰。

## operation_id

格式：`{plural}_{action}` snake_case（业务），endpoint 名本身（基础设施）：

| 端点 | tag | operation_id |
|---|---|---|
| `GET /api/v1/orders` | `["orders"]` | `orders_list` |
| `GET /api/v1/orders/{id}` | `["orders"]` | `orders_get` |
| `POST /api/v1/orders` | `["orders"]` | `orders_create` |
| `PATCH /api/v1/orders/{id}` | `["orders"]` | `orders_update` |
| `DELETE /api/v1/orders/{id}` | `["orders"]` | `orders_delete` |
| `GET /healthz` | `["health"]` | `healthz` |
| `GET /readyz` | `["health"]` | `readyz` |
| `GET /startupz` | `["health"]` | `startupz` |

**全局唯一**：同一 service 内 `operation_id` 不能重复（SDK 自动生成要求）。

## HTTP 动词 + 状态码

| 动作 | 动词 | 成功状态码 | 备注 |
|---|---|---|---|
| 创建 | `POST` | 201 Created | response body = 创建后实体 |
| 查询单条 | `GET` | 200 OK | — |
| 查询列表 | `GET` | 200 OK | 返回 `{Name}Page` envelope（不是裸数组）|
| 部分更新 | `PATCH` | 200 OK | response body = 更新后实体 |
| 全量替换 | `PUT` | 200 OK | 不强制要求支持 |
| 删除 | `DELETE` | 204 No Content | 无 body |

## 模块名 + 文件名

| 名 | 规则 | 示例 |
|---|---|---|
| Module name | snake_case 单数 | `order` / `user_profile` |
| Module pascal | 自动派生 | `Order` / `UserProfile` |
| URL plural | 默认 `<name>s`，不规则手传 | `orders` / `users` / `categories`（手传）|
| Table name | = URL plural | `orders` / `users` / `categories` |
| Pydantic class | `{Name}Create / {Name}Read / {Name}Update / {Name}Page` | `OrderCreate` 等 |
| ORM class | `{Name}` | `Order` |

## 路径前缀

- 业务端点 **必走** `/api/v{N}/...`（当前 `v1`）
- 基础设施端点 **不走**版本前缀：`/healthz` / `/readyz` / `/startupz` / `/docs` / `/openapi.json` / `/metrics`（未实施）

## 头部命名

| Header | 规则 | 来源 |
|---|---|---|
| `X-Request-ID` | 全大写 ID，3 字符；32-char lowercase hex 值 | ADR §4 |
| `Idempotent-Replayed` | response header，cached replay 时填 `true` | ADR §11 |
| `Idempotency-Key` | request header，调用方传 opaque string | ADR §11 |
| `traceparent` | W3C Trace Context | ADR §4 |
| `Authorization` | `Bearer <JWT>` | ADR §5 |

## 配置 / env

格式：`APP_<UPPER_SNAKE_CASE>`

| env | Settings 字段 | 默认 |
|---|---|---|
| `APP_APP_NAME` | `app_name` | `"python-web-service-template"` |
| `APP_SERVICE_ID` | `service_id` | `"service_name"`（ADR §3 服务前缀，sed rename 时自动 cover；多上下文同源——见上文「服务前缀」段）|
| `APP_DEBUG` | `debug` | `False` |
| `APP_LOG_LEVEL` | `log_level` | `"INFO"`（Python logging name，5-char `WARNING`；输出字段是 4-char `WARN`，见 [../architecture/OBSERVABILITY.md](../architecture/OBSERVABILITY.md)） |
| `APP_DATABASE_URL` | `database_url` | `mysql+asyncmy://app:app@localhost:3306/app` |
| `APP_REDIS_URL` | `redis_url` | `redis://localhost:6379/0` |
| `APP_IDEMPOTENCY_ENABLED` | `idempotency_enabled` | `True` |
| `APP_IDEMPOTENCY_TTL_SECONDS` | `idempotency_ttl_seconds` | `86400` (24h) |
| `APP_CORS_ALLOW_ORIGINS` | `cors_allow_origins` | `[]` |
| `APP_REQUEST_ID_HEADER` | `request_id_header` | `"X-Request-ID"` |

## 日志 level（输出字段）

ADR §9 强制 **4 字符**：

```
INFO / WARN / ERROR / DEBUG
```

Python 标准库默认输出 `WARNING`（5 字符）；`logging.py` 顶层 `addLevelName(WARNING, "WARN")` 改 mapping。

**注意**：`Settings.log_level` 是 Python `setLevel()` 输入，必须是 `"WARNING"`（标准库 name）；输出字段是 `"WARN"`——两者不冲突。

## 引用

- 全部命名规则的强制力来源：[跨语言协同契约](../reference/CROSS_LANGUAGE_ADR.md) §3 / §4 / §7 / §8 / §10
- 实现细节：[../architecture/ERROR_RESPONSE.md](../architecture/ERROR_RESPONSE.md) / [../architecture/OBSERVABILITY.md](../architecture/OBSERVABILITY.md)
- 服务前缀（`service_id`）约定：[跨语言协同契约](../reference/CROSS_LANGUAGE_ADR.md) §5
