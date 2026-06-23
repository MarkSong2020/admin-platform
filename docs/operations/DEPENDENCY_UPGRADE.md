# 依赖升级 Playbook

> 业务从本模板 fork 后，6-12 个月通常需要升级核心依赖（CVE / 新特性 / 上游 EOL）。本文是各核心依赖的升级 caveat + 推荐节奏，避免每个服务团队重新踩坑。

## 升级节奏（推荐）

| Cadence | 范围 | 触发条件 |
|---|---|---|
| **每周** | `make audit`（uvx pip-audit）扫 CVE | CI 已自动跑，发现新 CVE 立即评估 |
| **每月** | `uv lock --upgrade-package <pkg>` 跑次要版本 | 不破坏 API 的 patch/minor 升级 |
| **每季度** | `uv lock --upgrade` 全量 minor 升级 + 跑 `make smoke-generator` | 用 review-meeting 节奏 |
| **每年** | 评估 major 升级（SQLAlchemy / Pydantic / Python 自身） | 用 ADR 形式记录决策 |

## 核心依赖逐项 caveat

### `fastapi`

- **0.x 阶段**：minor 升级可能 breaking（FastAPI 自己不承诺 SemVer）。看 release notes 找 "Breaking Changes" 段
- **常见踩坑**：`include_in_schema=False` 行为、`responses=` 字段合并语义、`@app.exception_handler` 注册顺序
- **测试守门**：`tests/unit/test_openapi_contract.py` 4 项 + `tests/unit/test_new_module.py` generator 模板套件
- **回滚方案**：`uv.lock` 单独 pin：`uv add 'fastapi==<旧版>'`

### `starlette`

- FastAPI 强依赖，通常被动升
- **本模板已知坑**：`BaseHTTPMiddleware` 实现细节（见 KNOWN_DEVIATIONS #13）；任何涉及 `request._receive` 重写的 starlette 改动必须先看 deviation
- 升级前 grep `BaseHTTPMiddleware\|request._receive`，若 starlette release notes 提这两个就**立即停**

### `pydantic` + `pydantic-settings`

- **v1 → v2**：完全 breaking（迁移指南：<https://docs.pydantic.dev/latest/migration/>）。本模板已是 v2 baseline
- **v2 内部 minor**：`model_config = ConfigDict(...)` 字段、`@field_validator` / `@model_validator` 签名偶有调整
- **测试守门**：`tests/unit/test_config.py` 22 项 + generator 模板 schemas

### `sqlalchemy`

- **2.x → 2.x**：稳定，按 release notes 升即可
- **典型踩坑**：`Mapped[]` typed-mapping 严格性提升、`session.begin()` 与隐式事务的交互、`select(Model).filter_by()` 行为
- **测试守门**：`make check`；涉及 DB 行为时补 `make check-db` 和本地 MySQL smoke
- **升级前必跑**：`make check`；涉及 DB 行为时补 MySQL smoke

### `alembic`

- 跟 SQLAlchemy 同步升
- **风险点**：`compare_server_default=True`（已开）跨大版本可能 false-positive 漂移
- **守门**：`alembic check` 必跑

### `asyncmy`

- 稳定，跟着 SQLAlchemy 升即可
- **典型踩坑**：MySQL 认证插件（`caching_sha2_password` 需要 `cryptography`）、SSL 配置 schema 变化、连接断开后的 pool 回收

### `redis-py`

- **当前 floor `>=7.4`**（v0.4.22 起；5.x/6.x 在 lockfile 解析阶段就会被拒）
- `redis.asyncio` 7.x API 稳定（5.x → 7.x 的 import 路径 / `from_url(...)` 签名向后兼容；本模板 `tests/integration/test_idempotency_redis.py` 5 项实测通过）
- **风险点**：`from_url(...)` 参数（connection pool sizing）、`decode_responses=False` 默认行为
- **升级守门**：必跑 `APP_TEST_DB_ALLOW_DESTRUCTIVE=1 STRICT_REDIS_INTEGRATION=1 uv run pytest -m redis_integration`

### `argon2-cffi`（密码哈希）

- **当前 floor `>=25,<26`**（P0 多租户鉴权地基新增的唯一 runtime 依赖）。MIT，Production/Stable，PyCA 风格活跃维护，25.1.0 官方支持 Python 3.13/3.14
- **算法 = Argon2id**（ADR-F，见 `docs/specs/2026-06-02-p0-multitenant-auth-foundation.md`）。`PasswordHasher()` 默认参数：`m=65536 KiB(64 MiB) / t=3 / p=4 / hash_len=32 / salt_len=16`，强于 OWASP 最低线，对后台管理系统的低登录并发是合适的
- **intake 决策（依赖偏离记录）**：v3 plan 原写 `passlib[bcrypt]` → intake 核验否决（passlib 1.7.4 停在 2020、Python 3.14 已移除其依赖的 `crypt` 模块、bcrypt≥4 启动警告）→ 评估直连 `bcrypt` → **最终选 Argon2id**。理由：greenfield 零迁移成本 + admin 低登录并发使 memory-hard 的内存成本非瓶颈 + OWASP 密码存储首选 + 无 bcrypt 72-byte 输入限制 + `PasswordHasher` API 更难写错（自带盐管理 / `check_needs_rehash`）
- **运维 caveat**：每次 `verify`/`hash` 约消耗 `memory_cost` 内存（默认 64 MiB）。调大 `memory_cost` 前**必须**压测登录并发峰值 × 单次内存，写进 DEPLOYMENT.md 容量规划
- **参数演进**：调参后用 `ph.check_needs_rehash(stored_hash)` 在用户下次登录时透明 rehash，不需要批量迁移
- **已知噪声**：`argon2.__version__` 已 deprecated，查版本用 `importlib.metadata.version("argon2-cffi")`，不要在代码里读 `__version__`

### `uvicorn`

- **生产参数变化**：`--proxy-headers --forwarded-allow-ips` 配置近年迭代多
- **本模板 Dockerfile CMD 已显式写参数**，升 uvicorn 后检查这些 flag 是否仍受支持
- **lifespan 协议**：v0.30+ 已稳定 ASGI lifespan v2

### `ruff` / `pyright`

- 工具链，升级后 lint 规则可能变严
- **节奏**：每月按需升，看是否要 fix 新 warnings；不要凭"无新错误"心理跳过
- **新规则 opt-in**：本模板 `pyproject.toml [tool.ruff.lint].select` 已锁定规则集，升 ruff 不自动启用新规则

### `import-linter`

- **新增 intake（2026-06-03）**：dev-only，为 `make check-layer-boundaries` 提供分层 import 契约（C1–C7，见 `.importlinter`）。核验：v2.11 最新、David Seddon 维护、py3.14 wheel 可用、`uv run lint-imports` 项目内跑通
- **传递依赖**：拉 `grimp`（同作者的 import-graph 引擎，含预编译 rust 扩展，有 wheel）
- **当前 pin**：`import-linter>=2.11,<3`
- **当前裁剪**：C1（domain layers）暂注释 —— 业务域 tenant/user 仅有 `models.py`，未长出 api/service/repository 三层，`layers` 契约会报 "module not found"。补齐三层后填入 C1 `containers` 再启用；C2–C7 已生效
- **典型踩坑**：大版本可能调整 `[importlinter:contract:*]` 配置 schema / module 通配语法（`admin_platform.domains.*.api`）；升级后必跑 `uv run lint-imports` 确认契约仍 `kept`
- **守门**：`make check-layer-boundaries`（lint-imports）

### `pytest` + 插件

- **当前 floor**：`pytest>=9` / `pytest-asyncio>=1.3` / `pytest-cov>=7` / `pytest-mock>=3.15`（v0.4.22 起；`pytest-asyncio` 从 0.x 系列跨 major 到 1.x，`asyncio_mode = "auto"` 在 1.x 下行为不变）
- **常见踩坑**：fixture scope 行为、`--strict-markers` 严格性、`asyncio_mode` 默认值

### Python 自身（CPython）

- 本模板硬 floor `>=3.14`（v0.4.19 起）
- **升 3.14 → 3.15**：等 3.15 GA 6 个月以上 + 主流依赖（FastAPI/Pydantic/SQLAlchemy）都标 classifier `Programming Language :: Python :: 3.15` 后再考虑
- 升级流程参考 v0.4.19 commit message + CHANGELOG

### `uv`

- Astral 维护，迭代快
- **本模板 pin 在 `uv-version: 0.9.30`**（CI + Dockerfile 一致）
- 升 uv 时先在 scratch 跑 `uv sync --frozen` 看 lockfile 是否兼容；不兼容时同时升 lockfile

## 升级流程（标准 SOP）

```bash
# 1. fork 一个升级分支
git checkout -b deps/upgrade-q2-2026

# 2. 升单个包（先 minor 后 major）
uv lock --upgrade-package fastapi
uv lock --upgrade-package pydantic
# 或全量
uv lock --upgrade

# 3. 装新依赖
uv sync --all-extras --dev --frozen

# 4. 跑完整守门套件
make check                # 单测 + lint + type
# make compose-up-cache
# make migrate
# make check-db
# make test-integration
# APP_TEST_DB_ALLOW_DESTRUCTIVE=1 STRICT_REDIS_INTEGRATION=1 uv run pytest -m redis_integration
make smoke-generator      # generator 模板还能跑通
make audit                # 没新 CVE

# 5. 看 release notes 找 breaking changes（特别是 fastapi / starlette / sqlalchemy / pydantic）
# 6. 改代码适配 + 加守门测试
# 7. PR 描述写"升了哪些 + 跑了什么 + 还剩什么风险"
```

## 出现 CVE 后的最短路径

```bash
# 1. 看影响范围
uvx pip-audit . --format json | jq '.vulnerabilities[] | {name, id, fix_versions}'

# 2. 单包升到含修复的版本
uv lock --upgrade-package <vuln_pkg>

# 3. 走标准 SOP 第 3-7 步

# 4. 紧急例外（修复版本未出/破坏性变更）：
uvx pip-audit . --ignore-vuln <CVE-ID>
# 在 PR 描述写 owner + 解除时间，例外清单每周 review（见 CI_MIGRATION.md §4）
```

## 跨服务协同

业务团队若维护多个基于本模板的服务，建议：

1. **共享升级日历**：季度同步升一次，集中处理 breaking changes
2. **首个服务做 trailblazer**：选一个流量小的服务先升，验证 1-2 周再推其它
3. **升级 ADR 沉淀**：每次 major 升级（如未来 SA 3.x / Pydantic 3.x）写一份 ADR 记录决策 + 适配 patch

## 模板本身的升级

业务团队 fork 后，**模板自身**也会 release 新版本（看 [CHANGELOG.md](../../CHANGELOG.md)）。

- 模板里程碑版本和业务实例独立维护
- 业务可参考 `git log` 拉模板的 diff cherry-pick，但不必每次都跟 — 看是否涉及业务关心的 fix / feature
- 模板出 P0（如 v0.4.18 修的错误码 bug）必须广播到所有 fork 业务

完整模板演进 → [`../../CHANGELOG.md`](../../CHANGELOG.md)。
