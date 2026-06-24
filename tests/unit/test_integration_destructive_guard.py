"""集成测试破坏性清库 guard 单测。"""

from __future__ import annotations

import pytest

from tests.integration.db_cleanup import assert_destructive_test_database_allowed

_LOCAL_URL = "mysql+aiomysql://app:app@127.0.0.1:3306/app"
_NONLOCAL_URL = "mysql+aiomysql://app:app@db.example.com:3306/app"


def test_destructive_guard_requires_explicit_allow_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_TEST_DB_ALLOW_DESTRUCTIVE", raising=False)

    with pytest.raises(RuntimeError, match="APP_TEST_DB_ALLOW_DESTRUCTIVE=1"):
        assert_destructive_test_database_allowed(_LOCAL_URL)


def test_destructive_guard_still_rejects_nonlocal_database_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TEST_DB_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.delenv("APP_TEST_DB_ALLOW_NONLOCAL", raising=False)

    with pytest.raises(RuntimeError, match="疑似非本地库"):
        assert_destructive_test_database_allowed(_NONLOCAL_URL)


def test_destructive_guard_allows_explicit_local_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TEST_DB_ALLOW_DESTRUCTIVE", "1")

    assert_destructive_test_database_allowed(_LOCAL_URL)
