# python-web-service-template — 项目指引（给 Claude Code）

> 项目级 AI 上下文。全局规范在 `~/.claude/CLAUDE.md` 和 `~/.claude/rules/python.md`，**不要重复**。

## 仓库角色

团队 Python Web 服务脚手架模板（FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Ruff + Pytest）。**当选定 Python 作为后端栈后**，新建 API / 微服务的起点。

> 跨栈选型决策不在本仓口径——见 `~/.claude/CLAUDE.md` 的「技术栈」段（按需求选型，不预设默认）。

## 完整文档

**所有技术内容**都在 `doc/`，**不要**在本文件重复：

→ [`doc/INDEX.md`](./doc/INDEX.md)（按角色导航）
→ [`doc/PROJECT_OVERVIEW.md`](./doc/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.5.3）

`make check` 189 ✓ / `make test-integration` 29 selected ✓ / `make smoke-generator` ✓ / `make coverage` 门槛 85%（`fail_under = 85`，实测 ~87.19%）。

**v0.5.x milestone 浓缩**（v0.4.x 完整 list 见 CHANGELOG）：

| 版本 | 主要价值 |
|---|---|
| v0.5.0 | example domain `todo` 落地 — 5 分钟跑通 CRUD；CHANGELOG 加「版本号语义」段（milestone vs audit-build 分离） |
| v0.5.1 | 第二个 example domain `tag` + todo↔tag 多对多 + `lazy="raise"` + `selectinload` + N+1 守门；v0.5.1 新代码 docstring 中文化 |
| v0.5.2 | generator 模板 + core/db/health 既有代码 ~2100 行 docstring 全量中文化 — **至此模板内代码 docstring 一致简体中文** |
| v0.5.3 | JWT Bearer 鉴权中间件（ADR §5）— AuthMiddleware + get_optional_current_user / require_current_user |

**KNOWN_DEVIATIONS 当前状态**：#1-#6 / #9 / #10 已关；剩 #7 / #11 / #12 / #13 / #14 **按各自定义的"触发条件"等待，不主动重写**（v0.5.0 reality check：原 v0.5.1 重写 middleware 计划撤回，避免完美主义陷阱）。详见 [`doc/tech-debt/KNOWN_DEVIATIONS.md`](./doc/tech-debt/KNOWN_DEVIATIONS.md)。

**版本口径**：模板里程碑版本看 CHANGELOG.md 顶部（vX.Y.Z 严格三段）；`pyproject.toml [project].version` 是业务实例初始版本（克隆后由业务团队自管），两者不同源；`tests/unit/test_version_consistency.py` 守 README / AGENTS / CLAUDE / PROJECT_OVERVIEW 与 CHANGELOG 一致；自审 build 走 git tag `-audit.N` 后缀，不进 CHANGELOG。

下一步触发点（无强制顺序）：
- 解 ADR Open Q（团队仓 ADR；本仓追踪 → [`doc/tech-debt/OPEN_QUESTIONS.md`](./doc/tech-debt/OPEN_QUESTIONS.md)）
- 加第二个 Python 服务（真实使用反馈）
- OTel SDK 已接入（v0.5.3，默认关闭）；下一步补 exporter lifecycle hardening + enabled-path 自动化测试

## AI 工作约束

完整规则在 [`doc/standards/AI_CODING_RULES.md`](./doc/standards/AI_CODING_RULES.md)。要点：

1. **新增业务模块**必走 `make new-module`，不要手抄 `domains/<existing>/`
2. **分层硬约束**（不能跨）：api 不写业务逻辑 / service 不抛 `HTTPException` / repository 不抛业务异常 / schemas 不混 ORM / models 不放序列化
3. **异常**：`AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码 `{service}.{ERROR_CODE}` 或 `framework.*` / `auth.*`
4. **提交前**必须 `make check` 全绿；声称"测试通过"前自己跑过
5. **改代码必须同步改 `doc/`**（drift 视为 bug）
6. **碰基础设施红线**（`core/` `db/` `main.py`）先停下来评估
7. **docstring / comments 默认简体中文**（v0.5.1 起 §0 红线）—— 仅 code identifier / 错误码字面量 / 框架名保留英文

## 工作约束（给 Claude Code 的特定行为）

- 严格遵守 `~/.claude/rules/python.md` 「Web 服务（FastAPI）」分层规则
- 不重新评估技术选型（FastAPI / uv / SA 2.x / Alembic / Ruff / Pyright / Pytest / Redis 已定）
- 新增文档前先看 [`doc/INDEX.md`](./doc/INDEX.md) 是否已有，不要重复
- 不主动 `git init` / `git commit`（按全局约定，等用户授权）
- 跨多文件改动 → 先建 task list 分阶段；不要一锅烩
- review / 整理 / 重构类大任务 → 派 agent 隔离上下文

## 7 条 Errata 固化位置（速查）

| # | 修订 | 位置 |
|---|---|---|
| 1 | `uvx pip-audit` | `Makefile` `audit` |
| 2 | `pyright` dev 依赖 | `pyproject.toml` |
| 3 | `alembic check` 漂移检测 | `Makefile` `check-db` |
| 4 | Pydantic Settings 官方默认优先级 | `core/config.py` |
| 5 | Redis 可选 profile | `compose.yaml` |
| 6 | 集成测试用 docker compose（非 testcontainers） | `tests/integration/` |
| 7 | async ORM `lazy='raise'` | `db/base.py` |

7 条详情见 [`doc/archive/EVOLUTION.md`](./doc/archive/EVOLUTION.md) 起源段。

## 外部资源

- 跨语言 ADR 正本（团队仓）：`team-engineering-adr/0001-cross-language-conventions.md`
- 全局 Python 规则：`~/.claude/rules/python.md`
- java-reference-service（Java 维护仓，参考）：``
