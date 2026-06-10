"""cron 计划 tick 计算单测（H3 hardening-r1）—— scheduled_tick_at 取计划时刻，跨分钟界键值恒定。

H3 修复核心：claim 去重键从「触发墙钟分钟」改为「cron 计划 tick」，使 failover/misfire 下同一逻辑
触发的键值恒定（不再跨分钟界算出两值 → 双执行）。这些单测固化该不变式（DB-free，纯计算）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from admin_platform.domains.scheduled_task.cron import scheduled_tick_at


def test_returns_planned_tick_not_wallclock() -> None:
    # 每分钟 cron，now=02:00:30 → 最近计划 tick=02:00:00（不是墙钟截断的 02:00:30 本身，语义相同
    # 但这里验证取的是 cron tick 序列上的点）。
    now = datetime(2026, 6, 10, 2, 0, 30, tzinfo=UTC)
    tick = scheduled_tick_at("* * * * *", timezone="UTC", now=now, lookback_seconds=120)
    assert tick == datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)


def test_stable_across_minute_boundary() -> None:
    # H3 核心：daily tick 02:00，触发在 02:00:05 与延迟到 02:04:00（misfire grace 内）算出的计划
    # tick 都是 02:00:00 → claim 同键 → 去重正确，不双执行。原墙钟实现会得 02:00 / 02:04 两值。
    base = datetime(2026, 6, 10, 2, 0, 0, tzinfo=UTC)
    early = scheduled_tick_at(
        "0 2 * * *",
        timezone="UTC",
        now=datetime(2026, 6, 10, 2, 0, 5, tzinfo=UTC),
        lookback_seconds=360,
    )
    late = scheduled_tick_at(
        "0 2 * * *",
        timezone="UTC",
        now=datetime(2026, 6, 10, 2, 4, 0, tzinfo=UTC),
        lookback_seconds=360,
    )
    assert early == base
    assert late == base


def test_none_when_no_tick_in_lookback_window() -> None:
    # daily cron 在远离触发时刻被调用、lookback 窗口内无 tick → None（调用方兜底 now.replace 分钟）。
    now = datetime(2026, 6, 10, 14, 0, 0, tzinfo=UTC)
    tick = scheduled_tick_at("0 2 * * *", timezone="UTC", now=now, lookback_seconds=360)
    assert tick is None
