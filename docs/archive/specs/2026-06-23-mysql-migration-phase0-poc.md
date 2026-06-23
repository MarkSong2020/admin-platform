# MySQL 迁移阶段 0 PoC

> 范围：只验证 `MYSQL_MIGRATION_REPORT.md` 第六节阶段 0 的两个最高风险点，不进入全量迁移实现。
> 第二轮补做针对 review 结论：必须起 MySQL 真跑；补 scheduler 断连后旧 leader reconnect 脑裂场景；补调度 claim 的隔离环境与更接近真实 executor 的执行路径。

## 验收口径

1. scheduler leader 选举：同名 `GET_LOCK()` 同一时刻只能被一个连接持有；leader 连接被服务端断开后锁自动释放，standby 能接管；旧 leader 重新连接时不能与 standby 双持同名 MySQL lock。
2. 调度 claim 去重：`app_locks` 哨兵行 `INSERT IGNORE` 占位 + 同事务 `SELECT ... FOR UPDATE` 串行化 claim 临界区；生成列 `STORED` + 唯一索引让同一 `(task_id, scheduled_at)` 的 `schedule` claim 多 worker 并发下只成功 1 条。本阶段只验证同一 cron tick 的正确性层，不验证最终锁粒度是否保持跨任务并发。
3. 调度去重红线：MySQL 目标版本必须是 8.x 且不低于 8.0.16；`schedule => scheduled_at IS NOT NULL` 的 CHECK 必须实际拒绝脏行。

## 关键代码位置

- `scripts/mysql_phase0_poc.py`：独立 PoC 脚本，只操作 `mysql_phase0_*` 表，默认拒绝 schema reset，必须显式设置 `MYSQL_POC_ALLOW_SCHEMA_RESET=1`。
- `scripts/run_mysql_phase0_poc.sh`：一次性启动 `mysql:8.4.9` 临时容器、等待 MySQL SQL 可用、运行 PoC、退出时清理容器。
- `src/admin_platform/domains/scheduled_task/scheduler.py`：当前 PostgreSQL leader election 语义来源。
- `src/admin_platform/domains/scheduled_task/executor.py`：当前 claim session → handler 执行 → finish session 的语义来源。
- `src/admin_platform/domains/scheduled_task/models.py`：当前 partial unique + CHECK + FK 约束来源。

## 可复制命令

```bash
bash scripts/run_mysql_phase0_poc.sh 24 6
```

如需保留 stdout/stderr 供 review：

```bash
bash scripts/run_mysql_phase0_poc.sh 24 6 \
  > /private/tmp/admin-platform-phase0-poc.json \
  2> /private/tmp/admin-platform-phase0-poc.stderr
```

## 第二轮实测环境

- 临时容器：`mysql:8.4.9`
- 实测版本：`8.4.9`
- Python 连接：`uv run --with asyncmy --with cryptography`
- 并发参数：`24` workers × `6` rounds
- 隔离性：runner 使用随机容器名、随机本机端口、临时 `mysql_phase0` database；脚本只创建/删除 `mysql_phase0_*` 表，退出时 runner 清理容器。

## 实测结果

### 实验 A：scheduler leader GET_LOCK 断连 / reconnect

真实 MySQL 返回：

```json
{
  "leader_acquired": 1,
  "standby_while_leader_held": 0,
  "leader_probe_failed_after_kill": true,
  "standby_after_disconnect": 1,
  "old_leader_reconnect_while_standby_held": 0,
  "old_leader_after_standby_release": 1
}
```

结论：leader 连接被 `KILL CONNECTION` 后，原连接探活失败，standby 可接管同名 `GET_LOCK()`；旧 leader 重新建连时，在 standby 仍持锁期间返回 `0`，证明 MySQL 层不会双持同名 lock。该实验不声称应用层永远不会短暂双触发：真实 scheduler 在失锁到下一轮 demote 之间仍可能触发 `_fire`，正确性层仍由 `scheduled_task_logs` 的 claim 唯一约束兜底。

### 实验 B：调度 claim 并发去重

PoC claim 路径：

```text
INSERT IGNORE app_locks
-> SELECT app_locks FOR UPDATE
-> SELECT scheduled_tasks FOR UPDATE
-> INSERT scheduled_task_logs
-> COMMIT claim
-> UPDATE finish
```

PoC 使用单个 `scheduled-task-claim` sentinel，目的是在最小实验里放大同一 `(task_id, scheduled_at)` 的并发 claim 竞争。它不证明最终实现应使用全局锁粒度；阶段 3 落地 10 处事务级锁时必须逐调用点决定 sentinel 名称，避免把不同任务或不同聚合根不必要地全局串行化。

真实 MySQL 返回 `status=PASS`。6 轮每轮 24 worker 同时 claim 同一 `(task_id, scheduled_at)`，每轮结果均为：

- `claimed=1`
- `duplicate_1062=23`
- `db_rows=1`
- `success_rows=1`
- `running_rows=0`
- `max_db_lock_critical_section=1`

实测 round 摘要：

| round | task_id | duplicate_1062 | deadlock_1213_retries | db_rows | max_db_lock_critical_section |
|---:|---:|---:|---:|---:|---:|
| 1 | 1000 | 23 | 104 | 1 | 1 |
| 2 | 1001 | 23 | 97 | 1 | 1 |
| 3 | 1002 | 23 | 106 | 1 | 1 |
| 4 | 1003 | 23 | 107 | 1 | 1 |
| 5 | 1004 | 23 | 109 | 1 | 1 |
| 6 | 1005 | 23 | 102 | 1 | 1 |

CHECK 红线也已实测：`schedule + scheduled_at=NULL` 被 MySQL 拒绝，error code `3819`。`manual + scheduled_at=NULL` 可重复插入 2 行，符合 MySQL 唯一索引多 NULL 语义。

## 方案是否需要调整

核心选型不需要推翻：scheduler leader 用 `GET_LOCK()` 可满足同名 lock 断连接管语义；调度 claim 场景中，`app_locks` 行锁 sentinel + stored generated columns + unique index 已在 MySQL 8.4.9 真库上跑通。其余 10 处事务级锁和另外 2 处 partial unique 仍需在阶段 2/3 逐调用点落地和回归，不能把阶段 0 视为全量迁移验证完成。

阶段 1/2/3 实现必须补充约束：

1. `INSERT IGNORE app_locks` 热路径在 24 worker 并发下会出现 MySQL `1213 Deadlock found when trying to get lock`，PoC 通过有界 retry 后稳定 PASS。正式实现不能只处理 `1062`，必须对 claim 临界区增加 bounded retry。
2. 阶段 3 决定行锁 sentinel 粒度时，不能直接照搬本 PoC 的全局 `scheduled-task-claim` 名称；至少调度 claim 需要确认是否按任务粒度或聚合根粒度锁定，并补“不同 task_id 并发 claim”回归，避免无谓降低跨任务并发。
3. MySQL 8.4 在 `task_id` 被 stored generated column 引用时，允许 FK 默认/RESTRICT，但拒绝 `ON DELETE SET NULL`/`ON DELETE CASCADE`。当前 PostgreSQL 模型是 `scheduled_task_logs.task_id -> scheduled_tasks.id ON DELETE SET NULL`；阶段 2 迁移模型时必须单独决定如何保留“任务删除后日志保留”的语义。
4. 本阶段用 `mysql:8.4.9` 固定镜像保证复现；阶段 1/2 仍需在目标 MySQL 8.0.x 实例上验证 `CHECK` 强制执行和生成列索引行为，尤其是最低版本边界 `8.0.16`。

另外，`INSERT IGNORE` 的重复占位在 asyncmy 路径下会向 stderr 打印大量 `Duplicate entry 'scheduled-task-claim'` warning；这不影响正确性，但正式实现需要避免污染日志或调整占位写法。若要保持已锁定的 `INSERT IGNORE` 决策，应配套 warning 抑制/日志降噪策略。

## 对抗审查处理

本阶段改用 Codex subagent 做三路只读对抗审查：并发语义、MySQL DDL/方言边界、阶段产物/门禁。三路结论均为 `CONDITIONAL PASS`，未发现 P0/P1 代码阻断；发现项已处理如下：

- 收窄 `GET_LOCK` 结论：只声称 MySQL 层无双持同名 lock，应用层短暂双触发仍由 claim 唯一约束兜底。
- 收窄行锁 sentinel 结论：PoC 的全局 `scheduled-task-claim` 只用于放大同一 tick 竞争，最终锁粒度留到阶段 3 逐调用点决定。
- 固定 runner 默认镜像为 `mysql:8.4.9`，并用固定镜像重跑 PoC。
- 回填根报告第六节，避免主入口仍显示阶段 0 未执行。

## 自检命令与输出

```bash
uv run ruff format --check scripts/mysql_phase0_poc.py
# 1 file already formatted

uv run ruff check scripts/mysql_phase0_poc.py
# All checks passed!

bash -n scripts/run_mysql_phase0_poc.sh
# exit 0

bash scripts/run_mysql_phase0_poc.sh 24 6 \
  > /private/tmp/admin-platform-phase0-poc.json \
  2> /private/tmp/admin-platform-phase0-poc.stderr
# exit 0
```

关键 stdout：

```json
{
  "mysql_version": "8.4.9",
  "status": "PASS",
  "decision": "phase0_poc_passed_exact_insert_ignore_sentinel_path"
}
```

关键 stderr：

```text
Starting mysql:8.4.9 container: admin-platform-mysql-phase0-1782224667-10150
Unable to find image 'mysql:8.4.9' locally
8.4.9: Pulling from library/mysql
Digest: sha256:c36050afdca850f23cef85703f84c7531a5ae155a11b5ee1c60acb09937c4084
Status: Downloaded newer image for mysql:8.4.9
Running phase 0 PoC against 127.0.0.1:32772
Duplicate entry 'scheduled-task-claim' for key 'mysql_phase0_app_locks.PRIMARY'
...
```

stderr 共 774 行；除 runner 与首次拉取镜像输出外，均为 `INSERT IGNORE` 重复占位 warning。
