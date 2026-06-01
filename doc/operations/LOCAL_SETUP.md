# 本地启动

> 从 0 到能跑通 `make check` 全套测试。30 分钟内搞定。

## 前置条件

| 工具 | 最低版本 | 安装方式 |
|---|---|---|
| Python | 3.14 | `brew install python@3.14` 或 [pyenv](https://github.com/pyenv/pyenv) |
| uv | 0.9+ | `brew install uv` 或 `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | 任意现代版本 | **推荐 OrbStack**（Mac 上 Docker Desktop 替代，更快）：`brew install --cask orbstack` |
| Make | macOS/Linux 自带 | — |

## 克隆 + 改名

```bash
git clone <this-template> myservice && cd myservice

# 1. 改包目录
mv src/service_name src/myservice

# 2. 替换全仓占位（service_name → myservice）
SED_INPLACE="sed -i ''"   # Linux: sed -i
grep -rl "service_name" \
  --include="*.py" --include="*.toml" --include="*.yaml" --include="*.yml" \
  --include="*.ini" --include="*.md" --include="Dockerfile" \
  --exclude-dir=.venv --exclude-dir=.idea --exclude-dir=.claude . \
  | xargs $SED_INPLACE 's/service_name/myservice/g'

# 3. 手动调整（sed 改不到位的）：
#    - pyproject.toml [project].name / description
#    - README.md 标题 / 角色定位
#    - compose.yaml name
#    - .env.example APP_APP_NAME
#    - Dockerfile image tag
```

> **`Settings.service_id`**（ADR §3 / §5 / §8 / §10 服务前缀，用于错误码 / OpenAPI tag / JWT aud / Datadog service tag 同源）的默认值是 `"service_name"`——上面的 sed 命令会自动替换为 `"myservice"`。新服务建仓前需先在 `team-engineering-adr/service-prefix-registry.md` 注册前缀，否则错误码 / 监控 label 会冲突（详见 [../standards/NAMING_CONVENTIONS.md](../standards/NAMING_CONVENTIONS.md)）。

## 四步验证

```bash
make init                       # uv sync --all-extras --dev (装 baseline + dev 依赖)
uv run pre-commit install       # ⚠️ 必须：装 git hook，否则首次 commit 时 ruff/check 会拦着改文件
make check                      # ruff + pyright + pytest（全绿）
make dev                        # http://127.0.0.1:8000/healthz 返回 {"status":"ok"}
```

> **为什么单独列 `pre-commit install`**：`pre-commit` v0.4.17 起入 dev deps（`make init` 会装），但 `.pre-commit-config.yaml` 描述的 git hook 必须显式 `install` 才能生效。漏装 → 首次 commit 时 ruff-format 会改文件、commit 失败，新人误以为环境坏了。

## 接 PostgreSQL（含 ORM model 时必须）

```bash
make compose-up        # docker compose up -d --wait db (postgres:16-alpine, 端口 5432)
make migrate           # alembic upgrade head (应用 baseline)
make check-db          # alembic check (0 drift)
make test-integration  # pytest -m integration（v0.5.3 当前 collect 29 项）
make compose-down      # 停 Docker
```

**`make test-integration` 当前覆盖**（v0.5.3 baseline，跑 `pytest -m integration --collect-only` 自查最新数字）：
- `test_db_smoke.py` 2 项（DB 连通 + transaction commit smoke）
- `test_transaction_commit.py` 3 项（`get_session` 起真事务 / 回滚 / SAVEPOINT）
- `test_todo_db.py` 13 项（含 7 项 todo CRUD + 4 项多对多 E2E + 1 项 N+1 守门 + 1 项 IntegrityError 兜底 race）
- `test_tag_db.py` 6 项（tag CRUD + DUPLICATE 409）
- `test_idempotency_redis.py` 5 项（Redis-backed idempotency E2E，需 Redis 起来）

Redis（idempotency 中间件用）默认 lazy 连——本地开发不强制起。`compose-up`（不带 -cache）只起 Postgres，Redis 相关测试通常跑过去因为 `STRICT_REDIS_INTEGRATION` 默认未设时 redis_integration 标记的测试**会 skip**；要真测就 `make compose-up-cache` 起 Redis + 跑 `uv run pytest -m redis_integration`。

> ⚠️ **改 idempotency 相关代码必须跑 `pytest -m redis_integration`**：本地默认 `make test-integration` 包括 redis_integration 但需要 Redis 起着才不 skip。改 `core/idempotency.py` / 中间件链 / generator POST 模板的 PR 必须先 `make compose-up-cache`，否则 5 个关键 Redis 测试静默 skip 而你以为绿了。
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
| `make compose-up` / `make compose-down` | 启停 PostgreSQL |
| `make compose-up-cache` | 同上 + Redis（profile=cache） |
| `make migrate` | `alembic upgrade head` |
| `make migration name=...` | `alembic revision --autogenerate -m ...` |
| `make check-db` | `alembic check`（schema drift 检测） |
| `make test-integration` | `pytest -m integration` |
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
