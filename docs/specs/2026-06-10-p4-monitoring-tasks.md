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

## 4. P4c 定时任务（Codex PK 收敛后定稿）

> **待 Codex PK（medium，2026-06-10）收敛**。开放决策：① 调度库（APScheduler vs Celery beat）；② **多 worker 执行安全（roadmap P4 红线）**：单 worker / PG advisory lock / Redis 锁；③ 任务定义安全（预注册 job-registry vs RuoYi 任意调用串 = RCE 隐患）；④ 任务 + 执行日志数据模型；⑤ 调度器生命周期（main.py lifespan，基础设施红线）。
>
> 裁决处置表 + 数据模型 + 实现待 PK 结果回填。

## 5. 权限与机检（三集合一致：registry == 路由用 == seed 菜单）

| 资源 | perms | 菜单 |
|---|---|---|
| 服务监控 | `system:server:list` | monitor:server（C，只读单视图） |
| 缓存监控 | `system:cache:list` | monitor:cache（C，只读单视图） |
| 在线用户 | `system:online:list` / `system:online:remove` | monitor:online（C）+ 强制下线（F） |
| 定时任务 | 待 P4c | 待 P4c |

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

### P4c

待 P4c 实现后补。

## 7. 验证（实现后跑）

- `make check`（ruff + pyright + 全单测 + import-linter C1-C8）
- `make test-integration`（需本地 DB + Redis）
- `make coverage`（fail_under=85，collector.py 100% / schemas.py 100%）
- P4a：`tests/unit/test_monitor_metrics_service.py` + `tests/api/test_monitor_metrics_api.py` + `tests/integration/test_monitor_metrics_integration.py`
- P4b：`tests/unit/test_monitor_online_service.py` + `tests/api/test_monitor_online_api.py` + `tests/integration/test_monitor_online_integration.py`
