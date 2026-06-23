# admin-platform:PostgreSQL → MySQL 8 迁移评估报告

> 面向上司 / 团队的决策汇报 · 2026-06-23
> 评估方法:全代码库摸排(2 个独立调研)+ Claude×Codex 双模型交叉评审(并发正确性红线)

---

## 一、执行摘要(结论先行)

- **可行,无"无解"难点**:全部 PostgreSQL 专有用法都有确定的 MySQL 8 落地路径,不存在必须砍功能才能迁的死角。
- **工作量:约 2.5–3.5 周单人(13–18 人天)**,功能对等迁移;存量生产数据迁移另算 ~2–5 天。
- **成本集中在 3 个并发/约束点**,但经双模型评审后均已有低风险方案,不再是"重写并发层"级别的工程。
- **耦合特征:窄而深**——PG 用法集中在少数文件,不是散布全仓;无 JSONB 操作符、无 `ON CONFLICT`/`RETURNING`/数组类型等重度依赖。
- **需团队拍板的决策点见第五节**(属不可逆架构决策)。

---

## 二、背景与动机

- 现状技术栈:FastAPI + SQLAlchemy 2.x(async)+ asyncpg + Alembic + **PostgreSQL 16** + Redis + Vue3。
- 迁移动机:**团队 / 运维硬约束**(仅提供 MySQL 实例 / DBA),PostgreSQL 非可选项。
- 目标:MySQL 8.0(**要求 ≥ 8.0.16**,见第四节 CHECK 约束)。

---

## 三、工作量分解

| 工作块 | 规模 | 难度 | 人天 |
|---|---|---|---|
| 驱动切换(asyncpg→asyncmy)+ 连接配置 + scheme 白名单 | 1–2 文件单点 | 易 | 1 |
| 类型映射(JSONB→JSON、Uuid、BigInteger、CHECK、时间类型) | ~6 模型文件,多数 SQLAlchemy 方言自动完成 | 易–中 | 1.5 |
| 迁移文件改写(now()、CONCURRENTLY、0017 的 UPDATE...FROM/make_interval) | ~6 迁移文件 | 中 | 2 |
| **🔴 咨询锁迁移(10 处行锁 + 1 处 GET_LOCK)** | 9 文件 | 中 | 2–3 |
| **🔴 partial unique → 生成列(3 处)** | 3 模型 + 迁移 | 中 | 2 |
| **🔴 时区(timestamptz→DATETIME)端到端 UTC 复核** | ~40-52 列读写路径 | 中 | 1–2 |
| asyncpg 错误码解析 → MySQL 1062 适配 | core/errors.py | 中 | 1 |
| 测试体系(24 处 TRUNCATE CASCADE、方言绑定单测、compose/CI 换镜像) | ~26 文件 | 中(量大机械) | 2–3 |
| 集成回归 + 并发正确性验证 + 调试缓冲 | — | — | 2–3 |
| **合计** | | | **~13–18 人天** |

> ⚠️ 不含**存量生产数据迁移**。本仓迁移此前仅在 dev/CI 临时容器跑过、生产未授权,若已有生产 PG 数据,加 pgloader/dump 转换 + 校验 ~2–5 天。

---

## 四、技术风险与方案(双模型评审共识)

### 风险点 1:并发咨询锁(原以为最大障碍,评审后降级)

PostgreSQL 用了 11 处 `pg_advisory_*` 咨询锁。**关键发现**:其中

- **10 处是事务级**(`pg_advisory_xact_lock`,随事务 commit/rollback 自动释放,纯防并发写竞态/重复初始化);
- **仅 1 处是会话级长持**(定时任务 scheduler 的 leader 选举)。

**方案(已收敛)**:
1. **10 处事务级 → 行锁 sentinel**:同一事务内对一行哨兵记录 `SELECT ... FOR UPDATE`(可建 `app_locks(name)` 表统一管理)。事务级自动释放语义 **1:1 对齐**,无新依赖,回滚最简。
2. **1 处 leader 选举 → MySQL `GET_LOCK()`**:连接断开自动释放,天然防脑裂,`IS_FREE_LOCK` 可观测。
3. **不引入 Redis 分布式锁**:MySQL 自身语义已可覆盖全部 11 处,引 Redis 反而新增故障域与跨系统一致性问题。Redis 锁留作未来多实例水平扩展时再议。

### 风险点 2:条件唯一约束(partial unique index)

PostgreSQL 的 3 处"带 WHERE 的唯一索引"(超管全局唯一 / 字典每类型单默认值 / 定时任务调度去重),MySQL 8 不支持。

**方案**:统一用 **生成列(STORED)+ 普通唯一索引**——利用 MySQL 唯一索引"允许多个 NULL"的特性,把"仅满足条件的行参与唯一"编码进生成列(不满足条件的行生成列为 NULL,不互相冲突)。语义 1:1,可逆(删列删索引即回退),**优于触发器**(维护/可观测/可逆性都更差)。

**调度去重红线确认**:该处依赖与 `0018` 的 CHECK 约束(`schedule 行 ⇒ scheduled_at 必非空`)联动。**只要把该 CHECK 原样迁到 MySQL(8.0.16+ 强制执行),去重红线不会被旁路**,行为与 PostgreSQL 完全一致。这也是要求目标实例 **≥ 8.0.16** 的原因。

### 风险点 3:时区(timestamptz → MySQL 无时区类型)

PostgreSQL `timestamptz` 存绝对时刻;MySQL `DATETIME` 不带时区。代码注释多处已声明"库时间一律 UTC",故理论可行,但需**端到端复核**所有时间读写路径(审计日志 / 登录日志 / token 过期),确认驱动不做隐式时区转换。属"必须仔细做"而非"难做"。

### 好消息(评审确认,缩小了工作量)

代码库 grep 确认**不存在**以下重度 PG 依赖:JSONB 操作符(`@>`/`->>`)、`array_agg`/`DISTINCT ON`/`generate_series`、`ON CONFLICT`、`RETURNING`、数组/INET/全文检索类型、GIN/GIST 索引、方言分支判断。冲突处理走通用 `IntegrityError` 异常捕获(与方言无关)。部门/菜单树用的 recursive CTE,MySQL 8 原生支持。

---

## 五、需团队 / 上司拍板的决策点(不可逆)

| # | 决策 | 推荐 | 备选 |
|---|---|---|---|
| 1 | scheduler leader 选举可用性取舍 | 单实例 `GET_LOCK`(当前足够) | 若规划多机房 scheduler HA,改 Redis 租约/Redlock(需单独设计) |
| 2 | 事务级锁的哨兵承载 | 新建 `app_locks` 锁表统一管理 | 复用被保护聚合根行 |
| 3 | 目标 MySQL 版本 | **≥ 8.0.16**(CHECK 强制执行 + 表达式默认值) | 低于此版本 CHECK 被静默忽略,去重红线失效 — 不可接受 |
| 4 | 是否走 Spec Coding + 留档 | **是**(数据库迁移 + 并发模型变更,建议正式 spec) | — |

---

## 六、建议实施路径(分阶段,先消最大不确定性)

1. **阶段 0 — PoC spike(0.5–1 周)**:只验证两个最高风险点——scheduler leader 选举(`GET_LOCK` 断连/reconnect 行为)+ 调度 claim 并发去重(行锁 + 生成列唯一约束),用最小代价证明方案站得住,再决定全量投入。
   - **状态:已完成,Codex subagent 对抗审查后待 review gate**。阶段产物见 [`docs/archive/specs/2026-06-23-mysql-migration-phase0-poc.md`](docs/archive/specs/2026-06-23-mysql-migration-phase0-poc.md),PoC 脚本见 [`scripts/mysql_phase0_poc.py`](scripts/mysql_phase0_poc.py),临时 MySQL runner 见 [`scripts/run_mysql_phase0_poc.sh`](scripts/run_mysql_phase0_poc.sh)。
   - **实测摘要**:`mysql:8.4.9` + `asyncmy`,`24` workers × `6` rounds 并发 claim,每轮 `claimed=1`、`duplicate_1062=23`、`db_rows=1`、`max_db_lock_critical_section=1`;scheduler `GET_LOCK` 断连后 standby 可接管,旧 leader reconnect 时不能与 standby 双持同名 MySQL lock。
   - **后续约束**:正式实现必须处理 `1213 Deadlock` bounded retry、`INSERT IGNORE` warning 降噪、`scheduled_task_logs.task_id ON DELETE SET NULL` 与 stored generated column 的 MySQL 兼容性,并在阶段 3 确认行锁 sentinel 粒度,避免把 PoC 的全局 `scheduled-task-claim` 误用为最终跨任务锁粒度。
2. **阶段 1 — 基础设施层**:驱动、连接配置、compose/CI 换镜像、类型映射(机械批量)。
3. **阶段 2 — 迁移文件改写**:生成列约束、CHECK 迁移、0017 数据回填 SQL 改写。
   - **阶段 2 兼容性取舍(待 review gate 明确接受)**:MySQL 8.4 实测拒绝 `depts.parent_id <> id` / `menus.parent_id <> id` 这类引用 `AUTO_INCREMENT` 主键的 CHECK(错误 3818)。用 trigger 还原 DB 兜底也在默认 `app` 迁移账号 + binary logging 下被拒绝(错误 1419,需要 `SUPER` 或实例级 `log_bin_trust_function_creators=1`),不符合当前最小权限迁移口径。因此阶段 2 不引入 trigger；API/service 层自环校验仍保留,但 raw SQL / 导入 / 回放路径的 DB 级自环防护需 review 时确认是否接受,或另行授权更高权限 trigger 方案。
4. **阶段 3 — 并发控制层**:10 处行锁 + 1 处 GET_LOCK + asyncpg 错误码适配。
   - **状态:已实现,Codex subagent 对抗审查无 Blocking,待 review gate**。落地文件包括 `src/admin_platform/db/locks.py`、`migrations/versions/0021_mysql_app_locks.py`、各 repository 锁调用点、`domains/scheduled_task/scheduler.py`、`core/errors.py`。
   - **锁粒度核对**:当前代码实际存在 9 个既有事务级锁调用点；阶段 3 另在 scheduled task claim 入口新增 `scheduled-task:claim:{task_id}` sentinel,避免沿用阶段 0 PoC 的全局 `scheduled-task-claim` 而压低不同任务并发。合计 10 个事务级行锁入口 + 1 个 scheduler `GET_LOCK`。
   - **实测修正**:`AsyncConnection.close()` 只可能把连接归还 pool,不能当作 MySQL 断连来证明 `GET_LOCK` 释放；正式验证改用 `KILL CONNECTION`。异常 demote 路径改为 `invalidate()` 物理连接,避免会话锁泄漏回连接池。
   - **实测修正**:`INSERT IGNORE app_locks` 放在业务事务内会让 MySQL 1213 deadlock 出现在后续 `SELECT ... FOR UPDATE` 上,同一 `AsyncSession` 内不可可靠重试。正式实现改为独立短事务有界重试“确保 sentinel 行存在”,业务事务只持有 `SELECT ... FOR UPDATE` 行锁；事务级释放语义不变。为降低连接池压力,已存在 sentinel 行会先用调用方 session 探测并直接锁定,不再额外借第二条连接；首次创建动态锁行仍要求 pool 至少有第二条可用连接,启用 scheduler 时还需考虑 leader 长持 1 条连接。
   - **时区实测**:MySQL `DATETIME` 经 asyncmy 读回为 naive `datetime`。阶段 3 已修 executor duration 计算的 aware/naive 相减崩溃,并将自动调度 `scheduled_at=None` 路径的非 UTC cron tick 写库前统一转 UTC；阶段 4 仍需按原计划系统复核审计、登录日志、token 过期等全路径。
   - **验证脚本**:`scripts/mysql_phase3_verify.py` 在 `mysql:8.4.10` 上验证 `GET_LOCK` 断连接管、`app_locks` 同名串行、同任务 schedule claim 多 worker 去重、不同任务 claim 不共享全局锁、非 UTC cron tick 落库 UTC 语义。脚本会 `TRUNCATE scheduled_task_logs/scheduled_tasks/app_locks`,需同时满足本地 URL 与 `APP_TEST_DB_ALLOW_DESTRUCTIVE=1`。
5. **阶段 4 — 测试与回归**:TRUNCATE CASCADE 改写、方言单测修正、并发正确性集成回归(重点验证 scheduler 与调度去重)。
   - **执行期校正(2026-06-24)**:reference compose/CI 镜像固定为 `mysql:8.0`。原因是本机实测浮动 `mysql:8` 当前解析到 MySQL 8.4.10,asyncmy 0.2.11 在默认认证插件下从宿主连接会 1045;`mysql:8.0` 当前解析到 MySQL 8.0.46,满足 ≥8.0.16 红线且 asyncmy 默认连接通过。历史阶段 0/3 对 8.4 的并发语义验证仍作为方案证据保留,但当前回归基线以 MySQL 8.0 系列为准。

---

## 七、风险底线提示

- **并发正确性是本次迁移的核心风险**(scheduler 双 leader、调度重复执行),必须有专门的并发回归测试,不能只靠功能测试通过就放行。
- **时区**若复核不彻底,会导致审计 / 登录时间静默偏移,属"看起来对、实际错"的隐患。
- 迁移后需同步更新项目内 `AGENTS.md`(技术选型说明)与 CI/compose 配置。

---

*评估依据:全代码库 2 路并行摸排 + Claude(Opus 4.8)与 Codex(gpt-5.1-codex)双模型对两处并发红线的独立交叉评审,无实质冲突、方案收敛。所有技术结论可溯源到具体文件与行号。*

---

# 附:实现后深度审查报告(Claude review · 2026-06-24)

> 审查对象:本报告对应的 `feat/mysql-migration` 实际实现(改动全在工作区未提交)
> 审查方:Claude(Opus 4.8)
> 审查方式:主上下文亲审锁/scheduler/基础设施红线 + 3 个并行独立 agent 审生成列/时区/错误·测试·迁移机械 + **对核心结论用可执行实测交叉验证**
> 与上文关系:上文是**实施前方案**;本节是**实施后对照代码的验收审查**,发现 1 个必修严重 bug + 若干项。

## R1. 一句话结论

**有条件通过**:工程质量整体很高,但有 **1 个用户可见的严重 bug 必须修(时区静默偏移 8 小时)**,外加 2 个重要项、3 个需团队拍板的取舍/部署前置、5 个轻微项。

| 级别 | 项 | 是否阻断合并 |
|---|---|---|
| 🔴 严重 | S1 时区静默偏移 | **是** |
| 🟡 重要 | I1 锁缓存无界增长 / I2 缓存-表耦合陷阱 | 建议修 |
| 🟠 需拍板 | D1 自环 CHECK 删除 / D2 MySQL≥8.0.16 / D3 写连接 time_zone | 决策项 |
| 🟢 轻微 | L1–L5 | 否 |

## R2. 时区定责:是实现的缺口,不是审查误报(可执行实测钉死)

时区是本次迁移最核心的正确性风险。Codex PK 因额度用尽未出第二意见,故改用**可执行事实**替代意见,在仓库 `.venv` 实测三层,**完全闭环**:

| 层 | 实测输出 | 含义 |
|---|---|---|
| asyncmy 读回 | `datetime(2026,6,24,10,0) \| tzinfo=None` | MySQL DATETIME 读回是 **naive** |
| asyncmy 写入 | `+08 18:00` → `'2026-06-24 18:00:00'` | 写入时 **offset 被静默丢弃**(应转成 10:00) |
| Pydantic | aware→`"...10:00:00Z"`,naive→`"...10:00:00"` | naive 序列化 **丢了 `Z`** |
| 前端(东八区) | 带Z 显示 `18:00:00`,不带Z 显示 `10:00:00`,**相差 8 小时** | UTC 值被当本地值直显 → **偏早 8 小时** |

**定责关键证据(纯逻辑):** `monitor/schemas.py` 被**单独**加了 `_UtcDatetimeModel` normalizer —— 说明实施者已识别 naive→丢Z→偏移问题并修了 monitor 一个域,却没推广到其余 10 个域。这是**"修一处、漏同类"的实现遗漏**。上文第七节也预警过时区静默偏移、第六节也写了"阶段4 仍需系统复核全路径";所以这是**已知风险 + 未完成的修复**,但当前工作区里该 bug 已实际存在于响应路径。

## R3. 🔴 严重(必须修)

### S1. 时区静默偏移 —— 10 个域响应时间全站偏 8 小时

- **位置**:`src/admin_platform/domains/{dept,config,dict,menu,post,notice,role,user,scheduled_task,file}/schemas.py` 的 `*Read` 模型未加 UTC normalizer(只有 `monitor/schemas.py` 加了)
- **证据**:
  - `git diff HEAD --name-only -- 'src/admin_platform/domains/*/schemas.py'` 仅返回 `monitor/schemas.py`
  - `ScheduledTaskRead`/`ScheduledTaskLogRead`(`scheduled_task/schemas.py:75-110`)的 `last_run_at`/`created_at`/`updated_at`/`scheduled_at`/`started_at`/`finished_at` 全是裸 `datetime`,无 validator
  - 受影响页面:`frontend/src/views/monitor/job/components/JobLogDialog.vue:76,79`、`job/index.vue`(`last_run_at`)、各业务列表 `created_at`/`updated_at`
  - 前端 `frontend/src/utils/format.ts:10` `new Date(value)`,不带 `Z` 按本地时区解析
- **已正确修复的 3 处(对照,崩溃型,都修对了)**:executor duration `executor.py:276`、cron tick 写库转 UTC `executor.py:197`、refresh token 过期判断 `refresh_service.py:175-185`
- **修复建议(治本胜逐点)**:在 `src/admin_platform/db/base.py` 用 `DateTime` 的 `TypeDecorator`:
  - `process_result_value`:对 MySQL 读回 naive 统一 `replace(tzinfo=UTC)` → ORM 属性恒 aware,所有 `*Read` 序列化自动带 `Z`
  - `process_bind_param`:对带非 UTC tzinfo 的入参强制 `.astimezone(UTC)` → 堵死 cron tick 类"误传 +08 aware 被静默丢 offset"复发
  - 一处覆盖全库读写。当前"逐 schema 加 validator"已被证明会漏(漏 10 域)。治本后 `_as_utc*` 局部 helper 与 `_UtcDatetimeModel` 可简化(可选)

## R4. 🟡 重要(建议修)

### I1. app_lock 进程级缓存无界增长
- **位置**:`src/admin_platform/db/locks.py:29-30`(`_KNOWN_LOCK_ROWS`/`_ENSURE_ROW_GUARDS` 只 add 从不回收)
- **机理**:动态锁名 `auth:refresh-user:{user_id}`(`auth/repository.py:34`,每用户一份)、`scheduled-task:claim:{task_id}`(`executor.py:177`)→ 每个 distinct 实体永久驻留 + `app_locks` 表行只增不减。PG `pg_advisory_xact_lock(bigint)` 无此问题
- **建议**:动态锁名缓存改 LRU + 上限,或接受并文档化。静态锁名(`rbac:seed`/`role:*`/`menu:*`/`dept:tree`/`post:*`)无此问题

### I2. 缓存"锁行永久存在"的耦合陷阱(I1+I2 组合地雷)
- **位置**:`src/admin_platform/db/locks.py:56-59`
- **机理**:命中 `_KNOWN_LOCK_ROWS` 就跳过存在性检查直接 `SELECT...FOR UPDATE`。一旦有人删 `app_locks` 旧行(典型:**为缓解 I1 而清理**),进程内已缓存调用匹配 0 行 → **静默不获取锁 → 互斥失效**
- **独立印证**:审查测试层 agent 也独立得出"清理 app_locks 会与缓存不一致,排除它是对的" → 实施者有意识规避(`db_cleanup.truncate_tables` 不清 app_locks),但隐式约束未文档化
- **当前是否触发**:否(生产不删行;测试不 TRUNCATE app_locks)
- **建议**:`locks.py` 注释明确"app_locks 行永不可删";若将来支持清理须配套 `_KNOWN_LOCK_ROWS.clear()` + `_ENSURE_ROW_GUARDS.clear()`

## R5. 🟠 需团队/上司拍板(取舍 / 部署前置,非 bug)

| # | 事项 | 说明 | 证据 |
|---|---|---|---|
| D1 | **DB 级自环 CHECK 删除** | `ck_depts_not_self_parent`/`ck_menus_not_self_parent` 已删,防御深度降级:raw SQL/导入/回放路径失去 DB 兜底(service 层防环更全面但只覆盖走 service 的路径)。技术原因真实(MySQL 拒绝引用 AUTO_INCREMENT 的 CHECK→3818;trigger 需 SUPER→1419)。**本报告第六节阶段2 已声明待 review** | migrations diff;`dept/service.py:126-169`、`menu/service.py:138-144` |
| D2 | **生产 MySQL 必须 ≥8.0.16** | 否则 16 处 CHECK(含 0018 调度去重红线)在 <8.0.16 **静默 no-op** → 去重红线失效。CI 用 `mysql:8.0` 安全;生产托管库版本需确认 | `0018:24-28`;agent 实测 8.0.16+ 强制(ERROR 3819) |
| D3 | **所有写连接必须 `SET time_zone='+00:00'`** | `engine.py:38-47` hook 已对应用连接设;直连排障/旁路连接需自觉,否则 `CURRENT_TIMESTAMP` 默认值写服务器本地时区。建议登记 RUNBOOK | `engine.py:38-47`;38 处 `now()→CURRENT_TIMESTAMP` |

## R6. 🟢 轻微

- **L1** `tests/unit/test_db_locks.py:48-55` 用 mock 只断言 SQL 字符串,无法验证并发互斥(真验证在 CI db lane,可接受)
- **L2** 卫生:`me.md`、`var/uploads` 未 gitignore,提交前防误入库
- **L3** `examples/k8s/deployment.yaml:14` 注释仍写 "PostgreSQL"(URL 已对),doc 漂移
- **L4** `mysql:8.0` 浮动 tag 未 pin 补丁版,CI 可复现性可改进
- **L5** 建议加 api/integration 测试断言"并发双超管/双默认 → 409 + 业务码",锁住 `core/errors.py` 对 MySQL 1062 报错文本格式的隐式依赖

## R7. ✅ 做得好的地方

- **`pg_advisory` 清零**(仅剩 `locks.py:3,53` 两处文档注释);残留物 grep(JSONB/`::jsonb`/asyncpg/make_interval/CONCURRENTLY/`UPDATE...FROM`)在迁移体内全归零
- **生成列方案无 COALESCE 误冲突坑**:三处 `CASE WHEN cond THEN val ELSE NULL END`(`user/models.py:60-65`、`dict/models.py:87-92`、`scheduled_task/models.py:131-139`),live MySQL 8.0 逐条边界实证 **1:1 等价** + `alembic check` 零漂移
- **scheduler 双保险**:`GET_LOCK` 选举 + `scheduled_task_logs` 唯一索引(双 leader 也只一条 INSERT 成功);`_verify_leadership` 用 `asyncio.timeout` 处理 half-open + `invalidate()` 防锁泄漏
- **UTC session hook**(`engine.py:38-47`)、**READ COMMITTED 对齐 PG**(`engine.py:30`)、错误码三轨 fallback、24 处 TRUNCATE 正确迁移(`db_cleanup.py` FK 闭包模拟 CASCADE)、CI db lane(`ci.yml:96-158` mysql:8.0+redis 跑 `make test-integration` 并发回归)

## R8. 给 codex 的修复任务清单(按优先级)

**P0 — 合并前必修**
1. **S1 时区**:`db/base.py` 实现 `DateTime` 的 `TypeDecorator`(读回补 UTC + 写入非 UTC aware 转 UTC),全库 datetime 读回恒 aware。验证:任一 `*Read` 序列化带 `Z` + 前端东八区不再偏移 + `make check` 与 CI db lane `make test-integration` 全绿;(可选)简化 `_as_utc*` 与 `_UtcDatetimeModel`

**P1 — 建议修**
2. **I1/I2 锁缓存**:`db/locks.py` 加"app_locks 行不可删"注释;评估动态锁名缓存是否加 LRU 上限

**P2 — 决策后执行(需先拍 D1/D2/D3)**
3. D1 确认是否接受 DB 级自环防护降级;D2 RUNBOOK 登记"生产 MySQL ≥8.0.16";D3 RUNBOOK 登记"写连接 SET time_zone='+00:00'"

**P3 — 清理**
4. L2 gitignore 补 `me.md`/`var/`;L3 修 k8s 注释;L4 评估 pin mysql 补丁版;L5 补并发冲突 409 api 测试

---

*本审查所有技术声明可溯源到具体文件与行号。时区结论经可执行实测(asyncmy + Pydantic + JS 三层)交叉验证,非推断;生成列结论经 live MySQL 8.0 容器边界实证。Codex PK 因额度用尽未完成,核心争议项(时区)以可执行实测替代第二意见。*
