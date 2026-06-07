"""apply_data_scope —— 把 DataScope 翻译成 SQLAlchemy where 条件的纯函数（spec §4.2）。

声明式 + typed 上下文 + 显式 helper 三段式的「落地层」：repository 显式调用本函数，
把 DataScope（authz.scope）翻译成查询 where。安全默认 deny —— 部门范围但缺有效部门
信息（dept_id 为 None / visible_dept_ids 为空）时返回空结果，不泄露数据。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, false, or_

from admin_platform.authz.scope import DataScope, ScopeType


def apply_data_scope(
    stmt: Select, scope: DataScope, *, dept_col: Any, owner_col: Any | None = None
) -> Select:
    """按数据权限范围给 ``stmt`` 追加 where 并返回新 stmt（O2 归一后语义）。

    ``DataScope`` 已是多角色**归一**结果（``get_effective_data_scope`` 折叠多角色）：
      * ``scope_type == ALL`` —— 任一角色全部权限 → 不加条件。
      * 否则按归一字段组合（最多两段 OR，对标 RuoYi 多角色并集）：
        - ``visible_dept_ids`` 非空 → ``dept_col IN (...)``（部门范围并集：本部门/及以下/自定义）。
        - ``include_self``（或单角色 ``SELF``）且 ``owner_col`` 非 None → ``owner_col == user_id``。
        - 两段都有 → ``dept_col IN (...) OR owner_col == user_id``。
        - 两段都没有 → ``false()`` 默认 deny（无可见部门 + 无 SELF / 无 owner_col，不泄露）。

    ``owner_col=None`` 用于**无归属概念的资源**（如 dept 表本身）：此时 ``SELF`` 段跳过，
    避免把 ``SELF`` 误解成 ``pk == user_id``（Codex O2 review 揪出的隐患）。
    """
    if scope.scope_type is ScopeType.ALL:
        return stmt
    conditions = []
    if scope.visible_dept_ids:
        conditions.append(dept_col.in_(scope.visible_dept_ids))
    wants_self = scope.include_self or scope.scope_type is ScopeType.SELF
    if wants_self and owner_col is not None:
        conditions.append(owner_col == scope.user_id)
    if not conditions:
        return stmt.where(false())
    if len(conditions) == 1:
        return stmt.where(conditions[0])
    return stmt.where(or_(*conditions))
