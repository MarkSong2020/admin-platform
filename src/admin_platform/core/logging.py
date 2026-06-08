"""结构化 JSON 日志 —— 每条日志一行 JSON 对象，输出到 stdout。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from admin_platform.core.config import get_settings

# ADR 0001 §9：level 字段固定 4 字符 ``WARN``（不用 Python 默认的 7 字符
# ``WARNING``），保证跨语言日志聚合时字段宽度一致。
logging.addLevelName(logging.WARNING, "WARN")

# JsonFormatter 会从 LogRecord 的 ``extra=`` dict 里挑出这些字段塞进 JSON。
# ADR §9 「必含字段」（timestamp / level / logger / message）直接在 payload 里。
# 下面这些是 ADR §9 「推荐字段」 —— JsonFormatter 在它们存在时拷过来。
#
# - request_id / trace_id    ：RequestIDMiddleware 注入（HTTP 路径必定有）
# - method / path / status_code / duration_ms：RequestIDMiddleware 访问日志注入
# - user_id / span_id        ：给未来 auth middleware + OTel SDK 留的注入点。
#                              先放在白名单里 —— 真接 auth/OTel 时只需要往
#                              ``request.state`` + 访问日志的 ``extra=`` dict 写值，
#                              不必再改本文件。
_EXTRA_FIELDS = (
    "request_id",
    "trace_id",
    "span_id",
    "user_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    # 审计事件（spec §13.3）：emit_audit 把 audit_event.v1 嵌在此字段，JSON 日志整体输出。
    "audit_event",
)


def _adr_timestamp() -> str:
    """ADR 0001 §9：ISO 8601 UTC，毫秒精度，后缀 ``Z``（不带 offset）。"""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _adr_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
