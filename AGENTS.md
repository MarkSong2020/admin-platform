# admin-platform — AI Agent 协作指引

> 给 Codex / Cursor / Cline 等 AI agent。Claude Code 看 [`CLAUDE.md`](./CLAUDE.md)（两份内容同步）。

## 仓库角色

单租户后台管理脚手架**应用**（不是模板），**对标 RuoYi（若依）**。FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Vue3 全栈，派生自脚手架模板 `python-web-service-template`。早期多租户定位已废弃（见 [`docs/architecture/MULTI_TENANCY.md`](./docs/architecture/MULTI_TENANCY.md)）。技术选型已定，不重新评估。

## 完整文档

→ [`docs/INDEX.md`](./docs/INDEX.md)（导航）
→ [`docs/STANDARDS.md`](./docs/STANDARDS.md)（分层 / 命名 / 错误码 / 数据建模 / 安全 总览）
→ [`docs/PROJECT_OVERVIEW.md`](./docs/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md)（版本演进）

## 当前状态（v0.0.1）

P0–P6 全落地（认证 / RBAC / 审计 / 运营配置 / 监控·定时任务 / 文件·Excel / Vue 前端）。逐阶段细节见 CHANGELOG + `docs/archive/specs/`。

- **验证**：`make check`（fast lane：lint + type + unit + api，DB-free）；DB·Redis-bound 路径覆盖在 `make test-integration`；`make coverage` 门槛 85%。
- ⚠️ 迁移 `0013–0019` 仅本地 + CI 跑过，生产迁移待单独授权。

## AI 工作约束（最重要）

完整规则 → [`docs/standards/AI_CODING_RULES.md`](./docs/standards/AI_CODING_RULES.md)

1. **新增业务模块必走** `make new-module name=xxx [with-model=1]`，不手抄
2. **分层不能跨**：api 不写业务 / service 不抛 HTTPException / repository 不抛业务异常 / schemas 不混 ORM / models 不放序列化
3. **AppError**：`AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码 `{service}.{ERROR_CODE}`
4. **提交前** `make check` 必须全绿；声称"测试通过"前必须跑过
5. **改代码同步改 `docs/`**（drift 视为 bug）
6. **基础设施红线**（`core/` `db/` `main.py`）先评估
7. **docstring / comments 默认简体中文** —— 仅 code identifier / 错误码字面量 / 框架名保留英文

## 同步约定

`CLAUDE.md` ↔ `AGENTS.md` 改任一份必同步另一份。版本号需与 `pyproject.toml` 一致（`tests/unit/test_version_consistency.py` 自动守门）。

## 7 条 Errata + 跨语言协同

Errata 速查见 [`CLAUDE.md`](./CLAUDE.md)「7 条 Errata 固化位置」段。跨语言契约对齐见 [`docs/reference/CROSS_LANGUAGE_ADR.md`](./docs/reference/CROSS_LANGUAGE_ADR.md)。
