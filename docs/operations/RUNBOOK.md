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

## P0.9 后旧库 schema 与 ORM 不一致（残留 `tenants` / `tenant_id`）

**症状**：`make check-db`（alembic check）报大量漂移（`detected removed table 'tenants'`、`removed column 'tenant_id'/'is_platform_admin'`），或运行时报列不存在；但代码已是单租户。

**根因**：P0.9 单租户回归（2026-06-05）**重写了 `0002` 迁移**（同 revision id，内容从多租户 `tenants`/`users` 改为单租户 `users`）。已跑过**旧** `0002_p0_tenant_user` 的库，`alembic_version` 已记 `0002` applied，`alembic upgrade head` 不会重跑新 `0002` 的 DDL → 残留旧多租户结构。

**解决**（dev/CI 库，无生产数据）：
```bash
docker compose down -v            # 删数据卷
make compose-up && make migrate   # 全新跑迁移链 0001 → 0002 users
make check-db                     # 应零漂移
```
fresh clone / 全新 DB 无此问题（直接 `make migrate`）。

> 这是"重写已 applied 迁移"的固有要求。若将来有**不可重建**的持久库，必须改用新 `0003` 做显式转换（drop `tenant_id`/`tenants`），而非重写 `0002`。

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

## 迁移 0017 / 0020：生产大表执行（锁 / 回填 / CONCURRENTLY 中断恢复）

> `0013–0020` 仅本地 dev + CI 临时容器跑过（见 [DEPLOYMENT.md](./DEPLOYMENT.md) 迁移 gated 段）。
> 生产 / 共享库**首跑前**按本节评估——这两条是迁移链里唯二碰大表 / 长锁的。

### 0020 — audit_events / login_logs 分页复合索引

**风险**：两张 append-only 日志热表，行数随运行无限增长。普通 `CREATE INDEX` 持 `SHARE` 锁
会**阻塞表写入**（= 阻塞审计与登录日志落库），大表上可能锁住数分钟。

**已做的缓解**：迁移用 `CREATE INDEX CONCURRENTLY`（`autocommit_block` 跳出迁移链事务，
见 `migrations/versions/0020_log_pagination_indexes.py`），建索引期间**不阻塞读写**。代价：
① 比普通建索引慢 ~2–3×；② 不能在事务内，故 0020 的版本号提交与建索引分两段
（`alembic upgrade 0019:0020 --sql` 可见两条 `CREATE INDEX CONCURRENTLY` 落在 `COMMIT` 之外）。

**执行前检查**：
```bash
# 1. 看两表体量，估建索引时长（CONCURRENTLY ≈ 全表扫两遍）
psql "$APP_DATABASE_URL" -c "SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(oid)) FROM pg_class WHERE relname IN ('audit_events','login_logs');"
# 2. 确认无长事务（CONCURRENTLY 要等所有并发旧事务结束才完成）
psql "$APP_DATABASE_URL" -c "SELECT pid, state, now()-xact_start AS age, left(query,60) FROM pg_stat_activity WHERE state <> 'idle' ORDER BY age DESC LIMIT 5;"
```

**执行**：`make migrate`（= `alembic upgrade head`）。建议先 `alembic upgrade 0019:0020 --sql`
导出 SQL 交 DBA 审。建索引期间另开连接监控：
```sql
SELECT now()-query_start AS dur, query FROM pg_stat_activity WHERE query LIKE 'CREATE INDEX CONCURRENTLY%';
```

**中断恢复（CONCURRENTLY 特有坑）**：CONCURRENTLY 建索引中途失败 / 被 kill，会留下一个
**INVALID 索引**——不被查询使用、占空间，且让重跑迁移报 "already exists"。
```sql
-- 1. 查 INVALID 索引
SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
WHERE NOT i.indisvalid AND c.relname IN ('ix_audit_events_status_time','ix_login_logs_status_time');
-- 2. 删掉（DROP 也并发，免锁），再重跑迁移
DROP INDEX CONCURRENTLY IF EXISTS ix_audit_events_status_time;
DROP INDEX CONCURRENTLY IF EXISTS ix_login_logs_status_time;
```
> 版本号提交在建索引**之后**，正常不会出现 "version=0020 但索引 INVALID"。若真出现（手工中断时机刁钻），
> 删 INVALID 索引后 `alembic downgrade 0019 && alembic upgrade 0020` 重做，或按迁移文件定义手工
> `CREATE INDEX CONCURRENTLY` 补建。

### 0017 — refresh token family_absolute_at 回填 + NOT NULL

**风险**：`auth_refresh_tokens` 上 `add column(nullable) → UPDATE 回填 → ALTER SET NOT NULL`。
该表有界（活跃 refresh token，`cleanup_expired_refresh_tokens` 定期清），体量远小于日志表，但仍注意：
① 回填是一条带 `GROUP BY` 自连接的全表 `UPDATE`；② `ALTER ... SET NOT NULL` 会扫全表并持
`ACCESS EXCLUSIVE` 锁（PG 12+ 更快但仍扫）。

**关键参数（必读）**：回填用 `absolute_ttl` 默认 **30 天**（`auth_refresh_absolute_ttl_seconds=2592000`）。
**若该部署历史上把此配置改成非 30 天**，生产首跑必须显式传历史值，否则旧 family 绝对上限被错填：
```bash
alembic -x refresh_absolute_ttl_seconds=<历史秒数> upgrade 0017
```
迁移刻意不读运行时 config——当前 TTL ≠ 历史签发时 TTL（详见迁移文件注释）。

**执行前检查**：
```bash
psql "$APP_DATABASE_URL" -c "SELECT count(*), count(DISTINCT family_id) FROM auth_refresh_tokens;"
```
体量小（典型 < 数十万行）→ 直接 `make migrate`；若异常大，先评估 `UPDATE` 时长再排窗口。

## 其它

新故障 → 加到本文件 + PR review；不要在 Slack 散落。
