"""SQLAlchemy aiomysql pool_pre_ping 兼容性守门。"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects.mysql import aiomysql


class _FakeAiomysqlConnection:
    def __init__(self) -> None:
        self.ping_reconnect_args: list[bool] = []

    def ping(self, reconnect: bool = False) -> None:
        self.ping_reconnect_args.append(reconnect)


class _FakeDbapi:
    _send_false_to_ping = False


def test_aiomysql_adapter_accepts_argless_pool_pre_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """覆盖 PyMySQL 判定导致 SQLAlchemy 走 ``ping()`` 无参调用的路径。

    SQLAlchemy 2.0.49 的 aiomysql adapter 为 ``ping(self, reconnect)``，
    当 ``pool_pre_ping`` 走无参路径时会在 checkout 阶段 TypeError。
    """
    fake_connection = _FakeAiomysqlConnection()
    adapter = aiomysql.AsyncAdapt_aiomysql_connection(
        dbapi=_FakeDbapi(),
        connection=fake_connection,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        aiomysql.AsyncAdapt_aiomysql_connection,
        "await_",
        staticmethod(lambda value: value),
    )

    adapter.ping()

    assert fake_connection.ping_reconnect_args == [False]
