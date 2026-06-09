"""cron 表达式校验 + 下次触发计算（P4c）。

**第一版只支持 5 字段标准 crontab**（``分 时 日 月 周``，dow 标准语义 0/7=周日），用 APScheduler
``CronTrigger.from_crontab`` 解析——校验与实际调度用**同一构造器**，保证「校验通过即能调度」。
拒绝 Quartz 高级语法（``? L W #``）与 6/7 字段：6 字段带秒在 APScheduler 下 dow 约定为 0=周一，
与 5 字段标准 0=周日冲突，混用易踩坑，故秒级精度留排期（spec §4 非目标）。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

_QUARTZ_TOKENS = ("?", "L", "W", "#")
_STANDARD_CRON_FIELDS = 5


class CronValidationError(ValueError):
    """cron 表达式或时区非法（service 翻 422）。"""


def _resolve_tz(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronValidationError(f"非法时区: {timezone}") from exc


def build_cron_trigger(expr: str, *, timezone: str) -> CronTrigger:
    """构造 APScheduler ``CronTrigger``（校验 + 调度共用）。非法 → ``CronValidationError``。"""
    cleaned = expr.strip()
    fields = cleaned.split()
    if len(fields) != _STANDARD_CRON_FIELDS:
        raise CronValidationError("cron 必须是 5 字段标准 crontab（分 时 日 月 周）")
    if any(tok in cleaned for tok in _QUARTZ_TOKENS):
        raise CronValidationError("不支持 Quartz 高级语法 ? L W #")
    tz = _resolve_tz(timezone)
    try:
        return CronTrigger.from_crontab(cleaned, timezone=tz)
    except (ValueError, TypeError) as exc:
        raise CronValidationError(f"非法 cron 表达式: {exc}") from exc


def validate_cron(expr: str, *, timezone: str) -> None:
    """仅校验（构造成功即合法）。"""
    build_cron_trigger(expr, timezone=timezone)


def next_run_after(expr: str, *, timezone: str, now: datetime) -> datetime | None:
    """``now`` 之后的下次触发时刻（tz-aware）。无后续触发返回 None。"""
    trigger = build_cron_trigger(expr, timezone=timezone)
    return trigger.get_next_fire_time(None, now)
