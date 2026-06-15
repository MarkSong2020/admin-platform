# admin-platform — AI Agent 协作指引

> 给 Claude Code / Codex / Cursor / Cline 等 AI agent 的**唯一正本**。`CLAUDE.md` 通过 `@AGENTS.md` 导入本文件（Claude Code 自动加载），改约定只改这一处。
>
> 项目级 AI 上下文：本仓**特有**的分层约定、错误码规范、生成器流程。通用 Python / FastAPI 工程规范不在此重复。

## 仓库角色

单租户后台管理脚手架**应用**（FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Ruff + Pytest + Vue3 前端），**对标 RuoYi（若依）**。派生自脚手架模板 `python-web-service-template`，**不是模板本身**。

- 技术选型**已定、不重新评估**：FastAPI / uv / SA 2.x / Alembic / Ruff / Pyright / Pytest / Redis / Vue3。
- 单租户对标 RuoYi；早期 SaaS 多租户定位已废弃（背景见 [`docs/architecture/MULTI_TENANCY.md`](./docs/architecture/MULTI_TENANCY.md)）。

## 完整文档

**技术内容都在 `docs/`，不在本文件重复：**

→ [`docs/INDEX.md`](./docs/INDEX.md)（按主题 / 角色导航）
→ [`docs/STANDARDS.md`](./docs/STANDARDS.md)（分层 / 命名 / 错误码 / 数据建模 / 安全 总览）
→ [`docs/PROJECT_OVERVIEW.md`](./docs/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md) + [`docs/archive/specs/INDEX.md`](./docs/archive/specs/INDEX.md)（各阶段实现与设计决策溯源）

## 当前状态（v0.0.1）

P0–P6 全落地（认证 / RBAC / 审计 / 运营配置 / 监控·定时任务 / 文件·Excel / Vue 前端）。逐阶段细节见 CHANGELOG + archive/specs。

- **验证**：`make check`（fast lane：lint + type + unit + api + import-linter + schema-doc 漂移，须全绿）；`make test-integration` 需本地 DB + Redis；`make coverage` 门槛 85%。
- ⚠️ 迁移 `0013–0020` 仅本地 dev + CI 临时容器跑过，**生产 / 共享库迁移待单独授权**。
- **版本号**以 `pyproject.toml [project].version` 为准；`tests/unit/test_version_consistency.py` 守 README / AGENTS / PROJECT_OVERVIEW 与之一致（改版本号要同步三处）。

## AI 工作约束（核心）

完整规则 → [`docs/standards/AI_CODING_RULES.md`](./docs/standards/AI_CODING_RULES.md)。要点：

1. **新增业务模块**必走 `make new-module name=xxx [with-model=1]`，不手抄 `domains/<existing>/`
2. **分层硬约束**（不能跨）：api 不写业务逻辑 / service 不抛 `HTTPException` / repository 不抛业务异常 / schemas 不混 ORM / models 不放序列化
3. **异常**：`AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码 `{service}.{ERROR_CODE}` 或 `framework.*` / `auth.*`
4. **提交前** `make check` 必须全绿；声称"测试通过"前自己跑过
5. **改代码同步改 `docs/`**（drift 视为 bug）；新增文档前先查 [`docs/INDEX.md`](./docs/INDEX.md) 避免重复
6. **碰基础设施红线**（`core/` `db/` `main.py`）先停下来评估
7. **docstring / comments 默认简体中文** —— 仅 code identifier / 错误码字面量 / 框架名保留英文
8. **不主动 `git commit` / `push`**，等明确授权

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

7 条详情见 [`docs/archive/EVOLUTION.md`](./docs/archive/EVOLUTION.md) 起源段。

## 跨语言协同

本仓与其他语言后端的契约对齐（错误码 / Result / 鉴权边界）见 [`docs/reference/CROSS_LANGUAGE_ADR.md`](./docs/reference/CROSS_LANGUAGE_ADR.md)。
