# Runbook：常见故障排查

> 按故障症状索引。新增故障请按相同模板加。

## `/readyz` 返 503

**典型响应**：
```json
{"type": "framework.NOT_READY", "title": "Dependency unavailable", "status": 503, ...}
```

**诊断步骤**：
1. 看 server log 找最近一条 `service_name.errors` 含 stack trace 的记录（debug=True 时才有）
2. 直接连 DB 验证：
   ```bash
   psql "$APP_DATABASE_URL"  # 或 docker exec into pg container 跑 SELECT 1;
   ```
3. 检查 pod 网络：DB host 在 K8s 内是否可达（NetworkPolicy / DNS 解析）

**常见根因**：
- DB pool 满（看 `APP_DB_POOL_SIZE` + `APP_DB_MAX_OVERFLOW`）
- DB host 不可达（DNS / 防火墙）
- DB 凭据错（不会出现在 ProblemDetail body — 见 [../architecture/ERROR_RESPONSE.md](../architecture/ERROR_RESPONSE.md) 安全段）
- DB 真挂

## Idempotency 失效（重复请求出现重复副作用）

**症状**：调用方传相同 `Idempotency-Key`，服务端**没**返 `Idempotent-Replayed: true`，反而执行了两次（如扣两次款）。

**诊断**：
1. 端点是否标了 `@idempotent`？
   ```bash
   grep -B2 "def create_" src/<service>/domains/<name>/api.py
   ```
   没标的 POST 路由**默认不缓存**——`IdempotencyMiddleware` 跳过它。
2. Redis 是否可达？
   ```bash
   redis-cli -u "$APP_REDIS_URL" ping  # 应返 PONG
   ```
   不可达时 `RedisIdempotencyStore` 降级为 cache miss（log warning，不报错）。
3. `Idempotency-Key` header 是否真带了？
   middleware 收不到 header 时 log warning 但放行：
   ```bash
   grep "idempotent route invoked without" /var/log/app.log
   ```

**修复**：
- 缺 `@idempotent` → 加装饰器 + 重新部署
- Redis 不可达 → 修 Redis；不应该让 idempotency 在生产环境长期降级
- 调用方缺 header → 联调对齐

## X-Request-ID 跨服务断链

**症状**：上游调下游，下游 log 里 `request_id` 与上游对不上。

**诊断**：
1. 上游 HTTP client 是否透传 `X-Request-ID`？检查 `httpx.AsyncClient.headers` 配置
2. 调用方传入的格式是否合法 hex？middleware **会校验** `^[0-9a-f]{32}$`，非法值被丢弃替换为新生成（v0.3.2 起，见 ADR §4）
3. 是否有中间代理（gateway / load balancer）剥离了 header

**修复**：
- 上游补透传逻辑
- 调用方确保传 32-char lowercase hex
- 代理白名单 `X-Request-ID`

## OpenAPI spec 里的 422 schema 不对

**症状**：SDK 生成出来 422 类型是 FastAPI 默认 `HTTPValidationError`，不是 `ProblemDetail`。

**诊断**：
- 该 route 是否声明了 Pydantic body（POST/PATCH）？只有有 body 的 route 才触发 FastAPI 自动 422
- 该 route 是否走 `app.routes`（含 `include_router`）？
- 看 `main.py:_custom_openapi` 是否生效：`/openapi.json` 里 `components.schemas` 是否含 `ProblemDetail`

**修复**：
- 改 main.py 时小心 `app.openapi = lambda: _custom_openapi(app)` 这行不能丢
- 如新 route 应有 404 但 OpenAPI 没声明 → 加 `responses={404: {"model": ProblemDetail}}` 显式（generator 默认不加，见 [../tech-debt/KNOWN_DEVIATIONS.md](../tech-debt/KNOWN_DEVIATIONS.md) #3）

## 启动失败但容器看着正常

**症状**：pod READY 但请求超时或 5xx。

**诊断**：
- Redis / DB lazy 连——`Redis.from_url` / `create_async_engine` 都不在 lifespan 主动连
- 第一次请求才触发；如 Redis host 错，第一次 idempotency 请求会失败但 log only warning（middleware 降级）
- DB host 错，第一次 `/readyz` 才暴露

**修复 / 缓解**：
- K8s 起 startupProbe `/startupz`（已在 [DEPLOYMENT.md](./DEPLOYMENT.md)）但**不**强制依赖就绪——这是已知偏差，见 [../tech-debt/KNOWN_DEVIATIONS.md](../tech-debt/KNOWN_DEVIATIONS.md) #5
- 部署前 smoke test：`curl /readyz` 必 200

## Migration autogenerate 出 `NameError`

**症状**：跑 `alembic upgrade head` 时报 `NameError: name 'op' is not defined` 或 `'sa' is not defined`。

**诊断**：
- v0.4.2 修过这个 bug（`migrations/script.py.mako` 缺 `import sqlalchemy as sa` + `from alembic import op`）
- 如果你的 fork 早于 v0.4.2 → 拉新版

**修复**：
- 检查 `migrations/script.py.mako` line 12-13 是否有：
  ```python
  import sqlalchemy as sa
  from alembic import op
  ```

## 日志里 `level` 字段是 `WARNING` 不是 `WARN`

**症状**：log 聚合工具按 `level == "WARN"` 过滤拿不到 warning 日志。

**诊断**：
- `core/logging.py` 模块顶层 `logging.addLevelName(logging.WARNING, "WARN")` 是否还在？
- 是否有其他模块覆盖了 mapping？

**修复**：恢复 `addLevelName` 调用 + 跑 `tests/unit/test_logging.py` 守门。

## 其它

新故障 → 加到本文件 + PR review；不要在 Slack 散落。
