# admin-platform — 项目指引（给 Claude Code）

> 项目级 AI 上下文：本仓特有的分层约定、错误码规范、生成器流程等。通用 Python / FastAPI 工程规范不在此重复。

## 仓库角色

单租户后台管理脚手架**应用**（FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Ruff + Pytest），**对标 RuoYi（若依）**。派生自脚手架模板 `python-web-service-template`（lineage v0.5.3），**不是模板本身**。已落地认证 + RBAC + 审计 + 运营配置 + 监控 / 定时任务 + 文件 / Excel + Vue 前端（P0–P6 全落地）。

## 完整文档

**所有技术内容**都在 `docs/`，**不要**在本文件重复：

→ [`docs/INDEX.md`](./docs/INDEX.md)（按角色导航）
→ [`docs/PROJECT_OVERVIEW.md`](./docs/PROJECT_OVERVIEW.md)（一页概览）
→ [`docs/STANDARDS.md`](./docs/STANDARDS.md)（标准与原则总览：分层/命名/错误码/数据建模/安全）
→ [`CHANGELOG.md`](./CHANGELOG.md)（完整版本演进）

## 当前阶段（v0.0.1 — P0–P6 全落地）

`make check` 全绿（fast lane：lint + type + unit + api + import-linter + schema-doc 漂移）；`make test-integration` 需本地 DB + Redis；`make coverage` 门槛 85%。

**进度**（对标路线图 → [`docs/archive/specs/2026-06-04-ruoyi-parity-roadmap.md`](./docs/archive/specs/2026-06-04-ruoyi-parity-roadmap.md)）：

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
| P5 文件管理：对标 RuoYi sys_oss（StorageBackend 抽象 + LocalFileStorage / 零新依赖 / 扩展名白名单 + 魔数校验 + 流式 + 软删 + commit 后物理删） | ✓ |
| P5 Excel 导入导出：通用 `admin_platform/excel/`（reader/writer/schemas 零 domain 知识 + import-linter C10 叶子契约）+ post 绑定（import/export 2 端点 + formula injection 防御 + 一步全有全无 + 全量错误）+ openpyxl 3.1.5 | ✓ |
| P5 工具（**codegen 砍除（AI 时代）** / 文件管理✓ / Excel 导入导出✓） | ✓ |
| P6.0 前端工程基线：create-vue 脚手架（Vue3.5+TS strict+Vite8+Pinia+Router5）+ openapi-fetch 类型化 client / transport（blob/multipart/RFC9457）/ session（single-flight refresh + emitter）三件套 + 动态路由+seed 覆盖契约 + dependency-cruiser 分层机检 + CI 6 门 + pre-commit 提交门 | ✓ |
| P6.1 登录闭环：登录表单（文本验证码）+ getInfo/getRouters + bootstrap 时序 + 动态路由装配/reset + 全局守卫 + Layout 壳（Sidebar/Breadcrumb）+ v-hasPermi/usePermission + session 失效/登出统一出口 | ✓ |
| P6.2 RBAC 五页：用户（角色/岗位绑定）/ 角色（菜单·部门数据权限绑定，半选父纳入）/ 菜单（树+类型联动 M/C/F）/ 部门（树）/ 岗位 CRUD；复用 useCrudTable + TablePagination + useTree | ✓ |
| P6.3 运营/监控 9 页：字典（类型+数据抽屉）/ 参数 / 通知（不渲染 raw HTML）/ 操作日志 / 登录日志 / 在线用户（强制下线）/ 服务监控 / 缓存监控（降级）/ 定时任务（CRUD+手动触发+执行日志+handler 白名单） | ✓ |
| P6.4 文件管理 + Excel：文件 上传/下载/删除（复用 transport multipart/blob）+ 岗位 Excel 导入（始终 200+summary 全有全无）/ 导出 | ✓ |

> **2026-06-05 重大方向**：原 SaaS 多租户定位**已废弃**，回归单租户对标 RuoYi。多租户拆除背景见 [`docs/architecture/MULTI_TENANCY.md`](./docs/architecture/MULTI_TENANCY.md)（废弃说明）+ roadmap §3「单租户回归重构」。

**版本口径**：本应用版本以 `pyproject.toml [project].version`（当前 `0.0.1`）为准；`tests/unit/test_version_consistency.py` 守 README / AGENTS / CLAUDE / PROJECT_OVERVIEW 含该应用版本。模板 CHANGELOG.md（v0.5.3）是派生 lineage，不是本应用发版记录。

**脚手架 lineage / tech-debt**：generator、`docs/tech-debt/KNOWN_DEVIATIONS.md` 等继承自模板，是 lineage 资产。示例域 `todo`/`tag` 已删除（admin 平台不需要，建 domain 用 `make new-module`）。

P0–P6 全部落地（认证 / RBAC / 审计 / 运营配置 / 监控·定时任务 / 文件·Excel / Vue 前端 P6.0–6.5）；各阶段实现细节、关键决策与评审修复见 [设计决策溯源](./docs/archive/specs/INDEX.md)。⚠️ **迁移 0013–0019（含 0016 / 0019）生产 / 共享库迁移仍待单独授权**——仅本地 dev + CI 临时容器跑过。

## AI 工作约束

完整规则在 [`docs/standards/AI_CODING_RULES.md`](./docs/standards/AI_CODING_RULES.md)。要点：

1. **新增业务模块**必走 `make new-module`，不要手抄 `domains/<existing>/`
2. **分层硬约束**（不能跨）：api 不写业务逻辑 / service 不抛 `HTTPException` / repository 不抛业务异常 / schemas 不混 ORM / models 不放序列化
3. **异常**：`AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码 `{service}.{ERROR_CODE}` 或 `framework.*` / `auth.*`
4. **提交前**必须 `make check` 全绿；声称"测试通过"前自己跑过
5. **改代码必须同步改 `docs/`**（drift 视为 bug）
6. **碰基础设施红线**（`core/` `db/` `main.py`）先停下来评估
7. **docstring / comments 默认简体中文**（v0.5.1 起 §0 红线）—— 仅 code identifier / 错误码字面量 / 框架名保留英文

## 工作约束（给 Claude Code 的特定行为）

- 严格遵守本仓分层规则（[`docs/architecture/LAYERED_DESIGN.md`](./docs/architecture/LAYERED_DESIGN.md) + [`docs/standards/AI_CODING_RULES.md`](./docs/standards/AI_CODING_RULES.md)）
- 不重新评估技术选型（FastAPI / uv / SA 2.x / Alembic / Ruff / Pyright / Pytest / Redis 已定）
- 新增文档前先看 [`docs/INDEX.md`](./docs/INDEX.md) 是否已有，不要重复
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

7 条详情见 [`docs/archive/EVOLUTION.md`](./docs/archive/EVOLUTION.md) 起源段。

## 跨语言协同

本仓与其他语言后端的契约对齐（错误码 / Result / 鉴权边界）见 [`docs/reference/CROSS_LANGUAGE_ADR.md`](./docs/reference/CROSS_LANGUAGE_ADR.md)。
