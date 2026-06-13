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

## 当前阶段（v0.0.1 — P1 RBAC + 登录增强 + P2 审计/监控查询 + P3 运营配置 + P4 监控/任务 + P5 文件管理/Excel 导入导出已落地）

`make check` 650 ✓ / `make test-integration` 208 ✓ / `make coverage` 门槛 85%（集成需本地 DB + Redis）。

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
| P5 文件管理：对标 RuoYi sys_oss（StorageBackend 抽象 + LocalFileStorage / 零新依赖 / 扩展名白名单 + 魔数校验 + 流式 + 软删 + commit 后物理删） | ✓ |
| P5 Excel 导入导出：通用 `admin_platform/excel/`（reader/writer/schemas 零 domain 知识 + import-linter C10 叶子契约）+ post 绑定（import/export 2 端点 + formula injection 防御 + 一步全有全无 + 全量错误）+ openpyxl 3.1.5 | ✓ |
| P5 工具（**codegen 砍除（AI 时代）** / 文件管理✓ / Excel 导入导出✓） | ✓ |
| P6.0 前端工程基线：create-vue 脚手架（Vue3.5+TS strict+Vite8+Pinia+Router5）+ openapi-fetch 类型化 client / transport（blob/multipart/RFC9457）/ session（single-flight refresh + emitter）三件套 + 动态路由+seed 覆盖契约 + dependency-cruiser 分层机检 + CI 6 门 + pre-commit 提交门 | ✓ |
| P6.1 登录闭环：登录表单（文本验证码）+ getInfo/getRouters + bootstrap 时序 + 动态路由装配/reset + 全局守卫 + Layout 壳（Sidebar/Breadcrumb）+ v-hasPermi/usePermission + session 失效/登出统一出口 | ✓ |
| P6.2 RBAC 五页：用户（角色/岗位绑定）/ 角色（菜单·部门数据权限绑定，半选父纳入）/ 菜单（树+类型联动 M/C/F）/ 部门（树）/ 岗位 CRUD；复用 useCrudTable + TablePagination + useTree | ✓ |
| P6.3 运营/监控 9 页：字典（类型+数据抽屉）/ 参数 / 通知（不渲染 raw HTML）/ 操作日志 / 登录日志 / 在线用户（强制下线）/ 服务监控 / 缓存监控（降级）/ 定时任务（CRUD+手动触发+执行日志+handler 白名单） | ✓ |
| P6.4 文件管理 + Excel：文件 上传/下载/删除（复用 transport multipart/blob）+ 岗位 Excel 导入（始终 200+summary 全有全无）/ 导出 | ✓ |

> **2026-06-05 重大方向**：原 SaaS 多租户定位**已废弃**，回归单租户对标 RuoYi。多租户拆除背景见 [`doc/architecture/MULTI_TENANCY.md`](./doc/architecture/MULTI_TENANCY.md)（废弃说明）+ roadmap §3「单租户回归重构」。

**版本口径**：本应用版本以 `pyproject.toml [project].version`（当前 `0.0.1`）为准；`tests/unit/test_version_consistency.py` 守 README / AGENTS / CLAUDE / PROJECT_OVERVIEW 含该应用版本。模板 CHANGELOG.md（v0.5.3）是派生 lineage，不是本应用发版记录。

**脚手架 lineage / tech-debt**：generator、`doc/tech-debt/KNOWN_DEVIATIONS.md` 等继承自模板，是 lineage 资产。示例域 `todo`/`tag` 已删除（admin 平台不需要，建 domain 用 `make new-module`）。

下一步：**P6 Vue 前端**（P5 工具全落地）。**P5 Excel 导入导出已落地**（spec [`docs/specs/2026-06-11-p5-excel-import-export.md`](./docs/specs/2026-06-11-p5-excel-import-export.md)，对标 RuoYi 导入导出 + Codex PK 收敛 + 对抗审查修复）：通用机制 `admin_platform/excel/`（顶层叶子模块零 domain 知识——reader：openpyxl read-only 流式 + schema 驱动逐行 Pydantic 校验 + 坏行不阻断全量错误；writer：write-only 流式 + formula injection 防御；schemas：ExcelColumn/RowError/ParsedRow/ImportResult）+ **import-linter C10 契约**（excel 禁 import fastapi/sqlalchemy/domains/core，纯叶子，类比 authz C8）。第一版绑定 **post 岗位**（最小复杂度示范，避开 user 密码/scope、dict FK/单默认）：`domains/post/excel.py` 列适配（复用 PostCreate 作导入行 schema）+ service `import_posts`/`export_posts` + repository `list_existing_codes`/`bulk_create`/`list_for_export`。**2 端点**：`POST /api/v1/posts/import`（multipart xlsx，**一步全有全无** + 全量错误，**始终 200 + PostImportSummary{imported, errors}** 业务通道；并发撞 uq_posts_code → 409；超大 → 413）+ `GET /api/v1/posts/export`（全量 + 行数上限）。新增权限 `system:post:{import,export}`（三集一致 + seed `_resource_menu` 加 extra_buttons）。**无新迁移**（复用 posts 表）；新依赖 **openpyxl 3.1.5**。关键决策（Codex PK + Explore agent 两来源印证 + 一处 push back）：excel/ 顶层叶子（非 core 红线）/ 一步全有全无（push back Codex 两步暂存——一步同样避免部分写 + 全量报告，省暂存基建）/ 导入错误走 200+summary.errors（非 422，因 ProblemDetail.errors 受 debug 脱敏生产看不到行级反馈）。对抗审查修复（Codex 二审 + adversarial agent 两来源印证）：P0 Excel formula injection（导出 cell 以 =/+/-/@ 开头 → writer 前缀单引号文本化）/ P0 import 无 size 上限 OOM（→ 流式累计 + excel_max_upload_size_bytes 超限 413）；P1 审计 imported=0 记 success（→ display 标注错误数）/「始终 200」并发契约（→ spec 标并发 409 例外）；P2 非法 xlsx → 500（→ INVALID_FILE 业务错误）/ sort_order int4 越界（→ ge/le 约束）/ canonical 前导零漂移（→ docstring 诚实标注）。排期：zip bomb 深度防御 / 文本列强制 / 两步预览。**P5 文件管理已落地**（spec [`docs/specs/2026-06-11-p5-file-management.md`](./docs/specs/2026-06-11-p5-file-management.md)，用户 2026-06-11 拍板 + Codex PK 收敛）：P5 范围重新圈定——**砍 RuoYi 在线 codegen + introspection 逆向**（AI 时代过时：coding agent 直接读表生成五层 CRUD + 测试 + 迁移 + doc 比 velocity 模板灵活，绿地项目无遗留表逆向场景）；**保留 `make new-module` CLI**（不是 codegen，是 agent 生成时的「确定性护栏」——五层结构/import-linter/schema-doc/column-comment 自动注册，AI 时代防结构漂移更有用，「新模块必走 make new-module」规则不变）。**文件管理对标 RuoYi sys_oss**：`domains/file/` 五层 + `storage.py`（StorageBackend 抽象 + LocalFileStorage，**零新依赖**，python-multipart 随 fastapi[standard] 已装）；migration `0019_p5_file_management`（files 表 object_key/storage_backend/sha256/uploader_id FK→users.id RESTRICT/软删）；5 端点 `/api/v1/files` list/query/upload(multipart 流式)/download(StreamingResponse 流式)/remove(软删 + commit 后 BackgroundTasks 物理删)，6 权限点 `system:file:*` 过三集合契约 + seed 手写菜单块对标 RuoYi OSS；安全模型（defense-in-depth）：扩展名白名单 + 魔数头弱类型校验 + 边写边累计 size/sha256（不信 Content-Length）+ object_key=uuid4 分桶 + 路径穿越守卫 + Content-Disposition 注入防御（剥 CRLF/引号）+ X-Content-Type-Options: nosniff；对抗审查（Codex 二审 + adversarial agent 两独立来源）修复：P1 commit-after-unlink 数据丢失（改 commit 后 BackgroundTasks 物理删）/ P1 Content-Disposition 注入 / P2 nosniff XSS / P2 upload 孤儿清理 / object_key 不进 FileRead。排期项（spec §1）：orphan sweeper / ASGI body 上限 / 下载-删除 TOCTOU / content-type 白名单 / OOXML 深度校验 / 下载审计。**P4 监控/任务全落地**（spec [`docs/specs/2026-06-10-p4-monitoring-tasks.md`](./docs/specs/2026-06-10-p4-monitoring-tasks.md)）：P4a/P4b 服务/缓存监控（psutil + Redis INFO 白名单 + 降级）+ 在线用户（活动 refresh token family 派生，login_time 取轮换原点 + 强制下线 audited，仅撤 refresh）；**P4c 定时任务**（Codex PK medium 收敛 + 人值守拍板 §4，时区 Asia/Shanghai）：APScheduler `AsyncIOScheduler` + **PG advisory leader election + DB execution claim 双层防多 worker 重复执行（红线）** + **handler registry 白名单防 RCE**（管理员只选预注册 handler_key，非任意调用串）+ 手动触发 + 执行日志。关键纪律：`scheduler_enabled` 默认 False（CRUD/手动触发不依赖调度器）、手动并发靠任务行 FOR UPDATE 串行化、orphan running 靠 stale 阈值不冻调度。P4c 排期项：6 字段秒级 cron / SIGKILL 显式启动恢复 / 自动重试，见 spec §4 非目标。⚠️ **迁移 0019 + 0016 + 0013-0015 生产/共享库迁移仍待单独授权**（仅本地 dev + CI 临时容器跑过）。P3 运营配置已落地（spec [`docs/specs/2026-06-09-p3-operational-config.md`](./docs/specs/2026-06-09-p3-operational-config.md)，经 Codex high 数据模型 PK 收敛）；关键决策：**字典数据 FK→dict_types.id + RESTRICT**（删有数据的类型 409，不级联）、**参数热更新走读穿 DB 无缓存**（单/多 worker 都正确）、单默认值 partial unique index 兜底、is_builtin 可切换解保护（对抗审查 §6 收敛）。排期项：参数多 worker 版本化缓存（性能）、value_type 强类型解析、通知富文本渲染期净化（P6）、config 敏感值脱敏，见 spec §1 非目标。P2 排期项（Redis Stream / outbox / provider 连接池 / 非 HTTP RBAC 写原子性）仍未动，见 p2 spec §8。

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
