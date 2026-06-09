# Changelog

> 每个 milestone 版本一行小结。完整 commit 历史看 `git log`；架构演进背景看
> [`doc/archive/EVOLUTION.md`](./doc/archive/EVOLUTION.md)。
>
> 本仓不强制 SemVer——v0.x 阶段所有变更都被视为 breaking 可能。第一个
> stable 版本（v1.0）后改走严格 SemVer。

## 版本号语义（v0.5.0 起）

为避免"版本号既是模板里程碑、又是自审计数器"导致语义混乱（v0.4.x 期间 22
个版本号里有 17 个是自审 close），v0.5.0 起改两层口径：

| 层级 | 命名 | 进 CHANGELOG | 进 4 文档版本号 |
|---|---|---|---|
| **模板里程碑**（新能力 / 破坏性变更 / 路径切换） | `vX.Y.Z`（minor 跳） | ✅ 顶部 | ✅ |
| **自审 build**（修文档 drift / 小 lint / 守门补丁） | `vX.Y.Z-audit.N`（git tag 仅） | ❌ | ❌ |

`test_version_consistency.py` 的 regex 已只接受 `vX.Y.Z` 严格三段式（不接受
audit 后缀），自然实现"自审 build 不漂移 4 文档版本号"。

历史 v0.4.x 不追溯改名——保留作为"过渡期"记号。

## [Unreleased]

> **应用轨**（`v0.0.1`，P1 RBAC 阶段）——本仓自 `python-web-service-template`
> 派生后的独立演进；下方 `vX.Y.Z` 是模板 lineage，**非本应用发版记录**。
> 完整 commit 见 git log，路线图见
> [`docs/specs/2026-06-04-ruoyi-parity-roadmap.md`](./docs/specs/2026-06-04-ruoyi-parity-roadmap.md)。

### P4c 定时任务：APScheduler + 多 worker 安全 + handler registry（2026-06-10）

[spec](./docs/specs/2026-06-10-p4-monitoring-tasks.md) §4 · Codex PK medium 收敛 + 人值守拍板 + 4 视角对抗审查 2 轮

- **域** `domains/scheduled_task/`（迁移 0016：`scheduled_tasks` + `scheduled_task_logs`）：五层 + registry/executor/cron/scheduler 4 装备模块。新依赖 `apscheduler<4`
- **任务安全（防 RCE）**：管理员只能选代码侧预注册的 `handler_key`（registry 白名单），DB 只存 key + params_json，schema 无 `call_target/command/shell` 任意调用字段；service create/update/run 三处强制 registry 命中 + params 过 handler Pydantic schema——反 RuoYi 任意调用串
- **多 worker 安全（roadmap P4 红线，两层）**：① 进程级 **leader election**（`pg_try_advisory_lock(478270)` 专用连接，仅 leader 起 `AsyncIOScheduler`）；② 任务级 **DB execution claim**（`(task_id, scheduled_at) WHERE schedule` partial unique，兜 failover 双触发）。手动并发靠任务行 `SELECT FOR UPDATE` 串行化
- **executor 两段 session**（Codex 风险 #5）：claim（running 日志）先提交 → handler 事务外跑 → result 写终态；超时 `asyncio.wait_for`；orphan running 靠 `count_running` stale 阈值过滤不冻调度
- **cron**：仅 5 字段标准 crontab（`from_crontab`，校验器=调度构造器），拒 6/7 字段 + Quartz `?L W#`；next_run 仅单条算防永不触发 cron 的 lookahead 阻塞
- **端点** `/api/v1/monitor/jobs`：CRUD + `/{id}/run` 手动触发（audited）+ `/handlers` + `/logs`；6 perms `system:job:*` 过三集合契约；seed monitor:job 菜单
- **生命周期**：main.py lifespan，`scheduler_enabled` 默认 False（本地/CI/单测不起，CRUD+手动触发不依赖）；AsyncExitStack LIFO（stop 先于 dispose_engine）+ 优雅 drain + `_loop` 异常守护防僵尸 leader
- 测试：`make check` 537 ✓ / 8 import 契约 KEPT / `make test-integration` 189 ✓ / coverage 88%（executor/scheduler 走 integration omit，含 claim 并发去重 / leader 选举 / failover / 失败链路）
- ⚠️ 迁移 0016 仅本地 dev + CI 临时容器跑过，**生产/共享库迁移待单独授权**

### P4a/P4b 监控：服务/缓存监控 + 在线用户（2026-06-10）

[spec](./docs/specs/2026-06-10-p4-monitoring-tasks.md) · 各经 3 视角对抗审查收敛

- **服务监控** `GET /monitor/server`（`system:server:list`）：psutil 采 CPU/内存/磁盘/进程/负载；阻塞 syscall 整体下沉 `anyio.to_thread`（不阻塞事件循环），单分区读失败跳过不整体 500。新依赖 `psutil` + `types-psutil`
- **缓存监控** `GET /monitor/cache`（`system:cache:list`）：Redis `INFO` **白名单** 12 字段（不回整 dict，不泄露 executable/config/复制密钥）+ 命令统计；`asyncio.wait_for(2s)` 超时 + 不可达**降级 `available=False`**（监控面板不跟着 500）
- **在线用户** `GET /monitor/online`（`system:online:list`）+ `DELETE /monitor/online/{uuid}`（`system:online:remove`）：会话 = 活动 refresh token family 派生（roadmap §4），`login_time` 取 family **轮换原点**（min over 全部 token，非最近轮换）；分页 `family_id` tiebreaker；强制下线撤销 family 全部活动 token（镜像 `revoke_family`，reason=`forced_logout`），经 `audited_write` 织入 `rbac_write`（成功 + 失败 404 都记，target=会话 UUID + 用户名）。**仅撤 refresh**：access JWT 无状态，即时 denylist 触鉴权中间件留后续。无 IP/UA（P1.4 决策 refresh token 不落设备列，不反转）
- **core 微调**：`audited_write.target_id` 放宽 `int|None`→`int|str|None`（`_opt` 本就 `str()`，零行为变更）承载 UUID 会话目标
- 落 `domains/monitor`（系统监控 umbrella，复用 MonitorRepository 跨域读 auth/audit 先例）；新增 4 权限点 + seed 菜单 4 项；无新表（纯基础设施读 + 派生现有 auth_refresh_tokens）
- 测试：`make check` 484 ✓ / 8 import 契约 KEPT / `make test-integration` 168 ✓ / `make coverage` 87.6%（collector.py / schemas.py 100%）

### P3 运营配置：字典 + 参数 + 通知公告（2026-06-09）

分支 `p1-rbac` · [spec](./docs/specs/2026-06-09-p3-operational-config.md)（Codex high 数据模型 PK 收敛）

- **字典管理** `domains/dict/`（迁移 0015）：`dict_types` + `dict_data` 双表单域两资源，共用 `system:dict:*`。关联决策（Codex PK）：`dict_data.dict_type_id` 外键到代理键 `dict_types.id` + **`ondelete RESTRICT`**（删有数据的类型 → 409 `dict.TYPE_HAS_DATA`，service 预检，不走 DB 静默级联删配置事实）；同类型 `value` 唯一、跨类型可复用；**单默认值**（service 设默认时清同类型其它默认）；`type` 创建后不可改（防前端契约漂移）；内置类型禁删。消费契约 `GET /dict/data/type/{type}` 取启用数据渲染下拉
- **参数设置** `domains/config/`（迁移 0014）：`configs` 键值参数，`config_key` 全局唯一、内置参数禁删。**热更新决策（Codex PK）**：消费端点 `GET /configs/value/{key}` **纯读穿 DB 无缓存**——单/多 worker 都正确（READ COMMITTED + 一请求一事务，更新提交后下次读即新值），不接 `Settings`/`lru_cache`；P3 DoD「热更新生效」断言测试守门
- **通知公告** `domains/notice/`（迁移 0013）：`notices` 标题/类型/富文本/状态 CRUD，`notice_type`+`status` 双层 CheckConstraint；`content` 后端存 raw（渲染期净化是 P6 职责），集成测断言富文本原样往返
- 三域均：五层 + `audited_write` 写审计织入 + 默认 deny 权限守卫（每端点 guard，`test_route_auth_contract` 守）+ 15 权限点过 3-set 相等契约 + seed 菜单 + 每列中文 comment + 迁移零漂移
- 测试：`make check` 448 ✓ / 8 import 契约 KEPT / `make test-integration` 153 ✓ / `make coverage` 86.7%

### P2 审计持久化 + 登录日志 + 监控查询 API（2026-06-09）

`caa0f66`→`37d8eb6`（分支 `p2-audit-log`，7 commit）·
[spec](./docs/specs/2026-06-09-p2-audit-persistence.md)

- **audit_events 表**（迁移 0011）：`audit_event.v1` envelope 落库，`payload` JSONB 存完整 envelope（无损取证）+ 拆查询列；actor 无 FK 冗余快照（用户删后审计留存）；event_id UNIQUE 幂等键
- **写入路径**（Claude×Codex PK 收敛红线）：**成功审计走业务 session `begin_nested()` SAVEPOINT 原子提交**（commit 失败审计一同回滚、审计写失败不连累业务）；**失败/拒绝审计走请求缓冲 + 响应后独立 session flush**（业务已回滚、不被吞）。`AuditSink` 抽象，P2.1 可换 Redis Stream
- **login_logs 表**（迁移 0012，RuoYi `sys_logininfor` 对标）：登录全路径（成功/密码错/账号锁/限流/验证码）各落 1 条；`login_success` 扩 EventType
- **请求上下文中间件**：扩展 `RequestIDMiddleware` 灌 IP/UA/method/path 进 ContextVar，填 envelope 现恒空的 `request` 段；不裸信任 X-Forwarded-For
- **监控查询 API**：`domains/monitor/`（五层 + C1 契约）operlog/logininfor list+detail，4 权限点 + seed「系统监控」菜单
- **4 轮对抗审查收敛**（Codex high ×4 + 多视角 subagent ×7，发现 4→1→1→0）：F1 成功审计事务原子 / F2 登录连接放大 / F3 列宽溢出截断（payload 留完整）/ O1 分页上限 / R2-2 in-tx 前置 flush 防吞业务错 / R3-1 persist 先于 logger 防假成功日志
- 测试：`make check` 391 ✓ / 8 import 契约 KEPT / `make test-integration` 136 ✓ / 迁移零漂移

### P1.5 RBAC 绑定 API + 审计织入 + 安全加固（2026-06-09）

`0d38ca8` + `1bfbb29` ·
[spec](./docs/specs/2026-06-09-p1.5-rbac-binding-audit.md)

- **绑定 API**：user-role / role-menu / role-dept / user-post 关联读写端点，全部
  经 `core/rbac_audit.audited_write` 织入 `rbac_write` 审计（成功/失败均落
  `admin_platform.audit` logger）
- **权限图写收紧为超管专属**：`set_user_roles` / `set_role_menus` 加
  `_require_super_admin`（非超管 403 `auth.FORBIDDEN_BY_ROLE`）；role-dept 属数据
  范围委派，保留 scoped 操作但写前校验「新 ∪ 旧绑定」全部可见，防全量 PUT 静默
  删 scope 外数据
- **认证事务修复**：`auth.refresh()` 改 deferred-raise —— 账号停用/删除路径让
  `revoke_family` / `revoke` 先 COMMIT 再 re-raise（原先 AppError 穿透
  `session.begin()` 的 `__aexit__` 触发 ROLLBACK，安全副作用被回滚）
- **审计完整性**：`audited_write` 补 `IntegrityError → 409 framework.CONFLICT`
  分支，并发唯一约束兜底竞态也留审计
- **TOCTOU**：menu `create/update` 改父 / 转按钮前先 `acquire_tree_lock`
  （`pg_advisory_xact_lock`），父类型校验与写纳入同一 xact
- **其它加固**：dept 越权防护、登录防护（验证码 / 限流）默认开、route 鉴权契约
  测试、refresh user-lock、data_scope CTE 深度上限
- **审查方式**：5 轮 Codex high + 多视角 subagent 对抗式 review，Round-5 双路零
  新发现收敛；386 unit + 119 integration 全绿，8 import-linter 契约 KEPT

### 无人值守执行地基（2026-06-09）

`f6bc3ce` · [doc](./doc/operations/UNATTENDED_EXECUTION.md)

- **CI coverage gate**：`ci.yml` 新增 `make coverage` 阻塞 step（`fail_under=85`
  在 CI 通电，避免新代码 0 覆盖却 fast lane 全绿；实测 86.49%）
- **`UNATTENDED_EXECUTION.md`**：异步执行副作用隔离——三层防御（L1 团队权限基线
  / L2 supervisor 严格 allowlist / L3 物理隔离）+ 可逆-不可逆边界（commit 随便做、
  `push` 是 review 前红线）+ NIGHT_LOG + 诚实边界
- **`.claude/settings.json`**：团队权限基线（allow 安全操作 + deny 红线如
  `git push --force` / `git add -A` / `rm -rf`）；`settings.local.json` 已
  gitignore（per-developer）
- **`scripts/unattended/`**：supervisor + queue（A1–P1T 任务 DAG）+ R1/ME1/P1T
  任务 prompt 入库

## [v0.5.3] — 2026-05-19

**JWT Bearer 鉴权中间件（ADR §5 落地）**

新增 `core/auth.py`：`AuthMiddleware` + `get_optional_current_user()` / `require_current_user()` Depends。默认关闭（`APP_AUTH_ENABLED=false`）保持向后兼容。iss/aud 校验默认 off（等 Q4 决议）。

- 基础设施：`pyjwt>=2.12`；`config.py` 6 个 auth 字段 + secret 非空/长度校验
- 错误码：`auth.TOKEN_INVALID` / `TOKEN_EXPIRED`（middleware 使用）；`FORBIDDEN_BY_ROLE` / `FORBIDDEN_BY_SCOPE`（常量已定义，鉴权逻辑待业务层接入）
- 安全：空 secret 拒绝启动（fail-fast）；HS* 强制 ≥32 bytes
- RequestID：AuthMiddleware 在 RequestID 内层，401 响应带 `X-Request-ID` + body `request_id`
- CORS：只放行真实 preflight（Origin + Access-Control-Request-Method），普通 OPTIONS 仍需鉴权
- 依赖拆分：`get_optional_current_user`（fail-open）/ `require_current_user`（fail-closed）
- 测试：24 条 auth 测试（28 collected，含 token 验证 + iss/aud + preflight + request-id + Depends）
- OTel SDK：`core/observability.py` — 默认关闭，`APP_OTEL_ENABLED=true` 开启 OTLP exporter；`RequestIDMiddleware` 每请求创建 span，`span_id` / `trace_id` 注入 access log extra
- 已知债：`BaseHTTPMiddleware`（#13）；幂等 cache-before-commit（#12）；auth middleware 在路由前 O(N)（#11）

## [v0.5.2] — 2026-05-18

**generator 模板 + core/db/health 既有代码 docstring 全量中文化**

v0.5.1 落地的「代码 docstring 默认简体中文」规则只覆盖 v0.5.1 新加 / 修改的代码（tag / todo / 测试 / 文档）。基础设施侧 `scripts/new_module.py`、`core/idempotency.py`、`core/errors.py` 等是 v0.5.0 之前的债，docstring 仍是英文 —— 业务团队 `make new-module` 生成的代码还是英文。v0.5.2 清掉这部分：

- **`scripts/new_module.py`**（1028 行）：所有 `TEMPLATE_*` 字符串内的 docstring / 注释翻成中文，`_patch_alembic_env` 等核心函数 docstring 同步翻；保留 placeholder（`{name}` `{Name}` `{NAME_UPPER}` 等）+ 错误码字面量 + CLI 错误消息（user-facing 英文契约）原貌
- **`core/idempotency.py`**（392 行）：Stripe 风格幂等的两阶段存储 / fail-open 故障模式 / `@idempotent` 装饰器陷阱说明全部翻
- **`core/errors.py`**（237 行）：ProblemDetail 8 字段说明 / AppError docstring / 4 个 exception handler 注释翻
- **`core/config.py`**（125 行）：Pydantic Settings 优先级 / URL scheme validator / pool 边界理由翻
- **`core/middleware.py`**（121 行）：RequestIDMiddleware + W3C trace-id + ClientDisconnect 处理注释翻
- **`core/logging.py`**（68 行）：JSON 日志格式 + ADR §9 字段说明翻
- **`db/base.py`** / **`db/engine.py`** / **`db/session.py`**（114 行总）：lazy="raise" 策略 / 事务边界文档翻
- **`api/v1/health.py`**（93 行）：3 个 probe 端点 + 503 secret 屏蔽注释翻

业务团队从 v0.5.2 起 `make new-module name=ledger` 生成出来的 domain 代码 docstring 直接是中文，无需手工补翻。

**保留英文的部分**（仍按 AI_CODING_RULES.md §0 规则）：
- 代码 identifier / 类名 / 函数名 / 变量名
- 错误码字面量（`service_name.TODO_NOT_FOUND` / `framework.INTERNAL_ERROR` 等）
- 三方框架专有名词（`BaseHTTPMiddleware` / `selectinload` / `RFC 9457` / `ADR §1` 等）
- generator CLI 的 `argparse` help 文本（user-facing 英文 — 这是契约不是注释）

验证：`make check` 153 ✓ / `make smoke-generator` OK ✓ / `make test-integration` 28 ✓

## [v0.5.1] — 2026-05-18

**第二个 example domain — todo ↔ tag 多对多 + N+1 守门**

v0.5.0 把 `todo` 作为单 domain 蓝本落地后，业务团队第一个真实 PR 通常涉及
跨 domain 关联（外键、多对多、N+1 守门）。当前蓝本只覆盖单 domain，业务
团队的关联模式 PR 没有正面例子可对照。v0.5.1 关闭这个缺口：

- **新增 `tag` domain**：独立 CRUD + name UniqueConstraint + `name=...
  TAG_NAME_DUPLICATE`（与 todo 同模式）
- **多对多关联 todo↔tag**：
  - Core `Table` 定义 `todo_tags`（不用 Association Object，因为 edge
    无业务字段）+ ondelete=CASCADE
  - `Todo.tags: Mapped[list[Tag]] = relationship(secondary=todo_tags, lazy="raise")`
  - Repository 所有读路径用 `selectinload(Todo.tags)` 预加载
  - 跨 domain：`TodoService(todo_repo, tag_repo)` — 持有对方 repository
    而非 service，依赖方向无环、共享 AsyncSession
- **TodoCreate/Update.tag_ids**：None=不动 / []=清空 / list[int]=全替换。
  缺失 id → 422 `TODO_TAG_NOT_FOUND`（all-or-nothing，避免静默丢失）
- **N+1 守门**：`test_list_todos_with_tags_does_not_trigger_n_plus_1` 用
  SQLAlchemy `before_execute` event hook 计数 SELECT，10 行约 ≤ 8 query
- **migration 0003**：tags 表 + todo_tags 关联表（FK CASCADE + 显式 index）
- **EXAMPLE_DOMAIN.md 加「Multi-domain pattern」段**：5 个核心选择 +
  「when NOT to follow this pattern」边界说明
- **测试统计**：unit + api 135 → 153（+18） / integration 17 → 28（+11，
  含 tag CRUD + 关联 E2E + N+1 守门）

## [v0.5.0] — 2026-05-18

**模板可用性 milestone — 从骨架到"5 分钟跑通完整 CRUD"**

之前的模板提供了 A+ 级 `core/` 基础设施 + 14 项 KNOWN_DEVIATIONS 治理 +
302 行技术债追踪，但 `domains/` 是空的——业务团队 fork 后看不到任何"我该
怎么写第一个 endpoint"的范例，generator 出来的代码没有蓝本对照。本版本
关闭这个核心缺口：

- **新增 example domain `todo`**：完整 CRUD（5 文件 + 13 测试 + Alembic
  migration），扩展 generator 默认骨架，加入业务字段（`title`
  `UniqueConstraint` + `status: StrEnum` + `due_at: Optional`）和业务规则
  （title 唯一性 → 409 `service_name.TODO_TITLE_DUPLICATE`）
- **新增 `doc/architecture/EXAMPLE_DOMAIN.md`**：解释 `todo` 每一行选择的
  理由（为什么 `UniqueConstraint` 是 backstop / 为什么 service 做预检 /
  为什么 `@idempotent` 必须在最内层）
- **`doc/INDEX.md` 加「🚀 5 分钟新手路径」**：从 `git clone` 到调通
  `POST /api/v1/todos` 的最短路径
- **`main.py` 挂载 `todo_router`**：模板开箱即用 `/api/v1/todos`，业务
  团队真接入时按 `main.py` 注释删掉即可
- **版本号语义收敛**：本文件顶部新增「版本号语义」章节，区分模板里程碑
  与自审 build
- **撤回前一轮"3.14 floor 风险"提议**：经实测无 Python 项目资产 → 维持
  `>=3.14`；同时 `~/.claude/CLAUDE.md`「技术栈」段从"默认 Python"改为
  "按需求选型"（项目级 / 全局 / Python rules 三处同步）

**v0.5.0 自审 reality check（2026-05-18，post-release）**：原计划 v0.5.1
重写两个 middleware 关闭 KNOWN_DEVIATIONS #11/#12/#13——**撤回**。重读
deviation 描述发现这三项自己就明确"触发条件未到不修"（#11 路由 ≥ 500 +
QPS > 500 / #12 业务侧 DB-level table 才是正确性 SoT / #13
`is_known_to_break ≠ breaking_now`）。提前重写 = 逆策略 + 完美主义陷阱。
保留监控信号触发后再做。

## [v0.4.22] — 2026-05-17

**依赖全量刷新 + pyproject floor 跟齐 lockfile**

`uv lock --upgrade` 实际拉到的 3 个 patch/minor：

- `click 8.3.3 → 8.4.0`（FastAPI CLI 间接依赖）
- `ruff 0.15.12 → 0.15.13`
- `uvicorn 0.46.0 → 0.47.0`（Dockerfile 三个生产 flag `--proxy-headers / --forwarded-allow-ips / --no-access-log` 实测仍受支持，无需改 CMD）

`pyproject.toml` `dependencies` / `dev` floor 全部跟齐 lockfile 当前锁定的 minor，避免 fork 模板的业务用 `uv add` 时被解析器拉一个老版（老版不在守门测试覆盖范围内）：

| 包 | floor before | floor after |
|---|---|---|
| fastapi[standard] | >=0.115 | >=0.136 |
| pydantic | >=2.7 | >=2.13 |
| pydantic-settings | >=2.3 | >=2.14 |
| sqlalchemy[asyncio] | >=2.0 | >=2.0.49 |
| asyncpg | >=0.29 | >=0.31 |
| alembic | >=1.13 | >=1.18 |
| redis[hiredis] | >=5.0 | >=7.4 |
| pyright | >=1.1 | >=1.1.409 |
| ruff | >=0.6 | >=0.15 |
| pytest | >=8 | >=9 |
| pytest-asyncio | >=0.23 | >=1.3 |
| pytest-cov | >=5 | >=7 |
| pytest-mock | >=3.14 | >=3.15 |
| httpx | >=0.27 | >=0.28 |
| pre-commit | >=3.7 | >=4 |

守门全绿：`make check`（121 passed）/ `make smoke-generator`（129 passed）/ `STRICT_REDIS_INTEGRATION=1 pytest -m redis_integration`（5 passed）/ `make audit`（No known vulnerabilities）。

`DEPENDENCY_UPGRADE.md` 同步 floor 实际数字（避免读者困惑"为什么文档说 redis 5.x 稳定但 floor 7.4"）。

## [v0.4.21] — 2026-05-17

**第九轮自审 close：实测路径 + OpenAPI/CI 守门补完**

第九轮**真跑代码**而不是 grep：

- 起一个 generator 生成的 service + 抽 `app.openapi()` 实际 JSON，验证 POST `/api/v1/probes` 真含 `{201, 400, 409, 422}` 全部 ref 到 `ProblemDetail`、PATCH 真含 `{200, 404, 422}` — 前 8 轮加的设计真工作
- `envsubst < examples/k8s/deployment.yaml` 渲染 7 个 K8s 资源全部 parse 通过，无未解析占位

实测找到的真问题：

P1 (2 项)：
- 503 错误响应路径**没有断言** `X-Request-ID` 响应头：`test_readyz_returns_503_when_db_ping_fails` / `_redis_ping_fails` 只验 body 字段。中间件改链顺序后头丢失没人能抓到。两个 503 测试 + healthz 200 各加 `assert response.headers["X-Request-ID"]`
- `/readyz` `/healthz` `/startupz` 都裸 `@router.get(...)` 没 `responses=`，SDK 看不到 503 → ProblemDetail 路径；只看到自动推导的 200 dict。修：`/readyz` 加 `responses={503: {"model": ProblemDetail}}`，新 contract test `test_readyz_advertises_503_problem_detail_in_openapi` 守门

P2 (2 项)：
- CI 之前只跑 `make check`，**从未跑过** `pre-commit run --all-files`——加 fast lane 末尾一步。立刻抓到一个潜伏 bug：`examples/k8s/deployment.yaml` 多 doc 触发 `check-yaml` fail（K8s manifest 标准用 `---` 分多 resource），修 `.pre-commit-config.yaml` 加 `--allow-multiple-documents` flag
- `DEPLOYMENT.md` readyz 段：把 200/503 body 写成对照表（之前只有 503 描述，新人配 K8s readinessProbe 时不知道 200 body 长啥样）

> 关键洞察：前 8 轮 review 全靠 grep + 推理，第九轮**真跑**才发现 OpenAPI 显式声明缺、pre-commit hooks 漂移。"做绝"标准下，每轮都应该至少跑一遍生成器 + 抽 schema + 跑 pre-commit hooks。

## [v0.4.20] — 2026-05-17

**第八轮自审 close：onboarding 痛点 + 运维实操 + 文档死角**

P1（3 项）：
- `LOCAL_SETUP.md` 三步验证 → 四步（加 `uv run pre-commit install` 显式），
  README 快速开始同步；新单测
  `test_onboarding_doc_mentions_pre_commit_install` 守门防回归
- `redis_integration` 测试 fixture 加 `STRICT_REDIS_INTEGRATION=1` 开关：
  CI 强制 fail-not-skip（避免 Redis 不可达时静默 skip 让 CI 假绿）；
  本地 default skip 行为不变；`.github/workflows/ci.yml` db lane 自动设
  + 单独跑 `pytest -m redis_integration` step；LOCAL_SETUP 加显眼警示
- `examples/k8s/deployment.yaml` 完整模板（Namespace / ConfigMap /
  Secret / Service / Deployment / HPA / PDB），含 preStop drain /
  read-only rootfs / non-root uid / drop all caps 的 CIS baseline；
  `envsubst` 替换 `${SERVICE_NAME}` `${IMAGE}` `${REPLICAS}` 即可 apply；
  DEPLOYMENT.md probe 段加链接

P2（4 项）：
- `KNOWN_DEVIATIONS.md` #12 加 Redis 拓扑适用范围表（单节点 / 主从 /
  Cluster / Sentinel / 多区域 active-active 5 种语义差异 + 推论"对外
  不可重放业务必须 DB-level table 兜底，Redis 拓扑随便选"）
- `DEPLOYMENT.md` 多 worker 口径统一：sizing 表"按需 --workers N" →
  "单 worker per pod"，第 100 行警示扩写为完整解释（pool 乘数失控 +
  lifespan eager_probe 多 worker 各自跑导致部分失败 K8s 仍 ready）
- generator name 报错友好化：`name=OrderItem` 自动建议 `order_item`，
  reserved name 报错列出所有保留名清单；2 个新单测守门
- 新增 `doc/operations/DEPENDENCY_UPGRADE.md`：核心依赖（FastAPI /
  Starlette / Pydantic / SQLAlchemy / Alembic / asyncpg / redis-py /
  uvicorn / ruff / pyright / Python / uv）逐项升级 caveat + 升级 SOP
  + CVE 紧急通道 + 跨服务协同建议；INDEX.md 同步链接

## [v0.4.19] — 2026-05-17

**Python 3.13 → 3.14 硬升 floor**

`requires-python = ">=3.14"` / `[tool.ruff].target-version = "py314"` /
`[tool.pyright].pythonVersion = "3.14"` / `.python-version = 3.14` /
Dockerfile `python:3.14-slim`（builder + runtime 两层）/ CI
`PYTHON_VERSION: "3.14"` / 文档（PROJECT_OVERVIEW / CI_MIGRATION /
DEPLOYMENT / LOCAL_SETUP）全部刷新。

为什么硬升 floor 而不双轨：符合全局 rules "默认 3.14，3.13 仅维护
老项目"；模板生成的新业务直接走 3.14，避免双轨期模板代码不能用
3.14-only 语法（如 PEP 758 `except` parenthesized）的限制。已有
3.13 业务 fork 模板会失败——这是预期。

dry-run 验证：scratch 复制 + 切 3.14 后 `make check` / `make audit` /
`make test-integration` (含 redis_integration) / `make smoke-generator`
全部干净。所有核心依赖（FastAPI / Pydantic v2 / SQLAlchemy 2.x /
Alembic / Redis / asyncpg / uvicorn / structlog）均支持 3.14。

## [v0.4.18] — 2026-05-17

**第七轮自审 close：上一轮自己引入的 P0 + 装饰器陷阱守门**

P0：
- generator 注释和 `CODE_GENERATOR.md` 把不存在的 `framework.IDEMPOTENT_KEY_REPLAY_MISMATCH` 写当成 422 错误码（v0.4.17 自引）→ 全改成真实的 `framework.IDEMPOTENCY_KEY_REUSED`；新单测 `test_generator_text_only_cites_real_framework_codes` 以 `core/idempotency.py` + `core/errors.py` 为 SoT 守门 generator 文本里出现的所有 `framework.*` 字面量

P1：
- `@idempotent` 装饰器顺序陷阱：marker decorator 在裸 wrapper（不调 `functools.wraps`）下面会丢 attribute → middleware 静默禁用幂等 → 重试重复扣款。修：docstring 重写解释 wraps vs 裸 wrapper 的差异 + 推荐"innermost decorator" 位置；generator 模板注释同步；2 个新单测分别守"wraps 透传 OK" + "裸 wrapper 丢"
- `_replay()` 的 `status_code` 复用只测了 200 不测 201：generator 默认 POST 是 201 Created，未来谁误改 `_cache_and_return` 漏存 status_code 会 fallback 到 200 → 客户端按 201 分支出错。新 integration 测试 `test_redis_replay_preserves_201_created_status` 用 201 endpoint 显式锁定

P2：
- KNOWN_DEVIATIONS 加 `#14 _serialisable_headers collapse 多值响应头`：业务接 Set-Cookie / Server-Timing 类多值响应头到 idempotent POST 时丢；附自动升 P1 信号（cookie 监控 alert / code review grep）
- 四处文档（README / AGENTS / CLAUDE / PROJECT_OVERVIEW + AI_CODING_RULES）测试数字（106/106 / 113/113 / 9/9）模糊化成"`make check` 全绿"——避免每加一两个测试就 churn 文档

## [v0.4.17] — 2026-05-17

**第六轮自审：发版口径 + 模板交付配置 + CI 阻塞口径 + generator OpenAPI 完整**

P1（4 项）：
- **版本口径统一到 v0.4.16**：README / AGENTS / CLAUDE / PROJECT_OVERVIEW 全部刷新；
  新 `tests/unit/test_version_consistency.py` 以 CHANGELOG 顶部为 SoT 守门四处文档不漂移；
  `pyproject.toml [project].version` 明确是"业务实例初始版本"，与模板里程碑版本不同源
- **`.env.example` 补全**：加 `APP_SERVICE_ID` / `APP_STARTUP_EAGER_CONNECT` /
  `APP_IDEMPOTENCY_ENABLED` / `APP_REDIS_URL` / `APP_IDEMPOTENCY_TTL_SECONDS` /
  `APP_IDEMPOTENCY_LOCK_TTL_SECONDS`；新测试 `test_env_example_covers_all_settings_fields`
  以 `Settings.model_fields` 为 SoT 守门（缺 / 多都 fail）
- **`pre-commit` 入 dev deps**（>=3.7）：`.pre-commit-config.yaml` 写的
  `uv run pre-commit install` 现在真能跑通；之前没声明 dep 导致全新克隆撞 `Failed to spawn`
- **CI audit 口径对齐**：`CI_MIGRATION.md` 改"continue-on-error 不阻塞" → "阻塞 + `--ignore-vuln` 紧急通道"，
  与 Makefile / reference CI 一致；同时删 `.workflow/` `Jenkinsfile` "待建"占位描述
  （ADR Open Q11 未决前，占位空文件比"缺"更误导）；DB lane 加 Redis service / 加 generator lane

P2（3 项）：
- **Generator POST / PATCH OpenAPI 完整**：POST 用新 `IDEMPOTENT_POST_ERROR_RESPONSES`
  显式声明 400 / 409 / 422（middleware 拒绝路径 FastAPI 不知道），PATCH 用 `PATCH_ERROR_RESPONSES`
  显式声明 404 + 422，让 `_custom_openapi` 接力把 schema rewrite 成 ProblemDetail；
  3 个新单测守门
- **`CODE_GENERATOR.md` drift 修**："与 v0.4.7 对齐" → v0.4.16；POST 示例加 `@idempotent` +
  `responses=IDEMPOTENT_POST_ERROR_RESPONSES`；删除"留给用户：注册 ORM 到 env.py"行
  （v0.4.13 起自动 patch）
- **`KNOWN_DEVIATIONS.md` 触发器**：#11 / #12 / #13 每条加"自动升 P1 信号"小节
  （监控指标 / Grafana alert / 代码 review checklist），把"何时必须升 P1"从口头共识变成可观测条件

工程基础：
- `ruff` `tests/**` per-file-ignores 加 `RUF001/002/003`（中文全角符号在测试 docstring 是惯例）

## [v0.4.16] — 2026-05-17

**Generator 端到端烟测 + 模板 fmt 漂移修复**

- 新 `make smoke-generator`：一键跑 `new-module name=smoke_probe with-model=1` → `make check` → 自动清理；trap-based cleanup + 工作区脏/目标已存在 双重 abort 防线。结构上把"generator 输出能不能直接过质量门"变成可自动验证的目标
- 用 smoke 立刻抓到一个潜伏 bug：长模块名（11 字符）下 `update_{name}` 路由签名超过 ruff 100 列上限 → 拆成多行；短名（如 `order`）刚好不触发，所以历次 review 没看到
- `make smoke-generator` 写进提交前自检清单（AI_CODING_RULES.md §7）

## [v0.4.15] — 2026-05-15

**第五轮自审：端到端用户视角**

实地跑 `make new-module name=order with-model=1` → `make check` 复现新人流程，发现 v0.4.13 generator auto-patch 的 import 后缺 blank line → ruff `I001` (isort) 立刻 fail。一行 fix（`import_line + "\n\n"`）+ 守门防回归。模板"开箱即过 check"承诺补回。

## [v0.4.14] — 2026-05-15

**第四轮自审：边界硬化**

- **uvicorn 生产参数**：Dockerfile CMD 加 `--proxy-headers --forwarded-allow-ips=*`（K8s ingress 真实 client IP / scheme）+ `--no-access-log`（去重，保留自定义 JSON access log）
- **Idempotency-Key 长度上限 255**：`framework.IDEMPOTENCY_KEY_INVALID` 400；防止 1MB key 撑爆 Redis
- **Settings 字段范围 + URL scheme 校验**：`Field(ge/le)` for `db_pool_size` / `db_max_overflow` / `idempotency_ttl_seconds` / `idempotency_lock_ttl_seconds`；`@field_validator` for `database_url` / `redis_url` scheme 白名单
- **工程基础**：`.python-version` (3.13) / `.pre-commit-config.yaml` (ruff + 常规 hooks) / `CHANGELOG.md` 首版
- **OpenAPI**：`securitySchemes.bearerAuth` 占位（JWT 业务接入零摩擦）
- **DEPLOYMENT.md**：加 request body size limit 段（ingress 层兜底而非 service 自检）

## [v0.4.13] — 2026-05-15

**第三轮自审**

- **P1 真安全 bug**：`_validation_error` 422 响应回显 Pydantic `errors[].input`（password / API key / token 明文）→ 框架级 strip
- generator 自动 patch `migrations/env.py` model import（解决"忘加 import 后 alembic check 静默通过"踩坑）
- 3 处文档 drift 修；coverage 实测 91.41% → `fail_under` 70 → 85
- 归档 #13：BaseHTTPMiddleware 长期架构债

## [v0.4.12] — 2026-05-15

**第二轮自审：一锅 close P1+P2**

- lifespan startup-failure 路径资源不泄漏（eager probe 进 AsyncExitStack）
- CI: audit 阻塞 / redis profile / check-db 顺序前移
- generator 生成的 API test 挂 RequestIDMiddleware（错误响应 request_id 一致）
- ruff 加 S/ASYNC/T20；TEMPLATE_MODELS `__table_args__` 占位；alembic `compare_server_default=True`
- 4 项 Redis-backed Idempotency E2E（SET NX / replay / 409 / 422 / TTL 真行为）
- DEPLOYMENT.md：限流 / metrics / graceful-shutdown 边界
- ClientDisconnect → 499（access log 区分客户取消）

## [v0.4.11] — 2026-05-15

**P0 修复**

- **`get_session` 真起 transaction**（`async with session.begin():`）—— pre-v0.4.11 generator 服务写操作**静默丢数据**
- 3 项 integration 守门（commit / rollback / nested savepoint）
- /readyz 加 Redis ping（fail-closed）/ Dockerfile 缓存层 + tini / lifespan AsyncExitStack / fixture 真清 engine / pytest-cov / trace-id 防全 0 / DB pool sizing 文档 / compose env 化

## [v0.4.10] — 2026-05-15

- v0.4.9 review 闭环：`APP_IDEMPOTENCY_LOCK_TTL_SECONDS` 可配；generator POST 模板 OpenAPI 声明 409

## [v0.4.9] — 2026-05-15

**Idempotency B 方案**

- cache-replay → **SET NX in-flight lock + cache-replay** 两阶段
- **same-key + 不同 body 返 422**（pre-v0.4.9 是静默 re-execute，金额扣减场景双发）
- 文档明确 Redis lock 不能替代 DB idempotency_keys 表（KNOWN_DEVIATIONS #12）

## [v0.4.8] — 2026-05-14

- close P2 review findings：generator update PATCH 语义、`log_level` Literal 校验
- backfill KNOWN_DEVIATIONS #9 / #10

## [v0.4.7] — 2026-05-14

- close KNOWN_DEVIATIONS #4 / #5 / #6（access log 守门 / eager connect opt-in / span_id 占位）

## [v0.4.6] — 2026-05-14

- close KNOWN_DEVIATIONS #1 / #2 / #3（@idempotent 默认 / `service_id` 字段 / OpenAPI 404 schema）

## [v0.4.5] — 2026-05-14

- 知识库重组（仿 shopsell-server 7 目录）

## [v0.4.0 – v0.4.4]

- ADR Python follow-up #1（分页 envelope）/ #2（Idempotency-Key）/ #3（traceparent）/ #4（startupz）逐项落地

## [v0.3 – v0.3.3]

- 多轮 fellow-agent review + AppError breaking change + OpenAPI 422 schema 修正 + CI 平台说明

## [v0.1 – v0.2]

- 初始 scaffold + generator + 跨语言 ADR
