"""Dept repository — SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

树查询用 PostgreSQL recursive CTE（O1：邻接表存储 + 按需 CTE 展开）：
  * ``list_descendant_dept_ids`` —— 向下展开子孙（含自身），供「本部门及以下」/ 移动防环；
  * ``list_ancestor_dept_ids`` —— 向上回溯祖先（不含自身，root→parent 有序），供面包屑。
"""

from __future__ import annotations

from sqlalchemy import func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.authz.data_scope import apply_data_scope
from admin_platform.authz.scope import DataScope
from admin_platform.domains.dept.models import Dept
from admin_platform.domains.dept.schemas import DeptCreate, DeptUpdate

# pg_advisory_xact_lock 的稳定 key —— 串行化所有 dept 树写（移动/删除防并发成环）。
_DEPT_TREE_LOCK_KEY = 478221  # 任意固定 bigint，全仓 dept 树写共用
_MAX_DEPT_DEPTH = 64  # recursive CTE 深度兜底（实际深度 <10）；坏数据成环时防死循环


class DeptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(
        self, page: int, size: int, *, scope: DataScope | None = None
    ) -> list[Dept]:
        offset = (page - 1) * size
        stmt = select(Dept)
        if scope is not None:
            # dept 表无归属概念 → owner_col=None，SELF 段跳过（不退化成 Dept.id==user_id）。
            stmt = apply_data_scope(stmt, scope, dept_col=Dept.id, owner_col=None)
        stmt = stmt.offset(offset).limit(size).order_by(Dept.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, scope: DataScope | None = None) -> int:
        stmt = select(func.count()).select_from(Dept)
        if scope is not None:
            stmt = apply_data_scope(stmt, scope, dept_col=Dept.id, owner_col=None)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def acquire_tree_lock(self) -> None:
        """事务级 advisory lock，串行化 dept 树写（移动/删除防并发成环）。

        提交/回滚自动释放。配合锁内重新校验，关掉 ``_check_no_cycle`` 的 TOCTOU 窗口
        （两个并发移动 A→B、B→A 各自校验都过、提交后成环）。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_DEPT_TREE_LOCK_KEY)
        )

    async def get(self, dept_id: int) -> Dept | None:
        return await self._session.get(Dept, dept_id)

    async def find_by_code(self, code: str) -> Dept | None:
        """按 code 查找（唯一性预检用）。"""
        result = await self._session.execute(select(Dept).where(Dept.code == code).limit(1))
        return result.scalar_one_or_none()

    async def count_children(self, dept_id: int) -> int:
        """直接子部门数量（删除 RESTRICT 预检用）。"""
        result = await self._session.execute(
            select(func.count()).select_from(Dept).where(Dept.parent_id == dept_id)
        )
        return int(result.scalar_one())

    async def create(self, payload: DeptCreate) -> Dept:
        obj = Dept(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, dept_id: int, payload: DeptUpdate) -> Dept | None:
        obj = await self._session.get(Dept, dept_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 在 UPDATE 后被置为过期；异步 session 下
        # 后续序列化（DeptRead 含时间戳）访问过期列会触发隐式刷新报错（Errata #7 精神）。
        # 显式 refresh 把服务端计算的新值取回，避免隐式 IO。
        await self._session.refresh(obj)
        return obj

    async def delete(self, dept_id: int) -> bool:
        obj = await self._session.get(Dept, dept_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    async def list_descendant_dept_ids(self, dept_id: int) -> frozenset[int]:
        """递归向下，返回 ``dept_id`` 的全部子孙 id（**含自身**）。

        recursive CTE：base = 自身行；递归段按 ``parent_id == tree.id`` 连下一层。
        只按 ``parent_id`` 展开（不过滤 status，可见性过滤留更上层）。
        """
        tree = (
            select(Dept.id, literal(0).label("depth"))
            .where(Dept.id == dept_id)
            .cte("dept_descendants", recursive=True)
        )
        tree = tree.union_all(
            select(Dept.id, tree.c.depth + 1).where(
                Dept.parent_id == tree.c.id, tree.c.depth < _MAX_DEPT_DEPTH
            )
        )
        result = await self._session.execute(select(tree.c.id))
        return frozenset(int(row) for row in result.scalars().all())

    async def list_ancestor_dept_ids(self, dept_id: int) -> list[int]:
        """递归向上，返回 ``dept_id`` 的祖先 id 链（**不含自身**，root→直属父 有序）。

        recursive CTE 带 ``depth`` 计数：自身 depth=0，每向上一层 +1；最终按 depth 降序
        输出（root 在最前），剔除自身。供面包屑（service / api 组装展示）。
        """
        tree = (
            select(Dept.id, Dept.parent_id, literal(0).label("depth"))
            .where(Dept.id == dept_id)
            .cte("dept_ancestors", recursive=True)
        )
        tree = tree.union_all(
            select(Dept.id, Dept.parent_id, tree.c.depth + 1).where(Dept.id == tree.c.parent_id)
        )
        stmt = select(tree.c.id).where(tree.c.id != dept_id).order_by(tree.c.depth.desc())
        result = await self._session.execute(stmt)
        return [int(row) for row in result.scalars().all()]
