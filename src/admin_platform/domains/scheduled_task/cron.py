"""cron 表达式校验 + 下次触发计算（P4c）。

**第一版只支持 5 字段标准 crontab**（``分 时 日 月 周``，dow 标准语义 0/7=周日、1=周一）。dow 数字
经 ``_convert_dow_to_names`` 转命名修复 APScheduler ``from_crontab`` 的 **0=周一约定错位**（它把标准
crontab 数字 dow 直传 CronTrigger，而后者数字 0=周一、拒绝 7 → 周触发整体错位一天）；其余字段按
crontab 原样构造 ``CronTrigger``——校验与实际调度用**同一构造器**，保证「校验通过即能调度」。
拒绝 Quartz 高级语法（``? L W #``）与 6/7 字段：6 字段带秒在 APScheduler 下 dow 约定为 0=周一，
与 5 字段标准 0=周日冲突，混用易踩坑，故秒级精度留排期（spec §4 非目标）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
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


# 标准 crontab dow（0/7=周日, 1=周一..6=周六）→ APScheduler 命名 dow（修复 from_crontab 的
# 0=周一数字约定错位 + 拒绝 7 的问题）。
_CRON_DOW_NAMES = {
    "0": "sun",
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}


def _dow_name(value: str) -> str:
    name = _CRON_DOW_NAMES.get(value.strip())
    if name is None:
        raise CronValidationError(f"非法 day-of-week 值: {value!r}（标准 crontab dow 为 0-7）")
    return name


def _convert_dow_to_names(field: str) -> str:
    """day-of-week 字段：标准 crontab 数字 dow → APScheduler 命名 dow（消除 0=周一数字约定错位）。

    单值 / 范围 / 列表正确转换（``1-5``→工作日、``0``/``7``→周日）。dow 步进（``/``，语义歧义 + 罕见）
    与跨周首尾的逆向范围（如 ``0-4`` Sun-Thu，命名后 sun-thu 逆序）不支持 → CronValidationError，
    明确拒绝胜过静默错位（用户可改用列表如 ``0,1,2,3,4`` 或 ``*``）。
    """
    if "/" in field:
        raise CronValidationError("不支持 day-of-week 步进（如 */2）；请用单值/范围/列表")
    if field == "*":
        return field
    tokens = []
    for token in field.split(","):
        if "-" in token:
            lo, _, hi = token.partition("-")
            tokens.append(f"{_dow_name(lo)}-{_dow_name(hi)}")
        else:
            tokens.append(_dow_name(token))
    return ",".join(tokens)


def build_cron_trigger(expr: str, *, timezone: str) -> CronTrigger:
    """构造 APScheduler ``CronTrigger``（校验 + 调度共用）。非法 → ``CronValidationError``。

    dow 经 ``_convert_dow_to_names`` 转命名修复 from_crontab 的 0=周一约定错位（标准 crontab
    0/7=周日）；分/时/日/月按 crontab 原样传 ``CronTrigger``（second 默认 0，等价 from_crontab）。
    """
    cleaned = expr.strip()
    fields = cleaned.split()
    if len(fields) != _STANDARD_CRON_FIELDS:
        raise CronValidationError("cron 必须是 5 字段标准 crontab（分 时 日 月 周）")
    if any(tok in cleaned for tok in _QUARTZ_TOKENS):
        raise CronValidationError("不支持 Quartz 高级语法 ? L W #")
    tz = _resolve_tz(timezone)
    minute, hour, day, month, dow = fields
    try:
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=_convert_dow_to_names(dow),
            timezone=tz,
        )
    except (ValueError, TypeError) as exc:
        raise CronValidationError(f"非法 cron 表达式: {exc}") from exc


def validate_cron(expr: str, *, timezone: str) -> None:
    """仅校验（构造成功即合法）。"""
    build_cron_trigger(expr, timezone=timezone)


def next_run_after(expr: str, *, timezone: str, now: datetime) -> datetime | None:
    """``now`` 之后的下次触发时刻（tz-aware）。无后续触发返回 None。"""
    trigger = build_cron_trigger(expr, timezone=timezone)
    return trigger.get_next_fire_time(None, now)


def scheduled_tick_at(
    expr: str, *, timezone: str, now: datetime, lookback_seconds: int
) -> datetime | None:
    """``≤now`` 的最近 cron 计划 tick（H3：执行 claim 的去重键，取计划时刻而非触发墙钟分钟）。

    取计划 tick 使「同一逻辑触发」在任意触发延迟 / 跨分钟界下键值恒定：failover 两 leader 在相近
    时刻触发同一 tick → 各自算出同一计划时刻 → claim 同键去重（原用 ``now`` 截断分钟，跨分钟界会
    算出两值 → 双执行）。``lookback_seconds`` 需 ≥ 该任务可能的最大触发延迟（misfire_grace）。
    区间内无 tick（理论不应发生，因刚被触发）→ None（调用方兜底）。
    """
    trigger = build_cron_trigger(expr, timezone=timezone)
    tick = trigger.get_next_fire_time(None, now - timedelta(seconds=lookback_seconds))
    prev: datetime | None = None
    while tick is not None and tick <= now:
        prev = tick
        tick = trigger.get_next_fire_time(tick, tick + timedelta(microseconds=1))
    return prev
