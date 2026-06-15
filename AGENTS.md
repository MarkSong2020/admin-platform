# admin-platform — AI Agent 协作指引

> 给 Codex / Cursor / Cline / 其它 AI agent 用。Claude Code 看 [`CLAUDE.md`](./CLAUDE.md)（两份内容基本同步）。

## 仓库角色

单租户后台管理脚手架**应用**（不是模板），**对标 RuoYi（若依）**。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。
已落地 JWT 认证 + RBAC + 审计 + 运营配置（字典/参数/通知）+ 监控/定时任务 + 文件管理/Excel + Vue 前端（P0–P6 全落地）。

## 完整文档

→ [`docs/INDEX.md`](./docs/INDEX.md)（按角色导航）
→ [`docs/PROJECT_OVERVIEW.md`](./docs/PROJECT_OVERVIEW.md)（一页概览）
→ [`docs/STANDARDS.md`](./docs/STANDARDS.md)（标准与原则总览：分层/命名/错误码/数据建模/安全）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.0.1 — P0–P6 全落地）

`make check` 650 ✓ / `make test-integration` 208 ✓ / `make coverage` 门槛 85%（fast-lane 单测 + API，DB-free；refresh 轮换 / 定时任务调度 / RBAC 绑定 / repository 等 DB·Redis-bound 路径覆盖在 `make test-integration`，不在 fast-lane 门槛内）。

**进度**（对标路线图 → [`docs/archive/specs/2026-06-04-ruoyi-parity-roadmap.md`](./docs/archive/specs/2026-06-04-ruoyi-parity-roadmap.md)）：
- P0 认证地基：Argon2 密码 + JWT 签发/校验 + user 五层 CRUD + CLI 建超管 ✓
- P0.9 单租户回归：拆多租户（tenant_filter/TenantMixin/tenants 表/上下文/隔离）→ 对标 RuoYi 本体 ✓
- P1 RBAC：部门/角色/菜单/岗位 + RuoYi 数据权限 + getInfo/getRouters + audit_event.v1 ✓
- P1.4 登录增强：refresh 轮换 / 验证码 / 登录限流 ✓
- P1.5 安全加固：dept 越权 / 登录防护默认 / 绑定 API + 审计织入 / route 契约 / refresh lock ✓
- P2 审计持久化：audit_events（成功审计 in-tx / 失败缓冲独立）+ login_logs + IP/UA 中间件 + operlog/logininfor 查询 ✓
- P3 运营配置：字典（类型+数据 / FK RESTRICT / 单默认）+ 参数（热更新读穿）+ 通知公告 ✓
- P4 监控/任务：服务监控（psutil）+ 缓存监控（Redis INFO 降级）+ 在线用户 + 定时任务（APScheduler + PG leader election + DB claim + handler registry 白名单）✓
- P5 文件管理（对标 RuoYi sys_oss：StorageBackend + LocalFileStorage / 扩展名白名单 + 魔数 + 流式 + 软删）+ Excel 导入导出（excel 叶子机制 + post 绑定 + formula injection 防御）✓
- P6 Vue 前端：登录闭环 + RBAC 五页 + 运营/监控 9 页 + 文件/Excel + P6.5 UI 升级 ✓

> **2026-06-05 重大方向**：原 SaaS 多租户定位已废弃，回归单租户对标 RuoYi。背景见 [`docs/architecture/MULTI_TENANCY.md`](./docs/architecture/MULTI_TENANCY.md) 废弃说明 + roadmap §3。

**脚手架 lineage**：派生自 `python-web-service-template` v0.5.3（generator / CI 等模板资产保留；示例域 `todo`/`tag` 已删除，建 domain 用 `make new-module`）。模板演进史 → [`CHANGELOG.md`](./CHANGELOG.md)。

**KNOWN_DEVIATIONS 状态**：#1-#6 / #9 / #10 已关；剩 #7 / #11 / #12 / #13 / #14 按各自「触发条件」等待，不主动重写（v0.5.0 reality check）。详见 [`docs/tech-debt/KNOWN_DEVIATIONS.md`](./docs/tech-debt/KNOWN_DEVIATIONS.md)。

## AI 工作约束（最重要）

完整规则 → [`docs/standards/AI_CODING_RULES.md`](./docs/standards/AI_CODING_RULES.md)

**红线 5 条**：

1. **新增业务模块必走 generator**：`make new-module name=order [with-model=1]`，不要手抄
2. **分层不能跨**：api 不写业务 / service 不抛 HTTPException / repository 不抛业务异常 / schemas 不混 ORM
3. **AppError 用法**：`AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码 `{service}.{ERROR_CODE}`
4. **提交前** `make check` 必须全绿；声称"测试通过"前必须跑过
5. **改代码同步改 `docs/`**（drift 视为 bug）

**docstring/comments 默认简体中文**（v0.5.1 起 AI_CODING_RULES.md §0 红线）：仅 code identifier / 错误码字面量 / 框架名保留英文。

## 同步约定

`CLAUDE.md` ↔ `AGENTS.md` 改任一份必同步另一份。**任何与 CHANGELOG.md 顶部版本号不一致的描述视为 bug**，PR review 直接打回（`tests/unit/test_version_consistency.py` 自动守门）。

## 7 条 Errata（速查）

详见 [`CLAUDE.md`](./CLAUDE.md) 「7 条 Errata 固化位置」段。

## 外部资源

- 跨语言 ADR 正本：`team-engineering-adr/0001-cross-language-conventions.md`
- 全局 Python 规则：`~/.claude/rules/python.md`
