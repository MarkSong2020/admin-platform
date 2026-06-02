# admin-platform — AI Agent 协作指引

> 给 Codex / Cursor / Cline / 其它 AI agent 用。Claude Code 看 [`CLAUDE.md`](./CLAUDE.md)（两份内容基本同步）。

## 仓库角色

多租户 admin 平台**应用**（不是模板）。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。
当前在 P0 多租户认证地基阶段；目标是 fail-closed 隔离 + JWT 认证 + 后续 RBAC / 审计 / admin 业务域。

## 完整文档

→ [`doc/INDEX.md`](./doc/INDEX.md)（按角色导航）
→ [`doc/PROJECT_OVERVIEW.md`](./doc/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.0.1 — P0 多租户认证地基）

`make check` 202 ✓（含租户隔离单测）/ `make coverage` 门槛 85%。

**P0 进度**（完整计划 → [`docs/specs/2026-06-02-p0-multitenant-auth-foundation.md`](./docs/specs/2026-06-02-p0-multitenant-auth-foundation.md)）：
- Task 1：scaffold（从 `python-web-service-template` git archive 派生）✓
- Task 2：argon2-cffi 密码哈希依赖（ADR-F）+ access token TTL 配置 ✓
- Task 3：fail-closed 租户隔离 —— `session.info` 上下文 + `do_orm_execute`（读广义 fail-closed）/ `before_flush`（写对称 fail-closed）✓
- 下一步：Task 4 数据模型（Tenant/User）+ 迁移 → Task 5/6/7 认证签发 / 登录 / 上下文注入

**脚手架 lineage**：派生自 `python-web-service-template` v0.5.3（generator / CI 等模板资产保留；示例域 `todo`/`tag` 已删除，建 domain 用 `make new-module`）。模板演进史 → [`CHANGELOG.md`](./CHANGELOG.md)。

**KNOWN_DEVIATIONS 状态**：#1-#6 / #9 / #10 已关；剩 #7 / #11 / #12 / #13 / #14 按各自「触发条件」等待，不主动重写（v0.5.0 reality check）。详见 [`doc/tech-debt/KNOWN_DEVIATIONS.md`](./doc/tech-debt/KNOWN_DEVIATIONS.md)。

## AI 工作约束（最重要）

完整规则 → [`doc/standards/AI_CODING_RULES.md`](./doc/standards/AI_CODING_RULES.md)

**红线 5 条**：

1. **新增业务模块必走 generator**：`make new-module name=order [with-model=1]`，不要手抄
2. **分层不能跨**：api 不写业务 / service 不抛 HTTPException / repository 不抛业务异常 / schemas 不混 ORM
3. **AppError 用法**：`AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码 `{service}.{ERROR_CODE}`
4. **提交前** `make check` 必须全绿；声称"测试通过"前必须跑过
5. **改代码同步改 `doc/`**（drift 视为 bug）

**docstring/comments 默认简体中文**（v0.5.1 起 AI_CODING_RULES.md §0 红线）：仅 code identifier / 错误码字面量 / 框架名保留英文。

## 同步约定

`CLAUDE.md` ↔ `AGENTS.md` 改任一份必同步另一份。**任何与 CHANGELOG.md 顶部版本号不一致的描述视为 bug**，PR review 直接打回（`tests/unit/test_version_consistency.py` 自动守门）。

## 7 条 Errata（速查）

详见 [`CLAUDE.md`](./CLAUDE.md) 「7 条 Errata 固化位置」段。

## 外部资源

- 跨语言 ADR 正本：`~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`
- 全局 Python 规则：`~/.claude/rules/python.md`
