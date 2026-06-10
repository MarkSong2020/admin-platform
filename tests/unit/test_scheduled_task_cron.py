"""cron 计算单测（hardening-r1）—— H3 计划 tick + 簇H dow 标准 crontab 语义。

H3：claim 去重键从「触发墙钟分钟」改为「cron 计划 tick」，failover/misfire 下键值恒定（不双执行）。
簇H：dow 转命名修复 APScheduler from_crontab 的 0=周一约定错位（标准 crontab 0/7=周日 → 周触发
不再整体错位一天）。DB-free 纯计算/校验。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from admin_platform.domains.scheduled_task.cron import (
    CronValidationError,
    build_cron_trigger,
    scheduled_tick_at,
)


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


# ---- 簇H：dow 标准 crontab 语义（修复 from_crontab 的 0=周一约定错位）----


def _weekday_of(expr: str) -> str:
    trigger = build_cron_trigger(expr, timezone="UTC")
    fire = trigger.get_next_fire_time(None, datetime(2026, 6, 1, tzinfo=UTC))
    assert fire is not None
    return fire.strftime("%A")


@pytest.mark.parametrize(
    ("dow", "weekday"),
    [("0", "Sunday"), ("7", "Sunday"), ("1", "Monday"), ("3", "Wednesday"), ("6", "Saturday")],
)
def test_dow_single_value_is_standard_crontab(dow: str, weekday: str) -> None:
    # 标准 crontab dow（0/7=周日, 1=周一..6=周六）正确——原 from_crontab 把 0 当周一、1 当周二错位。
    assert _weekday_of(f"0 3 * * {dow}") == weekday


def test_dow_range_is_weekdays() -> None:
    trigger = build_cron_trigger("0 3 * * 1-5", timezone="UTC")  # Mon-Fri 工作日
    days = []
    prev = datetime(2026, 6, 1, tzinfo=UTC)
    for _ in range(5):
        fire = trigger.get_next_fire_time(None, prev)
        assert fire is not None
        days.append(fire.strftime("%a"))
        prev = fire + timedelta(seconds=1)
    assert days == ["Mon", "Tue", "Wed", "Thu", "Fri"]


def test_dow_list_sun_and_sat() -> None:
    trigger = build_cron_trigger("0 3 * * 0,6", timezone="UTC")  # 周日 + 周六
    days = set()
    prev = datetime(2026, 6, 1, tzinfo=UTC)
    for _ in range(4):
        fire = trigger.get_next_fire_time(None, prev)
        assert fire is not None
        days.add(fire.strftime("%a"))
        prev = fire + timedelta(seconds=1)
    assert days == {"Sat", "Sun"}


@pytest.mark.parametrize("bad", ["0 3 * * 8", "0 3 * * */2", "0 3 * * 0-4"])
def test_dow_rejects_invalid(bad: str) -> None:
    # 非法 dow 值(8) / 步进(*/2) / 跨周首尾逆向范围(0-4 Sun-Thu) → CronValidationError（明确拒绝）。
    with pytest.raises(CronValidationError):
        build_cron_trigger(bad, timezone="UTC")
