# 版本演进时间线

> v0.1（initial scaffold）→ v0.4.5（知识库重组）。每个版本一个 commit，可 `git log` 追溯。

## 路线图（4 步全部完成）

按 `1 → 2 → 4 → 3` 实施顺序：

| Step | 产出 | 状态 |
|---|---|---|
| 1 | 全局规范更新（`~/.claude/CLAUDE.md` + `rules/python.md`） | ✅ Step 1 完成 |
| 2 | 生成器 + AI 协作层 | ✅ 完成（`scripts/new_module.py` + 30 单测） |
| 3 | 脚手架骨架 MVP（Phase A/B/C/D） | ✅ 完成 |
| 4 | 跨语言协同 ADR | ✅ 完成（独立仓 `~/IdeaProjects/team-engineering-adr/`） |

## 版本演进

### v0.1 — `05f9e26` — Initial scaffold（2026-05-13/14）

- FastAPI 5 层分层结构 + uv 包管理 + ruff + pyright + pytest
- SQLAlchemy 2.x async + Alembic + asyncpg
- docker-compose PostgreSQL + 多阶段 Dockerfile
- 7 条 Codex errata 已固化
- Generator `scripts/new_module.py` + 30 单测
- ADR 0001 cross-language baseline 入仓

### v0.3 — `989922b` — fellow agent 9 项 review 修订

- §1 `instance` → null（不再 = `request_id`）
- §3 `{service}.{ERROR_CODE}` 措辞松绑
- §4 X-Request-ID 强制 32-char hex
- §7.5 cursor 分页 shape 强制统一
- §9 log level 强制 4-char `WARN`
- §11 重试触发白名单
- AppError API breaking change → `(code, title, *, detail=None, status_code=400, errors=None)`
- Java follow-up 扩到 11 项
- ADR Adoption status 加治理段

### v0.3.1 — `ae65680` — 第三轮 review 修复（4 项 + 2 测试 gap）

- ADR Revision history v0.3 段 AppError 签名语法非法 → 加 `*` keyword-only
- `middleware.py` 加 OTel TODO 锚点
- `generator-design.md` §5.4 加 §7.5 偏差提示
- 新增 X-Request-ID hex 格式断言（`test_health.py`）
- 新增 `JsonFormatter` level=WARN 守门（`test_logging.py` 4 项）

### v0.3.2 — `f700886` — 第四轮 review（12 项 finding）

代码 bug 修复：
- `logging.py` timestamp 微秒+offset → 毫秒+Z
- `errors.py` `framework.HTTP_<n>` → 显式映射表（16 项）
- `health.py` `str(e)` → `type(e).__name__`（防 DSN 泄露）
- `middleware.py` access log 入 finally 块
- `new_module.py` `_exit` 改 `NoReturn`

breaking：
- X-Request-ID 入站 regex 校验（不合法时丢弃 + 重生成）

ADR 治理：
- §1 加 CORS preflight transport-level 说明 + 字段顺序非强制
- §5 `aud` 锁定 = `Settings.service_id`
- §11 timeout 默认值陷阱

### v0.3.3 — `f73d803` — 第五轮 review（OpenAPI + CI 平台）

- ProblemDetail Pydantic model + `_custom_openapi` 全局注入（B-1）
- ADR §8 基础设施 endpoint 豁免（B-2）
- CI 平台澄清：阿里云效 + Jenkins；`.github/workflows/ci.yml` 标 reference-only
- 新建 `docs/operations/CI_MIGRATION.md`
- 依赖审计 56 包 0 CVE

### `5e7175a` — ADR Python follow-up #5 drop（文档漂移修正）

- ADR Adoption status `Implemented` → `Partially Implemented` 后用户基于 fellow #1 误判固化的 follow-up #5 删除（v0.3 起 errors.py 已重构，与 entry 矛盾）

### `6d5c7e1` — ADR 迁出本仓

- `docs/adr/0001-*.md` 迁到 `~/IdeaProjects/team-engineering-adr/`
- 本仓 `docs/adr/README.md` 留 stub
- 5 处引用全部更新到新路径

### v0.4 — `84f76f7` — 分页 envelope（Python follow-up #1）

- generator 模板加 `{Name}Page` Pydantic envelope
- repository `list_paginated` + `count`
- service `list_(page, size)` 返回 envelope
- API 用 `Query(ge=1, le=100)` 守门
- ADR §7.5 Python 端落地标记翻转

### v0.4.1 — `bffb0ae` — W3C traceparent 解析（Python follow-up #3）

- `middleware.py` `_resolve_ids` 优先级：traceparent > X-Request-ID > 自生成
- `request.state.trace_id` 注入
- `logging.py` `_EXTRA_FIELDS` 加 `trace_id`
- 5 项新测试（access log）

### v0.4.2 — `20a5658` — mako import 修复（D Migration 端到端发现）

- `migrations/script.py.mako` 加 `import sqlalchemy as sa` + `from alembic import op`
- **关键 bug**：6 轮 review 都没抓到，**只有真跑 alembic 才暴露**

### v0.4.3 — `125e484` — Idempotency-Key middleware（Python follow-up #2）

- 解 ADR Open Q7：Redis 后端 + endpoint opt-in + 24h TTL + Stripe-style cached replay
- `core/idempotency.py` 新建（IdempotencyStore Protocol / RedisIdempotencyStore / `@idempotent` 装饰器 / IdempotencyMiddleware）
- `pyproject.toml` 加 `redis[hiredis]>=5.0`
- `Settings` 加 3 项配置
- 8 项新测试

### v0.4.4 — `62aefba` — `/startupz` 端点（Python follow-up #4）

- 解 ADR Open Q8：基础设施豁免命名（startupz 不走 `{plural}_{action}`）+ K8s startupProbe 配置 yaml
- `api/v1/health.py` 加 `/startupz`
- 1 项新测试

**至此 4 个 Python follow-up 全部完成**。

### v0.4.5 — 知识库重组（仿 shopsell-server）

- `docs/` → `doc/` 七目录骨架
- 新增 13 文档（INDEX / PROJECT_OVERVIEW / architecture×5 / standards×3 / operations×4 / reference×2 / tech-debt×2 / archive×2）
- 第 6 轮 review 6 项 finding 全部记入 `tech-debt/KNOWN_DEVIATIONS.md`
- 修 5 份文档 drift（README / CLAUDE.md / AGENTS.md / generator-design 迁 / ai-coding-rules 迁）
- ADR Adoption status 同步到 v0.4.4 Implemented

### v0.4.6 → v0.4.22 — 自审密集期（2026-05-15 ~ 2026-05-17）

22 个版本号 17 个是「自审 close」式 bump（v0.5.0 起改两层版本号语义，本段保留作为历史记号）。逐版详情看 [CHANGELOG.md](../../CHANGELOG.md)；下面只列关键技术决策：

- **v0.4.9**：Idempotency-Key 引入 SET NX in-flight 锁（解 ADR Open Q7，Stripe 风格 24h cache replay）
- **v0.4.11 P0**：`get_session` 真起 transaction —— 此前 service 只 `flush()` 不 commit，每次写都被静默回滚。这是模板的 P0 修复
- **v0.4.13**：422 validation `input` 字段框架级脱敏（防 password / token / PII 经 422 body 泄露）+ generator 自动 patch `migrations/env.py`
- **v0.4.14 边界硬化**：uvicorn `--proxy-headers --forwarded-allow-ips --no-access-log` / Idempotency-Key 长度 255 上限 / Settings `Field(ge/le)` + URL scheme 校验 / OpenAPI `bearerAuth` 占位
- **v0.4.16**：`make smoke-generator` E2E 烟测落地（generator + `make check` + cleanup）—— v0.5.0 这套机制就抓到 3 个真 bug
- **v0.4.17**：四处文档版本统一守门（`test_version_consistency.py` 出现）/ `pre-commit` 入 dev deps / generator POST 400/409/422 + PATCH 404/422 显式声明
- **v0.4.18**：修 v0.4.17 杜撰错误码 + framework.* 字面量 grep 守门 / `@idempotent` 装饰器顺序陷阱文档+测试
- **v0.4.19**：Python 3.13 → 3.14 硬升 floor（`requires-python = ">=3.14"`，已有 3.13 业务 fork 模板会失败）
- **v0.4.20**：`pre-commit install` 进 onboarding 四步 / `STRICT_REDIS_INTEGRATION=1` fail-not-skip / `examples/k8s/deployment.yaml` 完整 manifest
- **v0.4.21 实测路径**：第九轮 review 用真跑代码（不靠 grep）抓到 503 路径漏 X-Request-ID 头 + `/readyz` `responses=` 漏 503 ProblemDetail。**关键洞察：前 8 轮 grep 抓不到**
- **v0.4.22 依赖全量刷新**：`uv lock --upgrade` + `pyproject.toml` floor 全部跟齐 lockfile minor（redis 5→7.4 / pytest 8→9 / pytest-asyncio 0→1.3 / pre-commit 3→4 等），避免业务 fork 后 `uv add` 解析到守门未覆盖的旧版

### v0.5.0 — example domain 落地（2026-05-18）— 模板可用性 milestone

模板从「A+ 基础设施 + 空 domains」骨架，升级为「5 分钟跑通完整 CRUD」可用模板：

- 新增 example domain `todo`：5 domain 文件 + 13 测试 + Alembic migration 0002
- generator 默认骨架字段扩展（`title` UniqueConstraint + `status: StrEnum` + `due_at: Optional`）+ title 唯一性业务规则（409 `service_name.TODO_TITLE_DUPLICATE`）
- 新增 `docs/architecture/EXAMPLE_DOMAIN.md` 解释每一行选择的理由
- `docs/INDEX.md` 加「🚀 5 分钟新手路径」
- `main.py` 挂载 `todo_router` 开箱即用
- CHANGELOG 头部加「版本号语义」段：**v0.5.0 起停止"自审 close"式 bump**，模板里程碑（`vX.Y.Z`）与自审 build（`vX.Y.Z-audit.N` git tag）分离
- v0.5.0 release 后跑 `make smoke-generator` 抓到 3 个真 bug（multi-patch alembic env.py I001 / env.py 需要 `isort: skip_file` / `Enum.create(checkfirst=True)` 在 async DDL 失效）—— 全部已修
- **post-release reality check**：原计划 v0.5.1 重写两个 middleware 关闭 #11/#12/#13 —— 重读 KNOWN_DEVIATIONS 后**撤回**（每条自己已经定「触发条件未到不修」，提前重写 = 完美主义陷阱）

### v0.5.1 — 第二个 example domain + 多 domain 关联（2026-05-18）

业务团队第一个真实 PR 通常涉及跨 domain 关联模式，单 domain 蓝本没正面例子可对照：

- 新增 `tag` domain（独立 CRUD + name UniqueConstraint + service 层 `TAG_NAME_DUPLICATE` 409 预检）
- todo ↔ tag 多对多通过 Core `Table` 关联表 + FK `ON DELETE CASCADE`
- `Todo.tags: Mapped[list[Tag]] = relationship(secondary=todo_tags, lazy="raise")` —— 任何忘记 `selectinload(Todo.tags)` 的代码会抛 `StatementError`（N+1 防御）
- repository 所有读路径自动用 `selectinload(Todo.tags)` 预加载
- 跨 domain 持有 repository（不是 service）：`TodoService(todo_repo, tag_repo)` 保持依赖方向无环
- 新增 `TODO_TAG_NOT_FOUND` 422（all-or-nothing 引用检查，拒绝悄悄关联存在子集）
- migration 0003 + N+1 守门测试（SQLAlchemy `before_execute` event hook 数 SELECT）
- EXAMPLE_DOMAIN.md 加「多 domain 关联模式」章节
- **v0.5.1 新代码 docstring/comments 中文化**（用户 reality check 后落地，AI_CODING_RULES.md §0 固化「默认简体中文」红线，pyproject.toml ignore RUF001/002/003 接受中文全角标点）
- 修 GHA 抓到的 alembic drift：`todo_tags` Table 缺 `Index` 声明对齐 migration 0003

### v0.5.2 — 既有代码全量中文化（2026-05-18）

v0.5.1 的 docstring 中文化只覆盖 v0.5.1 新加 / 修改的代码。`scripts/new_module.py` generator 模板 + `core/*` + `db/*` + `api/v1/health.py` 仍是英文 —— 业务团队 `make new-module` 生成出来的代码也跟着英文。

v0.5.2 清掉这部分基础设施债 —— 翻译 ~2100 行 docstring：

- `scripts/new_module.py`（1028 行）：所有 `TEMPLATE_*` 字符串内 docstring + `_patch_alembic_env` 等核心函数 docstring。保留 placeholder（`{name}` `{Name}` `{NAME_UPPER}` 等）+ 错误码字面量 + CLI `argparse` help（user-facing 英文契约）原貌
- `core/idempotency.py`（392 行）+ `core/errors.py`（237 行）+ `core/config.py`（125 行）+ `core/middleware.py`（121 行）+ `core/logging.py`（68 行）
- `db/base.py` / `db/engine.py` / `db/session.py`（114 行总）
- `api/v1/health.py`（93 行）

**业务影响**：v0.5.2 起 `make new-module name=ledger` 生成出来的 domain 代码 docstring **直接是中文** —— 不需要业务团队手工补翻。

至此**模板内所有代码 docstring 一致简体中文**，AI_CODING_RULES.md §0 的「v0.5.1 之前残留」过渡说明已删除。

## 关键决策时间线

| 日期 | 决策 | commit |
|---|---|---|
| 2026-05-13 | 选 FastAPI + uv 而非 Django + pip | initial |
| 2026-05-14 | 错误响应 RFC 9457-aligned 字段命名（非完全 problem+json） | v0.3 |
| 2026-05-14 | AppError API breaking — `code, title, *, detail, status_code, errors` | v0.3 |
| 2026-05-14 | X-Request-ID 强制 32-char hex（OTel 接入零跳变） | v0.3 |
| 2026-05-14 | X-Request-ID 入站**校验**（不合法丢弃重生）| v0.3.2 |
| 2026-05-14 | ADR 迁出本仓到团队级独立位置 | `6d5c7e1` |
| 2026-05-15 | Idempotency 选 Redis + Stripe 风格 cached replay | v0.4.3 |
| 2026-05-15 | OTel 接入选**轻量**（仅 parse traceparent，不装 SDK） | v0.4.1 |
| 2026-05-15 | startupProbe 强制（K8s manifest yaml 入 ADR §6） | v0.4.4 |
| 2026-05-15 | 知识库仿 shopsell-server doc/ 七目录 | v0.4.5 |
| 2026-05-16 | Idempotency-Key 引入 SET NX in-flight 锁 + 24h cache replay | v0.4.9 |
| 2026-05-16 | `get_session` 真起 transaction（P0 修复） | v0.4.11 |
| 2026-05-17 | Python 3.13 → 3.14 硬升 floor（`requires-python = ">=3.14"`） | v0.4.19 |
| 2026-05-17 | 自审密集期结束，依赖全量刷新 + floor 跟齐 lockfile | v0.4.22 |
| 2026-05-18 | example domain `todo` 落地；CHANGELOG 加「版本号语义」段（milestone vs audit-build） | v0.5.0 |
| 2026-05-18 | KNOWN_DEVIATIONS reality check：触发条件未到不主动重写（撤回 v0.5.1 middleware 重写计划） | v0.5.0 post-release |
| 2026-05-18 | 第二个 example domain `tag` + todo↔tag 多对多 + N+1 守门 | v0.5.1 |
| 2026-05-18 | 代码 docstring 默认简体中文（AI_CODING_RULES.md §0 红线） | v0.5.1 / v0.5.2 |

## 测试数演进

| 版本 | unit + api | integration | 备注 |
|---|---|---|---|
| v0.1 | 18 | — | initial |
| v0.3 | 18 | — | |
| v0.3.1 | 23 | — | +1 hex + 4 logging |
| v0.3.3 | 26 | — | +3 OpenAPI contract |
| v0.4 | 26 | — | +分页 envelope（生成 order+product 后 38） |
| v0.4.1 | 31 | — | +5 traceparent |
| v0.4.3 | 39 | — | +8 idempotency |
| v0.4.4 | 40 | — | +1 startupz |
| v0.4.x baseline | 72 | — | 含 generator 自身 30 测试 |
| v0.4.11 | — | 3 | transaction_commit integration |
| v0.4.12+ | — | 10 | + db_smoke / idempotency_redis |
| v0.5.0 | 134 | 17 | +todo example（unit 8 / api 5 + integration 7） |
| v0.5.1 | 153 | 28 | +tag domain（unit 8 / api 5）+ todo tag-related（unit 5）+ tag CRUD integration 6 + 多对多 E2E 4 + N+1 守门 1 |
| v0.5.2 | 153 | 28 | 仅 docstring 翻译，测试数不变 |
| v0.5.2-audit.3 | 157 | 29 | +4 IntegrityError handler 单元测试（coverage 83.11%→85.70%） |
| v0.5.3 | 189 | 29 | JWT Bearer 鉴权 + OTel SDK（ADR §4/§5）+ 27 条新测试（coverage 87.19%） |

**当前 baseline（v0.5.3）**：unit + api 189 / integration 29 = 总 218 ✓

## 引用

- 详细每轮 finding → [REVIEW_HISTORY.md](./REVIEW_HISTORY.md)
- ADR Revision history → `~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`
