# 本地启动

> 从 0 到能跑通 `make check` 全套测试。30 分钟内搞定。

## 前置条件

| 工具 | 最低版本 | 安装方式 |
|---|---|---|
| Python | 3.14 | `brew install python@3.14` 或 [pyenv](https://github.com/pyenv/pyenv) |
| uv | 0.9+ | `brew install uv` 或 `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | 任意现代版本 | **推荐 OrbStack**（Mac 上 Docker Desktop 替代，更快）：`brew install --cask orbstack` |
| Make | macOS/Linux 自带 | — |

## 克隆

```bash
git clone https://github.com/MarkSong2020/admin-platform.git && cd admin-platform
```

> 想 **fork 当脚手架、改造成自己的后台**（换包名 / 品牌、长自己的业务域）？看 [../guide/USE_AS_SCAFFOLD.md](../guide/USE_AS_SCAFFOLD.md)。本仓是开箱即用的派生**应用**——源码包已经是 `src/admin_platform`，直接跑下面四步即可，无需任何模板占位符替换。

## 四步验证

```bash
make init                       # uv sync --all-extras --dev (装 baseline + dev 依赖)
uv run pre-commit install       # ⚠️ 必须：装 git hook，否则首次 commit 时 ruff/check 会拦着改文件
make check                      # ruff + pyright + pytest（全绿）
make dev                        # http://127.0.0.1:8000/healthz 返回 {"status":"ok"}
```

> **为什么单独列 `pre-commit install`**：`pre-commit` v0.4.17 起入 dev deps（`make init` 会装），但 `.pre-commit-config.yaml` 描述的 git hook 必须显式 `install` 才能生效。漏装 → 首次 commit 时 ruff-format 会改文件、commit 失败，新人误以为环境坏了。

## 接 MySQL

```bash
make compose-up        # docker compose up -d --wait db (mysql:8.0, 端口 3306)
make migrate           # 本地 MySQL 执行 Alembic 迁移（生产/共享库仍需单独授权）
make check-db          # schema drift 检测
APP_TEST_DB_ALLOW_DESTRUCTIVE=1 make test-integration   # MySQL 集成测试，会 TRUNCATE disposable 测试库
make compose-down      # 停 Docker
```

MySQL schema 必须使用 `utf8mb4_0900_bin` 默认 collation（保留 PostgreSQL 的大小写敏感
unique / CHECK 语义）；`compose.yaml` 已配置新建 volume 的默认值。若旧本地 volume 是迁移前
创建的，`make migrate` 会在 Alembic 入口报错；确认是 disposable dev 库后再执行
`docker compose down -v` 重建。

迁移链还会创建 `depts` / `menus` 的 self-parent 防护 trigger。若 MySQL 开启 binary logging，
实例参数必须设置 `log_bin_trust_function_creators=1`；本地 `compose.yaml` 已配置，生产/共享库
由 DBA 在迁移窗口前设置，Alembic 入口会提前校验。

若本机 3306 已被占用，或 Docker/OrbStack 的 3306 发布端口行为异常，可显式换端口：

```bash
MYSQL_HOST_PORT=13306 make compose-up
APP_DATABASE_URL=mysql+aiomysql://app:app@127.0.0.1:13306/app make migrate
APP_DATABASE_URL=mysql+aiomysql://app:app@127.0.0.1:13306/app APP_TEST_DB_ALLOW_DESTRUCTIVE=1 make test-integration
```

**`make test-integration` 覆盖**（示例域 todo/tag 已删，跑 `pytest -m integration --collect-only` 自查最新数字）：
- `test_db_smoke.py` 2 项（DB 连通 + transaction commit smoke）
- `test_transaction_commit.py` 3 项（`get_session` 起真事务 / 回滚 / SAVEPOINT）
- `test_idempotency_redis.py` 5 项（Redis-backed idempotency E2E，需 Redis 起来）

Redis（idempotency 中间件 / 缓存监控用）默认 lazy 连——本地开发不强制起。`compose-up`（不带 -cache）只起 MySQL，Redis 相关测试通常跑过去因为 `STRICT_REDIS_INTEGRATION` 默认未设时 `redis_integration` 标记的测试**会 skip**；要真测就 `make compose-up-cache` 起 Redis + 跑 `APP_TEST_DB_ALLOW_DESTRUCTIVE=1 uv run pytest -m redis_integration`。

> ⚠️ **改 idempotency / 缓存监控相关代码必须跑 `APP_TEST_DB_ALLOW_DESTRUCTIVE=1 uv run pytest -m redis_integration`**：本地默认 `make test-integration` 包括 `redis_integration` 但需要 Redis 起着才不 skip。改 `core/idempotency.py` / 中间件链 / generator POST 模板 / `domains/monitor` 缓存采集的 PR 必须先 `make compose-up-cache`，否则关键 Redis 测试静默 skip 而你以为绿了。
>
> CI 自动设 `STRICT_REDIS_INTEGRATION=1`——Redis 不可达时把 skip 强转 fail，避免线上跑了但日志被忽略。

## 命令速查

| Make target | 作用 |
|---|---|
| `make help` | 列全部 target |
| `make init` | `uv sync --all-extras --dev` |
| `make dev` | `uv run fastapi dev`（hot reload） |
| `make check` | ruff + pyright + pytest（排除 integration） |
| `make audit` | `uvx pip-audit`（依赖漏洞扫描） |
| `make new-module name=order [with-model=1] [plural=...] [dry-run=1] [force=1]` | 生成业务模块（[CODE_GENERATOR.md](../standards/CODE_GENERATOR.md)） |
| `make compose-up` / `make compose-down` | 启停 MySQL |
| `make compose-up-cache` | 同上 + Redis（profile=cache） |
| `make migrate` | `alembic upgrade head`（生产/共享库仍需单独授权） |
| `make migration name=...` | `alembic revision --autogenerate -m ...` |
| `make check-db` | `alembic check`（schema drift 检测） |
| `make test-integration` | `pytest -m integration`（MySQL 集成测试） |
| `make docker-build` | 多阶段 Dockerfile build |
| `make format` / `make format-files` | ruff format 全仓 / 指定文件 |
| `make lint` / `make typecheck` | ruff check / pyright |

## AI Agent 视角下的常见误判

> 这段写给会读本仓的 LLM agent（Claude Code / Codex / Cursor / Cline 等）。
> 防止下一轮 review 把"工具沙盒拦截"误报成"仓库 bug"。

**`.env*` 在 agent 工具沙盒下不可读** —— 这是 **Claude Code / Codex / Cursor 等的默认安全策略**，
不是工作区文件损坏或权限问题。表现：

- `git status --short` / `git diff --stat` 输出 `.env.example: Operation not permitted`
- `Read` / `cat` / `sed` 直接对 `.env*` 也报权限错
- 但 **`git show HEAD:.env.example`** 能正常输出仓库对象内容（说明仓库是健康的）
- 用户在普通终端 `cat .env.example` 也完全正常

**因此**：reviewer agent 看到 `.env.example: Operation not permitted` 时不要再写进 finding，
这是工具层安全设计而非项目 bug。如果真要确认文件内容，用 `git show HEAD:.env.example`。

## 排障

碰到问题先看 [RUNBOOK.md](./RUNBOOK.md)。

## 相关文档

- 改名 + 加业务模块的下一步 → [../standards/CODE_GENERATOR.md](../standards/CODE_GENERATOR.md)
- 部署 + K8s 配置 → [DEPLOYMENT.md](./DEPLOYMENT.md)
- CI 平台（业务团队自选） → [CI_MIGRATION.md](./CI_MIGRATION.md)
