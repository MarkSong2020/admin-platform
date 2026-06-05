"""apply_data_scope —— 把 DataScope 翻译成 SQLAlchemy where 条件的纯函数（spec §4.2）。

声明式 + typed 上下文 + 显式 helper 三段式的「落地层」：repository 显式调用本函数，
把 DataScope（authz.scope）翻译成查询 where。安全默认 deny —— 部门范围但缺有效部门
信息（dept_id 为 None / visible_dept_ids 为空）时返回空结果，不泄露数据。
"""

from __future__ import annotations

from typing import Any, assert_never

from sqlalchemy import Select, false

from admin_platform.authz.scope import DataScope, ScopeType


def apply_data_scope(stmt: Select, scope: DataScope, *, dept_col: Any, owner_col: Any) -> Select:
    """按数据权限范围给 ``stmt`` 追加 where 条件并返回新 stmt。

    范围语义（对标 RuoYi 5 范围）：
      * ``ALL`` —— 不加条件，全部可见。
      * ``SELF`` —— ``owner_col == user_id``，仅本人归属。
      * ``SELF_DEPT`` —— ``dept_col == dept_id``，仅本部门；``dept_id`` 为 None
        时返回空结果（无部门用户不应看到部门数据，默认 deny）。
      * ``SELF_DEPT_AND_BELOW`` / ``CUSTOM_DEPT`` —— ``dept_col IN visible_dept_ids``；
        集合为空时返回空结果（默认 deny，不泄露）。

    ``dept_col`` / ``owner_col`` 是调用方（repository）传入的 SQLAlchemy 列。
    """
    match scope.scope_type:
        case ScopeType.ALL:
            return stmt
        case ScopeType.SELF:
            return stmt.where(owner_col == scope.user_id)
        case ScopeType.SELF_DEPT:
            if scope.dept_id is None:
                return stmt.where(false())
            return stmt.where(dept_col == scope.dept_id)
        case ScopeType.SELF_DEPT_AND_BELOW | ScopeType.CUSTOM_DEPT:
            if not scope.visible_dept_ids:
                return stmt.where(false())
            return stmt.where(dept_col.in_(scope.visible_dept_ids))
        case _:  # pragma: no cover —— 穷尽 5 范围，新增成员时 pyright 报错提醒
            assert_never(scope.scope_type)
