"""Role schema 同源门禁 —— ``data_scope`` 的 Literal 必须 == ``authz.ScopeType`` 的 5 个 value。

三处声明同一组取值（schemas 的 ``DataScopeValue`` Literal / models 的 ``ck_roles_data_scope``
CheckConstraint / authz 的 ``ScopeType``）。本测试守 Literal ↔ ScopeType 一致，任一处漂移即红，
避免「schema 接受但 provider ``ScopeType(value)`` 炸」或「DB 约束与 DTO 不一致」。
"""

from __future__ import annotations

from typing import get_args

from admin_platform.authz.scope import ScopeType
from admin_platform.domains.role.schemas import DataScopeValue


def test_data_scope_literal_matches_scope_type() -> None:
    literal_values = set(get_args(DataScopeValue))
    enum_values = {member.value for member in ScopeType}
    assert literal_values == enum_values, (
        f"data_scope Literal {literal_values} 与 ScopeType {enum_values} 漂移"
    )
