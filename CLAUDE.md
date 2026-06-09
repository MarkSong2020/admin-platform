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

## 当前阶段（v0.0.1 — P1 RBAC + 登录增强 + P2 审计/监控查询 + P3 运营配置 + P4 监控/任务已落地）

`make check` 537 ✓ / `make test-integration` 189 ✓ / `make coverage` 门槛 85%（集成需本地 DB + Redis）。

**进度**（对标路线图 → [`docs/specs/2026-06-04-ruoyi-parity-roadmap.md`](./docs/specs/2026-06-04-ruoyi-parity-roadmap.md)）：

| 阶段 | 状态 |
|---|---|
| P0 认证地基：Argon2 密码 + JWT 签发/校验 + user 五层 CRUD + CLI 建超管 | ✓ |
| P0.9 单租户回归：拆多租户（tenant_filter/TenantMixin/tenants 表/上下文/隔离）→ 对标 RuoYi 本体 | ✓ |
| P1 RBAC：部门/角色/菜单/岗位 + 数据权限 + getInfo/getRouters + audit_event.v1 | ✓ |
| P1.4 登录增强：refresh 轮换 + 验证码 + 登录限流 | ✓ |
| P1.5 安全加固：dept 越权 / 登录防护默认 / 绑定 API + 审计织入 / route 契约 / refresh lock | ✓ |
| P2 审计持久化：audit_events 表（成功审计 in-tx 原子 / 失败缓冲独立）+ login_logs + 中间件 IP/UA + 监控查询 API（operlog/logininfor） | ✓ |
| P3 运营配置：字典（类型+数据双资源 / FK RESTRICT / 单默认 / 消费端点）+ 参数（热更新读穿 / 内置禁删）+ 通知公告 | ✓ |
| P4a/P4b 监控：服务监控（psutil CPU/内存/磁盘/进程）+ 缓存监控（Redis INFO 降级）+ 在线用户（活动 family 派生 + 强制下线审计） | ✓ |
| P4c 定时任务：APScheduler + PG leader election + DB execution claim（多 worker 红线）+ handler registry 白名单（防 RCE）+ 手动触发 + 执行日志 | ✓ |
| P5 工具（代码生成 / Excel / 文件）/ P6 Vue 前端 | 待做 |

> **2026-06-05 重大方向**：原 SaaS 多租户定位**已废弃**，回归单租户对标 RuoYi。多租户拆除背景见 [`doc/architecture/MULTI_TENANCY.md`](./doc/architecture/MULTI_TENANCY.md)（废弃说明）+ roadmap §3「单租户回归重构」。

**版本口径**：本应用版本以 `pyproject.toml [project].version`（当前 `0.0.1`）为准；`tests/unit/test_version_consistency.py` 守 README / AGENTS / CLAUDE / PROJECT_OVERVIEW 含该应用版本。模板 CHANGELOG.md（v0.5.3）是派生 lineage，不是本应用发版记录。

**脚手架 lineage / tech-debt**：generator、`doc/tech-debt/KNOWN_DEVIATIONS.md` 等继承自模板，是 lineage 资产。示例域 `todo`/`tag` 已删除（admin 平台不需要，建 domain 用 `make new-module`）。

下一步：**P5 工具**（代码生成对标 / Excel 导入导出 / 文件上传）/ P6 Vue 前端。**P4 监控/任务全落地**（spec [`docs/specs/2026-06-10-p4-monitoring-tasks.md`](./docs/specs/2026-06-10-p4-monitoring-tasks.md)）：P4a/P4b 服务/缓存监控（psutil + Redis INFO 白名单 + 降级）+ 在线用户（活动 refresh token family 派生，login_time 取轮换原点 + 强制下线 audited，仅撤 refresh）；**P4c 定时任务**（Codex PK medium 收敛 + 人值守拍板 §4，时区 Asia/Shanghai）：APScheduler `AsyncIOScheduler` + **PG advisory leader election + DB execution claim 双层防多 worker 重复执行（红线）** + **handler registry 白名单防 RCE**（管理员只选预注册 handler_key，非任意调用串）+ 手动触发 + 执行日志。关键纪律：`scheduler_enabled` 默认 False（CRUD/手动触发不依赖调度器）、手动并发靠任务行 FOR UPDATE 串行化、orphan running 靠 stale 阈值不冻调度。P4c 排期项：6 字段秒级 cron / SIGKILL 显式启动恢复 / 自动重试，见 spec §4 非目标。⚠️ **迁移 0016 + 0013-0015 生产/共享库迁移仍待单独授权**（仅本地 dev + CI 临时容器跑过）。P3 运营配置已落地（spec [`docs/specs/2026-06-09-p3-operational-config.md`](./docs/specs/2026-06-09-p3-operational-config.md)，经 Codex high 数据模型 PK 收敛）；关键决策：**字典数据 FK→dict_types.id + RESTRICT**（删有数据的类型 409，不级联）、**参数热更新走读穿 DB 无缓存**（单/多 worker 都正确）、单默认值 partial unique index 兜底、is_builtin 可切换解保护（对抗审查 §6 收敛）。排期项：参数多 worker 版本化缓存（性能）、value_type 强类型解析、通知富文本渲染期净化（P6）、config 敏感值脱敏，见 spec §1 非目标。P2 排期项（Redis Stream / outbox / provider 连接池 / 非 HTTP RBAC 写原子性）仍未动，见 p2 spec §8。

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

- 跨语言 ADR 正本（团队仓）：`~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`
- 全局 Python 规则：`~/.claude/rules/python.md`
- shopsell-server（Java 维护仓，参考）：`~/IdeaProjects/shopsell-server/`
