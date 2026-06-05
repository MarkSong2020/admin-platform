"""单测：数据权限值对象（ScopeType 5 范围枚举 + DataScope frozen dataclass）。"""

from __future__ import annotations

import dataclasses

import pytest

from admin_platform.authz.scope import DataScope, ScopeType


def test_scope_type_has_exactly_five_members() -> None:
    """RuoYi 标准 5 范围齐全，无多无少。"""
    assert {member.name for member in ScopeType} == {
        "ALL",
        "CUSTOM_DEPT",
        "SELF_DEPT",
        "SELF_DEPT_AND_BELOW",
        "SELF",
    }


@pytest.mark.parametrize("scope_type", list(ScopeType))
def test_every_scope_type_constructs_data_scope(scope_type: ScopeType) -> None:
    """每个 ScopeType 都能用于构造 DataScope。"""
    scope = DataScope(scope_type=scope_type, user_id=7)
    assert scope.scope_type is scope_type
    assert scope.user_id == 7


def test_data_scope_defaults() -> None:
    """默认值：dept_id 为 None，visible_dept_ids 为空 frozenset。"""
    scope = DataScope(scope_type=ScopeType.SELF, user_id=1)
    assert scope.dept_id is None
    assert scope.visible_dept_ids == frozenset()
    assert isinstance(scope.visible_dept_ids, frozenset)


def test_data_scope_full_construction() -> None:
    """全字段构造：自定义部门范围携带可见部门集合。"""
    scope = DataScope(
        scope_type=ScopeType.CUSTOM_DEPT,
        user_id=7,
        dept_id=10,
        visible_dept_ids=frozenset({10, 11, 12}),
    )
    assert scope.dept_id == 10
    assert scope.visible_dept_ids == frozenset({10, 11, 12})


def test_data_scope_is_frozen() -> None:
    """frozen：改写字段抛 FrozenInstanceError。"""
    scope = DataScope(scope_type=ScopeType.ALL, user_id=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.user_id = 2  # type: ignore[misc]
