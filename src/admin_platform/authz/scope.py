"""数据权限值对象 —— RuoYi 5 范围枚举（ScopeType）+ 不可变上下文（DataScope）。

对标 RuoYi 数据权限的 5 个范围（spec §4 data_scope）。本模块是纯 Python 值对象：
不依赖 SQLAlchemy / FastAPI，不做任何 IO。由权限依赖在解析 ``CurrentUser`` 后构造，
repository 的 ``apply_data_scope`` 落地 SQL 时消费（声明式 + typed 上下文 + 显式 helper 三段式）。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ScopeType(enum.Enum):
    """数据权限范围（对标 RuoYi 5 范围）。"""

    ALL = "all"  # 全部数据权限：不追加任何部门/归属过滤
    CUSTOM_DEPT = "custom_dept"  # 自定义部门：仅可见 visible_dept_ids 指定的部门
    SELF_DEPT = "self_dept"  # 本部门：仅可见用户所属 dept_id 的数据
    SELF_DEPT_AND_BELOW = "self_dept_and_below"  # 本部门及以下：本部门 + 所有子孙部门
    SELF = "self"  # 仅本人：仅可见归属为本人（user_id）的数据


@dataclass(frozen=True)
class DataScope:
    """单次请求解析出的数据权限上下文（不可变值对象）。

    字段语义：
      * ``scope_type`` —— 生效的数据权限范围（多角色合并语义见 spec §11 O2）。
      * ``user_id`` —— 当前用户 id，供 ``SELF`` 范围按归属人过滤。
      * ``dept_id`` —— 当前用户所属部门 id，供 ``SELF_DEPT`` / ``SELF_DEPT_AND_BELOW`` 过滤；
        无部门时为 ``None``。
      * ``visible_dept_ids`` —— 可见部门 id 集合，供 ``CUSTOM_DEPT``（自定义部门）
        与 ``SELF_DEPT_AND_BELOW``（本部门 + 子孙）展开后的过滤；默认空。
    """

    scope_type: ScopeType
    user_id: int
    dept_id: int | None = None
    visible_dept_ids: frozenset[int] = frozenset()
