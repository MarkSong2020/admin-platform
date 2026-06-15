# 快速开始（部署运行）

> 受众：想把 admin-platform 跑起来的人。从克隆到「登录拿到 access token」一条龙，约 15 分钟。
> 想读代码学架构走 [`ARCHITECTURE_TOUR.md`](./ARCHITECTURE_TOUR.md)；想 Fork 二次开发走 [`USE_AS_SCAFFOLD.md`](./USE_AS_SCAFFOLD.md)。

**最短路径**（细节见下方各节）：

```bash
git clone <repo-url> admin-platform && cd admin-platform
make init                       # 装依赖（uv sync --all-extras --dev）
uv run pre-commit install       # 必须：装 git hook
make compose-up && make migrate # 起 PostgreSQL + 应用迁移
make dev                        # 起服务 → http://127.0.0.1:8000
```

---

## 1. 环境要求

| 工具 | 最低版本 | 说明 |
|---|---|---|
| Python | **3.14**（`pyproject.toml` 的 `requires-python = ">=3.14"`） | 由 uv 管理，不强制系统全局装 |
| uv | 0.9+ | 依赖 / venv / Python 版本一体化管理 |
| PostgreSQL | 16（`make compose-up` 起 `postgres:16-alpine`） | 主数据库；可用本机已有实例替代 |
| Redis | 7.x（可选） | 仅幂等 / 缓存 / 验证码 / 登录限流用，默认 lazy 连，本地不强制起 |
| Docker | 任意现代版本 | 起依赖容器；推荐 OrbStack（Mac） |
| Make | macOS/Linux 自带 | 所有命令入口 |

uv / Docker 的具体安装命令见 [`../operations/LOCAL_SETUP.md`](../operations/LOCAL_SETUP.md)（含 `brew` / 官方脚本）。

## 2. 克隆仓库

```bash
git clone <repo-url> admin-platform
cd admin-platform
```

> 如果目标是 **Fork 来搭自己的后台**（改包名 / service 前缀），先看 [`USE_AS_SCAFFOLD.md`](./USE_AS_SCAFFOLD.md)，别直接在原名上改。

## 3. 安装依赖 + 装 git hook

```bash
make init                  # = uv sync --all-extras --dev（装运行 + dev 依赖）
uv run pre-commit install  # ⚠️ 必须：装 git hook
```

> **`uv run pre-commit install` 不能漏**：`pre-commit` 已随 `make init` 装进 dev 依赖，但 `.pre-commit-config.yaml` 描述的 git hook 必须显式 `install` 才生效。漏装 → 首次 `git commit` 时 ruff-format 会改文件、commit 失败，新人常误以为环境坏了。

## 4. 起依赖容器 + 应用迁移

```bash
make compose-up   # docker compose up -d --wait db（起 PostgreSQL 并等到 healthy）
make migrate      # alembic upgrade head（应用全部 Alembic 迁移）
```

可选：想真测 Redis 相关功能（验证码 / 登录限流 / 幂等）用 `make compose-up-cache` 起 Postgres + Redis（profile=cache）。

> **数据库连接**：默认连 `postgresql+asyncpg://app:app@localhost:5432/app`（与 `make compose-up` 起的容器一致）。要连别的库或开启鉴权，在仓库根建 `.env`（参照 `.env.example`），配置项统一带 `APP_` 前缀（如 `APP_DATABASE_URL`、`APP_AUTH_ENABLED`、`APP_AUTH_JWT_SECRET`）。
>
> ⚠️ 共享库 / 生产库的迁移需单独授权，别对非本地库直接 `make migrate`。

## 5. 起服务

```bash
make dev   # = uv run fastapi dev（hot reload）
```

启动后访问：

- 服务根：<http://127.0.0.1:8000>
- OpenAPI 交互文档：<http://127.0.0.1:8000/docs>

## 6. 验证服务正常

```bash
# liveness：进程活着就返 200（不查依赖）
curl http://127.0.0.1:8000/healthz
# → {"status":"ok"}

# readiness：对 DB 跑 SELECT 1（启用幂等时还 PING Redis），失败返 503
curl http://127.0.0.1:8000/readyz
# → {"status":"ready"}
```

健康检查端点：`GET /healthz`（liveness）、`GET /readyz`（readiness）、`GET /startupz`（startup gate）。再打开 <http://127.0.0.1:8000/docs> 看全部端点的 OpenAPI。

## 7. 创建超级管理员（信任根）

通过一次性管理 CLI 创建。密码**只从环境变量** `ADMIN_BOOTSTRAP_PASSWORD` 读（不进 argv，规避 `ps` / shell history 暴露），要求 **≥ 12 字符**且不等于用户名：

```bash
ADMIN_BOOTSTRAP_PASSWORD='<你的强口令>' \
  uv run python -m admin_platform.cli create-super-admin --username root
# → created super admin: id=1 username=root
```

> 这是 **一次性 bootstrap**：只要库里已存在任意超管就拒绝重复创建（应用层检查 + DB partial unique index 双保险）。
>
> 想初始化内置菜单 / 权限 / 角色（幂等，可重跑）：`uv run python -m admin_platform.cli rbac seed`。

## 8. 登录拿 access token

向登录端点 `POST /api/v1/auth/login` 发用户名 / 密码：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"<你的强口令>"}'
```

成功返回 `LoginResponse`：

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "<opaque>",
  "refresh_expires_in": 604800
}
```

后续带 `Authorization: Bearer <access_token>` 调受保护端点：

```bash
curl http://127.0.0.1:8000/api/v1/users \
  -H 'Authorization: Bearer <access_token>'
```

> 启用了登录防护（`APP_AUTH_LOGIN_GUARD_ENABLED=true` + Redis）时，登录还需带 `captcha_id` / `captcha_answer`，验证码从 `GET /api/v1/auth/captcha` 取。默认 dev 配置（`auth_enabled=false`）不强制。

---

## 下一步

| 想做什么 | 去哪 |
|---|---|
| 完整本地启动 + 跑通 `make check` 全套测试 + 排障 | [`../operations/LOCAL_SETUP.md`](../operations/LOCAL_SETUP.md) |
| 生产部署 + K8s 配置 | [`../operations/DEPLOYMENT.md`](../operations/DEPLOYMENT.md) |
| 加业务模块（必走 `make new-module`） | [`../standards/CODE_GENERATOR.md`](../standards/CODE_GENERATOR.md) |
| 读代码学架构 | [`./ARCHITECTURE_TOUR.md`](./ARCHITECTURE_TOUR.md) |
