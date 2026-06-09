# admin-platform — AI Agent 协作指引

> 给 Codex / Cursor / Cline / 其它 AI agent 用。Claude Code 看 [`CLAUDE.md`](./CLAUDE.md)（两份内容基本同步）。

## 仓库角色

单租户后台管理脚手架**应用**（不是模板），**对标 RuoYi（若依）**。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。
已有 JWT 认证 + user CRUD；目标是 RuoYi 风格 RBAC / 审计 / 字典 / 前端。

## 完整文档

→ [`doc/INDEX.md`](./doc/INDEX.md)（按角色导航）
→ [`doc/PROJECT_OVERVIEW.md`](./doc/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.0.1 — P1 RBAC + 登录增强已落地，P1.5 加固中）

`make check` 378 ✓ / `make coverage` 门槛 85%。

**进度**（对标路线图 → [`docs/specs/2026-06-04-ruoyi-parity-roadmap.md`](./docs/specs/2026-06-04-ruoyi-parity-roadmap.md)）：
- P0 认证地基：Argon2 密码 + JWT 签发/校验 + user 五层 CRUD + CLI 建超管 ✓
- P0.9 单租户回归：拆多租户（tenant_filter/TenantMixin/tenants 表/上下文/隔离）→ 对标 RuoYi 本体 ✓
- P1 RBAC：部门/角色/菜单/岗位 + RuoYi 数据权限 + getInfo/getRouters + audit_event.v1 ✓
- P1.4 登录增强：refresh 轮换 / 验证码 / 登录限流 ✓
- 下一步 P1.5 安全加固：dept 越权 / 登录防护默认 / 绑定 API / 审计织入（源自 2026-06-09 多视角 review）

> **2026-06-05 重大方向**：原 SaaS 多租户定位已废弃，回归单租户对标 RuoYi。背景见 [`doc/architecture/MULTI_TENANCY.md`](./doc/architecture/MULTI_TENANCY.md) 废弃说明 + roadmap §3。

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

- 跨语言 ADR 正本：`team-engineering-adr/0001-cross-language-conventions.md`
- 全局 Python 规则：`~/.claude/rules/python.md`
