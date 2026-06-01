"""JsonFormatter level field — ADR 0001 §9 forces 4-char `WARN`."""

import json
import logging

from admin_platform.core.logging import JsonFormatter


def _emit(level: int, msg: str = "x") -> dict[str, object]:
    record = logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=None
    )
    return json.loads(JsonFormatter().format(record))


def test_level_field_uses_warn_not_warning() -> None:
    """ADR §9: log level field is forced to 4-char `WARN` (not Python's default 7-char `WARNING`)."""
    payload = _emit(logging.WARNING)
    assert payload["level"] == "WARN"


def test_level_field_for_info() -> None:
    assert _emit(logging.INFO)["level"] == "INFO"


def test_level_field_for_error() -> None:
    assert _emit(logging.ERROR)["level"] == "ERROR"


def test_level_field_for_debug() -> None:
    assert _emit(logging.DEBUG)["level"] == "DEBUG"
