"""Post repository —— SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

除标准 CRUD 外，承载岗位绑定查询与写（镜像 role 域 ``user_roles``，岗位无 data_scope 故更简单）：
  * ``list_posts_for_user`` —— JOIN ``user_posts`` 取用户的全部岗位。
  * ``set_user_posts`` —— 全量替换绑定（先取 advisory lock 再先删后插，幂等）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

from sqlalchemy import ColumnElement, Select, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.pagination import SortColumn, SortExpr, ilike_contains
from admin_platform.domains.post.models import Post, UserPost
from admin_platform.domains.post.schemas import PostCreate, PostListQuery, PostUpdate


def _post_filters(query: PostListQuery) -> list[ColumnElement[bool]]:
    """把过滤 DTO 翻成 WHERE 条件列表（参数化，无字符串拼接）。list / count 共用 → WHERE 一致。"""
    conds: list[ColumnElement[bool]] = []
    if query.code:
        conds.append(ilike_contains(Post.code, query.code))
    if query.name:
        conds.append(ilike_contains(Post.name, query.name))
    if query.status is not None:
        conds.append(Post.status == query.status)
    return conds


# pg_advisory_xact_lock 的稳定 key —— 串行化 user_posts「先删后插」的全量替换（镜像 role 域
# F3 修复）：并发两请求替换同一目标时，避免最终落成两请求的并集 / 撞 uq_user_posts。事务级锁，
# 提交/回滚自动释放。取与 dept(478221) / role(478231-2) / menu(478241-2) 不同的值避免跨域互锁。
_USER_POSTS_LOCK_KEY = 478251  # 串行化 user_posts 替换


class PostRepository:
    # 排序 allowlist（防注入红线）：order_by 字符串只用作此字典 key 查 ORM Column，命中才排序。
    # 不在表内 → service 的 resolve_sort 抛 422，绝不把客户端字符串拼进 SQL。SORT_DEFAULT 沿用
    # 既有默认序（sort_order, id），保 offset 分页跨页稳定。
    SORT_ALLOWED: ClassVar[Mapping[str, SortColumn]] = {
        "id": Post.id,
        "sort_order": Post.sort_order,
        "created_at": Post.created_at,
    }
    SORT_DEFAULT: ClassVar[Sequence[SortExpr]] = [Post.sort_order, Post.id]
    # 显式 order_by 命中非唯一列时追加的稳定 tie-breaker（pk，唯一）——保 OFFSET 深分页不跨页跳行。
    SORT_TIE_BREAK: ClassVar[SortColumn] = Post.id

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _filtered(self, query: PostListQuery) -> Select[tuple[Post]]:
        return select(Post).where(*_post_filters(query))

    async def list_paginated(
        self, query: PostListQuery, page: int, size: int, *, order_by: Sequence[SortExpr]
    ) -> list[Post]:
        offset = (page - 1) * size
        stmt = self._filtered(query).order_by(*order_by).offset(offset).limit(size)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, query: PostListQuery) -> int:
        inner = self._filtered(query).subquery()
        result = await self._session.execute(select(func.count()).select_from(inner))
        return int(result.scalar_one())

    async def get(self, item_id: int) -> Post | None:
        return await self._session.get(Post, item_id)

    async def find_by_code(self, code: str) -> Post | None:
        """按 code 查找（唯一性预检用）。"""
        result = await self._session.execute(select(Post).where(Post.code == code).limit(1))
        return result.scalar_one_or_none()

    async def create(self, payload: PostCreate) -> Post:
        obj = Post(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, item_id: int, payload: PostUpdate) -> Post | None:
        obj = await self._session.get(Post, item_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 在 UPDATE 后过期；异步 session 下后续序列化
        # （PostRead 含时间戳）访问过期列会触发隐式刷新报错（Errata #7）。显式 refresh 取回新值。
        await self._session.refresh(obj)
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Post, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    # ---- 岗位绑定查询 / 写（全量替换，先删后插）-------------------------------

    async def list_posts_for_user(self, user_id: int) -> list[Post]:
        """用户拥有的岗位（JOIN ``user_posts``）。"""
        stmt = (
            select(Post)
            .join(UserPost, UserPost.post_id == Post.id)
            .where(UserPost.user_id == user_id)
            .order_by(Post.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_user_posts(self, user_id: int, post_ids: list[int]) -> None:
        """全量替换用户的岗位绑定（去重；空列表 = 解绑所有岗位）。

        先取事务级 advisory lock 串行化「先删后插」（镜像 role 域 F3 修复）：并发两请求替换
        同一/不同用户的绑定时，避免最终落成两请求的并集或撞 ``uq_user_posts``。提交/回滚
        自动释放锁。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_USER_POSTS_LOCK_KEY)
        )
        await self._session.execute(delete(UserPost).where(UserPost.user_id == user_id))
        await self._session.flush()
        for post_id in dict.fromkeys(post_ids):
            self._session.add(UserPost(user_id=user_id, post_id=post_id))
        await self._session.flush()

    async def list_existing_ids(self, ids: list[int]) -> set[int]:
        """返回 ``ids`` 中实际存在的 post 子集（绑定前 all-or-nothing 校验用；空入参返回空集）。"""
        if not ids:
            return set()
        result = await self._session.execute(select(Post.id).where(Post.id.in_(ids)))
        return {int(i) for i in result.scalars().all()}

    async def list_post_ids_for_user(self, user_id: int) -> list[int]:
        """用户已绑定的岗位 id（管理端回显用）。按 id 有序。"""
        stmt = (
            select(UserPost.post_id).where(UserPost.user_id == user_id).order_by(UserPost.post_id)
        )
        result = await self._session.execute(stmt)
        return [int(i) for i in result.scalars().all()]

    # ---- Excel 导入导出（P5）-------------------------------------------------

    async def list_existing_codes(self, codes: list[str]) -> set[str]:
        """返回 ``codes`` 中库内已存在的子集（导入前库内重复校验；空入参返回空集）。"""
        if not codes:
            return set()
        result = await self._session.execute(select(Post.code).where(Post.code.in_(codes)))
        return {str(c) for c in result.scalars().all()}

    async def bulk_create(self, payloads: list[PostCreate]) -> int:
        """批量插入（导入全有全无：调用方已做全量校验，此处单事务 flush）。"""
        for payload in payloads:
            self._session.add(Post(**payload.model_dump()))
        await self._session.flush()
        return len(payloads)

    async def list_for_export(self, *, limit: int) -> list[Post]:
        """全量导出（按 sort_order, id 有序；limit 用于超限检测，传 max+1）。"""
        stmt = select(Post).order_by(Post.sort_order, Post.id).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
