"""单测：apply_data_scope（数据权限 5 范围 SQL where 注入）。

安全关键，断言编译出的 SQL、负向断言要全（含默认 deny 边界）。用 PostgreSQL dialect
编译（本仓目标库），不依赖真实 ORM 模型，避免引入 core/domains 依赖（守 C8）。
"""

from __future__ import annotations

from sqlalchemy import column, select
from sqlalchemy.dialects import postgresql

from admin_platform.authz.data_scope import apply_data_scope
from admin_platform.authz.scope import DataScope, ScopeType


def _where_sql(scope: DataScope) -> str:
    dept_col = column("dept_id")
    owner_col = column("owner_id")
    stmt = select(column("id"))
    result = apply_data_scope(stmt, scope, dept_col=dept_col, owner_col=owner_col)
    return str(result.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_all_adds_no_where() -> None:
    """全部范围：不追加任何 where。"""
    assert "WHERE" not in _where_sql(DataScope(ScopeType.ALL, user_id=7))


def test_self_filters_by_owner_only() -> None:
    """仅本人：按 owner 过滤，且不混入部门条件（负向）。"""
    sql = _where_sql(DataScope(ScopeType.SELF, user_id=7))
    assert "owner_id = 7" in sql
    assert "dept_id" not in sql


def test_self_dept_filters_by_dept() -> None:
    """本部门：按 dept_id 等值过滤。"""
    sql = _where_sql(DataScope(ScopeType.SELF_DEPT, user_id=7, dept_id=10))
    assert "dept_id = 10" in sql


def test_self_dept_without_dept_denies() -> None:
    """无部门用户 + 本部门范围 → 空结果（默认 deny，不泄露）。"""
    sql = _where_sql(DataScope(ScopeType.SELF_DEPT, user_id=7, dept_id=None))
    assert "false" in sql.lower()
    assert "dept_id = " not in sql


def test_dept_and_below_uses_in_set() -> None:
    """本部门及以下：dept_id IN 可见部门集合（含全部成员）。"""
    sql = _where_sql(
        DataScope(
            ScopeType.SELF_DEPT_AND_BELOW,
            user_id=7,
            dept_id=10,
            visible_dept_ids=frozenset({10, 11, 12}),
        )
    )
    assert "dept_id IN" in sql
    for dept in ("10", "11", "12"):
        assert dept in sql


def test_custom_dept_uses_in_set() -> None:
    """自定义部门：dept_id IN 自定义可见集合。"""
    sql = _where_sql(
        DataScope(ScopeType.CUSTOM_DEPT, user_id=7, visible_dept_ids=frozenset({5, 6}))
    )
    assert "dept_id IN" in sql
    assert "5" in sql and "6" in sql


def test_empty_visible_set_denies() -> None:
    """空可见部门集 + 部门范围 → 空结果（默认 deny）。"""
    sql = _where_sql(DataScope(ScopeType.CUSTOM_DEPT, user_id=7, visible_dept_ids=frozenset()))
    assert "false" in sql.lower()


def test_returns_new_stmt_not_mutating() -> None:
    """不就地修改入参 stmt（返回新对象）。"""
    base = select(column("id"))
    out = apply_data_scope(
        base,
        DataScope(ScopeType.SELF, user_id=1),
        dept_col=column("dept_id"),
        owner_col=column("owner_id"),
    )
    assert out is not base
    assert "WHERE" not in str(base.compile(dialect=postgresql.dialect()))
