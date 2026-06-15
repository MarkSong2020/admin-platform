# P4 监控/任务 spec —— 服务/缓存监控 · 在线用户 · 定时任务

> 对标 RuoYi「系统监控」：服务监控 / 缓存监控 / 在线用户 / 定时任务。
> roadmap：[`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md) §P4（line 169 DoD / 177 红线 / §7 Q4·Q10）。
> 分子阶段落地（按风险低→高）：**P4a 服务+缓存监控**（只读，无 DB）→ **P4b 在线用户**（派生 + 强退写）→ **P4c 定时任务**（新依赖 + 多 worker 安全，Codex PK）。

## 1. 范围与验收口径（roadmap §P4 DoD）

> DoD（roadmap line 169）：定时任务可增删改查 + 手动触发 + 执行日志；`/monitor` 返回真实 CPU/内存/Redis 指标。

| 子阶段 | 范围 | 状态 |
|---|---|---|
| P4a | 服务监控（psutil：CPU/内存/磁盘/进程）+ 缓存监控（Redis INFO 摘要 + 命令统计），只读单视图 | ✓ |
| P4b | 在线用户：活动 refresh token family 派生会话列表 + 强制下线（撤销 family） | ✓ |
| P4c | 定时任务：APScheduler + job 注册表 + CRUD + 手动触发 + 执行日志（多 worker 安全） | 待做（Codex PK） |

**非目标 / 排期**：数据监控（RuoYi Druid SQL 监控，§7 Q3 待定）；access token 即时 denylist（强退当前只撤 refresh，触鉴权中间件留后续）；服务监控限流/缓存（admin-only 读，暂不需要）。

## 2. P4a 服务/缓存监控（实现）

无新表（纯基础设施读）。落 `domains/monitor`（系统监控 umbrella，复用 MonitorRepository 跨域读先例）：

- `collector.py` `SystemMetricsCollector`：psutil 阻塞调用整体下沉 `anyio.to_thread.run_sync`（ASYNC lint：不阻塞事件循环）；Redis 调用 `await`。单分区读失败（权限/挂载不可达）跳过不整体 500。
- `service.py` `SystemMonitorService`：服务监控直采；缓存监控 `asyncio.wait_for(timeout=2s)` + Redis 不可达/超时降级 `available=False`（监控面板要能显示「缓存挂了」，不跟着 500）。
- `api.py`：`GET /api/v1/monitor/server`（`system:server:list`）+ `GET /api/v1/monitor/cache`（`system:cache:list`），只读单视图。
- Redis INFO **白名单**取 12 个具名字段（version/mode/uptime/clients/memory/hits/misses/...），**不回整个 INFO dict**（不泄露 executable/config_file/复制密钥线索）。

## 3. P4b 在线用户（实现 + 设计决策）

**会话源 = 活动 refresh token family**（roadmap §4 已定「依赖 token/session 落库，与 P1 refresh token 联动」）。一次登录 = 一 family；活动 = 有≥1 未撤销且未过期 token。

| 决策 | 取舍 |
|---|---|
| 会话源 | 派生 `auth_refresh_tokens`（命中 `ix_auth_refresh_tokens_user_active`），**不新建会话表** |
| login_time | `min(issued_at)` over family **全部 token** = 原点（轮换撤销旧 token，若只算活动 token 会把登录时间算成最近轮换时间——核心正确性） |
| 强制下线 | 撤销 family 全部活动 token（镜像 `auth.revoke_family` UPDATE，reason=`forced_logout`）。**仅撤 refresh**：access JWT 无状态，当前 access token 到期前仍有效（≤access TTL 窗口）；即时踢出需 denylist 触鉴权中间件，留后续 |
| IP/UA | **不展示**：P1.4 决策「device 信息只审计不强绑定校验」，refresh token 不落 ip/ua 列；不反转该决策、不加迁移 |
| 落点 | `domains/monitor`（MonitorRepository 跨域读/写 `auth_refresh_tokens`+`users`，与既有跨域读 audit/login 先例一致） |
| 审计 | 强退经 `audited_write` 织入 `rbac_write`（成功 + 失败 404 都记，target=会话 UUID + 用户名） |
| core/ 微调 | `audited_write.target_id` 放宽 `int|None`→`int|str|None`（`_opt` 本就 `str()`，**零行为变更**），承载 UUID 会话目标 |

端点：`GET /api/v1/monitor/online`（`system:online:list`）+ `DELETE /api/v1/monitor/online/{session_id}`（`system:online:remove`，path UUID 校验 → 422）。

## 4. P4c 定时任务（Codex PK medium 收敛 + 人值守拍板）

> 命中多红线（main.py 基础设施 / 新依赖 APScheduler / 多 worker「P4 拍板」/ 新迁移），经 Codex PK
> medium 收敛 + 用户拍板（提交 P4a/P4b 后做 P4c；时区 **Asia/Shanghai**）。

落 `domains/scheduled_task` 五层 + 4 个「装备」模块（registry/executor/cron/scheduler）+ 迁移 0016。

| 决策 | 取舍（Codex PK §1-5）|
|---|---|
| 调度库 | **APScheduler `AsyncIOScheduler`**（roadmap 已定，轻），反对 Celery beat（需 broker/worker 整套异步平台，超 DoD）。显式 `max_instances=1/coalesce=False/misfire_grace`，**不用 SQLAlchemyJobStore**（序列化 callable 与安全模型冲突） |
| 任务定义安全 | **代码侧 `JobHandlerRegistry` 白名单**：DB 只存 `handler_key`+`params_json`，schema 无 `call_target/command/shell` 等任意调用字段，service create/update/run 三处强制 `registry.get` 命中 + params 过 handler Pydantic schema——**反 RuoYi 任意调用串（RCE）** |
| **多 worker 安全（红线，两层）** | ① 进程级 **leader election**（`pg_try_advisory_lock(478270)` 专用连接，仅 leader 起 scheduler）；② 任务级 **DB execution claim**（`scheduled_task_logs (task_id, scheduled_at) WHERE schedule` partial unique，兜 failover 双触发）。`_fire` 的 scheduled_at 截断到分钟保 failover 同 tick 同值 |
| executor | **两段 session**：claim（建 running 日志）先提交 → handler 事务外跑（不长持事务）→ result 写终态。手动并发靠任务行 `SELECT FOR UPDATE` 串行化（manual 无 partial unique）；orphan running 靠 `count_running` stale 阈值过滤不冻任务 |
| cron | 仅 5 字段标准 crontab（`from_crontab`，校验器=调度构造器），拒 6/7 字段 + Quartz `?L W#`；6 字段秒级 dow 约定冲突留排期。next_run 仅单条算（list 不算，防永不触发 cron 的 lookahead 阻塞） |
| 数据模型 | `scheduled_tasks`（name 唯一 / handler_key / params jsonb / cron / status / allow_concurrent / misfire / timeout / last_run）+ `scheduled_task_logs`（execution_id uuid / trigger schedule·manual / status 6 态 / FK SET NULL 保留历史 / partial unique claim） |
| 生命周期 | main.py lifespan：`scheduler_enabled` 默认 **False**（本地/CI/单测不起，CRUD+手动触发不依赖）；start/stop 经 AsyncExitStack（LIFO：stop 先于 dispose_engine）；优雅 drain（grace 秒等 in-flight）；`_loop` 异常守护防僵尸 leader |

端点：`/api/v1/monitor/jobs` 下 list/get/create/update/delete + `/{id}/run`（手动触发）+ `/handlers`（可选 handler）+ `/logs`（执行日志）。perms `system:job:list/query/add/edit/remove/run`。内置 handler：noop / echo / cleanup_expired_refresh_tokens。

**非目标 / 排期**：6 字段秒级 cron；SIGKILL 后显式启动恢复（标 abandoned，已有 stale 过滤兜底不冻调度）；自动重试；独立 scheduler 进程；**stale 过滤的固有权衡**——治「孤儿冻死任务」必然重开一个等于「timeout↔实际完成」间隙的并发窗口（handler 实跑超过 `timeout_seconds` 且 `wait_for` 尚未 trip 时，`count_running` 漏算它），极小 timeout 下可能短暂违反 `allow_concurrent=False`；彻底消除需显式启动恢复（标 abandoned），留后续。

**调度器自治执行不进统一审计流**（对抗审查 P1-B，2026-06-11 用户拍板「先 spec 声明边界」）：HTTP 手动触发（`POST /{task_id}/run`）经 `audited_write` emit `rbac_write` 成功审计；但**调度器后台自治触发**（`scheduler._fire`→`executor.run`，`trigger_type="schedule"` / `actor_user_id=None`）只写 `ScheduledTaskLog` 域内执行日志（对标 RuoYi `sys_job_log`，含 task_id / 状态 / started_at / 输出 / 异常），**不产生 `audit_event`**。这是有意边界：`audit_events` 是 **HTTP 操作审计流**（含 actor / IP / UA / request_id），自治执行无 HTTP 上下文、无 request session，`record_audit_committed` 在非 HTTP 下走 `append_audit_event` 缓冲、而无请求缓冲即 no-op（不落库）。合规追溯靠 `ScheduledTaskLog` 兜底（非完全不可追溯）。若后续要求自治执行也进 `audit_events`（跨域 operlog 可查自动任务），需在 `executor._finish` 后显式 `DbAuditSink().persist([event])` 落库（**不能**靠 `record_audit_committed` 的缓冲回退路径，那条在非 HTTP 下 no-op），留排期。

## 5. 权限与机检（三集合一致：registry == 路由用 == seed 菜单）

| 资源 | perms | 菜单 |
|---|---|---|
| 服务监控 | `system:server:list` | monitor:server（C，只读单视图） |
| 缓存监控 | `system:cache:list` | monitor:cache（C，只读单视图） |
| 在线用户 | `system:online:list` / `system:online:remove` | monitor:online（C）+ 强制下线（F） |
| 定时任务 | `system:job:list/query/add/edit/remove/run` | monitor:job（C）+ 查/增/改/删/执行（F） |

机检：`test_permission_registry`（三集合相等 + 正则 `^system:[a-z]+:[a-z]+$`）/ `test_route_auth_contract`（非公开路由必有守卫）/ `test_rbac_endpoints`（系统监控子节点数）。

## 6. 对抗审查处置（每子阶段 3 视角 subagent loop 收敛）

### P4a（正确性·async / 安全·分层·契约 / 测试充分性，2026-06-10）

| 发现 | 严重度 | 处置 |
|---|---|---|
| `get_server_metrics()` 零覆盖（唯一编排裸奔 + 合计 83% < 85%） | 高 | 补 service 透传单测 + 真实 app 集成测试 |
| `_load_avg` None 分支 / `_collect_disks` 异常跳过分支零覆盖（防 500 降级语义） | 中 | mocker patch psutil 触发两分支 |
| `wait_for` 真超时计时路径未测（只测 collector 同步抛 TimeoutError） | 低 | monkeypatch 超时阈值 + slow collector |
| PEP 758 无括号 except / Redis INFO 白名单 / C1-C8 / 权限隔离 | — | 验证正确，无需改 |

### P4b（正确性·数据 / 安全·鉴权·跨域写 / 测试充分性，2026-06-10）

| 发现 | 严重度 | 处置 |
|---|---|---|
| 强制下线**审计 emission 完全未验证**（织入断了也不红，触「写改授权不漏审计」红线） | 高 | 集成测试加 caplog 断言（成功 + 失败 404 路径的 rbac_write） |
| `list_online_sessions` 分页**无 tiebreaker**（last_active 撞值跨页漏/重） | 中 | order_by 加 `family_id` 第二排序键 |
| 分页 / count-list 口径一致性未测（repo 在 omit，SQL 全压集成） | 中 | 补多 family 分页集成测试（按 family 非 token） |
| `expires_at` family 内恒定 docstring 不准 | 低 | 修正注释（各 token expires_at 随轮换前移，仅 absolute 上限共享锚点） |
| 并发已撤销仍记 success 审计 | 低 | 终态一致、RuoYi 不区分，**跳过**（避免过度设计） |
| core/ 放宽兼容性 / admin-only / 无信息泄露 / 跨域写无遗漏 auth 副作用 | — | grep 13 调用点验证零行为变更，无需改 |

### P4c（Codex PK medium + 4 视角 subagent loop，2 轮收敛，2026-06-10）

Codex PK 收敛架构（裁决：自动执行需 leader election + DB claim 兼具；命中升级 → 人值守拍板）。round-1 4 视角发现 + round-2 验证：

| 发现 | 严重度 | 处置 |
|---|---|---|
| 手动触发并发 **TOCTOU**（count_running 检查与 claim INSERT 间无锁，manual 无 partial unique 兜底） | 高 | 任务行 `SELECT FOR UPDATE` 串行化（覆盖 manual+schedule 全组合） |
| orphan running 永久冻结任务调度（崩溃遗留 running 被永远算"在跑"） | 中 | `count_running` 加 stale 阈值（`started_at >= now - timeout/3600s`）过滤 |
| `_loop` 无异常防护 → 僵尸 leader（持锁 + 停调度 + 无 failover） | 中 | loop 体包 try/except + log，下周期重试 |
| **executor 失败链路（handler 抛异常/超时/下线）零覆盖**（omit 但 integration 也没覆盖失败） | 严重 | 补集成测试（自定义 registry 注入 raise/slow handler），验证 omit 正当 |
| "合法但永不触发" cron（2月30日）→ next_run ~4 年 lookahead 阻塞，list 批量放大 | 中 | next_run 仅单条算（list 不算，消除放大） |
| `_StubExecutor` 不返回 None（偏离真实 `ExecutionOutcome \| None` 契约） | 中 | 补 None 变体单测 → manual_run 409；claim 并发断言加强（败者走 None 非异常） |
| `_try_acquire_leader` 异常路径连接泄漏 / `scheduler_shutdown_grace_seconds` 死配置 / 列注释"5或6字段"不准 / reconcile 删·坏cron 未测 | 低 | conn close 守护 / 实现优雅 drain 用上 grace / 改"5字段标准crontab" / 补 reconcile 测试 |
| RCE 封死（schema+service+executor 三层）/ cron·tz·SQL 注入 / 分层 C1-C8 / 迁移零漂移 / 权限三集合 / 跨域 import 无循环 / lifespan LIFO | — | 验证正确，无需改 |

> round-2 验证（探针打真 DB）：6 条修复全部正确收敛、无回归/无死锁/无连接泄漏/不吞 CancelledError（FOR UPDATE 串行化手动并发 2路→1+1·4路→1+3、drain 双分支实测、list next_run 全 None）。executor 95% / scheduler 83% 实测覆盖。唯一 [低] 观察 = stale 过滤固有权衡（已入排期，见 §4 非目标），不阻塞放行。

## 7. 验证（实现后跑）

- `make check`（ruff + pyright + 全单测 + import-linter C1-C8）
- `make test-integration`（需本地 DB + Redis）
- `make coverage`（fail_under=85，collector.py 100% / schemas.py 100%）
- P4a：`tests/unit/test_monitor_metrics_service.py` + `tests/api/test_monitor_metrics_api.py` + `tests/integration/test_monitor_metrics_integration.py`
- P4b：`tests/unit/test_monitor_online_service.py` + `tests/api/test_monitor_online_api.py` + `tests/integration/test_monitor_online_integration.py`
