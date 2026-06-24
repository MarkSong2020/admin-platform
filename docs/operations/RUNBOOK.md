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
   mysql --defaults-extra-file="$HOME/.my.cnf" \
     --init-command="SET time_zone = '+00:00'" \
     -e "SELECT 1;"  # ~/.my.cnf 权限 600；手工会话也固定 UTC，避免 CURRENT_TIMESTAMP 写入本地墙钟
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

> PostgreSQL 历史库排障路径；当前 MySQL 本地迁移链另按 `make migrate` 执行，生产 / 共享库仍需单独授权。

```bash
# 仅在迁移前 PostgreSQL 历史分支 / tag 上执行；当前 MySQL 分支不要照抄本段。
git checkout <postgres-history-branch-or-tag>
docker compose down -v            # 删历史 dev 数据卷
make compose-up                   # 历史 PostgreSQL compose：起一次性 DB
make migrate                      # 历史迁移链：全新跑 0001 → 0002 users
make check-db                     # 应零漂移
```
fresh clone / 全新 PostgreSQL 历史基线 DB 无此问题。

> 这是"重写已 applied 迁移"的固有要求。若将来有**不可重建**的持久库，必须改用新 `0003` 做显式转换（drop `tenant_id`/`tenants`），而非重写 `0002`。

## Idempotency 失效（重复请求出现重复副作用）

**症状**：调用方传相同 `Idempotency-Key`，服务端**没**返 `Idempotent-Replayed: true`，反而执行了两次（如扣两次款）。

**诊断**：
1. 端点是否标了 `@idempotent`？
   ```bash
   rg -B2 "def create_" src/<service>/domains/<name>/api.py
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
   rg "idempotent route invoked without" /var/log/app.log
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
- 生产/K8s 建议开启 `APP_STARTUP_EAGER_CONNECT=true`（模板已配）：startup 阶段会主动探 DB / Redis，
  配置错误会卡在 startupProbe 而不是等第一笔业务请求暴露
- 本地/dev 默认仍可 lazy 连：如 Redis host 错，第一次 idempotency 请求会失败但 log only warning（middleware 降级）
- DB host 错，`/readyz` 一定暴露；若已开 eager connect，`/startupz` 也会提前暴露

**修复 / 缓解**：
- K8s 起 startupProbe `/startupz`（已在 [DEPLOYMENT.md](./DEPLOYMENT.md)）并保持 `APP_STARTUP_EAGER_CONNECT=true`
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

## 迁移 0017 / 0020：生产 / 共享大表首跑（锁 / 回填 / 在线 DDL）

> `0013–0021` 已是 MySQL 迁移链。生产 / 共享库**首跑前**按本节评估——这两条是迁移链里唯二
> 碰大表 / 长锁的。⚠️ 本仓 `0013–0021` 仅本地 dev + CI 临时容器跑过，**生产 / 共享库迁移待单独授权**。

### 首跑前：核对既有表存储引擎

迁移前置 `assert_mysql_database_capabilities` 会校验 `@@default_storage_engine = InnoDB`，但它只
**管控新建表继承的默认引擎**——若目标库是既有 / 共享库，且历史上曾在非 InnoDB 默认引擎下建过业务表
（后来才把默认值改回 InnoDB），preflight 会放行，但那些既有表仍是 MyISAM，FK / CHECK / `FOR UPDATE`
行锁静默失效。共享 / 既有库首跑前用只读 SQL 审计一次（无非 InnoDB 行才算干净）：
```sql
SELECT TABLE_NAME, ENGINE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_TYPE = 'BASE TABLE'
  AND ENGINE <> 'InnoDB';
```
有命中则先 `ALTER TABLE <name> ENGINE=InnoDB` 转换（评估锁 / 时长，同下方 0020 在线 DDL 注意事项）。

### 0020 — audit_events / login_logs 分页复合索引

**风险**：两张 append-only 日志热表，行数随运行无限增长。建二级索引若退化成持表锁的 `COPY`
算法，会**阻塞表写入**（= 阻塞审计与登录日志落库），大表上可能锁住数分钟。

**已做的缓解**：MySQL 8.0 InnoDB 加二级索引默认走 **Online DDL**（`ALGORITHM=INPLACE, LOCK=NONE`），
建索引期间**允许并发读写**（仅起止两个极短瞬间拿元数据锁）。Alembic `op.create_index` 发出的
`CREATE INDEX` 即按此在线执行（见 `migrations/versions/0020_log_pagination_indexes.py`，additive、
不改表不动数据）。与 PostgreSQL 不同，MySQL 无需 `CONCURRENTLY`，也无需跳出事务。

**执行前检查**（用你的 MySQL 客户端连上目标库后执行——注意 `mysql` CLI 不接受 `$APP_DATABASE_URL`
的 SQLAlchemy URL 形式 `mysql+aiomysql://user:pass@host:port/db`，需手动拆成
`mysql -h<host> -P<port> -u<user> -p <db>`）：
```sql
-- 1. 看两表体量，估建索引时长与额外磁盘（INPLACE 建索引需临时排序 + rebuild 空间）
SELECT table_name, table_rows, ROUND((data_length+index_length)/1024/1024) AS total_mb
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name IN ('audit_events','login_logs');
-- 2. 确认无长事务 / 长查询（Online DDL 起止拿元数据锁，会被未结束的旧事务卡住，连带阻塞后续 DML）
SELECT id, time, state, LEFT(info,60) FROM information_schema.processlist
WHERE command <> 'Sleep' ORDER BY time DESC LIMIT 5;
```

**执行**：`make migrate`（= `alembic upgrade head`）。建议先 `alembic upgrade 0019:0020 --sql`
导出 SQL 交 DBA 审。想在大表上**显式拒绝退化成锁表**，可让 DBA 改用
`ALTER TABLE ... ADD INDEX ..., ALGORITHM=INPLACE, LOCK=NONE`——MySQL 若无法在线完成会直接报错，
而非静默持锁。建索引期间另开连接监控进度：
```sql
SELECT stage.event_name, ROUND(work_completed/NULLIF(work_estimated,0)*100,1) AS pct
FROM performance_schema.events_stages_current stage
JOIN performance_schema.threads thr USING (thread_id)
WHERE thr.processlist_info LIKE 'ALTER TABLE%' OR thr.processlist_info LIKE 'CREATE INDEX%';
```

**中断恢复（MySQL 与 PG 的关键差异）**：MySQL 8.0 是原子 DDL——单条 `CREATE INDEX` 要么建成要么完全
回滚，**不会**像 PostgreSQL 那样留下 INVALID 索引。但 0020 发**两条** `create_index`，而 DDL 在 MySQL
里**各自隐式提交**：若第一条成功、第二条失败，第一个索引已落地而 alembic 版本号尚未 stamp，重跑
迁移会在第一条上撞 `Duplicate key name`。恢复：
```sql
-- 1. 看哪几个索引已建（对照迁移定义的两个名字）
SHOW INDEX FROM audit_events;   -- 找 ix_audit_events_status_time
SHOW INDEX FROM login_logs;     -- 找 ix_login_logs_status_time
-- 2. 把已建的删掉（DROP INDEX 同为 online、免锁），再重跑迁移
DROP INDEX ix_audit_events_status_time ON audit_events;
DROP INDEX ix_login_logs_status_time ON login_logs;
```
> 删掉已建索引后 `make migrate` 重跑即可；或 `alembic downgrade 0019 && alembic upgrade 0020` 重做
> （downgrade 假定两个索引都存在，故需先把状态对齐到「两个都在」或「两个都不在」再执行）。

### 0017 — refresh token family_absolute_at 回填 + NOT NULL

**风险**：`auth_refresh_tokens` 上 `add column(nullable) → UPDATE 回填 → ALTER MODIFY NOT NULL`。
该表有界（活跃 refresh token，`cleanup_expired_refresh_tokens` 定期清），体量远小于日志表，但仍注意：
① 回填是一条带 `GROUP BY` 自连接的全表 `UPDATE`；② 改 `NOT NULL`（`op.alter_column`）在 MySQL 8.0
走 `ALTER TABLE ... MODIFY`，回填后无 NULL 时可 `ALGORITHM=INPLACE`，但起止仍持元数据锁、会被长事务卡住。

**关键参数（必读）**：回填用 `absolute_ttl` 默认 **30 天**（`auth_refresh_absolute_ttl_seconds=2592000`）。
**若该部署历史上把此配置改成非 30 天**，生产首跑必须显式传历史值，否则旧 family 绝对上限被错填：
```bash
alembic -x refresh_absolute_ttl_seconds=<历史秒数> upgrade 0017
```
迁移刻意不读运行时 config——当前 TTL ≠ 历史签发时 TTL（详见迁移文件注释）。

**执行前检查**（用你的 MySQL 客户端连上目标库执行；连接参数取自 `$APP_DATABASE_URL`，
`mysql` CLI 不接受其 SQLAlchemy URL 形式，需拆成 `-h/-P/-u/-p` flags）：
```sql
SELECT count(*), count(DISTINCT family_id) FROM auth_refresh_tokens;
```
该表体量通常小（典型 < 数十万行）→ 直接 `make migrate`；若异常大，先评估 `UPDATE` 时长再排窗口。

## 其它

新故障 → 加到本文件 + PR review；不要在 Slack 散落。
