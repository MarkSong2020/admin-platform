"""Task 9 CLI 纯逻辑单测（DB-free）—— username/password 校验 + main 缺 env 退出码。

这些是纯函数 / 校验分支，不碰 DB（``_create`` 的 DB 路径由 tests/integration/test_cli.py 覆盖）。
放 unit 让 ``make coverage``（``-m "not integration"``）也能计入 cli.py 的校验 + main 覆盖。
"""

from __future__ import annotations

import pytest

from admin_platform.cli import CliError, _read_password, _validate_username, main

_ENV = "ADMIN_BOOTSTRAP_PASSWORD"
_STRONG_PW = "bootstrap-strong-" + "z" * 12


# ---- _validate_username ----


def test_validate_username_ok() -> None:
    assert _validate_username("root") == "root"


@pytest.mark.parametrize("bad", ["", " root", "root ", "bad name", "a\tb", "x" * 65, "líne\nbreak"])
def test_validate_username_rejects(bad: str) -> None:
    with pytest.raises(CliError):
        _validate_username(bad)


# ---- _read_password ----


def test_read_password_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, _STRONG_PW)
    assert _read_password("root") == _STRONG_PW


def test_read_password_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(CliError):
        _read_password("root")


def test_read_password_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "short")
    with pytest.raises(CliError):
        _read_password("root")


def test_read_password_equals_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "rootrootroot")
    with pytest.raises(CliError):
        _read_password("rootrootroot")


def test_read_password_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, f"  {_STRONG_PW}  ")
    with pytest.raises(CliError):
        _read_password("root")


# ---- main 缺 env → 退出码非 0（在 DB 之前就失败，不建记录）----


def test_main_missing_env_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    assert main(["create-platform-admin", "--username", "root"]) != 0
