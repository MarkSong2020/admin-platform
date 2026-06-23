# 部署

> Dockerfile / K8s probe / 生产配置 checklist。

## Dockerfile

多阶段构建（python:3.14-slim builder + runtime），`uv sync --frozen --no-dev --no-editable`，非 root 用户（uid 10001）。`CMD ["uvicorn", "admin_platform.main:app", "--host", "0.0.0.0", "--port", "8000"]`。

**本地构建**：

```bash
make docker-build   # docker build -t admin-platform:dev .
```

**镜像 tag 规则**（生产）：

- `<service>:<git-sha-short>`（每个 commit）
- `admin-platform:v0.0.1`（语义版本，以 `pyproject.toml [project].version` 为准，发布时）
- 不用 `:latest`（不可追溯）

## K8s probe 配置（ADR §6）

三轨 probe 必须全配，K8s 在 `startupProbe` 通过前**不**跑 liveness/readiness：

```yaml
startupProbe:
  httpGet: { path: /startupz, port: 8000 }
  failureThreshold: 30        # 30 × 2s = 60s 启动窗口
  periodSeconds: 2

livenessProbe:
  httpGet: { path: /healthz, port: 8000 }
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet: { path: /readyz, port: 8000 }
  periodSeconds: 5
  failureThreshold: 2
```

> 📦 **完整 K8s manifest 模板（Deployment + Service + ConfigMap + Secret + HPA + PDB）**：
> [`examples/k8s/deployment.yaml`](../../examples/k8s/deployment.yaml) — 含 `${SERVICE_NAME}` `${IMAGE}` `${REPLICAS}` 占位，`envsubst` 替换即可 apply。包含 preStop drain / read-only rootfs / non-root uid 10001 / drop all caps 的 CIS baseline。

**响应**：

| Endpoint | 200 body | 503 body |
|---|---|---|
| `/healthz` | `{"status": "ok"}` | — 不会失败（不查依赖）|
| `/readyz` | `{"status": "ready"}` | `ProblemDetail` shape，`type=framework.NOT_READY`、`status=503`、`title="Dependency unavailable"`、`request_id` 同 `X-Request-ID` header |
| `/startupz` | `{"status": "started"}` | — 不会失败（lifespan 跑完前 K8s 不会发请求来）|

> OpenAPI 显式声明 `/readyz` 503 → `ProblemDetail`（v0.4.21 起）；SDK 生成器可看到完整失败路径。守门：`tests/unit/test_openapi_contract.py::test_readyz_advertises_503_problem_detail_in_openapi`。

重型 init（ML model load / 缓存预热）需在 `health.py:startupz` 加 `app.state.startup_complete` 检查。

## 生产配置 checklist

| 项 | env | 注意 |
|---|---|---|
| `APP_ENVIRONMENT` | `production` | **门禁总开关**。设 `production` 触发 `core.config` 生产门禁：缺 `auth_enabled` / 空 pepper / `debug=true` / `auth_public_paths` 含命名空间宽前缀（`/api` 等）→ startup fail-fast。**生产镜像 Dockerfile 已默认 `production`**；本地 / CI 不跑镜像（host 直跑 → 默认 `local`）。如用本镜像跑非生产须显式覆盖 `local` |
| `APP_DATABASE_URL` | `mysql+asyncmy://USER:PASS@HOST:3306/DB` | **绝不**用默认值 `app:app@localhost`；生产走 secret 注入；MySQL 版本需 ≥ 8.0.16，schema 默认 collation 必须是 `utf8mb4_0900_bin`，开启 binlog 时需 `log_bin_trust_function_creators=1` |
| `APP_REDIS_URL` | `redis://...:6379/0` | idempotency 用；不可达时降级，但金额场景应监控 Redis 健康 |
| `APP_DEBUG` | `False` | **绝不**在生产 / staging 设 True（会让错误响应填诊断信息）|
| `APP_LOG_LEVEL` | `INFO` | DEBUG 会量 |
| `APP_CORS_ALLOW_ORIGINS` | `["https://yourapp.com"]` | **禁止**`["*"]` + `allow_credentials=True` 组合（Pydantic validator 已拦） |
| `APP_IDEMPOTENCY_ENABLED` | `True` | 默认开；False 时跳过 Redis（dev 环境可用） |
| `APP_IDEMPOTENCY_TTL_SECONDS` | `86400` | 24h；金额场景按业务调整 |
| `APP_STARTUP_EAGER_CONNECT` | **`true`** | 生产推荐 true；lifespan 启动时主动 ping DB + Redis，失败 pod 起不来。本地 / CI 默认 false |

### 认证 / RBAC（P0–P1，**生产必设**）

| 项 | env | 默认 | 注意 |
|---|---|---|---|
| 启用鉴权 | `APP_AUTH_ENABLED` | `False` | **生产必开 `true`**。默认 False 时 RBAC / 业务端点全部 fail-closed 返回 `401`（AuthMiddleware 拒绝） |
| JWT 签名密钥 | `APP_AUTH_JWT_SECRET` | `""` | `auth_enabled=true` 时**必填**；HS* 算法要求 ≥ **32 字节**（`core/config.py` 校验，过短 fail-fast）。走 secret 注入，绝不入仓 |
| refresh token pepper | `APP_AUTH_REFRESH_TOKEN_PEPPER` | `""` | 空则 refresh 签发 / 校验 **fail-fast**。独立于 JWT 密钥（泄露隔离），生产必设 |
| access token TTL | `APP_AUTH_ACCESS_TOKEN_TTL_SECONDS` | `1800` | 30 分钟；按安全策略调整（≥ 60） |
| 登录防护 | `APP_AUTH_LOGIN_GUARD_ENABLED` | `False` | **生产强烈建议 `true`**（验证码 + 登录限流）；默认 False 仅便于 dev / 自动化登录 |

### 审计持久化（P2）

| 项 | env | 默认 | 注意 |
|---|---|---|---|
| 审计落库 | `APP_AUDIT_PERSISTENCE_ENABLED` | `True` | 默认开；写 `audit_events` / `login_logs`，operlog/logininfor 查询依赖之 |
| 信任 XFF | `APP_AUDIT_TRUST_X_FORWARDED_FOR` | `False` | **仅当**前置可信反代会覆盖 `X-Forwarded-For` 时才开；裸暴露公网开启会被伪造客户端 IP |

### 定时任务（P4c）

| 项 | env | 默认 | 注意 |
|---|---|---|---|
| 启用调度器 | `APP_SCHEDULER_ENABLED` | `False` | **生产显式开 `true`** 才跑 APScheduler；默认 False（CRUD / 手动触发不依赖调度器）。多 worker / 多 pod 安全靠 **MySQL GET_LOCK leader election + DB execution claim** 双层防重复执行；无需限制副本数 |

### 基础设施超时

| 项 | env | 默认 | 注意 |
|---|---|---|---|
| Redis socket 超时 | `APP_REDIS_SOCKET_TIMEOUT_SECONDS` | `2.0` | idempotency / 缓存监控 / 在线用户派生用；不可达时降级，超时过大会拖慢请求 |

> ⚠️ **数据库迁移 gated**：本地 MySQL 迁移链已可执行到当前 head；生产 / 共享库迁移仍需单独授权。PostgreSQL 历史生产首跑说明见 [RUNBOOK.md](./RUNBOOK.md) 的「迁移 0017 / 0020」节。

## 资源 sizing 建议

| 资源 | 起步 | 注意 |
|---|---|---|
| Pod memory | 256 MiB | Python + uvicorn 单进程；大约 ~150 MiB 占用 |
| Pod CPU | 200m request / 1000m limit | uvicorn **单 worker per pod**（扩容靠 pod 数，见下） |
| DB pool | `APP_DB_POOL_SIZE=5` + `APP_DB_MAX_OVERFLOW=10` | 总 15 连接 per pod，**必须**做容量评估（见下）；MySQL `app_locks` 首次创建动态锁行会短暂借用第二连接，启用 scheduler 时 leader 还会长持 1 条连接 |
| Redis pool | 默认 50（`Redis.from_url` 默认） | idempotency 流量大时调 |

### DB 连接容量评估（必读）

**核心公式**：

```
总连接占用 ≈ (DB_POOL_SIZE + DB_MAX_OVERFLOW) × Pod 数 × worker 数
```

**MySQL 侧硬上限**（必须不超过）：

以目标实例实际 `max_connections` 为准，给本服务预留建议不超过总连接数的 60%，其余留给迁移、
运维、只读查询和应急操作。容量验算口径：

```text
服务连接预算 = floor(max_connections × 0.6)
Pod 数 × worker 数 × (DB_POOL_SIZE + DB_MAX_OVERFLOW) <= 服务连接预算
```

**示例**：默认 `5 + 10 = 15` 连接/pod。HPA 弹到 **10 pod** → 150 连接 → 在 `db.t4g.medium` 上**已逼近上限**且没给其他服务（migrations / Datadog agent / admin tools）留空间。

**对策**（任选）：

1. **调小单 pod pool**：`APP_DB_POOL_SIZE=2` + `APP_DB_MAX_OVERFLOW=4`（10 pod = 60 连接），适合"短查询 + 多请求"型负载
2. **MySQL 连接代理**：优先用云厂商托管连接代理（如 RDS Proxy / 数据库代理）或 ProxySQL / MySQL Router，service 连代理，代理连 RDS。目标是把 1000+ service 连接压成可控后端连接数；不要沿用 PostgreSQL 专用的 PgBouncer。
3. **升 RDS 实例**：成本最高，反应模式

**监控**：CloudWatch / RDS Performance Insights 上看 `DatabaseConnections` 长时间 > 80% `max_connections` 必须告警。

**配套配置**：
- `pool_pre_ping=True`（baseline 已开）—— checkout 前 ping 防 stale connection；额外 `pool_recycle=3600` 可加显式回收，但 pre_ping 已覆盖大多数场景
- async 服务**强制单 worker + 多 pod**（uvicorn `--workers 1` + HPA），**绝不** `--workers N`：
  - 每个 worker 都自己一个 DB pool，乘数失控
  - lifespan `startup_eager_connect` 在 worker fork 后**各自独立跑**——worker 2 的 Redis ping 超时，worker 1 成功，uvicorn 进程 exit code 0，K8s 仍 mark pod ready 后挂了一半流量
  - 单 worker + pod 扩缩容由 HPA 统一管，行为可预测

## Request body 大小限制

**baseline 不在 service 内限制 body size** —— FastAPI / Starlette 默认无上限，恶意客户端可以 POST 1GB body 撑爆 pod 内存。**生产必须**在 ingress 层兜底：

```nginx
# nginx ingress / 内部 LB
client_max_body_size 10m;   # 业务真的需要传大文件时按 endpoint 调高
```

K8s `Ingress` 资源等价配置：

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
```

**为什么不在 service 内做**：每个业务的"合理上限"不同（普通 API 1MB / 文件上传 100MB / 视频上传 1GB+），baseline 不绑死值；ingress 是统一兜底层，超过它的请求根本不进 pod 网络栈，更经济。

**业务真要 per-endpoint 上限**（如 `/upload` 接 100MB，其它接 1MB）：在 endpoint 里读 `request.headers.get("content-length")` 校验后 raise `AppError(..., status_code=413)`。

## 限流（Rate limiting）

**baseline 不在 service 内**——交给 ingress（K8s Ingress / API Gateway / 内部 LB）做"per-IP / per-token" 限流，理由：

1. **正确性**：限流规则全集群一致；service 自限只看到本 pod 流量，HPA 弹 N pod 后总配额 × N，失控
2. **抗 DDoS**：ingress 层在 L7 边缘拦截，service 不浪费 CPU
3. **零代码侵入**：业务模块不引入 `slowapi` / `limits` 等依赖

**业务真要 per-user 限流**（如 free tier 60 req/min）：在 service 内部用 `slowapi` 或自实现 Redis token bucket，**别**自己写中间件做"全局 1000 RPS"——那是 ingress 的事。

## Metrics endpoint（Prometheus）

**baseline 不暴露 `/metrics`**——business 接入时按以下方式自加，不要绕过该路径：

```python
# pyproject.toml dev/runtime
"prometheus-fastapi-instrumentator>=7"

# main.py create_app() 末尾，return app 之前
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
```

**理由**：
- baseline 不绑死监控栈（团队也许换 OTel SDK exporter）
- `/metrics` 不进 OpenAPI（`include_in_schema=False`），不污染 SDK
- Datadog / Prometheus 用同样 endpoint scrape，零迁移成本

**K8s ServiceMonitor**（Prometheus Operator）：

```yaml
spec:
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

## 优雅关闭（Graceful shutdown）

K8s 滚动更新 / 缩容时的 SIGTERM 处理链：

```
K8s preStop hook (sleep 5s)
  → SIGTERM 到 uvicorn (PID 1 是 tini，转发)
  → uvicorn 拒绝新连接 + 等已有 request 完成（最长 30s）
  → ASGI lifespan shutdown 跑（AsyncExitStack 卸载 dispose_engine + redis.aclose）
  → 进程退出 → pod terminated
```

K8s manifest 必配：

```yaml
spec:
  containers:
  - lifecycle:
      preStop:
        exec:
          # 给 ingress 5s 把本 pod 从 endpoints 里摘掉，再开始 drain
          command: ["sh", "-c", "sleep 5"]
  terminationGracePeriodSeconds: 60   # > uvicorn graceful 30s + preStop 5s + 余量
```

**陷阱**：
- `terminationGracePeriodSeconds` 默认 30s，与 uvicorn graceful 默认 30s 撞——K8s 会在 uvicorn 还没完成最后一批请求时 SIGKILL。**必须**显式设 ≥ 60s
- 长事务 / 大文件上传：uvicorn `--timeout-graceful-shutdown 60` + `terminationGracePeriodSeconds 90`
- 没 preStop sleep 时，K8s 把 SIGTERM 和 endpoints 摘除是**并发**做的——新请求仍可能命中正在关闭的 pod

## 部署平台

CI/CD 平台由业务团队按 ADR 决议自选（阿里云效 / Jenkins / GitLab CI 等），模板不指定。CI 参考资产见 [CI_MIGRATION.md](./CI_MIGRATION.md)。

## 安全 checklist

- [ ] `Authorization` header 没记到 access log（middleware 默认未脱敏；如要记其它 header 需手动脱敏）
- [ ] `/readyz` 失败响应**不**含 DSN（`health.py:38` 用 `type(e).__name__` 而非 `str(e)`）
- [ ] `debug=False` 在生产
- [ ] CORS whitelist 显式
- [ ] `Settings.service_id` 已按服务名配置（v0.4.6 加入；JWT `aud` 校验 middleware 待业务接入时对齐，遵守 ADR §5）
- [ ] 跨服务调用必带 `X-Request-ID` 透传 + `Authorization`（如已鉴权）
- [ ] `APP_AUTH_ENABLED=true`（生产；False 时 RBAC / 业务端点全 fail-closed 401）
- [ ] `APP_AUTH_JWT_SECRET` ≥ 32 字节、`APP_AUTH_REFRESH_TOKEN_PEPPER` 非空（均经 secret 注入，不入仓）
- [ ] `APP_AUTH_LOGIN_GUARD_ENABLED=true`（生产；验证码 + 登录限流）
- [ ] `APP_AUDIT_TRUST_X_FORWARDED_FOR` 仅在可信反代覆盖 XFF 时开
- [ ] **【硬要求】pod 端口（8000）仅 ingress / 可信反代可达（NetworkPolicy 隔离）**。Dockerfile 的 `uvicorn --proxy-headers --forwarded-allow-ips *` 让 `request.client.host` 取自 `X-Forwarded-For` —— 登录失败限流（`APP_AUTH_LOGIN_IP_LIMIT`）与审计 IP 均依赖它。**若 pod 端口被直连绕过 ingress，客户端可伪造 XFF 污染审计并按伪造 IP 分桶绕过限流**（`APP_AUDIT_TRUST_X_FORWARDED_FOR=false` 仅控制 app 层是否二次解析 XFF，**挡不住** uvicorn 层已信任的代理头）。生产强约束：要么 NetworkPolicy 锁端口，要么把 `--forwarded-allow-ips` 收窄为可信反代 CIDR（排期：统一 IP 取值 helper + CIDR 注入，见 Codex PK P1.3）
- [ ] `APP_IDEMPOTENCY_LOCK_TTL_SECONDS` ≥ **最慢业务 handler 实际耗时 + 上游重试窗口**（v0.4.9+；默认 30s 适用于秒级 POST。若业务 handler 可达数十秒、外网回调或上游 60s 重试，必须显式调高，否则锁过期后并发重试会绕过 in-flight 保护造成**重复扣款 / 重复创单**。验证：以 P99 handler 延迟为基线，乘以 1.5 ~ 2 倍。）

## 排障

→ [RUNBOOK.md](./RUNBOOK.md)
