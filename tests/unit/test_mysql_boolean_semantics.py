"""MySQL Boolean 语义回归测试。

MySQL ``BOOLEAN`` 实际是 ``TINYINT(1)``，裸 SQL 可写入 2；生成列里的
``CASE WHEN flag THEN`` 也会把非 0 值当真。迁移到 MySQL 后必须用 CHECK
约束和 ``flag = 1`` 表达式显式保住 PostgreSQL 布尔语义。
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Table
from sqlalchemy.schema import CreateTable

from admin_platform.audit.models import AuditEventLog
from admin_platform.domains.config.models import Config
from admin_platform.domains.dict.models import DictData, DictType
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.scheduled_task.models import ScheduledTask
from admin_platform.domains.user.models import User

REPO_ROOT = Path(__file__).resolve().parents[2]


def _check_sql(model: type, name: str) -> str:
    table = model.__table__
    constraints = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert len(constraints) == 1
    return str(constraints[0].sqltext)


def test_mysql_boolean_columns_have_explicit_binary_checks() -> None:
    cases = [
        (User, "ck_users_is_super_admin_bool", "is_super_admin IN (0, 1)"),
        (DictType, "ck_dict_types_is_builtin_bool", "is_builtin IN (0, 1)"),
        (DictData, "ck_dict_data_is_default_bool", "is_default IN (0, 1)"),
        (Config, "ck_configs_is_builtin_bool", "is_builtin IN (0, 1)"),
        (Menu, "ck_menus_visible_bool", "visible IN (0, 1)"),
        (
            ScheduledTask,
            "ck_scheduled_tasks_allow_concurrent_bool",
            "allow_concurrent IN (0, 1)",
        ),
        (
            AuditEventLog,
            "ck_audit_events_actor_is_super_admin_bool",
            "actor_is_super_admin IN (0, 1)",
        ),
        (
            AuditEventLog,
            "ck_audit_events_redaction_applied_bool",
            "redaction_applied IN (0, 1)",
        ),
    ]

    for model, constraint_name, expected_sql in cases:
        assert _check_sql(model, constraint_name) == expected_sql


def test_generated_boolean_unique_keys_compare_to_one() -> None:
    user_expr = str(User.__table__.c.super_admin_unique_key.computed.sqltext)
    dict_expr = str(DictData.__table__.c.default_unique_key.computed.sqltext)

    assert user_expr == "CASE WHEN is_super_admin = 1 THEN 1 ELSE NULL END"
    assert dict_expr == "CASE WHEN is_default = 1 THEN 1 ELSE NULL END"


def test_boolean_semantics_are_present_in_migrations() -> None:
    migration_expectations = {
        "migrations/versions/0002_users.py": ["ck_users_is_super_admin_bool"],
        "migrations/versions/0003_one_super_admin.py": [
            "CASE WHEN is_super_admin = 1 THEN 1 ELSE NULL END"
        ],
        "migrations/versions/0006_p1_menus.py": ["ck_menus_visible_bool"],
        "migrations/versions/0011_p2_audit_events.py": [
            "ck_audit_events_actor_is_super_admin_bool",
            "ck_audit_events_redaction_applied_bool",
        ],
        "migrations/versions/0014_p3_configs.py": ["ck_configs_is_builtin_bool"],
        "migrations/versions/0015_p3_dicts.py": [
            "ck_dict_types_is_builtin_bool",
            "ck_dict_data_is_default_bool",
            "CASE WHEN is_default = 1 THEN 1 ELSE NULL END",
        ],
        "migrations/versions/0016_p4c_scheduled_tasks.py": [
            "ck_scheduled_tasks_allow_concurrent_bool"
        ],
    }

    for relative_path, snippets in migration_expectations.items():
        text = (REPO_ROOT / relative_path).read_text()
        for snippet in snippets:
            assert snippet in text


def test_mysql_create_table_sql_keeps_boolean_checks() -> None:
    sql = str(CreateTable(cast(Table, User.__table__)))

    assert "ck_users_is_super_admin_bool" in sql
    assert "is_super_admin IN (0, 1)" in sql


def test_self_parent_constraints_are_enforced_by_mysql_triggers_in_migrations() -> None:
    migration_expectations = {
        "migrations/versions/0004_p1_depts.py": [
            "CREATE TRIGGER ck_depts_not_self_parent_bi",
            "CREATE TRIGGER ck_depts_not_self_parent_bu",
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ck_depts_not_self_parent'",
        ],
        "migrations/versions/0006_p1_menus.py": [
            "CREATE TRIGGER ck_menus_not_self_parent_bi",
            "CREATE TRIGGER ck_menus_not_self_parent_bu",
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ck_menus_not_self_parent'",
        ],
    }

    for relative_path, snippets in migration_expectations.items():
        text = (REPO_ROOT / relative_path).read_text()
        for snippet in snippets:
            assert snippet in text
