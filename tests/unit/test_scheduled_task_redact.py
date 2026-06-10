"""执行日志脱敏单测（F6 hardening-r1）—— error_message/result_summary 屏蔽敏感模式。

F6：handler 异常文本 / 返回摘要可能含连接串、密钥（admin-only 日志，但 registry 是扩展点）。
_redact 在 executor 写日志前屏蔽常见 key=value 密钥与 URL 内嵌凭据。纯函数，DB-free。
"""

from __future__ import annotations

from admin_platform.domains.scheduled_task.executor import _redact


def test_redact_masks_key_value_secrets() -> None:
    assert "secret123" not in _redact("connect failed password=secret123")
    assert "abc123xyz" not in _redact("auth token: abc123xyz")
    assert "REDACTED" in _redact("api_key=sk-deadbeef")


def test_redact_masks_url_embedded_credentials() -> None:
    redacted = _redact("connect error postgresql://app:p4ssw0rd@db:5432/app")
    assert "p4ssw0rd" not in redacted
    assert "REDACTED" in redacted


def test_redact_keeps_plain_text_unchanged() -> None:
    assert _redact("plain timeout, no secrets here") == "plain timeout, no secrets here"
