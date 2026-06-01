# python-web-service-template — AI Agent 协作指引

> 给 Codex / Cursor / Cline / 其它 AI agent 用。Claude Code 看 [`CLAUDE.md`](./CLAUDE.md)（两份内容基本同步）。

## 仓库角色

团队 Python Web 服务脚手架模板。**新建后端 API / 微服务的默认起点**。

## 完整文档

→ [`doc/INDEX.md`](./doc/INDEX.md)（按角色导航）
→ [`doc/PROJECT_OVERVIEW.md`](./doc/PROJECT_OVERVIEW.md)（一页概览）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.5.3）

`make check` 189 ✓ / `make test-integration` 29 selected ✓ / `make coverage` 门槛 85%（`fail_under = 85`，实测 ~87.19%）。

**v0.5.0-v0.5.3 四个 milestone 浓缩**：
- v0.5.0：example domain `todo`（5 分钟跑通 CRUD）+ CHANGELOG 加「版本号语义」段（milestone vs audit build 分离）
- v0.5.1：第二个 example domain `tag` + todo↔tag 多对多（`lazy="raise"` + `selectinload` + N+1 守门）+ v0.5.1 新代码 docstring 中文化
- v0.5.2：generator 模板 + core/db/health 既有代码 ~2100 行 docstring 全量中文化 — **至此模板内代码 docstring 一致简体中文**
- v0.5.3：JWT Bearer 鉴权中间件（ADR §5）— AuthMiddleware + get_current_user Depends + pyjwt

逐版详情 → [`CHANGELOG.md`](./CHANGELOG.md)。

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
