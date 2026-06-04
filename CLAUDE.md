# admin-platform — 项目指引（给 Claude Code）

> 项目级 AI 上下文。全局规范在 `~/.claude/CLAUDE.md` 和 `~/.claude/rules/python.md`，**不要重复**。

## 仓库角色

单租户后台管理脚手架**应用**（FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Ruff + Pytest），**对标 RuoYi（若依）**。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3），**不是模板本身**。已有 JWT 认证 + user CRUD，目标长出 RBAC / 审计 / 字典 / 前端。

> 跨栈选型决策不在本仓口径——见 `~/.claude/CLAUDE.md` 的「技术栈」段（按需求选型，不预设默认）。

## 完整文档

**所有技术内容**都在 `doc/`，**不要**在本文件重复：

→ [`doc/INDEX.md`](./doc/INDEX.md)（按角色导航）
→ [`doc/PROJECT_OVERVIEW.md`](./doc/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.0.1 — 单租户回归完成，进 P1 RBAC）

`make check` 202 ✓ / `make test-integration` 24 selected（19 passed / 5 redis skipped）✓ / `make coverage` 门槛 85%。

**进度**（对标路线图 → [`docs/specs/2026-06-04-ruoyi-parity-roadmap.md`](./docs/specs/2026-06-04-ruoyi-parity-roadmap.md)）：

| 阶段 | 状态 |
|---|---|
| P0 认证地基：Argon2 密码 + JWT 签发/校验 + user 五层 CRUD + CLI 建超管 | ✓ |
| P0.9 单租户回归：拆多租户（tenant_filter/TenantMixin/tenants 表/上下文/隔离）→ 对标 RuoYi 本体 | ✓ |
| P1 RBAC：角色/菜单/部门/岗位 + 数据权限 + 登录增强（refresh/验证码） | 下一步 |
| P2+ 审计日志 / 字典参数 / 监控任务 / Vue 前端 | 待做 |

> **2026-06-05 重大方向**：原 SaaS 多租户定位**已废弃**，回归单租户对标 RuoYi。多租户拆除背景见 [`doc/architecture/MULTI_TENANCY.md`](./doc/architecture/MULTI_TENANCY.md)（废弃说明）+ roadmap §3「单租户回归重构」。

**版本口径**：本应用版本以 `pyproject.toml [project].version`（当前 `0.0.1`）为准；`tests/unit/test_version_consistency.py` 守 README / AGENTS / CLAUDE / PROJECT_OVERVIEW 含该应用版本。模板 CHANGELOG.md（v0.5.3）是派生 lineage，不是本应用发版记录。

**脚手架 lineage / tech-debt**：generator、`doc/tech-debt/KNOWN_DEVIATIONS.md` 等继承自模板，是 lineage 资产。示例域 `todo`/`tag` 已删除（admin 平台不需要，建 domain 用 `make new-module`）。

下一步：P1 RBAC（角色/菜单/部门/岗位 + RuoYi 风格数据权限，参考 RuoYi-Vue3-FastAPI；具体表结构设计拉 Codex PK）。

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
