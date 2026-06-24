"""MySQL 迁移阶段 0 PoC：验证 scheduler leader 与调度 claim 并发语义。

该脚本只操作 ``mysql_phase0_*`` PoC 表，默认拒绝执行 schema reset；运行方必须显式设置
``MYSQL_POC_ALLOW_SCHEMA_RESET=1``，避免误连真实库后执行 DDL。

验证范围：
- scheduler leader：``GET_LOCK`` 单赢家、断连释放、旧 leader 重连后不能与 standby 双持锁。
- schedule claim：按真实 executor 的 claim session → handler 外部执行 → finish session 形态，
  验证 ``app_locks`` 行锁 sentinel + 生成列唯一约束在多 worker 下不重复执行。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

_LOCK_NAME = "admin-platform:mysql-phase0:scheduler-leader"
_CLAIM_LOCK_NAME = "scheduled-task-claim"
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_MYSQL_TARGET_MAJOR = 8
_MYSQL_MIN_CHECK_VERSION = (0, 16)
_MYSQL_DUPLICATE_ENTRY = 1062
_MYSQL_CHECK_CONSTRAINT_VIOLATED = 3819
_MYSQL_DEADLOCK = 1213
_EXPECTED_MANUAL_NULL_ROWS = 2
_LOCK_RETRY_LIMIT = 20
_RETRY_BACKOFF_BASE_S = 0.02
_RETRY_BACKOFF_CAP_S = 0.5
_WORKER_RETRY_SKEW_S = 0.001
_CLAIM_HOLD_S = 0.02
_STALE_SECONDS = 3600


@dataclass
class _CriticalSectionState:
    lock: asyncio.Lock
    active: int = 0
    max_active: int = 0


@dataclass(frozen=True)
class _ClaimResult:
    worker_id: int
    claimed: bool
    duplicate: bool
    mysql_error_code: int | None
    log_id: int | None = None
    deadlock_retries: int = 0


@dataclass(frozen=True)
class _ClaimAttempt:
    task_id: int
    scheduled_at: datetime
    worker_id: int


def _mysql_error_code(exc: BaseException) -> int | None:
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _assert_mysql_8_check_enforced(version: str) -> None:
    if "mariadb" in version.lower():
        raise AssertionError(f"PoC 目标必须是 MySQL 8，不接受 MariaDB: {version}")
    match = _VERSION_RE.search(version)
    if match is None:
        raise AssertionError(f"无法解析 MySQL 版本: {version}")
    major, minor, patch = (int(part) for part in match.groups())
    if major != _MYSQL_TARGET_MAJOR:
        raise AssertionError(f"PoC 目标必须是 MySQL 8.x，当前版本: {version}")
    if (minor, patch) < _MYSQL_MIN_CHECK_VERSION:
        raise AssertionError(f"MySQL {version} 低于 8.0.16，CHECK 约束可能不强制执行")


async def _scalar(conn: AsyncConnection, sql: str, params: dict[str, Any] | None = None) -> Any:
    return (await conn.execute(text(sql), params or {})).scalar_one()


async def _reset_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SET sql_notes = 0"))
        await conn.execute(text("DROP TABLE IF EXISTS mysql_phase0_scheduled_task_logs"))
        await conn.execute(text("DROP TABLE IF EXISTS mysql_phase0_scheduled_tasks"))
        await conn.execute(text("DROP TABLE IF EXISTS mysql_phase0_app_locks"))
        await conn.execute(text("SET sql_notes = 1"))
        await conn.execute(
            text(
                """
                CREATE TABLE mysql_phase0_app_locks (
                    name VARCHAR(191) NOT NULL PRIMARY KEY
                ) ENGINE=InnoDB
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE mysql_phase0_scheduled_tasks (
                    id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    handler_key VARCHAR(128) NOT NULL,
                    params_json JSON NOT NULL,
                    cron_expression VARCHAR(128) NOT NULL,
                    cron_timezone VARCHAR(64) NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    allow_concurrent BOOLEAN NOT NULL,
                    timeout_seconds INT NULL,
                    last_run_at DATETIME(6) NULL,
                    last_status VARCHAR(16) NULL,
                    CONSTRAINT ck_mysql_phase0_task_status
                        CHECK (status IN ('enabled', 'disabled'))
                ) ENGINE=InnoDB
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE mysql_phase0_scheduled_task_logs (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    task_id BIGINT UNSIGNED NULL,
                    execution_id CHAR(36) NOT NULL,
                    trigger_type VARCHAR(16) NOT NULL,
                    scheduled_at DATETIME(6) NULL,
                    handler_key VARCHAR(128) NOT NULL,
                    params_json JSON NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    started_at DATETIME(6) NULL,
                    finished_at DATETIME(6) NULL,
                    duration_ms INT NULL,
                    worker_id VARCHAR(64) NOT NULL,
                    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    claim_task_id BIGINT UNSIGNED GENERATED ALWAYS AS (
                        CASE WHEN trigger_type = 'schedule' THEN task_id ELSE NULL END
                    ) STORED,
                    claim_scheduled_at DATETIME(6) GENERATED ALWAYS AS (
                        CASE WHEN trigger_type = 'schedule' THEN scheduled_at ELSE NULL END
                    ) STORED,
                    CONSTRAINT ck_mysql_phase0_log_status
                        CHECK (status IN ('running', 'success', 'failure', 'skipped')),
                    CONSTRAINT ck_mysql_phase0_trigger_type
                        CHECK (trigger_type IN ('schedule', 'manual')),
                    CONSTRAINT ck_mysql_phase0_schedule_at
                        CHECK (trigger_type <> 'schedule' OR scheduled_at IS NOT NULL),
                    CONSTRAINT fk_mysql_phase0_task
                        FOREIGN KEY (task_id)
                        REFERENCES mysql_phase0_scheduled_tasks(id)
                        ON DELETE RESTRICT,
                    UNIQUE KEY uq_mysql_phase0_execution_id (execution_id),
                    UNIQUE KEY uq_mysql_phase0_schedule_claim (
                        claim_task_id,
                        claim_scheduled_at
                    ),
                    KEY ix_mysql_phase0_task_started (task_id, started_at)
                ) ENGINE=InnoDB
                """
            )
        )


async def _verify_get_lock_disconnect(engine: AsyncEngine) -> dict[str, Any]:
    leader = await engine.connect()
    standby = await engine.connect()
    admin = await engine.connect()
    old_leader_reconnect: AsyncConnection | None = None
    try:
        leader_conn_id = int(await _scalar(leader, "SELECT CONNECTION_ID()"))
        got_leader = int(await _scalar(leader, "SELECT GET_LOCK(:name, 0)", {"name": _LOCK_NAME}))
        got_standby_while_held = int(
            await _scalar(standby, "SELECT GET_LOCK(:name, 0)", {"name": _LOCK_NAME})
        )
        if got_leader != 1:
            raise AssertionError(f"leader GET_LOCK 预期返回 1，实际 {got_leader}")
        if got_standby_while_held != 0:
            raise AssertionError(
                "standby 在 leader 持锁期间不应拿到同名 GET_LOCK，"
                f"实际返回 {got_standby_while_held}"
            )

        # leader 连接由服务端断开时，MySQL 应释放会话级 GET_LOCK。
        await admin.execute(text(f"KILL CONNECTION {leader_conn_id}"))
        await admin.commit()
        await asyncio.sleep(0.2)

        leader_probe_failed = False
        try:
            await leader.execute(text("SELECT 1"))
            await leader.commit()
        except DBAPIError:
            leader_probe_failed = True
        if not leader_probe_failed:
            raise AssertionError("leader 连接被 KILL 后仍可探活，无法证明断连释放路径")

        standby_after_disconnect = int(
            await _scalar(standby, "SELECT GET_LOCK(:name, 2)", {"name": _LOCK_NAME})
        )
        if standby_after_disconnect != 1:
            raise AssertionError(
                "leader 断连后 standby 未能在 2 秒内接管 GET_LOCK，"
                f"实际返回 {standby_after_disconnect}"
            )

        # 脑裂补强：旧 leader 重连时 standby 已持有锁，旧 leader 不能再次成为 leader。
        old_leader_reconnect = await engine.connect()
        old_leader_reconnect_conn_id = int(
            await _scalar(old_leader_reconnect, "SELECT CONNECTION_ID()")
        )
        old_leader_reconnect_while_standby_held = int(
            await _scalar(
                old_leader_reconnect,
                "SELECT GET_LOCK(:name, 0)",
                {"name": _LOCK_NAME},
            )
        )
        if old_leader_reconnect_while_standby_held != 0:
            raise AssertionError(
                "standby 接管后，旧 leader 重连不应拿到同名 GET_LOCK，"
                f"实际返回 {old_leader_reconnect_while_standby_held}"
            )

        await standby.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": _LOCK_NAME})
        await standby.commit()
        old_leader_after_standby_release = int(
            await _scalar(
                old_leader_reconnect,
                "SELECT GET_LOCK(:name, 2)",
                {"name": _LOCK_NAME},
            )
        )
        if old_leader_after_standby_release != 1:
            raise AssertionError(
                "standby 释放后，旧 leader 重连应可重新参选，"
                f"实际返回 {old_leader_after_standby_release}"
            )

        return {
            "leader_connection_id": leader_conn_id,
            "leader_acquired": got_leader,
            "standby_while_leader_held": got_standby_while_held,
            "leader_probe_failed_after_kill": leader_probe_failed,
            "standby_after_disconnect": standby_after_disconnect,
            "old_leader_reconnect_connection_id": old_leader_reconnect_conn_id,
            "old_leader_reconnect_while_standby_held": old_leader_reconnect_while_standby_held,
            "old_leader_after_standby_release": old_leader_after_standby_release,
        }
    finally:
        for conn in (standby, old_leader_reconnect):
            if conn is not None:
                with suppress(Exception):
                    await conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": _LOCK_NAME})
                    await conn.commit()
        for conn in (leader, standby, admin, old_leader_reconnect):
            if conn is not None:
                with suppress(Exception):
                    await conn.close()


async def _verify_check_constraint(engine: AsyncEngine) -> dict[str, Any]:
    await _seed_task(engine, task_id=1, round_index=0)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO mysql_phase0_scheduled_task_logs
                        (
                            task_id,
                            execution_id,
                            trigger_type,
                            scheduled_at,
                            handler_key,
                            params_json,
                            status,
                            worker_id
                        )
                    VALUES
                        (
                            1,
                            :execution_id,
                            'schedule',
                            NULL,
                            'noop',
                            JSON_OBJECT(),
                            'running',
                            'check-probe'
                        )
                    """
                ),
                {"execution_id": str(uuid.uuid4())},
            )
    except DBAPIError as exc:
        error_code = _mysql_error_code(exc)
        if error_code != _MYSQL_CHECK_CONSTRAINT_VIOLATED:
            raise
        return {"schedule_null_rejected": True, "mysql_error_code": error_code}
    raise AssertionError("CHECK 未拒绝 schedule + scheduled_at=NULL，调度去重红线不可接受")


async def _verify_manual_rows_can_repeat(engine: AsyncEngine) -> dict[str, Any]:
    await _seed_task(engine, task_id=2, round_index=0)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO mysql_phase0_scheduled_task_logs
                    (
                        task_id,
                        execution_id,
                        trigger_type,
                        scheduled_at,
                        handler_key,
                        params_json,
                        status,
                        worker_id
                    )
                VALUES
                    (2, :execution_id_a, 'manual', NULL, 'noop', JSON_OBJECT(), 'running', 'manual-a'),
                    (2, :execution_id_b, 'manual', NULL, 'noop', JSON_OBJECT(), 'running', 'manual-b')
                """
            ),
            {"execution_id_a": str(uuid.uuid4()), "execution_id_b": str(uuid.uuid4())},
        )
        count = int(
            await _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM mysql_phase0_scheduled_task_logs
                WHERE task_id = 2 AND trigger_type = 'manual'
                """,
            )
        )
    if count != _EXPECTED_MANUAL_NULL_ROWS:
        raise AssertionError(f"manual + NULL 行应允许重复，实际 count={count}")
    return {"manual_null_rows": count}


async def _seed_task(engine: AsyncEngine, *, task_id: int, round_index: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO mysql_phase0_scheduled_tasks
                    (
                        id,
                        name,
                        handler_key,
                        params_json,
                        cron_expression,
                        cron_timezone,
                        status,
                        allow_concurrent,
                        timeout_seconds
                    )
                VALUES
                    (
                        :task_id,
                        :name,
                        'noop',
                        :params_json,
                        '* * * * *',
                        'UTC',
                        'enabled',
                        FALSE,
                        300
                    )
                """
            ),
            {
                "task_id": task_id,
                "name": f"task-{task_id}",
                "params_json": json.dumps({"round": round_index}, separators=(",", ":")),
            },
        )


async def _claim_once(
    engine: AsyncEngine,
    *,
    attempt: _ClaimAttempt,
    gate: asyncio.Event,
    state: _CriticalSectionState,
) -> _ClaimResult:
    await gate.wait()
    for retry_index in range(_LOCK_RETRY_LIMIT):
        try:
            result = await _claim_once_attempt(engine, attempt=attempt, state=state)
            return replace(result, deadlock_retries=retry_index)
        except DBAPIError as exc:
            if _mysql_error_code(exc) != _MYSQL_DEADLOCK or retry_index == _LOCK_RETRY_LIMIT - 1:
                raise
            backoff = min(
                _RETRY_BACKOFF_BASE_S * (2**retry_index),
                _RETRY_BACKOFF_CAP_S,
            )
            await asyncio.sleep(backoff + attempt.worker_id * _WORKER_RETRY_SKEW_S)
    raise AssertionError("unreachable")


async def _claim_once_attempt(
    engine: AsyncEngine,
    *,
    attempt: _ClaimAttempt,
    state: _CriticalSectionState,
) -> _ClaimResult:
    conn = await engine.connect()
    transaction = await conn.begin()
    entered_critical_section = False

    async def leave_critical_section() -> None:
        nonlocal entered_critical_section
        if entered_critical_section:
            async with state.lock:
                state.active -= 1
            entered_critical_section = False

    try:
        # 真实目标路径：同事务内先 INSERT IGNORE 占位，再 SELECT ... FOR UPDATE 拿事务级行锁。
        await conn.execute(text("SET sql_notes = 0"))
        await conn.execute(
            text("INSERT IGNORE INTO mysql_phase0_app_locks (name) VALUES (:name)"),
            {"name": _CLAIM_LOCK_NAME},
        )
        await conn.execute(text("SET sql_notes = 1"))
        await conn.execute(
            text("SELECT name FROM mysql_phase0_app_locks WHERE name = :name FOR UPDATE"),
            {"name": _CLAIM_LOCK_NAME},
        )
        # 贴近 executor._claim：锁任务行，读任务快照，再插 running 日志。
        task = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT
                        id,
                        handler_key,
                        params_json,
                        allow_concurrent,
                        timeout_seconds
                    FROM mysql_phase0_scheduled_tasks
                    WHERE id = :task_id AND status = 'enabled'
                    FOR UPDATE
                    """
                    ),
                    {"task_id": attempt.task_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if task is None:
            await leave_critical_section()
            await transaction.commit()
            return _ClaimResult(
                attempt.worker_id,
                claimed=False,
                duplicate=False,
                mysql_error_code=None,
            )

        async with state.lock:
            state.active += 1
            entered_critical_section = True
            state.max_active = max(state.max_active, state.active)

        await asyncio.sleep(_CLAIM_HOLD_S)
        since = attempt.scheduled_at - timedelta(seconds=_STALE_SECONDS)
        running_count = int(
            await _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM mysql_phase0_scheduled_task_logs
                WHERE task_id = :task_id
                  AND status = 'running'
                  AND started_at >= :since
                """,
                {"task_id": attempt.task_id, "since": since},
            )
        )
        status = "skipped" if not task["allow_concurrent"] and running_count > 0 else "running"
        started_at = None if status == "skipped" else datetime.now()
        result = await conn.execute(
            text(
                """
                INSERT INTO mysql_phase0_scheduled_task_logs
                    (
                        task_id,
                        execution_id,
                        trigger_type,
                        scheduled_at,
                        handler_key,
                        params_json,
                        status,
                        started_at,
                        finished_at,
                        worker_id
                    )
                VALUES
                    (
                        :task_id,
                        :execution_id,
                        'schedule',
                        :scheduled_at,
                        :handler_key,
                        :params_json,
                        :status,
                        :started_at,
                        CASE WHEN :status = 'skipped' THEN CURRENT_TIMESTAMP(6) ELSE NULL END,
                        :worker_id
                    )
                """
            ),
            {
                "task_id": attempt.task_id,
                "execution_id": str(uuid.uuid4()),
                "scheduled_at": attempt.scheduled_at,
                "handler_key": task["handler_key"],
                "params_json": task["params_json"],
                "status": status,
                "started_at": started_at,
                "worker_id": f"worker-{attempt.worker_id}",
            },
        )
        log_id = int(result.lastrowid)
        await leave_critical_section()
        await transaction.commit()
        if status == "running":
            await _finish_log(engine, log_id=log_id, task_id=attempt.task_id)
        return _ClaimResult(
            attempt.worker_id,
            claimed=status == "running",
            duplicate=False,
            mysql_error_code=None,
            log_id=log_id,
        )
    except IntegrityError as exc:
        await leave_critical_section()
        await transaction.rollback()
        error_code = _mysql_error_code(exc)
        if error_code != _MYSQL_DUPLICATE_ENTRY:
            raise
        return _ClaimResult(
            attempt.worker_id,
            claimed=False,
            duplicate=True,
            mysql_error_code=error_code,
        )
    except Exception:
        await leave_critical_section()
        await transaction.rollback()
        raise
    finally:
        await leave_critical_section()
        await conn.close()


async def _finish_log(engine: AsyncEngine, *, log_id: int, task_id: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE mysql_phase0_scheduled_task_logs
                SET
                    status = 'success',
                    finished_at = CURRENT_TIMESTAMP(6),
                    duration_ms = TIMESTAMPDIFF(MICROSECOND, started_at, CURRENT_TIMESTAMP(6)) DIV 1000
                WHERE id = :log_id
                """
            ),
            {"log_id": log_id},
        )
        await conn.execute(
            text(
                """
                UPDATE mysql_phase0_scheduled_tasks
                SET last_run_at = CURRENT_TIMESTAMP(6), last_status = 'success'
                WHERE id = :task_id
                """
            ),
            {"task_id": task_id},
        )


async def _verify_claim_dedup(engine: AsyncEngine, *, workers: int, rounds: int) -> dict[str, Any]:
    round_summaries: list[dict[str, Any]] = []
    base_tick = datetime(2026, 6, 10, 2, 0, 0)
    for round_index in range(rounds):
        task_id = 1000 + round_index
        scheduled_at = base_tick + timedelta(minutes=round_index)
        await _seed_task(engine, task_id=task_id, round_index=round_index)
        gate = asyncio.Event()
        state = _CriticalSectionState(lock=asyncio.Lock())
        tasks = [
            asyncio.create_task(
                _claim_once(
                    engine,
                    attempt=_ClaimAttempt(
                        task_id=task_id,
                        scheduled_at=scheduled_at,
                        worker_id=worker_id,
                    ),
                    gate=gate,
                    state=state,
                )
            )
            for worker_id in range(workers)
        ]
        gate.set()
        results = await asyncio.gather(*tasks)
        claimed = [result for result in results if result.claimed]
        duplicates = [result for result in results if result.duplicate]
        if len(claimed) != 1:
            raise AssertionError(f"round {round_index}: 预期 1 个赢家，实际 {len(claimed)}")
        if len(duplicates) != workers - 1:
            raise AssertionError(
                f"round {round_index}: 预期 {workers - 1} 个 1062 败者，实际 {len(duplicates)}"
            )
        if state.max_active != 1:
            raise AssertionError(
                f"round {round_index}: 行锁临界区并发数应为 1，实际 {state.max_active}"
            )
        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT
                            COUNT(*) AS db_rows,
                            SUM(status = 'success') AS success_rows,
                            SUM(status = 'running') AS running_rows,
                            SUM(trigger_type = 'schedule') AS schedule_rows
                        FROM mysql_phase0_scheduled_task_logs
                        WHERE task_id = :task_id
                          AND trigger_type = 'schedule'
                          AND scheduled_at = :scheduled_at
                        """
                        ),
                        {"task_id": task_id, "scheduled_at": scheduled_at},
                    )
                )
                .mappings()
                .one()
            )
        db_rows = int(row["db_rows"] or 0)
        success_rows = int(row["success_rows"] or 0)
        running_rows = int(row["running_rows"] or 0)
        schedule_rows = int(row["schedule_rows"] or 0)
        if db_rows != 1 or success_rows != 1 or running_rows != 0 or schedule_rows != 1:
            raise AssertionError(
                f"round {round_index}: claim/finish 结果异常 "
                f"(db_rows={db_rows}, success={success_rows}, running={running_rows}, "
                f"schedule={schedule_rows})"
            )
        round_summaries.append(
            {
                "round": round_index + 1,
                "task_id": task_id,
                "scheduled_at": scheduled_at.isoformat(),
                "claimed": len(claimed),
                "duplicate_1062": len(duplicates),
                "deadlock_1213_retries": sum(result.deadlock_retries for result in results),
                "db_rows": db_rows,
                "success_rows": success_rows,
                "running_rows": running_rows,
                "max_db_lock_critical_section": state.max_active,
            }
        )
    return {
        "workers": workers,
        "rounds": rounds,
        "claim_path": (
            "INSERT IGNORE app_locks -> SELECT app_locks FOR UPDATE -> "
            "SELECT scheduled_tasks FOR UPDATE -> INSERT scheduled_task_logs -> "
            "COMMIT claim -> UPDATE finish"
        ),
        "round_summaries": round_summaries,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.database_url is None:
        raise SystemExit("必须通过 --database-url 或 MYSQL_POC_DATABASE_URL 提供 MySQL PoC DSN")
    if not args.database_url.startswith("mysql+aiomysql://"):
        raise SystemExit("阶段 0 PoC 必须使用 mysql+aiomysql:// URL，确保验证目标驱动路径")
    if os.environ.get("MYSQL_POC_ALLOW_SCHEMA_RESET") != "1":
        raise SystemExit("拒绝执行 DDL：请确认这是隔离 PoC 库后设置 MYSQL_POC_ALLOW_SCHEMA_RESET=1")

    engine = create_async_engine(args.database_url, poolclass=NullPool, echo=False)
    try:
        async with engine.connect() as conn:
            version = str(await _scalar(conn, "SELECT VERSION()"))
            database_name = str(await _scalar(conn, "SELECT DATABASE()"))
        _assert_mysql_8_check_enforced(version)
        await _reset_schema(engine)
        get_lock = await _verify_get_lock_disconnect(engine)
        check_constraint = await _verify_check_constraint(engine)
        manual_null = await _verify_manual_rows_can_repeat(engine)
        claim_dedup = await _verify_claim_dedup(engine, workers=args.workers, rounds=args.rounds)
        return {
            "status": "PASS",
            "mysql_version": version,
            "database": database_name,
            "schema_compatibility": {
                "scheduled_task_log_fk_delete_action": "RESTRICT",
                "note": (
                    "MySQL 8.4 在 task_id 被 STORED 生成列引用时拒绝 "
                    "ON DELETE SET NULL/CASCADE；阶段 2 需要单独决定如何保留"
                    "当前“任务删除后日志保留”的语义。"
                ),
            },
            "get_lock_disconnect_and_reconnect": get_lock,
            "check_constraint": check_constraint,
            "manual_null_partial_unique_semantics": manual_null,
            "claim_dedup": claim_dedup,
            "decision": "phase0_poc_passed_exact_insert_ignore_sentinel_path",
        }
    finally:
        if not args.keep_tables:
            with suppress(Exception):
                await _reset_schema(engine)
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("MYSQL_POC_DATABASE_URL"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument(
        "--keep-tables",
        action="store_true",
        help="调试时保留 mysql_phase0_* 表；默认结束前重置为空表结构。",
    )
    return parser.parse_args()


def main() -> None:
    result = asyncio.run(_run(_parse_args()))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
