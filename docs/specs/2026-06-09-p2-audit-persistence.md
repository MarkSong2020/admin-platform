# P2：审计持久化 + 登录日志 — 设计 spec

> 状态：**已拍板，实现中**（2026-06-09 用户签字）。分支 `p2-audit-log`。
> 用户拍板：① 按 §7 收敛设计开工；② **不做时间分区**（普通表 + 时间索引，量大再迁移）；③ P2 **含只读查询 API**（完整 RuoYi 对标）。
> 路线图锚点：[`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md) §line 63-64 / 150 / 167 / 176 / 283-284。
> 前置：P1 已冻结 `audit_event.v1` envelope（`src/admin_platform/audit/events.py`），当前只 emit 到 logger；`emit.py` docstring 明示「P2 接中间件 + 持久化表」。

## 0. 结论先行

P2 = 给现有 audit emit **加一个 DB 持久化 sink**（不动 envelope 冻结契约）+ 补 **请求上下文中间件**（填 envelope 现恒空的 `request` 子对象）+ 建 **登录日志表**（RuoYi `sys_logininfor` 对标，登录全路径织入）。

四个数据模型决策（红线，待签字）：

| # | 决策 | Claude 独立立场（pre-Codex） |
|---|---|---|
| D1 | 表数量 / 边界 | `audit_logs`（envelope 全量镜像）+ `login_logs`（登录专用宽表）两张 |
| D2 | **写入路径**（最关键） | **独立 session 同步落库**，失败降级回 logger，**绝不同事务、绝不阻断业务**；Redis Stream 异步**推迟** |
| D3 | 上下文传递 | 请求中间件 + `ContextVar`（IP/UA/request_id 注入 envelope.request，不穿层传 Request） |
| D4 | 与 envelope 关系 | `audit_logs` 是 envelope 1:1 镜像（JSONB metadata）；`login_logs` 另起 RuoYi 对标 schema，非镜像 |

---

## 1. 现状底座（Explore 摸查，file:line 锚点）

- **envelope**：`audit/events.py:120-137`，14 顶层字段（schema_version/event_id/event_type/action/title/occurred_at_utc/actor/target/request/result/duration_ms/risk_level/metadata/redaction_applied）。EventType 4 值（`permission_denied|login_failed|rbac_write|refresh_reused`，P1 注明「可向后兼容扩展」）。脱敏双层 deny-list 已落（`events.py:29-78`）。
- **emit 路径**：`emit.py:63-74` → logger `admin_platform.audit` INFO，extra key `audit_event`；**失败吞掉不抛**（审计不阻断业务，`emit.py:73`）。
- **8 处 emit 调用点**：auth login_failed（`service.py:59-69` / `:176-188`）、refresh_reused（`refresh_service.py:144-155`）、permission_denied（`core/permissions.py:82-93`）、rbac_write（`rbac_binding/service.py:260-280` + `core/rbac_audit.py:47-82`）。
- **登录路径缺口**：成功**无 emit**、限流**无**、验证码**无**；失败/锁有。IP 取自 `api/v1/auth.py:50-51`（`request.client.host`），**UA 全仓未捕获**。**service 层拿不到 Request**（分层：仅 api 层有）。
- **持久化基建**：`db/base.py` IdMixin（BigInt PK）+ TimestampMixin（created_at/updated_at, timestamptz UTC）+ `lazy="raise"`；`db/session.py` `db_session()` = 一调用一 session 一事务（`session.begin()`）。Redis 已用于 idempotency / login_guard，**无后台任务框架**。最新迁移 `0010_p1_4_refresh_tokens`，env.py 侧 import 注册 metadata。domain 五层骨架见 `domains/post/`（models/schemas/repository/service/api/deps）。

---

## 2. D1+D4 — 表结构与边界

### 2.1 `audit_logs`（审计主表 = envelope 全量镜像）

收**所有** `emit_audit`（每次 emit 多一个 DB sink）。是完整 append-only 审计轨，覆盖 RuoYi `sys_oper_log` 超集（rbac_write/permission_denied/refresh_reused/login_failed 都进）。

| 列 | 类型 | 来源（envelope） | 备注 |
|---|---|---|---|
| `id` | BigInt PK | — | IdMixin 代理键 |
| `event_id` | UUID/str unique | event_id | envelope 业务键，去重锚 |
| `event_type` | varchar(32) index | event_type | 查询/分区维度 |
| `action` | varchar(128) | action | 权限点/操作标识 |
| `title` | varchar(256) | title | 人读标题 |
| `occurred_at_utc` | timestamptz index | occurred_at_utc | 事件时刻（≠ created_at 落库时刻）|
| `actor_user_id` | BigInt null **index, 无 FK** | actor.user_id | ⚠️ **冗余快照不设 FK**：用户删除后审计须留存 |
| `actor_username` | varchar(64) null | actor.username | 冗余快照 |
| `actor_is_super` | bool | actor.is_super_admin | |
| `target_type` / `target_id` / `target_display` | varchar | target.* | 被作用对象快照 |
| `req_ip` / `req_user_agent` / `req_method` / `req_path` / `req_request_id` / `req_trace_id` | varchar null | request.* | 中间件填（D3）|
| `result_status` | varchar(16) index | result.status | success/failure/denied |
| `result_http_status` | int null | result.http_status | |
| `result_error_code` | varchar(64) null | result.error_code | |
| `duration_ms` | int null | duration_ms | |
| `risk_level` | varchar(8) index | risk_level | low/medium/high |
| `metadata` | **JSONB** | metadata（已脱敏） | redaction_applied 已 true 才入 |
| `redaction_applied` | bool | redaction_applied | |
| `created_at` | timestamptz | — | TimestampMixin 落库时刻 |

- **索引**：`(occurred_at_utc)`、`(event_type, occurred_at_utc)`、`(actor_user_id)`、`(result_status)`。
- **分区**：P2 先不做时间分区（量未知）；留 `occurred_at_utc` 索引，量大时再上 PG 声明式分区（不破坏 schema）。
- **不可变**：只 INSERT，无 UPDATE/DELETE（审计完整性）；无 `updated_at` 语义但 TimestampMixin 带着无害。

### 2.2 `login_logs`（RuoYi `sys_logininfor` 对标，登录专用）

登录全路径**显式**落 1 条（不走 envelope）。给 RuoYi 风格登录历史页用，覆盖成功 + 所有失败模式。

| 列 | 类型 | 备注 |
|---|---|---|
| `id` | BigInt PK | |
| `user_id` | BigInt null index | 失败/账号不存在时可空 |
| `username` | varchar(64) index | 尝试的账号（防枚举：内部记录，不外泄）|
| `status` | varchar(16) index | success/failure/locked/rate_limited/captcha_required |
| `reason_code` | varchar(64) null | error_code（密码错/锁定/限流…）|
| `ip` | varchar(64) null index | ContextVar 取 |
| `user_agent` | varchar(512) null | ContextVar 取 |
| `location` | varchar(128) null | IP 地理位置；P2 留列**不实现**（无 GeoIP 依赖），P3 填 |
| `login_at_utc` | timestamptz index | 登录尝试时刻 |
| `created_at` | timestamptz | 落库时刻 |

- **索引**：`(username, login_at_utc)`、`(user_id)`、`(status)`、`(ip)`。
- **登录失败的双轨**：login 失败既进 `login_logs`（ops 历史）又进 `audit_logs`（安全审计 via 现有 login_failed emit）——**有意重叠**，回答不同问题（"这账号最近登录历史" vs "全量安全事件流"）。RuoYi 同理（logininfor 与 oper_log 不交叉，admin 的 audit_logs 是超集所以交叉，可接受）。

---

## 3. D2 — 写入路径（最关键，红线核心）✅ 已实现（Phase 2）

> **实现优化 vs 原立场**：从「每 emit 一个独立 session」改为「**请求级缓冲 + 响应后批量 flush**」——
> `emit_audit` 仅同步 append 进请求缓冲（`audit/context.py` 的 ContextVar list），`RequestIDMiddleware`
> 在 `call_next` 后一次性 flush（`audit/sink.py` `DbAuditSink` 独立 session 批量 `add_all`）。三个收益：
> ① emit 保持**同步**，无需把 8 个调用点（含 permissions 同步依赖）改 async；② 一请求 N 条审计 =
> **1 个独立连接**（解 Codex 的连接放大）；③ 时点对所有事件统一在业务事务关闭后（成功/失败一致）。
>
> **规避 BaseHTTPMiddleware contextvar 上行不传播**：buffer 是中间件本地持有引用的可变 list，下游
> 只 append（mutate 同一对象）不重 set，flush 用本地引用。同步线程池依赖（permissions._dep）经 anyio
> context 复制进线程，append 仍命中同一 list。**三条均由 `test_audit_persistence.py` 端到端验证**。

### 3.1 立场：独立 session sink + 降级回 logger

`emit_audit(event)` 增加第二 sink `persist_audit_event(event)`：

```
async def persist_audit_event(event):
    try:
        async with db_session() as s:      # 自己的连接/事务，与业务 session 解耦
            s.add(AuditLog.from_envelope(event))
        # __aexit__ 独立 commit
    except Exception:
        logger.warning("audit persist failed", exc_info=True)   # 降级：logger sink 已是 durable 底线
        # 绝不 raise —— 守 emit_audit 既有契约「失败不阻断业务」
```

### 3.2 为什么**不**同事务（驳同步同事务方案）

失败/denied 审计（permission_denied / login_failed / rbac_write 失败）在业务 `raise AppError` 之时/之前 emit → 业务 `session.begin()` 的 `__aexit__` 触发 **ROLLBACK**。若审计同 session，**最该留的安全事件被一起回滚丢掉**——这正是 P1.5 刚修的「revoke 副作用被 ROLLBACK」同一 bug 类。独立 session 同时切断两个耦合：①审计不被业务回滚牵连；②审计写失败不回滚业务。

### 3.3 写入路径按结果分流（review F1 修正，方案 B）

> ⚠️ **修正**：原 §3.3 曾断言「假审计不存在 / 成功 emit 都在业务事务关闭后」——**错**。`audited_write`
> / `rbac_binding` 的成功 emit 在 `await coro` 之后，但 service 用的是**请求共享 `get_session`**，其
> commit 在 FastAPI teardown（晚于 emit），且 teardown 与中间件 flush 的先后不被框架保证。4 个独立
> 审查者（含 Codex high）命中：commit 失败时会留假成功审计。用户拍板方案 B 修复：

- **成功类审计**（rbac_write success）→ `record_audit_committed` 写**当前请求业务 session**
  （`db.session.current_request_session` 取，`begin_nested()` SAVEPOINT 隔离）。与业务**原子提交**：
  commit 失败 → 审计随业务一同回滚，**无假成功审计**；审计 insert 失败 → 仅回滚 savepoint，不连累
  业务。集成测试 `test_success_audit_{rolls_back,commits}_with_business_transaction` 守。
- **失败/拒绝类审计**（permission_denied / login_failed / rbac_write 失败 / refresh_reused）→ `emit_audit`
  缓冲 + 响应后中间件独立 session flush。这些事件业务**本就已 ROLLBACK**，必须独立落（不被回滚吞）。
- **登录成功**：`_emit_login_success` 在 `db_session()` 块外（业务已 commit），post-commit emit 无 F1，
  保持缓冲路径。
- **非 HTTP 上下文**（CLI / 后台）无请求 session → 成功审计回退缓冲（无业务事务可绑，无 F1 风险）。

### 3.5 已知缺口（诚实边界）

- **崩溃丢失窗口（仅失败/拒绝类）**：缓冲未 flush 即进程崩溃 → 丢该请求的失败审计 DB 行（logger sink
  是 durable 底线）。成功类已 in-tx 与业务原子，无此窗口。真不丢失败审计要 transactional outbox（P3）。
- **响应延迟**：失败审计 flush 在中间件 finally `await`（通常 1 条/~1ms）；成功审计随业务事务无额外往返。
- **列宽截断（F3）**：拆查询列截断到列宽防溢出丢批；完整原值在 `payload` JSONB（无损）。

### 3.4 Redis Stream 异步（推迟）

roadmap 列为「评估」。独立 session 同步更简单、无新基建、correctness 够。仅当审计写成延迟/吞吐瓶颈时升级为 outbox/stream + worker。**P2 不做**，留 §3.3 升级路径。

---

## 4. D3 — 请求上下文中间件 ✅ 已实现（Phase 1）

> **实现优化**：不新增中间件，**扩展现有 `RequestIDMiddleware`**（`core/middleware.py`）——它已管理请求级 ContextVar（request_id）+ request.state，只缺 IP/UA。再叠一层 `BaseHTTPMiddleware`（tech-debt #13）不划算。

- `audit/context.py`（audit 叶子，不 import core，守 C8 方向）：`ContextVar[AuditRequest|None]` + `set/reset/current_request_context`。
- `RequestIDMiddleware.dispatch`：入口把 `{request_id, trace_id, method, path, ip, user_agent}` 灌进 ContextVar，finally 复位（防跨请求泄漏）。
- IP 源：`_client_ip(request, trust_xff)` 默认取 `request.client.host`（直连 peer，不可伪造）；`audit_trust_x_forwarded_for=true` 时取 XFF 最左跳（Codex 红线：不裸信任 XFF，需可信反代）。
- `build_audit_event`：`request is None` 时默认读 `current_request_context()`（填现恒空的 `request` 段）；显式传入覆盖。`login_logs` 写入同样从 ContextVar 取 IP/UA。
- 这是 `emit.py` docstring「P2 接中间件」的落地半。**异步传播**：ContextVar 在 await 链 + `create_task` 快照透传（`test_audit_context` 守）。

---

## 5. 登录日志织入点（D 配套）✅ 已实现（Phase 3）

> **实现优化 vs 原 §5**：rate_limited / captcha_required **不再额外写 audit_events**——它们是登录流状态，
> 全在 login_logs（本就是登录安全日志，可查），写进 audit_events 是与 login_logs 的冗余。audit_events
> 保持聚焦 P1 定义的安全事件（login_failed 含 bad-cred/locked、refresh_reused）+ 新增 login_success。
> login_logs 则记**全部 5 种结局**。登录日志写入用 `domains/auth/login_log.py record_login_attempt`
> （独立 session、最佳努力、永不阻断登录；IP/UA/request_id 从 ContextVar 读）。

| 路径 | audit_events | login_logs | 备注 |
|---|---|---|---|
| 登录成功 | **新增** `login_success`（扩 EventType，向后兼容）| status=success + user_id | 块外提交后落，时点正确 |
| 密码错/账号不存在/停用 | 现有 login_failed | status=failure + reason（未知用户 user_id 空）| |
| 账号软锁 | 现有 login_failed（high）| status=locked | |
| 限流拒绝 | —（归 login_logs）| status=rate_limited | |
| 验证码不通过 | —（非安全事件，仅挑战）| status=captcha_required | |
| refresh 复用 | 现有 refresh_reused（token theft，high）| 不落 login_logs | |

- **声明式 vs 显式**：oper-log 审计沿用现有 `audited_write`（api 层 declarative-ish，符合 roadmap「声明式注解非纯 middleware」红线）；登录日志 = 5 个分支结果点**显式写**（分支多、显式更清晰）。
- **测试**：`test_login_log.py` 验收成功/失败各落 1 条 + IP/UA 非空 + 未知用户 user_id 空 + Redis-gated captcha 路径；audit_events 侧 login_success/login_failed 落库。

---

## 6. 实现顺序（签字后，无人值守，feature 分支 `p2-audit-log`）

> 每步一可验证目标；DB 步走一次性库 + Alembic 重建；push / 真库迁移 = 红线留人 review。

1. ✅ **Phase 1**：扩展 `RequestIDMiddleware` + `audit/context.py` ContextVar + envelope.request 自动填 → `test_audit_context`（默认读/覆盖/异步传播）。
2. ✅ **Phase 2**：`audit_events` 表 + 迁移 0011 + `AuditSink`/`DbAuditSink` + 请求缓冲响应后批量 flush → `test_audit_persistence`（失败审计 ROLLBACK 后落库 / 成功 / permission_denied 同步依赖）。
3. ✅ **Phase 3**：`login_logs` 表 + 迁移 0012 + 登录全路径织入 + `login_success` 扩 EventType → `test_login_log`（成功/失败各 1 条 + IP/UA + 未知用户 user_id 空 + captcha 路径）。
4. ✅ **Phase 4**：`domains/monitor/`（5 层 + C1）operlog/logininfor list+detail 查询 API + 4 权限点 + seed 监控菜单 → `test_monitor_query`（分页/过滤/detail/404/403）。
5. **Phase 5**：Codex high + 多视角 subagent 对抗审查 → 收敛。

---

## 7. Codex PK 交叉评审结论（high reasoning，2026-06-09）

> Codex 经 `-C` 独立读仓 + write-safe-migrations skill 出方案。原文 `/tmp/codex-pk-p2.out`。

### 7.1 强收敛（两方独立同结论）

最关键的 **D2 写入路径**两方**各自独立**得出同一结论，且都点名这是 P1.5「revoke 被 ROLLBACK」同类陷阱——这是 PK 防自欺的核心信号：

| 决策 | 收敛结论 |
|---|---|
| 表边界 D1/D4 | 两张表：`audit_events`（canonical 审计，全 event_type）+ `login_logs`（认证日志投影）；`sys_oper_log` **不建物理表**，作 audit_events 的查询视图/API DTO |
| actor 外键 | **不设 FK**，冗余快照 user_id + username（审计须在用户删除后留存；CASCADE 误删、SET NULL 损失调查价值）|
| 写入路径 D2 | **独立 session**，非同业务事务、非纯 BackgroundTask；失败/拒绝立即写，**成功事件确认业务 commit 后再写**；写失败降级 logger，绝不阻断业务 |
| metadata | JSONB（仅 PG），经 `redact_metadata` 脱敏，禁塞 raw headers/token/UA-as-secret |
| 分区 | P2 **不做**时间分区（量未知）；留时间索引，量大再上月分区 |
| Redis Stream | **推迟 P2.1**，behind `AuditSink` 接口 |
| login_success | 扩 EventType（schema_version 不变，向后兼容加值）|
| 幂等 | `event_id` UNIQUE |

### 7.2 采纳 Codex 三处精化（改进，非冲突）

1. **`payload JSONB NOT NULL` 列**：audit_events 除拆查询列外，再存**完整 envelope** 做无损回放（拆列查询 + payload 取证两全）。
2. **`AuditSink` 抽象**：P2 实现 `db_independent` sink，接口保留 `redis_stream` sink 可替换——Claude 若日后主张 Redis 可交叉评审 ops 成本，不把业务码绑死 Redis。
3. **after-commit 时点**：成功类 DB 写事件用请求级 collector，在主事务确认 commit 后 flush；驳「独立 session 过早写 success → 业务最终 rollback 但审计已 success」假审计。
4. **`login_logs.event_id` nullable unique**：回查关联 `audit_events.event_id`（登录失败双轨可串起来）。

### 7.3 一处分歧（非红线 / 可逆 / 已裁决）

| 维度 | Claude | Codex | 裁决 |
|---|---|---|---|
| D3 上下文传递 | RequestContextMiddleware + ContextVar（envelope.request 全局填）| API 层显式取 `request.client.host` / `headers` / `request.state` | **采 ContextVar**：①`rbac_audit.py:564` 现有注释已写明「请求段留 P2 中间件统一补」，②audited_write 拿不到 Request（只有 CurrentUser），显式取需穿层。**但加 Codex 的两条约束**：(a) 不信任 `X-Forwarded-For`，需 trusted proxy 配置；(b) 补 ContextVar 异步传播正确性单测（防 task 边界丢上下文）|

### 7.4 红线裁决 → **升级人拍板**

两方裁决信号一致：**否自动执行**，命中升级（数据模型不可逆 / 认证安全日志 / 跨模块横切 / 事务边界红线）。按 codex-pk 纪律 + CLAUDE.md「不可逆决策强制升级，不让 Claude 自裁」——数据模型落迁移前需用户签字。设计已收敛，升级性质为**收敛设计的 sign-off**（非让用户裁决分歧），外加 2 个用户语境相关的开放项（保留期/分区、P2 范围边界）。

---

## 8. Round-1 对抗审查处置（Codex high + 3 视角 subagent，2026-06-09）

实现完成后做对抗式深审：Codex high + 3 个独立 subagent（事务边界 / 安全脱敏越权 / 并发 ContextVar 资源）。4 路独立视角**全部命中 F1**（成功审计 emit 早于业务 commit）——PK 防自欺核心信号。

| # | 发现 | 严重度 | 处置 |
|---|---|---|---|
| F1 | 成功审计（audited_write/rbac_binding）emit 时业务用请求共享 session 未提交，commit 失败留假成功审计；推翻原 §3.3 论断 | 阻断（Codex）| **用户拍板方案 B**：成功审计写业务 session（SAVEPOINT 隔离）原子提交；失败/拒绝独立缓冲。测试 `test_success_audit_{rolls_back,commits}_with_business_transaction` |
| F2 | 登录失败分支 `record_login_attempt` 嵌业务 session 块内 → 每次失败登录占 2 连接 | 应修 | ✅ deferred 模式移出块外（块退出后落日志再 raise），与成功/锁/限流分支对齐 |
| F3 / A1 | 批量 flush 非原子：超长 UA/path（攻击者可控）触 VARCHAR 溢出 → 整批审计丢失 | 应修 | ✅ `from_envelope` / `record_login_attempt` 拆查询列截断到列宽；payload JSONB 留完整原值（零损失）。测试 `test_oversized_user_agent_does_not_lose_audit` |
| O1 | 监控查询 `page` 无上限 → 深分页 DoS | 可选 | ✅ `PageQ` 加 `le=10000` |
| A2 | XFF 信任开关默认安全但缺运维文档 | 应修 | config.py 注释 + .env.example + 本 spec §4 已记「仅可信反代剥离 XFF 时可开」三处覆盖 |
| 池放大 | provider sync 桥每权限校验多次独立 session + P2 flush session 叠加，threadpool(40) vs pool(15) 倒挂无 pool_timeout | 应修（P1 遗留） | 排期项：属 P1 RBAC provider 设计，P2 仅加剧；记入 §7 排期，建议 P2.1 给 engine 设 pool_timeout + provider 单 session 批量取 |

**未发现**：脱敏（payload 唯一自由文本入口 metadata 已 deny-list 递归脱敏，逐 emit 点核对无明文密码/token 旁路）、注入（监控查询全 ORM 参数化）、越权（4 端点全挂 require_permission，`test_monitor_query` 403 实测）、ContextVar 请求隔离（finally reset + 同步线程池依赖 buffer 共享已测）。
